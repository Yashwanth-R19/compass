import math
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import insert, select

from app.db.models import (
    AnalysisRun,
    AnalysisRunStatus,
    Commit,
    Contributor,
    File,
    FileExpertise,
    Finding,
    Repo,
    RepoPath,
    RepoStatus,
)
from app.engines.context import RunContext
from app.engines.expertise import (
    EXPERT_DOA_ABSOLUTE_THRESHOLD,
    EXPERT_DOA_NORMALIZED_THRESHOLD,
    ExpertiseEngine,
)

# Independent reimplementation of the published formula (never imported from
# app/engines/expertise.py) -- this is what makes the exactness test below
# prove the formula is IMPLEMENTED, not merely internally self-consistent.
_DOA_BASE = 3.293
_DOA_FA = 1.098
_DOA_DL = 0.164
_DOA_AC = 0.321


def _expected_doa(fa: int, dl: int, ac: int) -> float:
    return _DOA_BASE + _DOA_FA * fa + _DOA_DL * dl - _DOA_AC * math.log(1 + ac)


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


def _add_file(db_session, repo_id: uuid.UUID, path: str) -> None:
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
        )
    )
    db_session.flush()


_BASE_TIME = datetime(2024, 1, 1, tzinfo=UTC)


def _add_commit(
    db_session,
    repo_id: uuid.UUID,
    sha: str,
    author_name: str,
    author_email: str,
    day_offset: int,
    file_paths: list[str],
) -> None:
    path_ids = _intern_paths(db_session, repo_id, file_paths)
    commit = Commit(
        repo_id=repo_id,
        sha=sha,
        author_name=author_name,
        author_email=author_email,
        committed_at=_BASE_TIME + timedelta(days=day_offset),
        message="synthetic",
        is_fix=False,
        is_revert=False,
        files_changed=len(file_paths),
        insertions=0,
        deletions=0,
        changed_path_ids=[path_ids[p] for p in file_paths],
        added_lines=[3 for _ in file_paths],
        deleted_lines=[1 for _ in file_paths],
    )
    db_session.add(commit)
    db_session.flush()


def test_doa_matches_hand_computed_formula_exactly(db_session):
    """Session 05 Part G: hand-compute DOA for 2 devs / 3 files with known
    commit counts, assert to 4 decimal places -- proves the published
    formula is implemented rather than approximated, and specifically
    catches the AC="all OTHER developers' changes" hazard (Known Hazard #2):
    getting AC wrong as "total changes" instead would invert f2's ranking.
    """
    repo_id = _make_repo(db_session, "https://github.com/fixture/doa-exactness")
    for p in ("f1.py", "f2.py", "f3.py"):
        _add_file(db_session, repo_id, p)

    # f1.py: only Alice ever touches it, twice. FA=1 (she created it), DL=2, AC=0.
    _add_commit(db_session, repo_id, "c1", "Alice", "alice@corp.com", 0, ["f1.py"])
    _add_commit(db_session, repo_id, "c2", "Alice", "alice@corp.com", 1, ["f1.py"])

    # f2.py: Bob creates it (c3), Alice touches it once (c4), Bob touches it
    # again (c5). Bob: FA=1, DL=2, AC=1. Alice: FA=0, DL=1, AC=2.
    _add_commit(db_session, repo_id, "c3", "Bob", "bob@corp.com", 2, ["f2.py"])
    _add_commit(db_session, repo_id, "c4", "Alice", "alice@corp.com", 3, ["f2.py"])
    _add_commit(db_session, repo_id, "c5", "Bob", "bob@corp.com", 4, ["f2.py"])

    # f3.py: only Alice, once. FA=1, DL=1, AC=0.
    _add_commit(db_session, repo_id, "c6", "Alice", "alice@corp.com", 5, ["f3.py"])
    db_session.commit()

    run_id = _make_run(db_session, repo_id)
    metadata = ExpertiseEngine().run(RunContext(repo_id=repo_id, run_id=run_id), db_session)
    db_session.commit()

    assert metadata["contributors"] == 2
    assert metadata["files_scored"] == 3

    path_ids = _intern_paths(db_session, repo_id, ["f1.py", "f2.py", "f3.py"])
    contributors_by_name = {
        c.canonical_name: c
        for c in db_session.scalars(
            select(Contributor).where(Contributor.analysis_run_id == run_id)
        ).all()
    }
    alice = contributors_by_name["Alice"]
    bob = contributors_by_name["Bob"]

    rows = {
        (fe.path_id, fe.contributor_id): fe
        for fe in db_session.scalars(
            select(FileExpertise).where(FileExpertise.analysis_run_id == run_id)
        ).all()
    }

    # f1.py: Alice FA=1, DL=2, AC=0
    expected_f1_alice = _expected_doa(fa=1, dl=2, ac=0)
    row_f1_alice = rows[(path_ids["f1.py"], alice.id)]
    assert row_f1_alice.doa == pytest.approx(expected_f1_alice, abs=1e-4)
    assert row_f1_alice.doa_normalized == pytest.approx(1.0, abs=1e-4)
    assert row_f1_alice.is_expert is True

    # f2.py: Bob FA=1, DL=2, AC=1 ; Alice FA=0, DL=1, AC=2
    expected_f2_bob = _expected_doa(fa=1, dl=2, ac=1)
    expected_f2_alice = _expected_doa(fa=0, dl=1, ac=2)
    row_f2_bob = rows[(path_ids["f2.py"], bob.id)]
    row_f2_alice = rows[(path_ids["f2.py"], alice.id)]
    assert row_f2_bob.doa == pytest.approx(expected_f2_bob, abs=1e-4)
    assert row_f2_alice.doa == pytest.approx(expected_f2_alice, abs=1e-4)

    expected_f2_max = max(expected_f2_bob, expected_f2_alice)
    assert row_f2_bob.doa_normalized == pytest.approx(expected_f2_bob / expected_f2_max, abs=1e-4)
    assert row_f2_alice.doa_normalized == pytest.approx(
        expected_f2_alice / expected_f2_max, abs=1e-4
    )
    # Bob clears both expert thresholds; Alice does not.
    assert row_f2_bob.doa >= EXPERT_DOA_ABSOLUTE_THRESHOLD
    assert row_f2_bob.doa_normalized >= EXPERT_DOA_NORMALIZED_THRESHOLD
    assert row_f2_bob.is_expert is True
    assert row_f2_alice.is_expert is False

    # f3.py: Alice FA=1, DL=1, AC=0
    expected_f3_alice = _expected_doa(fa=1, dl=1, ac=0)
    row_f3_alice = rows[(path_ids["f3.py"], alice.id)]
    assert row_f3_alice.doa == pytest.approx(expected_f3_alice, abs=1e-4)


