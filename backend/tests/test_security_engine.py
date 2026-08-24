"""Session 10, Part F/G: SecurityEngine (findings from secret_hits +
vulnerabilities) and fetch_and_persist_vulnerabilities."""

import uuid
from datetime import UTC, datetime
from unittest.mock import patch

from sqlalchemy import insert, select

from app.db.models import (
    AnalysisRun,
    AnalysisRunStatus,
    DependencyDeclared,
    Finding,
    Repo,
    RepoPath,
    RepoStatus,
    SecretHit,
    Vulnerability,
)
from app.engines.context import RunContext
from app.engines.security import SecurityEngine, fetch_and_persist_vulnerabilities


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


def _intern_path(db_session, repo_id: uuid.UUID, path: str) -> int:
    db_session.execute(insert(RepoPath), [{"repo_id": repo_id, "path": path}])
    db_session.commit()
    return db_session.scalar(
        select(RepoPath.id).where(RepoPath.repo_id == repo_id, RepoPath.path == path)
    )


def test_security_engine_emits_secret_and_vulnerability_findings_with_signatures(db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/secengine-1")
    run_id = _make_run(db_session, repo_id)
    path_id = _intern_path(db_session, repo_id, "config.py")

    db_session.execute(
        insert(SecretHit),
        [
            {
                "repo_id": repo_id,
                "rule_id": "aws-access-key-id",
                "description": "AWS Access Key ID",
                "path_id": path_id,
                "commit_sha": "a" * 40,
                "committed_at": datetime.now(UTC),
                "line_number": 3,
                "fingerprint": "fp1",
                "redacted_preview": "AKIA****************GH",
                "entropy": None,
                "still_in_head": False,
            }
        ],
    )
    db_session.execute(
        insert(Vulnerability),
        [
            {
                "analysis_run_id": run_id,
                "repo_id": repo_id,
                "ecosystem": "PyPI",
                "package_name": "vulnpkg",
                "version": "1.0.0",
                "osv_id": "GHSA-aaaa-bbbb-cccc",
                "aliases": ["CVE-2024-0001"],
                "severity": "high",
                "cvss_score": 9.8,
                "summary": "A critical vulnerability",
                "fixed_version": "1.0.1",
                "published_at": datetime.now(UTC),
                "is_direct": True,
            }
        ],
    )
    db_session.commit()

    ctx = RunContext(repo_id=repo_id, run_id=run_id)
    result = SecurityEngine().run(ctx, db_session)

    assert result["secrets_found"] == 1
    assert result["secrets_still_in_head"] == 0
    assert result["vulnerabilities_found"] == 1
    assert result["findings_emitted"] == 2

    findings = db_session.scalars(select(Finding).where(Finding.analysis_run_id == run_id)).all()
    categories = {f.category for f in findings}
    assert categories == {"secret", "vulnerability"}

    secret_finding = next(f for f in findings if f.category == "secret")
    assert secret_finding.severity.value == "high"
    assert secret_finding.signature is not None
    # "only in history is ALSO high, never downgraded"
    assert "rotated" in secret_finding.detail

    vuln_finding = next(f for f in findings if f.category == "vulnerability")
    assert vuln_finding.severity.value == "high"
    assert "1.0.1" in vuln_finding.detail


def test_secret_still_in_head_is_not_downgraded_below_history_only(db_session):
    """Part F: still-in-HEAD and history-only secrets are BOTH high --
    neither is ever downgraded."""
    repo_id = _make_repo(db_session, "https://github.com/fixture/secengine-2")
    run_id = _make_run(db_session, repo_id)
    path_id = _intern_path(db_session, repo_id, "config.py")

    db_session.execute(
        insert(SecretHit),
        [
            {
                "repo_id": repo_id,
                "rule_id": "aws-access-key-id",
                "description": "AWS Access Key ID",
                "path_id": path_id,
                "commit_sha": "b" * 40,
                "committed_at": datetime.now(UTC),
                "line_number": 1,
                "fingerprint": "fp-still-in-head",
                "redacted_preview": "AKIA****************GH",
                "entropy": None,
                "still_in_head": True,
            }
        ],
    )
    db_session.commit()

    ctx = RunContext(repo_id=repo_id, run_id=run_id)
    SecurityEngine().run(ctx, db_session)

    finding = db_session.scalar(
        select(Finding).where(Finding.analysis_run_id == run_id, Finding.category == "secret")
    )
    assert finding.severity.value == "high"


def test_security_engine_caps_findings_at_ten_per_category(db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/secengine-cap")
    run_id = _make_run(db_session, repo_id)
    path_id = _intern_path(db_session, repo_id, "config.py")

    rows = [
        {
            "repo_id": repo_id,
            "rule_id": "aws-access-key-id",
            "description": "AWS Access Key ID",
            "path_id": path_id,
            "commit_sha": f"{i:040x}",
            "committed_at": datetime.now(UTC),
            "line_number": i,
            "fingerprint": f"fp-{i}",
            "redacted_preview": "AKIA****************GH",
            "entropy": None,
            "still_in_head": False,
        }
        for i in range(15)
    ]
    db_session.execute(insert(SecretHit), rows)
    db_session.commit()

    ctx = RunContext(repo_id=repo_id, run_id=run_id)
    result = SecurityEngine().run(ctx, db_session)

    assert result["secrets_found"] == 15
    findings = db_session.scalars(
        select(Finding).where(Finding.analysis_run_id == run_id, Finding.category == "secret")
    ).all()
    assert len(findings) == 10


def test_security_engine_only_reads_this_runs_vulnerabilities(db_session):
    """Vulnerability is Insight -- must be filtered by analysis_run_id, not
    just repo_id, or it mixes rows from unrelated runs."""
    repo_id = _make_repo(db_session, "https://github.com/fixture/secengine-runscope")
    run_a = _make_run(db_session, repo_id)
    run_b = _make_run(db_session, repo_id)

    db_session.execute(
        insert(Vulnerability),
        [
            {
                "analysis_run_id": run_a,
                "repo_id": repo_id,
                "ecosystem": "PyPI",
                "package_name": "pkg-a",
                "version": "1.0.0",
                "osv_id": "GHSA-a",
                "aliases": [],
                "severity": "low",
                "cvss_score": None,
                "summary": "s",
                "fixed_version": None,
                "published_at": None,
                "is_direct": True,
            }
        ],
    )
    db_session.commit()

    ctx = RunContext(repo_id=repo_id, run_id=run_b)
    result = SecurityEngine().run(ctx, db_session)
    assert result["vulnerabilities_found"] == 0


def test_zero_secrets_and_vulnerabilities_is_a_clean_empty_run(db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/secengine-empty")
    run_id = _make_run(db_session, repo_id)
    ctx = RunContext(repo_id=repo_id, run_id=run_id)
    result = SecurityEngine().run(ctx, db_session)
    assert result == {
        "secrets_found": 0,
        "secrets_still_in_head": 0,
        "vulnerabilities_found": 0,
        "findings_emitted": 0,
    }


def test_fetch_and_persist_vulnerabilities_no_declared_deps_makes_no_network_call(db_session):
    repo_id = _make_repo(db_session, "https://github.com/fixture/secengine-nodeps")
    run_id = _make_run(db_session, repo_id)
    ctx = RunContext(repo_id=repo_id, run_id=run_id)

    with patch("urllib.request.urlopen") as mock_urlopen:
        result = fetch_and_persist_vulnerabilities(ctx, db_session)

    mock_urlopen.assert_not_called()
    assert result == {"dependencies_queried": 0, "vulnerabilities_found": 0}


def test_fetch_and_persist_vulnerabilities_persists_rows_tagged_with_this_run(db_session):
    import json
    from unittest.mock import MagicMock

    repo_id = _make_repo(db_session, "https://github.com/fixture/secengine-fetch")
    run_id = _make_run(db_session, repo_id)
    manifest_path_id = _intern_path(db_session, repo_id, "requirements.txt")

    db_session.execute(
        insert(DependencyDeclared),
        [
            {
                "repo_id": repo_id,
                "ecosystem": "PyPI",
                "package_name": "vulnpkg",
                "version": "1.0.0",
                "is_direct": True,
                "manifest_path_id": manifest_path_id,
                "scope": "runtime",
            }
        ],
    )
    db_session.commit()

    def fake_urlopen(request, timeout=None):
        mock = MagicMock()
        url = request.full_url
        if "querybatch" in url:
            body = {"results": [{"vulns": [{"id": "GHSA-1"}]}]}
        else:
            body = {"id": "GHSA-1", "summary": "bad", "severity": [], "affected": [], "aliases": []}
        mock.__enter__.return_value.read.return_value = json.dumps(body).encode("utf-8")
        mock.__exit__.return_value = False
        return mock

    ctx = RunContext(repo_id=repo_id, run_id=run_id)
    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        result = fetch_and_persist_vulnerabilities(ctx, db_session)

    assert result == {"dependencies_queried": 1, "vulnerabilities_found": 1}
    row = db_session.scalar(select(Vulnerability).where(Vulnerability.analysis_run_id == run_id))
    assert row.osv_id == "GHSA-1"
    assert row.repo_id == repo_id
