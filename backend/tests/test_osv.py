"""Session 10, Part C/G: OSV.dev integration. All HTTP calls are mocked --
this never hits the real network.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from app.db.models import OsvCache
from app.security.osv import (
    OSV_BATCH_SIZE,
    DependencyQuery,
    OSVQueryError,
    _extract_fixed_version,
    _extract_severity,
    _parse_cvss_v3_base_score,
    query_vulnerabilities,
)


def _fake_response(payload: dict):
    """A context-manager-compatible stand-in for urllib.request.urlopen's
    return value."""
    mock = MagicMock()
    mock.__enter__.return_value.read.return_value = json.dumps(payload).encode("utf-8")
    mock.__exit__.return_value = False
    return mock


# ---------------------------------------------------------------------------
# CVSS v3 base-score computation
# ---------------------------------------------------------------------------


def test_cvss_v3_base_score_matches_known_reference_vector():
    # AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H is a well-known 9.8 (CRITICAL)
    # reference vector (the shape of e.g. CVE-2021-44228's own scoring).
    score = _parse_cvss_v3_base_score("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H")
    assert score == 9.8


def test_cvss_v3_base_score_returns_none_for_malformed_vector():
    assert _parse_cvss_v3_base_score("not-a-vector") is None
    assert _parse_cvss_v3_base_score("CVSS:3.1/AV:N/AC:L") is None  # missing metrics


def test_extract_severity_prefers_cvss_v3():
    data = {
        "severity": [{"type": "CVSS_V3", "score": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"}]
    }
    severity, score = _extract_severity(data)
    assert severity == "high"
    assert score == 9.8


def test_extract_severity_falls_back_to_database_specific():
    data = {"database_specific": {"severity": "MODERATE"}}
    severity, score = _extract_severity(data)
    assert severity == "med"
    assert score is None


def test_extract_severity_unknown_when_nothing_available():
    """Part C: "mark it unknown -- do not invent a severity"."""
    severity, score = _extract_severity({})
    assert severity == "unknown"
    assert score is None


def test_extract_fixed_version_reads_first_fixed_event():
    data = {
        "affected": [
            {
                "package": {"ecosystem": "PyPI", "name": "requests"},
                "ranges": [{"events": [{"introduced": "0"}, {"fixed": "2.31.0"}]}],
            }
        ]
    }
    assert _extract_fixed_version(data, "PyPI", "requests") == "2.31.0"


def test_extract_fixed_version_none_when_no_fix_published():
    data = {
        "affected": [
            {
                "package": {"ecosystem": "PyPI", "name": "requests"},
                "ranges": [{"events": [{"introduced": "0"}]}],
            }
        ]
    }
    assert _extract_fixed_version(data, "PyPI", "requests") is None


# ---------------------------------------------------------------------------
# Batching, ecosystem strings, caching, degradation
# ---------------------------------------------------------------------------


def test_ecosystem_strings_are_exact_and_case_sensitive(db_session):
    """Known Hazard #4: "pypi" != "PyPI" to OSV -- assert the EXACT strings
    this module sends."""
    deps = [
        DependencyQuery(ecosystem="PyPI", package_name="requests", version="2.0.0", is_direct=True)
    ]

    captured_payload = {}

    def fake_urlopen(request, timeout=None):
        captured_payload.update(json.loads(request.data.decode("utf-8")))
        return _fake_response({"results": [{}]})

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        query_vulnerabilities(deps, db_session)

    assert captured_payload["queries"][0]["package"]["ecosystem"] == "PyPI"

    npm_deps = [
        DependencyQuery(ecosystem="npm", package_name="left-pad", version="1.0.0", is_direct=True)
    ]
    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        query_vulnerabilities(npm_deps, db_session)
    assert captured_payload["queries"][0]["package"]["ecosystem"] == "npm"

    maven_deps = [
        DependencyQuery(
            ecosystem="Maven", package_name="org.example:lib", version="1.0", is_direct=True
        )
    ]
    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        query_vulnerabilities(maven_deps, db_session)
    assert captured_payload["queries"][0]["package"]["ecosystem"] == "Maven"


def test_batches_at_osv_batch_size(db_session):
    """1500 deps must be split into two querybatch POSTs: 1000 + 500."""
    deps = [
        DependencyQuery(ecosystem="PyPI", package_name=f"pkg{i}", version="1.0.0", is_direct=True)
        for i in range(1500)
    ]
    assert OSV_BATCH_SIZE == 1000

    batch_sizes = []

    def fake_urlopen(request, timeout=None):
        payload = json.loads(request.data.decode("utf-8"))
        batch_sizes.append(len(payload["queries"]))
        return _fake_response({"results": [{} for _ in payload["queries"]]})

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        result = query_vulnerabilities(deps, db_session)

    assert batch_sizes == [1000, 500]
    assert result == []


def test_cache_hit_avoids_a_second_fetch(db_session):
    """A second query for the same advisory must not re-fetch it -- the
    per-advisory GET is only called once, ever, across calls."""
    deps = [
        DependencyQuery(
            ecosystem="PyPI", package_name="vulnerable-pkg", version="1.0.0", is_direct=True
        )
    ]

    vuln_detail = {
        "id": "GHSA-xxxx-yyyy-zzzz",
        "summary": "A test vulnerability",
        "severity": [],
        "affected": [],
        "aliases": [],
    }
    get_calls = []

    def fake_urlopen(request, timeout=None):
        url = request.full_url
        if "querybatch" in url:
            return _fake_response({"results": [{"vulns": [{"id": "GHSA-xxxx-yyyy-zzzz"}]}]})
        get_calls.append(url)
        return _fake_response(vuln_detail)

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        first = query_vulnerabilities(deps, db_session)
    db_session.flush()
    assert db_session.get(OsvCache, "GHSA-xxxx-yyyy-zzzz") is not None
    assert len(get_calls) == 1

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        second = query_vulnerabilities(deps, db_session)

    # Still only ONE GET for the vuln detail across BOTH calls -- the
    # second call was served entirely from osv_cache.
    assert len(get_calls) == 1
    assert first[0].osv_id == second[0].osv_id == "GHSA-xxxx-yyyy-zzzz"


def test_graceful_degradation_when_osv_returns_500(db_session):
    """Part C/G: after retries are exhausted, a 500 raises OSVQueryError --
    never a silently empty/fabricated result (see osv.py's module
    docstring for why this IS the "graceful degradation": it degrades the
    one optional stage, not the truth of what was found)."""
    import urllib.error

    deps = [DependencyQuery(ecosystem="PyPI", package_name="pkg", version="1.0.0", is_direct=True)]

    def always_fail(request, timeout=None):
        raise urllib.error.HTTPError(request.full_url, 500, "Internal Server Error", {}, None)

    with (
        patch("urllib.request.urlopen", side_effect=always_fail),
        patch("app.security.osv._sleep"),
        pytest.raises(OSVQueryError),
    ):
        query_vulnerabilities(deps, db_session)


def test_no_deps_returns_empty_without_any_network_call(db_session):
    with patch("urllib.request.urlopen") as mock_urlopen:
        result = query_vulnerabilities([], db_session)
    assert result == []
    mock_urlopen.assert_not_called()
