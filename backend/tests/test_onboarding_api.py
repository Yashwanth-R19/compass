import uuid
from datetime import UTC, datetime

from sqlalchemy import insert, select

from app.db.models import (
    AnalysisRun,
    AnalysisRunStatus,
    AnalysisStage,
    File,
    GlossaryTerm,
    Health,
    Repo,
    RepoPath,
    RepoStatus,
    StageStatus,
    Subsystem,
    SubsystemMember,
    TourStop,
)
from app.jobs.stages import create_pending_stages


def _make_repo(db_session, url: str) -> uuid.UUID:
    repo = Repo(url=url, owner="fixture", name="repo", status=RepoStatus.ready)
    db_session.add(repo)
    db_session.commit()
    return repo.id


def _make_run_with_pending_stages(db_session, repo_id: uuid.UUID) -> uuid.UUID:
    run = AnalysisRun(repo_id=repo_id, status=AnalysisRunStatus.running, head_sha="test-sha")
    db_session.add(run)
    db_session.flush()
    create_pending_stages(run.id, db_session)
    db_session.commit()
    return run.id


def _set_stage_status(db_session, run_id: uuid.UUID, name: str, status: StageStatus) -> None:
    row = db_session.scalar(
        select(AnalysisStage).where(AnalysisStage.run_id == run_id, AnalysisStage.name == name)
    )
    row.status = status
    db_session.commit()


def _intern_path(db_session, repo_id: uuid.UUID, path: str) -> int:
    row = RepoPath(repo_id=repo_id, path=path)
    db_session.add(row)
    db_session.flush()
    return row.id


def _add_file(db_session, repo_id: uuid.UUID, path_id: int, path: str) -> None:
    now = datetime.now(UTC)
    db_session.add(
        File(
            repo_id=repo_id,
            path_id=path_id,
            path=path,
            language="python",
            current_loc=10,
            complexity=1.0,
            churn_total=1,
            commit_count=1,
            first_seen=now,
            last_seen=now,
            is_deleted=False,
        )
    )
    db_session.flush()


def test_tour_glossary_passport_health_all_gate_on_onboarding_stage(client, db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/onboarding-202")
    run_id = _make_run_with_pending_stages(db_session, repo_id)

    for path in (
        f"/repos/{repo_id}/tour",
        f"/repos/{repo_id}/glossary",
        f"/repos/{repo_id}/passport",
        f"/repos/{repo_id}/health",
    ):
        pending = client.get(path)
        assert pending.status_code == 202
        assert pending.json() == {"stage": "onboarding", "status": "pending"}

    _set_stage_status(db_session, run_id, "onboarding", StageStatus.done)

    tour_resp = client.get(f"/repos/{repo_id}/tour")
    assert tour_resp.status_code == 200
    assert tour_resp.json()["stops"] == []

    glossary_resp = client.get(f"/repos/{repo_id}/glossary")
    assert glossary_resp.status_code == 200
    body = glossary_resp.json()
    assert body["terms"] == []
    assert "vocabulary" in body["limitation"].lower()

    # No repo_passport row exists yet (this test never ran PassportEngine),
    # so the endpoint must 404 -- distinct from the 202 "not computed yet"
    # case, since the stage itself IS done.
    passport_resp = client.get(f"/repos/{repo_id}/passport")
    assert passport_resp.status_code == 404


def test_tour_endpoint_returns_ordered_stops_with_full_reason_detail(client, db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/onboarding-tour-data")
    run_id = _make_run_with_pending_stages(db_session, repo_id)
    _set_stage_status(db_session, run_id, "onboarding", StageStatus.done)

    path_id = _intern_path(db_session, repo_id, "entry.py")
    _add_file(db_session, repo_id, path_id, "entry.py")
    sub_result = db_session.execute(
        insert(Subsystem)
        .values(
            analysis_run_id=run_id,
            repo_id=repo_id,
            label="core",
            label_source="fallback",
            file_count=1,
            total_loc=10,
            internal_edges=0,
            external_edges=0,
            cohesion=1.0,
            rank=0,
        )
        .returning(Subsystem.id)
    )
    subsystem_id = sub_result.scalar_one()
    db_session.execute(
        insert(SubsystemMember),
        [{"subsystem_id": subsystem_id, "path_id": path_id, "centrality": 0.5}],
    )
    db_session.execute(
        insert(TourStop),
        [
            {
                "analysis_run_id": run_id,
                "repo_id": repo_id,
                "position": 1,
                "path_id": path_id,
                "reason_code": "entry_point",
                "reason_detail": {"kind": "cli", "confidence": 0.9, "subsystem": "core"},
                "subsystem_id": subsystem_id,
            }
        ],
    )
    db_session.commit()

    response = client.get(f"/repos/{repo_id}/tour")
    assert response.status_code == 200
    body = response.json()
    assert body["stops"] == [
        {
            "position": 1,
            "file_path": "entry.py",
            "reason_code": "entry_point",
            "reason_detail": {"kind": "cli", "confidence": 0.9, "subsystem": "core"},
            "subsystem_label": "core",
        }
    ]
    assert body["subsystems_covered"] == 1
    assert body["of"] == 1


def test_glossary_endpoint_resolves_defining_path_ids_to_paths(client, db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/onboarding-glossary-data")
    run_id = _make_run_with_pending_stages(db_session, repo_id)
    _set_stage_status(db_session, run_id, "onboarding", StageStatus.done)

    path_id = _intern_path(db_session, repo_id, "billing/invoice.py")
    _add_file(db_session, repo_id, path_id, "billing/invoice.py")
    db_session.execute(
        insert(GlossaryTerm),
        [
            {
                "analysis_run_id": run_id,
                "repo_id": repo_id,
                "term": "invoice",
                "score": 1.5,
                "occurrences": 3,
                "subsystem_spread": 1,
                "defining_path_ids": [path_id],
                "rank": 0,
            }
        ],
    )
    db_session.commit()

    response = client.get(f"/repos/{repo_id}/glossary")
    assert response.status_code == 200
    body = response.json()
    assert body["terms"] == [
        {
            "term": "invoice",
            "score": 1.5,
            "occurrences": 3,
            "subsystem_spread": 1,
            "defining_paths": ["billing/invoice.py"],
            "rank": 0,
        }
    ]


def test_health_endpoint_still_returns_the_persisted_health_row(client, db_session):
    """Session 06: /health moved from gating on the (now-removed) standalone
    "health" stage to gating on "onboarding", but its own response shape and
    data source (the persisted `health` row) are unchanged."""
    repo_id = _make_repo(db_session, "https://github.com/fixture/onboarding-health-unchanged")
    run_id = _make_run_with_pending_stages(db_session, repo_id)
    _set_stage_status(db_session, run_id, "onboarding", StageStatus.done)

    db_session.add(
        Health(
            id=uuid.uuid4(),
            analysis_run_id=run_id,
            repo_id=repo_id,
            score=87.5,
            high_risk_ratio=0.1,
            cycle_count=0,
            hidden_dependency_count=0,
        )
    )
    db_session.commit()

    response = client.get(f"/repos/{repo_id}/health")
    assert response.status_code == 200
    body = response.json()
    assert body["score"] == 87.5
    assert body["calibration"] == "heuristic"
