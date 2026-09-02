"""Run-vs-run compare (session 13, Part E): "risk dropped 12% since last
month; this hotspot cooled; two new hidden dependencies appeared; the truck
factor went from 2 to 3" -- the reason to open Compass a second time.

A pure, read-only computation over TWO ``analysis_runs`` of the SAME
repository -- no snapshotting, no persistence, computed fresh on every
``GET /compare/runs`` request (Part E). Findings are matched by
``findings.signature`` (session 01) rather than fuzzy title comparison,
which is the entire reason that column exists.

``compare_runs`` always treats the CHRONOLOGICALLY EARLIER of the two runs
(by ``started_at``) as "before" and the later as "after", regardless of the
order the caller passed ``run_a``/``run_b`` in -- a user picking two runs in
either order should always see "improved"/"worsened" framed the same way.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    AnalysisRun,
    Contributor,
    Coupling,
    FileMetrics,
    Finding,
    Health,
    RepoPassport,
    SecretHit,
    Subsystem,
    SubsystemMember,
    TruckFactor,
    Vulnerability,
)
from app.db.paths import load_path_map
from app.engines.risk import max_coupling_by_path
from app.schemas.compare import (
    CompareFindingOut,
    CompareResponse,
    ContributorChangeOut,
    CouplingChangeOut,
    FindingsDiffOut,
    HeadlineDeltaOut,
    RiskMoverOut,
    SecurityDiffOut,
    SubsystemChangeOut,
)

MAX_RISK_MOVERS_PER_DIRECTION = 10
"""Part E: "Cap at 10 per direction"."""

MAX_COMPARE_FINDINGS_PER_BUCKET = 20
"""Judgement call (plan/RULES.md sec 2.5): the session prompt doesn't name a
cap for the findings diff, but every other list-producing feature in this
codebase caps and reports an honest total (plan/RULES.md sec 12) -- applying
that same anti-alert-fatigue discipline here rather than returning an
unbounded list on a repo with a large finding count."""

MAX_COMPARE_CONTRIBUTOR_CHANGES = 30
MAX_COMPARE_COUPLING_CHANGES_PER_KIND = 10
"""Same anti-alert-fatigue reasoning as MAX_COMPARE_FINDINGS_PER_BUCKET."""

MIN_SUBSYSTEM_JACCARD = 0.5
"""Part E: "detected by membership Jaccard similarity >= 0.5 between a
subsystem in A and one in B"."""

MIN_COUPLING_CHANGE_DELTA = 0.05
"""HEURISTIC (plan/RULES.md sec 3): a pair whose coupling_degree moved by
less than this between runs is treated as unchanged, not reported as
"strengthened"/"weakened" -- two runs of an otherwise-stable repo will show
tiny floating point-scale drift in shared_revs/avg_revs ratios purely from a
handful of new commits touching unrelated files, and reporting every such
pair as a "change" would bury the pairs whose relationship genuinely
shifted."""


def _headline_delta(
    metric: str,
    label: str,
    before: float | None,
    after: float | None,
    higher_is_better: bool | None,
) -> HeadlineDeltaOut:
    delta = None if before is None or after is None else after - before
    return HeadlineDeltaOut(
        metric=metric,
        label=label,
        before=before,
        after=after,
        delta=delta,
        higher_is_better=higher_is_better,
    )


