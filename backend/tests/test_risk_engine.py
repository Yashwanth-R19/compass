import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import insert, select

from app.db.models import Commit, Coupling, File, FileMetrics, Finding, Repo, RepoPath, RepoStatus
from app.engines.risk import MAX_RISK_FINDINGS, RiskEngine


def _make_repo(db_session, url: str) -> uuid.UUID:
    repo = Repo(url=url, owner="fixture", name="repo", status=RepoStatus.pending)
    db_session.add(repo)
    db_session.commit()
    return repo.id


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


def _add_file(
    db_session,
    repo_id: uuid.UUID,
    path: str,
    *,
    churn_total: int,
    complexity: float,
    commit_count: int,
    language: str = "python",
) -> uuid.UUID:
    path_id = _intern_paths(db_session, repo_id, [path])[path]
    now = datetime.now(UTC)
    file = File(
        repo_id=repo_id,
        path_id=path_id,
        path=path,
        language=language,
        current_loc=100,
        complexity=complexity,
        churn_total=churn_total,
        commit_count=commit_count,
        first_seen=now,
        last_seen=now,
        is_deleted=False,
    )
    db_session.add(file)
    db_session.flush()
    return file.id


def _add_coupling(db_session, repo_id: uuid.UUID, path_a: str, path_b: str, degree: float) -> None:
    path_ids = _intern_paths(db_session, repo_id, [path_a, path_b])
    db_session.execute(
        insert(Coupling),
        [
            {
                "repo_id": repo_id,
                "path_a_id": path_ids[path_a],
                "path_b_id": path_ids[path_b],
                "shared_revs": 9,
                "coupling_degree": degree,
                "avg_revs": 9.5,
            }
        ],
    )


def _add_commit(
    db_session, repo_id: uuid.UUID, sha: str, file_paths: list[str], is_fix: bool = False
) -> None:
    path_ids = _intern_paths(db_session, repo_id, file_paths)
    commit = Commit(
        repo_id=repo_id,
        sha=sha,
        author_name="tester",
        author_email="tester@example.com",
        committed_at=datetime.now(UTC),
        message="fix: bug" if is_fix else "synthetic",
        is_fix=is_fix,
        is_revert=False,
        files_changed=len(file_paths),
        insertions=0,
        deletions=0,
        changed_path_ids=[path_ids[p] for p in file_paths],
        added_lines=[0 for _ in file_paths],
        deleted_lines=[0 for _ in file_paths],
    )
    db_session.add(commit)
    db_session.flush()


