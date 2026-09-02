from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import analysis, auth, health, jobs, me, narrative, repos, share
from app.config import settings

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

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(repos.router)
app.include_router(jobs.router)
app.include_router(analysis.router)
app.include_router(me.router)
app.include_router(share.router)
app.include_router(narrative.router)
