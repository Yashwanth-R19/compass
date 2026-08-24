import uuid
from datetime import UTC, datetime

from sqlalchemy import insert, select

from app.analysis import blast_radius
from app.db.models import (
    AnalysisRun,
    AnalysisRunStatus,
    Coupling,
    Dependency,
    Repo,
    RepoPath,
    RepoStatus,
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


def _add_edge(db_session, repo_id: uuid.UUID, from_path: str, to_path: str) -> None:
    """from_path imports to_path (app/engines/architecture.py::load_edges'
    convention)."""
    path_ids = _intern_paths(db_session, repo_id, [from_path, to_path])
    db_session.execute(
        insert(Dependency),
        [
            {
                "repo_id": repo_id,
                "from_path_id": path_ids[from_path],
                "to_path_id": path_ids[to_path],
                "dep_type": "import",
                "import_kind": "static",
            }
        ],
    )


def _add_coupling(
    db_session, repo_id: uuid.UUID, run_id: uuid.UUID, path_a: str, path_b: str, degree: float
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
                "shared_revs": 8,
                "coupling_degree": degree,
                "avg_revs": 9.0,
            }
        ],
    )


def test_structural_blast_radius_chain_reports_correct_hop_distances(db_session):
    """a -> b -> c -> d (a imports b, b imports c, c imports d): the blast
    radius of d at depth 3 must include a/b/c with hop distances 3/2/1 --
    d's DIRECT importer (c) is hop 1, the file that imports THAT (b) is hop
    2, and so on."""
    repo_id = _make_repo(db_session, "https://github.com/fixture/blast-chain")
    _add_edge(db_session, repo_id, "a.py", "b.py")
    _add_edge(db_session, repo_id, "b.py", "c.py")
    _add_edge(db_session, repo_id, "c.py", "d.py")
    db_session.commit()

    run_id = _make_run(db_session, repo_id)
    db_session.commit()

    result = blast_radius.compute_blast_radius(db_session, run_id, repo_id, "d.py", max_depth=3)

    hop_by_path = {a.path: a.hop_distance for a in result.structural_affected}
    assert hop_by_path == {"c.py": 1, "b.py": 2, "a.py": 3}
    assert result.depth_capped is False
    assert result.node_cap_engaged is False


def test_depth_cap_reports_when_engaged(db_session):
    """A chain longer than max_depth must report depth_capped=True -- there
    really is more to explore beyond the requested depth."""
    repo_id = _make_repo(db_session, "https://github.com/fixture/blast-depth-cap")
    _add_edge(db_session, repo_id, "a.py", "b.py")
    _add_edge(db_session, repo_id, "b.py", "c.py")
    _add_edge(db_session, repo_id, "c.py", "d.py")
    _add_edge(db_session, repo_id, "d.py", "e.py")
    db_session.commit()

    run_id = _make_run(db_session, repo_id)
    db_session.commit()

    result = blast_radius.compute_blast_radius(db_session, run_id, repo_id, "e.py", max_depth=2)

    hop_by_path = {a.path: a.hop_distance for a in result.structural_affected}
    assert hop_by_path == {"d.py": 1, "c.py": 2}
    assert result.depth_capped is True


def test_node_cap_reports_when_engaged(db_session):
    """A star of many direct importers, capped at a small max_nodes, must
    report node_cap_engaged=True and stop short of the full set."""
    repo_id = _make_repo(db_session, "https://github.com/fixture/blast-node-cap")
    for i in range(10):
        _add_edge(db_session, repo_id, f"importer{i}.py", "target.py")
    db_session.commit()

    run_id = _make_run(db_session, repo_id)
    db_session.commit()

    result = blast_radius.compute_blast_radius(
        db_session, run_id, repo_id, "target.py", max_depth=3, max_nodes=3
    )

    assert result.node_cap_engaged is True
    assert len(result.structural_affected) <= 3


