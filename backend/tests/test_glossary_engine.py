import math
import uuid
from datetime import UTC, datetime

from sqlalchemy import insert, select

from app.db.models import (
    AnalysisRun,
    AnalysisRunStatus,
    File,
    GlossaryTerm,
    Repo,
    RepoPath,
    RepoStatus,
    Subsystem,
    SubsystemMember,
)
from app.db.models import Symbol as SymbolRow
from app.engines.context import RunContext
from app.engines.glossary import GlossaryEngine, compute_glossary


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


def _add_symbol(
    db_session, repo_id: uuid.UUID, path: str, *, name: str, kind: str, exported: bool
) -> None:
    path_id = _intern_paths(db_session, repo_id, [path])[path]
    db_session.execute(
        insert(SymbolRow),
        [
            {
                "repo_id": repo_id,
                "path_id": path_id,
                "name": name,
                "kind": kind,
                "line": 1,
                "exported": exported,
            }
        ],
    )


def _add_subsystem_with_file(
    db_session, repo_id: uuid.UUID, run_id: uuid.UUID, label: str, rank: int, path: str
) -> None:
    result = db_session.execute(
        insert(Subsystem)
        .values(
            analysis_run_id=run_id,
            repo_id=repo_id,
            label=label,
            label_source="fallback",
            file_count=1,
            total_loc=10,
            internal_edges=0,
            external_edges=0,
            cohesion=0.0,
            rank=rank,
        )
        .returning(Subsystem.id)
    )
    subsystem_id = result.scalar_one()
    path_id = _intern_paths(db_session, repo_id, [path])[path]
    db_session.execute(
        insert(SubsystemMember),
        [{"subsystem_id": subsystem_id, "path_id": path_id, "centrality": 0.5}],
    )


def test_settlement_domain_term_ranks_above_get_and_below_no_stopword_leak(db_session):
    """Session 06 Part F: SettlementProcessor / settlement_batch /
    getSettlementStatus -> "settlement" highly ranked (rank 0, highest
    score); "get" (a required generic-programming stopword) is completely
    absent. "processor"/"batch"/"status" each occur only once (vs.
    settlement's three) so they score strictly lower under the locked
    scoring formula -- they are not "highly ranked" the way settlement is,
    even though they still surface in the ranked list (this fixture has no
    subsystems at all, so nothing is filtered beyond the stopword list)."""
    repo_id = _make_repo(db_session, "https://github.com/fixture/glossary-settlement")
    for p in ["a.py", "b.py", "c.py"]:
        _add_file(db_session, repo_id, p)
    _add_symbol(
        db_session, repo_id, "a.py", name="SettlementProcessor", kind="class", exported=True
    )
    _add_symbol(
        db_session, repo_id, "b.py", name="settlement_batch", kind="function", exported=False
    )
    _add_symbol(
        db_session, repo_id, "c.py", name="getSettlementStatus", kind="function", exported=False
    )
    db_session.commit()

    run_id = _make_run(db_session, repo_id)
    rows, summary = compute_glossary(repo_id, run_id, db_session)
    by_term = {r["term"]: r for r in rows}

    assert "get" not in by_term
    assert "settlement" in by_term
    assert by_term["settlement"]["rank"] == 0
    assert by_term["settlement"]["occurrences"] == 3
    for weaker in ("processor", "batch", "status"):
        if weaker in by_term:
            assert by_term[weaker]["score"] < by_term["settlement"]["score"]
            assert by_term[weaker]["rank"] > 0
    assert summary["terms"] == len(rows)


