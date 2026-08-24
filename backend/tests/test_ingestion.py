import subprocess
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.db.models import (
    AnalysisRun,
    AnalysisRunStatus,
    AnalysisStage,
    Commit,
    File,
    Health,
    Job,
    JobStatus,
    Repo,
    RepoPath,
    RepoStatus,
    StageStatus,
)
from app.ingestion.cloner import clone_repo
from app.ingestion.miner import mine_repo
from app.jobs.runner import run_ingestion_job
from app.jobs.stages import ALL_STAGES, FACT_STAGES, INSIGHT_STAGES


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _init_fixture_repo(root: Path) -> Path:
    """A tiny local git repo with 3 commits touching known files, used to
    exercise clone -> mine -> persist without hitting a real remote.
    """
    repo_dir = root / "fixture-repo"
    repo_dir.mkdir()
    _git(repo_dir, "init", "-b", "main")
    _git(repo_dir, "config", "user.email", "test@example.com")
    _git(repo_dir, "config", "user.name", "Test User")

    (repo_dir / "a.py").write_text("def foo():\n    return 1\n")
    _git(repo_dir, "add", "a.py")
    _git(repo_dir, "commit", "-m", "add a.py")

    (repo_dir / "b.py").write_text("def bar():\n    return 2\n")
    (repo_dir / "a.py").write_text("def foo():\n    if True:\n        return 1\n    return 0\n")
    _git(repo_dir, "add", "a.py", "b.py")
    _git(repo_dir, "commit", "-m", "fix foo and add b.py")

    _git(repo_dir, "rm", "b.py")
    _git(repo_dir, "commit", "-m", "remove b.py")

    return repo_dir


@pytest.fixture
def fixture_repo(tmp_path):
    return _init_fixture_repo(tmp_path)


def _make_repo_and_job(db_session, url: str) -> tuple:
    repo = Repo(url=url, owner="fixture", name="repo", status=RepoStatus.pending)
    db_session.add(repo)
    db_session.flush()
    job = Job(repo_id=repo.id, job_type="ingestion", status=JobStatus.queued, progress=0)
    db_session.add(job)
    db_session.commit()
    return repo.id, job.id


def _new_job(db_session, repo_id):
    job = Job(repo_id=repo_id, job_type="ingestion", status=JobStatus.queued, progress=0)
    db_session.add(job)
    db_session.commit()
    return job.id


def _stage_statuses(db_session, run_id) -> dict[str, StageStatus]:
    rows = db_session.scalars(select(AnalysisStage).where(AnalysisStage.run_id == run_id)).all()
    return {s.name: s.status for s in rows}


def test_mine_and_persist_fixture_repo(fixture_repo, db_session, monkeypatch):
    captured_clone_path = {}
    original_clone = clone_repo

    def spy_clone(url):
        path = original_clone(url)
        captured_clone_path["path"] = path
        return path

    monkeypatch.setattr("app.jobs.runner.clone_repo", spy_clone)

    repo_id, job_id = _make_repo_and_job(db_session, str(fixture_repo))

    run_ingestion_job(repo_id, job_id)

    # Clone is disposable: it must be gone once the job finishes.
    assert "path" in captured_clone_path
    assert not Path(captured_clone_path["path"]).exists()

    commits = db_session.scalars(select(Commit).where(Commit.repo_id == repo_id)).all()
    files = db_session.scalars(select(File).where(File.repo_id == repo_id)).all()

    assert len(commits) == 3

    files_by_path = {f.path: f for f in files}
    assert set(files_by_path) == {"a.py", "b.py"}
    assert files_by_path["b.py"].is_deleted is True
    assert files_by_path["a.py"].is_deleted is False
    assert files_by_path["a.py"].commit_count == 2

    # commit1 touches a.py; commit2 touches a.py+b.py; commit3 touches b.py --
    # changed_path_ids replaces the old commit_files join table (Phase 1).
    total_touches = sum(len(c.changed_path_ids) for c in commits)
    assert total_touches == 4

    for c in commits:
        assert len(c.changed_path_ids) == len(c.added_lines) == len(c.deleted_lines)

    path_ids = {row for c in commits for row in c.changed_path_ids}
    real_path_ids = set(
        db_session.scalars(select(RepoPath.id).where(RepoPath.repo_id == repo_id)).all()
    )
    assert path_ids <= real_path_ids

    job = db_session.get(Job, job_id)
    assert job.status == JobStatus.done
    assert job.progress == 100
    assert job.error is None

    repo = db_session.get(Repo, repo_id)
    assert repo.status == RepoStatus.ready
    assert repo.commit_count == 3
    assert repo.head_sha  # resolved via `git ls-remote`, non-empty
    assert repo.current_run_id is not None

    # Phase 02: a fresh repo's first-ever run computes everything -- no
    # stage is skipped, and every stage (fact + insight) reached done.
    run = db_session.get(AnalysisRun, repo.current_run_id)
    assert run.status == AnalysisRunStatus.ready
    assert run.head_sha == repo.head_sha

    statuses = _stage_statuses(db_session, run.id)
    assert set(statuses) == {s.name for s in ALL_STAGES}
    assert all(status == StageStatus.done for status in statuses.values())


