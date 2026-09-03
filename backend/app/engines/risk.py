import uuid
from collections import Counter
from typing import Any

from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from app.baseline.base import BaselineProvider
from app.baseline.heuristic import HeuristicBaseline, size_bucket_for
from app.db.models import Commit, Coupling, File, FileMetrics, Finding, Severity
from app.db.paths import load_path_map
from app.engines.base import Engine
from app.engines.context import RunContext
from app.engines.signature import finding_signature

MAX_RISK_FINDINGS = 10
"""Top-N hotspots emitted as findings, not all files -- the anti-alert-
fatigue discipline (master-context.md sec 7) applies to risk the same as
every other category. Every file still gets a persisted file_metrics row and
a hotspot_rank; this only caps what surfaces in the findings stream."""

RISK_HIGH_SEVERITY = 0.70
RISK_MED_SEVERITY = 0.40
"""Severity bands for a risk finding, keyed off the composite risk_score
(itself in [0, 1] since it's a weighted sum of three [0, 1] norm() outputs).
Heuristic, documented, same style as overlay.py's HIGH_DEGREE/MED_DEGREE."""

RISK_CHURN_COMPLEXITY_WEIGHT = 0.60
RISK_COUPLING_WEIGHT = 0.25
RISK_COMMIT_COUNT_WEIGHT = 0.15
"""LOCKED FORMULA weights (master-context.md sec 8.1 / CLAUDE.md release-B
spec) -- named module-level constants (session 2 of the UI rebuild, Part A)
specifically so ``GET /meta/formulas`` can read the real, live values this
engine actually uses instead of a re-typed copy that could silently drift
out of sync with the source. Same three numbers as before this session --
extracting them into named constants is not a formula change."""

RISK_CONFIDENCE_COMMIT_DIVISOR = 10
"""``risk_confidence = min(1, commit_count / RISK_CONFIDENCE_COMMIT_DIVISOR)``
-- independent of risk_score, see below. Named for the same
``/meta/formulas`` reason as the three weights above."""


def max_coupling_by_path(
    repo_id: uuid.UUID, run_id: uuid.UUID, session: Session
) -> dict[str, float]:
    """Max coupling_degree across each file's pairs, keyed by path STRING --
    0.0 for a file with no coupling pairs at all (per the risk-formula spec,
    not just "missing"). ``coupling`` stores integer path ids (Phase 1
    schema diet) AND holds rows from every past run of this repo (Phase 02),
    so this filters to ``run_id`` too, not just ``repo_id`` -- resolved back
    to strings here via ``load_path_map`` since callers (RiskEngine, the
    risk/architecture API) match against ``File.path``.
    """
    rows = session.execute(
        select(Coupling.path_a_id, Coupling.path_b_id, Coupling.coupling_degree).where(
            Coupling.repo_id == repo_id, Coupling.analysis_run_id == run_id
        )
    ).all()
    if not rows:
        return {}

    path_map = load_path_map(repo_id, session)
    max_degree: dict[str, float] = {}
    for a_id, b_id, degree in rows:
        a, b = path_map[a_id], path_map[b_id]
        max_degree[a] = max(max_degree.get(a, 0.0), degree)
        max_degree[b] = max(max_degree.get(b, 0.0), degree)
    return max_degree


def _most_recent_significant_commit_sha(
    repo_id: uuid.UUID, path_id: int, session: Session
) -> str | None:
    """Evidence commit for a risk finding: the most recent commit touching
    this file, preferring an ``is_fix`` commit over a merely-recent one when
    both exist -- "significant" here means "looks like it was fixing
    something", the same conservative is_fix regex flag the miner already
    computes (app/ingestion/miner.py), not a fabricated judgment. Matches via
    ``changed_path_ids`` array containment (Phase 1 schema diet) instead of
    the old commit_files join."""
    row = session.execute(
        select(Commit.sha)
        .where(
            Commit.repo_id == repo_id,
            Commit.changed_path_ids.any(path_id),  # type: ignore[arg-type]
        )
        .order_by(Commit.is_fix.desc(), Commit.committed_at.desc())
        .limit(1)
    ).first()
    return row[0] if row else None


def _risk_severity(risk_score: float) -> Severity:
    if risk_score >= RISK_HIGH_SEVERITY:
        return Severity.high
    if risk_score >= RISK_MED_SEVERITY:
        return Severity.med
    return Severity.low