def test_coupled_but_not_imported_is_the_surprising_set(db_session):
    """x and y co-change at 0.8 with NO import edge between them anywhere --
    the money output: they must appear in historical_affected AND
    surprising_affected, and NOT in structural_affected."""
    repo_id = _make_repo(db_session, "https://github.com/fixture/blast-surprise")
    # A totally unrelated structural edge, so the dependency graph isn't
    # empty -- x/y themselves have no structural relationship at all.
    _add_edge(db_session, repo_id, "unrelated_a.py", "unrelated_b.py")
    db_session.commit()

    run_id = _make_run(db_session, repo_id)
    _add_coupling(db_session, repo_id, run_id, "x.py", "y.py", 0.8)
    db_session.commit()

    result = blast_radius.compute_blast_radius(db_session, run_id, repo_id, "x.py", max_depth=3)

    assert [a.path for a in result.structural_affected] == []
    assert [a.path for a in result.historical_affected] == ["y.py"]
    assert [a.path for a in result.surprising_affected] == ["y.py"]
    assert result.historical_affected[0].coupling_degree == 0.8


def test_dependency_graph_is_cached_across_calls_for_the_same_run(db_session, monkeypatch):
    """The per-run graph cache (Known Hazard #7) must avoid rebuilding the
    graph on a second call for the SAME run_id -- spy on load_edges."""
    repo_id = _make_repo(db_session, "https://github.com/fixture/blast-cache")
    _add_edge(db_session, repo_id, "a.py", "b.py")
    db_session.commit()

    run_id = _make_run(db_session, repo_id)
    db_session.commit()

    call_count = {"n": 0}
    real_load_edges = blast_radius.load_edges

    def _spy_load_edges(repo_id_arg, session_arg):
        call_count["n"] += 1
        return real_load_edges(repo_id_arg, session_arg)

    monkeypatch.setattr(blast_radius, "load_edges", _spy_load_edges)

    blast_radius.compute_blast_radius(db_session, run_id, repo_id, "b.py", max_depth=2)
    blast_radius.compute_blast_radius(db_session, run_id, repo_id, "b.py", max_depth=2)

    assert call_count["n"] == 1


def test_historical_evidence_reports_shared_commits(db_session):
    """Part A step 6: turns the historical claim into evidence -- commit
    count/percentage/example shas for the top coupled file."""
    from sqlalchemy import insert as sa_insert

    from app.db.models import Commit

    repo_id = _make_repo(db_session, "https://github.com/fixture/blast-evidence")
    run_id = _make_run(db_session, repo_id)
    path_ids = _intern_paths(db_session, repo_id, ["x.py", "y.py", "z.py"])
    _add_coupling(db_session, repo_id, run_id, "x.py", "y.py", 0.8)
    db_session.commit()

    def _commit(sha: str, paths: list[str]) -> None:
        db_session.execute(
            sa_insert(Commit),
            [
                {
                    "repo_id": repo_id,
                    "sha": sha,
                    "author_name": "tester",
                    "author_email": "tester@example.com",
                    "committed_at": datetime.now(UTC),
                    "message": "synthetic",
                    "is_fix": False,
                    "is_revert": False,
                    "files_changed": len(paths),
                    "insertions": 0,
                    "deletions": 0,
                    "changed_path_ids": [path_ids[p] for p in paths],
                    "added_lines": [0 for _ in paths],
                    "deleted_lines": [0 for _ in paths],
                }
            ],
        )

    _commit("c1", ["x.py", "y.py"])
    _commit("c2", ["x.py", "y.py"])
    _commit("c3", ["x.py", "z.py"])  # touches x.py but NOT y.py
    _commit("c4", ["z.py"])  # doesn't touch x.py at all
    db_session.commit()

    result = blast_radius.compute_blast_radius(db_session, run_id, repo_id, "x.py", max_depth=3)

    assert result.commits_touching_path == 3  # c1, c2, c3
    evidence = {e.affected_path: e for e in result.historical_evidence}
    assert evidence["y.py"].shared_commit_count == 2
    assert evidence["y.py"].shared_commit_percentage == 2 / 3
    assert set(evidence["y.py"].example_shas) == {"c1", "c2"}
