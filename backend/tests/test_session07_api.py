"""API-level tests for session 07's new/extended endpoints: gating
(202-while-pending), and the ``unreferenced_files`` addition to
``/architecture`` (Part E -- no engine, no severity, no findings row).
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import insert, select

from app.db.models import (
    AnalysisRun,
    AnalysisRunStatus,
    AnalysisStage,
    Dependency,
    EntryPoint,
    File,
    Repo,
    RepoPath,
    RepoStatus,
    StageStatus,
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


def _add_file(
    db_session, repo_id: uuid.UUID, path: str, *, is_test: bool = False, loc: int = 10
) -> int:
    path_id = _intern_path(db_session, repo_id, path)
    now = datetime.now(UTC)
    db_session.add(
        File(
            repo_id=repo_id,
            path_id=path_id,
            path=path,
            language="python",
            current_loc=loc,
            complexity=1.0,
            churn_total=1,
            commit_count=1,
            first_seen=now,
            last_seen=now,
            is_deleted=False,
            is_test=is_test,
        )
    )
    db_session.flush()
    return path_id


def test_hygiene_gates_on_risk_stage(client, db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/session07-gating")
    run_id = _make_run_with_pending_stages(db_session, repo_id)

    pending = client.get(f"/repos/{repo_id}/hygiene")
    assert pending.status_code == 202
    assert pending.json() == {"stage": "risk", "status": "pending"}

    _set_stage_status(db_session, run_id, "risk", StageStatus.done)

    ready = client.get(f"/repos/{repo_id}/hygiene")
    assert ready.status_code == 200
    body = ready.json()
    assert body["repo_id"] == str(repo_id)


def test_blast_radius_gates_on_coupling_stage_and_404s_for_unknown_path(client, db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/session07-blast-gating")
    run_id = _make_run_with_pending_stages(db_session, repo_id)
    _add_file(db_session, repo_id, "a.py")
    db_session.commit()

    pending = client.get(f"/repos/{repo_id}/blast-radius", params={"path": "a.py"})
    assert pending.status_code == 202
    assert pending.json() == {"stage": "coupling", "status": "pending"}

    _set_stage_status(db_session, run_id, "coupling", StageStatus.done)

    not_found = client.get(f"/repos/{repo_id}/blast-radius", params={"path": "does-not-exist.py"})
    assert not_found.status_code == 404

    ready = client.get(f"/repos/{repo_id}/blast-radius", params={"path": "a.py"})
    assert ready.status_code == 200
    body = ready.json()
    assert body["file_path"] == "a.py"
    assert body["structural_affected"] == []


def test_unreferenced_files_excludes_test_files_and_entry_points(client, db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/session07-unreferenced")
    run_id = _make_run_with_pending_stages(db_session, repo_id)

    referenced_id = _add_file(db_session, repo_id, "referenced.py", loc=5)
    importer_id = _add_file(db_session, repo_id, "importer.py", loc=1)
    _add_file(db_session, repo_id, "orphan.py", loc=50)
    _add_file(db_session, repo_id, "test_orphan.py", is_test=True, loc=999)
    entry_point_orphan_id = _add_file(db_session, repo_id, "cli.py", loc=999)

    db_session.execute(
        insert(Dependency),
        [
            {
                "repo_id": repo_id,
                "from_path_id": importer_id,
                "to_path_id": referenced_id,
                "dep_type": "import",
                "import_kind": "static",
            }
        ],
    )
    db_session.execute(
        insert(EntryPoint),
        [
            {
                "analysis_run_id": run_id,
                "repo_id": repo_id,
                "path_id": entry_point_orphan_id,
                "kind": "cli",
                "evidence": "conventional filename: cli.py",
                "confidence": 0.75,
                "rank": 0,
            }
        ],
    )
    db_session.commit()

    _set_stage_status(db_session, run_id, "architecture", StageStatus.done)

    response = client.get(f"/repos/{repo_id}/architecture")
    assert response.status_code == 200
    body = response.json()

    unreferenced_paths = {f["file_path"] for f in body["unreferenced_files"]}
    # orphan.py has zero structural edges at all; importer.py has an
    # outgoing edge but nothing imports IT -- both are legitimately
    # unreferenced. referenced.py (the import target), test_orphan.py (a
    # test file), and cli.py (a detected entry point) must all be excluded.
    assert unreferenced_paths == {"orphan.py", "importer.py"}
    assert "test_orphan.py" not in unreferenced_paths
    assert "cli.py" not in unreferenced_paths
    assert "referenced.py" not in unreferenced_paths
    assert body["unreferenced_files_caveat"]
    assert isinstance(body["unreferenced_files_caveat"], str) and body["unreferenced_files_caveat"]

    # Part E: no engine, no severity, no findings row for this.
    findings = client.get(f"/repos/{repo_id}/findings")
    assert findings.status_code in (200, 202)
    if findings.status_code == 200:
        assert all(f["file_path"] not in {"orphan.py"} for f in findings.json()["findings"])
