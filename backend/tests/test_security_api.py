"""Session 10, Part F/G: GET /repos/{id}/secrets and
GET /repos/{id}/vulnerabilities -- gating, the private-repo share-link
exception (Part D.4), and the "no supported manifest" honesty contract.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import insert, select

from app.auth.session import SESSION_COOKIE_NAME, create_session_token
from app.db.models import (
    AnalysisRun,
    AnalysisRunStatus,
    AnalysisStage,
    Repo,
    RepoPath,
    RepoStatus,
    SecretHit,
    ShareLink,
    StageStatus,
    User,
    Vulnerability,
)
from app.jobs.stages import create_pending_stages


def _make_repo(db_session, url: str, **kwargs) -> Repo:
    repo = Repo(url=url, owner="fixture", name="repo", status=RepoStatus.ready, **kwargs)
    db_session.add(repo)
    db_session.commit()
    return repo


def _make_user(db_session, github_id: int) -> User:
    user = User(github_id=github_id, github_login=f"user-{github_id}")
    db_session.add(user)
    db_session.commit()
    return user


def _make_run_with_pending_stages(db_session, repo_id: uuid.UUID) -> uuid.UUID:
    run = AnalysisRun(repo_id=repo_id, status=AnalysisRunStatus.running, head_sha="test-sha")
    db_session.add(run)
    db_session.flush()
    create_pending_stages(run.id, db_session)
    db_session.commit()
    return run.id


def _set_stage_status(
    db_session, run_id: uuid.UUID, name: str, status: StageStatus, summary=None
) -> None:
    row = db_session.scalar(
        select(AnalysisStage).where(AnalysisStage.run_id == run_id, AnalysisStage.name == name)
    )
    row.status = status
    if summary is not None:
        row.summary = summary
    db_session.commit()


def _login(client, user: User) -> None:
    token = create_session_token(user.id)
    client.cookies.set(SESSION_COOKIE_NAME, token)


# ---------------------------------------------------------------------------
# /secrets -- gating
# ---------------------------------------------------------------------------


def test_secrets_endpoint_202_while_pending_then_200_when_done(client, db_session):
    repo = _make_repo(db_session, "https://github.com/fixture/secrets-gate")
    run_id = _make_run_with_pending_stages(db_session, repo.id)

    pending = client.get(f"/repos/{repo.id}/secrets")
    assert pending.status_code == 202
    assert pending.json() == {"stage": "secrets", "status": "pending"}

    _set_stage_status(db_session, run_id, "secrets", StageStatus.done)

    done = client.get(f"/repos/{repo.id}/secrets")
    assert done.status_code == 200
    body = done.json()
    assert body["hits"] == []
    assert body["total"] == 0
    assert body["truncated"] is False


def test_secrets_endpoint_returns_still_in_head_and_redacted_preview(client, db_session):
    repo = _make_repo(db_session, "https://github.com/fixture/secrets-content")
    run_id = _make_run_with_pending_stages(db_session, repo.id)
    _set_stage_status(db_session, run_id, "secrets", StageStatus.done, summary={"truncated": False})

    path = RepoPath(repo_id=repo.id, path="config.py")
    db_session.add(path)
    db_session.flush()
    db_session.execute(
        insert(SecretHit),
        [
            {
                "repo_id": repo.id,
                "rule_id": "aws-access-key-id",
                "description": "AWS Access Key ID",
                "path_id": path.id,
                "commit_sha": "c" * 40,
                "committed_at": datetime.now(UTC),
                "line_number": 2,
                "fingerprint": "fp-api-test",
                "redacted_preview": "AKIA****************GH",
                "entropy": None,
                "still_in_head": False,
            }
        ],
    )
    db_session.commit()

    response = client.get(f"/repos/{repo.id}/secrets")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["still_in_head_count"] == 0
    hit = body["hits"][0]
    assert hit["file_path"] == "config.py"
    assert hit["still_in_head"] is False
    assert hit["redacted_preview"] == "AKIA****************GH"
    # No raw secret substring anywhere in the serialized JSON payload.
    assert "QPMNBVCXZLKJHGFD" not in response.text


def test_secrets_truncation_reported_honestly(client, db_session):
    repo = _make_repo(db_session, "https://github.com/fixture/secrets-truncated")
    run_id = _make_run_with_pending_stages(db_session, repo.id)
    _set_stage_status(
        db_session,
        run_id,
        "secrets",
        StageStatus.done,
        summary={
            "truncated": True,
            "truncation_reason": "scanned the most recent 3 commits (time budget reached)",
        },
    )

    response = client.get(f"/repos/{repo.id}/secrets")
    body = response.json()
    assert body["truncated"] is True
    assert "3 commits" in body["truncation_reason"]


# ---------------------------------------------------------------------------
# /secrets -- Part D.4 private-repo share-link exception
# ---------------------------------------------------------------------------


def test_secrets_on_private_repo_visible_to_owner(client, db_session):
    owner = _make_user(db_session, 101)
    repo = _make_repo(
        db_session,
        "https://github.com/fixture/secrets-private-owner",
        is_private=True,
        owner_user_id=owner.id,
    )
    run_id = _make_run_with_pending_stages(db_session, repo.id)
    _set_stage_status(db_session, run_id, "secrets", StageStatus.done)

    _login(client, owner)
    response = client.get(f"/repos/{repo.id}/secrets")
    assert response.status_code == 200


def test_secrets_on_private_repo_blocked_for_anonymous(client, db_session):
    owner = _make_user(db_session, 102)
    repo = _make_repo(
        db_session,
        "https://github.com/fixture/secrets-private-anon",
        is_private=True,
        owner_user_id=owner.id,
    )
    _make_run_with_pending_stages(db_session, repo.id)

    response = client.get(f"/repos/{repo.id}/secrets")
    assert response.status_code == 403


def test_secrets_on_private_repo_NOT_visible_through_a_valid_share_link(client, db_session):
    """THE core Part D.4 assertion: a valid, unrevoked share link for the
    EXACT run being requested grants access to every other repo-scoped
    endpoint, but explicitly NOT this one -- asserted on the serialized
    HTTP response, not just the underlying query."""
    owner = _make_user(db_session, 103)
    repo = _make_repo(
        db_session,
        "https://github.com/fixture/secrets-private-share",
        is_private=True,
        owner_user_id=owner.id,
    )
    run_id = _make_run_with_pending_stages(db_session, repo.id)
    _set_stage_status(db_session, run_id, "secrets", StageStatus.done)

    path = RepoPath(repo_id=repo.id, path="config.py")
    db_session.add(path)
    db_session.flush()
    db_session.execute(
        insert(SecretHit),
        [
            {
                "repo_id": repo.id,
                "rule_id": "aws-access-key-id",
                "description": "AWS Access Key ID",
                "path_id": path.id,
                "commit_sha": "d" * 40,
                "committed_at": datetime.now(UTC),
                "line_number": 1,
                "fingerprint": "fp-share-test",
                "redacted_preview": "AKIA****************GH",
                "entropy": None,
                "still_in_head": True,
            }
        ],
    )
    link = ShareLink(run_id=run_id, slug="secrets-share-slug", created_by=owner.id)
    db_session.add(link)
    db_session.commit()

    # Sanity check: the SAME share link/run DOES unlock a normal endpoint
    # (architecture gates on a stage this run hasn't reached, so 202 is the
    # correctly-authorized response here -- the point is "not 403").
    other_endpoint = client.get(
        f"/repos/{repo.id}/architecture", params={"run_id": str(run_id), "share": link.slug}
    )
    assert other_endpoint.status_code != 403

    response = client.get(
        f"/repos/{repo.id}/secrets", params={"run_id": str(run_id), "share": link.slug}
    )
    assert response.status_code == 403
    assert "owner" in response.json()["detail"].lower()
    # And no secret content leaked into the 403 body either.
    assert "config.py" not in response.text


def test_secrets_on_public_repo_visible_to_anyone(client, db_session):
    repo = _make_repo(db_session, "https://github.com/fixture/secrets-public", is_private=False)
    run_id = _make_run_with_pending_stages(db_session, repo.id)
    _set_stage_status(db_session, run_id, "secrets", StageStatus.done)

    response = client.get(f"/repos/{repo.id}/secrets")
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# /vulnerabilities
# ---------------------------------------------------------------------------


def test_vulnerabilities_gates_on_security_stage(client, db_session):
    repo = _make_repo(db_session, "https://github.com/fixture/vulns-gate")
    _make_run_with_pending_stages(db_session, repo.id)

    pending = client.get(f"/repos/{repo.id}/vulnerabilities")
    assert pending.status_code == 202
    assert pending.json()["stage"] == "security"


def test_vulnerabilities_no_supported_manifest_distinguishable_from_empty(client, db_session):
    repo = _make_repo(db_session, "https://github.com/fixture/vulns-no-manifest")
    run_id = _make_run_with_pending_stages(db_session, repo.id)
    _set_stage_status(
        db_session,
        run_id,
        "structure",
        StageStatus.done,
        summary={"dependency_manifest_found": False},
    )
    _set_stage_status(db_session, run_id, "security", StageStatus.done)

    response = client.get(f"/repos/{repo.id}/vulnerabilities")
    assert response.status_code == 200
    body = response.json()
    assert body["vulnerabilities"] == []
    assert body["no_supported_manifest"] is True


def test_vulnerabilities_empty_but_manifest_found_is_not_reported_as_no_manifest(
    client, db_session
):
    repo = _make_repo(db_session, "https://github.com/fixture/vulns-manifest-found-empty")
    run_id = _make_run_with_pending_stages(db_session, repo.id)
    _set_stage_status(
        db_session,
        run_id,
        "structure",
        StageStatus.done,
        summary={"dependency_manifest_found": True},
    )
    _set_stage_status(db_session, run_id, "security", StageStatus.done)

    response = client.get(f"/repos/{repo.id}/vulnerabilities")
    body = response.json()
    assert body["vulnerabilities"] == []
    assert body["no_supported_manifest"] is False


def test_vulnerabilities_returns_persisted_rows_ranked_by_severity(client, db_session):
    repo = _make_repo(db_session, "https://github.com/fixture/vulns-content")
    run_id = _make_run_with_pending_stages(db_session, repo.id)
    _set_stage_status(
        db_session,
        run_id,
        "structure",
        StageStatus.done,
        summary={"dependency_manifest_found": True},
    )
    _set_stage_status(db_session, run_id, "security", StageStatus.done)

    db_session.execute(
        insert(Vulnerability),
        [
            {
                "analysis_run_id": run_id,
                "repo_id": repo.id,
                "ecosystem": "PyPI",
                "package_name": "low-pkg",
                "version": "1.0.0",
                "osv_id": "GHSA-low",
                "aliases": [],
                "severity": "low",
                "cvss_score": 2.0,
                "summary": "low sev",
                "fixed_version": None,
                "published_at": None,
                "is_direct": True,
            },
            {
                "analysis_run_id": run_id,
                "repo_id": repo.id,
                "ecosystem": "npm",
                "package_name": "high-pkg",
                "version": "2.0.0",
                "osv_id": "GHSA-high",
                "aliases": ["CVE-2024-1234"],
                "severity": "high",
                "cvss_score": 9.1,
                "summary": "high sev",
                "fixed_version": "2.0.1",
                "published_at": None,
                "is_direct": False,
            },
        ],
    )
    db_session.commit()

    response = client.get(f"/repos/{repo.id}/vulnerabilities")
    body = response.json()
    assert [v["osv_id"] for v in body["vulnerabilities"]] == ["GHSA-high", "GHSA-low"]


def test_vulnerabilities_failed_optional_security_stage_returns_200_not_202_forever(
    client, db_session
):
    """Session 10: a "failed" stage is now ALSO terminal for the 202
    contract (added specifically for optional stages) -- an OSV outage
    marks "security" failed while the run itself stays healthy, and this
    endpoint must resolve rather than 202 forever."""
    repo = _make_repo(db_session, "https://github.com/fixture/vulns-stage-failed")
    run_id = _make_run_with_pending_stages(db_session, repo.id)
    _set_stage_status(
        db_session,
        run_id,
        "structure",
        StageStatus.done,
        summary={"dependency_manifest_found": True},
    )
    _set_stage_status(db_session, run_id, "security", StageStatus.failed)

    response = client.get(f"/repos/{repo.id}/vulnerabilities")
    assert response.status_code == 200
    assert response.json()["vulnerabilities"] == []
