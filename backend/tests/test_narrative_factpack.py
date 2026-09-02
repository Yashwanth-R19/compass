"""Session 12, Part B/F: fact packs -- the structural enforcement that a
narrative can only ever see already-computed numbers/booleans/fixed labels.

Two tests here need no database at all (the import-boundary check and the
field-type allowlist check); the builder tests exercise real persisted rows
via ``db_session``, matching the pattern every other engine test in this
repo already uses.
"""

import ast
import inspect
import uuid
from datetime import UTC, datetime

import pytest
from pydantic import BaseModel
from sqlalchemy import insert

import app.narrative.factpack as factpack_module
from app.db.models import (
    AnalysisRun,
    AnalysisRunStatus,
    AnalysisStage,
    Contributor,
    Coupling,
    File,
    FileExpertise,
    FileMetrics,
    Repo,
    RepoPassport,
    RepoPath,
    RepoStatus,
    SecretHit,
    StageStatus,
    Vulnerability,
)
from app.narrative.factpack import (
    PassportFactPack,
    build_passport_factpack,
    build_risk_file_factpack,
    build_security_factpack,
    validate_factpack_allowlist,
)

# ---------------------------------------------------------------------------
# The import-boundary test -- structural, not a convention.
# ---------------------------------------------------------------------------


def test_factpack_module_never_imports_from_ingestion_or_security():
    """An AST-level check, not a substring search over the whole file --
    this module's own docstring legitimately NAMES ``app.ingestion``/
    ``app.security`` in prose (explaining why it has no import path to
    either), so a naive text search would false-positive on its own
    documentation. Only real ``import``/``from ... import`` statements
    count."""
    source = inspect.getsource(factpack_module)
    tree = ast.parse(source)
    imported_modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.append(node.module)

    forbidden = [
        m for m in imported_modules if m == "app.ingestion" or m.startswith("app.ingestion.")
    ] + [m for m in imported_modules if m == "app.security" or m.startswith("app.security.")]
    assert (
        not forbidden
    ), f"factpack.py must not import from app.ingestion/app.security: {forbidden}"


# ---------------------------------------------------------------------------
# The field-type allowlist.
# ---------------------------------------------------------------------------


def test_allowlist_accepts_every_real_factpack_shape():
    validate_factpack_allowlist(
        PassportFactPack(
            onboarding_difficulty=10.0,
            calibration="heuristic",
            file_count=1,
            loc=1,
            commit_count=1,
            contributor_count=1,
            subsystem_count=1,
            age_days=1.0,
            commits_last_30d=1,
            commits_last_90d=1,
            commits_last_365d=1,
            is_dormant=False,
            active_contributor_count=1,
            stale_contributor_count=0,
            bot_commit_ratio=0.0,
            truck_factor=1,
            modularity=0.5,
            entry_point_count=1,
            top_risk_file_count=1,
            churn_concentration=0.1,
            health_score=80.0,
            high_risk_ratio=0.1,
            cycle_count=0,
            hidden_dependency_count=0,
            primary_language="python",
        )
    )


def test_allowlist_rejects_a_free_text_field():
    class BadFactPack(BaseModel):
        commit_count: int
        note: str  # unbounded free text -- exactly what must never appear

    with pytest.raises(TypeError, match="not on the narrative fact-pack allowlist"):
        validate_factpack_allowlist(BadFactPack(commit_count=1, note="anything"))


def test_allowlist_rejects_a_bare_str_field_even_when_optional():
    class BadOptionalFactPack(BaseModel):
        commit_message: str | None = None

    with pytest.raises(TypeError):
        validate_factpack_allowlist(BadOptionalFactPack(commit_message="fix bug"))


def test_allowlist_rejects_a_list_field():
    class BadListFactPack(BaseModel):
        file_paths: list[str]

    with pytest.raises(TypeError):
        validate_factpack_allowlist(BadListFactPack(file_paths=["a.py"]))


def test_allowlist_accepts_a_literal_string_field():
    from typing import Literal

    class OkFactPack(BaseModel):
        language: Literal["python", "java"]

    validate_factpack_allowlist(OkFactPack(language="python"))


