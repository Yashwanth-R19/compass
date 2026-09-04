"""Showcase repository management (session 16, Part A) -- run as::

    python -m app.scripts.showcase add <url> --rank N
    python -m app.scripts.showcase list
    python -m app.scripts.showcase remove <url>

``add`` runs the exact same pipeline every real submission runs
(``app.jobs.runner.run_ingestion_job``, unchanged -- no duplicated pipeline
logic, the same discipline ``app/baseline/build_corpus.py`` already
established for a different console script), then pins the repository
(``repos.is_showcase = True``) and pre-generates its one repo-level
narrative (``pregenerate_narratives``, called as a plain function -- this is
a console script in the same process, not an HTTP client of its own API) so
no visitor of the showcase page ever triggers a live LLM call.

**The secret check is not optional** (session 16 Known Hazard #6). ``add``
always prints every ``secret_hits`` row with ``still_in_head=True`` it finds,
and refuses to pin the repository if any exist unless the operator passes
``--confirm-no-live-secrets`` after having actually read them -- publishing a
showcase repository that surfaces a live, unremediated credential would be
publishing a vulnerability, not a demo.
"""

from __future__ import annotations

import argparse
import sys
from urllib.parse import urlparse

from sqlalchemy import select

from app.api.narrative import pregenerate_narratives
from app.db.base import SessionLocal
from app.db.models import Job, JobStatus, Repo, RepoStatus, SecretHit
from app.ingestion.guardrails import validate_repo_url
from app.jobs.runner import run_ingestion_job


def _owner_name_from_url(url: str) -> tuple[str, str]:
    path = urlparse(url).path.strip("/")
    if path.endswith(".git"):
        path = path[: -len(".git")]
    parts = [p for p in path.split("/") if p]
    if len(parts) < 2:
        raise ValueError(f"Could not parse owner/name from {url!r}.")
    return parts[0], parts[1]


def _next_rank(session) -> int:
    ranks = session.scalars(
        select(Repo.showcase_rank).where(Repo.is_showcase.is_(True), Repo.showcase_rank.isnot(None))
    ).all()
    return (max(ranks) + 1) if ranks else 1


def cmd_add(url: str, rank: int | None, *, confirm_no_live_secrets: bool) -> int:
    validate_repo_url(url)
    owner, name = _owner_name_from_url(url)

    session = SessionLocal()
    try:
        repo = session.scalar(select(Repo).where(Repo.url == url))
        if repo is None:
            repo = Repo(url=url, owner=owner, name=name, status=RepoStatus.pending)
            session.add(repo)
        session.commit()
        session.refresh(repo)

        job = Job(repo_id=repo.id, job_type="showcase_add", status=JobStatus.queued, progress=0)
        session.add(job)
        session.commit()

        print(f"Analysing {owner}/{name} ({url}) ...")
        run_ingestion_job(repo.id, job.id, worker_mode="inline")

        session.refresh(repo)
        if repo.status != RepoStatus.ready or repo.current_run_id is None:
            print(f"FAILED: {owner}/{name} did not reach a ready analysis run. Not pinning.")
            return 1

        # Session 16 Known Hazard #6: always surface the full secrets picture
        # before pinning, regardless of whether --confirm-no-live-secrets was
        # passed -- the operator must SEE this, not just be trusted to have
        # checked it out-of-band.
        live_hits = session.scalars(
            select(SecretHit).where(SecretHit.repo_id == repo.id, SecretHit.still_in_head.is_(True))
        ).all()
        historical_hits = session.scalars(
            select(SecretHit).where(
                SecretHit.repo_id == repo.id, SecretHit.still_in_head.is_(False)
            )
        ).all()
        print(
            f"Secret scan: {len(live_hits)} still in HEAD, "
            f"{len(historical_hits)} in history only (deleted)."
        )
        for hit in live_hits:
            print(
                f"  LIVE  {hit.rule_id}  {hit.redacted_preview or '(no preview)'}  {hit.description}"
            )
        for hit in historical_hits:
            print(
                f"  history-only  {hit.rule_id}  {hit.redacted_preview or '(no preview)'}  "
                f"commit={hit.commit_sha[:8]}"
            )

        if live_hits and not confirm_no_live_secrets:
            print(
                "\nREFUSING to pin: this repository has a secret still present in HEAD. "
                "Rotate/remove it upstream, or re-run with --confirm-no-live-secrets only "
                "if you have personally reviewed every LIVE hit above and confirmed none is "
                "a real, exploitable credential (e.g. it is a documented test fixture)."
            )
            return 1

        repo.is_showcase = True
        repo.showcase_rank = rank if rank is not None else _next_rank(session)
        session.commit()
        print(f"Pinned {owner}/{name} as showcase rank {repo.showcase_rank}.")

        print("Pre-generating narratives ...")
        result = pregenerate_narratives(run_id=repo.current_run_id, db=session, _admin=None)
        print(f"  generated: {len(result['generated'])}, skipped: {len(result['skipped'])}")
        for skipped in result["skipped"]:
            print(f"    skipped {skipped['surface']}: {skipped['reason']}")

        return 0
    finally:
        session.close()


def cmd_list() -> int:
    session = SessionLocal()
    try:
        rows = session.scalars(
            select(Repo)
            .where(Repo.is_showcase.is_(True))
            .order_by(Repo.showcase_rank.asc().nulls_last())
        ).all()
        if not rows:
            print("No showcase repositories pinned.")
            return 0
        for repo in rows:
            print(
                f"[{repo.showcase_rank}] {repo.owner}/{repo.name}  "
                f"{repo.url}  id={repo.id}  commits={repo.commit_count}"
            )
        return 0
    finally:
        session.close()


def cmd_remove(url: str) -> int:
    session = SessionLocal()
    try:
        repo = session.scalar(select(Repo).where(Repo.url == url))
        if repo is None:
            print(f"No repository found for {url!r}.")
            return 1
        if not repo.is_showcase:
            print(f"{repo.owner}/{repo.name} is not currently a showcase repository.")
            return 0
        repo.is_showcase = False
        repo.showcase_rank = None
        session.commit()
        print(f"Unpinned {repo.owner}/{repo.name}.")
        return 0
    finally:
        session.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    add_parser = sub.add_parser("add", help="Analyse and pin a repository as a showcase example.")
    add_parser.add_argument("url")
    add_parser.add_argument("--rank", type=int, default=None)
    add_parser.add_argument(
        "--confirm-no-live-secrets",
        action="store_true",
        help="Required to pin a repo whose analysis found a secret still in HEAD.",
    )

    sub.add_parser("list", help="List pinned showcase repositories.")

    remove_parser = sub.add_parser("remove", help="Unpin a showcase repository.")
    remove_parser.add_argument("url")

    args = parser.parse_args(argv)

    if args.command == "add":
        return cmd_add(args.url, args.rank, confirm_no_live_secrets=args.confirm_no_live_secrets)
    if args.command == "list":
        return cmd_list()
    if args.command == "remove":
        return cmd_remove(args.url)
    return 1


if __name__ == "__main__":
    sys.exit(main())


__all__ = ["cmd_add", "cmd_list", "cmd_remove", "main"]
