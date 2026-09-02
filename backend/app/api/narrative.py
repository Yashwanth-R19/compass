"""The narrative layer's API surface (session 12, Part E): a single
repo-scoped read endpoint, plus session 16's admin-only pre-generation hook.
See ``app/narrative/__init__.py`` and ``CLAUDE.md``'s "Narrative layer"
section for the six rules this whole package answers to.

``GET /repos/{repo_id}/narrative`` never raises for "there is no narrative
here" in any of its forms (no keys configured, every key cooling down, a
generation that failed validation, or the underlying computed data for this
surface/subject not being ready yet) -- every one of those is
``{"available": false, "reason": ...}`` on a plain 200, never a 404 or a
500. This is a deliberate simplification for ``NarrativeBlock`` on the
frontend: it can treat the response uniformly without a second branch for
"this specific subject doesn't exist yet" vs. "there's no LLM available" --
both are just "nothing to show, render the quiet unavailable line." A
genuinely malformed request (an unknown ``surface`` value, or a missing
``subject`` for ``risk_file``) is still a real 422 -- that's a caller bug,
not a data-availability question.
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
from app.db.models import AnalysisRun, File, FileMetrics, Narrative, Repo, User
from app.db.runs import resolve_run_id
from app.narrative import factpack, generate, pool
from app.narrative.factpack import PassportFactPack, RiskFactPack, SecurityFactPack
from app.schemas.narrative import NarrativeResponse

router = APIRouter()

_VALID_SURFACES = ("passport", "risk_file", "security")

# Postgres' unique index treats NULL as distinct from every other NULL, so
# a bare `subject_key IS NULL` would NOT stop two concurrent requests from
# both inserting a row for the same (run, surface) pair with no real
# subject. The two whole-run surfaces (passport/security) store this
# sentinel instead of NULL so the DB's own unique constraint actually does
# its job -- no real file path is ever the empty string, so there is no
# collision risk with `risk_file`'s real subject keys.
_NO_SUBJECT_SENTINEL = ""


def _factpack_hash(fact_pack: PassportFactPack | RiskFactPack | SecurityFactPack) -> str:
    payload = json.dumps(fact_pack.model_dump(), sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _build_factpack(
    surface: str, subject: str | None, repo_id: uuid.UUID, run_id: uuid.UUID, db: Session
) -> PassportFactPack | RiskFactPack | SecurityFactPack | None:
    if surface == "passport":
        return factpack.build_passport_factpack(db, run_id)
    if surface == "security":
        return factpack.build_security_factpack(db, repo_id, run_id)
    # surface == "risk_file" -- validated by the caller before this point.
    assert subject is not None
    return factpack.build_risk_file_factpack(db, repo_id, run_id, subject)


@router.get("/repos/{repo_id}/narrative", response_model=NarrativeResponse)
def get_narrative(
    request: Request,
    repo_id: uuid.UUID,
    surface: str,
    subject: str | None = None,
    run_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    repo: Repo = Depends(require_repo_access),
    user: User | None = Depends(current_user_optional),
) -> NarrativeResponse:
    if surface not in _VALID_SURFACES:
        raise HTTPException(
            status_code=422, detail=f"surface must be one of {', '.join(_VALID_SURFACES)}."
        )
    if surface == "risk_file" and not subject:
        raise HTTPException(
            status_code=422, detail="subject (a file path) is required for surface=risk_file."
        )

    resolved_run_id = resolve_run_id(repo, run_id, db)
    if resolved_run_id is None:
        raise HTTPException(status_code=404, detail="No analysis run exists for this repo yet.")

    subject_key = subject if surface == "risk_file" else _NO_SUBJECT_SENTINEL

    fact_pack = _build_factpack(surface, subject, repo_id, resolved_run_id, db)
    if fact_pack is None:
        return NarrativeResponse(available=False, reason="disabled")

    current_hash = _factpack_hash(fact_pack)

    cached = db.scalar(
        select(Narrative)
        .where(
            Narrative.analysis_run_id == resolved_run_id,
            Narrative.surface == surface,
            Narrative.subject_key == subject_key,
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
            Narrative.surface == surface,
            Narrative.subject_key == subject_key,
        )
    )
    db.add(
        Narrative(
            analysis_run_id=resolved_run_id,
            surface=surface,
            subject_key=subject_key,
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


# Session 06's passport engine already caps hotspot lists at a handful of
# files (PassportEngine); this cap bounds how many `risk_file` narratives
# session 16's pre-generation will pay for per repo, mirroring that same
# "top N, not everything" discipline rather than inventing a new number.
MAX_PREGENERATE_RISK_FILES = 10


@router.post("/internal/runs/{run_id}/pregenerate-narratives")
def pregenerate_narratives(
    run_id: uuid.UUID,
    db: Session = Depends(get_db),
    _admin: None = Depends(require_admin_token),
) -> dict[str, object]:
    """Session 16's showcase-repo hook: generates and caches every narrative
    this run can currently support (passport, security, and the top
    ``MAX_PREGENERATE_RISK_FILES`` risk files by hotspot rank) so a viewer of
    a curated showcase repo never triggers a live provider call. Silently
    skips any surface/subject whose fact pack isn't ready yet or whose
    generation is rejected/exhausted -- this is a best-effort warm-up, not a
    guarantee every surface gets a narrative."""
    run = db.get(AnalysisRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found.")

    generated: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []

    def _try(surface: str, subject: str | None) -> None:
        fact_pack = _build_factpack(surface, subject, run.repo_id, run_id, db)
        if fact_pack is None:
            skipped.append({"surface": surface, "subject": subject or "", "reason": "not_ready"})
            return
        subject_key = subject if surface == "risk_file" else _NO_SUBJECT_SENTINEL
        current_hash = _factpack_hash(fact_pack)
        existing = db.scalar(
            select(Narrative).where(
                Narrative.analysis_run_id == run_id,
                Narrative.surface == surface,
                Narrative.subject_key == subject_key,
            )
        )
        if existing is not None and existing.factpack_hash == current_hash:
            return
        result = generate.generate_narrative(fact_pack)
        if not result.ok:
            skipped.append(
                {"surface": surface, "subject": subject or "", "reason": result.reason or ""}
            )
            return
        assert result.content is not None
        assert result.provider is not None
        assert result.model is not None
        db.execute(
            delete(Narrative).where(
                Narrative.analysis_run_id == run_id,
                Narrative.surface == surface,
                Narrative.subject_key == subject_key,
            )
        )
        db.add(
            Narrative(
                analysis_run_id=run_id,
                surface=surface,
                subject_key=subject_key,
                content=result.content,
                provider=result.provider,
                model=result.model,
                factpack_hash=current_hash,
                generated_at=datetime.now(UTC),
            )
        )
        db.commit()
        generated.append({"surface": surface, "subject": subject or ""})

    _try("passport", None)
    _try("security", None)

    top_files = (
        db.execute(
            select(File.path)
            .join(
                FileMetrics,
                (FileMetrics.path_id == File.path_id) & (FileMetrics.analysis_run_id == run_id),
            )
            .where(File.repo_id == run.repo_id)
            .order_by(FileMetrics.hotspot_rank)
            .limit(MAX_PREGENERATE_RISK_FILES)
        )
        .scalars()
        .all()
    )
    for path in top_files:
        _try("risk_file", path)

    return {"generated": generated, "skipped": skipped}


__all__ = ["router"]
