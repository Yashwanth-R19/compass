import uuid
from datetime import UTC, datetime

from sqlalchemy import insert, select

from app.db.models import (
    AnalysisRun,
    AnalysisRunStatus,
    Contributor,
    FileExpertise,
    Repo,
    RepoPath,
    RepoStatus,
    TruckFactor,
)
from app.engines.context import RunContext
from app.engines.truck_factor import TruckFactorEngine


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
    db_session.execute(insert(RepoPath), [{"repo_id": repo_id, "path": p} for p in paths])
    db_session.flush()
    return {
        row.path: row.id
        for row in db_session.execute(
            select(RepoPath.path, RepoPath.id).where(RepoPath.repo_id == repo_id)
        ).all()
    }


def _make_contributor(
    db_session, repo_id: uuid.UUID, run_id: uuid.UUID, name: str, rank: int, *, is_bot: bool = False
) -> int:
    now = datetime.now(UTC)
    result = db_session.execute(
        insert(Contributor)
        .values(
            analysis_run_id=run_id,
            repo_id=repo_id,
            canonical_name=name,
            canonical_email=f"{name.lower()}@corp.com",
            aliases=[{"name": name, "email": f"{name.lower()}@corp.com"}],
            commit_count=10,
            lines_added=100,
            lines_deleted=10,
            first_commit_at=now,
            last_commit_at=now,
            is_bot=is_bot,
            active_days=5,
            is_stale=False,
            rank=rank,
        )
        .returning(Contributor.id)
    )
    return result.scalar_one()


def _make_expert(
    db_session, run_id: uuid.UUID, path_id: int, contributor_id: int, *, is_expert: bool = True
) -> None:
    db_session.execute(
        insert(FileExpertise).values(
            analysis_run_id=run_id,
            path_id=path_id,
            contributor_id=contributor_id,
            doa=5.0,
            doa_normalized=1.0,
            is_expert=is_expert,
            changes=3,
            last_touched_at=datetime.now(UTC),
        )
    )


def _get_truck_factor(db_session, run_id: uuid.UUID) -> TruckFactor:
    row = db_session.scalar(select(TruckFactor).where(TruckFactor.analysis_run_id == run_id))
    assert row is not None
    return row


