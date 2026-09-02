import itertools
import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta

from sqlalchemy import insert, select

from app.analysis.identities import resolve_identities
from app.analysis.snapshots import select_snapshot_points
from app.db.models import (
    AnalysisRun,
    AnalysisRunStatus,
    Commit,
    File,
    Repo,
    RepoPath,
    RepoStatus,
    Snapshot,
)
from app.db.paths import load_path_map
from app.engines.context import RunContext
from app.engines.coupling import MAX_CHANGESET_SIZE, MIN_COUPLING_DEGREE, MIN_SHARED_REVS
from app.engines.timeline import (
    ACTIVE_CONTRIBUTOR_WINDOW_DAYS,
    TimelineEngine,
    _canonical_names,
    _churn_ranked_hotspots,
    _contributor_shares,
    _file_count_alive_at,
    _load_commits,
    _load_file_lifetimes,
    _top_coupling_pairs,
    compute_timeline,
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


def _add_commit(
    db_session,
    repo_id: uuid.UUID,
    sha: str,
    file_paths: list[str],
    *,
    author_name: str = "tester",
    author_email: str = "tester@example.com",
    committed_at: datetime | None = None,
    added: list[int] | None = None,
    deleted: list[int] | None = None,
) -> None:
    path_ids = _intern_paths(db_session, repo_id, file_paths)
    added = added if added is not None else [5 for _ in file_paths]
    deleted = deleted if deleted is not None else [1 for _ in file_paths]
    db_session.execute(
        insert(Commit),
        [
            {
                "repo_id": repo_id,
                "sha": sha,
                "author_name": author_name,
                "author_email": author_email,
                "committed_at": committed_at or datetime.now(UTC),
                "message": "synthetic change",
                "is_fix": False,
                "is_revert": False,
                "files_changed": len(file_paths),
                "insertions": sum(added),
                "deletions": sum(deleted),
                "changed_path_ids": [path_ids[p] for p in file_paths],
                "added_lines": added,
                "deleted_lines": deleted,
            }
        ],
    )


def _add_file(
    db_session,
    repo_id: uuid.UUID,
    path: str,
    *,
    first_seen: datetime,
    last_seen: datetime,
    is_deleted: bool,
) -> int:
    path_id = _intern_paths(db_session, repo_id, [path])[path]
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
            first_seen=first_seen,
            last_seen=last_seen,
            is_deleted=is_deleted,
        )
    )
    db_session.flush()
    return path_id


# --- Part A/B: compute_timeline over a synthetic history -------------------


def _seed_synthetic_repo(db_session, repo_id: uuid.UUID, n_commits: int = 40) -> None:
    base = datetime(2022, 1, 1, tzinfo=UTC)
    authors = [("alice", "alice@example.com"), ("bob", "bob@example.com")]
    files = [f"src/module_{i}.py" for i in range(6)]
    for i in range(n_commits):
        author = authors[i % len(authors)]
        # Rotate through overlapping file pairs so real coupling accumulates
        # (module_0 + module_1 change together often; the rest churn alone).
        touched = [files[0], files[1]] if i % 3 == 0 else [files[(i + 2) % len(files)]]
        _add_commit(
            db_session,
            repo_id,
            f"sha{i}",
            touched,
            author_name=author[0],
            author_email=author[1],
            committed_at=base + timedelta(days=i * 5),
            added=[10 + i for _ in touched],
            deleted=[1 for _ in touched],
        )
    db_session.commit()


def test_file_count_alive_at_uses_first_and_last_seen():
    t0 = datetime(2020, 1, 1, tzinfo=UTC)
    t1 = datetime(2020, 6, 1, tzinfo=UTC)
    t2 = datetime(2020, 12, 1, tzinfo=UTC)
    rows = [
        (t0, t2, False),  # created early, survives to HEAD
        (t1, t1, True),  # created and deleted at the same point (short-lived)
        (t2, t2, False),  # created late, still alive
    ]
    assert _file_count_alive_at(rows, datetime(2019, 1, 1, tzinfo=UTC)) == 0
    assert _file_count_alive_at(rows, t0) == 1  # only the first file exists yet
    assert _file_count_alive_at(rows, t1) == 1  # the short-lived file is created AND gone at t1
    assert _file_count_alive_at(rows, t1 + timedelta(days=1)) == 1  # still gone afterward
    assert _file_count_alive_at(rows, t2) == 2  # first file + the newly-created third file


