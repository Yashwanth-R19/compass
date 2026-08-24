"""Guided reading order (session 06, Part B): a computed tour telling a new
joinee which files to read first and why.

Algorithm, in order (do not substitute a different one):

1. The directed dependency graph comes from ``ctx.dependency_graph`` (session
   01's run context) -- never rebuilt here.
2. PageRank comes from ``subsystem_members.centrality``, computed ONCE by
   ``SubsystemEngine`` (session 04). **Never recomputed** -- see that
   engine's docstring for why (cost, and a different graph-construction
   choice would silently produce a different value).
3. ``in_degree``/``out_degree`` per file come from the same dependency graph.
4. The candidate set is the UNION of six rules (manifest-declared entry
   points, top-3 PageRank, one anchor per subsystem, top-2 risk hotspots,
   top-2 widely-depended-on files, the repository's README) -- see
   ``compute_tour`` for the exact query behind each.
5. Candidates are deduplicated by path, keeping the FIRST reason code in
   priority order ``REASON_PRIORITY`` -- but EVERY rule that fired for a
   path is retained in ``reason_detail["reasons"]``, so the UI can show
   secondary justifications, not just the winning one.
6. Ordering: the README (if present) is position 1; then entry points by
   confidence desc; then every other candidate in BFS-layer order from the
   entry-point set (layer ties broken by pagerank desc, then in_degree desc,
   then **path asc** -- the path-asc tiebreak is what makes step 6's order
   deterministic across runs: BFS layer + pagerank + in_degree can still tie
   exactly on a repo with a regular/symmetric graph shape, and an unbroken
   tie would make Python's sort fall through to whatever order the earlier
   dict iteration happened to produce, i.e. non-deterministic in the same
   way session 04's community-list sort had to guard against); anything
   unreachable from any entry point sorts the same way and goes last.
7. Capped at ``MAX_TOUR_STOPS``. **Subsystem-coverage-over-hotspot rule**: if
   naively keeping only the top ``MAX_TOUR_STOPS`` candidates would drop a
   subsystem's anchor entirely (that subsystem would have zero
   representation in the tour), the anchor is swapped back in, evicting
   whichever ``hotspot``-reason stop currently in the kept set has the
   LOWEST risk_score (hotspots are the one reason category whose own
   internal priority -- top-2 by risk_score -- gives an unambiguous "which
   one matters less" answer; every other reason category has no such
   internal ranking to fall back on). One eviction per uncovered subsystem,
   processed in ascending subsystem-id order for determinism; if there are
   more uncovered subsystems than evictable hotspots, the remainder stay
   uncovered rather than looping indefinitely -- a repo would need more
   subsystems than ``MAX_TOUR_STOPS`` minus the README/entry-point/hotspot
   overhead for that to happen, which ``SubsystemEngine``'s own
   ``MAX_SUBSYSTEMS = 12`` cap makes very unlikely in practice.
8. Every stop's ``reason_detail`` is enriched with the same fixed field set
   regardless of reason_code (in_degree, out_degree, pagerank, loc,
   complexity, risk_score, risk_confidence, subsystem, top_expert,
   last_touched_at) -- this is what guarantees ``reason_detail`` is never an
   empty object (session 06 Known Hazard #6): even a stop with a thin
   ``reasons`` breakdown still carries this universal evidence set.

**On a graph with zero entry points (or an import-sparse repo generally)**
the BFS seed set is empty, so every non-entry-point candidate is
"unreachable" and the tour degenerates to "README, [no entry points],
then N files in pagerank/in-degree order" (session 06 Known Hazard #5) --
this is correct, expected behaviour on a sparse repo, not a bug to work
around; the deterministic tiebreak still applies so the order is stable.

**Non-source candidate exclusion (manual-QA follow-up, post-session-06).**
Manual acceptance testing against real repositories (compass itself,
expressjs/express) found the algorithm above, implemented exactly as
specified, producing tours dominated by test-fixture files, demo/example
scripts, and a CI config file -- e.g. a dummy `Main.java` test fixture at
position 3, and 8 of 15 express stops being `examples/*`, `test/support/*`,
or `History.md`. Root cause: `SubsystemEngine` (session 04) clusters
test/example/fixture directories into their own named subsystems on equal
footing with real source subsystems, and this engine's own
subsystem-coverage rule (step 7) then dutifully forces their anchor into the
tour. Rather than touching `SubsystemEngine` (out of this engine's scope --
its clustering and labels are still used for coverage bookkeeping), every
candidacy rule below (entry_point, high_centrality, subsystem_anchor,
hotspot, widely_depended_on) now skips a file that is either
`files.is_test`, lives under an `examples/`-or-`fixtures/`-style directory,
is a dotfile/dot-directory, or matches a fixed repo-metadata/build/CI
basename set (`_is_non_source`, `_NON_SOURCE_DIR_SEGMENTS`,
`_NON_SOURCE_BASENAMES`) -- HEURISTIC, not in the original session 06 spec,
documented per plan/RULES.md sec 3. The second round (metadata/CI
basenames) was added after the first round alone still left `History.md`,
`package.json`, `.github/workflows/ci.yml`, and `.editorconfig` anchoring
express's weaker subsystems. The `documentation` (README) rule is
deliberately NOT filtered: a README living under such a directory would be
a vanishingly rare, and still genuinely useful, edge case. A subsystem
whose every member is excluded this way simply gets no `subsystem_anchor`
candidate; the existing subsystem-coverage cap (step 7) already handles "no
anchor available" gracefully (it just leaves that subsystem uncovered
rather than forcing in a non-source file), so no change was needed there.
"""

