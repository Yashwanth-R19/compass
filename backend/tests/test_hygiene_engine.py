import inspect
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import insert, select

from app.db.models import (
    AnalysisRun,
    AnalysisRunStatus,
    Commit,
    File,
    FileMetrics,
    Finding,
    HygieneEvent,
    Repo,
    RepoPath,
    RepoStatus,
    Severity,
    Subsystem,
    SubsystemMember,
)
from app.engines import hygiene
from app.engines.context import RunContext
from app.engines.hygiene import (
    HYGIENE_RISKY_SEVERITY,
    MAX_HYGIENE_FINDINGS,
    MIN_COMMITS_FOR_PERCENTILE,
    HygieneEngine,
)


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


def _add_file(db_session, repo_id: uuid.UUID, path: str, *, is_test: bool = False) -> int:
    path_id = _intern_paths(db_session, repo_id, [path])[path]
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
            is_test=is_test,
        )
    )
    db_session.flush()
    return path_id


def _seed_file_metrics(
    db_session, repo_id: uuid.UUID, run_id: uuid.UUID, path_ids: list[int]
) -> None:
    """Simulates RiskEngine's insert -- HygieneEngine UPDATEs these rows, it
    never inserts its own (see that engine's docstring)."""
    if not path_ids:
        return
    db_session.execute(
        insert(FileMetrics),
        [
            {"analysis_run_id": run_id, "repo_id": repo_id, "path_id": pid, "hotspot_rank": i}
            for i, pid in enumerate(path_ids)
        ],
    )


def _add_commit(
    db_session,
    repo_id: uuid.UUID,
    sha: str,
    file_paths: list[str],
    *,
    author_name: str = "tester",
    author_email: str = "tester@example.com",
    committed_at: datetime | None = None,
    message: str = "synthetic change",
    is_revert: bool = False,
    insertions: int = 1,
    deletions: int = 0,
) -> None:
    path_ids = _intern_paths(db_session, repo_id, file_paths)
    db_session.execute(
        insert(Commit),
        [
            {
                "repo_id": repo_id,
                "sha": sha,
                "author_name": author_name,
                "author_email": author_email,
                "committed_at": committed_at or datetime.now(UTC),
                "message": message,
                "is_fix": False,
                "is_revert": is_revert,
                "files_changed": len(file_paths),
                "insertions": insertions,
                "deletions": deletions,
                "changed_path_ids": [path_ids[p] for p in file_paths],
                "added_lines": [insertions for _ in file_paths],
                "deleted_lines": [deletions for _ in file_paths],
            }
        ],
    )


def test_no_hour_or_timezone_usage_in_scoring():
    """Session 07 hard constraint: time-of-day ("late-night commits are
    risky") must never be a hygiene signal -- folklore, timezone-dependent,
    unreliable. Asserted by grepping the module's own source for any
    hour/timezone-shaped attribute access."""
    source = inspect.getsource(hygiene)
    forbidden_tokens = [".hour", "utcoffset", ".tzinfo", "astimezone", ".weekday(", ".isoweekday("]
    for token in forbidden_tokens:
        assert token not in source, (
            f"hygiene.py must never read {token!r} -- time-of-day heuristics are "
            "explicitly forbidden (folklore, timezone-dependent, unreliable)"
        )


