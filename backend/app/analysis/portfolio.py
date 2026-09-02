"""Portfolio aggregation (session 14, Part B) -- pooling metrics ACROSS a
user's own repositories, the answer to "all my repositories are small"
(master-context.md sec 4/6): weak signal in one repository becomes strong
pooled signal across an account.

**Deliberately under ``app/analysis/``, not ``app/engines/``.** This is the
one distinction this module exists to make loud: it operates across
repositories for a user, has no ``run_id`` (it spans several), and is never
run as a pipeline stage -- ``app/jobs/stages.py`` has no reference to it and
must never gain one (session 14 Known Hazard #7). Every ``compute_*``
function here is a pure read over data other engines already computed and
persisted; nothing here mutates ``coupling``/``file_metrics``/``findings``/
etc., and nothing here is scoped to one ``analysis_run_id``.

Storage: ``portfolio_cache`` (``app/db/models.py::PortfolioCache``) is a
recompute-on-demand cache with a 10-minute TTL, not a history table -- this
is a derived view over data that already exists elsewhere, not a new fact
or a new per-run insight, which is also why it appears in NEITHER
``app/db/wipe.py::wipe_facts`` NOR ``prune_run``: it isn't scoped to a repo
or a run at all, only to a user, and a stale cache row simply recomputes
itself past its TTL regardless of what happens to any one repo underneath.

**Every pooled percentile/distribution this module returns is relative to
the user's OWN repositories, never a general benchmark** -- see
``app/baseline/corpus.py``/``app/api/portfolio.py``'s ``GET
/repos/{id}/benchmark`` (Part D) for the real cross-project corpus
comparison. Conflating the two is a meaningful overclaim (session 14's own
framing) -- every field this module produces is named/labelled
accordingly, and the frontend must render it that way too
(``frontend/src/pages/PortfolioPage.tsx``).
"""

from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analysis.identities import is_bot_name, resolve_identities
from app.db.models import (
    Commit,
    Coupling,
    DependencyDeclared,
    File,
    FileMetrics,
    Finding,
    Health,
    PortfolioCache,
    Repo,
    RepoPassport,
    Severity,
    TruckFactor,
    Vulnerability,
)

PORTFOLIO_CACHE_TTL_SECONDS = 600
"""Recompute-on-demand, not stored history (Part B: "recompute on demand
with a 10-minute cache rather than storing history -- this is a derived
view over data you already have")."""

MAX_SHARED_DEPENDENCIES = 20
MAX_VULNERABLE_SHARED_DEPENDENCIES = 20
DORMANT_AFTER_DAYS = 180
"""Same threshold PassportEngine's own DORMANT_AFTER_DAYS uses
(app/engines/passport.py) -- reused as a plain literal here rather than
imported, since importing an engine module from app/analysis/ would blur
exactly the analysis-vs-engine line this module's own docstring insists on;
both values are HEURISTIC and happen to agree, not coupled."""


def _five_number_summary(values: list[float]) -> dict[str, float | int]:
    """min/p25/median/p75/max plus count -- a fixed-size summary of a
    metric pooled across every repository, rather than embedding a raw,
    unbounded array of every file's/repo's value in the cached JSONB blob
    (the same anti-unbounded-payload discipline every capped list in this
    codebase already follows, plan/RULES.md sec 12)."""
    if not values:
        return {"count": 0, "min": 0.0, "p25": 0.0, "median": 0.0, "p75": 0.0, "max": 0.0}
    ordered = sorted(values)
    n = len(ordered)

    def _pct(p: float) -> float:
        idx = min(n - 1, max(0, round(p * (n - 1))))
        return ordered[idx]

    return {
        "count": n,
        "min": ordered[0],
        "p25": _pct(0.25),
        "median": _pct(0.50),
        "p75": _pct(0.75),
        "max": ordered[-1],
    }


