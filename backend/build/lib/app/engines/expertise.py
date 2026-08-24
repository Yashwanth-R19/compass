"""Degree-of-Authorship (DOA), expert selection, and the knowledge map
(session 05, Part C).

DOA is implemented EXACTLY as published -- Fernandez-Ramil, Izquierdo-
Cortazar & Mens, as used by Avelino, Passos, Hora & Valente ("A Novel
Approach for Estimating Truck Factors", ICPC 2016) to compute per-file
expertise for truck-factor analysis:

    DOA(d, f) = 3.293 + 1.098*FA + 0.164*DL - 0.321*ln(1 + AC)

where, for developer ``d`` and file ``f``:
    FA = 1 if d authored the FIRST commit that created f, else 0
    DL = number of changes d has made to f
    AC = number of changes all OTHER developers have made to f

``DOA_BASE``/``DOA_FA_WEIGHT``/``DOA_DL_WEIGHT``/``DOA_AC_WEIGHT`` and the
two expert thresholds below are CITED constants from the literature, not
tuned or invented by Compass -- do not treat them as HEURISTIC
(plan/RULES.md sec 3: heuristic means "we chose this value and can defend
why"; these values were never Compass's to choose). Do not adjust them for
a "better-looking" result on any particular repo.

**Judgement call, documented (session 05):** bots are excluded from DOA
entirely, not just from being scored as a candidate developer -- a bot's
commits are dropped from the DL/AC/FA history a file is judged against, as
if they never happened from an authorship-modeling point of view. This is
the more conservative reading of "exclude bot identities... entirely"
(session 05 Part A/C) over the alternative (count bot changes toward AC but
never score a bot as `d`); it also means an automation-heavy file's human
DOA scores reflect only human activity, not diluted by e.g. a dependency-bump
bot's commit volume.

**Known simplification, deliberate (session 05, Known Hazard #6):** a
commit has exactly one author in this schema (``commits.author_name``/
``author_email``) -- Compass does not model co-authors, so "the single
author of the first commit touching a file" is always well-defined, never
ambiguous.

Display/privacy rules (plan/RULES.md sec 11, session 05 Part F -- not
optional, apply to this module and to every endpoint reading its output):
only what's already in the repository's public commit metadata, no email
ever returned unmasked (``app/analysis/identities.py::mask_email``), and
every user-facing word is knowledge-distribution framing ("principal
author", "expert", "knowledge concentration") -- never "productivity",
"top performer", "contribution score", or any ranking that reads as an
employee evaluation.
"""

from __future__ import annotations

import math
import uuid
from collections import Counter
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from app.analysis.identities import is_bot_name, most_frequent_recent, resolve_identities
from app.analysis.staleness import is_stale_relative_to_repo
from app.db.models import (
    Commit,
    Contributor,
    File,
    FileExpertise,
    FileMetrics,
    Finding,
    Severity,
    Subsystem,
    SubsystemMember,
)
from app.db.paths import load_path_map
from app.engines.base import Engine
from app.engines.signature import finding_signature

if TYPE_CHECKING:
    from app.engines.context import RunContext

# ---- The published DOA formula -- CITED, not HEURISTIC (see module docstring) ----

DOA_BASE = 3.293
DOA_FA_WEIGHT = 1.098
DOA_DL_WEIGHT = 0.164
DOA_AC_WEIGHT = 0.321

EXPERT_DOA_NORMALIZED_THRESHOLD = 0.75
"""CITED (Fernandez-Ramil et al. / Avelino et al.), not tuned: a developer
must reach at least 75% of the file's own maximum DOA to count as an
expert."""

EXPERT_DOA_ABSOLUTE_THRESHOLD = DOA_BASE
"""CITED, not tuned: 3.293 is the published DOA of a developer whose entire
recorded relationship to the file is having created it -- the absolute
floor an expert must also clear (independent of the normalized threshold),
so a file with only weak, thin history never manufactures a false expert
purely from a lopsided normalization against other weak candidates."""

STALE_AFTER_DAYS = 180
"""A contributor is stale once their last commit is this many days before
the REPOSITORY's own most recent commit -- never `datetime.now()`, see
``app/analysis/staleness.py`` (session 05 Known Hazard #1)."""

