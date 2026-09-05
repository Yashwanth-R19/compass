"""GitHub OAuth login/callback/logout and the current-user endpoint (session
02, Part C).

**Two-step scope escalation.** ``GET /auth/github/login`` accepts
``scope=basic`` (default, requests only ``read:user``) or ``scope=repo``
(requests ``read:user repo``). The frontend uses ``basic`` for the ordinary
"Log in" button and only ever sends a user through ``repo`` when they
explicitly click "Connect private repositories" -- plan/RULES.md's
constraint "do not request repo scope at first login" exists because
``repo`` grants read AND WRITE access to every repository the user can see,
and asking for it unconditionally at login would needlessly show that scary
consent screen to every user who only ever wants to analyse public repos.

**SameSite / cross-origin cookies.** See ``app/auth/session.py``'s module
docstring for the full writeup: the OAuth `state` cookie stays
``SameSite=Lax`` (it only needs to survive a top-level GET redirect back
from GitHub to this API's own origin); the session cookie is
``SameSite=None; Secure`` because the frontend and API are different sites
and a Lax cookie would never reach a cross-site ``fetch(..., {credentials:
"include"})`` call.
"""

import base64
import hmac
import json
import logging
import secrets
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from typing import Literal

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.crypto import decrypt_token, encrypt_token
from app.auth.deps import current_user_required, has_repo_scope
from app.auth.session import SESSION_COOKIE_NAME, SESSION_TTL, create_session_token
from app.config import settings
from app.db.base import get_db
from app.db.models import Repo, User
from app.jobs.log_redaction import redact
from app.schemas.auth import UserOut

logger = logging.getLogger(__name__)

router = APIRouter()

GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_URL = "https://api.github.com/user"

OAUTH_STATE_COOKIE_NAME = "compass_oauth_state"
OAUTH_STATE_TTL = timedelta(minutes=5)
_STATE_ALGORITHM = "HS256"

# scope=basic vs scope=repo -- see module docstring's two-step escalation note.
_GITHUB_SCOPES = {"basic": "read:user", "repo": "read:user repo"}

_OAUTH_TIMEOUT_SECONDS = 10.0


def _validate_next_path(next_path: str | None) -> str:
    """Rejects anything that isn't a plain relative path on our own
    frontend -- an open-redirect vector (session 02, Part C, explicitly
    tested). ``urlparse`` alone doesn't catch every case: it happily leaves
    a backslash variant like ``/\\evil.com`` with no scheme/netloc (browsers
    treat a leading ``/\\`` as protocol-relative, normalising it to
    ``//evil.com``), so that's checked for explicitly rather than trusted to
    ``urlparse``.
    """
    if not next_path:
        return "/"
    parsed = urllib.parse.urlparse(next_path)
    if parsed.scheme or parsed.netloc:
        raise HTTPException(status_code=400, detail="Invalid redirect path.")
    if next_path.startswith("//") or next_path.startswith("/\\"):
        raise HTTPException(status_code=400, detail="Invalid redirect path.")
    if not next_path.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid redirect path.")
    return next_path