def _pooled_distribution(
    values_by_repo: dict[uuid.UUID, float],
) -> dict[str, Any]:
    """A pooled metric's five-number summary PLUS one value per repository
    (``by_repo``, keyed by repo id as a string) -- what lets the frontend
    "mark the current repository" against the pooled distribution (Part E)
    without embedding every underlying file-level value."""
    return {
        "summary": _five_number_summary(list(values_by_repo.values())),
        "by_repo": {str(k): v for k, v in values_by_repo.items()},
    }


def compute_portfolio(session: Session, user_id: uuid.UUID) -> dict[str, Any]:
    """The full portfolio payload for one user, computed fresh (no caching
    here -- see ``get_or_compute_portfolio`` below for the TTL-cached
    wrapper ``GET /portfolio`` actually calls).

    Scoped to repositories the user OWNS (``repos.owner_user_id``) that have
    a ``ready`` current run (``current_run_id`` set) -- a repo still
    analyzing, or one that has never finished, contributes nothing yet.
    """
    repos = list(
        session.scalars(
            select(Repo).where(Repo.owner_user_id == user_id, Repo.current_run_id.is_not(None))
        )
    )
    if not repos:
        return _empty_portfolio()

    repo_ids = [r.id for r in repos]
    run_ids = [r.current_run_id for r in repos if r.current_run_id is not None]
    repo_by_id = {r.id: r for r in repos}

    totals = _compute_totals(session, repo_ids, repos)
    language_activity = _compute_language_activity(session, repo_ids)
    distributions = _compute_pooled_distributions(session, repo_ids, run_ids)
    cross_repo = _compute_cross_repo_patterns(session, repo_ids, run_ids)
    health = _compute_portfolio_health(session, repo_ids, run_ids, repo_by_id)
    growth = _compute_growth(session, repo_ids)

    return {
        "repository_count": len(repos),
        "totals": totals,
        "language_activity_by_year": language_activity,
        "pooled_distributions": distributions,
        "cross_repo_patterns": cross_repo,
        "portfolio_health": health,
        "growth": growth,
    }


def _empty_portfolio() -> dict[str, Any]:
    return {
        "repository_count": 0,
        "totals": {
            "repositories": 0,
            "files": 0,
            "loc": 0,
            "commits": 0,
            "contributors": 0,
        },
        "language_activity_by_year": {},
        "pooled_distributions": {
            metric: _pooled_distribution({})
            for metric in (
                "risk_score",
                "complexity",
                "max_coupling_degree",
                "health_score",
                "onboarding_difficulty",
            )
        },
        "cross_repo_patterns": {"shared_dependencies": [], "vulnerable_shared_dependencies": []},
        "portfolio_health": {
            "average_health_score": None,
            "dormant_repository_ids": [],
            "truck_factor_one_repository_ids": [],
            "repositories_with_unresolved_high_severity_ids": [],
        },
        "growth": {"commits_per_month": {}, "repositories_started_per_year": {}},
    }


def _compute_totals(
    session: Session, repo_ids: list[uuid.UUID], repos: list[Repo]
) -> dict[str, Any]:
    file_rows = session.execute(
        select(File.current_loc).where(File.repo_id.in_(repo_ids), File.is_deleted.is_(False))
    ).all()
    total_files = len(file_rows)
    total_loc = sum(row[0] for row in file_rows)
    total_commits = sum(r.commit_count for r in repos)

    # Contributor dedup ACROSS repositories -- the whole reason this lives
    # here rather than summing each repo's own contributors.commit_count:
    # session 05's resolve_identities is re-run over the UNION of every
    # repo's raw (author_name, author_email) commit pairs, so the same
    # human under a work email in one repo and a personal email in another
    # collapses to one identity, not two (Part B: "that dedup is what makes
    # the pooling meaningful rather than a sum").
    pairs = session.execute(
        select(Commit.author_name, Commit.author_email).where(Commit.repo_id.in_(repo_ids))
    ).all()
    contributor_count = 0
    if pairs:
        identity_map = resolve_identities([(name, email) for name, email in pairs])
        # A cluster counts as a bot (excluded from the human contributor
        # total, matching the "knowledge distribution" framing every other
        # per-person feature in this codebase uses) when ANY member's name
        # looks like a bot -- same conservative "a bot rarely also collides
        # with a human's real identity under these merge rules" reasoning
        # session 05's ExpertiseEngine already applies to DOA.
        bot_clusters: set[int] = set()
        for (name, _email), cluster_id in identity_map.items():
            if is_bot_name(name):
                bot_clusters.add(cluster_id)
        human_clusters = {cid for cid in identity_map.values() if cid not in bot_clusters}
        contributor_count = len(human_clusters)

    return {
        "repositories": len(repos),
        "files": total_files,
        "loc": total_loc,
        "commits": total_commits,
        "contributors": contributor_count,
    }