MAX_EXPERTS_PER_FILE = 5
"""Storage cap (session 05 Part B): only the top-N contributors per file are
persisted to ``file_expertise``. Applied AFTER ranking/normalizing over the
full candidate set for that file, never before (Known Hazard #5) -- see
``_compute_doa_per_file``."""

MAX_KNOWLEDGE_FINDINGS = 8
"""Anti-alert-fatigue cap (plan/RULES.md sec 12), shared across all three
finding kinds this engine emits, same discipline as every other
finding-emitting engine in this codebase."""

ORPHANED_KNOWLEDGE_RISK_QUARTILE = 0.75
"""HEURISTIC (plan/RULES.md sec 3): "top quartile of risk_score" for the
orphaned-knowledge finding -- the 75th percentile of this run's own
risk_score distribution, computed directly (not via BaselineProvider, since
this is a within-run relative cutoff, not a normalization of a raw
signal)."""

SINGLE_EXPERT_SUBSYSTEM_RATIO = 0.70
KNOWLEDGE_CONCENTRATION_RATIO = 0.50
"""Session 05 Part C thresholds for the other two finding kinds, given
directly by the session spec (not independently chosen HEURISTIC values,
but not literature-cited either -- product thresholds)."""


def _percentile(sorted_values: list[float], fraction: float) -> float:
    """Simple, deterministic percentile over an already-sorted list -- no
    external stats dependency, no exception on small inputs (unlike
    ``statistics.quantiles``, which raises below 2 data points)."""
    if not sorted_values:
        return 0.0
    idx = int(fraction * (len(sorted_values) - 1))
    return sorted_values[idx]


def _load_commit_rows(repo_id: uuid.UUID, session: Session) -> Sequence[Any]:
    return session.execute(
        select(
            Commit.id,
            Commit.sha,
            Commit.author_name,
            Commit.author_email,
            Commit.committed_at,
            Commit.changed_path_ids,
            Commit.added_lines,
            Commit.deleted_lines,
        )
        .where(Commit.repo_id == repo_id)
        .order_by(Commit.committed_at.asc(), Commit.id.asc())
    ).all()


def _build_contributor_meta(
    commits: Sequence[Any], identity_map: dict[tuple[str, str], int]
) -> dict[int, dict[str, Any]]:
    """Per-identity aggregate stats (Part C: commit_count, lines
    added/deleted, first/last commit, active_days) plus canonical
    name/email/aliases/is_bot -- computed from ALL commits (bots included;
    a bot still gets a contributor row, just excluded from expertise --
    see module docstring)."""
    commits_by_identity: dict[int, list[Any]] = {}
    aliases_by_identity: dict[int, set[tuple[str, str]]] = {}
    for c in commits:
        iid = identity_map[(c.author_name, c.author_email)]
        commits_by_identity.setdefault(iid, []).append(c)
        aliases_by_identity.setdefault(iid, set()).add((c.author_name, c.author_email))

    repo_last_commit_at = commits[-1].committed_at  # commits is sorted ascending

    meta: dict[int, dict[str, Any]] = {}
    for iid, group in commits_by_identity.items():
        aliases = sorted(aliases_by_identity[iid])
        canonical_name = most_frequent_recent([(c.author_name, c.committed_at) for c in group])
        canonical_email = most_frequent_recent([(c.author_email, c.committed_at) for c in group])
        is_bot = any(is_bot_name(name) for name, _ in aliases)
        last_commit_at = group[-1].committed_at
        meta[iid] = {
            "aliases": aliases,
            "canonical_name": canonical_name,
            "canonical_email": canonical_email,
            "is_bot": is_bot,
            "commit_count": len(group),
            "lines_added": sum(sum(c.added_lines) for c in group),
            "lines_deleted": sum(sum(c.deleted_lines) for c in group),
            "first_commit_at": group[0].committed_at,
            "last_commit_at": last_commit_at,
            "active_days": len({c.committed_at.date() for c in group}),
            "is_stale": is_stale_relative_to_repo(
                last_commit_at, repo_last_commit_at, STALE_AFTER_DAYS
            ),
        }

    # Deterministic rank: commit_count desc, canonical_name asc (activity,
    # never a "contribution score" -- plan/RULES.md sec 11.3 / Known Hazard #8).
    order = sorted(
        meta.keys(), key=lambda iid: (-meta[iid]["commit_count"], meta[iid]["canonical_name"])
    )
    for rank, iid in enumerate(order):
        meta[iid]["rank"] = rank

    return meta


