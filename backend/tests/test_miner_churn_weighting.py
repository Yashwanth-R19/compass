"""Session 07 (Risk v2, Part D.1): app/ingestion/miner.py::mine_repo computes
churn_recent_365d/churn_weighted directly from real git history -- these
tests exercise the actual production code path (unlike
test_risk_engine.py::test_recency_weighted_churn_outranks_identical_stale_churn,
which hand-sets churn_weighted on a File fixture to test RiskEngine's
CONSUMPTION of the value, not the miner's computation of it).
"""

import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.ingestion.miner import mine_repo


def _git(cwd: Path, *args: str, env: dict[str, str] | None = None) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, env=env)


def _commit_at(cwd: Path, when: datetime, message: str) -> None:
    iso = when.isoformat()
    _git(
        cwd,
        "commit",
        "-m",
        message,
        env={
            "GIT_AUTHOR_DATE": iso,
            "GIT_COMMITTER_DATE": iso,
            # subprocess env replaces the whole environment unless merged --
            # git needs a real PATH/HOME to run at all on this platform.
            **_base_env(),
        },
    )


def _base_env() -> dict[str, str]:
    return dict(os.environ)


def test_recency_weighted_churn_favors_recently_touched_files(tmp_path):
    """Two files with IDENTICAL raw churn (same lines added), touched at
    very different ages relative to the repo's own last commit -- the
    recently-touched file must end up with materially higher
    churn_weighted, and the anciently-touched one's churn must fall mostly
    outside churn_recent_365d's 365-day window."""
    repo_dir = tmp_path / "churn-weighting-repo"
    repo_dir.mkdir()
    _git(repo_dir, "init", "-b", "main")
    _git(repo_dir, "config", "user.email", "test@example.com")
    _git(repo_dir, "config", "user.name", "Test User")

    now = datetime(2026, 1, 1, tzinfo=UTC)
    old_commit_at = now - timedelta(days=1000)
    recent_commit_at = now - timedelta(days=10)
    last_commit_at = now  # this is the repo's own "last commit" reference

    (repo_dir / "stale.py").write_text("x = 1\n" * 50)
    _git(repo_dir, "add", "stale.py")
    _commit_at(repo_dir, old_commit_at, "touch stale.py, 1000 days before the repo's last commit")

    (repo_dir / "recent.py").write_text("y = 1\n" * 50)
    _git(repo_dir, "add", "recent.py")
    _commit_at(repo_dir, recent_commit_at, "touch recent.py, 10 days before the repo's last commit")

    (repo_dir / "anchor.py").write_text("z = 1\n")
    _git(repo_dir, "add", "anchor.py")
    _commit_at(repo_dir, last_commit_at, "the repo's actual most recent commit")

    mined = mine_repo(str(repo_dir))
    files_by_path = {f.path: f for f in mined.files}

    stale = files_by_path["stale.py"]
    recent = files_by_path["recent.py"]

    # Identical raw churn_total (both files were a single 50-line add).
    assert stale.churn_total == recent.churn_total == 50

    # But churn_weighted must differ sharply -- decayed to near-zero for the
    # 800-day-old touch, close to full weight for the 10-day-old one.
    assert recent.churn_weighted > stale.churn_weighted
    assert recent.churn_weighted > 0.9 * recent.churn_total
    assert stale.churn_weighted < 0.2 * stale.churn_total

    # churn_recent_365d: the 10-day-old touch is well inside the 365-day
    # window (full raw churn counted); the 800-day-old one is entirely
    # outside it (zero).
    assert recent.churn_recent_365d == 50
    assert stale.churn_recent_365d == 0
