"""The narrative layer's API surface: a single repo-scoped read endpoint,
plus an admin-only pre-generation hook. See ``app/narrative/__init__.py``
and ``master-context.md``'s "Narrative layer" section for the six rules this
whole package answers to.

The rebuild (plan/REBUILD.md D17/§8.2) collapsed the three former surfaces
(passport / risk_file / security) into a single, explicitly user-triggered
"Explain this repo" action -- there is no ``?surface=``/``?subject=`` to
choose between any more; ``GET /repos/{repo_id}/narrative`` always answers
for the whole repository.

This endpoint never raises for "there is no narrative here" in any of its
forms (no keys configured, every key cooling down, a generation that failed
validation, or the underlying computed data not being ready yet) -- every
one of those is ``{"available": false, "reason": ...}`` on a plain 200,
never a 404 or a 500. This is a deliberate simplification for the
frontend's narrative drawer: it can treat the response uniformly without a
second branch for "not ready yet" vs. "there's no LLM available" -- both
are just "nothing to show, render the quiet unavailable line."
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.api.limits import check_narrative_rate_limit
from app.auth.admin import require_admin_token
from app.auth.deps import current_user_optional, require_repo_access
from app.db.base import get_db
from app.db.models import AnalysisRun, Narrative, Repo, User
from app.db.runs import resolve_run_id
from app.narrative import factpack, generate, pool
from app.narrative.factpack import RepoFactPack
from app.schemas.narrative import NarrativeResponse

router = APIRouter()

NARRATIVE_SURFACE = "repo"
"""The one narrative surface that exists post-rebuild -- kept as a named
constant (rather than a bare literal scattered across this module) since
``Narrative.surface``/``.subject_key`` are still real columns (see that
model's docstring for why they weren't dropped)."""

# Postgres' unique index treats NULL as distinct from every other NULL, so a
# bare `subject_key IS NULL` would not stop two concurrent requests from
# both inserting a row for the same run. There being only one surface now
# doesn't change that -- the sentinel stays.
_NO_SUBJECT_SENTINEL = ""


def _factpack_hash(fact_pack: RepoFactPack) -> str:
    payload = json.dumps(fact_pack.model_dump(), sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@router.get("/repos/{repo_id}/narrative", response_model=NarrativeResponse)
def get_narrative(
    request: Request,
    repo_id: uuid.UUID,
    run_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    repo: Repo = Depends(require_repo_access),
    user: User | None = Depends(current_user_optional),
) -> NarrativeResponse:
    resolved_run_id = resolve_run_id(repo, run_id, db)
    if resolved_run_id is None:
        raise HTTPException(status_code=404, detail="No analysis run exists for this repo yet.")

    fact_pack = factpack.build_repo_factpack(db, repo_id, resolved_run_id)
    if fact_pack is None:
        return NarrativeResponse(available=False, reason="disabled")

    current_hash = _factpack_hash(fact_pack)

    cached = db.scalar(
        select(Narrative)
        .where(
            Narrative.analysis_run_id == resolved_run_id,
            Narrative.surface == NARRATIVE_SURFACE,
            Narrative.subject_key == _NO_SUBJECT_SENTINEL,
        )
        .order_by(Narrative.generated_at.desc())
        .limit(1)
    )
    if cached is not None and cached.factpack_hash == current_hash:
        return NarrativeResponse(
            available=True,
            content=cached.content,
            provider=cached.provider,
            model=cached.model,
            generated_at=cached.generated_at.isoformat(),
        )

    # Not cached (or the cached row is stale against a changed fact pack) --
    # about to generate, which is the one path that costs pool/rate-limit
    # quota. A cache hit above never reaches this line.
    if not pool.has_any_keys():
        return NarrativeResponse(available=False, reason="no_keys")

    check_narrative_rate_limit(request, user)

    result = generate.generate_narrative(fact_pack)
    if not result.ok:
        return NarrativeResponse(available=False, reason=result.reason)

    assert result.content is not None
    assert result.provider is not None
    assert result.model is not None
    generated_at = datetime.now(UTC)

    db.execute(
        delete(Narrative).where(
            Narrative.analysis_run_id == resolved_run_id,
            Narrative.surface == NARRATIVE_SURFACE,
            Narrative.subject_key == _NO_SUBJECT_SENTINEL,
        )
    )
    db.add(
        Narrative(
            analysis_run_id=resolved_run_id,
            surface=NARRATIVE_SURFACE,
            subject_key=_NO_SUBJECT_SENTINEL,
            content=result.content,
            provider=result.provider,
            model=result.model,
            factpack_hash=current_hash,
            generated_at=generated_at,
        )
    )
    db.commit()

    return NarrativeResponse(
        available=True,
        content=result.content,
        provider=result.provider,
        model=result.model,
        generated_at=generated_at.isoformat(),
    )


@router.post("/internal/runs/{run_id}/pregenerate-narratives")
def pregenerate_narratives(
    run_id: uuid.UUID,
    db: Session = Depends(get_db),
    _admin: None = Depends(require_admin_token),
) -> dict[str, object]:
    """The showcase-repo hook: generates and caches this run's one repo-level
    narrative so a viewer of a curated showcase repo never triggers a live
    provider call. Silently skips (rather than raising) when the fact pack
    isn't ready yet or generation is rejected/exhausted -- this is a
    best-effort warm-up, not a guarantee."""
    run = db.get(AnalysisRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found.")

    generated: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []

    fact_pack = factpack.build_repo_factpack(db, run.repo_id, run_id)
    if fact_pack is None:
        skipped.append({"surface": NARRATIVE_SURFACE, "reason": "not_ready"})
        return {"generated": generated, "skipped": skipped}

    current_hash = _factpack_hash(fact_pack)
    existing = db.scalar(
        select(Narrative).where(
            Narrative.analysis_run_id == run_id,
            Narrative.surface == NARRATIVE_SURFACE,
            Narrative.subject_key == _NO_SUBJECT_SENTINEL,
        )
    )
    if existing is not None and existing.factpack_hash == current_hash:
        generated.append({"surface": NARRATIVE_SURFACE})
        return {"generated": generated, "skipped": skipped}

    result = generate.generate_narrative(fact_pack)
    if not result.ok:
        skipped.append({"surface": NARRATIVE_SURFACE, "reason": result.reason or ""})
        return {"generated": generated, "skipped": skipped}

    assert result.content is not None
    assert result.provider is not None
    assert result.model is not None
    db.execute(
        delete(Narrative).where(
            Narrative.analysis_run_id == run_id,
            Narrative.surface == NARRATIVE_SURFACE,
            Narrative.subject_key == _NO_SUBJECT_SENTINEL,
        )
    )
    db.add(
        Narrative(
            analysis_run_id=run_id,
            surface=NARRATIVE_SURFACE,
            subject_key=_NO_SUBJECT_SENTINEL,
            content=result.content,
            provider=result.provider,
            model=result.model,
            factpack_hash=current_hash,
            generated_at=datetime.now(UTC),
        )
    )
    db.commit()
    generated.append({"surface": NARRATIVE_SURFACE})

    return {"generated": generated, "skipped": skipped}


__all__ = ["router"]
