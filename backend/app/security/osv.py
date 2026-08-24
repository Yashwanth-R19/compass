"""OSV.dev integration (session 10, Part C): batches declared dependencies
against ``https://api.osv.dev/v1/querybatch``, resolves full details for
each unique advisory id (checking the ``osv_cache`` table first -- see its
docstring in app/db/models.py for why that table lives outside both the
Facts and Insight lifecycles), and extracts a best-effort severity.

No paid/key-requiring API, no new dependency: HTTP calls go through
``urllib.request``, the same pattern already established in
``app/ingestion/guardrails.py`` and ``app/jobs/dispatch.py`` for every
other outbound call in this codebase.

**OSV ecosystem strings are exact and case-sensitive** (Known Hazard #4):
``"pypi"`` and ``"PyPI"`` are different strings to that API, and a wrong
string returns an empty result with a 200 status -- no error, just
silence. The three ecosystem strings this module (and
``app/ingestion/manifests.py::extract_declared_dependencies``) ever use are
``PyPI``, ``npm``, ``Maven`` -- exactly OSV's own documented ecosystem
names.

**Total failure must degrade the ONE "security" stage, never the whole
run.** After ``MAX_ATTEMPTS`` retries with backoff, ``query_vulnerabilities``
raises ``OSVQueryError`` rather than silently returning an empty or
fabricated result -- a 500 from OSV is not the same fact as "this repo
genuinely has zero vulnerabilities," and conflating the two would be
exactly the dishonest-degradation this product's whole design argues
against. The "security" stage is ``optional=True`` (app/jobs/stages.py)
specifically so this exception marks THAT ONE STAGE failed while the
analysis run still reaches "ready" -- the mechanism session 11's "two
working sections, one errored" security page depends on.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.db.models import OsvCache

logger = logging.getLogger(__name__)

OSV_QUERYBATCH_URL = "https://api.osv.dev/v1/querybatch"
OSV_VULN_URL_TEMPLATE = "https://api.osv.dev/v1/vulns/{osv_id}"

OSV_BATCH_SIZE = 1000
"""OSV's own documented cap on queries per querybatch request (Part C)."""

REQUEST_TIMEOUT_SECONDS = 10.0
MAX_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = (1.0, 2.0, 4.0)
"""Session 10, Part C: "timeouts (10s), retries with backoff (3 attempts)".
A short, fixed sequence rather than a formula -- HEURISTIC, chosen to keep
one failing request's total worst-case wait (~7s across 2 backoff sleeps)
comfortably inside the "security" stage's own network-latency budget."""


class OSVQueryError(RuntimeError):
    """Raised when OSV.dev is unreachable/erroring after MAX_ATTEMPTS
    retries -- see this module's docstring for why this deliberately
    propagates rather than degrading silently to an empty result."""


@dataclass(frozen=True)
class DependencyQuery:
    ecosystem: str
    package_name: str
    version: str
    is_direct: bool


@dataclass(frozen=True)
class Vulnerability:
    ecosystem: str
    package_name: str
    version: str
    osv_id: str
    aliases: list[str]
    severity: str
    cvss_score: float | None
    summary: str
    fixed_version: str | None
    published_at: datetime | None
    is_direct: bool


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


def _post_json(url: str, payload: dict) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


def _get_json(url: str) -> dict:
    request = urllib.request.Request(url)
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


def _with_retries(call, *, description: str) -> dict:
    last_error: Exception | None = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            return call()
        except (
            urllib.error.HTTPError,
            urllib.error.URLError,
            TimeoutError,
            OSError,
            ValueError,
        ) as exc:
            last_error = exc
            logger.warning(
                "OSV request failed (%s), attempt %d/%d: %r",
                description,
                attempt + 1,
                MAX_ATTEMPTS,
                exc,
            )
            if attempt < MAX_ATTEMPTS - 1:
                _sleep(RETRY_BACKOFF_SECONDS[attempt])
    raise OSVQueryError(
        f"OSV request failed after {MAX_ATTEMPTS} attempts ({description})"
    ) from last_error