def test_zero_commits_returns_empty_with_zeroed_summary(db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/timeline-empty")
    run_id = _make_run(db_session, repo_id)
    rows, summary = compute_timeline(repo_id, run_id, db_session)
    assert rows == []
    assert summary == {"snapshots": 0, "span_days": 0}


def test_snapshot_coupling_matches_locked_formula_over_truncated_commits(db_session):
    """A small, hand-computable repo: two files (a.py, b.py) always change
    together for the first 6 commits, then a.py alone for 4 more. At the
    FINAL snapshot, shared_revs(a,b) must be exactly 6 and
    coupling_degree = 6 / min(revs(a), revs(b)) -- the locked formula,
    verbatim, over the full (untruncated) commit set."""
    repo_id = _make_repo(db_session, "https://github.com/fixture/timeline-coupling")
    base = datetime(2021, 1, 1, tzinfo=UTC)
    for i in range(6):
        _add_commit(
            db_session, repo_id, f"pair{i}", ["a.py", "b.py"], committed_at=base + timedelta(days=i)
        )
    for i in range(4):
        _add_commit(
            db_session, repo_id, f"solo{i}", ["a.py"], committed_at=base + timedelta(days=6 + i)
        )
    db_session.commit()
    run_id = _make_run(db_session, repo_id)

    rows, _summary = compute_timeline(repo_id, run_id, db_session)
    assert rows, "expected at least one snapshot"
    final = rows[-1]["metrics"]

    assert final["commits_to_date"] == 10
    top_pairs = final["top_coupling_pairs"]
    assert len(top_pairs) == 1
    pair = top_pairs[0]
    assert {pair["path_a"], pair["path_b"]} == {"a.py", "b.py"}
    assert pair["shared_revs"] == 6
    # revs(a) = 10 (6 paired + 4 solo), revs(b) = 6 -> min = 6
    assert pair["coupling_degree"] == 6 / 6
    assert final["coupling_pairs_count"] == 1


def test_engine_persists_snapshot_rows(db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/timeline-engine")
    _seed_synthetic_repo(db_session, repo_id, n_commits=30)
    run_id = _make_run(db_session, repo_id)

    summary = TimelineEngine().run(RunContext(repo_id=repo_id, run_id=run_id), db_session)
    db_session.commit()

    persisted = db_session.scalars(
        select(Snapshot).where(Snapshot.analysis_run_id == run_id).order_by(Snapshot.position)
    ).all()
    assert len(persisted) == summary["snapshots"]
    assert len(persisted) > 0
    # positions are contiguous starting at 0, matching the pure core's output
    assert [p.position for p in persisted] == list(range(len(persisted)))
    assert persisted[-1].commit_index == 29  # last of 30 commits, 0-indexed
    assert "file_count" in persisted[0].metrics
    assert "churn_ranked_hotspots" in persisted[0].metrics


# --- Part H: single-pass correctness against a naive, independently-built --
# --- 24-independent-passes oracle -------------------------------------------


def _naive_oracle_snapshots(repo_id: uuid.UUID, session) -> list[dict]:
    """Deliberately NOT the production accumulator: for each snapshot point,
    truncates the commit list and recomputes every counter FROM SCRATCH --
    the "obvious", unoptimized implementation Known Hazard #2 warns is a
    minute of wall time at scale. Reuses timeline.py's small, already-correct
    DERIVATION helpers (_top_coupling_pairs/_churn_ranked_hotspots/
    _file_count_alive_at/_contributor_shares -- pure functions of an already-
    built counter, not part of what's being verified) but builds every
    counter itself, independently of compute_timeline's incremental
    accumulation loop -- exactly the "build the oracle inside the test"
    approach plan/SESSION_13's Part H calls for."""
    commits = _load_commits(repo_id, session)
    if not commits:
        return []

    identity_map = resolve_identities([(c.author_name, c.author_email) for c in commits])
    name_by_identity = _canonical_names(commits, identity_map)
    points = select_snapshot_points([(c.sha, c.committed_at) for c in commits])
    path_map = load_path_map(repo_id, session)
    file_lifetimes = _load_file_lifetimes(repo_id, session)

    results = []
    for point in points:
        truncated = commits[: point.commit_index + 1]

        churn_by_path: Counter[int] = Counter()
        shared_revs: Counter[tuple[int, int]] = Counter()
        file_revs: Counter[int] = Counter()
        churn_to_date = 0
        for c in truncated:
            churn_to_date += sum(c.added_lines) + sum(c.deleted_lines)
            for pid, added, deleted in zip(
                c.changed_path_ids, c.added_lines, c.deleted_lines, strict=True
            ):
                churn_by_path[pid] += added + deleted
            unique_ids = sorted(set(c.changed_path_ids))
            if unique_ids and len(unique_ids) <= MAX_CHANGESET_SIZE:
                file_revs.update(unique_ids)
                shared_revs.update(itertools.combinations(unique_ids, 2))

        cutoff = point.date - timedelta(days=ACTIVE_CONTRIBUTOR_WINDOW_DAYS)
        window = [
            (c.committed_at, identity_map[(c.author_name, c.author_email)])
            for c in truncated
            if c.committed_at >= cutoff
        ]
        pairs_count, top_pairs = _top_coupling_pairs(shared_revs, file_revs, path_map, 10)

        results.append(
            {
                "commits_to_date": len(truncated),
                "churn_to_date": churn_to_date,
                "file_count": _file_count_alive_at(file_lifetimes, point.date),
                "active_contributors": len({iid for _, iid in window}),
                "contributor_shares": _contributor_shares(window, name_by_identity, 8),
                "coupling_pairs_count": pairs_count,
                "top_coupling_pairs": top_pairs,
                "churn_ranked_hotspots": _churn_ranked_hotspots(churn_by_path, path_map, 20),
            }
        )
    return results


def test_single_pass_accumulator_matches_naive_oracle(db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/timeline-oracle")
    _seed_synthetic_repo(db_session, repo_id, n_commits=45)
    run_id = _make_run(db_session, repo_id)

    optimized_rows, _summary = compute_timeline(repo_id, run_id, db_session)
    oracle = _naive_oracle_snapshots(repo_id, db_session)

    assert len(optimized_rows) == len(oracle)
    for optimized_row, expected in zip(optimized_rows, oracle, strict=True):
        assert optimized_row["metrics"] == expected


def test_min_coupling_thresholds_reused_not_redeclared():
    """CLAUDE.md/plan/RULES.md sec 1.4: the snapshot coupling pass must use
    the SAME thresholds as app/engines/coupling.py, imported, not a locally
    redeclared copy that could silently drift."""
    from app.engines import timeline as timeline_module

    assert timeline_module.MIN_SHARED_REVS is MIN_SHARED_REVS
    assert timeline_module.MIN_COUPLING_DEGREE is MIN_COUPLING_DEGREE
