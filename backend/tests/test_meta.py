"""``GET /meta/{formulas,pipeline,worked-example}`` (UI rebuild session 2,
Part A). The whole point of these endpoints is that they read real values
off the engine modules and the persisted database rather than re-typing a
copy -- these tests spot-check that the response actually agrees with the
source it claims to read from, not just that the response has the right
shape.
"""

from datetime import UTC, datetime

from app.db.models import (
    AnalysisRun,
    AnalysisRunStatus,
    Commit,
    Health,
    Repo,
    RepoPassport,
    RepoPath,
    RepoStatus,
    Subsystem,
    TruckFactor,
)
from app.engines import glossary as glossary_engine_module
from app.engines import health as health_engine_module
from app.engines import risk as risk_engine_module
from app.engines.coupling import MIN_SHARED_REVS


def test_formulas_risk_weights_match_the_engine_source(client):
    resp = client.get("/meta/formulas")
    assert resp.status_code == 200
    body = resp.json()

    groups = {g["key"]: g for g in body["groups"]}
    risk = groups["risk"]
    assert risk["status"] == "locked"
    constants = {c["name"]: c["value"] for c in risk["constants"]}
    assert constants["churn_complexity_weight"] == risk_engine_module.RISK_CHURN_COMPLEXITY_WEIGHT
    assert constants["coupling_weight"] == risk_engine_module.RISK_COUPLING_WEIGHT
    assert constants["commit_count_weight"] == risk_engine_module.RISK_COMMIT_COUNT_WEIGHT
    # The three weights are the real, currently-in-use LOCKED formula values.
    assert (
        constants["churn_complexity_weight"],
        constants["coupling_weight"],
        constants["commit_count_weight"],
    ) == (0.60, 0.25, 0.15)


def test_formulas_coupling_thresholds_match_the_engine_source(client):
    resp = client.get("/meta/formulas")
    body = resp.json()
    groups = {g["key"]: g for g in body["groups"]}
    coupling = groups["coupling"]
    assert coupling["status"] == "locked"
    constants = {c["name"]: c["value"] for c in coupling["constants"]}
    assert constants["min_shared_revs"] == MIN_SHARED_REVS


def test_formulas_health_penalty_weights_match_the_engine_source(client):
    resp = client.get("/meta/formulas")
    body = resp.json()
    groups = {g["key"]: g for g in body["groups"]}
    health = groups["health"]
    assert health["status"] == "heuristic"
    constants = {c["name"]: c["value"] for c in health["constants"]}
    assert constants["risk_penalty_weight"] == health_engine_module.RISK_PENALTY_WEIGHT
    assert constants["cycle_penalty_per_cycle"] == health_engine_module.CYCLE_PENALTY_PER_CYCLE


def test_formulas_expertise_is_cited_with_a_citation_string(client):
    resp = client.get("/meta/formulas")
    body = resp.json()
    groups = {g["key"]: g for g in body["groups"]}
    expertise = groups["expertise"]
    assert expertise["status"] == "cited"
    assert expertise["citation"]
    assert "ICPC 2016" in expertise["citation"]


def test_formulas_glossary_constants_match_the_engine_source(client):
    # UI rebuild session 3: the glossary term-score formula (CLAUDE.md
    # "Domain glossary", section 5.1's table) had no /meta/formulas group at
    # all until this session -- added so TourPage's glossary panel can show
    # a real ScoreExplainer instead of degrading forever.
    resp = client.get("/meta/formulas")
    body = resp.json()
    groups = {g["key"]: g for g in body["groups"]}
    glossary = groups["glossary"]
    assert glossary["status"] == "heuristic"
    constants = {c["name"]: c["value"] for c in glossary["constants"]}
    assert constants["min_token_length"] == glossary_engine_module.MIN_TOKEN_LENGTH
    assert constants["max_glossary_terms"] == glossary_engine_module.MAX_GLOSSARY_TERMS
    assert (
        constants["max_defining_paths_per_term"]
        == glossary_engine_module.MAX_DEFINING_PATHS_PER_TERM
    )


def test_formulas_reports_the_active_baseline_provider(client):
    resp = client.get("/meta/formulas")
    body = resp.json()
    assert body["active_baseline_provider"]


def test_formulas_every_group_has_a_valid_status(client):
    resp = client.get("/meta/formulas")
    body = resp.json()
    for group in body["groups"]:
        assert group["status"] in ("locked", "heuristic", "cited")
        assert group["formula"]
        assert group["constants"]


def test_pipeline_returns_thirteen_stages_in_order(client):
    resp = client.get("/meta/pipeline")
    assert resp.status_code == 200
    stages = resp.json()["stages"]
    assert len(stages) == 13
    assert [s["order"] for s in stages] == list(range(1, 14))
    names = [s["name"] for s in stages]
    assert names == [
        "clone",
        "mine",
        "structure",
        "persist_facts",
        "secrets",
        "coupling",
        "subsystems",
        "architecture",
        "risk",
        "knowledge",
        "onboarding",
        "security",
        "rank",
    ]


def test_pipeline_marks_only_security_as_optional(client):
    resp = client.get("/meta/pipeline")
    stages = resp.json()["stages"]
    optional_names = {s["name"] for s in stages if s["optional"]}
    assert optional_names == {"security"}