def _compute_doa_per_file(
    commits: Sequence[Any],
    identity_map: dict[tuple[str, str], int],
    contributor_meta: dict[int, dict[str, Any]],
    existing_path_ids: set[int],
) -> tuple[
    dict[int, list[tuple[int, float, float, int, Any, str]]],  # path_id -> ranked, truncated rows
    Counter[int],  # is_expert count per identity (any file, sole or not)
    dict[int, int | None],  # path_id -> sole expert identity id, or None
]:
    """Builds, for every existing (non-deleted) file with at least one
    non-bot developer touching it, the ranked/truncated list of
    (identity_id, doa, doa_normalized, changes, last_touched_at, last_sha)
    tuples -- ranking and normalizing over the FULL candidate set first,
    truncating to MAX_EXPERTS_PER_FILE only at the very end (Known Hazard
    #5).
    """
    dl_counts: dict[int, dict[int, int]] = {}
    first_author_by_path: dict[int, int] = {}
    last_touch: dict[tuple[int, int], tuple[Any, str]] = {}

    for c in commits:  # chronological -- see _load_commit_rows
        iid = identity_map[(c.author_name, c.author_email)]
        if contributor_meta[iid]["is_bot"]:
            continue
        for path_id in sorted(set(c.changed_path_ids)):
            if path_id not in first_author_by_path:
                first_author_by_path[path_id] = iid
            file_counts = dl_counts.setdefault(path_id, {})
            file_counts[iid] = file_counts.get(iid, 0) + 1
            last_touch[(path_id, iid)] = (c.committed_at, c.sha)

    ranked_by_path: dict[int, list[tuple[int, float, float, int, Any, str]]] = {}
    expert_counts: Counter[int] = Counter()
    sole_expert_by_path: dict[int, int | None] = {}

    for path_id, per_dev in dl_counts.items():
        if path_id not in existing_path_ids:
            continue
        total = sum(per_dev.values())
        candidates: list[tuple[int, float]] = []
        for iid, dl in per_dev.items():
            fa = 1 if first_author_by_path[path_id] == iid else 0
            ac = total - dl
            doa = (
                DOA_BASE
                + DOA_FA_WEIGHT * fa
                + DOA_DL_WEIGHT * dl
                - DOA_AC_WEIGHT * math.log(1 + ac)
            )
            candidates.append((iid, doa))

        max_doa = max(doa for _, doa in candidates)
        normalized = [(iid, doa, (doa / max_doa if max_doa else 0.0)) for iid, doa in candidates]
        # Rank over the FULL set, THEN truncate (Known Hazard #5). Tie-break
        # deterministically by canonical_name asc.
        normalized.sort(key=lambda t: (-t[2], contributor_meta[t[0]]["canonical_name"]))
        top = normalized[:MAX_EXPERTS_PER_FILE]

        rows: list[tuple[int, float, float, int, Any, str]] = []
        experts_this_file: list[int] = []
        for iid, doa, doa_norm in top:
            is_expert = (
                doa_norm >= EXPERT_DOA_NORMALIZED_THRESHOLD and doa >= EXPERT_DOA_ABSOLUTE_THRESHOLD
            )
            last_touched_at, last_sha = last_touch[(path_id, iid)]
            rows.append((iid, doa, doa_norm, per_dev[iid], last_touched_at, last_sha))
            if is_expert:
                expert_counts[iid] += 1
                experts_this_file.append(iid)
        ranked_by_path[path_id] = rows
        sole_expert_by_path[path_id] = experts_this_file[0] if len(experts_this_file) == 1 else None

    return ranked_by_path, expert_counts, sole_expert_by_path


_SEVERITY_WEIGHT = {Severity.high: 2, Severity.med: 1, Severity.low: 0}