def test_oversized_threshold_is_distribution_derived_not_hardcoded(db_session):
    """Two repos with very different "normal" commit sizes: a commit
    touching 5 files is oversized in the repo whose commits are usually
    tiny, but NOT oversized in the repo whose commits are usually large --
    proving the threshold comes from each repo's OWN distribution rather
    than a fixed absolute number (Known Hazard #4's companion claim)."""
    small_repo_id = _make_repo(db_session, "https://github.com/fixture/hygiene-small-commits")
    for i in range(MIN_COMMITS_FOR_PERCENTILE + 5):
        _add_commit(db_session, small_repo_id, f"small-{i}", [f"f{i}.py"])
    # The "big" commit for this repo, identical in shape between both repos.
    _add_commit(
        db_session,
        small_repo_id,
        "small-big",
        [f"big{i}.py" for i in range(5)],
        insertions=50,
    )
    db_session.commit()
    small_run_id = _make_run(db_session, small_repo_id)
    HygieneEngine().run(RunContext(repo_id=small_repo_id, run_id=small_run_id), db_session)
    db_session.commit()

    large_repo_id = _make_repo(db_session, "https://github.com/fixture/hygiene-large-commits")
    for i in range(MIN_COMMITS_FOR_PERCENTILE + 5):
        _add_commit(
            db_session,
            large_repo_id,
            f"large-{i}",
            [f"f{i}-{j}.py" for j in range(6)],
            insertions=50,
        )
    _add_commit(
        db_session,
        large_repo_id,
        "large-big",
        [f"big{i}.py" for i in range(5)],
        insertions=50,
    )
    db_session.commit()
    large_run_id = _make_run(db_session, large_repo_id)
    HygieneEngine().run(RunContext(repo_id=large_repo_id, run_id=large_run_id), db_session)
    db_session.commit()

    small_oversized_shas = set(
        db_session.scalars(
            select(HygieneEvent.commit_sha).where(
                HygieneEvent.analysis_run_id == small_run_id, HygieneEvent.kind == "oversized"
            )
        ).all()
    )
    large_oversized_shas = set(
        db_session.scalars(
            select(HygieneEvent.commit_sha).where(
                HygieneEvent.analysis_run_id == large_run_id, HygieneEvent.kind == "oversized"
            )
        ).all()
    )

    assert "small-big" in small_oversized_shas
    assert "large-big" not in large_oversized_shas


def test_insufficient_history_below_min_commits_for_percentile(db_session):
    """Known Hazard #4: fewer than MIN_COMMITS_FOR_PERCENTILE commits ->
    no oversized detection at all, regardless of how large one commit looks
    relative to the others -- a percentile over ~5 points is noise."""
    repo_id = _make_repo(db_session, "https://github.com/fixture/hygiene-tiny-repo")
    for i in range(5):
        _add_commit(db_session, repo_id, f"c{i}", [f"f{i}.py"])
    _add_commit(
        db_session, repo_id, "the-big-one", [f"big{i}.py" for i in range(20)], insertions=500
    )
    db_session.commit()

    run_id = _make_run(db_session, repo_id)
    metadata = HygieneEngine().run(RunContext(repo_id=repo_id, run_id=run_id), db_session)
    db_session.commit()

    assert metadata["insufficient_history_for_oversized"] is True
    oversized_events = db_session.scalars(
        select(HygieneEvent).where(
            HygieneEvent.analysis_run_id == run_id, HygieneEvent.kind == "oversized"
        )
    ).all()
    assert oversized_events == []


def test_fixup_cluster_detected_and_persisted(db_session):
    """3 consecutive commits by the same author, overlapping files, within
    the time window, at least one WIP-style message -- one fixup_churn
    event, spanning all 3 shas."""
    repo_id = _make_repo(db_session, "https://github.com/fixture/hygiene-fixup")
    base = datetime.now(UTC)
    _add_commit(db_session, repo_id, "f1", ["shared.py"], committed_at=base, message="add feature")
    _add_commit(
        db_session,
        repo_id,
        "f2",
        ["shared.py"],
        committed_at=base + timedelta(minutes=5),
        message="wip",
    )
    _add_commit(
        db_session,
        repo_id,
        "f3",
        ["shared.py"],
        committed_at=base + timedelta(minutes=10),
        message="actually fix it",
    )
    # Pad with enough unrelated commits to clear MIN_COMMITS_FOR_PERCENTILE
    # without disturbing the cluster (different author, no overlap).
    for i in range(MIN_COMMITS_FOR_PERCENTILE):
        _add_commit(
            db_session,
            repo_id,
            f"pad-{i}",
            [f"pad{i}.py"],
            author_name="other",
            author_email="other@example.com",
            committed_at=base + timedelta(days=i + 1),
        )
    db_session.commit()

    run_id = _make_run(db_session, repo_id)
    HygieneEngine().run(RunContext(repo_id=repo_id, run_id=run_id), db_session)
    db_session.commit()

    fixup_events = db_session.scalars(
        select(HygieneEvent).where(
            HygieneEvent.analysis_run_id == run_id, HygieneEvent.kind == "fixup_churn"
        )
    ).all()
    assert len(fixup_events) == 1
    assert set(fixup_events[0].detail["commit_shas"]) == {"f1", "f2", "f3"}
    assert fixup_events[0].commit_sha == "f1"