def test_framework_and_language_keyword_noise_is_filtered(db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/glossary-noise")
    _add_file(db_session, repo_id, "x.py")
    _add_file(db_session, repo_id, "y.py")
    _add_symbol(
        db_session, repo_id, "x.py", name="ReactComponentWrapper", kind="class", exported=True
    )
    _add_symbol(db_session, repo_id, "y.py", name="InvoiceLedger", kind="class", exported=True)
    db_session.commit()

    run_id = _make_run(db_session, repo_id)
    rows, _summary = compute_glossary(repo_id, run_id, db_session)
    terms = {r["term"] for r in rows}

    # "react"/"component"/"wrapper" are all framework-noise or
    # generic-programming stopwords and must not survive, while an
    # ordinary domain term from the SAME symbol-extraction pass does --
    # proving the filter is selective, not just accidentally emptying
    # everything.
    assert terms.isdisjoint({"react", "component", "wrapper"})
    assert {"invoice", "ledger"} <= terms


def test_subsystem_spread_increases_score_over_single_subsystem_jargon(db_session):
    """Hand-computed against the locked-in-this-session HEURISTIC formula:
    score = log(1 + occurrences) * (1 + subsystem_spread / total_subsystems).
    "shared" occurs twice, once in each of two subsystems (spread=2);
    "solo" occurs twice, both times in the SAME subsystem (spread=1). Equal
    occurrence counts isolate the spread term as the only variable."""
    repo_id = _make_repo(db_session, "https://github.com/fixture/glossary-spread")
    _add_file(db_session, repo_id, "fa.py")
    _add_file(db_session, repo_id, "fb.py")
    _add_symbol(db_session, repo_id, "fa.py", name="SharedThing", kind="class", exported=True)
    _add_symbol(db_session, repo_id, "fb.py", name="useShared", kind="function", exported=False)
    _add_symbol(db_session, repo_id, "fa.py", name="SoloItem", kind="class", exported=True)
    _add_symbol(db_session, repo_id, "fa.py", name="SoloWorker", kind="class", exported=True)
    db_session.commit()

    run_id = _make_run(db_session, repo_id)
    _add_subsystem_with_file(db_session, repo_id, run_id, "subA", 0, "fa.py")
    _add_subsystem_with_file(db_session, repo_id, run_id, "subB", 1, "fb.py")
    db_session.commit()

    rows, _summary = compute_glossary(repo_id, run_id, db_session)
    by_term = {r["term"]: r for r in rows}

    assert by_term["shared"]["occurrences"] == 2
    assert by_term["shared"]["subsystem_spread"] == 2
    assert by_term["solo"]["occurrences"] == 2
    assert by_term["solo"]["subsystem_spread"] == 1

    expected_shared = math.log(3) * (1 + 2 / 2)
    expected_solo = math.log(3) * (1 + 1 / 2)
    assert by_term["shared"]["score"] == expected_shared
    assert by_term["solo"]["score"] == expected_solo
    assert by_term["shared"]["score"] > by_term["solo"]["score"]


def test_defining_path_ids_prefer_exported_class_interface_type_symbols(db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/glossary-defining-paths")
    _add_file(db_session, repo_id, "helper.py")
    _add_file(db_session, repo_id, "impl.py")
    _add_file(db_session, repo_id, "iface.py")
    _add_symbol(
        db_session, repo_id, "helper.py", name="widget_helper_fn", kind="function", exported=False
    )
    _add_symbol(db_session, repo_id, "impl.py", name="WidgetImpl", kind="class", exported=False)
    _add_symbol(
        db_session, repo_id, "iface.py", name="WidgetInterface", kind="interface", exported=True
    )
    db_session.commit()

    run_id = _make_run(db_session, repo_id)
    path_ids = _intern_paths(db_session, repo_id, ["helper.py", "impl.py", "iface.py"])
    rows, _summary = compute_glossary(repo_id, run_id, db_session)
    by_term = {r["term"]: r for r in rows}

    widget_paths = by_term["widget"]["defining_path_ids"]
    assert widget_paths[0] == path_ids["iface.py"]  # exported + preferred kind wins
    assert set(widget_paths) == {path_ids["helper.py"], path_ids["impl.py"], path_ids["iface.py"]}


def test_glossary_ranking_is_deterministic_including_the_tiebreak(db_session):
    """Four terms with IDENTICAL score (no shared tokens, no subsystems) --
    only the term-ascending tiebreak can be deciding their rank order."""
    repo_id = _make_repo(db_session, "https://github.com/fixture/glossary-determinism")
    # Stems kept short (<MIN_TOKEN_LENGTH) so they don't themselves
    # contribute extra tied terms via the file-stem tokenization pass.
    _add_file(db_session, repo_id, "f1.py")
    _add_file(db_session, repo_id, "f2.py")
    _add_symbol(db_session, repo_id, "f1.py", name="AlphaThing", kind="class", exported=True)
    _add_symbol(db_session, repo_id, "f2.py", name="BetaZebra", kind="class", exported=True)
    db_session.commit()

    run_id = _make_run(db_session, repo_id)

    snapshots = []
    for _ in range(5):
        rows, _summary = compute_glossary(repo_id, run_id, db_session)
        snapshots.append(tuple((r["term"], r["rank"]) for r in rows))

    assert len(set(snapshots)) == 1, f"glossary ranking was not deterministic: {snapshots}"
    ranked_terms = [term for term, _rank in snapshots[0]]
    assert ranked_terms == sorted(ranked_terms)  # all tied scores -> pure alphabetical order
    assert ranked_terms == ["alpha", "beta", "thing", "zebra"]


def test_zero_files_produces_an_empty_glossary_with_no_crash(db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/glossary-empty")
    run_id = _make_run(db_session, repo_id)
    rows, summary = compute_glossary(repo_id, run_id, db_session)
    assert rows == []
    assert summary == {"terms": 0}


def test_engine_persists_rows_matching_compute_glossary(db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/glossary-engine-persist")
    _add_file(db_session, repo_id, "a.py")
    _add_symbol(db_session, repo_id, "a.py", name="BillingAccount", kind="class", exported=True)
    db_session.commit()

    run_id = _make_run(db_session, repo_id)
    ctx = RunContext(repo_id=repo_id, run_id=run_id)
    metadata = GlossaryEngine().run(ctx, db_session)
    db_session.commit()

    persisted = db_session.scalars(
        select(GlossaryTerm)
        .where(GlossaryTerm.analysis_run_id == run_id)
        .order_by(GlossaryTerm.rank)
    ).all()
    assert len(persisted) == metadata["terms"]
    assert {p.term for p in persisted} == {"billing", "account"}