def test_pipeline_every_stage_has_a_kind_and_a_description(client):
    resp = client.get("/meta/pipeline")
    stages = resp.json()["stages"]
    for s in stages:
        assert s["kind"] in ("fact", "insight")
        assert s["description"]


def test_pipeline_insight_stages_name_real_engine_classes(client):
    resp = client.get("/meta/pipeline")
    stages = {s["name"]: s for s in resp.json()["stages"]}
    assert "SubsystemEngine" in stages["subsystems"]["engines"]
    assert "ModuleCouplingEngine" in stages["subsystems"]["engines"]
    assert stages["subsystems"]["engines"].index("SubsystemEngine") < stages["subsystems"][
        "engines"
    ].index("ModuleCouplingEngine")
    # The "risk" stage's callables are wrapper functions (per-call
    # BaselineProvider injection, session 14) -- the pipeline response must
    # still name the real engines they wrap, not the private helper names.
    assert stages["risk"]["engines"] == ["RiskEngine", "HygieneEngine"]


def test_worked_example_is_null_when_no_showcase_repo_has_a_ready_run(client):
    resp = client.get("/meta/worked-example")
    assert resp.status_code == 200
    assert resp.json() is None


def test_worked_example_ignores_a_showcase_repo_with_no_current_run(client, db_session):
    repo = Repo(
        url="https://github.com/fixture/no-run-yet",
        owner="fixture",
        name="no-run-yet",
        status=RepoStatus.pending,
        is_showcase=True,
        showcase_rank=1,
    )
    db_session.add(repo)
    db_session.commit()

    resp = client.get("/meta/worked-example")
    assert resp.status_code == 200
    assert resp.json() is None


def test_worked_example_reads_real_persisted_figures_for_the_lowest_ranked_showcase_repo(
    client, db_session
):
    repo = Repo(
        url="https://github.com/fixture/worked-example",
        owner="fixture",
        name="worked-example",
        status=RepoStatus.ready,
        is_showcase=True,
        showcase_rank=1,
        head_sha="deadbeef",
    )
    db_session.add(repo)
    db_session.flush()

    run = AnalysisRun(repo_id=repo.id, status=AnalysisRunStatus.ready, head_sha="deadbeef")
    db_session.add(run)
    db_session.flush()

    repo.current_run_id = run.id
    db_session.add(repo)

    db_session.add(
        Commit(
            repo_id=repo.id,
            sha="a" * 40,
            author_name="Jane Doe",
            author_email="jane@example.com",
            committed_at=datetime.now(UTC),
            message="Initial commit",
        )
    )
    path = RepoPath(repo_id=repo.id, path="src/app.py")
    db_session.add(path)
    db_session.flush()

    db_session.add(
        Subsystem(
            analysis_run_id=run.id,
            repo_id=repo.id,
            label="billing",
            label_source="path_prefix",
            file_count=3,
            total_loc=100,
            internal_edges=2,
            external_edges=1,
            cohesion=0.67,
            rank=0,
        )
    )
    db_session.add(
        Health(
            analysis_run_id=run.id,
            repo_id=repo.id,
            score=82.5,
            high_risk_ratio=0.1,
            cycle_count=2,
            hidden_dependency_count=4,
        )
    )
    db_session.add(
        RepoPassport(
            analysis_run_id=run.id,
            repo_id=repo.id,
            data={},
            onboarding_difficulty=41.0,
            difficulty_breakdown={},
        )
    )
    db_session.add(
        TruckFactor(
            analysis_run_id=run.id,
            repo_id=repo.id,
            value=3,
            removal_order=[],
            total_files_considered=10,
            orphaned_file_count=0,
        )
    )
    db_session.commit()

    resp = client.get("/meta/worked-example")
    assert resp.status_code == 200
    body = resp.json()

    assert body["repo"]["id"] == str(repo.id)
    assert body["repo"]["owner"] == "fixture"
    assert body["run_id"] == str(run.id)
    assert body["commit_count"] == 1
    assert body["path_count"] == 1
    assert body["subsystem_count"] == 1
    assert body["subsystem_labels"] == ["billing"]
    assert body["cycle_count"] == 2
    assert body["hidden_dependency_count"] == 4
    assert body["health_score"] == 82.5
    assert body["onboarding_difficulty"] == 41.0
    assert body["truck_factor"] == 3
    # Real zeros, not nulls -- these tables genuinely have no rows for this
    # run, and a count query returns 0, not "unknown".
    assert body["symbol_count"] == 0
    assert body["entry_point_count"] == 0
    assert body["vulnerability_count"] == 0


def test_worked_example_prefers_the_lowest_showcase_rank(client, db_session):
    def _ready_showcase_repo(name: str, rank: int) -> Repo:
        repo = Repo(
            url=f"https://github.com/fixture/{name}",
            owner="fixture",
            name=name,
            status=RepoStatus.ready,
            is_showcase=True,
            showcase_rank=rank,
            head_sha="sha",
        )
        db_session.add(repo)
        db_session.flush()
        run = AnalysisRun(repo_id=repo.id, status=AnalysisRunStatus.ready, head_sha="sha")
        db_session.add(run)
        db_session.flush()
        repo.current_run_id = run.id
        db_session.add(repo)
        db_session.commit()
        return repo

    _ready_showcase_repo("second", 2)
    first = _ready_showcase_repo("first", 1)

    resp = client.get("/meta/worked-example")
    body = resp.json()
    assert body["repo"]["id"] == str(first.id)