def _exchange_code_for_token(code: str) -> dict:
    """POSTs to GitHub's token endpoint. Raises on any transport failure;
    the caller decides what to tell the browser. Never logs ``code`` or
    ``GITHUB_CLIENT_SECRET`` -- both go in the request body, never in a log
    line, and urllib's own exceptions don't echo the request body back."""
    data = urllib.parse.urlencode(
        {
            "client_id": settings.GITHUB_CLIENT_ID,
            "client_secret": settings.GITHUB_CLIENT_SECRET,
            "code": code,
            "redirect_uri": settings.GITHUB_OAUTH_REDIRECT_URI,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        GITHUB_TOKEN_URL,
        data=data,
        method="POST",
        headers={"Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=_OAUTH_TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


def _fetch_github_user(access_token: str) -> dict:
    """GETs the authenticated GitHub user's profile. Never logs
    ``access_token`` -- it's only ever placed in the Authorization header of
    this one outbound request, never in a log line or exception message."""
    request = urllib.request.Request(
        GITHUB_USER_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {access_token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(request, timeout=_OAUTH_TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


def _upsert_user(db: Session, github_user: dict, access_token: str, scopes: str) -> User:
    """Upserts by ``github_id`` (GitHub's stable numeric id -- never the
    mutable ``github_login``). The stored token and its scopes are always
    overwritten together, in sync -- token_scopes must never claim a
    broader grant than the currently-stored token actually has."""
    github_id = github_user["id"]
    now = datetime.now(UTC)
    user = db.scalar(select(User).where(User.github_id == github_id))
    if user is None:
        user = User(
            github_id=github_id,
            github_login=github_user.get("login", ""),
            name=github_user.get("name"),
            avatar_url=github_user.get("avatar_url"),
            access_token_encrypted=encrypt_token(access_token),
            token_scopes=scopes,
            created_at=now,
            last_login_at=now,
        )
        db.add(user)
    else:
        user.github_login = github_user.get("login", user.github_login)
        user.name = github_user.get("name")
        user.avatar_url = github_user.get("avatar_url")
        user.access_token_encrypted = encrypt_token(access_token)
        user.token_scopes = scopes
        user.last_login_at = now
    db.flush()
    return user


@router.get("/auth/github/login")
def github_login(
    scope: Literal["basic", "repo"] = "basic",
    next: str | None = None,
) -> RedirectResponse:
    next_path = _validate_next_path(next)
    state = secrets.token_urlsafe(24)
    state_token = jwt.encode(
        {
            "state": state,
            "next": next_path,
            "exp": datetime.now(UTC) + OAUTH_STATE_TTL,
        },
        settings.COMPASS_JWT_SECRET,
        algorithm=_STATE_ALGORITHM,
    )

    params = urllib.parse.urlencode(
        {
            "client_id": settings.GITHUB_CLIENT_ID,
            "redirect_uri": settings.GITHUB_OAUTH_REDIRECT_URI,
            "scope": _GITHUB_SCOPES[scope],
            "state": state,
        }
    )
    response = RedirectResponse(url=f"{GITHUB_AUTHORIZE_URL}?{params}", status_code=302)
    response.set_cookie(
        OAUTH_STATE_COOKIE_NAME,
        state_token,
        max_age=int(OAUTH_STATE_TTL.total_seconds()),
        httponly=True,
        secure=True,
        samesite="lax",
    )
    return response


@router.get("/auth/github/callback")
def github_callback(
    code: str,
    state: str,
    request: Request,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    state_cookie = request.cookies.get(OAUTH_STATE_COOKIE_NAME)
    if not state_cookie:
        raise HTTPException(status_code=400, detail="Missing or expired OAuth state.")
    try:
        payload = jwt.decode(
            state_cookie, settings.COMPASS_JWT_SECRET, algorithms=[_STATE_ALGORITHM]
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state.") from exc

    expected_state = payload.get("state", "")
    if not hmac.compare_digest(expected_state.encode("utf-8"), state.encode("utf-8")):
        raise HTTPException(status_code=400, detail="OAuth state mismatch.")
    next_path = payload.get("next") or "/"

    try:
        token_data = _exchange_code_for_token(code)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        logger.warning(redact(f"GitHub OAuth token exchange failed: {exc!r}"))
        raise HTTPException(status_code=502, detail="GitHub OAuth exchange failed.") from exc

    access_token = token_data.get("access_token")
    if not access_token:
        logger.warning("GitHub OAuth token exchange returned no access_token.")
        raise HTTPException(status_code=502, detail="GitHub OAuth exchange failed.")
    granted_scope = token_data.get("scope", "")

    try:
        github_user = _fetch_github_user(access_token)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        logger.warning(redact(f"GitHub profile lookup failed: {exc!r}"))
        raise HTTPException(status_code=502, detail="Failed to fetch GitHub profile.") from exc

    user = _upsert_user(db, github_user, access_token, granted_scope)
    db.commit()

    session_token = create_session_token(user.id)
    response = RedirectResponse(url=f"{settings.COMPASS_FRONTEND_URL}{next_path}", status_code=302)
    response.delete_cookie(OAUTH_STATE_COOKIE_NAME)
    response.set_cookie(
        SESSION_COOKIE_NAME,
        session_token,
        max_age=int(SESSION_TTL.total_seconds()),
        httponly=True,
        secure=True,
        samesite="none",
    )
    return response


@router.post("/auth/logout")
def logout() -> JSONResponse:
    # Clears the session cookie only -- the stored GitHub token is left
    # alone, the user may log back in (session 02, Part C).
    #
    # The deletion's own Set-Cookie must repeat the exact `Secure;
    # SameSite=None` attributes the cookie was originally issued with
    # (app/auth/session.py's module docstring). The frontend and API are
    # different sites, so this response is a cross-site fetch response from
    # the browser's point of view -- and a cross-site Set-Cookie header that
    # isn't `SameSite=None; Secure` is silently REJECTED by the browser
    # rather than applied. Starlette's `delete_cookie` default
    # (`secure=False, samesite="lax"`) is exactly such a header, which is
    # why logout previously appeared to do nothing: the browser never
    # actually cleared the cookie, so the very next request was still
    # authenticated under the old session.
    response = JSONResponse({"status": "ok"})
    response.delete_cookie(SESSION_COOKIE_NAME, path="/", secure=True, samesite="none")
    return response


@router.delete("/auth/github/connection")
def delete_github_connection(
    user: User = Depends(current_user_required),
    db: Session = Depends(get_db),
) -> dict:
    user.access_token_encrypted = None
    user.token_scopes = None
    db.commit()
    return {"status": "ok"}


def _revoke_github_grant(access_token: str) -> None:
    """Revokes this OAuth App's entire authorization for ``access_token`` via
    GitHub's grant-deletion endpoint -- this is what makes a later login with
    the same GitHub account show the consent screen again, exactly as if the
    user had never connected before. Merely clearing our own stored token
    (``DELETE /auth/github/connection`` above) leaves GitHub's own record of
    the grant in place, so a future login would silently re-use it with no
    prompt. Best-effort: the caller swallows any failure here rather than
    blocking account deletion on a GitHub API hiccup -- never logs or raises
    the token itself."""
    credentials = base64.b64encode(
        f"{settings.GITHUB_CLIENT_ID}:{settings.GITHUB_CLIENT_SECRET}".encode()
    ).decode("ascii")
    request = urllib.request.Request(
        f"https://api.github.com/applications/{settings.GITHUB_CLIENT_ID}/grant",
        data=json.dumps({"access_token": access_token}).encode("utf-8"),
        method="DELETE",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Basic {credentials}",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=_OAUTH_TIMEOUT_SECONDS):
        pass


@router.delete("/auth/account")
def delete_account(
    user: User = Depends(current_user_required),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """The full "stop sharing my data with Compass" action -- distinct from
    (and stronger than) ``DELETE /auth/github/connection`` above, which only
    disconnects private-repo access and keeps the account/history intact.
    This: (1) revokes this app's GitHub authorization entirely, so the next
    login re-prompts every consent screen from scratch; (2) deletes every
    repository this user owns, cascading through every Facts/Insight table
    that references it (same cascade ``DELETE /repos/{id}`` relies on) --
    never a showcase repo, matching that endpoint's own guard; (3) deletes
    the user's own account row (``share_links.created_by`` cascades,
    ``repos.owner_user_id``/``analysis_runs.triggered_by_user_id`` on any
    OTHER repo just go to NULL); (4) clears the session cookie so the
    browser is logged out immediately, not just left pointing at a
    now-deleted user id."""
    if user.access_token_encrypted:
        try:
            access_token = decrypt_token(user.access_token_encrypted)
            _revoke_github_grant(access_token)
        except Exception as exc:  # best-effort GitHub call, never blocks account deletion
            logger.warning(redact(f"GitHub grant revocation failed: {exc!r}"))

    owned_repo_ids = db.scalars(
        select(Repo.id).where(Repo.owner_user_id == user.id, Repo.is_showcase.is_(False))
    ).all()
    for repo_id in owned_repo_ids:
        repo = db.get(Repo, repo_id)
        if repo is not None:
            db.delete(repo)

    db.delete(user)
    db.commit()

    response = JSONResponse({"status": "deleted"})
    response.delete_cookie(SESSION_COOKIE_NAME, path="/", secure=True, samesite="none")
    return response


@router.get("/auth/me", response_model=UserOut)
def get_me(user: User = Depends(current_user_required)) -> UserOut:
    return UserOut(
        id=user.id,
        github_login=user.github_login,
        name=user.name,
        avatar_url=user.avatar_url,
        has_repo_scope=has_repo_scope(user),
        created_at=user.created_at,
    )


__all__ = ["router"]
