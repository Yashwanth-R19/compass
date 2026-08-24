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

    # Session 02: GitHub OAuth App credentials (see DEPLOY.md for how to
    # create the App). Two-step scope escalation (CLAUDE.md) means the same
    # App is used for both the profile-only login and the repo-scoped
    # "connect private repositories" flow -- the requested `scope` differs
    # per call to /auth/github/login, not the App itself.
    GITHUB_CLIENT_ID: str = ""
    GITHUB_CLIENT_SECRET: str = ""
    GITHUB_OAUTH_REDIRECT_URI: str = "http://localhost:8000/auth/github/callback"

    # Session 02: signs the session JWT cookie issued by
    # /auth/github/callback. Distinct from COMPASS_TOKEN_ENCRYPTION_KEY --
    # this one signs (HMAC), it never encrypts a GitHub token.
    COMPASS_JWT_SECRET: str = ""

    # Session 02: Fernet key encrypting users.access_token_encrypted at rest
    # (app/auth/crypto.py). MUST be set in production -- see that module's
    # startup assertion. In development, an unset key logs a loud warning and
    # derives an ephemeral one (tokens stored under it don't survive a
    # process restart, which is fine for local dev and never true in prod).
    COMPASS_TOKEN_ENCRYPTION_KEY: str = ""

    # Session 02: where /auth/github/callback and various auth error paths
    # redirect back to. Distinct from FRONTEND_ORIGIN (a CORS allowlist
    # entry) even though they're normally the same URL -- this one is used
    # for building a redirect Location header, not for CORS matching.
    COMPASS_FRONTEND_URL: str = "http://localhost:5173"

    # Session 02: "development" or "production". Gates the
    # COMPASS_TOKEN_ENCRYPTION_KEY startup assertion (app/auth/crypto.py) --
    # a missing/invalid key refuses to start in production, only warns in
    # development. Distinct from ENV above (kept for backward compatibility
    # with anything already reading it); new code should read COMPASS_ENV.
    COMPASS_ENV: str = "development"

    # Session 02, Part F: in-memory rate limiting (app/api/limits.py). All
    # tunable without a code change -- see that module's docstring for why
    # this is a single-process limiter, not yet Redis/Postgres-backed.
    COMPASS_RATE_LIMIT_ANON_PER_HOUR: int = 3
    COMPASS_RATE_LIMIT_ANON_PER_DAY: int = 10
    COMPASS_RATE_LIMIT_USER_PER_HOUR: int = 20
    COMPASS_RATE_LIMIT_USER_PER_DAY: int = 100
    COMPASS_MAX_CONCURRENT_RUNS: int = 3

    # Session 10, Part D.8: the stable salt app/security/scanner.py's
    # fingerprint() mixes into every secret's SHA-256 -- read from config
    # ONCE, never generated per-scan. A changing salt would silently break
    # still_in_head matching (the history scan and the working-tree scan
    # must fingerprint the same secret identically within one run) and
    # cross-run deduplication (the same secret found again on a later
    # re-analysis must produce the same fingerprint). Unlike
    # COMPASS_TOKEN_ENCRYPTION_KEY, this salt does not gate startup in
    # production -- a fingerprint is not itself sensitive (it can't be
    # reversed to the secret value), so an unset default is safe to ship,
    # just documented as worth overriding in production so fingerprints
    # aren't guessable across deployments by anyone who knows the default.
    COMPASS_SECRET_SCAN_SALT: str = "compass-secret-scan-dev-salt"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