def test_hotspot_ranking_matches_locked_formula(db_session):
    """Locks in the exact weighted formula (CLAUDE.md / master-context.md
    sec 8.1) against HeuristicBaseline's per-repo min-max normalizer, with
    numbers chosen so the expected risk_score is hand-computable.
    """
    repo_id = _make_repo(db_session, "https://github.com/fixture/risk-formula")
    # churn_x_complexity: a=100, b=1, c=25 -> min=1, max=100, range=99
    # commit_count:       a=10,  b=1, c=5  -> min=1, max=10,  range=9
    _add_file(db_session, repo_id, "a.py", churn_total=10, complexity=10.0, commit_count=10)
    _add_file(db_session, repo_id, "b.py", churn_total=1, complexity=1.0, commit_count=1)
    _add_file(db_session, repo_id, "c.py", churn_total=5, complexity=5.0, commit_count=5)
    db_session.flush()

    # max_coupling_degree: a=0.9, b=0.9, c=0.0 (no pairs) -> min=0, max=0.9
    _add_coupling(db_session, repo_id, "a.py", "b.py", 0.9)
    db_session.commit()

    metadata = RiskEngine().run(repo_id, db_session)
    db_session.commit()

    assert metadata["files_scored"] == 3

    rows = {
        m.file_id: m
        for m in db_session.scalars(
            select(FileMetrics)
            .join(File, File.id == FileMetrics.file_id)
            .where(File.repo_id == repo_id)
        ).all()
    }
    by_path = {
        f.path: rows[f.id]
        for f in db_session.scalars(select(File).where(File.repo_id == repo_id)).all()
    }

    # a: norm(churn*cx)=1.0, norm(coupling)=1.0, norm(commits)=1.0
    # risk_score = 0.6*1 + 0.25*1 + 0.15*1 = 1.0
    assert by_path["a.py"].risk_score == pytest.approx(1.0)
    assert by_path["a.py"].hotspot_rank == 0

    # b: norm(churn*cx)=0.0, norm(coupling)=1.0, norm(commits)=0.0
    # risk_score = 0.6*0 + 0.25*1 + 0.15*0 = 0.25
    assert by_path["b.py"].risk_score == pytest.approx(0.25)

    # c: norm(churn*cx)=24/99, norm(coupling)=0.0, norm(commits)=4/9
    # risk_score = 0.6*(24/99) + 0.25*0 + 0.15*(4/9)
    expected_c = 0.60 * (24 / 99) + 0.15 * (4 / 9)
    assert by_path["c.py"].risk_score == pytest.approx(expected_c)

    # b (0.25) outranks c (~0.212) despite c's higher churn*complexity,
    # because coupling pulled b up -- exercises all three weighted terms.
    assert by_path["b.py"].hotspot_rank == 1
    assert by_path["c.py"].hotspot_rank == 2

    # risk_confidence = min(1.0, commit_count / 10), INDEPENDENT of risk_score
    assert by_path["a.py"].risk_confidence == pytest.approx(1.0)
    assert by_path["b.py"].risk_confidence == pytest.approx(0.1)
    assert by_path["c.py"].risk_confidence == pytest.approx(0.5)


def test_top_finding_uses_most_recent_fix_commit_as_evidence(db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/risk-evidence")
    _add_file(db_session, repo_id, "hot.py", churn_total=100, complexity=20.0, commit_count=15)
    _add_file(db_session, repo_id, "cold.py", churn_total=1, complexity=1.0, commit_count=1)
    db_session.flush()

    _add_commit(db_session, repo_id, "c1", ["hot.py"], is_fix=False)
    _add_commit(db_session, repo_id, "c2-fix", ["hot.py"], is_fix=True)
    db_session.commit()

    RiskEngine().run(repo_id, db_session)
    db_session.commit()

    findings = db_session.scalars(
        select(Finding).where(Finding.repo_id == repo_id, Finding.category == "risk")
    ).all()
    assert len(findings) == 2

    path_by_id = {
        row.id: row.path
        for row in db_session.execute(
            select(RepoPath.id, RepoPath.path).where(RepoPath.repo_id == repo_id)
        ).all()
    }
    top = next(f for f in findings if path_by_id[f.path_id] == "hot.py")
    assert top.evidence_sha == "c2-fix"
    assert 0.0 <= top.confidence <= 1.0
    assert top.severity is not None


def test_findings_capped_at_max_risk_findings(db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/risk-cap")
    for i in range(MAX_RISK_FINDINGS + 5):
        _add_file(
            db_session, repo_id, f"f{i}.py", churn_total=i + 1, complexity=1.0, commit_count=1
        )
    db_session.commit()

    metadata = RiskEngine().run(repo_id, db_session)
    db_session.commit()

    assert metadata["files_scored"] == MAX_RISK_FINDINGS + 5
    assert metadata["findings_emitted"] == MAX_RISK_FINDINGS

    findings = db_session.scalars(
        select(Finding).where(Finding.repo_id == repo_id, Finding.category == "risk")
    ).all()
    assert len(findings) == MAX_RISK_FINDINGS

    all_metrics = db_session.scalars(
        select(FileMetrics)
        .join(File, File.id == FileMetrics.file_id)
        .where(File.repo_id == repo_id)
    ).all()
    assert len(all_metrics) == MAX_RISK_FINDINGS + 5


def test_no_files_is_a_harmless_noop(db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/risk-empty")
    metadata = RiskEngine().run(repo_id, db_session)
    db_session.commit()
    assert metadata == {"files_scored": 0, "findings_emitted": 0}
