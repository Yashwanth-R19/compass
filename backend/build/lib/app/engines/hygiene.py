"""Commit hygiene (session 07, Part B): signals about HOW a repository is
committed to, distinct from risk (WHAT is risky) and knowledge (WHO knows
it). Everything here reads the Facts layer only (`commits` and its parallel
arrays, `files.is_test`) plus this run's own `subsystems`/`subsystem_members`
partition -- no clone needed, same discipline as every other engine.

Deliberately excludes time-of-day / "late-night commits are risky" as a
signal -- see the module-level comment right above `_detect_risky_commits`
for why, and `tests/test_hygiene_engine.py`'s dedicated assertion that no
hour/timezone logic exists anywhere in this file's scoring.
"""

from __future__ import annotations

import re
import uuid
from collections import Counter
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, NamedTuple

from sqlalchemy import bindparam, insert, select, update
from sqlalchemy.orm import Session

from app.baseline.base import BaselineProvider
from app.baseline.heuristic import HeuristicBaseline, size_bucket_for
from app.db.models import (
    Commit,
    File,
    FileMetrics,
    Finding,
    HygieneEvent,
    Severity,
    Subsystem,
    SubsystemMember,
)
from app.engines.base import Engine
from app.engines.signature import finding_signature

if TYPE_CHECKING:
    from app.engines.context import RunContext

# ---- Config (module-level, documented; not per-caller knobs) ----

OVERSIZED_PERCENTILE = 0.95
"""Flags commits above the 95th percentile of BOTH files_changed and
insertions+deletions, computed from THIS REPO's OWN distribution -- never a
fixed absolute threshold. A 200-file commit is unremarkable in a monorepo
that regularly does dependency-bump PRs touching hundreds of lockfile
entries, and remarkable in a 50-commit personal project; using the repo's
own distribution is what makes this meaningful across both, rather than a
number tuned for one specific repo size."""

MIN_COMMITS_FOR_PERCENTILE = 20
"""Below this many commits, a percentile is really just "the single largest
commit so far" -- noise, not a distribution. No oversized-commit finding or
event is emitted below this floor; the stage summary records
`insufficient_history_for_oversized: true` instead (session 07 Known
Hazard #4)."""

FIXUP_WINDOW_MINUTES = 120
FIXUP_MIN_CONSECUTIVE = 3
FIXUP_MESSAGE_RE = re.compile(
    r"\b(wip|fixup|oops|typo|forgot|revert me|temp|asdf)\b", re.IGNORECASE
)
"""A fixup cluster is >= FIXUP_MIN_CONSECUTIVE consecutive commits by the
SAME author (exact author_name/author_email match -- this is a commit-
sequence pattern, not a person-level aggregate, so it doesn't need session
05's cross-alias identity resolution), each within FIXUP_WINDOW_MINUTES of
the previous one, each sharing at least one touched file with the previous
one, where AT LEAST ONE commit's message matches FIXUP_MESSAGE_RE. Reported
as a hygiene SIGNAL, never a defect -- everyone does this."""

RISKY_MIN_SUBSYSTEMS = 3
RISKY_CHURN_QUINTILE_FRACTION = 0.80
""""Top churn quintile" == the top 20% by insertions+deletions == value >=
the 80th percentile of this repo's own commit-churn distribution."""
RISKY_MIN_MESSAGE_LENGTH = 15
RISKY_MIN_SCORE = 3
"""A commit is "risky" (session 07 Part B.3, EXPLICITLY HEURISTIC) when it
combines >= RISKY_MIN_SCORE of: touches >= RISKY_MIN_SUBSYSTEMS distinct
subsystems; is in the top churn quintile; changes NO test file
(files.is_test, session 03's shared classifier); has a message shorter than
RISKY_MIN_MESSAGE_LENGTH characters. Score is the count of conditions met
(0-4); reported when score >= RISKY_MIN_SCORE.

Deliberately does NOT include time-of-day ("late-night commits are risky").
It is folklore -- timezone-dependent (whose midnight? committer's local
clock is not even reliably recorded) and unreliable as a bug-proneness
signal -- and including it would weaken the credibility of the other three,
genuinely evidence-based conditions. There is no hour/timezone read
anywhere in this module; see the dedicated test asserting that."""