def _compute_language_activity(session: Session, repo_ids: list[uuid.UUID]) -> dict[str, Any]:
    """Lines ADDED per (year, language), from ``commits.added_lines`` paired
    with the CURRENT ``files.language`` for each touched path (Part B: "from
    files.language and commit dates"). This is an activity signal -- how
    much a language was being written in a given year -- not a
    reconstruction of "how many lines of language X existed on disk in year
    Y" (that would need the tree checked out at every historical point,
    which this product deliberately does not do anywhere, see
    ``app/engines/timeline.py``'s own honesty constraint). Labelled
    "added_lines" throughout, never "loc", for exactly that reason.
    """
    path_language: dict[int, str] = {
        path_id: language
        for path_id, language in session.execute(
            select(File.path_id, File.language).where(File.repo_id.in_(repo_ids))
        ).all()
    }
    if not path_language:
        return {}

    activity: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    rows = session.execute(
        select(Commit.committed_at, Commit.changed_path_ids, Commit.added_lines).where(
            Commit.repo_id.in_(repo_ids)
        )
    ).all()
    for committed_at, changed_path_ids, added_lines in rows:
        year = str(committed_at.year)
        for path_id, added in zip(changed_path_ids, added_lines, strict=False):
            language = path_language.get(path_id)
            if language is None:
                continue
            activity[year][language] += added

    return {year: dict(langs) for year, langs in sorted(activity.items())}


def _compute_pooled_distributions(
    session: Session, repo_ids: list[uuid.UUID], run_ids: list[uuid.UUID]
) -> dict[str, Any]:
    """Each of the five pooled metrics reduces to ONE VALUE PER REPO (the
    repo's own mean across its files/pairs, for the per-file metrics) before
    pooling -- pooling raw per-file rows directly would let a single huge
    repository dominate the distribution just by having more files, which
    is not "positioning a repository against your other repositories", it's
    "positioning a file against every file you've ever written"."""

    def _mean_per_repo(
        rows: list[tuple[uuid.UUID, float | None]],
    ) -> dict[uuid.UUID, float]:
        buckets: dict[uuid.UUID, list[float]] = defaultdict(list)
        for repo_id, value in rows:
            if value is not None:
                buckets[repo_id].append(value)
        return {repo_id: sum(vals) / len(vals) for repo_id, vals in buckets.items()}

    risk_rows = session.execute(
        select(FileMetrics.repo_id, FileMetrics.risk_score).where(
            FileMetrics.analysis_run_id.in_(run_ids)
        )
    ).all()
    complexity_rows = session.execute(
        select(File.repo_id, File.complexity).where(
            File.repo_id.in_(repo_ids), File.is_deleted.is_(False)
        )
    ).all()
    coupling_rows = session.execute(
        select(Coupling.repo_id, Coupling.coupling_degree).where(
            Coupling.analysis_run_id.in_(run_ids)
        )
    ).all()
    health_rows = session.execute(
        select(Health.repo_id, Health.score).where(Health.analysis_run_id.in_(run_ids))
    ).all()
    difficulty_rows = session.execute(
        select(RepoPassport.repo_id, RepoPassport.onboarding_difficulty).where(
            RepoPassport.analysis_run_id.in_(run_ids)
        )
    ).all()

    return {
        "risk_score": _pooled_distribution(_mean_per_repo(risk_rows)),
        "complexity": _pooled_distribution(_mean_per_repo(complexity_rows)),
        "max_coupling_degree": _pooled_distribution(_mean_per_repo(coupling_rows)),
        "health_score": _pooled_distribution(_mean_per_repo(health_rows)),
        "onboarding_difficulty": _pooled_distribution(_mean_per_repo(difficulty_rows)),
    }


