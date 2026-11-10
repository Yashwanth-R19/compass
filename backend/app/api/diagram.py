"""The Map surface's API: the computed diagram, plus the optional, on-demand
AI labelling for it (and an admin-only pre-generation hook for showcase
repos).

``GET /repos/{id}/diagram`` computes nothing new -- it is a read-time join
and aggregation of already-persisted Facts/Insight (see
``app/analysis/diagram.py``), deterministic for a given run and grouping.

``GET /repos/{id}/diagram/ai`` mirrors ``app/api/narrative.py`` exactly in
shape: a cache hit costs nothing and is never rate-limited; a cache miss
goes through the SAME narrative rate limiter and key pool; every "nothing to
show" outcome is a plain 200 with ``available=false`` and a reason, never a
202/404/500 -- the Map renders fully without it.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.analysis.diagram import build_diagram
from app.api.analysis import _pending_response, _resolve_run_or_404
from app.api.limits import check_narrative_rate_limit
from app.auth.admin import require_admin_token
from app.auth.deps import current_user_optional, require_repo_access
from app.db.base import get_db
from app.db.models import AnalysisRun, Narrative, Repo, User
from app.db.runs import resolve_run_id
from app.narrative import diagram_ai, pool
from app.schemas.diagram import DiagramAiPayload, DiagramAiResponse, DiagramResponse

router = APIRouter()

DIAGRAM_SURFACE = "diagram"
"""``narratives.surface`` for cached Map labelling; ``subject_key`` is the
grouping ("subsystem"/"folder"), so each grouping caches separately."""

_GROUPINGS = ("subsystem", "folder")


def _validate_grouping(grouping: str) -> None:
    if grouping not in _GROUPINGS:
        raise HTTPException(status_code=422, detail="grouping must be 'subsystem' or 'folder'.")


def _fact_pack_hash(fact_pack: diagram_ai.DiagramFactPack) -> str:
    payload = json.dumps(fact_pack.model_dump(), sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _cached_payload(
    db: Session, run_id: uuid.UUID, grouping: str, current_hash: str
) -> tuple[Narrative, DiagramAiPayload] | None:
    cached = db.scalar(
        select(Narrative)
        .where(
            Narrative.analysis_run_id == run_id,
            Narrative.surface == DIAGRAM_SURFACE,
            Narrative.subject_key == grouping,
        )
        .order_by(Narrative.generated_at.desc())
        .limit(1)
    )
    if cached is None or cached.factpack_hash != current_hash:
        return None
    try:
        return cached, DiagramAiPayload.model_validate_json(cached.content)
    except ValidationError:
        # An unparseable cached row is treated as a miss, never served.
        return None


def _store_payload(
    db: Session,
    run_id: uuid.UUID,
    grouping: str,
    result: diagram_ai.DiagramAiResult,
    current_hash: str,
) -> datetime:
    assert result.payload is not None
    assert result.provider is not None
    assert result.model is not None
    generated_at = datetime.now(UTC)
    db.execute(
        delete(Narrative).where(
            Narrative.analysis_run_id == run_id,
            Narrative.surface == DIAGRAM_SURFACE,
            Narrative.subject_key == grouping,
        )
    )
    db.add(
        Narrative(
            analysis_run_id=run_id,
            surface=DIAGRAM_SURFACE,
            subject_key=grouping,
            content=result.payload.model_dump_json(),
            provider=result.provider,
            model=result.model,
            factpack_hash=current_hash,
            generated_at=generated_at,
        )
    )
    db.commit()
    return generated_at


@router.get("/repos/{repo_id}/diagram", response_model=DiagramResponse)
def get_diagram(
    repo_id: uuid.UUID,
    grouping: str = "subsystem",
    run_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    repo: Repo = Depends(require_repo_access),
) -> DiagramResponse | JSONResponse:
    """The Map's computed diagram for the resolved run. Gated on the
    "architecture" stage, which runs after "coupling" and "subsystems" and
    produces entry points/hidden dependencies -- so it gates every input
    this response reads at once."""
    _validate_grouping(grouping)
    resolved_run_id = _resolve_run_or_404(repo, run_id, db)
    pending = _pending_response(resolved_run_id, "architecture", db)
    if pending is not None:
        return pending
    return build_diagram(repo, resolved_run_id, grouping, db)


@router.get("/repos/{repo_id}/diagram/ai", response_model=DiagramAiResponse)
def get_diagram_ai(
    request: Request,
    repo_id: uuid.UUID,
    grouping: str = "subsystem",
    run_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    repo: Repo = Depends(require_repo_access),
    user: User | None = Depends(current_user_optional),
) -> DiagramAiResponse:
    _validate_grouping(grouping)
    resolved_run_id = resolve_run_id(repo, run_id, db)
    if resolved_run_id is None:
        raise HTTPException(status_code=404, detail="No analysis run exists for this repo yet.")

    def _unavailable(reason: str) -> DiagramAiResponse:
        return DiagramAiResponse.model_validate(
            {"available": False, "reason": reason, "grouping": grouping}
        )

    if _pending_response(resolved_run_id, "architecture", db) is not None:
        return _unavailable("disabled")

    diagram = build_diagram(repo, resolved_run_id, grouping, db)
    if diagram.facts_archived or not diagram.groups:
        return _unavailable("disabled")

    fact_pack = diagram_ai.build_fact_pack(diagram, repo, db)
    current_hash = _fact_pack_hash(fact_pack)

    hit = _cached_payload(db, resolved_run_id, grouping, current_hash)
    if hit is not None:
        cached, payload = hit
        return DiagramAiResponse.model_validate(
            {
                "available": True,
                "provider": cached.provider,
                "model": cached.model,
                "generated_at": cached.generated_at.isoformat(),
                "grouping": grouping,
                "payload": payload,
            }
        )

    if not pool.has_any_keys():
        return _unavailable("no_keys")

    # The one path that spends provider quota -- shares the narrative limiter.
    check_narrative_rate_limit(request, user)

    result = diagram_ai.generate_diagram_ai(fact_pack)
    if not result.ok:
        return _unavailable(result.reason or "rejected")

    generated_at = _store_payload(db, resolved_run_id, grouping, result, current_hash)
    return DiagramAiResponse.model_validate(
        {
            "available": True,
            "provider": result.provider,
            "model": result.model,
            "generated_at": generated_at.isoformat(),
            "grouping": grouping,
            "payload": result.payload,
        }
    )


@router.post("/internal/runs/{run_id}/pregenerate-diagram-ai")
def pregenerate_diagram_ai(
    run_id: uuid.UUID,
    db: Session = Depends(get_db),
    _admin: None = Depends(require_admin_token),
) -> dict[str, object]:
    """Showcase warm-up, same contract as ``pregenerate_narratives``:
    best-effort, never rate-limited, skips rather than raises."""
    run = db.get(AnalysisRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    repo = db.get(Repo, run.repo_id)
    if repo is None:
        raise HTTPException(status_code=404, detail="Repo not found.")

    generated: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    for grouping in _GROUPINGS:
        if _pending_response(run_id, "architecture", db) is not None:
            skipped.append({"grouping": grouping, "reason": "not_ready"})
            continue
        diagram = build_diagram(repo, run_id, grouping, db)
        if diagram.facts_archived or not diagram.groups:
            skipped.append({"grouping": grouping, "reason": "not_ready"})
            continue
        fact_pack = diagram_ai.build_fact_pack(diagram, repo, db)
        current_hash = _fact_pack_hash(fact_pack)
        if _cached_payload(db, run_id, grouping, current_hash) is not None:
            generated.append({"grouping": grouping})
            continue
        result = diagram_ai.generate_diagram_ai(fact_pack)
        if not result.ok:
            skipped.append({"grouping": grouping, "reason": result.reason or ""})
            continue
        _store_payload(db, run_id, grouping, result, current_hash)
        generated.append({"grouping": grouping})

    return {"generated": generated, "skipped": skipped}


__all__ = ["router"]
