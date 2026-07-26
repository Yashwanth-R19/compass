import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import insert, select

from app.db.models import Commit, CommitFile, Dependency, Finding, Repo, RepoStatus
from app.engines.architecture import ArchEngine
from app.engines.coupling import CouplingEngine
from app.engines.overlay import OverlayEngine, compute_hidden_dependencies
from app.languages.scanner import extract_structural_edges


def _make_repo(db_session, url: str) -> uuid.UUID:
    repo = Repo(url=url, owner="fixture", name="repo", status=RepoStatus.pending)
    db_session.add(repo)
    db_session.commit()
    return repo.id


def _add_commit(
    db_session, repo_id: uuid.UUID, sha: str, file_paths: list[str], when: datetime
) -> None:
    commit = Commit(
        repo_id=repo_id,
        sha=sha,
        author_name="tester",
        author_email="tester@example.com",
        committed_at=when,
        message="synthetic",
        is_fix=False,
        is_revert=False,
        files_changed=len(file_paths),
        insertions=0,
        deletions=0,
    )
    db_session.add(commit)
    db_session.flush()
    db_session.execute(
        insert(CommitFile),
        [{"id": uuid.uuid4(), "commit_id": commit.id, "file_path": p} for p in file_paths],
    )


def _build_fixture_tree(root: Path) -> None:
    """A flat 5-file Python tree: a.py imports b.py (a real structural
    edge); x.py/y.py import each other (a planted 2-file cycle); c.py
    imports nothing and isn't imported by anyone.
    """
    (root / "a.py").write_text("import b\n")
    (root / "b.py").write_text("value = 1\n")
    (root / "c.py").write_text("value = 2\n")
    (root / "x.py").write_text("import y\n")
    (root / "y.py").write_text("import x\n")


def test_import_edge_found_cycle_detected_hidden_dependency_surfaced(tmp_path, db_session):
    _build_fixture_tree(tmp_path)

    # 1. Structural parsing (app/languages/scanner.py + PythonAnalyzer):
    # the real import edge must be found.
    edges = extract_structural_edges(str(tmp_path))
    edge_pairs = {(e.from_path, e.to_path) for e in edges}
    assert ("a.py", "b.py") in edge_pairs
    assert ("x.py", "y.py") in edge_pairs
    assert ("y.py", "x.py") in edge_pairs

    repo_id = _make_repo(db_session, "https://github.com/fixture/architecture-basic")
    db_session.execute(
        insert(Dependency),
        [
            {
                "id": uuid.uuid4(),
                "repo_id": repo_id,
                "from_path": e.from_path,
                "to_path": e.to_path,
                "dep_type": e.dep_type,
            }
            for e in edges
        ],
    )

    now = datetime.now(UTC)
    # a.py and c.py co-change repeatedly with NO import between them -> hidden dependency.
    for i in range(6):
        _add_commit(db_session, repo_id, f"ac{i}", ["a.py", "c.py"], now)
    # a.py and b.py also co-change -- but they DO have a real import edge,
    # so this pair must NOT be flagged as hidden.
    for i in range(6):
        _add_commit(db_session, repo_id, f"ab{i}", ["a.py", "b.py"], now)
    db_session.commit()

    CouplingEngine().run(repo_id, db_session)
    db_session.commit()

    # 2. ArchEngine: the planted x<->y cycle must be detected.
    arch_metadata = ArchEngine().run(repo_id, db_session)
    db_session.commit()

    assert arch_metadata["cycles_found"] == 1

    arch_findings = db_session.scalars(
        select(Finding).where(Finding.repo_id == repo_id, Finding.category == "architecture")
    ).all()
    cycle_finding = next(f for f in arch_findings if "Circular dependency" in f.title)
    cycle_files = set(cycle_finding.detail.split(": ", 1)[1].split(" -> "))
    assert cycle_files >= {"x.py", "y.py"}

    # 3. OverlayEngine: (a, c) is a hidden dependency; (a, b) is not,
    # because a real import edge already accounts for it.
    overlay_metadata = OverlayEngine().run(repo_id, db_session)
    db_session.commit()

    assert overlay_metadata["hidden_dependencies_found"] == 1

    hidden = compute_hidden_dependencies(repo_id, db_session)
    hidden_pairs = {frozenset((h["file_a_path"], h["file_b_path"])) for h in hidden}
    assert frozenset({"a.py", "c.py"}) in hidden_pairs
    assert frozenset({"a.py", "b.py"}) not in hidden_pairs

    hidden_findings = db_session.scalars(
        select(Finding).where(Finding.repo_id == repo_id, Finding.category == "hidden_dependency")
    ).all()
    assert len(hidden_findings) == 1
    assert {"a.py", "c.py"} <= set(hidden_findings[0].title.replace("<->", " ").split())


def test_layering_violation_flagged_for_ui_importing_db_directly(db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/architecture-layering")
    db_session.execute(
        insert(Dependency),
        [
            {
                "id": uuid.uuid4(),
                "repo_id": repo_id,
                "from_path": "ui/widget.py",
                "to_path": "db/models.py",
                "dep_type": "import",
            }
        ],
    )
    db_session.commit()

    metadata = ArchEngine().run(repo_id, db_session)
    db_session.commit()

    assert metadata["layering_violations_found"] == 1

    findings = db_session.scalars(
        select(Finding).where(Finding.repo_id == repo_id, Finding.category == "architecture")
    ).all()
    assert len(findings) == 1
    assert findings[0].file_path == "ui/widget.py"
    assert "UI imports DB" in findings[0].title
