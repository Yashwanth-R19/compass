"""The fact pack -- the structural enforcement of narrative rule 1 ("the
model only phrases facts already computed and already rendered on screen")
and rule 4 ("prompts contain only already-computed numbers... never source
code, file contents, commit diffs, commit messages, or a token").

The rebuild (plan/REBUILD.md D17/§8.2) collapsed the narrative layer's three
former surfaces (passport / risk_file / security) into a single, explicitly
user-triggered "Explain this repo" action. ``RepoFactPack`` is the one fact
pack that replaces all three: it aggregates the counts and scores those three
used to cover, whole-repo, rather than per-file or per-section.

A fact pack is a **strictly-typed Pydantic model containing ONLY computed
numbers and labels that are already displayed somewhere in the product.**
Every field is one of: a plain ``int``/``float``/``bool``, or a
``Literal[...]`` of a small, fixed set of string labels (the literal
``"heuristic"`` calibration tag). There is no field anywhere in this module
capable of holding a file path, a contributor's name, a commit message, or
any other free-text string that originated inside the analyzed repository --
``validate_factpack_allowlist`` below checks this structurally, not just by
code review, precisely so a future session adding a field can't quietly
reintroduce one.

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
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.baseline.provider import calibration_label
from app.db.models import (
    AnalysisStage,
    Finding,
    RepoPassport,
    SecretHit,
    StageStatus,
    Vulnerability,
)

Calibration = Literal["heuristic", "corpus"]

# A stage counts as "resolved" for fact-pack purposes using the exact same
# terminal-status set app/api/analysis.py::_pending_response treats as
# terminal for the 202 contract (done/skipped/failed) -- a fact pack must
# never be built from a stage that could still change under it.
_TERMINAL_STAGE_STATUSES = (StageStatus.done, StageStatus.skipped, StageStatus.failed)


class RepoFactPack(BaseModel):
    """Counts and scores only, mirroring numbers already rendered on the
    Overview/Findings surfaces -- health score, difficulty, subsystem count,
    file count, commit count, contributor count, truck factor,
    hidden-dependency count, cycle count, high-risk ratio, finding counts by
    severity, secret counts (in-head vs history-only), vulnerability counts
    by severity, calibration label. Deliberately excludes the repo's own
    name/owner/URL, contributor names, subsystem labels, file paths, and
    package names -- all repository-authored strings, even though several of
    them are on screen too (rule 1 only requires that a fact pack never
    contain something NOT on screen, not that every on-screen field be
    included)."""

    calibration: Calibration
    file_count: int
    loc: int
    commit_count: int
    contributor_count: int
    subsystem_count: int
    truck_factor: int
    health_score: float
    high_risk_ratio: float
    cycle_count: int
    hidden_dependency_count: int
    onboarding_difficulty: float
    finding_count_high: int
    finding_count_med: int
    finding_count_low: int
    secret_count_still_in_head: int
    secret_count_history_only: int
    vulnerability_count_high: int
    vulnerability_count_med: int
    vulnerability_count_low: int
    vulnerability_count_unknown: int


# ---------------------------------------------------------------------------
# The field-type allowlist -- structural, not a convention.
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
# The builder -- session + repo id + run id in, a fact pack (or None, when
# the underlying data isn't ready yet) out.
# ---------------------------------------------------------------------------


def build_repo_factpack(
    session: Session, repo_id: uuid.UUID, run_id: uuid.UUID
) -> RepoFactPack | None:
    """Reads the already-persisted ``repo_passport`` row for this run (never
    recomputes anything, and never imports ``app.engines.passport`` -- the
    JSONB ``data`` column comes back as a plain dict; indexing the few keys
    this fact pack needs avoids depending on that engine module at all) plus
    finding/secret/vulnerability counts.

    Returns ``None`` (the caller renders that as "unavailable", never a 500)
    until BOTH the "onboarding" stage (via the ``repo_passport`` row itself)
    AND the "security" stage have reached a terminal status for this run --
    "security" runs immediately before "rank", after every other
    finding-emitting engine, so by the time it's terminal every finding this
    run will ever emit has already been written; reading the vulnerability
    count any earlier would honestly-but-wrongly report 0 for a stage that
    simply hasn't run yet."""
    passport_row = session.scalar(
        select(RepoPassport).where(RepoPassport.analysis_run_id == run_id)
    )
    if passport_row is None:
        return None

    security_stage = session.scalar(
        select(AnalysisStage).where(
            AnalysisStage.run_id == run_id, AnalysisStage.name == "security"
        )
    )
    if security_stage is None or security_stage.status not in _TERMINAL_STAGE_STATUSES:
        return None

    data = passport_row.data
    scale = data["scale"]
    team = data["team"]
    health = data["health"]

    finding_rows = session.scalars(
        select(Finding.severity).where(Finding.analysis_run_id == run_id)
    ).all()
    finding_counts = {"high": 0, "med": 0, "low": 0}
    for severity in finding_rows:
        if severity.value in finding_counts:
            finding_counts[severity.value] += 1

    secret_rows = session.scalars(select(SecretHit).where(SecretHit.repo_id == repo_id)).all()
    still_in_head = sum(1 for h in secret_rows if h.still_in_head)

    vuln_rows = session.scalars(
        select(Vulnerability).where(Vulnerability.analysis_run_id == run_id)
    ).all()
    vuln_counts = {"high": 0, "med": 0, "low": 0, "unknown": 0}
    for v in vuln_rows:
        key = v.severity if v.severity in vuln_counts else "unknown"
        vuln_counts[key] += 1

    return RepoFactPack(
        calibration=calibration_label(),  # type: ignore[arg-type]
        file_count=scale["files"],
        loc=scale["loc"],
        commit_count=scale["commits"],
        contributor_count=scale["contributors"],
        subsystem_count=scale["subsystems"],
        truck_factor=team["truck_factor"],
        health_score=health["score"],
        high_risk_ratio=health["high_risk_ratio"],
        cycle_count=health["cycle_count"],
        hidden_dependency_count=health["hidden_dependency_count"],
        onboarding_difficulty=passport_row.onboarding_difficulty,
        finding_count_high=finding_counts["high"],
        finding_count_med=finding_counts["med"],
        finding_count_low=finding_counts["low"],
        secret_count_still_in_head=still_in_head,
        secret_count_history_only=len(secret_rows) - still_in_head,
        vulnerability_count_high=vuln_counts["high"],
        vulnerability_count_med=vuln_counts["med"],
        vulnerability_count_low=vuln_counts["low"],
        vulnerability_count_unknown=vuln_counts["unknown"],
    )


__all__ = [
    "Calibration",
    "RepoFactPack",
    "build_repo_factpack",
    "validate_factpack_allowlist",
]
