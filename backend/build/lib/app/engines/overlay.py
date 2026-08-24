from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any, TypedDict

from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from app.db.models import Coupling, Dependency, Finding, Severity
from app.db.paths import load_path_map
from app.engines.base import Engine
from app.engines.coupling import CONFIDENCE_SCORE, confidence_hint, is_low_confidence
from app.engines.signature import finding_signature

if TYPE_CHECKING:
    # See app/engines/base.py -- app.engines.context imports this module for
    # hidden_dependencies, so a top-level import of RunContext here would be
    # circular.
    from app.engines.context import RunContext

HIGH_DEGREE = 0.65
MED_DEGREE = 0.45
"""Severity thresholds for a hidden-dependency finding, keyed off the same
coupling_degree CouplingEngine already computed (which enforces >= 0.30 as
the floor for a pair to exist at all -- see app/engines/coupling.py)."""


class HiddenDependency(TypedDict):
    file_a_path: str
    file_b_path: str
    path_a_id: int
    path_b_id: int
    shared_revs: int
    coupling_degree: float
    severity: Severity
    confidence_hint: str
    confidence_score: float


def compute_hidden_dependencies(
    repo_id: uuid.UUID, run_id: uuid.UUID, session: Session
) -> list[HiddenDependency]:
    """Coupling pairs with no structural edge between them (in either
    direction), sorted by coupling_degree desc.

    Pure join over `coupling` (filtered to this ``run_id`` -- the table
    holds rows from every past run of this repo, see Coupling's docstring in
    app/db/models.py) and `dependencies` (Facts, repo_id-scoped only),
    recomputing neither. The membership check itself runs entirely in
    integer path-id space (no string join needed); path strings are only
    resolved, via ``load_path_map``, for the pairs that actually surface as
    hidden -- used for a finding's title/detail text and the
    hidden-dependencies API response. Shared by OverlayEngine (persists
    these as findings) and the hidden-dependencies API endpoint (returns
    them directly, structured -- the findings row's free-text title/detail
    isn't meant to be parsed back by a client).
    """
    coupling_rows = session.execute(
        select(
            Coupling.path_a_id,
            Coupling.path_b_id,
            Coupling.shared_revs,
            Coupling.coupling_degree,
        ).where(Coupling.repo_id == repo_id, Coupling.analysis_run_id == run_id)
    ).all()
    if not coupling_rows:
        return []

    structural_pairs = {
        frozenset((row.from_path_id, row.to_path_id))
        for row in session.execute(
            select(Dependency.from_path_id, Dependency.to_path_id).where(
                Dependency.repo_id == repo_id
            )
        ).all()
    }

    low_confidence_repo = is_low_confidence(run_id, session)
    path_map = load_path_map(repo_id, session)

    hidden: list[HiddenDependency] = []
    for row in coupling_rows:
        if frozenset((row.path_a_id, row.path_b_id)) in structural_pairs:
            continue  # a real import exists between them -- not hidden

        if row.coupling_degree >= HIGH_DEGREE:
            severity = Severity.high
        elif row.coupling_degree >= MED_DEGREE:
            severity = Severity.med
        else:
            severity = Severity.low

        hint = confidence_hint(row.shared_revs, low_confidence_repo)
        hidden.append(
            {
                "file_a_path": path_map[row.path_a_id],
                "file_b_path": path_map[row.path_b_id],
                "path_a_id": row.path_a_id,
                "path_b_id": row.path_b_id,
                "shared_revs": row.shared_revs,
                "coupling_degree": row.coupling_degree,
                "severity": severity,
                "confidence_hint": hint,
                "confidence_score": CONFIDENCE_SCORE[hint],
            }
        )

    # coupling_degree desc -- the strongest, most surprising hidden
    # couplings surface first (master-context.md sec 7).
    hidden.sort(key=lambda h: h["coupling_degree"], reverse=True)
    return hidden


class OverlayEngine(Engine):
    """The money insight (master-context.md sec 5): for every coupling pair
    with NO structural import edge between the two files, in either
    direction, record a `hidden_dependency` finding -- the refactor
    candidates the architecture diagram is lying about.

    Pure join over `coupling` and `dependencies`; runs after CouplingEngine
    and ArchEngine have persisted their outputs, recomputes neither.
    """

    def run(self, ctx: RunContext, session: Session) -> dict[str, Any]:
        repo_id, run_id = ctx.repo_id, ctx.run_id
        hidden = ctx.hidden_dependencies(session)

        findings = [
            {
                "analysis_run_id": run_id,
                "repo_id": repo_id,
                "category": "hidden_dependency",
                "severity": h["severity"],
                "confidence": h["confidence_score"],
                "path_id": h["path_a_id"],
                "evidence_sha": None,
                "title": f"Hidden dependency: {h['file_a_path']} <-> {h['file_b_path']}",
                "detail": (
                    f"These files change together in {h['shared_revs']} commits "
                    f"(coupling_degree={h['coupling_degree']:.2f}) but neither imports the other."
                ),
                "rank": rank,
                "signature": finding_signature(
                    "hidden_dependency",
                    "|".join(sorted((h["file_a_path"], h["file_b_path"]))),
                ),
            }
            for rank, h in enumerate(hidden)
        ]

        if findings:
            session.execute(insert(Finding), findings)

        return {"hidden_dependencies_found": len(findings)}