def _touch_count(db_session, repo_id) -> int:
    commits = db_session.scalars(select(Commit).where(Commit.repo_id == repo_id)).all()
    return sum(len(c.changed_path_ids) for c in commits)


def test_reanalysis_with_unchanged_head_sha_skips_fact_stages(fixture_repo, db_session):
    """Part G: re-running ingestion against an unchanged head_sha must skip
    the four FACT stages entirely (near-instant re-analysis, Part C step 3)
    while still producing a fresh, correctly-computed set of Insight rows for
    the new run -- and must never duplicate Facts (the older
    "idempotent re-ingestion" invariant, now achieved via skip rather than
    wipe-and-reinsert)."""
    repo_id, job1_id = _make_repo_and_job(db_session, str(fixture_repo))

    run_ingestion_job(repo_id, job1_id)
    db_session.expire_all()

    repo = db_session.get(Repo, repo_id)
    first_run_id = repo.current_run_id
    commits_after_first = db_session.scalar(
        select(func.count()).select_from(Commit).where(Commit.repo_id == repo_id)
    )
    files_after_first = db_session.scalar(
        select(func.count()).select_from(File).where(File.repo_id == repo_id)
    )
    repo_paths_after_first = db_session.scalar(
        select(func.count()).select_from(RepoPath).where(RepoPath.repo_id == repo_id)
    )
    touches_after_first = _touch_count(db_session, repo_id)

    job2_id = _new_job(db_session, repo_id)
    run_ingestion_job(repo_id, job2_id)
    db_session.expire_all()

    repo = db_session.get(Repo, repo_id)
    second_run_id = repo.current_run_id
    assert second_run_id != first_run_id

    commits_after_second = db_session.scalar(
        select(func.count()).select_from(Commit).where(Commit.repo_id == repo_id)
    )
    files_after_second = db_session.scalar(
        select(func.count()).select_from(File).where(File.repo_id == repo_id)
    )
    repo_paths_after_second = db_session.scalar(
        select(func.count()).select_from(RepoPath).where(RepoPath.repo_id == repo_id)
    )
    touches_after_second = _touch_count(db_session, repo_id)

    assert commits_after_first == 3
    assert commits_after_second == commits_after_first
    assert files_after_second == files_after_first
    assert repo_paths_after_second == repo_paths_after_first
    assert touches_after_second == touches_after_first

    # The FACT stages were skipped outright on the second run...
    second_run_statuses = _stage_statuses(db_session, second_run_id)
    for s in FACT_STAGES:
        assert second_run_statuses[s.name] == StageStatus.skipped
    # ...but every INSIGHT stage still ran fresh for the new run_id.
    for s in INSIGHT_STAGES:
        assert second_run_statuses[s.name] == StageStatus.done

    # Results are versioned, not overwritten: two distinct runs now each have
    # their own Health row for the same repo_id (HealthEngine always writes
    # exactly one row per run, unconditionally -- unlike Coupling, which this
    # particular 3-commit fixture never produces a single pair for, since no
    # pair of files ever co-changes even FALLBACK_MIN_SHARED_REVS times).
    run_ids_with_health = set(
        db_session.scalars(
            select(Health.analysis_run_id).where(Health.repo_id == repo_id).distinct()
        ).all()
    )
    assert run_ids_with_health == {first_run_id, second_run_id}

    # The first run is superseded, not deleted -- its rows are untouched.
    first_run = db_session.get(AnalysisRun, first_run_id)
    assert first_run.status == AnalysisRunStatus.superseded
    second_run = db_session.get(AnalysisRun, second_run_id)
    assert second_run.status == AnalysisRunStatus.ready


