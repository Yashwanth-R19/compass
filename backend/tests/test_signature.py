import uuid
from datetime import UTC, datetime

from sqlalchemy import insert, select

from app.db.models import (
    AnalysisRun,
    AnalysisRunStatus,
    Commit,
    Dependency,
    File,
    Finding,
    Repo,
    RepoPath,
    RepoStatus,
)
from app.engines.architecture import ArchEngine
from app.engines.context import RunContext
from app.engines.coupling import CouplingEngine
from app.engines.overlay import OverlayEngine
from app.engines.risk import RiskEngine
from app.engines.signature import finding_signature


def _make_repo(db_session, url: str) -> uuid.UUID:
    repo = Repo(url=url, owner="fixture", name="repo", status=RepoStatus.pending)
    db_session.add(repo)
    db_session.commit()
    return repo.id


def _make_run(db_session, repo_id: uuid.UUID) -> uuid.UUID:
    run = AnalysisRun(repo_id=repo_id, status=AnalysisRunStatus.running, head_sha="test-sha")
    db_session.add(run)
    db_session.commit()
    return run.id


def _intern_paths(db_session, repo_id: uuid.UUID, paths: list[str]) -> dict[str, int]:
    existing = {
        row.path: row.id
        for row in db_session.execute(
            select(RepoPath.path, RepoPath.id).where(RepoPath.repo_id == repo_id)
        ).all()
    }
    new_paths = [p for p in paths if p not in existing]
    if new_paths:
        db_session.execute(insert(RepoPath), [{"repo_id": repo_id, "path": p} for p in new_paths])
        db_session.flush()
        existing = {
            row.path: row.id
            for row in db_session.execute(
                select(RepoPath.path, RepoPath.id).where(RepoPath.repo_id == repo_id)
            ).all()
        }
    return existing


def _add_dependency(db_session, repo_id: uuid.UUID, from_path: str, to_path: str) -> None:
    path_ids = _intern_paths(db_session, repo_id, [from_path, to_path])
    db_session.execute(
        insert(Dependency),
        [
            {
                "repo_id": repo_id,
                "from_path_id": path_ids[from_path],
                "to_path_id": path_ids[to_path],
                "dep_type": "import",
            }
        ],
    )


def test_finding_signature_is_deterministic_across_calls() -> None:
    assert finding_signature("risk", "a.py") == finding_signature("risk", "a.py")


def test_finding_signature_differs_across_file_or_category() -> None:
    assert finding_signature("risk", "a.py") != finding_signature("risk", "b.py")
    assert finding_signature("risk", "a.py") != finding_signature("hidden_dependency", "a.py")


def test_finding_signature_is_32_hex_chars() -> None:
    sig = finding_signature("risk", "a.py")
    assert len(sig) == 32
    int(sig, 16)  # raises if not hex


def test_rotated_cycle_produces_the_same_signature() -> None:
    """A cycle detected as a->b->c is the same cycle as one detected starting
    at b->c->a -- must produce the same signature, since only the walk start
    point changed, not the underlying graph (see finding_signature's
    docstring)."""
    key_1 = "|".join(sorted(["a.py", "b.py", "c.py"]))
    key_2 = "|".join(sorted(["b.py", "c.py", "a.py"]))
    assert finding_signature("architecture", key_1) == finding_signature("architecture", key_2)


def test_hidden_dependency_signature_stable_across_two_runs(db_session):
    """The same underlying hidden dependency, computed in two separate
    analysis runs of the same repo, must persist the same signature -- this
    is what session 13's run-to-run diff matches on."""
    repo_id = _make_repo(db_session, "https://github.com/fixture/signature-hidden-dep")
    now = datetime.now(UTC)
    path_ids = _intern_paths(db_session, repo_id, ["a.py", "c.py"])
    for i in range(6):
        commit = Commit(
            repo_id=repo_id,
            sha=f"ac{i}",
            author_name="tester",
            author_email="tester@example.com",
            committed_at=now,
            message="synthetic",
            is_fix=False,
            is_revert=False,
            files_changed=2,
            insertions=0,
            deletions=0,
            changed_path_ids=[path_ids["a.py"], path_ids["c.py"]],
            added_lines=[0, 0],
            deleted_lines=[0, 0],
        )
        db_session.add(commit)
    db_session.commit()

    signatures = []
    for _ in range(2):
        run_id = _make_run(db_session, repo_id)
        ctx = RunContext(repo_id=repo_id, run_id=run_id)
        CouplingEngine().run(ctx, db_session)
        ArchEngine().run(ctx, db_session)
        OverlayEngine().run(ctx, db_session)
        db_session.commit()

        finding = db_session.scalar(
            select(Finding).where(
                Finding.analysis_run_id == run_id, Finding.category == "hidden_dependency"
            )
        )
        assert finding is not None
        signatures.append(finding.signature)

    assert signatures[0] == signatures[1]
    assert signatures[0] is not None


def test_risk_finding_signature_is_the_file_path(db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/signature-risk")
    run_id = _make_run(db_session, repo_id)
    path_id = _intern_paths(db_session, repo_id, ["hot.py"])["hot.py"]
    now = datetime.now(UTC)
    db_session.add(
        File(
            repo_id=repo_id,
            path_id=path_id,
            path="hot.py",
            language="python",
            current_loc=10,
            complexity=10.0,
            churn_total=50,
            commit_count=10,
            first_seen=now,
            last_seen=now,
            is_deleted=False,
        )
    )
    db_session.commit()

    RiskEngine().run(RunContext(repo_id=repo_id, run_id=run_id), db_session)
    db_session.commit()

    finding = db_session.scalar(
        select(Finding).where(Finding.analysis_run_id == run_id, Finding.category == "risk")
    )
    assert finding is not None
    assert finding.signature == finding_signature("risk", "hot.py")


def test_layering_violation_signature_uses_from_to_path(db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/signature-layering")
    _add_dependency(db_session, repo_id, "ui/widget.py", "db/models.py")
    db_session.commit()

    run_id = _make_run(db_session, repo_id)
    ArchEngine().run(RunContext(repo_id=repo_id, run_id=run_id), db_session)
    db_session.commit()

    finding = db_session.scalar(
        select(Finding).where(Finding.analysis_run_id == run_id, Finding.category == "architecture")
    )
    assert finding is not None
    assert finding.signature == finding_signature("architecture", "ui/widget.py->db/models.py")
