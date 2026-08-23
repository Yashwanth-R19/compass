"""Truck factor via Avelino's greedy removal algorithm (session 05, Part D):
Avelino, Passos, Hora & Valente, "A Novel Approach for Estimating Truck
Factors" (ICPC 2016) -- repeatedly remove the developer who is expert for
the most still-covered files, until more than half the considered files
have lost every expert; the count removed is the truck factor.

Must run AFTER ``ExpertiseEngine`` in the "knowledge" stage
(``app/jobs/stages.py``) -- reads the ``file_expertise``/``contributors``
rows that engine just wrote for this SAME ``run_id``, never recomputes DOA
itself.

This measures the PROJECT's knowledge-distribution risk, not any individual
contributor's importance (plan/RULES.md sec 11.4) -- the API attaches a
fixed interpretation string to every read of this data
(``app/api/analysis.py::KNOWLEDGE_INTERPRETATION_NOTE``).
"""

from __future__ import annotations

import uuid
from collections import Counter
from typing import TYPE_CHECKING, Any

from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from app.db.models import Contributor, FileExpertise, TruckFactor
from app.engines.base import Engine

if TYPE_CHECKING:
    from app.engines.context import RunContext

ORPHAN_STOP_RATIO = 0.50
"""Session 05 Part D step 3: stop once MORE than this fraction of considered
files have no remaining expert -- a strict ">", not ">=" (see the "4 devs,
25% each" worked example in the session spec: removing 2 of 4 crosses
exactly 50%, which must NOT stop the loop yet)."""


def compute_truck_factor(repo_id: uuid.UUID, run_id: uuid.UUID, session: Session) -> dict[str, Any]:
    contributors = session.execute(
        select(
            Contributor.id, Contributor.canonical_name, Contributor.rank, Contributor.is_stale
        ).where(Contributor.analysis_run_id == run_id, Contributor.is_bot.is_(False))
    ).all()
    contributor_info = {c.id: (c.canonical_name, c.rank) for c in contributors}
    stale_by_id = {c.id: c.is_stale for c in contributors}

    expert_rows = session.execute(
        select(FileExpertise.path_id, FileExpertise.contributor_id).where(
            FileExpertise.analysis_run_id == run_id, FileExpertise.is_expert.is_(True)
        )
    ).all()

    experts_by_file: dict[int, set[int]] = {}
    for path_id, contributor_id in expert_rows:
        experts_by_file.setdefault(path_id, set()).add(contributor_id)

    total_files_considered = len(experts_by_file)

    orphaned_file_count = sum(
        1
        for experts in experts_by_file.values()
        if len(experts) == 1 and stale_by_id.get(next(iter(experts)), False)
    )

    # Degenerate case 1 (Part D): no file has any expert at all -- authorship
    # is too diffuse to compute a meaningful truck factor.
    if total_files_considered == 0:
        return {
            "value": 0,
            "removal_order": [],
            "total_files_considered": 0,
            "orphaned_file_count": 0,
            "note": (
                "No file in this repository has a clear expert -- knowledge is too "
                "diffuse to compute a meaningful truck factor."
            ),
        }

    # Degenerate case 2: exactly one (non-bot) contributor has ever reached
    # expert status anywhere -- truck factor 1 by definition.
    if len(contributor_info) == 1:
        (only_id,) = contributor_info.keys()
        name, _rank = contributor_info[only_id]
        return {
            "value": 1,
            "removal_order": [
                {
                    "contributor_id": only_id,
                    "name": name,
                    "files_orphaned": total_files_considered,
                    "cumulative_orphan_ratio": 1.0,
                }
            ],
            "total_files_considered": total_files_considered,
            "orphaned_file_count": orphaned_file_count,
            "note": (
                "Only one contributor has ever reached expert status in this "
                "repository -- the project's knowledge is not distributed at all."
            ),
        }

    remaining_experts: dict[int, set[int]] = {pid: set(e) for pid, e in experts_by_file.items()}
    removed: set[int] = set()
    removal_order: list[dict[str, Any]] = []

    # Known Hazard #4: unconditionally remove one developer per iteration
    # (never skip a no-progress iteration), capped at the contributor count
    # as a safety net -- the loop provably terminates via the ratio check
    # well before this cap is ever reached (removing every contributor
    # necessarily drives every file's remaining-expert set to empty, i.e.
    # ratio=1.0, which always exceeds ORPHAN_STOP_RATIO).
    for _ in range(len(contributor_info)):
        coverage: Counter[int] = Counter()
        for experts in remaining_experts.values():
            for cid in experts:
                if cid not in removed:
                    coverage[cid] += 1

        candidates = [cid for cid in contributor_info if cid not in removed and coverage[cid] > 0]
        if not candidates:
            break

        # Deterministic tie-break (Part D step 2): coverage desc, then
        # contributor rank asc, then canonical name asc -- an unbroken tie
        # would make the whole result non-reproducible.
        chosen = min(
            candidates,
            key=lambda cid: (-coverage[cid], contributor_info[cid][1], contributor_info[cid][0]),
        )
        removed.add(chosen)
        for experts in remaining_experts.values():
            experts.discard(chosen)

        orphaned_now = sum(1 for experts in remaining_experts.values() if not experts)
        ratio = orphaned_now / total_files_considered
        removal_order.append(
            {
                "contributor_id": chosen,
                "name": contributor_info[chosen][0],
                "files_orphaned": orphaned_now,
                "cumulative_orphan_ratio": ratio,
            }
        )
        if ratio > ORPHAN_STOP_RATIO:
            break

    return {
        "value": len(removal_order),
        "removal_order": removal_order,
        "total_files_considered": total_files_considered,
        "orphaned_file_count": orphaned_file_count,
        "note": None,
    }


class TruckFactorEngine(Engine):
    """Persists one ``truck_factor`` row per run from Avelino's greedy
    removal simulation over this run's ``file_expertise`` -- see module
    docstring and ``compute_truck_factor``."""

    def run(self, ctx: RunContext, session: Session) -> dict[str, Any]:
        result = compute_truck_factor(ctx.repo_id, ctx.run_id, session)

        session.execute(
            insert(TruckFactor).values(
                id=uuid.uuid4(),
                analysis_run_id=ctx.run_id,
                repo_id=ctx.repo_id,
                value=result["value"],
                removal_order=result["removal_order"],
                total_files_considered=result["total_files_considered"],
                orphaned_file_count=result["orphaned_file_count"],
                note=result["note"],
            )
        )

        return {
            "truck_factor": result["value"],
            "total_files_considered": result["total_files_considered"],
            "orphaned_file_count": result["orphaned_file_count"],
        }