def test_one_dev_owns_80_percent_of_files_truck_factor_is_1(db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/tf-dominant")
    run_id = _make_run(db_session, repo_id)
    paths = _intern_paths(db_session, repo_id, [f"f{i}.py" for i in range(5)])

    alice = _make_contributor(db_session, repo_id, run_id, "Alice", rank=0)
    bob = _make_contributor(db_session, repo_id, run_id, "Bob", rank=1)

    for i in range(4):  # Alice is sole expert for 4 of 5 files (80%)
        _make_expert(db_session, run_id, paths[f"f{i}.py"], alice)
    _make_expert(db_session, run_id, paths["f4.py"], bob)
    db_session.commit()

    metadata = TruckFactorEngine().run(RunContext(repo_id=repo_id, run_id=run_id), db_session)
    db_session.commit()

    assert metadata["truck_factor"] == 1
    row = _get_truck_factor(db_session, run_id)
    assert row.value == 1
    assert len(row.removal_order) == 1
    assert row.removal_order[0]["contributor_id"] == alice
    assert row.removal_order[0]["files_orphaned"] == 4
    assert row.removal_order[0]["cumulative_orphan_ratio"] == 0.8


def test_four_devs_each_owning_a_quarter_truck_factor_is_3(db_session):
    """Session 05 Part G's required fixture: removing 3 of 4 crosses 50%
    (removing 2 lands exactly on 50%, which must NOT stop the loop -- the
    stop condition is strictly ">", not ">=")."""
    repo_id = _make_repo(db_session, "https://github.com/fixture/tf-quarters")
    run_id = _make_run(db_session, repo_id)
    paths = _intern_paths(db_session, repo_id, [f"f{i}.py" for i in range(8)])

    names = ["Alice", "Bob", "Carol", "Dave"]
    contributor_ids = [
        _make_contributor(db_session, repo_id, run_id, name, rank=i) for i, name in enumerate(names)
    ]
    for i, cid in enumerate(contributor_ids):
        # each owns exactly 2 of 8 files (a quarter), sole expert
        _make_expert(db_session, run_id, paths[f"f{2 * i}.py"], cid)
        _make_expert(db_session, run_id, paths[f"f{2 * i + 1}.py"], cid)
    db_session.commit()

    metadata = TruckFactorEngine().run(RunContext(repo_id=repo_id, run_id=run_id), db_session)
    db_session.commit()

    assert metadata["truck_factor"] == 3
    row = _get_truck_factor(db_session, run_id)
    assert len(row.removal_order) == 3
    # Cumulative ratios after each removal: 25%, 50%, 75% -- the 50% step
    # must NOT have stopped the loop.
    ratios = [step["cumulative_orphan_ratio"] for step in row.removal_order]
    assert ratios == [0.25, 0.5, 0.75]
    removed_names = {step["name"] for step in row.removal_order}
    assert removed_names <= set(names)


def test_exactly_one_contributor_truck_factor_is_1_with_note(db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/tf-single")
    run_id = _make_run(db_session, repo_id)
    paths = _intern_paths(db_session, repo_id, ["a.py", "b.py"])
    alice = _make_contributor(db_session, repo_id, run_id, "Alice", rank=0)
    _make_expert(db_session, run_id, paths["a.py"], alice)
    _make_expert(db_session, run_id, paths["b.py"], alice)
    db_session.commit()

    TruckFactorEngine().run(RunContext(repo_id=repo_id, run_id=run_id), db_session)
    db_session.commit()

    row = _get_truck_factor(db_session, run_id)
    assert row.value == 1
    assert row.note is not None
    assert len(row.removal_order) == 1
    assert row.removal_order[0]["cumulative_orphan_ratio"] == 1.0


def test_no_file_has_an_expert_truck_factor_is_0_with_note(db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/tf-diffuse")
    run_id = _make_run(db_session, repo_id)
    _make_contributor(db_session, repo_id, run_id, "Alice", rank=0)
    db_session.commit()

    metadata = TruckFactorEngine().run(RunContext(repo_id=repo_id, run_id=run_id), db_session)
    db_session.commit()

    assert metadata["truck_factor"] == 0
    row = _get_truck_factor(db_session, run_id)
    assert row.value == 0
    assert row.note is not None
    assert row.removal_order == []
    assert row.total_files_considered == 0


def test_bots_are_never_candidates_for_removal(db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/tf-bots")
    run_id = _make_run(db_session, repo_id)
    paths = _intern_paths(db_session, repo_id, ["a.py"])
    alice = _make_contributor(db_session, repo_id, run_id, "Alice", rank=0)
    bot = _make_contributor(db_session, repo_id, run_id, "some-bot", rank=1, is_bot=True)
    _make_expert(db_session, run_id, paths["a.py"], alice)
    # Even if a bot somehow had an is_expert row, it must never be treated
    # as a candidate contributor for removal.
    _make_expert(db_session, run_id, paths["a.py"], bot)
    db_session.commit()

    TruckFactorEngine().run(RunContext(repo_id=repo_id, run_id=run_id), db_session)
    db_session.commit()

    row = _get_truck_factor(db_session, run_id)
    removed_ids = {step["contributor_id"] for step in row.removal_order}
    assert bot not in removed_ids


def test_tie_broken_deterministically_by_rank_then_name(db_session):
    """Two contributors with identical coverage must be removed in a fixed
    order -- contributor rank asc, then name asc (session 05 Part D step
    2) -- not whatever order a dict/set iteration happens to produce."""
    repo_id = _make_repo(db_session, "https://github.com/fixture/tf-tiebreak")
    run_id = _make_run(db_session, repo_id)
    paths = _intern_paths(db_session, repo_id, ["a.py", "b.py"])
    # "Zed" has a lower rank (more active) than "Amy" despite alphabetical order.
    zed = _make_contributor(db_session, repo_id, run_id, "Zed", rank=0)
    amy = _make_contributor(db_session, repo_id, run_id, "Amy", rank=1)
    _make_expert(db_session, run_id, paths["a.py"], zed)
    _make_expert(db_session, run_id, paths["b.py"], amy)
    db_session.commit()

    TruckFactorEngine().run(RunContext(repo_id=repo_id, run_id=run_id), db_session)
    db_session.commit()

    row = _get_truck_factor(db_session, run_id)
    # Both own exactly one file (50% coverage each) -- tie broken by rank
    # asc, so Zed (rank 0) is removed first.
    assert row.removal_order[0]["contributor_id"] == zed


def test_determinism_across_repeated_runs(db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/tf-determinism")
    paths_master = _intern_paths(db_session, repo_id, [f"f{i}.py" for i in range(6)])
    db_session.commit()

    snapshots = []
    for _ in range(3):
        run_id = _make_run(db_session, repo_id)
        names = ["Alice", "Bob", "Carol"]
        ids = [
            _make_contributor(db_session, repo_id, run_id, n, rank=i) for i, n in enumerate(names)
        ]
        for i, cid in enumerate(ids):
            _make_expert(db_session, run_id, paths_master[f"f{2 * i}.py"], cid)
            _make_expert(db_session, run_id, paths_master[f"f{2 * i + 1}.py"], cid)
        db_session.commit()

        TruckFactorEngine().run(RunContext(repo_id=repo_id, run_id=run_id), db_session)
        db_session.commit()

        row = _get_truck_factor(db_session, run_id)
        snapshot = (row.value, tuple(step["name"] for step in row.removal_order))
        snapshots.append(snapshot)

    assert len(set(snapshots)) == 1, f"truck factor was not deterministic: {snapshots}"