MAX_HYGIENE_FINDINGS = 8
"""Anti-alert-fatigue cap (plan/RULES.md sec 12), shared across all three
finding kinds -- hygiene is informational and must never crowd out a
security or risk finding in the global ranking."""

HYGIENE_OVERSIZED_SEVERITY = Severity.med
HYGIENE_FIXUP_SEVERITY = Severity.low
HYGIENE_RISKY_SEVERITY = Severity.med
"""HEURISTIC (plan/RULES.md sec 3): fixed per-kind severities, never above
MED -- hygiene findings are informational signals, not defects or
vulnerabilities, and must never compete with a HIGH-severity risk/security
finding in the global cross-category ranking (FindingsRankEngine)."""

_SEVERITY_WEIGHT = {Severity.high: 2, Severity.med: 1, Severity.low: 0}

INSTABILITY_REVERT_WEIGHT = 2
"""HEURISTIC: a revert-cycle counts double toward instability_score's raw
input relative to an oversized or fixup-cluster occurrence -- a revert means
a change was bad enough to undo entirely, a stronger signal than "this
commit was unusually large" or "this looked like a fixup"."""


class _CommitRow(NamedTuple):
    sha: str
    author_name: str
    author_email: str
    committed_at: datetime
    message: str
    is_revert: bool
    files_changed: int
    churn: int
    changed_path_ids: tuple[int, ...]


def _load_commits(repo_id: uuid.UUID, session: Session) -> list[_CommitRow]:
    rows = session.execute(
        select(
            Commit.sha,
            Commit.author_name,
            Commit.author_email,
            Commit.committed_at,
            Commit.message,
            Commit.is_revert,
            Commit.files_changed,
            Commit.insertions,
            Commit.deletions,
            Commit.changed_path_ids,
        )
        .where(Commit.repo_id == repo_id)
        .order_by(Commit.committed_at.asc(), Commit.id.asc())
    ).all()
    return [
        _CommitRow(
            sha=r.sha,
            author_name=r.author_name,
            author_email=r.author_email,
            committed_at=r.committed_at,
            message=r.message,
            is_revert=r.is_revert,
            files_changed=r.files_changed,
            churn=r.insertions + r.deletions,
            changed_path_ids=tuple(r.changed_path_ids),
        )
        for r in rows
    ]


def _nearest_rank_percentile(sorted_values: list[float], fraction: float) -> float:
    """Deterministic percentile over an already-sorted list, no external
    stats dependency -- mirrors app/engines/expertise.py::_percentile's
    exact nearest-rank formula (kept as a small local copy rather than a
    cross-module import of that function's private helper)."""
    if not sorted_values:
        return 0.0
    idx = int(fraction * (len(sorted_values) - 1))
    return sorted_values[idx]


def _detect_oversized(commits: list[_CommitRow]) -> tuple[set[str], bool]:
    """Returns (oversized_shas, insufficient_history). A commit is oversized
    when it exceeds the 95th percentile of BOTH files_changed and churn
    (insertions+deletions), computed over this repo's own distribution --
    never aggregated/summed, per-metric percentiles, both must be exceeded."""
    if len(commits) < MIN_COMMITS_FOR_PERCENTILE:
        return set(), True

    files_changed_p95 = _nearest_rank_percentile(
        sorted(c.files_changed for c in commits), OVERSIZED_PERCENTILE
    )
    churn_p95 = _nearest_rank_percentile(sorted(c.churn for c in commits), OVERSIZED_PERCENTILE)

    oversized = {
        c.sha for c in commits if c.files_changed > files_changed_p95 and c.churn > churn_p95
    }
    return oversized, False


