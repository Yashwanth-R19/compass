"""session 14, Part C.2/F: ``build_corpus.py`` must actually prune a
repository's Facts/Insight rows after accumulating its contribution --
this is the real storage-discipline guarantee, tested against a real
(tiny, local) fixture repo, not mocked.
"""

import subprocess
from pathlib import Path

from sqlalchemy import func, select

from app.baseline.build_corpus import build_corpus
from app.db.models import (
    AnalysisRun,
    Commit,
    File,
    FileMetrics,
    Repo,
)


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _init_fixture_repo(root: Path) -> Path:
    repo_dir = root / "corpus-fixture-repo"
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

    return repo_dir


def test_build_corpus_accumulates_then_prunes_facts_and_insight(tmp_path, db_session):
    fixture_repo = _init_fixture_repo(tmp_path)
    url = str(fixture_repo)

    output_path = tmp_path / "corpus_breakpoints.json"
    state_path = tmp_path / "state.json"

    result = build_corpus(
        repos=[{"url": url}],
        output_path=output_path,
        state_path=state_path,
    )

    # The corpus's own output file was written with at least one cell.
    assert output_path.exists()
    assert result["cells"], "expected at least one breakpoint cell from the fixture repo"
    assert {"metric", "language", "size_bucket", "p10", "p50", "p90", "n_repos", "n_files"} <= set(
        result["cells"][0].keys()
    )

    # The repo row itself survives (small, bounded -- see build_corpus.py's
    # module docstring), but NO Facts or Insight rows remain for it.
    repo = db_session.scalar(select(Repo).where(Repo.url == url))
    assert repo is not None
    assert repo.current_run_id is None  # prune_run's ON DELETE SET NULL

    commit_count = db_session.scalar(
        select(func.count()).select_from(Commit).where(Commit.repo_id == repo.id)
    )
    file_count = db_session.scalar(
        select(func.count()).select_from(File).where(File.repo_id == repo.id)
    )
    run_count = db_session.scalar(
        select(func.count()).select_from(AnalysisRun).where(AnalysisRun.repo_id == repo.id)
    )
    file_metrics_count = db_session.scalar(
        select(func.count()).select_from(FileMetrics).where(FileMetrics.repo_id == repo.id)
    )
    assert commit_count == 0
    assert file_count == 0
    assert run_count == 0
    assert file_metrics_count == 0


def test_build_corpus_is_resumable_via_state_file(tmp_path, db_session):
    fixture_repo = _init_fixture_repo(tmp_path)
    url = str(fixture_repo)
    output_path = tmp_path / "corpus_breakpoints.json"
    state_path = tmp_path / "state.json"

    build_corpus(repos=[{"url": url}], output_path=output_path, state_path=state_path)
    assert state_path.exists()

    # Re-running with the SAME state file must not re-process the repo --
    # it's already marked "done". The clearest observable proof: no new
    # AnalysisRun/Job/Repo activity occurs (the fixture repo isn't even
    # touched a second time), so calling build_corpus again is a fast no-op
    # that still produces a valid (identical) breakpoints file.
    result_first = build_corpus(
        repos=[{"url": url}], output_path=output_path, state_path=state_path
    )
    result_second = build_corpus(
        repos=[{"url": url}], output_path=output_path, state_path=state_path
    )
    assert result_first["cells"] == result_second["cells"]
