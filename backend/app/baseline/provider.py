"""Selects which ``BaselineProvider`` the insight pipeline uses, per
``COMPASS_BASELINE_PROVIDER`` (session 14).

Deliberately NOT read at import time: ``SeedBaseline``/``CorpusBaseline``
both need a live DB ``Session`` (they read the ``baselines`` table), and
``app/jobs/stages.py``'s ``INSIGHT_STAGES`` tuple is built once, at MODULE
IMPORT time, long before any particular run's session exists. So
``get_baseline_provider`` is called PER RUN, from inside
``app/jobs/stages.py``'s own wrapper functions for the risk/hygiene/onboarding
stages (see that module) -- never from ``app/engines/*``, which keeps this
session's diff under ``app/engines/`` at zero: those engines already accept
an injected ``BaselineProvider`` via their existing constructor (session 07),
unchanged.
"""

from sqlalchemy.orm import Session

from app.baseline.base import BaselineProvider
from app.baseline.corpus import CorpusBaseline
from app.baseline.heuristic import HeuristicBaseline
from app.baseline.seed import SeedBaseline
from app.config import settings


def get_baseline_provider(session: Session) -> BaselineProvider:
    """Returns the provider named by ``COMPASS_BASELINE_PROVIDER``
    ("heuristic" | "seed" | "corpus"). An unrecognized value falls back to
    "heuristic" rather than raising -- a typo'd env var must not take the
    whole insight pipeline down."""
    name = settings.COMPASS_BASELINE_PROVIDER
    if name == "corpus":
        return CorpusBaseline(session)
    if name == "seed":
        return SeedBaseline(session)
    return HeuristicBaseline()


def calibration_label() -> str:
    """What ``CALIBRATION_LABEL`` (app/api/analysis.py) derives at runtime,
    session 14 Part C.5: "corpus" only when a CorpusBaseline is actually the
    configured provider, "heuristic" for both the heuristic and seed
    providers (SeedBaseline's whole corpus table ships empty in Release A/B,
    so labelling it "corpus" would overclaim precision it doesn't have)."""
    return "corpus" if settings.COMPASS_BASELINE_PROVIDER == "corpus" else "heuristic"


__all__ = ["calibration_label", "get_baseline_provider"]
