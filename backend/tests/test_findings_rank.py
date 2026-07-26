import uuid
from datetime import UTC, datetime

from sqlalchemy import insert, select

from app.db.models import (
    Commit,
    CommitFile,
    Dependency,
    File,
    Finding,
    Repo,
    RepoStatus,
    Severity,
)
from app.engines.architecture import ArchEngine
from app.engines.coupling import CouplingEngine
from app.engines.findings import FindingsRankEngine, impact_score
from app.engines.health import HealthEngine
from app.engines.overlay import OverlayEngine
from app.engines.risk import RiskEngine


def _make_repo(db_session, url: str) -> uuid.UUID:
    repo = Repo(url=url, owner="fixture", name="repo", status=RepoStatus.pending)
    db_session.add(repo)
    db_session.commit()
    return repo.id


def test_global_rank_orders_by_severity_then_confidence(db_session):
    """Findings from different categories interleave correctly: severity is
    the primary key (a low-confidence high finding still beats a
    high-confidence med finding), confidence only breaks ties within the
    same severity."""
    repo_id = _make_repo(db_session, "https://github.com/fixture/findings-rank-basic")
    rows = [
        {
            "id": uuid.uuid4(),
            "repo_id": repo_id,
            "category": "architecture",
            "severity": Severity.med,
            "confidence": 0.95,
            "file_path": None,
            "evidence_sha": None,
            "title": "med-high-confidence",
            "detail": "",
            "rank": 0,
        },
        {
            "id": uuid.uuid4(),
            "repo_id": repo_id,
            "category": "risk",
            "severity": Severity.high,
            "confidence": 0.1,
            "file_path": "hot.py",
            "evidence_sha": "abc123",
            "title": "high-low-confidence",
            "detail": "",
            "rank": 0,
        },
        {
            "id": uuid.uuid4(),
            "repo_id": repo_id,
            "category": "hidden_dependency",
            "severity": Severity.low,
            "confidence": 0.9,
            "file_path": None,
            "evidence_sha": None,
            "title": "low-high-confidence",
            "detail": "",
            "rank": 0,
        },
        {
            "id": uuid.uuid4(),
            "repo_id": repo_id,
            "category": "risk",
            "severity": Severity.high,
            "confidence": 0.8,
            "file_path": "hotter.py",
            "evidence_sha": "def456",
            "title": "high-high-confidence",
            "detail": "",
            "rank": 0,
        },
    ]
    db_session.execute(insert(Finding), rows)
    db_session.commit()

    metadata = FindingsRankEngine().run(repo_id, db_session)
    db_session.commit()

    assert metadata["findings_ranked"] == 4

    ranked = db_session.scalars(
        select(Finding).where(Finding.repo_id == repo_id).order_by(Finding.rank)
    ).all()
    titles_in_order = [f.title for f in ranked]
    assert titles_in_order == [
        "high-high-confidence",  # high severity, 0.8 confidence
        "high-low-confidence",  # high severity, 0.1 confidence -- still beats med/low
        "med-high-confidence",  # med severity
        "low-high-confidence",  # low severity, even with 0.9 confidence
    ]
    assert [f.rank for f in ranked] == [0, 1, 2, 3]

    # Every finding has severity, confidence in [0,1]; evidence_sha only
    # where the emitter actually had a commit to point at.
    for f in ranked:
        assert f.severity in Severity
        assert 0.0 <= f.confidence <= 1.0
    assert next(f for f in ranked if f.title == "high-high-confidence").evidence_sha == "def456"