from __future__ import annotations

import uuid
from collections import defaultdict, deque
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any

from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from app.db.models import (
    Contributor,
    EntryPoint,
    File,
    FileExpertise,
    FileMetrics,
    RepoManifest,
    RepoPath,
    Subsystem,
    SubsystemMember,
    TourStop,
)
from app.engines.base import Engine

if TYPE_CHECKING:
    from app.engines.context import RunContext

MAX_TOUR_STOPS = 15
"""Session 06 spec: a person cannot productively hold more than this many
"read this first" pointers in their head at once -- same comprehension
argument as SubsystemEngine's MAX_SUBSYSTEMS."""

TOP_PAGERANK_COUNT = 3
TOP_HOTSPOT_COUNT = 2
TOP_IN_DEGREE_COUNT = 2
"""Session 06 spec: the exact candidate-pool sizes for the high_centrality/
hotspot/widely_depended_on rules."""

ENTRY_POINT_KINDS_FOR_TOUR = ("web_server", "cli", "ui_root")
"""Session 06 Part B step 4: only these three EntryPoint kinds seed the tour
-- "test_root"/"build"/"graph_inferred" entries are real entry points for
other purposes (session 04) but not the kind of place a new joinee should
START reading."""

REASON_PRIORITY: tuple[str, ...] = (
    "documentation",
    "entry_point",
    "subsystem_anchor",
    "high_centrality",
    "widely_depended_on",
    "hotspot",
)
"""Session 06 Part B step 5's exact priority order -- the first of these
present in a candidate's ``reasons`` dict becomes its stored
``reason_code``; every reason that actually fired stays recorded in
``reason_detail["reasons"]`` regardless of which one wins."""

_REASON_RANK = {code: i for i, code in enumerate(REASON_PRIORITY)}

_NON_SOURCE_DIR_SEGMENTS = frozenset({"examples", "example", "fixtures", "fixture"})
"""HEURISTIC (manual-QA follow-up, post-session-06; plan/RULES.md sec 3): a
file under one of these directory segments, at any depth, is demo/scaffolding
code rather than real library source -- forcing it into the guided tour
misleads a new joinee. Matches the existing fixed-directory-segment-set
pattern already used elsewhere in this codebase (miner.py's IGNORE_DIRS,
persist.py's _JS_TEST_DIR_SEGMENTS)."""