def _headline_deltas(
    run_before: AnalysisRun, run_after: AnalysisRun, session: Session
) -> list[HeadlineDeltaOut]:
    health_before = session.scalar(select(Health).where(Health.analysis_run_id == run_before.id))
    health_after = session.scalar(select(Health).where(Health.analysis_run_id == run_after.id))
    passport_before = session.scalar(
        select(RepoPassport).where(RepoPassport.analysis_run_id == run_before.id)
    )
    passport_after = session.scalar(
        select(RepoPassport).where(RepoPassport.analysis_run_id == run_after.id)
    )
    truck_before = session.scalar(
        select(TruckFactor).where(TruckFactor.analysis_run_id == run_before.id)
    )
    truck_after = session.scalar(
        select(TruckFactor).where(TruckFactor.analysis_run_id == run_after.id)
    )
    subsystems_before = len(
        session.scalars(
            select(Subsystem.id).where(Subsystem.analysis_run_id == run_before.id)
        ).all()
    )
    subsystems_after = len(
        session.scalars(select(Subsystem.id).where(Subsystem.analysis_run_id == run_after.id)).all()
    )

    return [
        _headline_delta(
            "health_score",
            "Health score",
            health_before.score if health_before else None,
            health_after.score if health_after else None,
            True,
        ),
        _headline_delta(
            "onboarding_difficulty",
            "Onboarding difficulty",
            passport_before.onboarding_difficulty if passport_before else None,
            passport_after.onboarding_difficulty if passport_after else None,
            False,
        ),
        _headline_delta(
            "truck_factor",
            "Truck factor",
            float(truck_before.value) if truck_before else None,
            float(truck_after.value) if truck_after else None,
            True,
        ),
        _headline_delta(
            "high_risk_ratio",
            "High-risk file ratio",
            health_before.high_risk_ratio if health_before else None,
            health_after.high_risk_ratio if health_after else None,
            False,
        ),
        _headline_delta(
            "hidden_dependency_count",
            "Hidden dependencies",
            float(health_before.hidden_dependency_count) if health_before else None,
            float(health_after.hidden_dependency_count) if health_after else None,
            False,
        ),
        _headline_delta(
            "subsystem_count",
            "Subsystems",
            float(subsystems_before),
            float(subsystems_after),
            None,
        ),
    ]


def _risk_movers(
    run_before: AnalysisRun, run_after: AnalysisRun, path_map: dict[int, str], session: Session
) -> tuple[list[RiskMoverOut], list[RiskMoverOut]]:
    metrics_before = {
        r.path_id: r
        for r in session.scalars(
            select(FileMetrics).where(FileMetrics.analysis_run_id == run_before.id)
        ).all()
    }
    metrics_after = {
        r.path_id: r
        for r in session.scalars(
            select(FileMetrics).where(FileMetrics.analysis_run_id == run_after.id)
        ).all()
    }
    coupling_before = max_coupling_by_path(run_before.repo_id, run_before.id, session)
    coupling_after = max_coupling_by_path(run_after.repo_id, run_after.id, session)

    movers: list[RiskMoverOut] = []
    for path_id in set(metrics_before) & set(metrics_after):
        before, after = metrics_before[path_id], metrics_after[path_id]
        if before.hotspot_rank is None or after.hotspot_rank is None:
            continue
        path = path_map.get(path_id)
        if path is None:
            continue
        rank_delta = before.hotspot_rank - after.hotspot_rank  # positive = moved toward worse
        risk_before = before.risk_score or 0.0
        risk_after = after.risk_score or 0.0
        movers.append(
            RiskMoverOut(
                file_path=path,
                hotspot_rank_before=before.hotspot_rank,
                hotspot_rank_after=after.hotspot_rank,
                rank_delta=rank_delta,
                risk_score_before=before.risk_score,
                risk_score_after=after.risk_score,
                risk_score_delta=risk_after - risk_before,
                max_coupling_degree_before=coupling_before.get(path, 0.0),
                max_coupling_degree_after=coupling_after.get(path, 0.0),
            )
        )

    worsened = sorted(movers, key=lambda m: (-m.rank_delta, m.file_path))
    worsened = [m for m in worsened if m.rank_delta > 0][:MAX_RISK_MOVERS_PER_DIRECTION]
    improved = sorted(movers, key=lambda m: (m.rank_delta, m.file_path))
    improved = [m for m in improved if m.rank_delta < 0][:MAX_RISK_MOVERS_PER_DIRECTION]
    return worsened, improved