def test_full_replace_when_head_sha_changes_and_old_run_stays_intact(fixture_repo, db_session):
    """When a repo genuinely gets new commits, the FACT stages must run for
    real (not skip), Facts get fully replaced, and -- the load-bearing
    correctness property behind leaving repo_paths out of wipe_facts (see
    app/db/wipe.py) -- a path that exists both before and after the change
    keeps the SAME repo_paths.id, so the FIRST run's Insight rows (which
    reference that id) are still valid and readable after the second run.
    """
    repo_id, job1_id = _make_repo_and_job(db_session, str(fixture_repo))
    run_ingestion_job(repo_id, job1_id)
    db_session.expire_all()

    repo = db_session.get(Repo, repo_id)
    first_run_id = repo.current_run_id
    first_head_sha = repo.head_sha
    a_py_id_before = db_session.scalar(
        select(RepoPath.id).where(RepoPath.repo_id == repo_id, RepoPath.path == "a.py")
    )

    # A genuinely new commit -- head_sha must change.
    (fixture_repo / "a.py").write_text("def foo():\n    return 42\n")
    _git(fixture_repo, "add", "a.py")
    _git(fixture_repo, "commit", "-m", "change foo again")

    job2_id = _new_job(db_session, repo_id)
    run_ingestion_job(repo_id, job2_id)
    db_session.expire_all()

    repo = db_session.get(Repo, repo_id)
    second_run_id = repo.current_run_id
    assert repo.head_sha != first_head_sha
    assert repo.commit_count == 4

    second_run_statuses = _stage_statuses(db_session, second_run_id)
    for s in FACT_STAGES:
        assert second_run_statuses[s.name] == StageStatus.done  # not skipped this time

    a_py_id_after = db_session.scalar(
        select(RepoPath.id).where(RepoPath.repo_id == repo_id, RepoPath.path == "a.py")
    )
    assert a_py_id_after == a_py_id_before

    # The first run's own Insight rows must still exist and still resolve
    # -- nothing cascaded away when Facts were replaced.
    first_run = db_session.get(AnalysisRun, first_run_id)
    assert first_run.status == AnalysisRunStatus.superseded
    first_run_stage_rows = db_session.scalars(
        select(AnalysisStage).where(AnalysisStage.run_id == first_run_id)
    ).all()
    assert len(first_run_stage_rows) == len(ALL_STAGES)


