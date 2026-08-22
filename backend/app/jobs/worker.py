"""CLI entry point for the GitHub Actions mining worker (session 01, Part F).

Invoked as::

    python -m app.jobs.worker --repo-id <uuid> --run-id <uuid>

by ``.github/workflows/mine.yml`` after a ``repository_dispatch`` event.
Reads ``DATABASE_URL`` from the environment (never from an argument -- an
argument would show up in the public workflow's logs, see
CLAUDE.md/RULES.md's public-logs constraint) and calls the SAME
``run_ingestion_job`` the in-process (FastAPI BackgroundTasks) path calls --
this file duplicates no pipeline logic at all, which is the entire payoff of
``run_ingestion_job`` being transport-agnostic.

``--run-id`` is the ``jobs.id`` row created by ``POST /repos`` (or a
re-analysis), NOT an ``analysis_runs.id`` -- that row does not exist yet at
dispatch time, since ``run_ingestion_job`` creates it itself as its first
step. It is called "run-id" at the dispatch boundary (``app/jobs/dispatch.py``,
``client_payload``) because from a caller's perspective it identifies "the
run being dispatched", and renaming ``run_ingestion_job``'s existing
``job_id`` parameter was out of scope for this session.

Exits 0 on success, non-zero on failure. On an unhandled exception, the
error is written to the ``analysis_runs`` row (private, in the database
only) and only a generic line is printed to stdout -- the workflow
repository is public, so nothing that might contain repo content, tokens,
or connection strings may ever reach its logs.
"""

import argparse
import logging
import sys
import uuid

from app.jobs.log_redaction import install_log_redaction

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    install_log_redaction()  # before anything else runs, per the module docstring

    parser = argparse.ArgumentParser(description="Compass mining worker")
    parser.add_argument("--repo-id", required=True, type=uuid.UUID)
    parser.add_argument("--run-id", required=True, type=uuid.UUID)
    args = parser.parse_args(argv)

    # Imported after install_log_redaction() so any logging module-level
    # side effects in these imports are still subject to the filter.
    from app.jobs.runner import run_ingestion_job

    try:
        run_ingestion_job(args.repo_id, args.run_id, worker_mode="actions")
    except Exception:
        # run_ingestion_job already wrote the real error message to the
        # analysis_runs row (private, DB-only) before re-raising -- never
        # print exc details here, only a generic pointer at the record.
        logger.error("run failed, see run record")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
