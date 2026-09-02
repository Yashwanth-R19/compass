"""Builds ``app/baseline/corpus_breakpoints.json`` from the curated
repository list (session 14, Part C.2) -- run as::

    python -m app.baseline.build_corpus                 # the whole list
    python -m app.baseline.build_corpus --limit 5        # first N only (smoke test)
    python -m app.baseline.build_corpus --only owner/name owner2/name2

For each repository: clone, run the SAME pipeline every real analysis runs
(``app.jobs.runner.run_ingestion_job``, unchanged -- this script duplicates
no pipeline logic, same discipline every other transport in this codebase
already follows), read the resulting per-file/per-repo metrics, accumulate
them into the running distribution, then delete the repository's Facts
(``app.db.wipe.wipe_facts``) and Insight (``app.db.wipe.prune_run``) rows
immediately -- **STORAGE DISCIPLINE, not a nicety**: thirty repositories of
full commit history would consume a large share of a 0.5 GB Neon tier. The
``repos``/``repo_paths`` rows themselves are left behind (small, bounded,
and ``repo_paths`` is architecturally append-only -- see its docstring in
``app/db/models.py`` -- never deleted by this or any other code path); only
the two things this script's own storage budget actually cares about
(Facts and Insight, which scale with commit-history depth) are wiped.

**What this script does NOT do, on purpose**: SZZ defect labelling, a
trained classifier, transfer-learning normalization. It computes plain
percentile breakpoints (p10/p25/p50/p75/p90) per (metric, language,
size_bucket) cell -- see this module's own docstring in
``app/baseline/corpus.py`` for what "corpus" honestly means here.

Resumability (a 30-repository build WILL fail partway at least once, per
session 14's own prompt): ``--state-file`` (default
``app/baseline/.corpus_build_state.json``, gitignored -- transient local
build state, not a committed artifact) records per-repository status
(``done``/``failed``/error message) after each repository finishes,
independent of the DB -- re-running the script skips any repository already
marked ``done``.

Requires a real ``DATABASE_URL`` (this script opens the SAME ``SessionLocal``
every other transport uses -- app/db/base.py) and real outbound network
access (it clones real GitHub repositories). Point it at a DISPOSABLE
database when smoke-testing, never blindly at a production database you
care about, even though this script cleans up after itself -- see the
module docstring above and CLAUDE.md's "Corpus baseline" section.
"""

from __future__ import annotations

import argparse
import json
import logging
import statistics
import sys
import uuid
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml
from sqlalchemy import select, text

from app.baseline.heuristic import size_bucket_for
from app.db.base import SessionLocal
from app.db.models import (
    Coupling,
    File,
    FileMetrics,
    Health,
    Job,
    JobStatus,
    Repo,
    RepoPassport,
    RepoStatus,
)
from app.db.wipe import prune_run, wipe_facts
from app.jobs.runner import run_ingestion_job

logger = logging.getLogger(__name__)

CORPUS_REPOS_YAML = Path(__file__).parent / "corpus_repos.yaml"
DEFAULT_OUTPUT_PATH = Path(__file__).parent / "corpus_breakpoints.json"
DEFAULT_STATE_PATH = Path(__file__).parent / ".corpus_build_state.json"

MAX_DB_SIZE_BYTES = int(0.4 * 1024**3)
"""Session 14, Known Hazard #2: abort BEFORE crossing this rather than
finding out the hard way that a Neon free tier's 0.5 GB is gone. Checked
after every repository, not just at the end."""

BREAKPOINT_METRICS = (
    "churn_total",
    "churn_weighted",
    "complexity",
    "current_loc",
    "commit_count",
    "max_coupling_degree",
    "risk_score",
    "health_score",
    "onboarding_difficulty",
    "test_cochange_ratio",
)


def _owner_name_from_url(url: str) -> tuple[str, str]:
    """Best-effort owner/name extraction, same shape as
    ``app/api/repos.py::_parse_owner_name``. A real corpus entry is always a
    ``github.com`` URL with a clean two-segment path; a local filesystem
    path (used only by ``tests/test_build_corpus.py``'s fixture repo, never
    a real corpus entry) falls back to the directory name with a fixed
    "local" owner placeholder, since a bare path has no genuine owner/name
    structure to parse."""
    parsed = urlparse(url)
    if parsed.scheme in ("http", "https"):
        path = parsed.path.strip("/")
        if path.endswith(".git"):
            path = path[: -len(".git")]
        parts = [p for p in path.split("/") if p]
        if len(parts) >= 2:
            return parts[0], parts[1]
    return "local", Path(url).name or "repo"


def _database_size_bytes(session) -> int:
    return session.execute(text("SELECT pg_database_size(current_database())")).scalar_one()


