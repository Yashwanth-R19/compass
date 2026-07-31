import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Finding, Severity
from app.engines.base import Engine

SEVERITY_WEIGHT: dict[Severity, int] = {Severity.high: 3, Severity.med: 2, Severity.low: 1}
"""Primary sort key for the global, cross-category findings rank (the
anti-alert-fatigue contract, master-context.md sec 7 / decision 5). Distinct
from ArchEngine's local _SEVERITY_WEIGHT (which starts at 0 and only orders
that engine's own findings against each other before this pass runs) --
these start at 1 so severity always dominates impact_score regardless of
confidence."""


def impact_score(severity: Severity, confidence: float) -> float:
    """severity is the PRIMARY sort key; confidence only breaks ties within
    the same severity band -- a low-confidence high-severity finding still
    outranks a high-confidence low-severity one, because severity*10 always
    dwarfs a confidence delta bounded to [0, 1]. Exported so the findings API
    and tests can recompute/assert the same ordering without duplicating the
    weight table.
    """
    return SEVERITY_WEIGHT[severity] * 10 + confidence


class FindingsRankEngine(Engine):
    """Finalizes the single, global, cross-category rank on the unified
    ``findings`` table (master-context.md sec 7 / sec 9 decision 5).

    Every emitter (Risk, ArchEngine, OverlayEngine) writes its findings with
    a LOCAL rank (0..n-1 within its own category) because it runs before the
    others and has no view of the rest. This runs last, after every other
    engine has written its findings for this run_id, and overwrites ``rank``
    with one global ordering by impact_score across all categories -- so the
    findings API can return "top findings" as a single ranked list without
    the client ever needing to know about categories. Filters by
    ``analysis_run_id``, not ``repo_id`` -- findings holds rows from every
    past run of this repo too (Phase 02), and ranking must stay scoped to
    the run currently being computed.
    """

    def run(self, repo_id: uuid.UUID, run_id: uuid.UUID, session: Session) -> dict[str, Any]:
        findings = session.scalars(select(Finding).where(Finding.analysis_run_id == run_id)).all()
        if not findings:
            return {"findings_ranked": 0}

        ordered = sorted(
            findings, key=lambda f: impact_score(f.severity, f.confidence), reverse=True
        )
        for rank, finding in enumerate(ordered):
            finding.rank = rank

        return {"findings_ranked": len(ordered)}
