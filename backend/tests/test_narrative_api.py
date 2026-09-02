"""Session 12, Part E/F: GET /repos/{id}/narrative and
POST /internal/runs/{id}/pregenerate-narratives.

These tests never make a real network call -- either the key pool is
genuinely empty (the default, unmodified test environment: no
``COMPASS_GEMINI_KEYS``/``COMPASS_GROQ_KEYS``), or ``generate_narrative``
itself is mocked. The mock is the "spy" Part F's cache test asks for: it
lets a test assert exactly how many times a live generation would have
happened.
"""

import uuid
from unittest.mock import MagicMock

from app.db.models import (
    AnalysisRun,
    AnalysisRunStatus,
    Repo,
    RepoPassport,
    RepoStatus,
)
from app.jobs.stages import create_pending_stages
from app.narrative.generate import GenerationResult

PASSPORT_DATA = {
    "identity": {"primary_language": "python"},
    "scale": {
        "files": 5,
        "loc": 100,
        "commits": 10,
        "contributors": 1,
        "subsystems": 1,
        "age_days": 5.0,
    },
    "cadence": {
        "commits_last_30d": 1,
        "commits_last_90d": 2,
        "commits_last_365d": 10,
        "is_dormant": False,
    },
    "team": {
        "active_contributors": 1,
        "stale_contributors": 0,
        "bot_commit_ratio": 0.0,
        "truck_factor": 1,
    },
    "shape": {"subsystems": [], "entry_points": [], "modularity": 0.5},
    "hotspots": {"top_risk_files": [], "churn_concentration": 0.1},
    "health": {
        "score": 90.0,
        "high_risk_ratio": 0.0,
        "cycle_count": 0,
        "hidden_dependency_count": 0,
    },
}


def _make_repo(db_session, url: str, **kwargs) -> Repo:
    repo = Repo(url=url, owner="fixture", name="repo", status=RepoStatus.ready, **kwargs)
    db_session.add(repo)
    db_session.commit()
    return repo


def _make_ready_run_with_passport(
    db_session, repo_id: uuid.UUID, difficulty: float = 40.0
) -> uuid.UUID:
    run = AnalysisRun(repo_id=repo_id, status=AnalysisRunStatus.ready, head_sha="sha1")
    db_session.add(run)
    db_session.flush()
    create_pending_stages(run.id, db_session)
    db_session.add(
        RepoPassport(
            analysis_run_id=run.id,
            repo_id=repo_id,
            data=PASSPORT_DATA,
            onboarding_difficulty=difficulty,
            difficulty_breakdown={},
        )
    )
    db_session.commit()
    return run.id


def test_returns_available_false_no_keys_when_pool_is_empty(client, db_session):
    """The default, unmodified test environment has zero narrative keys
    configured -- this must be a clean, honest false, never a 500."""
    repo = _make_repo(db_session, "https://github.com/fixture/narrative-nokeys")
    _make_ready_run_with_passport(db_session, repo.id)

    resp = client.get(f"/repos/{repo.id}/narrative?surface=passport")
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is False
    assert body["reason"] == "no_keys"
    assert body["content"] is None


def test_invalid_surface_is_422(client, db_session):
    repo = _make_repo(db_session, "https://github.com/fixture/narrative-badsurface")
    _make_ready_run_with_passport(db_session, repo.id)
    resp = client.get(f"/repos/{repo.id}/narrative?surface=not_a_real_surface")
    assert resp.status_code == 422


def test_risk_file_without_subject_is_422(client, db_session):
    repo = _make_repo(db_session, "https://github.com/fixture/narrative-nosubject")
    _make_ready_run_with_passport(db_session, repo.id)
    resp = client.get(f"/repos/{repo.id}/narrative?surface=risk_file")
    assert resp.status_code == 422


def test_no_analysis_run_yet_is_404(client, db_session):
    repo = _make_repo(db_session, "https://github.com/fixture/narrative-norun")
    resp = client.get(f"/repos/{repo.id}/narrative?surface=passport")
    assert resp.status_code == 404


