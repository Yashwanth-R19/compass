"""Resolves the URL the cloner actually shells out to (session 02, Part D).

Public repo -> the plain https URL stored on ``repos.url``.
Private repo -> ``https://x-access-token:<decrypted token>@github.com/o/n...``,
using the *repo owner's* stored, Fernet-decrypted GitHub token.

Called by the cloner in BOTH worker modes -- the GitHub Actions worker has
its own ``DATABASE_URL`` and ``COMPASS_TOKEN_ENCRYPTION_KEY`` (see
DEPLOY.md), so it resolves this itself, exactly like the inline path. There
is no credentials-callback endpoint and no job-token concept (CLAUDE.md's
worker-dispatch section, unchanged by this session): the worker already had
everything it needs to look this up on its own.

The returned URL embeds a live credential. Callers must never log it, put it
in an exception message that propagates out of the clone step, or store it
anywhere -- see ``app/ingestion/cloner.py`` for how the clone step itself
keeps that promise even when the clone fails.
"""

from urllib.parse import urlparse, urlunparse

from sqlalchemy.orm import Session

from app.auth.crypto import decrypt_token
from app.db.models import Repo, User


def resolve_clone_url(repo: Repo, session: Session) -> str:
    if not repo.is_private:
        return repo.url

    if repo.owner_user_id is None:
        raise ValueError(
            f"Private repo {repo.id} has no owner_user_id -- cannot resolve a clone URL "
            "without a token to authenticate with."
        )

    owner = session.get(User, repo.owner_user_id)
    if owner is None or owner.access_token_encrypted is None:
        raise ValueError(
            f"Private repo {repo.id}'s owner has no stored GitHub token -- they must "
            "reconnect private repositories before this repo can be re-analyzed."
        )

    token = decrypt_token(owner.access_token_encrypted)

    parsed = urlparse(repo.url)
    netloc = f"x-access-token:{token}@{parsed.hostname}"
    if parsed.port is not None:
        netloc = f"{netloc}:{parsed.port}"
    return urlunparse(parsed._replace(netloc=netloc))


__all__ = ["resolve_clone_url"]