def test_risky_commit_scores_and_severity_never_exceeds_med(db_session):
    """A commit touching >=3 subsystems, top-quintile churn, no test file,
    and a short message scores 4/4 and is reported (>= RISKY_MIN_SCORE)."""
    repo_id = _make_repo(db_session, "https://github.com/fixture/hygiene-risky")
    run_id = _make_run(db_session, repo_id)

    path_ids = {
        p: _add_file(db_session, repo_id, p)
        for p in ["a.py", "b.py", "c.py", "small1.py", "small2.py"]
    }
    db_session.flush()

    # Three subsystems, one file each -- a.py/b.py/c.py.
    for i, path in enumerate(["a.py", "b.py", "c.py"]):
        sub = Subsystem(
            analysis_run_id=run_id,
            repo_id=repo_id,
            label=f"sub{i}",
            label_source="fallback",
            file_count=1,
            total_loc=10,
            internal_edges=0,
            external_edges=0,
            cohesion=0.0,
            rank=i,
        )
        db_session.add(sub)
        db_session.flush()
        db_session.add(SubsystemMember(subsystem_id=sub.id, path_id=path_ids[path], centrality=0.1))
    db_session.flush()

    # Padding commits establish a low churn baseline so the risky commit's
    # large churn clears the top-quintile threshold.
    for i in range(MIN_COMMITS_FOR_PERCENTILE):
        _add_commit(db_session, repo_id, f"pad-{i}", ["small1.py"], insertions=1)

    _add_commit(
        db_session,
        repo_id,
        "risky1",
        ["a.py", "b.py", "c.py"],
        message="wip",  # < 15 chars, short message condition
        insertions=500,
    )
    db_session.commit()

    _seed_file_metrics(db_session, repo_id, run_id, list(path_ids.values()))
    db_session.commit()

    metadata = HygieneEngine().run(RunContext(repo_id=repo_id, run_id=run_id), db_session)
    db_session.commit()

    assert metadata["risky_commits"] == 1
    risky_event = db_session.scalar(
        select(HygieneEvent).where(
            HygieneEvent.analysis_run_id == run_id, HygieneEvent.kind == "risky_commit"
        )
    )
    assert risky_event is not None
    assert risky_event.detail["score"] == 4

    findings = db_session.scalars(
        select(Finding).where(Finding.analysis_run_id == run_id, Finding.category == "hygiene")
    ).all()
    assert findings
    assert all(f.severity != Severity.high for f in findings)
    assert any(f.severity == HYGIENE_RISKY_SEVERITY for f in findings)
    assert len(findings) <= MAX_HYGIENE_FINDINGS


def test_per_file_instability_weights_reverts_double(db_session):
    """instability_score's raw input is oversized_count + fixup_count +
    2*revert_count -- a file touched only by a single revert commit must
    score higher (via the doubled weight) than one touched only by a single
    non-revert, non-oversized, non-fixup commit."""
    repo_id = _make_repo(db_session, "https://github.com/fixture/hygiene-instability")
    run_id = _make_run(db_session, repo_id)

    reverted_id = _add_file(db_session, repo_id, "reverted.py")
    plain_id = _add_file(db_session, repo_id, "plain.py")
    db_session.flush()

    for i in range(MIN_COMMITS_FOR_PERCENTILE):
        _add_commit(db_session, repo_id, f"pad-{i}", [f"pad{i}.py"])
    _add_commit(db_session, repo_id, "revert1", ["reverted.py"], is_revert=True)
    _add_commit(db_session, repo_id, "plain1", ["plain.py"])
    db_session.commit()

    _seed_file_metrics(db_session, repo_id, run_id, [reverted_id, plain_id])
    db_session.commit()

    HygieneEngine().run(RunContext(repo_id=repo_id, run_id=run_id), db_session)
    db_session.commit()

    rows = {
        m.path_id: m
        for m in db_session.scalars(
            select(FileMetrics).where(FileMetrics.analysis_run_id == run_id)
        ).all()
    }
    assert rows[reverted_id].revert_cycle_count == 1
    assert rows[plain_id].revert_cycle_count == 0
    assert rows[reverted_id].instability_score > rows[plain_id].instability_score


def test_no_commits_is_a_harmless_noop(db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/hygiene-empty")
    run_id = _make_run(db_session, repo_id)
    metadata = HygieneEngine().run(RunContext(repo_id=repo_id, run_id=run_id), db_session)
    db_session.commit()
    assert metadata == {
        "events_emitted": 0,
        "findings_emitted": 0,
        "insufficient_history_for_oversized": True,
    }