def _load_repo_list(only: list[str] | None, limit: int | None) -> list[dict[str, str]]:
    data = yaml.safe_load(CORPUS_REPOS_YAML.read_text(encoding="utf-8"))
    repos = data["repositories"]
    if only:
        wanted = {o.lower() for o in only}
        repos = [r for r in repos if r["url"].lower().rstrip("/").endswith(tuple(wanted))]
    if limit is not None:
        repos = repos[:limit]
    return repos


def _load_state(path: Path) -> dict[str, Any]:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def _save_state(path: Path, state: dict[str, Any]) -> None:
    path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def _max_coupling_by_path_id(session, repo_id: uuid.UUID, run_id: uuid.UUID) -> dict[int, float]:
    rows = session.execute(
        select(Coupling.path_a_id, Coupling.path_b_id, Coupling.coupling_degree).where(
            Coupling.repo_id == repo_id, Coupling.analysis_run_id == run_id
        )
    ).all()
    out: dict[int, float] = {}
    for a, b, degree in rows:
        out[a] = max(out.get(a, 0.0), degree)
        out[b] = max(out.get(b, 0.0), degree)
    return out


def _accumulate_one_repo(
    session, repo: Repo, run_id: uuid.UUID, accumulator: dict[tuple[str, str, str], list[float]]
) -> tuple[str, int, int]:
    """Reads this repo's just-computed per-file/per-repo metrics and adds
    them to ``accumulator`` (keyed ``(metric, language, size_bucket)``),
    tagging every value with the REPO's OWN dominant language/size_bucket --
    the same bucketing key ``GET /repos/{id}/benchmark`` looks values up by,
    so build-time and read-time buckets agree. Returns
    ``(dominant_language, size_bucket, file_count)`` for logging.
    """
    files = session.scalars(
        select(File).where(File.repo_id == repo.id, File.is_deleted.is_(False))
    ).all()
    if not files:
        return "other", "small", 0

    dominant_language = Counter(f.language for f in files).most_common(1)[0][0]
    size_bucket = size_bucket_for(len(files))
    max_coupling = _max_coupling_by_path_id(session, repo.id, run_id)

    def _add(metric: str, values: list[float]) -> None:
        accumulator[(metric, dominant_language, size_bucket)].extend(values)

    _add("churn_total", [float(f.churn_total) for f in files])
    _add("churn_weighted", [f.churn_weighted for f in files])
    _add("complexity", [f.complexity for f in files])
    _add("current_loc", [float(f.current_loc) for f in files])
    _add("commit_count", [float(f.commit_count) for f in files])
    _add("max_coupling_degree", [max_coupling.get(f.path_id, 0.0) for f in files])

    file_metrics = session.scalars(
        select(FileMetrics).where(FileMetrics.analysis_run_id == run_id)
    ).all()
    _add("risk_score", [fm.risk_score for fm in file_metrics if fm.risk_score is not None])
    _add(
        "test_cochange_ratio",
        [fm.test_cochange_ratio for fm in file_metrics if fm.test_cochange_ratio is not None],
    )

    health = session.scalar(select(Health).where(Health.analysis_run_id == run_id))
    if health is not None:
        _add("health_score", [health.score])

    passport = session.scalar(select(RepoPassport).where(RepoPassport.analysis_run_id == run_id))
    if passport is not None:
        _add("onboarding_difficulty", [passport.onboarding_difficulty])

    return dominant_language, size_bucket, len(files)


