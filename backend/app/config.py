from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    DATABASE_URL: str
    ENV: str = "development"
    FRONTEND_ORIGIN: str = "http://localhost:5173"

    # Session 01: comma-separated allowed CORS origins for production
    # (Vercel + any preview URLs). FRONTEND_ORIGIN above stays the local-dev
    # default; COMPASS_CORS_ORIGINS, when set, is what main.py actually uses.
    # Deliberately never "*" -- session 02 adds cookie authentication, and
    # wildcard origins are incompatible with credentialed requests.
    COMPASS_CORS_ORIGINS: str = ""

    # Session 01, Part G: which transport POST /repos uses to run a job --
    # "inline" (FastAPI BackgroundTasks, same as before this session) or
    # "actions" (dispatch to a GitHub Actions worker in COMPASS_WORKER_REPO).
    COMPASS_WORKER_MODE: str = "inline"
    # "{owner}/{repo}" of the PUBLIC repository whose mine.yml workflow
    # receives the repository_dispatch event. Its Actions logs are public --
    # see app/jobs/log_redaction.py and DEPLOY.md.
    COMPASS_WORKER_REPO: str = ""
    # Fine-grained PAT scoped to Actions: read and write on COMPASS_WORKER_REPO
    # only. Never logged, never returned by any API (app/jobs/dispatch.py).
    COMPASS_WORKER_PAT: str = ""

    # Session 01, Part I: submissions larger than this are rejected at
    # POST /repos rather than analyzed slowly (plan/RULES.md sec 14).
    COMPASS_MAX_REPO_MB: int = 300

    # Session 01, Part I: surfaced by GET /health so the keep-alive ping
    # also proves which build is actually running.
    COMPASS_VERSION: str = "0.1.0"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
