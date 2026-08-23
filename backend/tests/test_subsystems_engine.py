import itertools
import uuid
from datetime import UTC, datetime

import networkx as nx
from sqlalchemy import insert, select

from app.db.models import (
    AnalysisRun,
    AnalysisRunStatus,
    Coupling,
    Dependency,
    File,
    Repo,
    RepoPath,
    RepoStatus,
    Subsystem,
    SubsystemMember,
)
from app.engines.context import RunContext
from app.engines.subsystems import (
    MIN_SUBSYSTEM_SIZE,
    SubsystemEngine,
    _Community,
    _identifier_label,
    _merge_small_communities,
    _path_prefix_label,
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


def _add_file(db_session, repo_id: uuid.UUID, path: str, *, current_loc: int = 10) -> None:
    path_id = _intern_paths(db_session, repo_id, [path])[path]
    now = datetime.now(UTC)
    db_session.add(
        File(
            repo_id=repo_id,
            path_id=path_id,
            path=path,
            language="python",
            current_loc=current_loc,
            complexity=1.0,
            churn_total=1,
            commit_count=1,
            first_seen=now,
            last_seen=now,
            is_deleted=False,
        )
    )
    db_session.flush()


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


def _add_coupling(
    db_session, repo_id: uuid.UUID, run_id: uuid.UUID, path_a: str, path_b: str, degree: float = 0.9
) -> None:
    path_ids = _intern_paths(db_session, repo_id, [path_a, path_b])
    db_session.execute(
        insert(Coupling),
        [
            {
                "analysis_run_id": run_id,
                "repo_id": repo_id,
                "path_a_id": path_ids[path_a],
                "path_b_id": path_ids[path_b],
                "shared_revs": 6,
                "coupling_degree": degree,
                "avg_revs": 6.0,
            }
        ],
    )


def _members_by_subsystem(db_session, run_id: uuid.UUID) -> dict[str, set[str]]:
    rows = db_session.execute(
        select(Subsystem.label, RepoPath.path)
        .select_from(Subsystem)
        .join(SubsystemMember, SubsystemMember.subsystem_id == Subsystem.id)
        .join(RepoPath, RepoPath.id == SubsystemMember.path_id)
        .where(Subsystem.analysis_run_id == run_id)
    ).all()
    grouped: dict[str, set[str]] = {}
    for label, path in rows:
        grouped.setdefault(label, set()).add(path)
    return grouped


def test_two_dense_clusters_joined_by_one_edge_produce_two_subsystems(db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/subsystems-two-clusters")
    cluster_a = [f"a/{i}.py" for i in range(4)]
    cluster_b = [f"b/{i}.py" for i in range(4)]
    for path in cluster_a + cluster_b:
        _add_file(db_session, repo_id, path)

    for x, y in itertools.combinations(cluster_a, 2):
        _add_dependency(db_session, repo_id, x, y)
    for x, y in itertools.combinations(cluster_b, 2):
        _add_dependency(db_session, repo_id, x, y)
    # One weak bridge edge -- everything else is a dense mesh, so Louvain
    # should still separate these into two communities.
    _add_dependency(db_session, repo_id, cluster_a[0], cluster_b[0])
    db_session.commit()

    run_id = _make_run(db_session, repo_id)
    metadata = SubsystemEngine().run(RunContext(repo_id=repo_id, run_id=run_id), db_session)
    db_session.commit()

    assert metadata["subsystems"] == 2

    grouped = _members_by_subsystem(db_session, run_id)
    assert len(grouped) == 2
    membership_sets = list(grouped.values())
    assert set(cluster_a) in membership_sets
    assert set(cluster_b) in membership_sets


def test_subsystem_partition_is_deterministic(db_session):
    """The determinism claim (master-context.md sec 2 / plan/RULES.md sec 4)
    made executable: the SAME facts + coupling produce the IDENTICAL
    partition, labels, and order across 10 independent runs."""
    repo_id = _make_repo(db_session, "https://github.com/fixture/subsystems-determinism")

    billing = [f"src/billing/mod{i}.py" for i in range(5)]
    shipping = [f"src/shipping/mod{i}.py" for i in range(5)]
    orphans = ["orphan_a.py", "orphan_b.py"]
    for path in billing + shipping + orphans:
        _add_file(db_session, repo_id, path)

    for x, y in itertools.combinations(billing, 2):
        _add_dependency(db_session, repo_id, x, y)
    db_session.commit()

    snapshots = []
    for _ in range(10):
        run_id = _make_run(db_session, repo_id)
        for x, y in itertools.combinations(shipping, 2):
            _add_coupling(db_session, repo_id, run_id, x, y, degree=0.8)
        db_session.commit()

        SubsystemEngine().run(RunContext(repo_id=repo_id, run_id=run_id), db_session)
        db_session.commit()

        rows = db_session.scalars(
            select(Subsystem).where(Subsystem.analysis_run_id == run_id).order_by(Subsystem.rank)
        ).all()
        snapshot = [(r.rank, r.label, r.label_source, r.file_count, r.cohesion) for r in rows]
        snapshots.append(tuple(snapshot))

    assert len(set(snapshots)) == 1, f"partition was not deterministic across runs: {snapshots}"


def test_two_file_community_merges_into_its_strongest_neighbour():
    """Session 04 Part B step 3, unit-tested directly against the merge
    helper (bypassing Louvain's own community-detection choices, which
    can't be forced deterministically from a hand-built fixture graph) --
    a size-2 community with a strong edge to one larger community and a weak
    edge to another must merge into the STRONGER one."""
    graph: nx.Graph = nx.Graph()
    for a, b in itertools.combinations([1, 2, 3, 4], 2):
        graph.add_edge(a, b, weight=1.0)
    for a, b in itertools.combinations([5, 6, 7, 8], 2):
        graph.add_edge(a, b, weight=1.0)
    graph.add_edge(9, 10, weight=5.0)
    graph.add_edge(9, 1, weight=0.5)  # weak link to cluster A
    graph.add_edge(10, 5, weight=2.0)  # strong link to cluster B
    graph.add_edge(10, 6, weight=2.0)  # (total to B = 4.0, to A = 0.5)

    path_map = {i: f"a/{i}.py" for i in (1, 2, 3, 4)}
    path_map.update({i: f"b/{i}.py" for i in (5, 6, 7, 8)})
    path_map.update({i: f"small/{i}.py" for i in (9, 10)})

    communities = [
        _Community(members={1, 2, 3, 4}),
        _Community(members={5, 6, 7, 8}),
        _Community(members={9, 10}),
    ]
    assert len(communities[2].members) < MIN_SUBSYSTEM_SIZE

    merged = _merge_small_communities(graph, communities, path_map)

    assert len(merged) == 2
    b_community = next(c for c in merged if {5, 6, 7, 8} <= c.members)
    assert {9, 10} <= b_community.members
    a_community = next(c for c in merged if c is not b_community)
    assert a_community.members == {1, 2, 3, 4}


def test_isolated_small_community_with_no_edges_becomes_unclustered():
    graph: nx.Graph = nx.Graph()
    for a, b in itertools.combinations([1, 2, 3, 4], 2):
        graph.add_edge(a, b, weight=1.0)
    graph.add_nodes_from([9, 10])  # no edges to anywhere at all

    path_map = {i: f"a/{i}.py" for i in (1, 2, 3, 4)}
    path_map.update({i: f"solo/{i}.py" for i in (9, 10)})

    communities = [_Community(members={1, 2, 3, 4}), _Community(members={9, 10})]
    merged = _merge_small_communities(graph, communities, path_map)

    unclustered = next(c for c in merged if c.forced_label == "Unclustered")
    assert unclustered.members == {9, 10}


def test_path_prefix_naming_wins_when_majority_share_prefix():
    path_map = {
        1: "src/services/billing/invoice.py",
        2: "src/services/billing/payment.py",
        3: "src/services/billing/refund.py",
        4: "src/other/unrelated.py",
    }
    label = _path_prefix_label({1, 2, 3, 4}, path_map)
    assert label == "billing"  # 3 of 4 members (75%) share this prefix


def test_identifier_naming_used_when_no_prefix_meets_coverage():
    path_map = {
        1: "backend/a/foo_bar.py",
        2: "frontend/b/foo_baz.py",
        3: "tools/c/qux_foo.py",
    }
    assert _path_prefix_label({1, 2, 3}, path_map) is None

    label = _identifier_label({1, 2, 3}, path_map, symbol_names_by_path_id={}, used_labels=set())
    assert label == "foo"  # most frequent non-stopword token across the three stems


def test_repo_with_no_edges_at_all_produces_singleton_unclustered_subsystem_and_does_not_crash(
    db_session,
):
    repo_id = _make_repo(db_session, "https://github.com/fixture/subsystems-no-edges")
    _add_file(db_session, repo_id, "lonely.py")
    db_session.commit()

    run_id = _make_run(db_session, repo_id)
    metadata = SubsystemEngine().run(RunContext(repo_id=repo_id, run_id=run_id), db_session)
    db_session.commit()

    assert metadata["subsystems"] == 1
    assert metadata["modularity"] == 0.0
    row = db_session.scalar(select(Subsystem).where(Subsystem.analysis_run_id == run_id))
    assert row.label == "Unclustered"
    assert row.file_count == 1
    assert row.cohesion == 0.0
