import uuid

from pydantic import BaseModel


class UserOut(BaseModel):
    id: uuid.UUID
    github_login: str
    name: str | None
    avatar_url: str | None
    # Derived from users.token_scopes (never returned raw) -- whether this
    # user has completed the second, repo-scoped consent (CLAUDE.md's
    # two-step scope escalation) and can therefore submit/view private
    # repositories and use GET /me/github/repos.
    has_repo_scope: bool
