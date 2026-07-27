import subprocess
from pathlib import Path

from app.ingestion.miner import mine_repo


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _commit(cwd: Path, message: str, *, author_env: dict[str, str] | None = None) -> str:
    env = None
    if author_env:
        import os

        env = {**os.environ, **author_env}
    subprocess.run(
        ["git", "commit", "-m", message], cwd=cwd, check=True, capture_output=True, env=env
    )
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def _build_fixture_repo(root: Path) -> dict[str, str]:
    """Builds a real git repository exercising every case Part D asks for:
    known files/line counts, a binary file, a commit message with an
    embedded newline + pipe + emoji, a deleted file, and a merge commit
    (which must be excluded by --no-merges).

    Returns a dict of {label: sha} for the commits the test needs to
    reference individually.
    """
    repo_dir = root / "fixture-repo"
    repo_dir.mkdir()
    _git(repo_dir, "init", "-b", "main")
    _git(repo_dir, "config", "user.email", "test@example.com")
    _git(repo_dir, "config", "user.name", "Test User")

    shas: dict[str, str] = {}

    # C1: a.py, 3 lines added.
    (repo_dir / "a.py").write_text("one\ntwo\nthree\n")
    _git(repo_dir, "add", "a.py")
    shas["c1"] = _commit(repo_dir, "add a.py")

    # C2: a.py +1 line, b.py new (2 lines).
    (repo_dir / "a.py").write_text("one\ntwo\nthree\nfour\n")
    (repo_dir / "b.py").write_text("alpha\nbeta\n")
    _git(repo_dir, "add", "a.py", "b.py")
    shas["c2"] = _commit(repo_dir, "add b.py and extend a.py")

    # C3: delete b.py.
    _git(repo_dir, "rm", "b.py")
    shas["c3"] = _commit(repo_dir, "remove b.py")

    # C4: binary file.
    (repo_dir / "data.bin").write_bytes(b"\x00\x01\x02binary-not-text")
    _git(repo_dir, "add", "data.bin")
    shas["c4"] = _commit(repo_dir, "add binary blob")

    # C5: the tricky message -- newline, pipe, and a unicode emoji. This is
    # what proves the \x1e/\x1f record/unit separator choice was necessary:
    # a newline- or pipe-delimited log format would corrupt on this commit.
    (repo_dir / "a.py").write_text("one\ntwo\nthree\nfour\nfive\n")
    _git(repo_dir, "add", "a.py")
    nasty_subject = "Fix: contains | pipe and emoji \U0001f389"
    nasty_body = "Body line one\nBody line two with | pipe\nBody line three \U0001f389 more emoji"
    shas["c5"] = _commit(repo_dir, f"{nasty_subject}\n\n{nasty_body}")

    # Branch off C5 for a merge commit later.
    _git(repo_dir, "branch", "feature")
    _git(repo_dir, "checkout", "feature")
    (repo_dir / "feature.py").write_text("x\n")
    _git(repo_dir, "add", "feature.py")
    shas["c6"] = _commit(repo_dir, "add feature.py on feature branch")

    _git(repo_dir, "checkout", "main")
    (repo_dir / "main2.py").write_text("y\ny2\n")
    _git(repo_dir, "add", "main2.py")
    shas["c7"] = _commit(repo_dir, "add main2.py on main")

    # Merge feature into main -- both sides diverged, so this is a real
    # 2-parent merge commit, not a fast-forward. --no-merges must exclude it.
    _git(repo_dir, "merge", "feature", "--no-edit")
    shas["merge"] = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo_dir, check=True, capture_output=True, text=True
    ).stdout.strip()

    shas["_repo_dir"] = str(repo_dir)
    return shas


