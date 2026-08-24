from __future__ import annotations

import itertools
import uuid
from collections import Counter
from typing import TYPE_CHECKING, Any

from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from app.db.models import (
    Commit,
    Dependency,
    Finding,
    ModuleCoupling,
    Severity,
    Subsystem,
    SubsystemMember,
)
from app.db.paths import load_path_map
from app.engines.base import Engine
from app.engines.coupling import CONFIDENCE_SCORE, FALLBACK_MIN_SHARED_REVS, confidence_hint
from app.engines.overlay import HIGH_DEGREE
from app.engines.signature import finding_signature

if TYPE_CHECKING:
    from app.engines.context import RunContext

# ---- Config (module-level, documented; not per-caller knobs) ----

MAX_DIR_DEPTH = 3
"""HEURISTIC: a directory "module" is the file's parent directory truncated
to at most this many leading segments (``a/b/c/d/e.py`` -> ``a/b/c``).
Repositories vary wildly in nesting depth; truncation keeps modules
comparable in size across repos instead of the deepest-nested repo producing
hundreds of nearly-unique single-file "modules"."""

MAX_MODULE_CHANGESET = 10
"""A different, SMALLER cap than file-level coupling's MAX_CHANGESET_SIZE
(30, app/engines/coupling.py) -- deliberately so, not a typo. A commit
touching 10 or more DISTINCT MODULES (not files) is almost certainly a
repo-wide reformat, a mass rename, or a dependency-lockfile bump that
happens to touch many directories, not a real signal that those modules are
functionally related. Ten files in ONE module is completely ordinary and
never dropped by this cap -- it only fires on module BREADTH."""

MIN_SHARED_REVS_MODULE = 5
MIN_COUPLING_DEGREE_MODULE = 0.30
"""Matches file-level coupling's MIN_SHARED_REVS/MIN_COUPLING_DEGREE exactly
(app/engines/coupling.py) -- same reasoning, same code-maat-derived defaults,
just applied to module-granularity changesets instead of file changesets."""


def _directory_module(path: str) -> str:
    segments = path.split("/")[:-1]  # drop the filename itself
    truncated = segments[:MAX_DIR_DEPTH]
    return "/".join(truncated) if truncated else "(root)"


def _module_changesets(
    raw_changesets: list[list[int]], module_of_path: dict[int, str], max_module_changeset: int
) -> list[frozenset[str]]:
    """Session 04 Part C step 2/3: collapses each commit's file-level
    changeset to the SET of distinct modules it touched (a commit touching 5
    files in one module counts that module once -- the whole point of using
    a set), then drops any commit whose MODULE changeset exceeds
    ``max_module_changeset`` (see MAX_MODULE_CHANGESET above). A path not
    present in ``module_of_path`` (e.g. a deleted file some historical commit
    still references) is silently excluded from that commit's module set,
    never guessed at.
    """
    changesets: list[frozenset[str]] = []
    for path_ids in raw_changesets:
        modules = frozenset(module_of_path[pid] for pid in path_ids if pid in module_of_path)
        if not modules:
            continue
        if len(modules) <= max_module_changeset:
            changesets.append(modules)
    return changesets


def _module_pair_stats(
    changesets: list[frozenset[str]],
) -> tuple[Counter[tuple[str, str]], Counter[str]]:
    shared_revs: Counter[tuple[str, str]] = Counter()
    module_revs: Counter[str] = Counter()
    for modules in changesets:
        sorted_modules = sorted(modules)
        module_revs.update(sorted_modules)
        # sorted_modules guarantees combinations() always keys a given pair
        # the same way regardless of which commit it came from -- same
        # discipline as app/engines/coupling.py::_pair_stats.
        shared_revs.update(itertools.combinations(sorted_modules, 2))
    return shared_revs, module_revs


