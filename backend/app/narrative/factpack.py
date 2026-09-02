"""Fact packs -- the structural enforcement of narrative rule 1 ("the model
only phrases facts already computed and already rendered on the same
screen") and rule 4 ("prompts contain only already-computed numbers... never
source code, file contents, commit diffs, commit messages, or a token").

A fact pack is a **strictly-typed Pydantic model containing ONLY computed
numbers and labels that are already displayed on the corresponding page.**
Every field is one of: a plain ``int``/``float``/``bool``, or a
``Literal[...]`` of a small, fixed set of string labels (a language name, a
test classification, the literal ``"heuristic"`` calibration tag). There is
no field anywhere in this module capable of holding a file path, a
contributor's name, a commit message, or any other free-text string that
originated inside the analyzed repository -- ``validate_factpack_allowlist``
below checks this structurally, not just by code review, precisely so a
future session adding a field can't quietly reintroduce one.

**This deliberately excludes some data the pages it mirrors actually
display** (a file path, a contributor's name, a subsystem label). Rule 1
only requires that a fact pack never contain something NOT on screen; it
does not require every on-screen field to be included. Any field whose value
could be repository-authored free text is left out entirely rather than
threaded through with an escape hatch -- the intersection of "on screen" and
"safe to ever hand to a third-party API" is exactly what a fact pack is.

**Builders have no import path to ``app.ingestion`` or ``app.security``.**
They read only the DB tables they need (``app/db/models.py``) -- this is
what makes "a builder cannot see file contents, commit messages, diffs, or
the clone" true by construction rather than by convention:
``app.ingestion``/``app.security`` are the only places in this codebase that
ever touch a clone or a commit message/diff at all, so a module with no
import path to either literally cannot reach that data.
``tests/test_narrative_factpack.py`` greps this file's own source for both
import prefixes and fails loudly if either ever appears.
"""

from __future__ import annotations

import types
import uuid
from typing import Literal, Union, get_args, get_origin

from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db.models import (
    AnalysisStage,
    Contributor,
    Coupling,
    File,
    FileExpertise,
    FileMetrics,
    RepoPassport,
    SecretHit,
    StageStatus,
    Vulnerability,
)

Language = Literal["python", "javascript", "typescript", "java", "other"]
Calibration = Literal["heuristic"]
TestClassification = Literal["no_test", "stale_test", "tracked"]

_KNOWN_LANGUAGES: tuple[str, ...] = ("python", "javascript", "typescript", "java", "other")
_KNOWN_TEST_CLASSIFICATIONS: tuple[str, ...] = ("no_test", "stale_test", "tracked")

# A stage counts as "resolved" for fact-pack purposes using the exact same
# terminal-status set app/api/analysis.py::_pending_response treats as
# terminal for the 202 contract (done/skipped/failed) -- a fact pack must
# never be built from a stage that could still change under it.
_TERMINAL_STAGE_STATUSES = (StageStatus.done, StageStatus.skipped, StageStatus.failed)


class PassportFactPack(BaseModel):
    """Mirrors the numeric/boolean/enum subset of ``PassportResponse``
    (``app/schemas/analysis.py``) -- every field here is already rendered
    somewhere on ``PassportPage.tsx``. Deliberately excludes: the repo's
    name/owner/URL, contributor names, subsystem labels, entry-point paths,
    hotspot file paths, license SPDX id -- all repository-authored strings,
    even though every one of them is on screen too."""

    onboarding_difficulty: float
    calibration: Calibration
    file_count: int
    loc: int
    commit_count: int
    contributor_count: int
    subsystem_count: int
    age_days: float
    commits_last_30d: int
    commits_last_90d: int
    commits_last_365d: int
    is_dormant: bool
    active_contributor_count: int
    stale_contributor_count: int
    bot_commit_ratio: float
    truck_factor: int
    modularity: float
    entry_point_count: int
    top_risk_file_count: int
    churn_concentration: float
    health_score: float
    high_risk_ratio: float
    cycle_count: int
    hidden_dependency_count: int
    primary_language: Language


