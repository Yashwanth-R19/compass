"""Security & Supply Chain (session 10, Part F): secret and vulnerability
findings for the "security" INSIGHT stage (app/jobs/stages.py), the last
stage before "rank".

This module holds TWO very different things sharing one stage:

- **``fetch_and_persist_vulnerabilities``** -- NOT an ``Engine``
  (app/engines/base.py forbids network access; this function's whole job is
  an OSV.dev lookup). It reads ``dependencies_declared`` (Facts) and writes
  ``vulnerabilities`` (Insight, tagged with THIS run's ``analysis_run_id``).
  This is the one deliberate exception to "every insight stage is pure
  DB-only" in the whole pipeline -- see app/security/osv.py's module
  docstring and app/jobs/stages.py's ``optional`` stage mechanism, which is
  what keeps an OSV outage from failing anything but this one stage.
- **``SecurityEngine``** -- a proper ``Engine``: pure, DB-only, reads
  ``secret_hits`` (Facts, filtered by ``repo_id`` only -- history scanning
  doesn't depend on which run is selected) and ``vulnerabilities`` (Insight,
  filtered by THIS run's ``analysis_run_id``, just written by the function
  above earlier in the SAME stage) and emits ``category="secret"``/
  ``category="vulnerability"`` findings.

Both run inside the "security" stage's ``callables`` tuple, in this fixed
order -- the Engine must run AFTER the fetch function, since it reads the
vulnerabilities that function just persisted for this run_id.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from app.db.models import DependencyDeclared, Finding, SecretHit, Severity, Vulnerability
from app.db.paths import load_path_map
from app.engines.base import Engine
from app.engines.signature import finding_signature
from app.security.osv import DependencyQuery, query_vulnerabilities

if TYPE_CHECKING:
    from app.engines.context import RunContext

MAX_FINDINGS_PER_CATEGORY = 10
"""Anti-alert-fatigue cap (plan/RULES.md sec 12), applied independently to
"secret" and "vulnerability" findings -- "showing 10 of 47" alongside the
honest total, same discipline as every other finding-emitting engine."""

_VULN_SEVERITY: dict[str, Severity] = {
    "high": Severity.high,
    "med": Severity.med,
    "low": Severity.low,
    "unknown": Severity.low,
}
_VULN_CONFIDENCE: dict[str, float] = {"high": 0.9, "med": 0.7, "low": 0.5, "unknown": 0.3}
"""HEURISTIC (plan/RULES.md sec 3): an "unknown"-severity vulnerability
(OSV published no CVSS vector and no database_specific.severity -- see
app/security/osv.py::_extract_severity) still deserves a finding, since a
supply-chain issue with no severity data is still worth surfacing, but at
the LOWEST severity band and confidence -- never invented as anything more
precise than "we don't actually know"."""

_SEVERITY_RANK = {"high": 2, "med": 1, "low": 0, "unknown": -1}


def load_declared_dependencies(repo_id: uuid.UUID, session: Session) -> list[DependencyQuery]:
    """Version-PINNED declared dependencies only (a version range can't be
    queried against OSV -- see ``DependencyDeclared``'s docstring), deduped
    across manifests: the SAME package/version can legitimately be declared
    in more than one manifest (e.g. requirements.txt AND pyproject.toml),
    and OSV should only be asked about it once. ``is_direct`` is True for
    the dedup key if ANY declaring manifest calls it direct.
    """
    rows = session.execute(
        select(
            DependencyDeclared.ecosystem,
            DependencyDeclared.package_name,
            DependencyDeclared.version,
            DependencyDeclared.is_direct,
        ).where(DependencyDeclared.repo_id == repo_id, DependencyDeclared.version.isnot(None))
    ).all()

    dedup: dict[tuple[str, str, str], bool] = {}
    for ecosystem, package_name, version, is_direct in rows:
        key = (ecosystem, package_name, version)
        dedup[key] = dedup.get(key, False) or is_direct

    return [
        DependencyQuery(ecosystem=eco, package_name=pkg, version=ver, is_direct=direct)
        for (eco, pkg, ver), direct in sorted(dedup.items())
    ]


def fetch_and_persist_vulnerabilities(ctx: RunContext, session: Session) -> dict[str, Any]:
    """Queries OSV for every version-pinned declared dependency and persists
    the results as ``vulnerabilities`` rows tagged ``analysis_run_id=ctx.run_id``.

    Raises whatever ``query_vulnerabilities`` raises (``OSVQueryError`` on
    total OSV failure after retries) -- deliberately NOT caught here. The
    "security" stage this runs inside is ``optional=True``
    (app/jobs/stages.py), which is what turns that exception into "this one
    stage failed, the run still reaches ready" rather than failing the
    whole analysis.
    """
    deps = load_declared_dependencies(ctx.repo_id, session)
    if not deps:
        return {"dependencies_queried": 0, "vulnerabilities_found": 0}

    vulns = query_vulnerabilities(deps, session)
    if vulns:
        session.execute(
            insert(Vulnerability),
            [
                {
                    "analysis_run_id": ctx.run_id,
                    "repo_id": ctx.repo_id,
                    "ecosystem": v.ecosystem,
                    "package_name": v.package_name,
                    "version": v.version,
                    "osv_id": v.osv_id,
                    "aliases": v.aliases,
                    "severity": v.severity,
                    "cvss_score": v.cvss_score,
                    "summary": v.summary,
                    "fixed_version": v.fixed_version,
                    "published_at": v.published_at,
                    "is_direct": v.is_direct,
                }
                for v in vulns
            ],
        )

    return {"dependencies_queried": len(deps), "vulnerabilities_found": len(vulns)}


def _secret_finding_candidate(hit: SecretHit, path: str | None) -> dict[str, Any]:
    # Part F: a secret still in HEAD is HIGH; a secret only in history is
    # ALSO HIGH -- it is still fully recoverable from this repository's
    # public git history and still needs rotation. Never downgraded.
    if hit.still_in_head:
        presence = "still present in the current version of this file"
    else:
        presence = (
            "no longer present in the current tree, but still recoverable from this "
            "repository's public commit history -- deleting a file does not remove it "
            "from git history, and this secret still needs to be rotated"
        )
    location = f" in {path}" if path else ""
    return {
        "category": "secret",
        "severity": Severity.high,
        "confidence": 0.9,
        "path_id": hit.path_id,
        "evidence_sha": hit.commit_sha,
        "title": f"{hit.description} committed{location}",
        "detail": (
            f"{hit.description} found in commit {hit.commit_sha[:8]}{location}. "
            f"It is {presence}."
        ),
        "signature": finding_signature("secret", f"{hit.rule_id}|{hit.fingerprint}"),
        "_sort_key": (1 if hit.still_in_head else 0, hit.committed_at.isoformat()),
    }


def _vulnerability_finding_candidate(v: Vulnerability) -> dict[str, Any]:
    fix_note = (
        f" Fix available: upgrade to {v.fixed_version}."
        if v.fixed_version
        else " No fixed version has been published yet."
    )
    unknown_note = (
        " Severity could not be determined from OSV data." if v.severity == "unknown" else ""
    )
    return {
        "category": "vulnerability",
        "severity": _VULN_SEVERITY[v.severity],
        "confidence": _VULN_CONFIDENCE[v.severity],
        "path_id": None,
        "evidence_sha": None,
        "title": f"{v.osv_id}: {v.package_name}@{v.version}",
        "detail": (v.summary or "No summary published.") + fix_note + unknown_note,
        "signature": finding_signature("vulnerability", f"{v.osv_id}|{v.package_name}"),
        "_sort_key": (_SEVERITY_RANK[v.severity], v.cvss_score or 0.0),
    }


class SecurityEngine(Engine):
    """Emits ``category="secret"``/``category="vulnerability"`` findings
    from the ``secret_hits``/``vulnerabilities`` rows already persisted
    earlier this stage. Pure DB-only, no network -- everything network-
    bound already happened in ``fetch_and_persist_vulnerabilities`` (or, for
    secrets, in the earlier "secrets" FACT stage's ``scan_history`` call).
    """

    def run(self, ctx: RunContext, session: Session) -> dict[str, Any]:
        repo_id, run_id = ctx.repo_id, ctx.run_id

        secret_rows = session.scalars(select(SecretHit).where(SecretHit.repo_id == repo_id)).all()
        vuln_rows = session.scalars(
            select(Vulnerability).where(Vulnerability.analysis_run_id == run_id)
        ).all()

        path_map = load_path_map(repo_id, session)

        secret_candidates = [
            {
                "analysis_run_id": run_id,
                "repo_id": repo_id,
                **_secret_finding_candidate(
                    hit, path_map.get(hit.path_id) if hit.path_id is not None else None
                ),
            }
            for hit in secret_rows
        ]
        vuln_candidates = [
            {"analysis_run_id": run_id, "repo_id": repo_id, **_vulnerability_finding_candidate(v)}
            for v in vuln_rows
        ]

        secret_total = len(secret_candidates)
        vuln_total = len(vuln_candidates)

        secret_candidates.sort(key=lambda f: f["_sort_key"], reverse=True)
        vuln_candidates.sort(key=lambda f: f["_sort_key"], reverse=True)

        kept_secrets = secret_candidates[:MAX_FINDINGS_PER_CATEGORY]
        kept_vulns = vuln_candidates[:MAX_FINDINGS_PER_CATEGORY]
        for rank, f in enumerate(kept_secrets):
            f["rank"] = rank
            del f["_sort_key"]
        for rank, f in enumerate(kept_vulns):
            f["rank"] = rank
            del f["_sort_key"]

        kept = kept_secrets + kept_vulns
        if kept:
            session.execute(insert(Finding), kept)

        return {
            "secrets_found": secret_total,
            "secrets_still_in_head": sum(1 for h in secret_rows if h.still_in_head),
            "vulnerabilities_found": vuln_total,
            "findings_emitted": len(kept),
        }