# ---- CVSS v3.0/3.1 base-score computation (Part C: "parse the base score") ----
#
# Base metrics only, per FIRST.org's own published formula
# (https://www.first.org/cvss/v3-1/specification-document sec 7.4/8.4) --
# OSV.dev's `severity[].score` field for a CVSS_V3 entry is the VECTOR
# STRING (e.g. "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"), not a
# numeric score directly, so computing the score means implementing the
# real formula, not just parsing a number out of the string.

_AV = {"N": 0.85, "A": 0.62, "L": 0.55, "P": 0.20}
_AC = {"L": 0.77, "H": 0.44}
_PR_UNCHANGED = {"N": 0.85, "L": 0.62, "H": 0.27}
_PR_CHANGED = {"N": 0.85, "L": 0.68, "H": 0.50}
_UI = {"N": 0.85, "R": 0.62}
_CIA = {"N": 0.0, "L": 0.22, "H": 0.56}


def _roundup(value: float) -> float:
    """FIRST.org's specified rounding: UP to one decimal place, via an
    integer-scaled algorithm that sidesteps float-precision edge cases
    (their own reference implementation does the same)."""
    int_value = int(round(value * 100000))
    if int_value % 10000 == 0:
        return int_value / 100000.0
    return (int_value // 10000 + 1) / 10.0


def _parse_cvss_v3_base_score(vector: str) -> float | None:
    """Computes the CVSS v3.0/3.1 BASE score from a vector string. Returns
    ``None`` for a vector missing a required metric or using a value this
    table doesn't recognize -- never a guessed score."""
    metrics: dict[str, str] = {}
    for part in vector.split("/"):
        if ":" not in part:
            continue
        key, _, value = part.partition(":")
        metrics[key] = value

    try:
        av = _AV[metrics["AV"]]
        ac = _AC[metrics["AC"]]
        ui = _UI[metrics["UI"]]
        scope = metrics["S"]
        pr_table = _PR_CHANGED if scope == "C" else _PR_UNCHANGED
        pr = pr_table[metrics["PR"]]
        c = _CIA[metrics["C"]]
        i = _CIA[metrics["I"]]
        a = _CIA[metrics["A"]]
    except KeyError:
        return None

    iss = 1 - ((1 - c) * (1 - i) * (1 - a))
    impact = 7.52 * (iss - 0.029) - 3.25 * (iss - 0.02) ** 15 if scope == "C" else 6.42 * iss
    exploitability = 8.22 * av * ac * pr * ui

    if impact <= 0:
        return 0.0

    combined = impact + exploitability
    if scope == "C":
        combined *= 1.08

    return _roundup(min(combined, 10.0))


def _cvss_to_severity(score: float) -> str:
    # FIRST.org's own published CVSS v3 qualitative severity bands.
    if score >= 7.0:
        return "high"
    if score >= 4.0:
        return "med"
    return "low"


def _extract_severity(vuln_data: dict) -> tuple[str, float | None]:
    """Prefer a CVSS v3 vector from ``severity[]``, parse its base score.
    Fall back to ``database_specific.severity`` (a plain string some OSV
    sources, e.g. GHSA, already provide). If neither exists: "unknown" --
    NEVER invented (Part C)."""
    for entry in vuln_data.get("severity", []) or []:
        if entry.get("type") != "CVSS_V3":
            continue
        vector = entry.get("score")
        if not vector:
            continue
        score = _parse_cvss_v3_base_score(vector)
        if score is not None:
            return _cvss_to_severity(score), score

    db_specific = vuln_data.get("database_specific") or {}
    raw = db_specific.get("severity")
    if isinstance(raw, str) and raw.strip():
        label = raw.strip().lower()
        if label in ("critical", "high"):
            return "high", None
        if label in ("moderate", "medium", "med"):
            return "med", None
        if label == "low":
            return "low", None

    return "unknown", None


def _extract_fixed_version(vuln_data: dict, ecosystem: str, package_name: str) -> str | None:
    """The first "fixed" event found in any range for the matching
    (ecosystem, package) affected entry -- best-effort, not a claim of "the
    single correct" fix version when several ranges/branches each declare
    their own fix."""
    for affected in vuln_data.get("affected", []) or []:
        pkg = affected.get("package") or {}
        if pkg.get("ecosystem") != ecosystem or pkg.get("name") != package_name:
            continue
        for rng in affected.get("ranges", []) or []:
            for event in rng.get("events", []) or []:
                fixed = event.get("fixed")
                if fixed:
                    return fixed
    return None


def _parse_osv_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def query_vulnerabilities(deps: list[DependencyQuery], session: Session) -> list[Vulnerability]:
    """Batches ``deps`` against OSV's querybatch endpoint (already filtered
    to version-PINNED dependencies -- a version range can't be queried
    against OSV, only a resolved version, see
    app/ingestion/manifests.py::extract_declared_dependencies), resolves
    full details for every unique advisory id found (``osv_cache`` first),
    and returns one ``Vulnerability`` per (dependency, advisory) pair that
    actually affects that dependency.

    Raises ``OSVQueryError`` if OSV is unreachable/erroring after retries --
    see this module's docstring for why that's deliberate, not a bug.
    """
    if not deps:
        return []

    dep_list = list(deps)
    vuln_ids_by_dep_index: dict[int, list[str]] = {}

    for batch_start in range(0, len(dep_list), OSV_BATCH_SIZE):
        batch = dep_list[batch_start : batch_start + OSV_BATCH_SIZE]
        payload = {
            "queries": [
                {
                    "package": {"name": d.package_name, "ecosystem": d.ecosystem},
                    "version": d.version,
                }
                for d in batch
            ]
        }
        response = _with_retries(
            lambda p=payload: _post_json(OSV_QUERYBATCH_URL, p),
            description=f"querybatch ({len(batch)} deps)",
        )
        results = response.get("results", [])
        for offset, result in enumerate(results):
            ids = [v["id"] for v in (result.get("vulns") or []) if "id" in v]
            if ids:
                vuln_ids_by_dep_index[batch_start + offset] = ids

    unique_ids = sorted({vid for ids in vuln_ids_by_dep_index.values() for vid in ids})
    details_by_id: dict[str, dict] = {}
    for osv_id in unique_ids:
        cached = session.get(OsvCache, osv_id)
        if cached is not None:
            details_by_id[osv_id] = cached.data
            continue
        data = _with_retries(
            lambda oid=osv_id: _get_json(OSV_VULN_URL_TEMPLATE.format(osv_id=oid)),
            description=f"vulns/{osv_id}",
        )
        details_by_id[osv_id] = data
        session.add(OsvCache(osv_id=osv_id, data=data, fetched_at=datetime.now(UTC)))
        session.flush()

    vulnerabilities: list[Vulnerability] = []
    for index, dep in enumerate(dep_list):
        for osv_id in vuln_ids_by_dep_index.get(index, []):
            vuln_data = details_by_id.get(osv_id)
            if vuln_data is None:
                continue
            severity, cvss_score = _extract_severity(vuln_data)
            vulnerabilities.append(
                Vulnerability(
                    ecosystem=dep.ecosystem,
                    package_name=dep.package_name,
                    version=dep.version,
                    osv_id=osv_id,
                    aliases=[a for a in (vuln_data.get("aliases") or []) if isinstance(a, str)],
                    severity=severity,
                    cvss_score=cvss_score,
                    summary=vuln_data.get("summary") or vuln_data.get("details") or "",
                    fixed_version=_extract_fixed_version(
                        vuln_data, dep.ecosystem, dep.package_name
                    ),
                    published_at=_parse_osv_datetime(vuln_data.get("published")),
                    is_direct=dep.is_direct,
                )
            )
    return vulnerabilities