class RiskFactPack(BaseModel):
    """One file's risk evidence, mirroring ``RiskFileOut`` minus its
    ``file_path`` -- the narrative renders inline next to that specific
    file's already-expanded row (``RiskPage.tsx``), so the file itself never
    needs to be named inside the prompt."""

    risk_score: float
    risk_confidence: float
    hotspot_rank: int
    churn_total: int
    churn_weighted: float
    complexity: float
    commit_count: int
    max_coupling_degree: float
    instability_score: float | None
    revert_cycle_count: int | None
    test_classification: TestClassification | None
    test_cochange_ratio: float | None
    expert_count: int
    is_orphaned_knowledge: bool
    language: Language
    calibration: Calibration


class SecurityFactPack(BaseModel):
    """Counts only, by category and severity -- mirrors the header numbers
    on ``SecurityPage.tsx``. Never a secret's redacted preview, never a
    package name or version string, per the session prompt's explicit
    instruction beyond what a plain count already implies."""

    secret_count_total: int
    secret_count_still_in_head: int
    secret_count_history_only: int
    vulnerability_count_total: int
    vulnerability_count_high: int
    vulnerability_count_med: int
    vulnerability_count_low: int
    vulnerability_count_unknown: int
    vulnerability_count_direct: int
    vulnerability_count_transitive: int
    no_supported_manifest: bool
    secrets_truncated: bool


# ---------------------------------------------------------------------------
# The field-type allowlist (Part B) -- structural, not a convention.
# ---------------------------------------------------------------------------


def _unwrap_optional(annotation: object) -> object:
    origin = get_origin(annotation)
    if origin is Union or origin is types.UnionType:
        args = [a for a in get_args(annotation) if a is not type(None)]
        if len(args) == 1:
            return args[0]
    return annotation


def _check_field_type(location: str, annotation: object) -> None:
    annotation = _unwrap_optional(annotation)
    origin = get_origin(annotation)

    if origin is Literal:
        args = get_args(annotation)
        if args and all(isinstance(a, str) for a in args):
            return
        raise TypeError(f"{location}: Literal must be a fixed set of string labels, got {args!r}")

    if isinstance(annotation, type):
        if issubclass(annotation, bool | int | float):
            return
        if issubclass(annotation, BaseModel):
            for nested_name, nested_info in annotation.model_fields.items():
                _check_field_type(f"{location}.{nested_name}", nested_info.annotation)
            return

    raise TypeError(
        f"{location}: field type {annotation!r} is not on the narrative fact-pack "
        "allowlist (number, boolean, or Literal[...] of a fixed set of string "
        "labels). Free text originating from the repository must never reach a "
        "fact pack -- see app/narrative/factpack.py's module docstring."
    )


def validate_factpack_allowlist(model: BaseModel) -> None:
    """Raises ``TypeError``, loudly, the moment ``model``'s class declares a
    field that isn't a number, a boolean, or a ``Literal[...]`` of a fixed
    set of string labels. Called by ``generate.py::build_prompt`` before any
    prompt is ever built, so a future session that adds a free-text field to
    a fact pack (a file path, a commit message, ...) fails here instead of
    quietly shipping that text to a third-party API."""
    for field_name, field_info in type(model).model_fields.items():
        _check_field_type(f"{type(model).__name__}.{field_name}", field_info.annotation)


# ---------------------------------------------------------------------------
# Builders -- session + run id (+ repo id / subject where needed) in,
# a fact pack (or None, when the underlying data isn't ready/found) out.
# ---------------------------------------------------------------------------


