"""Fact packs -- the structural enforcement that a narrative can only ever
see already-computed numbers/booleans/fixed labels.

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
    Repo,
    RepoPassport,
    RepoStatus,
    SecretHit,
    StageStatus,
    Vulnerability,
)
from app.narrative.factpack import (
    RepoFactPack,
    build_repo_factpack,
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


def _make_repo_factpack(**overrides) -> RepoFactPack:
    defaults = dict(
        calibration="heuristic",
        file_count=10,
        loc=500,
        commit_count=20,
        contributor_count=2,
        subsystem_count=1,
        truck_factor=1,
        health_score=80.0,
        high_risk_ratio=0.1,
        cycle_count=0,
        hidden_dependency_count=0,
        onboarding_difficulty=42.0,
        finding_count_high=0,
        finding_count_med=1,
        finding_count_low=2,
        secret_count_still_in_head=0,
        secret_count_history_only=0,
        vulnerability_count_high=0,
        vulnerability_count_med=0,
        vulnerability_count_low=0,
        vulnerability_count_unknown=0,
    )
    defaults.update(overrides)
    return RepoFactPack(**defaults)


def test_allowlist_accepts_a_real_factpack_shape():
    validate_factpack_allowlist(_make_repo_factpack())


def test_allowlist_accepts_the_corpus_calibration_label_too():
    validate_factpack_allowlist(_make_repo_factpack(calibration="corpus"))


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
# The builder.
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


_PASSPORT_DATA = {
    "identity": {
        "name": "repo",
        "owner": "fixture",
        "url": "https://github.com/fixture/repo",
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


def test_build_repo_factpack_returns_none_when_no_passport_row_exists(db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/repo-no-passport")
    run_id = _make_run(db_session, repo_id)
    assert build_repo_factpack(db_session, repo_id, run_id) is None


def test_build_repo_factpack_returns_none_until_security_stage_is_terminal(db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/repo-pending-security")
    run_id = _make_run(db_session, repo_id)
    db_session.add(
        RepoPassport(
            analysis_run_id=run_id,
            repo_id=repo_id,
            data=_PASSPORT_DATA,
            onboarding_difficulty=42.0,
            difficulty_breakdown={},
        )
    )
    db_session.commit()

    # Passport is ready, but "security" hasn't reached a terminal status yet
    # -- the vulnerability counts below aren't trustworthy until it has.
    assert build_repo_factpack(db_session, repo_id, run_id) is None

    _make_stage(db_session, run_id, "security", StageStatus.done)
    assert build_repo_factpack(db_session, repo_id, run_id) is not None


def test_build_repo_factpack_reads_scores_and_never_a_name_or_path(db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/repo-ok")
    run_id = _make_run(db_session, repo_id)
    db_session.add(
        RepoPassport(
            analysis_run_id=run_id,
            repo_id=repo_id,
            data=_PASSPORT_DATA,
            onboarding_difficulty=42.0,
            difficulty_breakdown={},
        )
    )
    _make_stage(db_session, run_id, "security", StageStatus.done)
    db_session.commit()

    pack = build_repo_factpack(db_session, repo_id, run_id)
    assert pack is not None
    assert pack.onboarding_difficulty == 42.0
    assert pack.file_count == 10
    assert pack.subsystem_count == 1
    assert pack.truck_factor == 1
    assert pack.health_score == 80.0
    assert pack.calibration in ("heuristic", "corpus")

    # Rule 1/allowlist, checked end to end: nothing on this model can hold
    # "Real Person Name", "main.py", or "MIT" -- the builder never even
    # tries to copy them across.
    for value in pack.model_dump().values():
        assert not isinstance(value, str) or value in ("heuristic", "corpus")


def test_build_repo_factpack_counts_findings_secrets_and_vulnerabilities(db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/repo-counts")
    run_id = _make_run(db_session, repo_id)
    db_session.add(
        RepoPassport(
            analysis_run_id=run_id,
            repo_id=repo_id,
            data=_PASSPORT_DATA,
            onboarding_difficulty=42.0,
            difficulty_breakdown={},
        )
    )
    _make_stage(db_session, run_id, "security", StageStatus.done)
    db_session.commit()

    from app.db.models import Finding, Severity

    db_session.add_all(
        [
            Finding(
                analysis_run_id=run_id,
                repo_id=repo_id,
                category="risk",
                severity=Severity.high,
                confidence=0.9,
                path_id=None,
                evidence_sha=None,
                title="t",
                detail="d",
                rank=0,
            ),
            Finding(
                analysis_run_id=run_id,
                repo_id=repo_id,
                category="risk",
                severity=Severity.med,
                confidence=0.5,
                path_id=None,
                evidence_sha=None,
                title="t2",
                detail="d2",
                rank=1,
            ),
        ]
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

    pack = build_repo_factpack(db_session, repo_id, run_id)
    assert pack is not None
    assert pack.finding_count_high == 1
    assert pack.finding_count_med == 1
    assert pack.finding_count_low == 0
    assert pack.secret_count_still_in_head == 1
    assert pack.secret_count_history_only == 1
    assert pack.vulnerability_count_high == 1

    for value in pack.model_dump().values():
        assert value != "SHOULD****NEVER**BE"
        assert value != "sneaky-should-never-appear"
        assert value != "9.9.9-should-never-appear"


def test_build_repo_factpack_uses_query_result_not_stage_dict(db_session):
    """The gate reads the persisted ``analysis_stages`` row for "security"
    directly (never a stage-summary teaser) -- a row that exists but is
    still ``running``/``pending`` must not be treated as ready."""
    repo_id = _make_repo(db_session, "https://github.com/fixture/repo-still-running")
    run_id = _make_run(db_session, repo_id)
    db_session.add(
        RepoPassport(
            analysis_run_id=run_id,
            repo_id=repo_id,
            data=_PASSPORT_DATA,
            onboarding_difficulty=42.0,
            difficulty_breakdown={},
        )
    )
    _make_stage(db_session, run_id, "security", StageStatus.running)
    db_session.commit()

    assert build_repo_factpack(db_session, repo_id, run_id) is None
