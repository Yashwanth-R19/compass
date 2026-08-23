import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import insert, select

from app.db.models import (
    AnalysisRun,
    AnalysisRunStatus,
    AnalysisStage,
    Contributor,
    File,
    FileExpertise,
    Repo,
    RepoPath,
    RepoStatus,
    StageStatus,
    TruckFactor,
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


def _make_contributor(
    db_session, repo_id: uuid.UUID, run_id: uuid.UUID, name: str, email: str, rank: int = 0
) -> int:
    now = datetime.now(UTC)
    result = db_session.execute(
        insert(Contributor)
        .values(
            analysis_run_id=run_id,
            repo_id=repo_id,
            canonical_name=name,
            canonical_email=email,
            aliases=[{"name": name, "email": email}, {"name": name, "email": f"alt.{email}"}],
            commit_count=5,
            lines_added=50,
            lines_deleted=5,
            first_commit_at=now,
            last_commit_at=now,
            is_bot=False,
            active_days=3,
            is_stale=False,
            rank=rank,
        )
        .returning(Contributor.id)
    )
    db_session.commit()
    return result.scalar_one()


def test_knowledge_endpoints_202_while_pending_then_200_when_done(client, db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/knowledge-202")
    run_id = _make_run_with_pending_stages(db_session, repo_id)

    for path in (
        f"/repos/{repo_id}/contributors",
        f"/repos/{repo_id}/knowledge-map",
        f"/repos/{repo_id}/truck-factor",
    ):
        pending = client.get(path)
        assert pending.status_code == 202
        assert pending.json() == {"stage": "knowledge", "status": "pending"}

    _set_stage_status(db_session, run_id, "knowledge", StageStatus.done)

    contributors_resp = client.get(f"/repos/{repo_id}/contributors")
    assert contributors_resp.status_code == 200
    assert contributors_resp.json()["contributors"] == []

    knowledge_map_resp = client.get(f"/repos/{repo_id}/knowledge-map")
    assert knowledge_map_resp.status_code == 200
    assert knowledge_map_resp.json()["files"] == []

    truck_factor_resp = client.get(f"/repos/{repo_id}/truck-factor")
    assert truck_factor_resp.status_code == 200
    body = truck_factor_resp.json()
    assert body["value"] == 0
    assert "knowledge-distribution risk" in body["interpretation"]


def test_truck_factor_skipped_stage_returns_synthetic_empty_response(client, db_session):
    """Zero-commit repos leave the 'knowledge' stage skipped (Part D
    degenerate case) with no truck_factor row ever written -- the endpoint
    must still return a legitimate 200, not crash on a missing row."""
    repo_id = _make_repo(db_session, "https://github.com/fixture/knowledge-skipped")
    run_id = _make_run_with_pending_stages(db_session, repo_id)
    _set_stage_status(db_session, run_id, "knowledge", StageStatus.skipped)

    response = client.get(f"/repos/{repo_id}/truck-factor")
    assert response.status_code == 200
    body = response.json()
    assert body["value"] == 0
    assert body["removal_order"] == []
    assert body["note"] is not None


def test_expertise_endpoint_404s_for_unknown_path(client, db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/knowledge-expertise-404")
    run_id = _make_run_with_pending_stages(db_session, repo_id)
    _set_stage_status(db_session, run_id, "knowledge", StageStatus.done)

    response = client.get(f"/repos/{repo_id}/expertise", params={"path": "does/not/exist.py"})
    assert response.status_code == 404


def test_expertise_endpoint_pending_before_path_resolution(client, db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/knowledge-expertise-202")
    _make_run_with_pending_stages(db_session, repo_id)

    response = client.get(f"/repos/{repo_id}/expertise", params={"path": "whatever.py"})
    assert response.status_code == 202


def test_no_endpoint_returns_an_unmasked_email(client, db_session):
    """plan/RULES.md sec 11.2 / session 05 Part F, enforced end-to-end: no
    raw email address, canonical or aliased, ever appears in the serialized
    JSON of any of the four new endpoints."""
    repo_id = _make_repo(db_session, "https://github.com/fixture/knowledge-privacy")
    run_id = _make_run_with_pending_stages(db_session, repo_id)
    _set_stage_status(db_session, run_id, "knowledge", StageStatus.done)

    raw_canonical_email = "jane.doe@sensitive-corp.example"
    contributor_id = _make_contributor(db_session, repo_id, run_id, "Jane Doe", raw_canonical_email)
    raw_alias_email = f"alt.{raw_canonical_email}"

    path_id = _intern_path(db_session, repo_id, "src/billing/invoice.py")
    _add_file(db_session, repo_id, path_id, "src/billing/invoice.py")
    db_session.execute(
        insert(FileExpertise).values(
            analysis_run_id=run_id,
            path_id=path_id,
            contributor_id=contributor_id,
            doa=4.5,
            doa_normalized=1.0,
            is_expert=True,
            changes=3,
            last_touched_at=datetime.now(UTC),
        )
    )
    db_session.execute(
        insert(TruckFactor).values(
            id=uuid.uuid4(),
            analysis_run_id=run_id,
            repo_id=repo_id,
            value=1,
            removal_order=[
                {
                    "contributor_id": contributor_id,
                    "name": "Jane Doe",
                    "files_orphaned": 1,
                    "cumulative_orphan_ratio": 1.0,
                }
            ],
            total_files_considered=1,
            orphaned_file_count=0,
            note=None,
        )
    )
    db_session.commit()

    responses = [
        client.get(f"/repos/{repo_id}/contributors"),
        client.get(f"/repos/{repo_id}/expertise", params={"path": "src/billing/invoice.py"}),
        client.get(f"/repos/{repo_id}/knowledge-map"),
        client.get(f"/repos/{repo_id}/truck-factor"),
    ]

    for response in responses:
        assert response.status_code == 200
        raw_text = response.text
        assert raw_canonical_email not in raw_text
        assert raw_alias_email not in raw_text

    # Sanity check: the masked form (and the domain) DOES legitimately
    # appear -- proving this isn't passing merely because the contributor
    # is missing from the response entirely.
    contributors_json = json.dumps(responses[0].json())
    assert "j***@sensitive-corp.example" in contributors_json