def build_passport_factpack(session: Session, run_id: uuid.UUID) -> PassportFactPack | None:
    """Reads the already-persisted ``repo_passport`` row for this run --
    never recomputes anything, and never imports ``app.engines.passport``
    (the JSONB ``data`` column comes back as a plain dict; indexing the few
    keys this fact pack needs avoids depending on that engine module at
    all)."""
    row = session.scalar(select(RepoPassport).where(RepoPassport.analysis_run_id == run_id))
    if row is None:
        return None

    data = row.data
    identity = data["identity"]
    scale = data["scale"]
    cadence = data["cadence"]
    team = data["team"]
    shape = data["shape"]
    hotspots = data["hotspots"]
    health = data["health"]

    primary_language = identity.get("primary_language", "other")
    if primary_language not in _KNOWN_LANGUAGES:
        primary_language = "other"

    return PassportFactPack(
        onboarding_difficulty=row.onboarding_difficulty,
        calibration="heuristic",
        file_count=scale["files"],
        loc=scale["loc"],
        commit_count=scale["commits"],
        contributor_count=scale["contributors"],
        subsystem_count=scale["subsystems"],
        age_days=scale["age_days"],
        commits_last_30d=cadence["commits_last_30d"],
        commits_last_90d=cadence["commits_last_90d"],
        commits_last_365d=cadence["commits_last_365d"],
        is_dormant=cadence["is_dormant"],
        active_contributor_count=team["active_contributors"],
        stale_contributor_count=team["stale_contributors"],
        bot_commit_ratio=team["bot_commit_ratio"],
        truck_factor=team["truck_factor"],
        modularity=shape["modularity"],
        entry_point_count=len(shape["entry_points"]),
        top_risk_file_count=len(hotspots["top_risk_files"]),
        churn_concentration=hotspots["churn_concentration"],
        health_score=health["score"],
        high_risk_ratio=health["high_risk_ratio"],
        cycle_count=health["cycle_count"],
        hidden_dependency_count=health["hidden_dependency_count"],
        primary_language=primary_language,  # type: ignore[arg-type]
    )


def build_risk_file_factpack(
    session: Session, repo_id: uuid.UUID, run_id: uuid.UUID, file_path: str
) -> RiskFactPack | None:
    """Looks up one file's already-persisted ``file_metrics`` row for this
    run, joined to ``files`` by ``path_id`` (the permanent id -- see
    ``FileMetrics``'s docstring), plus the expert-count/orphaned-knowledge
    fields ``GET /repos/{id}/risk`` computes the same way (a cheap join over
    ``file_expertise``, never stored). Returns ``None`` when the path
    doesn't resolve to a scored file for this run -- the caller renders that
    as "unavailable", never a 500."""
    row = session.execute(
        select(File, FileMetrics)
        .join(
            FileMetrics,
            (FileMetrics.path_id == File.path_id) & (FileMetrics.analysis_run_id == run_id),
        )
        .where(File.repo_id == repo_id, File.path == file_path)
    ).first()
    if row is None:
        return None
    file, metrics = row

    max_coupling_degree = (
        session.scalar(
            select(func.max(Coupling.coupling_degree)).where(
                Coupling.repo_id == repo_id,
                Coupling.analysis_run_id == run_id,
                or_(Coupling.path_a_id == file.path_id, Coupling.path_b_id == file.path_id),
            )
        )
        or 0.0
    )

    expert_rows = session.execute(
        select(Contributor.is_stale)
        .join(FileExpertise, FileExpertise.contributor_id == Contributor.id)
        .where(
            FileExpertise.analysis_run_id == run_id,
            FileExpertise.is_expert.is_(True),
            FileExpertise.path_id == file.path_id,
        )
    ).all()
    expert_count = len(expert_rows)
    is_orphaned_knowledge = expert_count == 1 and bool(expert_rows[0][0])

    language = file.language if file.language in _KNOWN_LANGUAGES else "other"
    classification = (
        metrics.test_classification
        if metrics.test_classification in _KNOWN_TEST_CLASSIFICATIONS
        else None
    )

    return RiskFactPack(
        risk_score=metrics.risk_score or 0.0,
        risk_confidence=metrics.risk_confidence or 0.0,
        hotspot_rank=metrics.hotspot_rank if metrics.hotspot_rank is not None else 0,
        churn_total=file.churn_total,
        churn_weighted=file.churn_weighted,
        complexity=file.complexity,
        commit_count=file.commit_count,
        max_coupling_degree=max_coupling_degree,
        instability_score=metrics.instability_score,
        revert_cycle_count=metrics.revert_cycle_count,
        test_classification=classification,  # type: ignore[arg-type]
        test_cochange_ratio=metrics.test_cochange_ratio,
        expert_count=expert_count,
        is_orphaned_knowledge=is_orphaned_knowledge,
        language=language,  # type: ignore[arg-type]
        calibration="heuristic",
    )