# ---------------------------------------------------------------------------
# Builders.
# ---------------------------------------------------------------------------


def _make_repo(db_session, url: str) -> uuid.UUID:
    repo = Repo(url=url, owner="fixture", name="repo", status=RepoStatus.ready)
    db_session.add(repo)
    db_session.commit()
    return repo.id


def _make_run(db_session, repo_id: uuid.UUID) -> uuid.UUID:
    run = AnalysisRun(repo_id=repo_id, status=AnalysisRunStatus.ready, head_sha="deadbeef")
    db_session.add(run)
    db_session.commit()
    return run.id


def _make_stage(db_session, run_id: uuid.UUID, name: str, status: StageStatus, summary=None):
    db_session.add(AnalysisStage(run_id=run_id, name=name, status=status, summary=summary))
    db_session.commit()


def test_build_passport_factpack_returns_none_when_no_row_exists(db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/passport-none")
    run_id = _make_run(db_session, repo_id)
    assert build_passport_factpack(db_session, run_id) is None


def test_build_passport_factpack_reads_only_numeric_fields_from_the_persisted_row(db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/passport-ok")
    run_id = _make_run(db_session, repo_id)

    data = {
        "identity": {
            "name": "repo",
            "owner": "fixture",
            "url": "https://github.com/fixture/passport-ok",
            "primary_language": "python",
            "language_breakdown": {"python": 10},
            "license_spdx": "MIT",
            "has_readme": True,
            "readme_lines": 5,
        },
        "scale": {
            "files": 10,
            "loc": 500,
            "commits": 20,
            "contributors": 2,
            "subsystems": 1,
            "age_days": 30.0,
            "first_commit_at": None,
            "last_commit_at": None,
        },
        "cadence": {
            "commits_last_30d": 5,
            "commits_last_90d": 10,
            "commits_last_365d": 20,
            "median_commits_per_active_week": 1.0,
            "active_days": 15,
            "longest_gap_days": 2.0,
            "is_dormant": False,
        },
        "team": {
            "active_contributors": 2,
            "stale_contributors": 0,
            "bot_commit_ratio": 0.0,
            "truck_factor": 1,
            "top_contributors": [{"name": "Real Person Name", "share": 1.0, "is_stale": False}],
        },
        "shape": {
            "subsystems": [{"label": "core", "file_count": 10, "cohesion": 0.9}],
            "entry_points": [{"path": "main.py", "kind": "cli"}],
            "modularity": 0.9,
        },
        "hotspots": {
            "top_risk_files": [{"path": "main.py", "risk_score": 0.5, "risk_confidence": 0.5}],
            "churn_concentration": 0.4,
        },
        "health": {
            "score": 80.0,
            "high_risk_ratio": 0.1,
            "cycle_count": 0,
            "hidden_dependency_count": 0,
            "calibration": "heuristic",
        },
        "first_pr": [],
    }
    db_session.add(
        RepoPassport(
            analysis_run_id=run_id,
            repo_id=repo_id,
            data=data,
            onboarding_difficulty=42.0,
            difficulty_breakdown={},
        )
    )
    db_session.commit()

    pack = build_passport_factpack(db_session, run_id)
    assert pack is not None
    assert pack.onboarding_difficulty == 42.0
    assert pack.file_count == 10
    assert pack.subsystem_count == 1
    assert pack.entry_point_count == 1  # a COUNT, never "main.py" itself
    assert pack.primary_language == "python"

    # Rule 1/allowlist, checked end to end: nothing on this model can hold
    # "Real Person Name", "main.py", or "MIT" -- the builder never even
    # tries to copy them across.
    for value in pack.model_dump().values():
        assert not isinstance(value, str) or value in ("heuristic", "python")


def test_build_passport_factpack_falls_back_to_other_for_unknown_language(db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/passport-unknown-lang")
    run_id = _make_run(db_session, repo_id)
    data = {
        "identity": {"primary_language": "rust"},
        "scale": {
            "files": 1,
            "loc": 1,
            "commits": 1,
            "contributors": 1,
            "subsystems": 1,
            "age_days": 1.0,
        },
        "cadence": {
            "commits_last_30d": 0,
            "commits_last_90d": 0,
            "commits_last_365d": 0,
            "is_dormant": True,
        },
        "team": {
            "active_contributors": 0,
            "stale_contributors": 0,
            "bot_commit_ratio": 0.0,
            "truck_factor": 0,
        },
        "shape": {"subsystems": [], "entry_points": [], "modularity": 0.0},
        "hotspots": {"top_risk_files": [], "churn_concentration": 0.0},
        "health": {
            "score": 0.0,
            "high_risk_ratio": 0.0,
            "cycle_count": 0,
            "hidden_dependency_count": 0,
        },
    }
    db_session.add(
        RepoPassport(
            analysis_run_id=run_id,
            repo_id=repo_id,
            data=data,
            onboarding_difficulty=0.0,
            difficulty_breakdown={},
        )
    )
    db_session.commit()

    pack = build_passport_factpack(db_session, run_id)
    assert pack.primary_language == "other"


def _intern_path(db_session, repo_id: uuid.UUID, path: str) -> int:
    db_session.execute(insert(RepoPath), [{"repo_id": repo_id, "path": path}])
    db_session.commit()
    from sqlalchemy import select

    return db_session.scalar(
        select(RepoPath.id).where(RepoPath.repo_id == repo_id, RepoPath.path == path)
    )


def test_build_risk_file_factpack_returns_none_for_unknown_path(db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/risk-none")
    run_id = _make_run(db_session, repo_id)
    assert build_risk_file_factpack(db_session, repo_id, run_id, "no/such/file.py") is None


def test_build_risk_file_factpack_reads_scores_and_never_the_path(db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/risk-ok")
    run_id = _make_run(db_session, repo_id)
    path_id = _intern_path(db_session, repo_id, "app/services/billing.py")

    now = datetime.now(UTC)
    db_session.add(
        File(
            repo_id=repo_id,
            path_id=path_id,
            path="app/services/billing.py",
            language="python",
            current_loc=200,
            complexity=25.0,
            churn_total=500,
            churn_weighted=300.0,
            commit_count=40,
            first_seen=now,
            last_seen=now,
            is_deleted=False,
            is_test=False,
        )
    )
    db_session.add(
        FileMetrics(
            analysis_run_id=run_id,
            repo_id=repo_id,
            path_id=path_id,
            risk_score=0.77,
            risk_confidence=0.8,
            hotspot_rank=0,
            instability_score=0.3,
            revert_cycle_count=1,
            test_classification="no_test",
            test_cochange_ratio=None,
        )
    )
    db_session.commit()

    pack = build_risk_file_factpack(db_session, repo_id, run_id, "app/services/billing.py")
    assert pack is not None
    assert pack.risk_score == 0.77
    assert pack.language == "python"
    assert pack.test_classification == "no_test"
    assert pack.expert_count == 0
    assert pack.is_orphaned_knowledge is False
    for value in pack.model_dump().values():
        assert value != "app/services/billing.py"


def test_build_risk_file_factpack_computes_max_coupling_and_orphaned_knowledge(db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/risk-coupled")
    run_id = _make_run(db_session, repo_id)
    path_a = _intern_path(db_session, repo_id, "a.py")
    path_b = _intern_path(db_session, repo_id, "b.py")

    now = datetime.now(UTC)
    for path_id, path in ((path_a, "a.py"), (path_b, "b.py")):
        db_session.add(
            File(
                repo_id=repo_id,
                path_id=path_id,
                path=path,
                language="python",
                current_loc=10,
                complexity=1.0,
                churn_total=1,
                churn_weighted=1.0,
                commit_count=1,
                first_seen=now,
                last_seen=now,
                is_deleted=False,
                is_test=False,
            )
        )
    db_session.add(
        FileMetrics(
            analysis_run_id=run_id,
            repo_id=repo_id,
            path_id=path_a,
            risk_score=0.5,
            risk_confidence=0.5,
            hotspot_rank=0,
        )
    )
    db_session.add(
        Coupling(
            analysis_run_id=run_id,
            repo_id=repo_id,
            path_a_id=path_a,
            path_b_id=path_b,
            shared_revs=5,
            coupling_degree=0.66,
            avg_revs=6.0,
        )
    )
    contributor = Contributor(
        analysis_run_id=run_id,
        repo_id=repo_id,
        canonical_name="Someone",
        canonical_email="s@example.com",
        aliases=[],
        commit_count=5,
        lines_added=1,
        lines_deleted=1,
        first_commit_at=now,
        last_commit_at=now,
        active_days=1,
        is_bot=False,
        is_stale=True,
        rank=0,
    )
    db_session.add(contributor)
    db_session.flush()
    db_session.add(
        FileExpertise(
            analysis_run_id=run_id,
            path_id=path_a,
            contributor_id=contributor.id,
            doa=4.0,
            doa_normalized=1.0,
            is_expert=True,
            changes=5,
            last_touched_at=now,
        )
    )
    db_session.commit()

    pack = build_risk_file_factpack(db_session, repo_id, run_id, "a.py")
    assert pack.max_coupling_degree == 0.66
    assert pack.expert_count == 1
    assert pack.is_orphaned_knowledge is True  # sole expert, and that expert is stale


def test_build_security_factpack_none_until_both_gating_stages_are_terminal(db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/sec-pending")
    run_id = _make_run(db_session, repo_id)
    assert build_security_factpack(db_session, repo_id, run_id) is None

    _make_stage(db_session, run_id, "secrets", StageStatus.done)
    assert (
        build_security_factpack(db_session, repo_id, run_id) is None
    )  # security stage still missing

    _make_stage(db_session, run_id, "security", StageStatus.done)
    assert build_security_factpack(db_session, repo_id, run_id) is not None


def test_build_security_factpack_counts_never_carry_a_preview_or_version(db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/sec-counts")
    run_id = _make_run(db_session, repo_id)
    _make_stage(db_session, run_id, "secrets", StageStatus.done, summary={"truncated": True})
    _make_stage(db_session, run_id, "security", StageStatus.done)
    _make_stage(
        db_session,
        run_id,
        "structure",
        StageStatus.done,
        summary={"dependency_manifest_found": True},
    )

    db_session.execute(
        insert(SecretHit),
        [
            {
                "repo_id": repo_id,
                "rule_id": "r",
                "description": "d",
                "path_id": None,
                "commit_sha": "a" * 40,
                "committed_at": datetime.now(UTC),
                "line_number": None,
                "fingerprint": "fp1",
                "redacted_preview": "SHOULD****NEVER**BE",
                "entropy": None,
                "still_in_head": True,
            },
            {
                "repo_id": repo_id,
                "rule_id": "r",
                "description": "d",
                "path_id": None,
                "commit_sha": "b" * 40,
                "committed_at": datetime.now(UTC),
                "line_number": None,
                "fingerprint": "fp2",
                "redacted_preview": None,
                "entropy": None,
                "still_in_head": False,
            },
        ],
    )
    db_session.execute(
        insert(Vulnerability),
        [
            {
                "analysis_run_id": run_id,
                "repo_id": repo_id,
                "ecosystem": "PyPI",
                "package_name": "sneaky-should-never-appear",
                "version": "9.9.9-should-never-appear",
                "osv_id": "GHSA-x",
                "aliases": [],
                "severity": "high",
                "cvss_score": 9.0,
                "summary": "s",
                "fixed_version": None,
                "published_at": None,
                "is_direct": True,
            }
        ],
    )
    db_session.commit()

    pack = build_security_factpack(db_session, repo_id, run_id)
    assert pack.secret_count_total == 2
    assert pack.secret_count_still_in_head == 1
    assert pack.secret_count_history_only == 1
    assert pack.vulnerability_count_total == 1
    assert pack.vulnerability_count_high == 1
    assert pack.vulnerability_count_direct == 1
    assert pack.secrets_truncated is True
    assert pack.no_supported_manifest is False

    for value in pack.model_dump().values():
        assert value != "SHOULD****NEVER**BE"
        assert value != "sneaky-should-never-appear"
        assert value != "9.9.9-should-never-appear"
