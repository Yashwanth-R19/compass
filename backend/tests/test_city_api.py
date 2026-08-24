"""Session 09, Part E: GET /repos/{id}/city -- gating on "onboarding", the
columnar `files` shape, the server-computed `bounds`, and that the endpoint
is a pure join (no engine, no persisted table of its own).
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from app.db.models import (
    AnalysisRun,
    AnalysisRunStatus,
    AnalysisStage,
    Contributor,
    File,
    FileExpertise,
    FileMetrics,
    Repo,
    RepoPath,
    RepoStatus,
    StageStatus,
    Subsystem,
    SubsystemMember,
)
from app.jobs.stages import create_pending_stages
from app.schemas.analysis import CITY_FILE_COLUMNS


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
    db_session,
    repo_id: uuid.UUID,
    path: str,
    *,
    loc: int = 10,
    complexity: float = 1.0,
    commit_count: int = 1,
    churn_weighted: float = 0.0,
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
            complexity=complexity,
            churn_total=1,
            churn_weighted=churn_weighted,
            commit_count=commit_count,
            first_seen=now,
            last_seen=now,
            is_deleted=False,
        )
    )
    db_session.flush()
    return path_id


def test_city_gates_on_onboarding_stage(client, db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/city-gating")
    run_id = _make_run_with_pending_stages(db_session, repo_id)
    _add_file(db_session, repo_id, "a.py")
    db_session.commit()

    pending = client.get(f"/repos/{repo_id}/city")
    assert pending.status_code == 202
    assert pending.json() == {"stage": "onboarding", "status": "pending"}

    # An earlier stage reaching "done" must NOT unlock this endpoint --
    # /city needs "onboarding" specifically (the last insight stage), not
    # an earlier one like "risk" or "knowledge".
    _set_stage_status(db_session, run_id, "risk", StageStatus.done)
    _set_stage_status(db_session, run_id, "knowledge", StageStatus.done)
    still_pending = client.get(f"/repos/{repo_id}/city")
    assert still_pending.status_code == 202

    _set_stage_status(db_session, run_id, "onboarding", StageStatus.done)
    ready = client.get(f"/repos/{repo_id}/city")
    assert ready.status_code == 200
    assert ready.json()["repo_id"] == str(repo_id)


def test_city_payload_shape_bounds_and_joins(client, db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/city-shape")
    run_id = _make_run_with_pending_stages(db_session, repo_id)

    subsystem = Subsystem(
        analysis_run_id=run_id,
        repo_id=repo_id,
        label="billing",
        label_source="path_prefix",
        file_count=2,
        total_loc=30,
        internal_edges=1,
        external_edges=0,
        cohesion=1.0,
        rank=0,
    )
    db_session.add(subsystem)
    db_session.flush()

    path_a = _add_file(
        db_session, repo_id, "billing/invoice.py", loc=20, complexity=5.0, churn_weighted=12.5
    )
    path_b = _add_file(
        db_session, repo_id, "billing/receipt.py", loc=10, complexity=2.0, churn_weighted=3.0
    )
    # A file outside the subsystem and with no file_metrics row at all --
    # /city must still include it (LEFT joined), not silently drop it.
    _add_file(db_session, repo_id, "standalone.py", loc=5, complexity=1.0)

    db_session.add_all(
        [
            SubsystemMember(subsystem_id=subsystem.id, path_id=path_a, centrality=0.9),
            SubsystemMember(subsystem_id=subsystem.id, path_id=path_b, centrality=0.4),
        ]
    )
    db_session.add(
        FileMetrics(
            analysis_run_id=run_id,
            repo_id=repo_id,
            path_id=path_a,
            risk_score=0.8,
            risk_confidence=0.9,
            hotspot_rank=0,
        )
    )
    contributor = Contributor(
        analysis_run_id=run_id,
        repo_id=repo_id,
        canonical_name="Jane Doe",
        canonical_email="jane@example.com",
        aliases=[{"name": "Jane Doe", "email": "jane@example.com"}],
        commit_count=10,
        lines_added=100,
        lines_deleted=10,
        first_commit_at=datetime.now(UTC),
        last_commit_at=datetime.now(UTC),
        is_bot=False,
        active_days=5,
        is_stale=False,
        rank=0,
    )
    db_session.add(contributor)
    db_session.flush()
    db_session.add(
        FileExpertise(
            analysis_run_id=run_id,
            path_id=path_a,
            contributor_id=contributor.id,
            doa=3.8,
            doa_normalized=0.95,
            is_expert=True,
            changes=8,
            last_touched_at=datetime.now(UTC),
        )
    )
    db_session.commit()

    _set_stage_status(db_session, run_id, "onboarding", StageStatus.done)

    response = client.get(f"/repos/{repo_id}/city")
    assert response.status_code == 200
    body = response.json()

    assert body["subsystems"] == [
        {"id": subsystem.id, "label": "billing", "file_count": 2, "total_loc": 30}
    ]

    # Columnar, not array-of-objects (Part E): a fixed columns header plus
    # one row tuple per file, in that exact order.
    assert body["files"]["columns"] == CITY_FILE_COLUMNS
    rows_by_path = {row[0]: row for row in body["files"]["rows"]}
    assert set(rows_by_path) == {"billing/invoice.py", "billing/receipt.py", "standalone.py"}

    col = {name: i for i, name in enumerate(CITY_FILE_COLUMNS)}
    invoice_row = rows_by_path["billing/invoice.py"]
    assert invoice_row[col["subsystem_id"]] == subsystem.id
    assert invoice_row[col["loc"]] == 20
    assert invoice_row[col["risk_score"]] == 0.8
    assert invoice_row[col["principal_expert_id"]] == contributor.id
    assert invoice_row[col["churn_weighted"]] == 12.5

    # standalone.py has no subsystem, no file_metrics row, and no expert --
    # the LEFT joins must degrade to null, not drop the file.
    standalone_row = rows_by_path["standalone.py"]
    assert standalone_row[col["subsystem_id"]] is None
    assert standalone_row[col["risk_score"]] is None
    assert standalone_row[col["principal_expert_id"]] is None

    # bounds computed server-side over the same rows.
    assert body["bounds"]["loc"] == {"min": 5.0, "max": 20.0}
    assert body["bounds"]["complexity"] == {"min": 1.0, "max": 5.0}
    # Only invoice.py has a risk_score at all -- bounds over the non-null
    # subset, not defaulting the missing ones to 0 and skewing the range.
    assert body["bounds"]["risk_score"] == {"min": 0.8, "max": 0.8}

    assert body["contributors"] == [{"id": contributor.id, "name": "Jane Doe"}]


def test_city_on_zero_file_repo_returns_empty_not_500(client, db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/city-empty")
    run_id = _make_run_with_pending_stages(db_session, repo_id)
    _set_stage_status(db_session, run_id, "onboarding", StageStatus.done)

    response = client.get(f"/repos/{repo_id}/city")
    assert response.status_code == 200
    body = response.json()
    assert body["subsystems"] == []
    assert body["files"]["rows"] == []
    assert body["contributors"] == []
    assert body["bounds"]["loc"] == {"min": 0.0, "max": 0.0}