def test_ac_is_other_developers_changes_not_total_changes(db_session):
    """Known Hazard #2, isolated: a file touched by many OTHER developers
    must have a LOWER doa for a fixed developer than the same developer's
    doa on a file nobody else ever touched -- the opposite would mean AC
    was wired up as "total changes" instead of "changes by others"."""
    repo_id = _make_repo(db_session, "https://github.com/fixture/doa-ac-hazard")
    _add_file(db_session, repo_id, "solo.py")
    _add_file(db_session, repo_id, "popular.py")

    _add_commit(db_session, repo_id, "s1", "Alice", "alice@corp.com", 0, ["solo.py"])

    _add_commit(db_session, repo_id, "p1", "Alice", "alice@corp.com", 1, ["popular.py"])
    for i, name in enumerate(["Bob", "Carol", "Dave"]):
        _add_commit(
            db_session,
            repo_id,
            f"p{i + 2}",
            name,
            f"{name.lower()}@corp.com",
            2 + i,
            ["popular.py"],
        )
    db_session.commit()

    run_id = _make_run(db_session, repo_id)
    ExpertiseEngine().run(RunContext(repo_id=repo_id, run_id=run_id), db_session)
    db_session.commit()

    path_ids = _intern_paths(db_session, repo_id, ["solo.py", "popular.py"])
    alice = db_session.scalar(
        select(Contributor).where(
            Contributor.analysis_run_id == run_id, Contributor.canonical_name == "Alice"
        )
    )
    solo_row = db_session.scalar(
        select(FileExpertise).where(
            FileExpertise.analysis_run_id == run_id,
            FileExpertise.path_id == path_ids["solo.py"],
            FileExpertise.contributor_id == alice.id,
        )
    )
    popular_row = db_session.scalar(
        select(FileExpertise).where(
            FileExpertise.analysis_run_id == run_id,
            FileExpertise.path_id == path_ids["popular.py"],
            FileExpertise.contributor_id == alice.id,
        )
    )
    # Same FA=1, DL=1 on both files; solo.py has AC=0, popular.py has AC=3.
    assert solo_row.doa > popular_row.doa


