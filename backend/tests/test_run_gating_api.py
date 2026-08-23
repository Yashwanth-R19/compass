import uuid

from sqlalchemy import select

from app.db.models import (
    AnalysisRun,
    AnalysisRunStatus,
    AnalysisStage,
    Repo,
    RepoStatus,
    StageStatus,
)
from app.jobs.stages import ALL_STAGES, create_pending_stages


def _make_repo(db_session, url: str) -> uuid.UUID:
    repo = Repo(url=url, owner="fixture", name="repo", status=RepoStatus.mining)
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


def test_status_endpoint_shows_full_pending_stage_list_immediately(client, db_session):
    """Part E/F: the very first status poll, before any stage has actually
    started, must already show every stage -- this is what lets the
    frontend render skeletons instead of a blank page."""
    repo_id = _make_repo(db_session, "https://github.com/fixture/status-precreate")
    run_id = _make_run_with_pending_stages(db_session, repo_id)

    response = client.get(f"/repos/{repo_id}/status")
    assert response.status_code == 200
    body = response.json()

    assert body["repo_id"] == str(repo_id)
    assert body["run_id"] == str(run_id)
    assert body["run_status"] == "running"
    assert [s["name"] for s in body["stages"]] == [s.name for s in ALL_STAGES]
    assert all(s["status"] == "pending" for s in body["stages"])


def test_result_endpoint_returns_202_while_stage_pending_then_200_once_done(client, db_session):
    """Part E: the ?run_id= contract's core promise -- "not computed yet" is
    a 202 with a stage/status body, never an empty 200, and never a 4xx."""
    repo_id = _make_repo(db_session, "https://github.com/fixture/status-202")
    run_id = _make_run_with_pending_stages(db_session, repo_id)

    pending_response = client.get(f"/repos/{repo_id}/coupling")
    assert pending_response.status_code == 202
    assert pending_response.json() == {"stage": "coupling", "status": "pending"}

    _set_stage_status(db_session, run_id, "coupling", StageStatus.done)

    done_response = client.get(f"/repos/{repo_id}/coupling")
    assert done_response.status_code == 200
    body = done_response.json()
    # Computed AND genuinely empty (no coupling rows were ever inserted) --
    # distinct from the 202 case above, which is "not computed yet".
    assert body["pairs"] == []


def test_findings_endpoint_gates_on_rank_stage_not_earlier_finding_stages(client, db_session):
    """Findings exist as soon as any emitting engine runs, but `rank` is not
    final until FindingsRankEngine runs last -- the endpoint must gate on
    "rank", not on risk/architecture (which now also runs OverlayEngine,
    session 04) individually."""
    repo_id = _make_repo(db_session, "https://github.com/fixture/status-findings-gate")
    run_id = _make_run_with_pending_stages(db_session, repo_id)

    for name in ("coupling", "subsystems", "architecture", "risk", "health"):
        _set_stage_status(db_session, run_id, name, StageStatus.done)

    still_pending = client.get(f"/repos/{repo_id}/findings")
    assert still_pending.status_code == 202
    assert still_pending.json() == {"stage": "rank", "status": "pending"}

    _set_stage_status(db_session, run_id, "rank", StageStatus.done)

    ready = client.get(f"/repos/{repo_id}/findings")
    assert ready.status_code == 200
    assert ready.json()["findings"] == []


def test_result_endpoint_404s_when_no_run_exists_yet(client, db_session):
    """Distinct from the 202 case: a repo with no analysis_runs row at all
    (ingestion job hasn't even started) is a 404, not a 202 -- there is no
    stage to report a status for."""
    repo = Repo(
        url="https://github.com/fixture/no-run-yet",
        owner="fixture",
        name="repo",
        status=RepoStatus.pending,
    )
    db_session.add(repo)
    db_session.commit()

    response = client.get(f"/repos/{repo.id}/coupling")
    assert response.status_code == 404
