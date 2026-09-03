from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    analysis,
    auth,
    compare,
    health,
    internal,
    jobs,
    me,
    meta,
    narrative,
    portfolio,
    repos,
    share,
    timeline,
)
from app.api.logging_config import configure_logging
from app.api.middleware import (
    BodySizeLimitMiddleware,
    RequestContextMiddleware,
    RequestTimeoutMiddleware,
    SecurityHeadersMiddleware,
)
from app.config import settings

# Session 16, Part D: configured once, at process import time, before any
# request can possibly be served -- the same "before anything else runs"
# discipline app/jobs/worker.py already applies to install_log_redaction,
# now generalized into structured JSON logging that redactor filter sits
# underneath.
configure_logging()

app = FastAPI(title="Compass API")

# COMPASS_CORS_ORIGINS (comma-separated) is the production origin list --
# set it in the Render dashboard to the deployed Vercel URL(s). It's added
# alongside FRONTEND_ORIGIN, never in place of it, so local dev against
# http://localhost:5173 keeps working regardless of what's configured for
# production. Deliberately never "*": session 02 adds cookie authentication,
# and allow_credentials=True is incompatible with a wildcard origin by the
# CORS spec itself, not just as a matter of taste.
_extra_origins = [o.strip() for o in settings.COMPASS_CORS_ORIGINS.split(",") if o.strip()]
_allowed_origins = [settings.FRONTEND_ORIGIN, *_extra_origins]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Session 16, Parts C/D: registered AFTER CORSMiddleware above, which makes
# each of these OUTER to it (Starlette wraps middleware in the reverse of
# add_middleware call order -- the last one added is the outermost layer).
# BodySizeLimit closest to CORS/the router, then RequestTimeout, then
# SecurityHeaders (added to virtually every response), with
# RequestContextMiddleware outermost of all so its request id and total
# request-duration log line wrap the ENTIRE stack, including anything a
# lower middleware rejects (a 413, a CORS-blocked response, ...).
app.add_middleware(BodySizeLimitMiddleware)
app.add_middleware(RequestTimeoutMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestContextMiddleware)

app.include_router(health.router)
app.include_router(internal.router)
app.include_router(meta.router)
app.include_router(auth.router)
app.include_router(repos.router)
app.include_router(jobs.router)
app.include_router(analysis.router)
app.include_router(me.router)
app.include_router(share.router)
app.include_router(narrative.router)
app.include_router(timeline.router)
app.include_router(compare.router)
app.include_router(portfolio.router)