def _findings_diff(
    run_before: AnalysisRun, run_after: AnalysisRun, path_map: dict[int, str], session: Session
) -> FindingsDiffOut:
    findings_before = session.scalars(
        select(Finding).where(Finding.analysis_run_id == run_before.id)
    ).all()
    findings_after = session.scalars(
        select(Finding).where(Finding.analysis_run_id == run_after.id)
    ).all()

    by_sig_before = {f.signature: f for f in findings_before if f.signature}
    by_sig_after = {f.signature: f for f in findings_after if f.signature}

    def _out(f: Finding) -> CompareFindingOut:
        return CompareFindingOut(
            signature=f.signature or "",
            category=f.category,
            severity=f.severity.value,
            confidence=f.confidence,
            title=f.title,
            file_path=path_map.get(f.path_id) if f.path_id is not None else None,
        )

    def _rank(f: Finding) -> tuple[int, float]:
        weight = {"high": 2, "med": 1, "low": 0}.get(f.severity.value, 0)
        return (-weight, -f.confidence)

    appeared = sorted((f for sig, f in by_sig_after.items() if sig not in by_sig_before), key=_rank)
    resolved = sorted((f for sig, f in by_sig_before.items() if sig not in by_sig_after), key=_rank)
    persisted = sorted((f for sig, f in by_sig_after.items() if sig in by_sig_before), key=_rank)

    return FindingsDiffOut(
        appeared=[_out(f) for f in appeared[:MAX_COMPARE_FINDINGS_PER_BUCKET]],
        resolved=[_out(f) for f in resolved[:MAX_COMPARE_FINDINGS_PER_BUCKET]],
        persisted=[_out(f) for f in persisted[:MAX_COMPARE_FINDINGS_PER_BUCKET]],
        appeared_total=len(appeared),
        resolved_total=len(resolved),
        persisted_total=len(persisted),
    )


def _jaccard(a: set[int], b: set[int]) -> float:
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def _load_subsystem_membership(run_id: uuid.UUID, session: Session) -> dict[int, dict[str, Any]]:
    subsystems = session.scalars(select(Subsystem).where(Subsystem.analysis_run_id == run_id)).all()
    result: dict[int, dict[str, Any]] = {
        s.id: {"label": s.label, "file_count": s.file_count, "members": set()} for s in subsystems
    }
    if not result:
        return result
    members = session.scalars(
        select(SubsystemMember).where(SubsystemMember.subsystem_id.in_(result.keys()))
    ).all()
    for m in members:
        result[m.subsystem_id]["members"].add(m.path_id)
    return result


def subsystem_changes(
    subsystems_before: dict[int, dict[str, Any]], subsystems_after: dict[int, dict[str, Any]]
) -> list[SubsystemChangeOut]:
    """Pure core of the Jaccard-matching step, independently testable (Part
    H): an edge ``(a_id, b_id)`` exists whenever those two subsystems' member
    sets overlap at >= MIN_SUBSYSTEM_JACCARD. A subsystem with exactly one
    edge is treated as "the same subsystem, persisted" and produces no
    change row at all; zero edges is appeared/disappeared; more than one edge
    on either side is a merge or a split. See SubsystemChangeOut's docstring
    for why this is identity-by-overlap, not identity-by-tracking.
    """
    edges: list[tuple[int, int, float]] = []
    for a_id, a in subsystems_before.items():
        for b_id, b in subsystems_after.items():
            j = _jaccard(a["members"], b["members"])
            if j >= MIN_SUBSYSTEM_JACCARD:
                edges.append((a_id, b_id, j))

    a_matches: dict[int, list[int]] = {}
    b_matches: dict[int, list[int]] = {}
    for a_id, b_id, _ in edges:
        a_matches.setdefault(a_id, []).append(b_id)
        b_matches.setdefault(b_id, []).append(a_id)

    changes: list[SubsystemChangeOut] = []
    for a_id, a in sorted(subsystems_before.items(), key=lambda kv: kv[1]["label"]):
        matches = a_matches.get(a_id, [])
        if not matches:
            changes.append(
                SubsystemChangeOut(
                    kind="disappeared",
                    label=a["label"],
                    detail="No matching subsystem in the newer run.",
                    file_count_before=a["file_count"],
                    file_count_after=None,
                )
            )
        elif len(matches) > 1:
            labels = sorted(subsystems_after[m]["label"] for m in matches)
            changes.append(
                SubsystemChangeOut(
                    kind="split",
                    label=a["label"],
                    detail=f"Split into: {', '.join(labels)}.",
                    file_count_before=a["file_count"],
                    file_count_after=None,
                )
            )
    for b_id, b in sorted(subsystems_after.items(), key=lambda kv: kv[1]["label"]):
        matches = b_matches.get(b_id, [])
        if not matches:
            changes.append(
                SubsystemChangeOut(
                    kind="appeared",
                    label=b["label"],
                    detail="No matching subsystem in the older run.",
                    file_count_before=None,
                    file_count_after=b["file_count"],
                )
            )
        elif len(matches) > 1:
            labels = sorted(subsystems_before[m]["label"] for m in matches)
            changes.append(
                SubsystemChangeOut(
                    kind="merged",
                    label=b["label"],
                    detail=f"Merged from: {', '.join(labels)}.",
                    file_count_before=None,
                    file_count_after=b["file_count"],
                )
            )
    return changes


