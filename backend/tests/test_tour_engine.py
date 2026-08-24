import uuid
from datetime import UTC, datetime

from sqlalchemy import insert, select

from app.db.models import (
    AnalysisRun,
    AnalysisRunStatus,
    Dependency,
    EntryPoint,
    File,
    FileMetrics,
    Repo,
    RepoManifest,
    RepoPath,
    RepoStatus,
    Subsystem,
    SubsystemMember,
)
from app.engines.context import RunContext
from app.engines.tour import MAX_TOUR_STOPS, TourEngine, compute_tour


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


def _add_file(db_session, repo_id: uuid.UUID, path: str) -> int:
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
    return path_id


def _add_subsystem(
    db_session,
    repo_id: uuid.UUID,
    run_id: uuid.UUID,
    label: str,
    rank: int,
    members: list[tuple[str, float]],
) -> int:
    """A single-purpose test helper: inserts one Subsystem row plus its
    SubsystemMember rows DIRECTLY (bypassing SubsystemEngine entirely,
    since TourEngine only ever reads these two tables) -- gives full,
    deterministic control over each file's centrality, which is what makes
    the ordering assertions below hand-verifiable."""
    result = db_session.execute(
        insert(Subsystem)
        .values(
            analysis_run_id=run_id,
            repo_id=repo_id,
            label=label,
            label_source="fallback",
            file_count=len(members),
            total_loc=10 * len(members),
            internal_edges=0,
            external_edges=0,
            cohesion=0.0,
            rank=rank,
        )
        .returning(Subsystem.id)
    )
    subsystem_id = result.scalar_one()
    path_ids = _intern_paths(db_session, repo_id, [p for p, _c in members])
    db_session.execute(
        insert(SubsystemMember),
        [
            {"subsystem_id": subsystem_id, "path_id": path_ids[p], "centrality": c}
            for p, c in members
        ],
    )
    return subsystem_id


def _add_subsystem_member(
    db_session, repo_id: uuid.UUID, subsystem_id: int, path: str, centrality: float
) -> None:
    """Adds an EXTRA member to an already-created subsystem, at a centrality
    lower than its existing anchor -- used to give a file a non-anchor
    subsystem membership without it becoming that subsystem's anchor."""
    path_id = _intern_paths(db_session, repo_id, [path])[path]
    db_session.execute(
        insert(SubsystemMember),
        [{"subsystem_id": subsystem_id, "path_id": path_id, "centrality": centrality}],
    )


def _add_entry_point(
    db_session,
    repo_id: uuid.UUID,
    run_id: uuid.UUID,
    path: str,
    kind: str,
    confidence: float,
    rank: int,
) -> None:
    path_id = _intern_paths(db_session, repo_id, [path])[path]
    db_session.execute(
        insert(EntryPoint),
        [
            {
                "analysis_run_id": run_id,
                "repo_id": repo_id,
                "path_id": path_id,
                "kind": kind,
                "evidence": "test fixture",
                "confidence": confidence,
                "rank": rank,
            }
        ],
    )


def _add_risk(
    db_session, repo_id: uuid.UUID, run_id: uuid.UUID, path: str, risk_score: float
) -> None:
    path_id = _intern_paths(db_session, repo_id, [path])[path]
    db_session.execute(
        insert(FileMetrics),
        [
            {
                "analysis_run_id": run_id,
                "repo_id": repo_id,
                "path_id": path_id,
                "risk_score": risk_score,
                "risk_confidence": 0.5,
                "hotspot_rank": 0,
            }
        ],
    )


def _add_dependency(db_session, repo_id: uuid.UUID, from_path: str, to_path: str) -> None:
    path_ids = _intern_paths(db_session, repo_id, [from_path, to_path])
    db_session.execute(
        insert(Dependency),
        [
            {
                "repo_id": repo_id,
                "from_path_id": path_ids[from_path],
                "to_path_id": path_ids[to_path],
                "dep_type": "import",
            }
        ],
    )


