"""The authenticated user's own history (session 02, Part E):
``GET /me/repos`` (Compass's own record of what they've submitted) and
``GET /me/github/repos`` (a live proxy of their GitHub account, for the
frontend's repository picker). Neither is repo-scoped
(``/repos/{...}``), so neither goes through ``require_repo_access`` --
both are gated on the request simply being an authenticated user, via
``current_user_required``.
"""

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.crypto import decrypt_token
from app.auth.deps import current_user_required
from app.db.base import get_db
from app.db.models import Health, Repo, User
from app.db.runs import get_latest_run
from app.schemas.me import GithubRepoOut, MyGithubReposResponse, MyRepoOut, MyReposResponse

logger = logging.getLogger(__name__)

router = APIRouter()

GITHUB_USER_REPOS_URL = "https://api.github.com/user/repos"
_GITHUB_TIMEOUT_SECONDS = 10.0
# GET /me/github/repos, Part E's explicit hazard note: paginating eagerly
# would hit GitHub's rate limit on an account with many repositories.
# Capped at 100 per page (GitHub's own max) and 3 pages -- 300 repos is
# already far more than a repository picker needs to be useful.
_GITHUB_REPOS_MAX_PAGES = 3
_GITHUB_REPOS_PER_PAGE = 100


@router.get("/me/repos", response_model=MyReposResponse)
def get_my_repos(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(current_user_required),
) -> MyReposResponse:
    base_query = select(Repo).where(Repo.owner_user_id == user.id)
    total = db.scalar(select(func.count()).select_from(base_query.subquery())) or 0
    rows = db.scalars(
        base_query.order_by(Repo.created_at.desc()).offset((page - 1) * per_page).limit(per_page)
    ).all()

    def _latest_run_status_and_health(repo_id: uuid.UUID) -> tuple[str | None, float | None]:
        run = get_latest_run(repo_id, db)
        if run is None:
            return None, None
        health_score = db.scalar(select(Health.score).where(Health.analysis_run_id == run.id))
        return run.status, health_score

    repo_outs = []
    for r in rows:
        latest_run_status, health_score = _latest_run_status_and_health(r.id)
        repo_outs.append(
            MyRepoOut(
                id=r.id,
                url=r.url,
                owner=r.owner,
                name=r.name,
                is_private=r.is_private,
                status=r.status,
                latest_run_status=latest_run_status,
                analyzed_at=r.analyzed_at,
                health_score=health_score,
            )
        )

    return MyReposResponse(
        repos=repo_outs,
        page=page,
        per_page=per_page,
        total=total,
    )


def _fetch_user_repos_page(token: str, page: int) -> list[dict]:
    params = urllib.parse.urlencode(
        {"per_page": _GITHUB_REPOS_PER_PAGE, "page": page, "sort": "pushed"}
    )
    request = urllib.request.Request(
        f"{GITHUB_USER_REPOS_URL}?{params}",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(request, timeout=_GITHUB_TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


@router.get("/me/github/repos", response_model=MyGithubReposResponse)
def get_my_github_repos(
    user: User = Depends(current_user_required),
) -> MyGithubReposResponse:
    """Proxies GitHub's ``/user/repos`` using the caller's own stored token
    -- the token itself is never sent to the browser, only the derived
    fields the repo picker needs."""
    if user.access_token_encrypted is None:
        raise HTTPException(status_code=403, detail="Connect your GitHub account first.")
    token = decrypt_token(user.access_token_encrypted)

    fetched: list[dict] = []
    try:
        for page_number in range(1, _GITHUB_REPOS_MAX_PAGES + 1):
            batch = _fetch_user_repos_page(token, page_number)
            fetched.extend(batch)
            if len(batch) < _GITHUB_REPOS_PER_PAGE:
                break
    except (urllib.error.URLError, OSError, ValueError) as exc:
        logger.warning("GitHub /user/repos lookup failed: %r", exc)
        raise HTTPException(status_code=502, detail="Failed to fetch GitHub repositories.") from exc

    truncated = len(fetched) == _GITHUB_REPOS_MAX_PAGES * _GITHUB_REPOS_PER_PAGE

    return MyGithubReposResponse(
        repos=[
            GithubRepoOut(
                full_name=r["full_name"],
                private=r["private"],
                size=r.get("size", 0),
                language=r.get("language"),
                pushed_at=r.get("pushed_at"),
            )
            for r in fetched
        ],
        truncated=truncated,
    )


__all__ = ["router"]