_NON_SOURCE_BASENAMES = frozenset(
    {
        "readme", "readme.md", "readme.rst", "readme.txt",
        "history.md", "history.rst", "history.txt", "changes.md",
        "changelog", "changelog.md", "changelog.rst", "changelog.txt",
        "license", "license.md", "license.txt",
        "licence", "licence.md", "licence.txt",
        "contributing.md", "contributing.rst",
        "package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
        "pyproject.toml", "poetry.lock", "pipfile", "pipfile.lock",
        "requirements.txt", "setup.py", "setup.cfg",
        "dockerfile", "docker-compose.yml", "docker-compose.yaml",
        "makefile", "procfile", "gemfile", "gemfile.lock",
    }
)  # fmt: skip
"""HEURISTIC (manual-QA follow-up, post-session-06; plan/RULES.md sec 3):
repo-metadata/build/CI files (matched case-insensitively by basename), plus
any dotfile/dot-directory (``.github``, ``.editorconfig``, ...) via
``_is_non_source`` below. These aren't demo code like the directory-segment
set above, but the same manual QA found them anchoring a trivial or
"Unclustered" subsystem purely by having the highest PageRank of a handful
of orphan files -- a CI workflow or a lockfile is not what a new joinee
should read to understand the codebase. The dedicated ``documentation``
rule (the actual README, via ``repo_manifests``) is unaffected -- this list
only removes files from the OTHER candidacy rules (entry_point,
high_centrality, subsystem_anchor, hotspot, widely_depended_on)."""


def _is_non_source(path: str, is_test: bool) -> bool:
    """Whether ``path`` should be excluded from every tour candidacy rule
    except ``documentation`` -- see the module docstring's "Non-source
    candidate exclusion" section for why."""
    if is_test:
        return True
    parts = PurePosixPath(path).parts
    if any(segment in _NON_SOURCE_DIR_SEGMENTS for segment in parts):
        return True
    if any(segment.startswith(".") for segment in parts):
        return True
    return PurePosixPath(path).name.lower() in _NON_SOURCE_BASENAMES


@dataclass
class _Candidate:
    path_id: int
    subsystem_id: int | None
    reasons: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def primary_reason_code(self) -> str:
        return min(self.reasons, key=lambda code: _REASON_RANK[code])


def _select_primary_readme(
    repo_id: uuid.UUID, session: Session
) -> tuple[int, str, dict[str, Any]] | None:
    """The repository's README, when ``repo_manifests`` has one -- a
    monorepo can have several (session 03's manifest walk isn't
    root-only), so the shallowest path wins, tie-broken by path asc for
    determinism (judgement call, session 06: the spec names no selection
    rule for "the repository's README" beyond assuming there is one)."""
    rows = session.execute(
        select(RepoManifest.path_id, RepoPath.path, RepoManifest.data)
        .join(RepoPath, RepoPath.id == RepoManifest.path_id)
        .where(RepoManifest.repo_id == repo_id, RepoManifest.kind == "readme")
    ).all()
    if not rows:
        return None
    path_id, path, data = min(rows, key=lambda r: (r[1].count("/"), r[1]))
    return path_id, path, data


def _bfs_layers(graph: Any, seeds: Sequence[str]) -> dict[str, int]:
    """Multi-source BFS distance (in graph hops) from ``seeds``, following
    structural (import) edges forward -- "what does reading this entry point
    lead you to next". Nodes unreachable from every seed are simply absent
    from the returned dict."""
    dist: dict[str, int] = {}
    queue: deque[str] = deque()
    for s in seeds:
        if s in graph and s not in dist:
            dist[s] = 0
            queue.append(s)
    while queue:
        node = queue.popleft()
        for nxt in graph.successors(node):
            if nxt not in dist:
                dist[nxt] = dist[node] + 1
                queue.append(nxt)
    return dist