def _knowledge_findings(
    repo_id: uuid.UUID,
    run_id: uuid.UUID,
    session: Session,
    contributor_meta: dict[int, dict[str, Any]],
    sole_expert_by_path: dict[int, int | None],
    expert_counts: Counter[int],
    total_files_with_expertise: int,
    path_map: dict[int, str],
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []

    # --- orphaned_knowledge: sole expert is stale, file is top-quartile risk ---
    risk_rows = session.execute(
        select(FileMetrics.path_id, FileMetrics.risk_score).where(
            FileMetrics.analysis_run_id == run_id
        )
    ).all()
    risk_by_path = {row.path_id: row.risk_score for row in risk_rows}
    risk_threshold = _percentile(sorted(risk_by_path.values()), ORPHANED_KNOWLEDGE_RISK_QUARTILE)

    for path_id, sole_iid in sole_expert_by_path.items():
        if sole_iid is None or not contributor_meta[sole_iid]["is_stale"]:
            continue
        risk_score = risk_by_path.get(path_id)
        if risk_score is None or risk_score < risk_threshold:
            continue
        last_touched_at = contributor_meta[sole_iid]["last_commit_at"]
        candidates.append(
            {
                "analysis_run_id": run_id,
                "repo_id": repo_id,
                "category": "knowledge",
                "severity": Severity.high,
                "confidence": min(1.0, risk_score),
                "path_id": path_id,
                "evidence_sha": None,
                "title": f"Orphaned knowledge: {path_map[path_id]}",
                "detail": (
                    f"The sole expert for this file ({contributor_meta[sole_iid]['canonical_name']}, "
                    f"last active {last_touched_at.date().isoformat()}) has had no activity in over "
                    f"{STALE_AFTER_DAYS} days, and this file is in the top quartile of risk."
                ),
                "signature": finding_signature("knowledge", path_map[path_id]),
            }
        )

    # --- single_expert_subsystem: one contributor sole-experts >70% of a subsystem ---
    subsystem_rows = session.execute(
        select(Subsystem.label, SubsystemMember.path_id)
        .join(SubsystemMember, SubsystemMember.subsystem_id == Subsystem.id)
        .where(Subsystem.analysis_run_id == run_id)
    ).all()
    members_by_label: dict[str, list[int]] = {}
    for label, path_id in subsystem_rows:
        members_by_label.setdefault(label, []).append(path_id)

    for label, path_ids in members_by_label.items():
        total_files = len(path_ids)
        if total_files == 0:
            continue
        sole_counts: Counter[int] = Counter()
        for path_id in path_ids:
            sole_iid = sole_expert_by_path.get(path_id)
            if sole_iid is not None:
                sole_counts[sole_iid] += 1
        if not sole_counts:
            continue
        top_iid, top_count = sole_counts.most_common(1)[0]
        ratio = top_count / total_files
        if ratio > SINGLE_EXPERT_SUBSYSTEM_RATIO:
            candidates.append(
                {
                    "analysis_run_id": run_id,
                    "repo_id": repo_id,
                    "category": "knowledge",
                    "severity": Severity.high,
                    "confidence": min(1.0, ratio),
                    "path_id": None,
                    "evidence_sha": None,
                    "title": f"Single-expert subsystem: {label}",
                    "detail": (
                        f"{contributor_meta[top_iid]['canonical_name']} is the sole expert for "
                        f"{ratio:.0%} of files in the {label} subsystem -- knowledge here is "
                        "concentrated in one person."
                    ),
                    "signature": finding_signature("knowledge", f"single_expert_subsystem:{label}"),
                }
            )

    # --- knowledge_concentration: one contributor is an expert for >50% of all files ---
    if total_files_with_expertise > 0 and expert_counts:
        top_iid, top_count = expert_counts.most_common(1)[0]
        ratio = top_count / total_files_with_expertise
        if ratio > KNOWLEDGE_CONCENTRATION_RATIO:
            candidates.append(
                {
                    "analysis_run_id": run_id,
                    "repo_id": repo_id,
                    "category": "knowledge",
                    "severity": Severity.med,
                    "confidence": min(1.0, ratio),
                    "path_id": None,
                    "evidence_sha": None,
                    "title": "Knowledge concentration",
                    "detail": (
                        f"{contributor_meta[top_iid]['canonical_name']} is the principal expert for "
                        f"{ratio:.0%} of files with an identified expert in this repository."
                    ),
                    "signature": finding_signature("knowledge", "repo"),
                }
            )

    candidates.sort(key=lambda f: (_SEVERITY_WEIGHT[f["severity"]], f["confidence"]), reverse=True)
    candidates = candidates[:MAX_KNOWLEDGE_FINDINGS]
    for rank, f in enumerate(candidates):
        f["rank"] = rank
    return candidates


class ExpertiseEngine(Engine):
    """Computes contributor identities, per-file Degree-of-Authorship, and
    knowledge-concentration findings (session 05, Part C). Must run AFTER
    ``RiskEngine`` (reads ``file_metrics.risk_score`` for the
    orphaned-knowledge finding) and after ``SubsystemEngine`` (reads
    subsystem membership for the single-expert-subsystem finding) -- see
    ``app/jobs/stages.py``'s "knowledge" stage, which runs this before
    ``TruckFactorEngine`` in the same stage (that engine reads the
    ``file_expertise``/``contributors`` rows this one just wrote).
    """

    def run(self, ctx: RunContext, session: Session) -> dict[str, Any]:
        repo_id, run_id = ctx.repo_id, ctx.run_id

        commits = _load_commit_rows(repo_id, session)
        if not commits:
            # run_ingestion_job skips the whole "knowledge" stage on zero
            # commits (Part D degenerate case) -- this branch only guards
            # ExpertiseEngine's own compute_* helper against being called
            # directly (tests, future callers) with an empty repo.
            return {"contributors": 0, "files_scored": 0, "findings_emitted": 0}

        identity_map = resolve_identities([(c.author_name, c.author_email) for c in commits])
        contributor_meta = _build_contributor_meta(commits, identity_map)

        bot_commit_count = sum(m["commit_count"] for m in contributor_meta.values() if m["is_bot"])

        # Persist contributors in rank order, one row at a time (matches
        # SubsystemEngine's insert-then-RETURNING pattern) -- collects the
        # DB-assigned id for each identity so file_expertise rows below can
        # FK to it.
        contributor_id_by_identity: dict[int, int] = {}
        ordered_identities = sorted(
            contributor_meta.keys(), key=lambda iid: contributor_meta[iid]["rank"]
        )
        for iid in ordered_identities:
            m = contributor_meta[iid]
            result = session.execute(
                insert(Contributor)
                .values(
                    analysis_run_id=run_id,
                    repo_id=repo_id,
                    canonical_name=m["canonical_name"],
                    canonical_email=m["canonical_email"],
                    aliases=[{"name": n, "email": e} for n, e in m["aliases"]],
                    commit_count=m["commit_count"],
                    lines_added=m["lines_added"],
                    lines_deleted=m["lines_deleted"],
                    first_commit_at=m["first_commit_at"],
                    last_commit_at=m["last_commit_at"],
                    is_bot=m["is_bot"],
                    active_days=m["active_days"],
                    is_stale=m["is_stale"],
                    rank=m["rank"],
                )
                .returning(Contributor.id)
            )
            contributor_id_by_identity[iid] = result.scalar_one()

        files = session.scalars(
            select(File).where(File.repo_id == repo_id, File.is_deleted.is_(False))
        ).all()
        existing_path_ids = {f.path_id for f in files}

        ranked_by_path, expert_counts, sole_expert_by_path = _compute_doa_per_file(
            commits, identity_map, contributor_meta, existing_path_ids
        )

        file_expertise_rows = [
            {
                "analysis_run_id": run_id,
                "path_id": path_id,
                "contributor_id": contributor_id_by_identity[iid],
                "doa": doa,
                "doa_normalized": doa_norm,
                "is_expert": (
                    doa_norm >= EXPERT_DOA_NORMALIZED_THRESHOLD
                    and doa >= EXPERT_DOA_ABSOLUTE_THRESHOLD
                ),
                "changes": changes,
                "last_touched_at": last_touched_at,
            }
            for path_id, rows in ranked_by_path.items()
            for iid, doa, doa_norm, changes, last_touched_at, _last_sha in rows
        ]
        if file_expertise_rows:
            session.execute(insert(FileExpertise), file_expertise_rows)

        path_map = load_path_map(repo_id, session)
        findings = _knowledge_findings(
            repo_id,
            run_id,
            session,
            contributor_meta,
            sole_expert_by_path,
            expert_counts,
            len(ranked_by_path),
            path_map,
        )
        if findings:
            session.execute(insert(Finding), findings)

        return {
            "contributors": len(contributor_meta),
            "bots": sum(1 for m in contributor_meta.values() if m["is_bot"]),
            "bot_commit_ratio": (bot_commit_count / len(commits)) if commits else 0.0,
            "files_scored": len(ranked_by_path),
            "findings_emitted": len(findings),
        }