def test_bot_excluded_from_expertise_but_counted_in_commit_total(db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/doa-bots")
    _add_file(db_session, repo_id, "lockfile.json")
    _add_file(db_session, repo_id, "app.py")

    _add_commit(db_session, repo_id, "b1", "Alice", "alice@corp.com", 0, ["app.py"])
    _add_commit(
        db_session,
        repo_id,
        "b2",
        "dependabot[bot]",
        "49699333+dependabot[bot]@users.noreply.github.com",
        1,
        ["lockfile.json"],
    )
    _add_commit(
        db_session,
        repo_id,
        "b3",
        "dependabot[bot]",
        "49699333+dependabot[bot]@users.noreply.github.com",
        2,
        ["lockfile.json"],
    )
    db_session.commit()

    run_id = _make_run(db_session, repo_id)
    metadata = ExpertiseEngine().run(RunContext(repo_id=repo_id, run_id=run_id), db_session)
    db_session.commit()

    assert metadata["contributors"] == 2
    assert metadata["bots"] == 1
    assert metadata["bot_commit_ratio"] == pytest.approx(2 / 3)

    bot = db_session.scalar(
        select(Contributor).where(
            Contributor.analysis_run_id == run_id, Contributor.is_bot.is_(True)
        )
    )
    assert bot.commit_count == 2

    path_ids = _intern_paths(db_session, repo_id, ["lockfile.json"])
    experts_for_lockfile = db_session.scalars(
        select(FileExpertise).where(
            FileExpertise.analysis_run_id == run_id,
            FileExpertise.path_id == path_ids["lockfile.json"],
        )
    ).all()
    # The bot is the only author of lockfile.json -- excluded entirely means
    # no file_expertise row exists for it at all, not a row with is_expert=False.
    assert experts_for_lockfile == []


def test_staleness_measured_against_repo_last_commit_not_wall_clock(db_session):
    """The guard against datetime.now() creeping back in (Known Hazard #1):
    a repo whose last commit was 3 years ago, with all contributors active
    within a month of each other, has NOBODY stale."""
    repo_id = _make_repo(db_session, "https://github.com/fixture/doa-staleness")
    _add_file(db_session, repo_id, "old.py")

    three_years_ago = datetime.now(UTC) - timedelta(days=365 * 3)
    for i, (name, email) in enumerate([("Alice", "alice@corp.com"), ("Bob", "bob@corp.com")]):
        commit = Commit(
            repo_id=repo_id,
            sha=f"old{i}",
            author_name=name,
            author_email=email,
            committed_at=three_years_ago + timedelta(days=i * 10),
            message="ancient",
            is_fix=False,
            is_revert=False,
            files_changed=1,
            insertions=0,
            deletions=0,
            changed_path_ids=[_intern_paths(db_session, repo_id, ["old.py"])["old.py"]],
            added_lines=[1],
            deleted_lines=[0],
        )
        db_session.add(commit)
    db_session.commit()

    run_id = _make_run(db_session, repo_id)
    ExpertiseEngine().run(RunContext(repo_id=repo_id, run_id=run_id), db_session)
    db_session.commit()

    contributors = db_session.scalars(
        select(Contributor).where(Contributor.analysis_run_id == run_id)
    ).all()
    assert len(contributors) == 2
    assert all(not c.is_stale for c in contributors)


def test_determinism_across_repeated_runs(db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/doa-determinism")
    _add_file(db_session, repo_id, "a.py")
    _add_file(db_session, repo_id, "b.py")
    _add_commit(db_session, repo_id, "d1", "Alice", "alice@corp.com", 0, ["a.py"])
    _add_commit(db_session, repo_id, "d2", "Bob", "bob@corp.com", 1, ["a.py", "b.py"])
    _add_commit(db_session, repo_id, "d3", "Alice", "alice@corp.com", 2, ["b.py"])
    db_session.commit()

    snapshots = []
    for _ in range(3):
        run_id = _make_run(db_session, repo_id)
        ExpertiseEngine().run(RunContext(repo_id=repo_id, run_id=run_id), db_session)
        db_session.commit()

        contributors = db_session.scalars(
            select(Contributor)
            .where(Contributor.analysis_run_id == run_id)
            .order_by(Contributor.rank)
        ).all()
        snapshot = tuple((c.canonical_name, c.rank, c.commit_count, c.is_bot) for c in contributors)
        snapshots.append(snapshot)

    assert len(set(snapshots)) == 1, f"contributor ranking was not deterministic: {snapshots}"


def test_no_commits_returns_zero_without_crashing(db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/doa-empty")
    run_id = _make_run(db_session, repo_id)
    metadata = ExpertiseEngine().run(RunContext(repo_id=repo_id, run_id=run_id), db_session)
    db_session.commit()
    assert metadata["contributors"] == 0
    assert metadata["files_scored"] == 0


def test_findings_set_signature(db_session):
    """Any knowledge finding this engine emits must carry a signature
    (session 05 Part C convention, CLAUDE.md's finding-signature table)."""
    repo_id = _make_repo(db_session, "https://github.com/fixture/doa-signature")
    _add_file(db_session, repo_id, "solo.py")
    for i in range(6):
        _add_commit(db_session, repo_id, f"s{i}", "Alice", "alice@corp.com", i, ["solo.py"])
    db_session.commit()

    run_id = _make_run(db_session, repo_id)
    ExpertiseEngine().run(RunContext(repo_id=repo_id, run_id=run_id), db_session)
    db_session.commit()

    findings = db_session.scalars(
        select(Finding).where(Finding.analysis_run_id == run_id, Finding.category == "knowledge")
    ).all()
    for f in findings:
        assert f.signature is not None