def build_corpus(
    *,
    only: list[str] | None = None,
    limit: int | None = None,
    output_path: Path = DEFAULT_OUTPUT_PATH,
    state_path: Path = DEFAULT_STATE_PATH,
    repos: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """``repos`` overrides reading ``corpus_repos.yaml`` entirely when given
    -- used by ``tests/test_build_corpus.py`` to exercise the real
    clone-run-accumulate-wipe pipeline against a tiny LOCAL fixture repo
    (same pattern ``tests/test_ingestion.py`` already uses) instead of the
    30 real, network-hosted, curated repositories."""
    entries = repos if repos is not None else _load_repo_list(only, limit)
    state = _load_state(state_path)

    # accumulator[(metric, language, size_bucket)] -> list of raw values
    accumulator: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    # cell_repo_counts[(metric, language, size_bucket)] -> set of repo URLs
    # that contributed at least one value -- n_repos for the honesty fields.
    cell_repo_counts: dict[tuple[str, str, str], set[str]] = defaultdict(set)

    # Re-hydrate the accumulator from any repositories already marked "done"
    # in a PREVIOUS run of this script, so resuming after a partial failure
    # doesn't lose earlier repositories' contributions -- their raw values
    # are stored in the state file precisely so this is possible without
    # re-cloning anything.
    for url, entry in state.items():
        if entry.get("status") == "done" and "contribution" in entry:
            for key_str, values in entry["contribution"].items():
                metric, language, size_bucket = key_str.split("|", 2)
                key = (metric, language, size_bucket)
                accumulator[key].extend(values)
                if values:
                    cell_repo_counts[key].add(url)

    for entry in entries:
        url = entry["url"]
        if state.get(url, {}).get("status") == "done":
            logger.info("skip (already done): %s", url)
            continue

        session = SessionLocal()
        try:
            size_before = _database_size_bytes(session)
            logger.info("db size before %s: %.1f MB", url, size_before / 1024**2)

            owner, name = _owner_name_from_url(url)
            repo = session.scalar(select(Repo).where(Repo.url == url))
            if repo is None:
                repo = Repo(url=url, owner=owner, name=name, status=RepoStatus.pending)
                session.add(repo)
                session.flush()
            job = Job(repo_id=repo.id, job_type="corpus_build", status=JobStatus.queued, progress=0)
            session.add(job)
            session.commit()

            run_ingestion_job(repo.id, job.id, worker_mode="inline")

            session.refresh(repo)
            if repo.current_run_id is None:
                raise RuntimeError(f"ingestion did not reach a ready run for {url}")
            run_id = repo.current_run_id

            contribution: dict[tuple[str, str, str], list[float]] = defaultdict(list)
            dominant_language, size_bucket, file_count = _accumulate_one_repo(
                session, repo, run_id, contribution
            )
            for key, values in contribution.items():
                accumulator[key].extend(values)
                if values:
                    cell_repo_counts[key].add(url)

            wipe_facts(repo.id, session)
            prune_run(run_id, session)
            session.commit()

            size_after = _database_size_bytes(session)
            logger.info("db size after cleanup %s: %.1f MB", url, size_after / 1024**2)

            state[url] = {
                "status": "done",
                "language": dominant_language,
                "size_bucket": size_bucket,
                "file_count": file_count,
                "finished_at": datetime.now(UTC).isoformat(),
                "contribution": {
                    "|".join(key): values for key, values in contribution.items() if values
                },
            }
            _save_state(state_path, state)

            if size_after > MAX_DB_SIZE_BYTES:
                raise RuntimeError(
                    f"database size {size_after / 1024**2:.1f} MB exceeds the "
                    f"{MAX_DB_SIZE_BYTES / 1024**2:.0f} MB budget after {url} -- aborting build "
                    "before the next repository. Check for a leak in wipe_facts/prune_run."
                )
        except Exception as exc:
            session.rollback()
            logger.warning("build failed for %s: %r", url, exc)
            state[url] = {"status": "failed", "error": str(exc)}
            _save_state(state_path, state)
            raise
        finally:
            session.close()

    breakpoints = _compute_breakpoints(accumulator, cell_repo_counts)
    output = {
        "generated_at": datetime.now(UTC).isoformat(),
        "metrics": list(BREAKPOINT_METRICS),
        "cells": breakpoints,
    }
    output_path.write_text(json.dumps(output, indent=2, sort_keys=True), encoding="utf-8")
    logger.info("wrote %d breakpoint cells to %s", len(breakpoints), output_path)
    return output


def _compute_breakpoints(
    accumulator: dict[tuple[str, str, str], list[float]],
    cell_repo_counts: dict[tuple[str, str, str], set[str]],
) -> list[dict[str, Any]]:
    cells = []
    for (metric, language, size_bucket), values in sorted(accumulator.items()):
        if not values:
            continue
        ordered = sorted(values)

        def _pct(p: float, ordered: list[float] = ordered) -> float:
            n = len(ordered)
            idx = min(n - 1, max(0, round(p * (n - 1))))
            return ordered[idx]

        cells.append(
            {
                "metric": metric,
                "language": language,
                "size_bucket": size_bucket,
                "p10": _pct(0.10),
                "p25": _pct(0.25),
                "p50": statistics.median(ordered),
                "p75": _pct(0.75),
                "p90": _pct(0.90),
                "n_repos": len(cell_repo_counts[(metric, language, size_bucket)]),
                "n_files": len(values),
            }
        )
    return cells


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Build the Compass corpus baseline")
    parser.add_argument("--limit", type=int, default=None, help="Only build the first N repos")
    parser.add_argument(
        "--only", nargs="*", default=None, help="Only these repos (owner/name, space-separated)"
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--state-file", type=Path, default=DEFAULT_STATE_PATH)
    args = parser.parse_args(argv)

    build_corpus(
        only=args.only, limit=args.limit, output_path=args.output, state_path=args.state_file
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