def _apply_subsystem_coverage_cap(
    ordered: list[_Candidate],
    all_subsystem_ids: set[int],
    risk_by_path_id: dict[int, tuple[float | None, float | None]],
) -> list[_Candidate]:
    """Session 06 Part B step 7. See module docstring for the full rule --
    this is the executable form of it."""
    if len(ordered) <= MAX_TOUR_STOPS:
        return ordered

    final = list(ordered[:MAX_TOUR_STOPS])
    overflow = ordered[MAX_TOUR_STOPS:]

    anchor_in_overflow: dict[int, _Candidate] = {}
    for c in overflow:
        if c.primary_reason_code == "subsystem_anchor" and c.subsystem_id is not None:
            anchor_in_overflow.setdefault(c.subsystem_id, c)

    covered = {c.subsystem_id for c in final if c.subsystem_id is not None}
    missing = sorted(sid for sid in all_subsystem_ids if sid not in covered)

    for subsystem_id in missing:
        anchor = anchor_in_overflow.get(subsystem_id)
        if anchor is None:
            continue  # no anchor waiting in the overflow tail for this subsystem

        hotspot_indices = [i for i, c in enumerate(final) if c.primary_reason_code == "hotspot"]
        if not hotspot_indices:
            break  # nothing left to evict -- give up gracefully (see docstring)

        # Lowest-priority hotspot = lowest risk_score among the hotspot
        # stops currently kept, tie-broken by path desc (arbitrary but
        # deterministic -- there are at most TOP_HOTSPOT_COUNT candidates
        # to choose between).
        evict_idx = min(
            hotspot_indices,
            key=lambda i: (
                risk_by_path_id.get(final[i].path_id, (0.0, 0.0))[0] or 0.0,
                -final[i].path_id,
            ),
        )
        final[evict_idx] = anchor

    return final