def _build_module_rows(
    repo_id: uuid.UUID,
    run_id: uuid.UUID,
    granularity: str,
    shared_revs: Counter[tuple[str, str]],
    module_revs: Counter[str],
    min_shared_revs: int,
    subsystem_id_by_label: dict[str, int],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for (module_a, module_b), shared in shared_revs.items():
        if shared < min_shared_revs:
            continue

        revs_a, revs_b = module_revs[module_a], module_revs[module_b]

        # THE FORMULA IS LOCKED AND IDENTICAL TO FILE-LEVEL COUPLING:
        #   coupling_degree(M, N) = shared_revs(M, N) / min(revs(M), revs(N))
        # Computed HERE, directly from module-granularity commit changesets,
        # exactly like file-level coupling is computed directly from file
        # changesets (app/engines/coupling.py). DO NOT "optimize" this by
        # summing/averaging/maxing the underlying FILE-PAIR coupling_degree
        # values for file pairs that happen to cross these two modules --
        # that is the obvious-looking WRONG implementation. It is
        # mathematically invalid (coupling_degree is a ratio against each
        # file's own individual revision count, not additive across files),
        # and it silently produces plausible-looking, meaningless numbers.
        # See tests/test_module_coupling_engine.py for a fixture that
        # demonstrates the two approaches give different answers.
        coupling_degree = shared / min(revs_a, revs_b)
        if coupling_degree < MIN_COUPLING_DEGREE_MODULE:
            continue

        avg_revs = (revs_a + revs_b) / 2
        rows.append(
            {
                "analysis_run_id": run_id,
                "repo_id": repo_id,
                "granularity": granularity,
                "module_a": module_a,
                "module_b": module_b,
                "subsystem_a_id": (
                    subsystem_id_by_label.get(module_a) if granularity == "subsystem" else None
                ),
                "subsystem_b_id": (
                    subsystem_id_by_label.get(module_b) if granularity == "subsystem" else None
                ),
                "shared_revs": shared,
                "coupling_degree": coupling_degree,
                "avg_revs": avg_revs,
            }
        )
    return rows


def _compute_one_granularity(
    repo_id: uuid.UUID,
    run_id: uuid.UUID,
    granularity: str,
    raw_changesets: list[list[int]],
    module_of_path: dict[int, str],
    subsystem_id_by_label: dict[str, int],
) -> list[dict[str, Any]]:
    """Session 04 Part C step 5: tries the normal MIN_SHARED_REVS_MODULE
    floor first; if that produces nothing at all, retries with the SAME
    lowered floor the file-level engine uses (FALLBACK_MIN_SHARED_REVS,
    reused rather than a redeclared duplicate constant) -- identical
    small-repo-fallback mechanism to app/engines/coupling.py::compute_coupling,
    just applied at module grain."""
    changesets = _module_changesets(raw_changesets, module_of_path, MAX_MODULE_CHANGESET)
    if not changesets:
        return []

    shared_revs, module_revs = _module_pair_stats(changesets)

    rows = _build_module_rows(
        repo_id,
        run_id,
        granularity,
        shared_revs,
        module_revs,
        MIN_SHARED_REVS_MODULE,
        subsystem_id_by_label,
    )
    if rows:
        return rows

    return _build_module_rows(
        repo_id,
        run_id,
        granularity,
        shared_revs,
        module_revs,
        FALLBACK_MIN_SHARED_REVS,
        subsystem_id_by_label,
    )


def is_module_coupling_low_confidence(
    run_id: uuid.UUID, granularity: str, session: Session
) -> bool:
    """True when module-level pairs for this ``(run_id, granularity)`` were
    computed under the lowered small-repo fallback floor, inferred CHEAPLY
    from the persisted rows themselves (one indexed existence query) rather
    than a separate stored flag -- Part A's schema has no low-confidence
    column on ``module_coupling``/``analysis_runs`` for this, and adding one
    wasn't specified.

    The inference is exact, not a heuristic guess: ``_compute_one_granularity``
    only ever falls back to ``FALLBACK_MIN_SHARED_REVS`` when the NORMAL
    ``MIN_SHARED_REVS_MODULE`` floor produced ZERO rows for the whole repo --
    so a persisted row with ``shared_revs < MIN_SHARED_REVS_MODULE`` can only
    exist because the fallback pass ran, and when it did, EVERY row for this
    (run_id, granularity) came from that same fallback pass (identical
    binary trigger to app/engines/coupling.py::compute_coupling, which this
    mirrors exactly -- see that module's ``FALLBACK_MIN_SHARED_REVS``
    docstring).
    """
    exists = session.scalar(
        select(ModuleCoupling.id)
        .where(
            ModuleCoupling.analysis_run_id == run_id,
            ModuleCoupling.granularity == granularity,
            ModuleCoupling.shared_revs < MIN_SHARED_REVS_MODULE,
        )
        .limit(1)
    )
    return exists is not None


_SEVERITY_WEIGHT = {Severity.high: 2, Severity.med: 1, Severity.low: 0}

SUBSYSTEM_COUPLING_FINDING_THRESHOLD = 0.5
MAX_MODULE_COUPLING_FINDINGS = 5


def _subsystem_coupling_findings(
    repo_id: uuid.UUID,
    run_id: uuid.UUID,
    subsystem_rows: list[dict[str, Any]],
    structural_subsystem_pairs: set[frozenset[int]],
    low_confidence: bool,
) -> list[dict[str, Any]]:
    """Session 04 Part C: the most actionable form of the flagship insight
    at architectural scale -- two subsystems that look structurally
    independent (no import between ANY of their member files) but that
    change together strongly enough to prove they aren't. Category
    ``hidden_dependency`` (same category file-level hidden dependencies use,
    per the session prompt), capped at MAX_MODULE_COUPLING_FINDINGS."""
    candidates: list[dict[str, Any]] = []
    for row in subsystem_rows:
        if row["coupling_degree"] < SUBSYSTEM_COUPLING_FINDING_THRESHOLD:
            continue
        pair_key = frozenset((row["subsystem_a_id"], row["subsystem_b_id"]))
        if pair_key in structural_subsystem_pairs:
            continue  # a real structural edge already accounts for this pair

        severity = Severity.high if row["coupling_degree"] >= HIGH_DEGREE else Severity.med
        hint = confidence_hint(row["shared_revs"], low_confidence)
        candidates.append(
            {
                "analysis_run_id": run_id,
                "repo_id": repo_id,
                "category": "hidden_dependency",
                "severity": severity,
                "confidence": CONFIDENCE_SCORE[hint],
                "path_id": None,
                "evidence_sha": None,
                "title": f"Hidden dependency: {row['module_a']} <-> {row['module_b']} (subsystems)",
                "detail": (
                    f"These subsystems change together in {row['shared_revs']} commits "
                    f"(coupling_degree={row['coupling_degree']:.2f}) but no file in either "
                    "imports a file in the other."
                ),
                "_sort_degree": row["coupling_degree"],
                "signature": finding_signature(
                    "hidden_dependency", "|".join(sorted((row["module_a"], row["module_b"])))
                ),
            }
        )

    candidates.sort(key=lambda f: f["_sort_degree"], reverse=True)
    candidates = candidates[:MAX_MODULE_COUPLING_FINDINGS]
    for rank, f in enumerate(candidates):
        f["rank"] = rank
        del f["_sort_degree"]
    return candidates


class ModuleCouplingEngine(Engine):
    """Extends the LOCKED file-level coupling formula to directory and
    subsystem granularity (session 04, Part C -- master-context.md sec 5's
    module-level-coupling extension). Must run AFTER ``SubsystemEngine`` in
    the "subsystems" stage (both share one stage, see app/jobs/stages.py) --
    the subsystem-granularity pass reads ``subsystem_members``/``subsystems``
    rows that engine just wrote for this SAME run_id.
    """

    def run(self, ctx: RunContext, session: Session) -> dict[str, Any]:
        repo_id, run_id = ctx.repo_id, ctx.run_id

        raw_changesets = session.scalars(
            select(Commit.changed_path_ids).where(Commit.repo_id == repo_id)
        ).all()
        raw_changesets = [list(ids) for ids in raw_changesets]

        path_map = load_path_map(repo_id, session)
        directory_of_path = {path_id: _directory_module(path) for path_id, path in path_map.items()}

        subsystem_rows = session.execute(
            select(SubsystemMember.path_id, Subsystem.id, Subsystem.label)
            .join(Subsystem, Subsystem.id == SubsystemMember.subsystem_id)
            .where(Subsystem.analysis_run_id == run_id)
        ).all()
        subsystem_of_path: dict[int, str] = {}
        subsystem_id_by_label: dict[str, int] = {}
        subsystem_id_of_path: dict[int, int] = {}
        for path_id, subsystem_id, label in subsystem_rows:
            subsystem_of_path[path_id] = label
            subsystem_id_by_label[label] = subsystem_id
            subsystem_id_of_path[path_id] = subsystem_id

        directory_rows = _compute_one_granularity(
            repo_id, run_id, "directory", raw_changesets, directory_of_path, {}
        )
        subsystem_module_rows = _compute_one_granularity(
            repo_id, run_id, "subsystem", raw_changesets, subsystem_of_path, subsystem_id_by_label
        )

        all_rows = directory_rows + subsystem_module_rows
        if all_rows:
            session.execute(insert(ModuleCoupling), all_rows)

        # Read back via the same cheap, exact inference the API uses (see
        # is_module_coupling_low_confidence's docstring) rather than
        # threading a second return value out of _compute_one_granularity --
        # one code path decides "was this low-confidence", used identically
        # here and at request time.
        directory_low_confidence = is_module_coupling_low_confidence(run_id, "directory", session)
        subsystem_low_confidence = is_module_coupling_low_confidence(run_id, "subsystem", session)

        structural_subsystem_pairs: set[frozenset[int]] = set()
        for from_path_id, to_path_id in session.execute(
            select(Dependency.from_path_id, Dependency.to_path_id).where(
                Dependency.repo_id == repo_id
            )
        ).all():
            a = subsystem_id_of_path.get(from_path_id)
            b = subsystem_id_of_path.get(to_path_id)
            if a is not None and b is not None and a != b:
                structural_subsystem_pairs.add(frozenset((a, b)))

        findings = _subsystem_coupling_findings(
            repo_id,
            run_id,
            subsystem_module_rows,
            structural_subsystem_pairs,
            subsystem_low_confidence,
        )
        if findings:
            session.execute(insert(Finding), findings)

        return {
            "directory_pairs": len(directory_rows),
            "subsystem_pairs": len(subsystem_module_rows),
            "directory_low_confidence": directory_low_confidence,
            "subsystem_low_confidence": subsystem_low_confidence,
            "hidden_subsystem_couplings_found": len(findings),
        }