def build_security_factpack(
    session: Session, repo_id: uuid.UUID, run_id: uuid.UUID
) -> SecurityFactPack | None:
    """Counts over ``secret_hits`` (Facts, ``repo_id``-scoped -- history
    scanning doesn't depend on which run is selected, same as
    ``GET /repos/{id}/secrets``) and ``vulnerabilities`` (Insight,
    ``run_id``-scoped). Returns ``None`` until BOTH the "secrets" and
    "security" stages have reached a terminal status for this run (the same
    set ``_pending_response`` treats as terminal) -- otherwise a narrative
    could honestly-but-wrongly claim "0 vulnerabilities" for a stage that
    simply hasn't run yet."""
    secrets_stage = session.scalar(
        select(AnalysisStage).where(AnalysisStage.run_id == run_id, AnalysisStage.name == "secrets")
    )
    security_stage = session.scalar(
        select(AnalysisStage).where(
            AnalysisStage.run_id == run_id, AnalysisStage.name == "security"
        )
    )
    if secrets_stage is None or secrets_stage.status not in _TERMINAL_STAGE_STATUSES:
        return None
    if security_stage is None or security_stage.status not in _TERMINAL_STAGE_STATUSES:
        return None

    structure_stage = session.scalar(
        select(AnalysisStage).where(
            AnalysisStage.run_id == run_id, AnalysisStage.name == "structure"
        )
    )
    manifest_found = bool(
        (structure_stage.summary or {}).get("dependency_manifest_found", False)
        if structure_stage is not None
        else False
    )
    secrets_truncated = bool((secrets_stage.summary or {}).get("truncated", False))

    secret_rows = session.scalars(select(SecretHit).where(SecretHit.repo_id == repo_id)).all()
    vuln_rows = session.scalars(
        select(Vulnerability).where(Vulnerability.analysis_run_id == run_id)
    ).all()

    still_in_head = sum(1 for h in secret_rows if h.still_in_head)
    severity_counts = {"high": 0, "med": 0, "low": 0, "unknown": 0}
    for v in vuln_rows:
        key = v.severity if v.severity in severity_counts else "unknown"
        severity_counts[key] += 1

    return SecurityFactPack(
        secret_count_total=len(secret_rows),
        secret_count_still_in_head=still_in_head,
        secret_count_history_only=len(secret_rows) - still_in_head,
        vulnerability_count_total=len(vuln_rows),
        vulnerability_count_high=severity_counts["high"],
        vulnerability_count_med=severity_counts["med"],
        vulnerability_count_low=severity_counts["low"],
        vulnerability_count_unknown=severity_counts["unknown"],
        vulnerability_count_direct=sum(1 for v in vuln_rows if v.is_direct),
        vulnerability_count_transitive=sum(1 for v in vuln_rows if not v.is_direct),
        no_supported_manifest=not manifest_found,
        secrets_truncated=secrets_truncated,
    )


__all__ = [
    "Calibration",
    "Language",
    "PassportFactPack",
    "RiskFactPack",
    "SecurityFactPack",
    "TestClassification",
    "build_passport_factpack",
    "build_risk_file_factpack",
    "build_security_factpack",
    "validate_factpack_allowlist",
]