def _detect_fixup_clusters(commits: list[_CommitRow]) -> list[list[_CommitRow]]:
    """Sequences of >= FIXUP_MIN_CONSECUTIVE consecutive (in time) commits by
    the same author, each within FIXUP_WINDOW_MINUTES of the previous one and
    sharing >= 1 touched file with it, where at least one commit's message
    matches FIXUP_MESSAGE_RE. `commits` must already be sorted by
    committed_at asc (see _load_commits)."""
    window = timedelta(minutes=FIXUP_WINDOW_MINUTES)
    clusters: list[list[_CommitRow]] = []
    current: list[_CommitRow] = []

    def _flush() -> None:
        if len(current) >= FIXUP_MIN_CONSECUTIVE and any(
            FIXUP_MESSAGE_RE.search(c.message) for c in current
        ):
            clusters.append(list(current))

    for c in commits:
        if current:
            prev = current[-1]
            same_author = (c.author_name, c.author_email) == (prev.author_name, prev.author_email)
            within_window = (c.committed_at - prev.committed_at) <= window
            overlaps = bool(set(c.changed_path_ids) & set(prev.changed_path_ids))
            if same_author and within_window and overlaps:
                current.append(c)
                continue
        _flush()
        current = [c]
    _flush()

    return clusters


def _detect_risky_commits(
    commits: list[_CommitRow],
    subsystem_by_path: dict[int, int],
    is_test_by_path: dict[int, bool],
) -> dict[str, int]:
    """Returns {sha: score} for commits scoring >= RISKY_MIN_SCORE (session
    07 Part B.3). Deliberately no hour/timezone/time-of-day input anywhere
    in this function -- see RISKY_MIN_SCORE's docstring."""
    if not commits:
        return {}

    churn_p80 = _nearest_rank_percentile(
        sorted(c.churn for c in commits), RISKY_CHURN_QUINTILE_FRACTION
    )

    scored: dict[str, int] = {}
    for c in commits:
        subsystems_touched = {
            subsystem_by_path[pid] for pid in c.changed_path_ids if pid in subsystem_by_path
        }
        touches_test = any(is_test_by_path.get(pid, False) for pid in c.changed_path_ids)

        score = 0
        score += 1 if len(subsystems_touched) >= RISKY_MIN_SUBSYSTEMS else 0
        score += 1 if c.churn >= churn_p80 else 0
        score += 1 if not touches_test else 0
        score += 1 if len(c.message.strip()) < RISKY_MIN_MESSAGE_LENGTH else 0

        if score >= RISKY_MIN_SCORE:
            scored[c.sha] = score

    return scored


