import itertools
from datetime import UTC, datetime, timedelta

from app.analysis.snapshots import HISTORY_SNAPSHOTS, select_snapshot_points


def _commits(n: int, *, start_index_offset: int = 0) -> list[tuple[str, datetime]]:
    base = datetime(2020, 1, 1, tzinfo=UTC)
    return [(f"sha{i + start_index_offset}", base + timedelta(days=i)) for i in range(n)]


def test_empty_commit_list_returns_no_snapshots():
    assert select_snapshot_points([], 24) == []


def test_fewer_commits_than_n_uses_one_snapshot_per_commit():
    commits = _commits(5)
    points = select_snapshot_points(commits, 24)
    assert len(points) == 5
    assert [p.commit_index for p in points] == [0, 1, 2, 3, 4]
    assert [p.sha for p in points] == ["sha0", "sha1", "sha2", "sha3", "sha4"]


def test_always_includes_first_and_last_commit():
    commits = _commits(1000)
    points = select_snapshot_points(commits, 24)
    assert points[0].commit_index == 0
    assert points[0].sha == "sha0"
    assert points[-1].commit_index == 999
    assert points[-1].sha == "sha999"


def test_spaced_evenly_by_commit_index_not_date():
    # A dormant stretch in the middle (a 1000-day gap between commit 10 and
    # commit 11) must not pull snapshot density toward it -- spacing is by
    # commit INDEX, so the gap should barely register in where points land.
    base = datetime(2020, 1, 1, tzinfo=UTC)
    commits = [(f"sha{i}", base + timedelta(days=i)) for i in range(11)]
    commits += [(f"sha{i}", base + timedelta(days=1000 + i)) for i in range(11, 100)]

    points = select_snapshot_points(commits, 24)
    indices = [p.commit_index for p in points]
    # Evenly spaced by index means consecutive gaps are all close to
    # (100 - 1) / (24 - 1) =~ 4.3 -- no huge jump concentrated at the dormant
    # boundary the way date-spacing would produce.
    gaps = [b - a for a, b in itertools.pairwise(indices)]
    assert max(gaps) <= 6


def test_deterministic_for_a_given_commit_list():
    commits = _commits(500)
    first = select_snapshot_points(commits, 24)
    second = select_snapshot_points(list(reversed(commits)), 24)
    assert first == second


def test_default_n_is_history_snapshots_constant():
    commits = _commits(500)
    assert len(select_snapshot_points(commits)) <= HISTORY_SNAPSHOTS
    assert len(select_snapshot_points(commits)) == HISTORY_SNAPSHOTS


def test_single_commit():
    commits = _commits(1)
    points = select_snapshot_points(commits, 24)
    assert len(points) == 1
    assert points[0].commit_index == 0