def _compute_cross_repo_patterns(
    session: Session, repo_ids: list[uuid.UUID], run_ids: list[uuid.UUID]
) -> dict[str, Any]:
    dep_rows = session.execute(
        select(
            DependencyDeclared.ecosystem,
            DependencyDeclared.package_name,
            DependencyDeclared.repo_id,
        ).where(DependencyDeclared.repo_id.in_(repo_ids))
    ).all()
    by_package: dict[tuple[str, str], set[uuid.UUID]] = defaultdict(set)
    for ecosystem, package_name, repo_id in dep_rows:
        by_package[(ecosystem, package_name)].add(repo_id)

    shared = sorted(
        (
            {
                "ecosystem": ecosystem,
                "package_name": package_name,
                "repository_ids": sorted(str(r) for r in repos_set),
                "repository_count": len(repos_set),
            }
            for (ecosystem, package_name), repos_set in by_package.items()
            if len(repos_set) >= 2
        ),
        key=lambda d: (-d["repository_count"], d["ecosystem"], d["package_name"]),
    )[:MAX_SHARED_DEPENDENCIES]
    shared_total = sum(1 for repos_set in by_package.values() if len(repos_set) >= 2)

    vuln_rows = session.execute(
        select(
            Vulnerability.ecosystem,
            Vulnerability.package_name,
            Vulnerability.repo_id,
            Vulnerability.osv_id,
            Vulnerability.severity,
        ).where(Vulnerability.analysis_run_id.in_(run_ids))
    ).all()
    vuln_by_package: dict[tuple[str, str], dict[str, Any]] = {}
    for ecosystem, package_name, repo_id, osv_id, severity in vuln_rows:
        key = (ecosystem, package_name)
        entry = vuln_by_package.setdefault(
            key,
            {
                "ecosystem": ecosystem,
                "package_name": package_name,
                "repository_ids": set(),
                "osv_ids": set(),
                "max_severity": severity,
            },
        )
        entry["repository_ids"].add(repo_id)
        entry["osv_ids"].add(osv_id)
        if _severity_rank(severity) > _severity_rank(entry["max_severity"]):
            entry["max_severity"] = severity

    vulnerable_shared = sorted(
        (
            {
                "ecosystem": e["ecosystem"],
                "package_name": e["package_name"],
                "repository_ids": sorted(str(r) for r in e["repository_ids"]),
                "repository_count": len(e["repository_ids"]),
                "osv_ids": sorted(e["osv_ids"]),
                "max_severity": e["max_severity"],
            }
            for e in vuln_by_package.values()
            if len(e["repository_ids"]) >= 2
        ),
        key=lambda d: (-d["repository_count"], d["ecosystem"], d["package_name"]),
    )[:MAX_VULNERABLE_SHARED_DEPENDENCIES]
    vulnerable_shared_total = sum(
        1 for e in vuln_by_package.values() if len(e["repository_ids"]) >= 2
    )

    return {
        "shared_dependencies": shared,
        "shared_dependencies_total": shared_total,
        "vulnerable_shared_dependencies": vulnerable_shared,
        "vulnerable_shared_dependencies_total": vulnerable_shared_total,
    }


def _severity_rank(severity: str) -> int:
    return {"low": 0, "unknown": 0, "med": 1, "high": 2}.get(severity, 0)