def _build_events(
    repo_id: uuid.UUID,
    run_id: uuid.UUID,
    commits_by_sha: dict[str, _CommitRow],
    oversized_shas: set[str],
    fixup_clusters: list[list[_CommitRow]],
    risky_scores: dict[str, int],
    files_changed_p95: float,
    churn_p95: float,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []

    for sha in sorted(oversized_shas):
        c = commits_by_sha[sha]
        events.append(
            {
                "analysis_run_id": run_id,
                "repo_id": repo_id,
                "kind": "oversized",
                "commit_sha": sha,
                "occurred_at": c.committed_at,
                "detail": {
                    "files_changed": c.files_changed,
                    "churn": c.churn,
                    "files_changed_p95": files_changed_p95,
                    "churn_p95": churn_p95,
                },
                "severity_hint": HYGIENE_OVERSIZED_SEVERITY.value,
            }
        )

    for cluster in fixup_clusters:
        events.append(
            {
                "analysis_run_id": run_id,
                "repo_id": repo_id,
                "kind": "fixup_churn",
                "commit_sha": cluster[0].sha,
                "occurred_at": cluster[0].committed_at,
                "detail": {
                    "commit_shas": [c.sha for c in cluster],
                    "author_name": cluster[0].author_name,
                    "author_email": cluster[0].author_email,
                    "cluster_size": len(cluster),
                },
                "severity_hint": HYGIENE_FIXUP_SEVERITY.value,
            }
        )

    for sha, score in sorted(risky_scores.items()):
        c = commits_by_sha[sha]
        events.append(
            {
                "analysis_run_id": run_id,
                "repo_id": repo_id,
                "kind": "risky_commit",
                "commit_sha": sha,
                "occurred_at": c.committed_at,
                "detail": {
                    "score": score,
                    "files_changed": c.files_changed,
                    "churn": c.churn,
                    "message_length": len(c.message.strip()),
                },
                "severity_hint": HYGIENE_RISKY_SEVERITY.value,
            }
        )

    return events


def _hygiene_findings(
    repo_id: uuid.UUID,
    run_id: uuid.UUID,
    commits_by_sha: dict[str, _CommitRow],
    oversized_shas: set[str],
    fixup_clusters: list[list[_CommitRow]],
    risky_scores: dict[str, int],
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []

    for sha in oversized_shas:
        c = commits_by_sha[sha]
        candidates.append(
            {
                "analysis_run_id": run_id,
                "repo_id": repo_id,
                "category": "hygiene",
                "severity": HYGIENE_OVERSIZED_SEVERITY,
                "confidence": 0.7,
                "path_id": None,
                "evidence_sha": sha,
                "title": f"Oversized commit: {sha[:8]}",
                "detail": (
                    f"This commit changed {c.files_changed} files and {c.churn} lines, "
                    "both above the 95th percentile of this repository's own commit-size "
                    "distribution."
                ),
                "signature": finding_signature("hygiene", f"oversized:{sha}"),
                "_sort_key": c.churn,
            }
        )

    for cluster in fixup_clusters:
        shas = [c.sha for c in cluster]
        key = "|".join(sorted(shas))
        candidates.append(
            {
                "analysis_run_id": run_id,
                "repo_id": repo_id,
                "category": "hygiene",
                "severity": HYGIENE_FIXUP_SEVERITY,
                "confidence": 0.6,
                "path_id": None,
                "evidence_sha": shas[-1],
                "title": f"Fixup commit cluster ({len(cluster)} commits)",
                "detail": (
                    f"{cluster[0].author_name} made {len(cluster)} consecutive commits to "
                    "overlapping files within a short window, including a WIP/fixup-style "
                    "message -- a hygiene signal, not a defect."
                ),
                "signature": finding_signature("hygiene", f"fixup_churn:{key}"),
                "_sort_key": len(cluster),
            }
        )

    for sha, score in risky_scores.items():
        c = commits_by_sha[sha]
        candidates.append(
            {
                "analysis_run_id": run_id,
                "repo_id": repo_id,
                "category": "hygiene",
                "severity": HYGIENE_RISKY_SEVERITY,
                "confidence": score / 4,
                "path_id": None,
                "evidence_sha": sha,
                "title": f"Risky commit: {sha[:8]}",
                "detail": (
                    f"This commit meets {score} of 4 risky-commit conditions (wide "
                    "subsystem spread, top-quintile churn, no test changes, a very short "
                    "message) -- EXPLICITLY HEURISTIC, not a confirmed defect."
                ),
                "signature": finding_signature("hygiene", f"risky_commit:{sha}"),
                "_sort_key": score,
            }
        )

    candidates.sort(
        key=lambda f: (_SEVERITY_WEIGHT[f["severity"]], f["confidence"], f["_sort_key"]),
        reverse=True,
    )
    candidates = candidates[:MAX_HYGIENE_FINDINGS]
    for rank, f in enumerate(candidates):
        f["rank"] = rank
        del f["_sort_key"]
    return candidates


class HygieneEngine(Engine):
    """Commit hygiene (session 07, Part B): oversized commits, fixup-churn
    clusters, risky commits, and per-file instability -- all from the Facts
    layer plus this run's own subsystem partition. Runs immediately after
    ``RiskEngine`` in the "risk" stage (app/jobs/stages.py) and UPDATES the
    ``file_metrics`` rows RiskEngine already inserted for this run (never a
    second insert -- the unique constraint on (analysis_run_id, path_id)
    would reject that, and a fresh run_id already has exactly the rows
    RiskEngine wrote, per the Facts/Insight split's "engines never delete,
    only insert" rule -- an UPDATE against this run's own just-written rows
    is the one exception that rule doesn't forbid).
    """

    def __init__(self, baseline: BaselineProvider | None = None) -> None:
        self._baseline = baseline or HeuristicBaseline()

    def run(self, ctx: RunContext, session: Session) -> dict[str, Any]:
        repo_id, run_id = ctx.repo_id, ctx.run_id

        commits = _load_commits(repo_id, session)
        if not commits:
            return {
                "events_emitted": 0,
                "findings_emitted": 0,
                "insufficient_history_for_oversized": True,
            }

        commits_by_sha = {c.sha: c for c in commits}

        oversized_shas, insufficient_history = _detect_oversized(commits)
        files_changed_p95 = (
            _nearest_rank_percentile(sorted(c.files_changed for c in commits), OVERSIZED_PERCENTILE)
            if not insufficient_history
            else 0.0
        )
        churn_p95 = (
            _nearest_rank_percentile(sorted(c.churn for c in commits), OVERSIZED_PERCENTILE)
            if not insufficient_history
            else 0.0
        )

        fixup_clusters = _detect_fixup_clusters(commits)

        subsystem_by_path: dict[int, int] = {
            path_id: subsystem_id
            for path_id, subsystem_id in session.execute(
                select(SubsystemMember.path_id, SubsystemMember.subsystem_id)
                .join(Subsystem, Subsystem.id == SubsystemMember.subsystem_id)
                .where(Subsystem.analysis_run_id == run_id)
            ).all()
        }
        is_test_by_path: dict[int, bool] = {
            path_id: is_test
            for path_id, is_test in session.execute(
                select(File.path_id, File.is_test).where(File.repo_id == repo_id)
            ).all()
        }
        risky_scores = _detect_risky_commits(commits, subsystem_by_path, is_test_by_path)

        events = _build_events(
            repo_id,
            run_id,
            commits_by_sha,
            oversized_shas,
            fixup_clusters,
            risky_scores,
            files_changed_p95,
            churn_p95,
        )
        if events:
            session.execute(insert(HygieneEvent), events)

        # ---- per-file instability (Part B.4) ----
        fixup_shas = {c.sha for cluster in fixup_clusters for c in cluster}
        oversized_count: Counter[int] = Counter()
        fixup_count: Counter[int] = Counter()
        revert_count: Counter[int] = Counter()
        for c in commits:
            touched = set(c.changed_path_ids)
            for path_id in touched:
                if c.sha in oversized_shas:
                    oversized_count[path_id] += 1
                if c.sha in fixup_shas:
                    fixup_count[path_id] += 1
                if c.is_revert:
                    revert_count[path_id] += 1

        files = session.scalars(
            select(File).where(File.repo_id == repo_id, File.is_deleted.is_(False))
        ).all()
        path_ids = [f.path_id for f in files]

        raw_instability = [
            oversized_count[pid] + fixup_count[pid] + INSTABILITY_REVERT_WEIGHT * revert_count[pid]
            for pid in path_ids
        ]
        dominant_language = (
            Counter(f.language for f in files).most_common(1)[0][0] if files else "other"
        )
        size_bucket = size_bucket_for(len(files))
        normalized_instability = self._baseline.risk_normalizer(
            "hygiene_instability", dominant_language, size_bucket
        )(raw_instability)

        if path_ids:
            update_rows = [
                {
                    "b_path_id": pid,
                    "b_instability_score": normalized_instability[i],
                    "b_revert_cycle_count": revert_count[pid],
                    "b_oversized_commit_count": oversized_count[pid],
                    "b_fixup_commit_count": fixup_count[pid],
                }
                for i, pid in enumerate(path_ids)
            ]
            session.execute(
                update(FileMetrics)
                .where(
                    FileMetrics.analysis_run_id == run_id,
                    FileMetrics.path_id == bindparam("b_path_id"),
                )
                .values(
                    instability_score=bindparam("b_instability_score"),
                    revert_cycle_count=bindparam("b_revert_cycle_count"),
                    oversized_commit_count=bindparam("b_oversized_commit_count"),
                    fixup_commit_count=bindparam("b_fixup_commit_count"),
                ),
                update_rows,
            )

        findings = _hygiene_findings(
            repo_id, run_id, commits_by_sha, oversized_shas, fixup_clusters, risky_scores
        )
        if findings:
            session.execute(insert(Finding), findings)

        return {
            "events_emitted": len(events),
            "findings_emitted": len(findings),
            "oversized_commits": len(oversized_shas),
            "fixup_clusters": len(fixup_clusters),
            "risky_commits": len(risky_scores),
            "insufficient_history_for_oversized": insufficient_history,
        }