def test_miner_produces_exact_commits_paths_and_churn(tmp_path):
    shas = _build_fixture_repo(tmp_path)
    repo_dir = shas.pop("_repo_dir")

    mined = mine_repo(repo_dir)

    mined_shas = {c.sha for c in mined.commits}

    # --no-merges: the merge commit must not appear at all.
    assert shas["merge"] not in mined_shas
    assert len(mined.commits) == 7
    assert mined_shas == {shas[k] for k in ("c1", "c2", "c3", "c4", "c5", "c6", "c7")}

    files_by_path = {f.path: f for f in mined.files}
    assert set(files_by_path) == {"a.py", "b.py", "data.bin", "feature.py", "main2.py"}

    # a.py: 3 + 1 + 1 = 5 total churn across 3 commits (c1, c2, c5).
    assert files_by_path["a.py"].churn_total == 5
    assert files_by_path["a.py"].commit_count == 3
    assert files_by_path["a.py"].is_deleted is False

    # b.py: added 2 lines in c2, deleted 2 lines in c3 -> churn 4, 2 commits,
    # and it must be flagged deleted since it isn't in the final tree.
    assert files_by_path["b.py"].churn_total == 4
    assert files_by_path["b.py"].commit_count == 2
    assert files_by_path["b.py"].is_deleted is True

    # Binary file: counted as touched, but 0 added/0 deleted.
    assert files_by_path["data.bin"].churn_total == 0
    assert files_by_path["data.bin"].commit_count == 1
    assert files_by_path["data.bin"].is_deleted is False

    assert files_by_path["feature.py"].churn_total == 1
    assert files_by_path["feature.py"].commit_count == 1
    assert files_by_path["main2.py"].churn_total == 2
    assert files_by_path["main2.py"].commit_count == 1


def test_miner_survives_tricky_commit_message(tmp_path):
    """The nasty commit message (embedded newline + pipe + unicode emoji)
    must come through mining intact -- proving \\x1e/\\x1f were the right
    delimiter choice. A naive newline- or pipe-delimited parser would either
    split this commit's record in the wrong place or truncate the message.
    """
    shas = _build_fixture_repo(tmp_path)
    repo_dir = shas.pop("_repo_dir")

    mined = mine_repo(repo_dir)

    nasty_commit = next(c for c in mined.commits if c.sha == shas["c5"])

    assert "\U0001f389" in nasty_commit.message
    assert "|" in nasty_commit.message
    assert "\n" in nasty_commit.message
    assert nasty_commit.message.startswith("Fix: contains | pipe and emoji \U0001f389")
    assert "Body line two with | pipe" in nasty_commit.message

    # The commit's own file changes must still parse correctly despite the
    # message chaos -- it touched exactly a.py.
    assert nasty_commit.file_paths == ["a.py"]
    assert nasty_commit.file_added_lines == [1]
    assert nasty_commit.file_deleted_lines == [0]


def test_binary_file_touch_has_zero_added_and_deleted_lines(tmp_path):
    shas = _build_fixture_repo(tmp_path)
    repo_dir = shas.pop("_repo_dir")

    mined = mine_repo(repo_dir)

    binary_commit = next(c for c in mined.commits if c.sha == shas["c4"])
    assert binary_commit.file_paths == ["data.bin"]
    assert binary_commit.file_added_lines == [0]
    assert binary_commit.file_deleted_lines == [0]


def test_ignored_dirs_excluded_from_historical_paths(tmp_path):
    """IGNORE_DIRS filtering must apply to historical --numstat paths too,
    not just the final-tree walk used for is_deleted/complexity."""
    repo_dir = tmp_path / "ignore-fixture"
    repo_dir.mkdir()
    _git(repo_dir, "init", "-b", "main")
    _git(repo_dir, "config", "user.email", "test@example.com")
    _git(repo_dir, "config", "user.name", "Test User")

    (repo_dir / "node_modules").mkdir()
    (repo_dir / "node_modules" / "dep.js").write_text("noise\n")
    (repo_dir / "real.py").write_text("value = 1\n")
    _git(repo_dir, "add", "node_modules/dep.js", "real.py")
    _commit(repo_dir, "add real file and vendored noise")

    mined = mine_repo(str(repo_dir))

    paths = {f.path for f in mined.files}
    assert paths == {"real.py"}
    for commit in mined.commits:
        assert "node_modules/dep.js" not in commit.file_paths