def _compute_portfolio_health(
    session: Session,
    repo_ids: list[uuid.UUID],
    run_ids: list[uuid.UUID],
    repo_by_id: dict[uuid.UUID, Repo],
) -> dict[str, Any]:
    health_scores = [
        score
        for (score,) in session.execute(
            select(Health.score).where(Health.analysis_run_id.in_(run_ids))
        ).all()
    ]
    average_health = sum(health_scores) / len(health_scores) if health_scores else None

    last_commit_by_repo: dict[uuid.UUID, datetime] = {
        repo_id: last
        for repo_id, last in session.execute(
            select(Commit.repo_id, func.max(Commit.committed_at))
            .where(Commit.repo_id.in_(repo_ids))
            .group_by(Commit.repo_id)
        ).all()
    }
    cutoff = datetime.now(UTC) - timedelta(days=DORMANT_AFTER_DAYS)
    dormant_ids = sorted(
        str(repo_id)
        for repo_id, last in last_commit_by_repo.items()
        if last is not None and last < cutoff
    )

    truck_factor_one_ids = sorted(
        str(repo_id)
        for repo_id, value in session.execute(
            select(TruckFactor.repo_id, TruckFactor.value).where(
                TruckFactor.analysis_run_id.in_(run_ids)
            )
        ).all()
        if value == 1
    )

    high_severity_repo_ids = sorted(
        {
            str(repo_id)
            for (repo_id,) in session.execute(
                select(Finding.repo_id).where(
                    Finding.analysis_run_id.in_(run_ids), Finding.severity == Severity.high
                )
            ).all()
        }
    )

    return {
        "average_health_score": average_health,
        "dormant_repository_ids": dormant_ids,
        "truck_factor_one_repository_ids": truck_factor_one_ids,
        "repositories_with_unresolved_high_severity_ids": high_severity_repo_ids,
    }


def _compute_growth(session: Session, repo_ids: list[uuid.UUID]) -> dict[str, Any]:
    rows = session.execute(
        select(Commit.repo_id, Commit.committed_at).where(Commit.repo_id.in_(repo_ids))
    ).all()

    commits_per_month: Counter[str] = Counter()
    first_commit_by_repo: dict[uuid.UUID, datetime] = {}
    for repo_id, committed_at in rows:
        month_key = f"{committed_at.year:04d}-{committed_at.month:02d}"
        commits_per_month[month_key] += 1
        current_first = first_commit_by_repo.get(repo_id)
        if current_first is None or committed_at < current_first:
            first_commit_by_repo[repo_id] = committed_at

    repos_started_per_year: Counter[str] = Counter()
    for first_commit in first_commit_by_repo.values():
        repos_started_per_year[str(first_commit.year)] += 1

    return {
        "commits_per_month": dict(sorted(commits_per_month.items())),
        "repositories_started_per_year": dict(sorted(repos_started_per_year.items())),
    }


def get_or_compute_portfolio(
    session: Session, user_id: uuid.UUID, *, force: bool = False
) -> tuple[dict[str, Any], datetime]:
    """The TTL-cached entry point ``GET /portfolio`` calls. Caller owns the
    transaction (same convention as every other function in this codebase
    that isn't itself an engine) -- commits, if any, happen at the API
    layer, not here."""
    cached = session.get(PortfolioCache, user_id)
    now = datetime.now(UTC)
    if (
        cached is not None
        and not force
        and (now - cached.computed_at).total_seconds() < PORTFOLIO_CACHE_TTL_SECONDS
    ):
        return cached.data, cached.computed_at

    data = compute_portfolio(session, user_id)
    if cached is None:
        cached = PortfolioCache(user_id=user_id, computed_at=now, data=data)
        session.add(cached)
    else:
        cached.computed_at = now
        cached.data = data
    session.flush()
    return data, now


__all__ = [
    "PORTFOLIO_CACHE_TTL_SECONDS",
    "compute_portfolio",
    "get_or_compute_portfolio",
]
