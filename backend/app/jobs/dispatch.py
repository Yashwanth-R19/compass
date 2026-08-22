"""Chooses which transport actually runs an ingestion job (session 01, Part
G): FastAPI ``BackgroundTasks`` in the same process, or a dispatched GitHub
Actions workflow run in ``COMPASS_WORKER_REPO``.

The dispatched payload carries only ``repo_id``/``run_id`` (see
``dispatch_run``'s docstring for what ``run_id`` means here) -- the worker
looks up everything else (repo URL, credentials) itself via its own database
access. There is deliberately no credentials endpoint and no job-token
concept: the two identifiers are the entire contract.
"""

import json
import logging
import urllib.error
import urllib.request
import uuid

from fastapi import BackgroundTasks
from sqlalchemy.orm import Session

from app.config import settings
from app.jobs.log_redaction import redact
from app.jobs.runner import run_ingestion_job

logger = logging.getLogger(__name__)

DISPATCH_TIMEOUT_SECONDS = 10.0
"""Short and deliberate: dispatch_run is on the POST /repos request path.
A hung GitHub API call must not hang repo creation -- a timeout here always
falls through to the inline fallback."""


def _dispatch_url() -> str:
    return f"https://api.github.com/repos/{settings.COMPASS_WORKER_REPO}/dispatches"


def _post_repository_dispatch(repo_id: uuid.UUID, run_id: uuid.UUID) -> None:
    """Raises on any failure (network, non-2xx, timeout) -- the caller
    decides what to do about it. Never includes the PAT or anything other
    than the two identifiers in a log line; see log_redaction for the
    belt-and-suspenders scrub applied to whatever does get logged."""
    payload = {
        "event_type": "compass-mine",
        "client_payload": {"repo_id": str(repo_id), "run_id": str(run_id)},
    }
    request = urllib.request.Request(
        _dispatch_url(),
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {settings.COMPASS_WORKER_PAT}",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
    )
    # repository_dispatch returns 204 on success. GitHub returns 404 for
    # BOTH "repo not found" and "PAT lacks permission" -- indistinguishable
    # from the status code alone (see DEPLOY.md's troubleshooting table).
    with urllib.request.urlopen(request, timeout=DISPATCH_TIMEOUT_SECONDS):
        pass


def dispatch_run(
    repo_id: uuid.UUID,
    run_id: uuid.UUID,
    session: Session,
    background_tasks: BackgroundTasks,
    triggered_by_user_id: uuid.UUID | None = None,
) -> str:
    """Runs the ingestion job via whichever transport ``COMPASS_WORKER_MODE``
    selects, and returns the mode actually used ("inline", "actions", or
    "inline_fallback").

    ``run_id`` here is the ``jobs.id`` row the caller already created for
    this ingestion attempt (POST /repos creates it before calling this) --
    NOT an ``analysis_runs.id``, which doesn't exist yet at this point;
    ``run_ingestion_job`` creates that row itself as its first step. It is
    named ``run_id`` at this boundary (and in the ``client_payload`` the
    Actions worker receives) because from a dispatcher's point of view it
    identifies "the run being dispatched" -- see app/jobs/worker.py's
    docstring for the same note.

    "actions" mode POSTs a ``repository_dispatch`` event carrying only
    ``repo_id``/``run_id`` to ``COMPASS_WORKER_REPO``, authenticated with
    ``COMPASS_WORKER_PAT``. If that POST fails for ANY reason (GitHub outage,
    network error, bad PAT, wrong repo name), this logs the failure (through
    the redactor) and falls back to running inline -- a GitHub Actions outage
    must never mean Compass itself is down -- and records
    ``worker_mode="inline_fallback"`` on the run so it's visible after the
    fact which path actually ran.

    ``triggered_by_user_id`` (session 02) is passed straight through to
    ``run_ingestion_job`` for the inline/inline_fallback paths, which run in
    this same process and so have the real authenticated-request context
    available. It is deliberately NOT added to the ``repository_dispatch``
    ``client_payload`` -- that payload's contract is "only the two
    identifiers" (CLAUDE.md's worker-dispatch section), and widening it to
    carry a user id too isn't worth breaking that invariant for a nullable
    audit column; "actions"-mode runs simply leave it NULL.
    """
    mode = settings.COMPASS_WORKER_MODE

    if mode == "actions":
        try:
            _post_repository_dispatch(repo_id, run_id)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            logger.warning(
                redact(
                    f"repository_dispatch failed for repo {repo_id}: {exc!r} -- "
                    "check COMPASS_WORKER_REPO and PAT scope; falling back to inline"
                )
            )
        else:
            return "actions"

        background_tasks.add_task(
            run_ingestion_job,
            repo_id,
            run_id,
            worker_mode="inline_fallback",
            triggered_by_user_id=triggered_by_user_id,
        )
        return "inline_fallback"

    background_tasks.add_task(
        run_ingestion_job,
        repo_id,
        run_id,
        worker_mode="inline",
        triggered_by_user_id=triggered_by_user_id,
    )
    return "inline"