class RiskEngine(Engine):
    """Heuristic calibrated-style risk (master-context.md sec 8.1): pure
    DB-only, injected with a BaselineProvider so the normalization behind
    ``norm()`` can be swapped for a corpus model in Release C with no
    changes to this engine's structure (master-context.md sec 9, decision 2).

    Reads ``files`` (churn_total/complexity/commit_count, already mined) and
    ``coupling`` (max coupling_degree per file) -- both pure DB reads, no
    git/filesystem access, consistent with every other engine.
    """

    def __init__(self, baseline: BaselineProvider | None = None) -> None:
        self._baseline = baseline or HeuristicBaseline()

    def run(self, ctx: RunContext, session: Session) -> dict[str, Any]:
        repo_id, run_id = ctx.repo_id, ctx.run_id
        files = session.scalars(
            select(File).where(File.repo_id == repo_id, File.is_deleted.is_(False))
        ).all()
        if not files:
            return {"files_scored": 0, "findings_emitted": 0}

        max_coupling = max_coupling_by_path(repo_id, run_id, session)

        # Session 07 (Risk v2): churn_weighted (recency-decayed, computed by
        # the miner -- app/ingestion/miner.py) replaces churn_total as the
        # churn measurement fed into the LOCKED formula below. This is a
        # measurement change the formula itself explicitly permits
        # (master-context.md sec 8.1 / plan/RULES.md sec 3: "you may improve
        # how an input is measured"), not a formula change -- the weights
        # and the three terms are untouched. churn_total is still stored on
        # `files` and surfaced in the /risk API response for comparison.
        churn_x_complexity = [f.churn_weighted * f.complexity for f in files]
        coupling_degrees = [max_coupling.get(f.path, 0.0) for f in files]
        commit_counts = [float(f.commit_count) for f in files]

        # language/size_bucket are cache keys for a future corpus lookup, not
        # something HeuristicBaseline's per-repo min-max varies on today; the
        # repo's single most-common language is a reasonable stand-in for
        # "this repo's language" until a per-file corpus join exists.
        dominant_language = Counter(f.language for f in files).most_common(1)[0][0]
        size_bucket = size_bucket_for(len(files))

        # LOCKED FORMULA (master-context.md sec 8.1 / CLAUDE.md release-B spec)
        # -- exact fixed weights, never invent different numbers here:
        #   risk_score = 0.60 * norm(churn * complexity)
        #              + 0.25 * norm(max_coupling_degree)
        #              + 0.15 * norm(commit_count)
        # "churn" here is churn_weighted (session 07, Risk v2) -- a
        # MEASUREMENT of churn, not a formula change; see the comment above
        # churn_x_complexity's assignment.
        # Churn*complexity gets majority weight because it's the original,
        # most-validated hotspot signal (Tornhill's hotspots work, same
        # code-maat lineage as coupling): files that change a lot AND are
        # complex are disproportionately where bugs cluster -- it's the
        # anchor, not an equal-weight blend. Coupling is a real but secondary
        # contributor (0.25): high hidden coupling means changes ripple
        # (blast-radius risk), which correlates with but isn't the same as
        # defect-proneness, so it earns a supporting role. Commit_count is
        # the smallest weight (0.15), a mild activity/maturity tiebreaker so
        # a file with one lucky low-complexity commit doesn't score
        # identically to the same churn*complexity spread across 50 commits.
        # norm() itself is never hardcoded here -- it comes from the injected
        # BaselineProvider (per-repo min-max today, corpus-calibrated in
        # Release C, same call site either way).
        norm_churn_complexity = self._baseline.risk_normalizer(
            "churn_x_complexity", dominant_language, size_bucket
        )(churn_x_complexity)
        norm_coupling = self._baseline.risk_normalizer(
            "coupling_degree", dominant_language, size_bucket
        )(coupling_degrees)
        norm_commit_count = self._baseline.risk_normalizer(
            "commit_count", dominant_language, size_bucket
        )(commit_counts)

        risk_scores = [
            RISK_CHURN_COMPLEXITY_WEIGHT * c
            + RISK_COUPLING_WEIGHT * k
            + RISK_COMMIT_COUNT_WEIGHT * m
            for c, k, m in zip(
                norm_churn_complexity, norm_coupling, norm_commit_count, strict=False
            )
        ]

        # risk_confidence is INDEPENDENT of risk_score -- not part of the
        # weighted sum above. An honest signal of how much history backs the
        # score: a file can be high-risk and low-confidence at once, and the
        # UI must be able to show both (master-context.md sec 8.1).
        risk_confidences = [
            min(1.0, f.commit_count / RISK_CONFIDENCE_COMMIT_DIVISOR) for f in files
        ]

        # hotspot_rank: descending risk_score, ties broken by insertion order
        # (stable sort) -- no secondary criterion specified, so don't invent one.
        order = sorted(range(len(files)), key=lambda i: risk_scores[i], reverse=True)
        hotspot_rank = [0] * len(files)
        for rank, i in enumerate(order):
            hotspot_rank[i] = rank

        metrics_rows = [
            {
                "analysis_run_id": run_id,
                "repo_id": repo_id,
                "path_id": files[i].path_id,
                "risk_score": risk_scores[i],
                "risk_confidence": risk_confidences[i],
                "hotspot_rank": hotspot_rank[i],
            }
            for i in range(len(files))
        ]
        session.execute(insert(FileMetrics), metrics_rows)

        top_indices = order[:MAX_RISK_FINDINGS]
        findings = []
        for rank, i in enumerate(top_indices):
            f = files[i]
            evidence_sha = _most_recent_significant_commit_sha(repo_id, f.path_id, session)
            findings.append(
                {
                    "analysis_run_id": run_id,
                    "repo_id": repo_id,
                    "category": "risk",
                    "severity": _risk_severity(risk_scores[i]),
                    "confidence": risk_confidences[i],
                    "path_id": f.path_id,
                    "evidence_sha": evidence_sha,
                    "title": f"Hotspot: {f.path}",
                    "detail": (
                        f"risk_score={risk_scores[i]:.2f} "
                        f"(churn_weighted={f.churn_weighted:.0f}, churn_total={f.churn_total}, "
                        f"complexity={f.complexity:.1f}, max_coupling_degree={coupling_degrees[i]:.2f}, "
                        f"commit_count={f.commit_count})."
                    ),
                    "rank": rank,
                    "signature": finding_signature("risk", f.path),
                }
            )
        if findings:
            session.execute(insert(Finding), findings)

        return {"files_scored": len(files), "findings_emitted": len(findings)}