def _add_readme(db_session, repo_id: uuid.UUID, path: str, heading: str, line_count: int) -> None:
    path_id = _intern_paths(db_session, repo_id, [path])[path]
    db_session.execute(
        insert(RepoManifest),
        [
            {
                "repo_id": repo_id,
                "path_id": path_id,
                "kind": "readme",
                "data": {"heading": heading, "line_count": line_count},
            }
        ],
    )


def test_readme_is_always_position_1(db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/tour-readme-first")
    for p in ["README.md", "entry.py", "hot.py"]:
        _add_file(db_session, repo_id, p)
    _add_readme(db_session, repo_id, "README.md", "My Project", 50)
    run_id = _make_run(db_session, repo_id)
    _add_entry_point(db_session, repo_id, run_id, "entry.py", "web_server", 0.95, 0)
    _add_risk(db_session, repo_id, run_id, "hot.py", 0.8)
    db_session.commit()

    ctx = RunContext(repo_id=repo_id, run_id=run_id)
    rows, summary = compute_tour(repo_id, run_id, db_session, ctx)

    assert rows[0]["position"] == 1
    assert rows[0]["reason_code"] == "documentation"
    assert summary["stops"] == len(rows)


def test_no_readme_first_stop_is_an_entry_point(db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/tour-no-readme")
    for p in ["entry.py", "hot.py"]:
        _add_file(db_session, repo_id, p)
    run_id = _make_run(db_session, repo_id)
    _add_entry_point(db_session, repo_id, run_id, "entry.py", "cli", 0.95, 0)
    _add_risk(db_session, repo_id, run_id, "hot.py", 0.8)
    db_session.commit()

    ctx = RunContext(repo_id=repo_id, run_id=run_id)
    rows, _summary = compute_tour(repo_id, run_id, db_session, ctx)

    assert rows[0]["reason_code"] == "entry_point"


def test_reason_detail_is_never_empty(db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/tour-reason-detail")
    for p in ["entry.py", "hot.py", "wide.py"]:
        _add_file(db_session, repo_id, p)
    run_id = _make_run(db_session, repo_id)
    _add_entry_point(db_session, repo_id, run_id, "entry.py", "cli", 0.9, 0)
    _add_risk(db_session, repo_id, run_id, "hot.py", 0.8)
    db_session.commit()

    ctx = RunContext(repo_id=repo_id, run_id=run_id)
    rows, _summary = compute_tour(repo_id, run_id, db_session, ctx)

    assert rows  # sanity: the fixture actually produced stops
    for row in rows:
        assert row["reason_detail"]
        assert len(row["reason_detail"]) > 0


def test_tour_order_is_deterministic_across_ten_runs(db_session):
    """The determinism claim (master-context.md sec 2 / plan/RULES.md sec 4)
    made executable, including the path-asc tiebreak: two hotspot files
    share the EXACT SAME risk_score on purpose, so only the path-asc
    tiebreak can be deciding which of them sorts first."""
    repo_id = _make_repo(db_session, "https://github.com/fixture/tour-determinism")
    for p in ["entry.py", "lib_a.py", "lib_b.py", "hot_z.py", "hot_a.py", "wide.py", "widee.py"]:
        _add_file(db_session, repo_id, p)
    run_id = _make_run(db_session, repo_id)

    _add_subsystem(db_session, repo_id, run_id, "libs", 0, [("lib_a.py", 0.5), ("lib_b.py", 0.4)])
    _add_entry_point(db_session, repo_id, run_id, "entry.py", "web_server", 0.9, 0)
    _add_dependency(db_session, repo_id, "entry.py", "lib_a.py")
    _add_dependency(db_session, repo_id, "lib_a.py", "lib_b.py")
    # Tied risk_score -- only the path-asc tiebreak can separate these two.
    _add_risk(db_session, repo_id, run_id, "hot_z.py", 0.7)
    _add_risk(db_session, repo_id, run_id, "hot_a.py", 0.7)
    _add_dependency(db_session, repo_id, "wide.py", "widee.py")
    _add_dependency(db_session, repo_id, "lib_a.py", "widee.py")
    db_session.commit()

    snapshots = []
    for _ in range(10):
        ctx = RunContext(repo_id=repo_id, run_id=run_id)
        rows, summary = compute_tour(repo_id, run_id, db_session, ctx)
        snapshot = tuple((r["position"], r["path_id"], r["reason_code"]) for r in rows)
        snapshots.append((snapshot, summary["stops"]))

    assert len(set(snapshots)) == 1, f"tour order was not deterministic across runs: {snapshots}"

    # hot_a.py sorts before hot_z.py under the tied-risk_score tiebreak.
    ctx = RunContext(repo_id=repo_id, run_id=run_id)
    rows, _summary = compute_tour(repo_id, run_id, db_session, ctx)
    path_map = {
        row.id: row.path
        for row in db_session.execute(
            select(RepoPath.id, RepoPath.path).where(RepoPath.repo_id == repo_id)
        ).all()
    }
    hotspot_positions = {
        path_map[r["path_id"]]: r["position"] for r in rows if r["reason_code"] == "hotspot"
    }
    assert hotspot_positions["hot_a.py"] < hotspot_positions["hot_z.py"]


def test_every_subsystem_covered_when_subsystem_count_is_at_most_max_tour_stops(db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/tour-coverage-small")
    run_id = _make_run(db_session, repo_id)
    for k in range(8):
        path = f"sub{k}/anchor.py"
        _add_file(db_session, repo_id, path)
        _add_subsystem(db_session, repo_id, run_id, f"sub{k}", k, [(path, 0.9 - 0.01 * k)])
    db_session.commit()

    ctx = RunContext(repo_id=repo_id, run_id=run_id)
    rows, summary = compute_tour(repo_id, run_id, db_session, ctx)

    assert len(rows) <= MAX_TOUR_STOPS
    assert summary["subsystems_covered"] == summary["of"] == 8
    covered = {r["subsystem_id"] for r in rows}
    assert len(covered) == 8


def test_subsystem_coverage_cap_evicts_lowest_priority_hotspot(db_session):
    """Session 06 Known Hazard / Part B step 7: build a fixture where the
    NAIVE top-15 cap would drop sub13's anchor entirely, and assert the
    capping pass swaps it back in by evicting the LOWER-risk_score of the
    two hotspot stops (hotspot_B, risk_score 0.8) rather than the
    higher-risk one (hotspot_A, risk_score 0.9).

    No entry points and no dependency edges are used, so every candidate is
    "unreached" by BFS and the whole ordering collapses to a pure
    pagerank-desc sort (Known Hazard #5) -- which is exactly what makes this
    fixture hand-verifiable: centrality values are chosen so the naive
    pagerank-desc order is, by construction,
    sub0..sub10, hotspot_A, sub11, hotspot_B, sub12, sub13 (16 candidates,
    1 over the MAX_TOUR_STOPS=15 cap; sub13 falls into the overflow).

    The two hotspot files are each added as an EXTRA (non-anchor) member of
    an existing subsystem, at a centrality below that subsystem's real
    anchor -- giving them a real subsystem_id without letting the
    subsystem_anchor rule also claim them (which would outrank "hotspot" in
    REASON_PRIORITY and defeat the fixture's whole point).
    """
    repo_id = _make_repo(db_session, "https://github.com/fixture/tour-coverage-eviction")
    run_id = _make_run(db_session, repo_id)

    subsystem_ids: dict[str, int] = {}
    for k in range(14):
        path = f"sub{k}/anchor.py"
        _add_file(db_session, repo_id, path)
        centrality = 0.99 - 0.01 * k
        sid = _add_subsystem(db_session, repo_id, run_id, f"sub{k}", k, [(path, centrality)])
        subsystem_ids[f"sub{k}"] = sid

    _add_file(db_session, repo_id, "hotspot_a.py")
    _add_file(db_session, repo_id, "hotspot_b.py")
    _add_risk(db_session, repo_id, run_id, "hotspot_a.py", 0.9)
    _add_risk(db_session, repo_id, run_id, "hotspot_b.py", 0.8)
    # sub10's anchor is 0.89, sub11's is 0.88 -- both hotspot centralities
    # below their host subsystem's anchor, so neither becomes an anchor.
    _add_subsystem_member(db_session, repo_id, subsystem_ids["sub10"], "hotspot_a.py", 0.885)
    _add_subsystem_member(db_session, repo_id, subsystem_ids["sub11"], "hotspot_b.py", 0.875)
    db_session.commit()

    ctx = RunContext(repo_id=repo_id, run_id=run_id)
    rows, summary = compute_tour(repo_id, run_id, db_session, ctx)

    assert len(rows) == MAX_TOUR_STOPS
    path_map = {
        row.id: row.path
        for row in db_session.execute(
            select(RepoPath.id, RepoPath.path).where(RepoPath.repo_id == repo_id)
        ).all()
    }
    final_paths = {path_map[r["path_id"]] for r in rows}

    # sub13's anchor was pushed into the overflow by the naive cap, but the
    # coverage rule must have swapped it back in.
    assert "sub13/anchor.py" in final_paths
    # hotspot_b.py (the LOWER-risk of the two) is what got evicted to make room.
    assert "hotspot_b.py" not in final_paths
    # hotspot_a.py (the HIGHER-risk one) survives.
    assert "hotspot_a.py" in final_paths

    covered_subsystems = {r["subsystem_id"] for r in rows if r["subsystem_id"] is not None}
    # Every one of the 14 "subN" subsystems is represented -- including
    # sub13, which only made it in via the eviction swap.
    for k in range(14):
        assert subsystem_ids[f"sub{k}"] in covered_subsystems, f"sub{k} missing from final tour"
    assert summary["of"] == 14


def test_one_file_one_commit_repo_produces_a_valid_tour_with_no_crash(db_session):
    """Session 06 Known Hazard #2's 1-file/1-commit edge case, applied to
    the tour: a single file, no subsystems computed by an actual engine run
    (hand-inserted as a lone singleton, matching SubsystemEngine's own
    documented Unclustered-singleton behaviour), no entry points, no risk
    data at all."""
    repo_id = _make_repo(db_session, "https://github.com/fixture/tour-one-file")
    _add_file(db_session, repo_id, "only.py")
    run_id = _make_run(db_session, repo_id)
    _add_subsystem(db_session, repo_id, run_id, "Unclustered", 0, [("only.py", 0.0)])
    db_session.commit()

    ctx = RunContext(repo_id=repo_id, run_id=run_id)
    rows, summary = compute_tour(repo_id, run_id, db_session, ctx)

    assert len(rows) == 1
    assert rows[0]["reason_code"] == "subsystem_anchor"
    assert summary["stops"] == 1
    assert summary["subsystems_covered"] == 1
    assert summary["of"] == 1


def test_engine_persists_rows_matching_compute_tour(db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/tour-engine-persist")
    for p in ["entry.py", "hot.py"]:
        _add_file(db_session, repo_id, p)
    run_id = _make_run(db_session, repo_id)
    _add_entry_point(db_session, repo_id, run_id, "entry.py", "cli", 0.9, 0)
    _add_risk(db_session, repo_id, run_id, "hot.py", 0.8)
    db_session.commit()

    ctx = RunContext(repo_id=repo_id, run_id=run_id)
    metadata = TourEngine().run(ctx, db_session)
    db_session.commit()

    from app.db.models import TourStop

    persisted = db_session.scalars(
        select(TourStop).where(TourStop.analysis_run_id == run_id).order_by(TourStop.position)
    ).all()
    assert len(persisted) == metadata["stops"]
    assert [p.position for p in persisted] == list(range(1, len(persisted) + 1))