def _contributor_changes(
    run_before: AnalysisRun, run_after: AnalysisRun, session: Session
) -> list[ContributorChangeOut]:
    contributors_before = session.scalars(
        select(Contributor).where(
            Contributor.analysis_run_id == run_before.id, Contributor.is_bot.is_(False)
        )
    ).all()
    contributors_after = session.scalars(
        select(Contributor).where(
            Contributor.analysis_run_id == run_after.id, Contributor.is_bot.is_(False)
        )
    ).all()
    by_email_before = {c.canonical_email: c for c in contributors_before}
    by_email_after = {c.canonical_email: c for c in contributors_after}

    changes: list[ContributorChangeOut] = []
    for email, c in sorted(by_email_after.items(), key=lambda kv: kv[1].canonical_name):
        if email not in by_email_before:
            changes.append(ContributorChangeOut(kind="joined", name=c.canonical_name))
    for email, c in sorted(by_email_before.items(), key=lambda kv: kv[1].canonical_name):
        if email not in by_email_after:
            changes.append(ContributorChangeOut(kind="left", name=c.canonical_name))
        elif not c.is_stale and by_email_after[email].is_stale:
            changes.append(ContributorChangeOut(kind="went_stale", name=c.canonical_name))
    return changes[:MAX_COMPARE_CONTRIBUTOR_CHANGES]


def _coupling_changes(
    run_before: AnalysisRun, run_after: AnalysisRun, path_map: dict[int, str], session: Session
) -> list[CouplingChangeOut]:
    rows_before = session.execute(
        select(Coupling.path_a_id, Coupling.path_b_id, Coupling.coupling_degree).where(
            Coupling.analysis_run_id == run_before.id
        )
    ).all()
    rows_after = session.execute(
        select(Coupling.path_a_id, Coupling.path_b_id, Coupling.coupling_degree).where(
            Coupling.analysis_run_id == run_after.id
        )
    ).all()
    before = {(a, b): d for a, b, d in rows_before}
    after = {(a, b): d for a, b, d in rows_after}

    def _names(pair: tuple[int, int]) -> tuple[str, str] | None:
        a_name, b_name = path_map.get(pair[0]), path_map.get(pair[1])
        if a_name is None or b_name is None:
            return None
        return a_name, b_name

    appeared, vanished, strengthened, weakened = [], [], [], []
    for pair in set(before) | set(after):
        names = _names(pair)
        if names is None:
            continue
        b_degree, a_degree = before.get(pair), after.get(pair)
        if b_degree is None and a_degree is not None:
            appeared.append((names, a_degree))
        elif a_degree is None and b_degree is not None:
            vanished.append((names, b_degree))
        elif b_degree is not None and a_degree is not None:
            delta = a_degree - b_degree
            if delta >= MIN_COUPLING_CHANGE_DELTA:
                strengthened.append((names, b_degree, a_degree))
            elif delta <= -MIN_COUPLING_CHANGE_DELTA:
                weakened.append((names, b_degree, a_degree))

    changes: list[CouplingChangeOut] = []
    for names, degree in sorted(appeared, key=lambda t: -t[1])[
        :MAX_COMPARE_COUPLING_CHANGES_PER_KIND
    ]:
        changes.append(
            CouplingChangeOut(
                kind="appeared",
                file_a_path=names[0],
                file_b_path=names[1],
                coupling_degree_before=None,
                coupling_degree_after=degree,
            )
        )
    for names, degree in sorted(vanished, key=lambda t: -t[1])[
        :MAX_COMPARE_COUPLING_CHANGES_PER_KIND
    ]:
        changes.append(
            CouplingChangeOut(
                kind="vanished",
                file_a_path=names[0],
                file_b_path=names[1],
                coupling_degree_before=degree,
                coupling_degree_after=None,
            )
        )
    for names, before_d, after_d in sorted(strengthened, key=lambda t: -(t[2] - t[1]))[
        :MAX_COMPARE_COUPLING_CHANGES_PER_KIND
    ]:
        changes.append(
            CouplingChangeOut(
                kind="strengthened",
                file_a_path=names[0],
                file_b_path=names[1],
                coupling_degree_before=before_d,
                coupling_degree_after=after_d,
            )
        )
    for names, before_d, after_d in sorted(weakened, key=lambda t: (t[2] - t[1]))[
        :MAX_COMPARE_COUPLING_CHANGES_PER_KIND
    ]:
        changes.append(
            CouplingChangeOut(
                kind="weakened",
                file_a_path=names[0],
                file_b_path=names[1],
                coupling_degree_before=before_d,
                coupling_degree_after=after_d,
            )
        )
    return changes