def test_no_findings_is_a_harmless_noop(db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/findings-rank-empty")
    metadata = FindingsRankEngine().run(repo_id, db_session)
    db_session.commit()
    assert metadata == {"findings_ranked": 0}


def _add_commit(db_session, repo_id: uuid.UUID, sha: str, file_paths: list[str]) -> None:
    commit = Commit(
        repo_id=repo_id,
        sha=sha,
        author_name="tester",
        author_email="tester@example.com",
        committed_at=datetime.now(UTC),
        message="synthetic",
        is_fix=False,
        is_revert=False,
        files_changed=len(file_paths),
        insertions=0,
        deletions=0,
    )
    db_session.add(commit)
    db_session.flush()
    db_session.execute(
        insert(CommitFile),
        [{"id": uuid.uuid4(), "commit_id": commit.id, "file_path": p} for p in file_paths],
    )


def _add_file(
    db_session,
    repo_id: uuid.UUID,
    path: str,
    churn_total: int,
    complexity: float,
    commit_count: int,
) -> None:
    now = datetime.now(UTC)
    db_session.add(
        File(
            repo_id=repo_id,
            path=path,
            language="python",
            current_loc=10,
            complexity=complexity,
            churn_total=churn_total,
            commit_count=commit_count,
            first_seen=now,
            last_seen=now,
            is_deleted=False,
        )
    )


def test_full_pipeline_produces_one_globally_ranked_stream(db_session):
    """End-to-end: Coupling -> Architecture -> Overlay -> Risk -> Health ->
    FindingsRank, on a fixture engineered to trigger all three finding
    categories at once. Asserts the anti-alert-fatigue contract (master-
    context.md sec 7): every finding has severity + confidence in [0,1], and
    the persisted rank is a single, strictly non-increasing-impact ordering
    across categories, not per-category local ranks.
    """
    repo_id = _make_repo(db_session, "https://github.com/fixture/findings-rank-pipeline")
    # a.py/c.py co-change a lot with no import between them -> hidden dependency.
    for i in range(6):
        _add_commit(db_session, repo_id, f"ac{i}", ["a.py", "c.py"])
    db_session.commit()

    # Planted structural cycle x<->y -> architecture finding.
    db_session.execute(
        insert(Dependency),
        [
            {
                "id": uuid.uuid4(),
                "repo_id": repo_id,
                "from_path": "x.py",
                "to_path": "y.py",
                "dep_type": "import",
            },
            {
                "id": uuid.uuid4(),
                "repo_id": repo_id,
                "from_path": "y.py",
                "to_path": "x.py",
                "dep_type": "import",
            },
        ],
    )

    # Files so RiskEngine has something to score/rank/emit.
    _add_file(db_session, repo_id, "a.py", churn_total=50, complexity=10.0, commit_count=6)
    _add_file(db_session, repo_id, "c.py", churn_total=50, complexity=10.0, commit_count=6)
    _add_file(db_session, repo_id, "x.py", churn_total=1, complexity=1.0, commit_count=1)
    _add_file(db_session, repo_id, "y.py", churn_total=1, complexity=1.0, commit_count=1)
    db_session.commit()

    CouplingEngine().run(repo_id, db_session)
    ArchEngine().run(repo_id, db_session)
    OverlayEngine().run(repo_id, db_session)
    RiskEngine().run(repo_id, db_session)
    HealthEngine().run(repo_id, db_session)
    FindingsRankEngine().run(repo_id, db_session)
    db_session.commit()

    findings = db_session.scalars(
        select(Finding).where(Finding.repo_id == repo_id).order_by(Finding.rank)
    ).all()

    categories = {f.category for f in findings}
    assert "hidden_dependency" in categories
    assert "architecture" in categories
    assert "risk" in categories

    for f in findings:
        assert f.severity in Severity
        assert 0.0 <= f.confidence <= 1.0
        if f.category == "risk" and f.file_path in ("a.py", "c.py"):
            # a.py/c.py have real commits in this fixture; x.py/y.py don't.
            assert f.evidence_sha is not None

    # rank is a contiguous 0..n-1 permutation, and impact_score is
    # non-increasing across it -- the single global ordering, not
    # separate per-category sequences that would each restart at 0.
    assert [f.rank for f in findings] == list(range(len(findings)))
    scores = [impact_score(f.severity, f.confidence) for f in findings]
    assert scores == sorted(scores, reverse=True)
