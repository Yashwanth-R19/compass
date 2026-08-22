import uuid

from sqlalchemy import insert, select

from app.db.models import AnalysisRun, AnalysisRunStatus, Dependency, Repo, RepoPath, RepoStatus
from app.engines.context import RunContext


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


def test_cycles_memoises_and_calls_find_cycles_once(db_session, monkeypatch):
    """Session 01 Part A: calling ctx.cycles(session) twice must only invoke
    find_cycles once -- the whole point of RunContext is that ArchEngine and
    HealthEngine, sharing one ctx, don't each recompute the cycle list from
    scratch."""
    import app.engines.context as context_module

    repo_id = _make_repo(db_session, "https://github.com/fixture/context-memoize")
    _add_dependency(db_session, repo_id, "x.py", "y.py")
    _add_dependency(db_session, repo_id, "y.py", "x.py")
    db_session.commit()

    run_id = _make_run(db_session, repo_id)
    ctx = RunContext(repo_id=repo_id, run_id=run_id)

    calls = {"count": 0}
    original = context_module.find_cycles

    def spy(*args, **kwargs):
        calls["count"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(context_module, "find_cycles", spy)

    first = ctx.cycles(db_session)
    second = ctx.cycles(db_session)

    assert calls["count"] == 1
    assert first == second


def test_dependency_edges_memoises(db_session, monkeypatch):
    import app.engines.context as context_module

    repo_id = _make_repo(db_session, "https://github.com/fixture/context-memoize-edges")
    _add_dependency(db_session, repo_id, "a.py", "b.py")
    db_session.commit()

    run_id = _make_run(db_session, repo_id)
    ctx = RunContext(repo_id=repo_id, run_id=run_id)

    calls = {"count": 0}
    original = context_module.load_edges

    def spy(*args, **kwargs):
        calls["count"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(context_module, "load_edges", spy)

    ctx.dependency_edges(db_session)
    ctx.dependency_edges(db_session)
    ctx.dependency_graph(db_session)  # also depends on dependency_edges

    assert calls["count"] == 1


def test_a_fresh_context_per_run_does_not_share_cache(db_session):
    """RunContext is scoped to exactly one run -- two separate instances for
    two different runs of the same repo must not see each other's cache."""
    repo_id = _make_repo(db_session, "https://github.com/fixture/context-not-shared")
    _add_dependency(db_session, repo_id, "a.py", "b.py")
    db_session.commit()

    run_a = _make_run(db_session, repo_id)
    run_b = _make_run(db_session, repo_id)

    ctx_a = RunContext(repo_id=repo_id, run_id=run_a)
    ctx_b = RunContext(repo_id=repo_id, run_id=run_b)

    ctx_a.dependency_edges(db_session)

    assert ctx_b._dependency_edges is None