def compute_tour(
    repo_id: uuid.UUID, run_id: uuid.UUID, session: Session, ctx: RunContext
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Pure computation (no writes) -- the module-level ``compute_*`` core
    every engine follows. Returns ``(rows, summary)`` where ``rows`` are
    ready for a bulk insert into ``tour_stops``."""
    files = session.scalars(
        select(File).where(File.repo_id == repo_id, File.is_deleted.is_(False))
    ).all()
    if not files:
        return [], {"stops": 0, "subsystems_covered": 0, "of": 0}

    files_by_path_id = {f.path_id: f for f in files}
    path_by_id = {f.path_id: f.path for f in files}
    excluded_path_ids = {f.path_id for f in files if _is_non_source(f.path, f.is_test)}

    graph = ctx.dependency_graph(session)

    subsystem_rows = session.execute(
        select(SubsystemMember.path_id, SubsystemMember.centrality, Subsystem.id, Subsystem.label)
        .join(Subsystem, Subsystem.id == SubsystemMember.subsystem_id)
        .where(Subsystem.analysis_run_id == run_id)
    ).all()
    centrality_by_path_id: dict[int, float] = {}
    subsystem_id_by_path_id: dict[int, int] = {}
    subsystem_label_by_id: dict[int, str] = {}
    members_by_subsystem: dict[int, list[tuple[int, float]]] = defaultdict(list)
    for path_id, centrality, subsystem_id, label in subsystem_rows:
        if path_id not in files_by_path_id:
            continue
        centrality_by_path_id[path_id] = centrality
        subsystem_id_by_path_id[path_id] = subsystem_id
        subsystem_label_by_id[subsystem_id] = label
        members_by_subsystem[subsystem_id].append((path_id, centrality))
    total_subsystems = len(members_by_subsystem)

    risk_rows = session.execute(
        select(FileMetrics.path_id, FileMetrics.risk_score, FileMetrics.risk_confidence).where(
            FileMetrics.analysis_run_id == run_id
        )
    ).all()
    risk_by_path_id: dict[int, tuple[float | None, float | None]] = {
        r.path_id: (r.risk_score, r.risk_confidence)
        for r in risk_rows
        if r.path_id in files_by_path_id
    }

    entry_point_rows = session.execute(
        select(
            EntryPoint.path_id, EntryPoint.kind, EntryPoint.confidence, EntryPoint.evidence
        ).where(
            EntryPoint.analysis_run_id == run_id,
            EntryPoint.kind.in_(ENTRY_POINT_KINDS_FOR_TOUR),
        )
    ).all()

    readme = _select_primary_readme(repo_id, session)

    candidates: dict[int, _Candidate] = {}

    def _get(path_id: int) -> _Candidate:
        if path_id not in candidates:
            candidates[path_id] = _Candidate(
                path_id=path_id, subsystem_id=subsystem_id_by_path_id.get(path_id)
            )
        return candidates[path_id]

    # (a) manifest/conventional/graph-inferred entry points, restricted kinds
    # -- excludes test/example/fixture files (see module docstring's
    # "Non-source candidate exclusion"), same as every other rule below.
    for path_id, kind, confidence, evidence in entry_point_rows:
        if path_id not in files_by_path_id or path_id in excluded_path_ids:
            continue
        _get(path_id).reasons["entry_point"] = {
            "kind": kind,
            "confidence": confidence,
            "evidence": evidence,
        }

    # (b) top-3 files by PageRank across the whole repository
    ranked_by_pagerank = sorted(
        (kv for kv in centrality_by_path_id.items() if kv[0] not in excluded_path_ids),
        key=lambda kv: (-kv[1], path_by_id[kv[0]]),
    )
    for path_id, centrality in ranked_by_pagerank[:TOP_PAGERANK_COUNT]:
        _get(path_id).reasons.setdefault("high_centrality", {"pagerank": centrality})

    # (c) each subsystem's own highest-PageRank member among its non-excluded
    # members -- a subsystem whose every member is test/example/fixture code
    # simply gets no anchor candidate (see module docstring).
    for subsystem_id, members in members_by_subsystem.items():
        eligible = [(pid, c) for pid, c in members if pid not in excluded_path_ids]
        if not eligible:
            continue
        anchor_path_id, anchor_centrality = min(
            eligible, key=lambda pc: (-pc[1], path_by_id[pc[0]])
        )
        _get(anchor_path_id).reasons.setdefault(
            "subsystem_anchor",
            {"subsystem": subsystem_label_by_id[subsystem_id], "pagerank": anchor_centrality},
        )

    # (d) top-2 files by risk_score
    ranked_by_risk = sorted(
        (kv for kv in risk_by_path_id.items() if kv[0] not in excluded_path_ids),
        key=lambda kv: (-(kv[1][0] or 0.0), path_by_id[kv[0]]),
    )
    for path_id, (risk_score, risk_confidence) in ranked_by_risk[:TOP_HOTSPOT_COUNT]:
        _get(path_id).reasons.setdefault(
            "hotspot", {"risk_score": risk_score, "risk_confidence": risk_confidence}
        )

    already_included = set(candidates.keys())

    # (e) top-2 files by in_degree, excluding anything already a candidate
    in_degree_by_path_id: dict[int, int] = {
        path_id: (graph.in_degree(path) if path in graph else 0)
        for path_id, path in path_by_id.items()
    }
    ranked_by_in_degree = sorted(
        (
            pid
            for pid in in_degree_by_path_id
            if pid not in already_included and pid not in excluded_path_ids
        ),
        key=lambda pid: (-in_degree_by_path_id[pid], path_by_id[pid]),
    )
    for path_id in ranked_by_in_degree[:TOP_IN_DEGREE_COUNT]:
        _get(path_id).reasons.setdefault(
            "widely_depended_on", {"in_degree": in_degree_by_path_id[path_id]}
        )

    # (f) the repository's README, if any
    if readme is not None:
        readme_path_id, _readme_path, readme_data = readme
        if readme_path_id in files_by_path_id:
            _get(readme_path_id).reasons.setdefault(
                "documentation",
                {
                    "heading": readme_data.get("heading"),
                    "line_count": readme_data.get("line_count"),
                },
            )

    if not candidates:
        return [], {"stops": 0, "subsystems_covered": 0, "of": total_subsystems}

    readme_candidate = next(
        (c for c in candidates.values() if c.primary_reason_code == "documentation"), None
    )
    entry_point_candidates = sorted(
        (c for c in candidates.values() if c.primary_reason_code == "entry_point"),
        key=lambda c: (-c.reasons["entry_point"]["confidence"], path_by_id[c.path_id]),
    )

    placed_ids = {c.path_id for c in entry_point_candidates}
    if readme_candidate is not None:
        placed_ids.add(readme_candidate.path_id)

    remaining = [c for c in candidates.values() if c.path_id not in placed_ids]
    seed_paths = [path_by_id[c.path_id] for c in entry_point_candidates]
    distances = _bfs_layers(graph, seed_paths)

    def _tiebreak(c: _Candidate) -> tuple[float, int, str]:
        pagerank = centrality_by_path_id.get(c.path_id, 0.0)
        in_degree = in_degree_by_path_id.get(c.path_id, 0)
        return (-pagerank, -in_degree, path_by_id[c.path_id])

    reached: list[tuple[int, _Candidate]] = []
    unreached: list[_Candidate] = []
    for c in remaining:
        d = distances.get(path_by_id[c.path_id])
        if d is None:
            unreached.append(c)
        else:
            reached.append((d, c))
    reached.sort(key=lambda t: (t[0], *_tiebreak(t[1])))
    unreached.sort(key=_tiebreak)

    ordered: list[_Candidate] = []
    if readme_candidate is not None:
        ordered.append(readme_candidate)
    ordered.extend(entry_point_candidates)
    ordered.extend(c for _, c in reached)
    ordered.extend(unreached)

    final = _apply_subsystem_coverage_cap(
        ordered, set(members_by_subsystem.keys()), risk_by_path_id
    )

    final_path_ids = [c.path_id for c in final]
    top_expert_by_path_id: dict[int, str] = {}
    if final_path_ids:
        expert_rows = session.execute(
            select(FileExpertise.path_id, FileExpertise.doa_normalized, Contributor.canonical_name)
            .join(Contributor, Contributor.id == FileExpertise.contributor_id)
            .where(
                FileExpertise.analysis_run_id == run_id,
                FileExpertise.path_id.in_(final_path_ids),
            )
        ).all()
        best_doa: dict[int, float] = {}
        for path_id, doa_normalized, name in expert_rows:
            if path_id not in best_doa or doa_normalized > best_doa[path_id]:
                best_doa[path_id] = doa_normalized
                top_expert_by_path_id[path_id] = name

    rows: list[dict[str, Any]] = []
    for position, c in enumerate(final, start=1):
        path = path_by_id[c.path_id]
        file = files_by_path_id[c.path_id]
        risk_score, risk_confidence = risk_by_path_id.get(c.path_id, (None, None))
        reason_detail = {
            "in_degree": in_degree_by_path_id.get(c.path_id, 0),
            "out_degree": graph.out_degree(path) if path in graph else 0,
            "pagerank": centrality_by_path_id.get(c.path_id, 0.0),
            "loc": file.current_loc,
            "complexity": file.complexity,
            "risk_score": risk_score,
            "risk_confidence": risk_confidence,
            "subsystem": subsystem_label_by_id.get(subsystem_id_by_path_id.get(c.path_id, -1)),
            "top_expert": top_expert_by_path_id.get(c.path_id),
            "last_touched_at": file.last_seen.isoformat(),
            "reasons": c.reasons,
        }
        rows.append(
            {
                "analysis_run_id": run_id,
                "repo_id": repo_id,
                "position": position,
                "path_id": c.path_id,
                "reason_code": c.primary_reason_code,
                "reason_detail": reason_detail,
                "subsystem_id": c.subsystem_id,
            }
        )

    subsystems_covered = len({c.subsystem_id for c in final if c.subsystem_id is not None})
    return rows, {
        "stops": len(rows),
        "subsystems_covered": subsystems_covered,
        "of": total_subsystems,
    }


class TourEngine(Engine):
    """Deterministic guided reading order (session 06, Part B) -- see the
    module docstring for the full algorithm. Runs first in the "onboarding"
    stage; reads Coupling/Subsystems/Architecture/Risk/Knowledge output from
    earlier stages in this same run, writes no findings of its own.
    """

    def run(self, ctx: RunContext, session: Session) -> dict[str, Any]:
        rows, summary = compute_tour(ctx.repo_id, ctx.run_id, session, ctx)
        if rows:
            session.execute(insert(TourStop), rows)
        return summary