def test_failed_insight_stage_leaves_current_run_id_on_previous_good_run(
    fixture_repo, db_session, monkeypatch
):
    """Part G: a failure inside an Insight stage on a re-analysis must never
    blank out a repo that already had a good run -- repos.current_run_id/
    head_sha stay pointed at the last successful run, the new run and its
    failing stage are marked failed, and repos.status flips to failed."""
    repo_id, job1_id = _make_repo_and_job(db_session, str(fixture_repo))
    run_ingestion_job(repo_id, job1_id)
    db_session.expire_all()

    repo = db_session.get(Repo, repo_id)
    good_run_id = repo.current_run_id
    good_head_sha = repo.head_sha

    def _broken_max_coupling_by_path(repo_id, run_id, session):
        raise RuntimeError("synthetic risk engine failure")

    monkeypatch.setattr("app.engines.risk.max_coupling_by_path", _broken_max_coupling_by_path)

    job2_id = _new_job(db_session, repo_id)
    with pytest.raises(RuntimeError, match="synthetic risk engine failure"):
        run_ingestion_job(repo_id, job2_id)
    db_session.expire_all()

    repo = db_session.get(Repo, repo_id)
    assert repo.status == RepoStatus.failed
    # CRUCIAL: the repo must still point at the previous good run.
    assert repo.current_run_id == good_run_id
    assert repo.head_sha == good_head_sha

    job2 = db_session.get(Job, job2_id)
    assert job2.status == JobStatus.failed
    assert "synthetic risk engine failure" in job2.error

    failed_runs = db_session.scalars(
        select(AnalysisRun).where(AnalysisRun.repo_id == repo_id, AnalysisRun.id != good_run_id)
    ).all()
    assert len(failed_runs) == 1
    failed_run = failed_runs[0]
    assert failed_run.status == AnalysisRunStatus.failed
    assert failed_run.error and "synthetic risk engine failure" in failed_run.error

    # The FACT stages were skipped (head_sha unchanged); risk failed;
    # knowledge, onboarding, and rank, which all run after risk, never even
    # started. Session 04: the standalone "overlay" stage no longer exists --
    # OverlayEngine now runs inside "architecture" (see app/jobs/stages.py),
    # and "subsystems" is new. Session 06: the standalone "health" stage no
    # longer exists either -- HealthEngine now runs inside "onboarding".
    statuses = _stage_statuses(db_session, failed_run.id)
    for s in FACT_STAGES:
        assert statuses[s.name] == StageStatus.skipped
    assert statuses["coupling"] == StageStatus.done
    assert statuses["subsystems"] == StageStatus.done
    assert statuses["architecture"] == StageStatus.done
    assert statuses["risk"] == StageStatus.failed
    assert statuses["knowledge"] == StageStatus.pending
    assert statuses["onboarding"] == StageStatus.pending
    assert statuses["rank"] == StageStatus.pending

    # The previous good run's own data is untouched.
    good_run = db_session.get(AnalysisRun, good_run_id)
    assert good_run.status == AnalysisRunStatus.ready


def test_mined_paths_are_posix_even_on_windows(tmp_path):
    """Regression test: the miner normalizes every path to forward slashes
    (app/ingestion/miner.py's ``_normalize_path``) even though git's own
    --numstat output is already posix -- defense in depth, since a backslash
    path would silently break `is_deleted` (comparing it against
    `_final_tree_paths`' posix set never matches) and the hidden-dependency
    overlay too, since app/languages/scanner.py always produces posix paths.
    The original fixture repo (top-level a.py/b.py only) never caught this
    because a bare filename has no separator to get mangled.
    """
    repo_dir = tmp_path / "nested-fixture-repo"
    repo_dir.mkdir()
    _git(repo_dir, "init", "-b", "main")
    _git(repo_dir, "config", "user.email", "test@example.com")
    _git(repo_dir, "config", "user.name", "Test User")

    (repo_dir / "pkg").mkdir()
    (repo_dir / "pkg" / "a.py").write_text("value = 1\n")
    _git(repo_dir, "add", "pkg/a.py")
    _git(repo_dir, "commit", "-m", "add pkg/a.py")

    (repo_dir / "pkg" / "b.py").write_text("value = 2\n")
    _git(repo_dir, "add", "pkg/b.py")
    _git(repo_dir, "commit", "-m", "add pkg/b.py")

    mined = mine_repo(str(repo_dir))

    paths = {f.path for f in mined.files}
    assert paths == {"pkg/a.py", "pkg/b.py"}
    assert not any("\\" in p for p in paths)

    files_by_path = {f.path: f for f in mined.files}
    assert files_by_path["pkg/a.py"].is_deleted is False
    assert files_by_path["pkg/b.py"].is_deleted is False

    for commit in mined.commits:
        assert not any("\\" in p for p in commit.file_paths)