def test_security_surface_is_disabled_until_stages_are_terminal(client, db_session):
    repo = _make_repo(db_session, "https://github.com/fixture/narrative-secpending")
    run_id = _make_ready_run_with_passport(db_session, repo.id)
    # create_pending_stages already left "secrets"/"security" as `pending`.
    resp = client.get(f"/repos/{repo.id}/narrative?surface=security&run_id={run_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is False
    assert body["reason"] == "disabled"


def _enable_pool_and_mock_generation(monkeypatch, content: str = "Grounded prose about this repo."):
    import app.api.narrative as narrative_api

    monkeypatch.setattr(narrative_api.pool, "has_any_keys", lambda: True)
    mock_generate = MagicMock(
        return_value=GenerationResult(True, content, "gemini", "gemini-2.0-flash", None)
    )
    monkeypatch.setattr(narrative_api.generate, "generate_narrative", mock_generate)
    return mock_generate


def test_generated_narrative_is_cached_second_request_makes_no_generation_call(
    client, db_session, monkeypatch
):
    repo = _make_repo(db_session, "https://github.com/fixture/narrative-cache")
    run_id = _make_ready_run_with_passport(db_session, repo.id)
    mock_generate = _enable_pool_and_mock_generation(monkeypatch)

    first = client.get(f"/repos/{repo.id}/narrative?surface=passport&run_id={run_id}")
    assert first.status_code == 200
    body1 = first.json()
    assert body1["available"] is True
    assert body1["content"] == "Grounded prose about this repo."
    assert body1["provider"] == "gemini"
    assert mock_generate.call_count == 1

    second = client.get(f"/repos/{repo.id}/narrative?surface=passport&run_id={run_id}")
    assert second.status_code == 200
    body2 = second.json()
    assert body2["available"] is True
    assert body2["content"] == body1["content"]
    # The spy: a cache hit must never call the generator again.
    assert mock_generate.call_count == 1


def test_changed_factpack_hash_regenerates(client, db_session, monkeypatch):
    repo = _make_repo(db_session, "https://github.com/fixture/narrative-invalidate")
    run_id = _make_ready_run_with_passport(db_session, repo.id, difficulty=40.0)
    mock_generate = _enable_pool_and_mock_generation(monkeypatch, content="First version.")

    first = client.get(f"/repos/{repo.id}/narrative?surface=passport&run_id={run_id}")
    assert first.json()["content"] == "First version."
    assert mock_generate.call_count == 1

    # Mutate the underlying computed data for the SAME run -- a legitimate,
    # if unusual, case (e.g. a corrected engine run under the same run id in
    # a test), which must invalidate the cache rather than silently keep
    # serving stale prose.
    from sqlalchemy import select

    row = db_session.scalar(select(RepoPassport).where(RepoPassport.analysis_run_id == run_id))
    row.onboarding_difficulty = 99.0
    db_session.commit()

    mock_generate.return_value = GenerationResult(True, "Second version.", "gemini", "m", None)
    second = client.get(f"/repos/{repo.id}/narrative?surface=passport&run_id={run_id}")
    assert second.json()["content"] == "Second version."
    assert mock_generate.call_count == 2


def test_rejected_generation_returns_available_false_reason_rejected(
    client, db_session, monkeypatch
):
    repo = _make_repo(db_session, "https://github.com/fixture/narrative-rejected")
    run_id = _make_ready_run_with_passport(db_session, repo.id)
    import app.api.narrative as narrative_api

    monkeypatch.setattr(narrative_api.pool, "has_any_keys", lambda: True)
    monkeypatch.setattr(
        narrative_api.generate,
        "generate_narrative",
        MagicMock(return_value=GenerationResult(False, None, None, None, "rejected")),
    )

    resp = client.get(f"/repos/{repo.id}/narrative?surface=passport&run_id={run_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is False
    assert body["reason"] == "rejected"


def test_a_rejected_generation_is_never_persisted(client, db_session, monkeypatch):
    from sqlalchemy import select

    from app.db.models import Narrative

    repo = _make_repo(db_session, "https://github.com/fixture/narrative-not-persisted")
    run_id = _make_ready_run_with_passport(db_session, repo.id)
    import app.api.narrative as narrative_api

    monkeypatch.setattr(narrative_api.pool, "has_any_keys", lambda: True)
    monkeypatch.setattr(
        narrative_api.generate,
        "generate_narrative",
        MagicMock(return_value=GenerationResult(False, None, None, None, "rejected")),
    )
    client.get(f"/repos/{repo.id}/narrative?surface=passport&run_id={run_id}")

    rows = db_session.scalars(select(Narrative).where(Narrative.analysis_run_id == run_id)).all()
    assert rows == []


# ---------------------------------------------------------------------------
# Admin pre-generation endpoint.
# ---------------------------------------------------------------------------


def test_pregenerate_endpoint_503_when_admin_token_unconfigured(client, db_session):
    repo = _make_repo(db_session, "https://github.com/fixture/narrative-admin-unconf")
    run_id = _make_ready_run_with_passport(db_session, repo.id)
    resp = client.post(f"/internal/runs/{run_id}/pregenerate-narratives")
    assert resp.status_code == 503


def test_pregenerate_endpoint_401_with_wrong_token(client, db_session, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "COMPASS_ADMIN_TOKEN", "correct-token")
    repo = _make_repo(db_session, "https://github.com/fixture/narrative-admin-wrong")
    run_id = _make_ready_run_with_passport(db_session, repo.id)

    resp = client.post(
        f"/internal/runs/{run_id}/pregenerate-narratives", headers={"X-Admin-Token": "wrong"}
    )
    assert resp.status_code == 401


def test_pregenerate_endpoint_generates_with_correct_token(client, db_session, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "COMPASS_ADMIN_TOKEN", "correct-token")
    repo = _make_repo(db_session, "https://github.com/fixture/narrative-admin-ok")
    run_id = _make_ready_run_with_passport(db_session, repo.id)
    _enable_pool_and_mock_generation(monkeypatch, content="Pre-generated prose.")

    resp = client.post(
        f"/internal/runs/{run_id}/pregenerate-narratives",
        headers={"X-Admin-Token": "correct-token"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert {"surface": "passport", "subject": ""} in body["generated"]