def _security_diff(
    run_before: AnalysisRun, run_after: AnalysisRun, session: Session
) -> SecurityDiffOut:
    vulns_before = session.scalars(
        select(Vulnerability).where(Vulnerability.analysis_run_id == run_before.id)
    ).all()
    vulns_after = session.scalars(
        select(Vulnerability).where(Vulnerability.analysis_run_id == run_after.id)
    ).all()
    keys_before = {(v.osv_id, v.package_name) for v in vulns_before}
    keys_after = {(v.osv_id, v.package_name) for v in vulns_after}

    secrets = session.scalars(
        select(SecretHit).where(SecretHit.repo_id == run_before.repo_id)
    ).all()
    secrets_introduced = sum(
        1 for s in secrets if run_before.started_at < s.committed_at <= run_after.started_at
    )

    return SecurityDiffOut(
        vulnerabilities_introduced=len(keys_after - keys_before),
        vulnerabilities_remediated=len(keys_before - keys_after),
        secrets_introduced=secrets_introduced,
        secrets_caveat=(
            "Secret scans are not versioned per analysis run -- secret_hits reflects only the "
            "most recent full-history scan. 'Introduced' is approximated by each secret's own "
            "commit date falling between the two runs' start times; a reliable 'remediated' "
            "count cannot be reconstructed the same way, so it is not shown."
        ),
    )


def compare_runs(session: Session, run_a: AnalysisRun, run_b: AnalysisRun) -> CompareResponse:
    """Two runs of the SAME repository -- raises ``ValueError`` otherwise
    (the API layer turns that into a 400). Orders them chronologically by
    ``started_at`` (ties by id) so "before"/"after" framing never depends on
    which order the caller passed ``a``/``b`` in.
    """
    if run_a.repo_id != run_b.repo_id:
        raise ValueError("compare_runs requires two runs of the same repository")

    run_before, run_after = sorted((run_a, run_b), key=lambda r: (r.started_at, str(r.id)))

    path_map = load_path_map(run_before.repo_id, session)

    subsystems_before = _load_subsystem_membership(run_before.id, session)
    subsystems_after = _load_subsystem_membership(run_after.id, session)

    worsened, improved = _risk_movers(run_before, run_after, path_map, session)

    return CompareResponse(
        repo_id=run_before.repo_id,
        run_before=run_before.id,
        run_after=run_after.id,
        engine_version_before=run_before.engine_version,
        engine_version_after=run_after.engine_version,
        engine_version_differs=run_before.engine_version != run_after.engine_version,
        headline=_headline_deltas(run_before, run_after, session),
        risk_movers_worsened=worsened,
        risk_movers_improved=improved,
        findings=_findings_diff(run_before, run_after, path_map, session),
        subsystem_changes=subsystem_changes(subsystems_before, subsystems_after),
        contributor_changes=_contributor_changes(run_before, run_after, session),
        coupling_changes=_coupling_changes(run_before, run_after, path_map, session),
        security=_security_diff(run_before, run_after, session),
    )
