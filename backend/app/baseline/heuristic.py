from bisect import bisect_left
from collections.abc import Callable, Sequence

from app.baseline.base import BaselineProvider

# ---- Fixed, documented thresholds (no corpus) ----
#
# Release A/B ship with no reference corpus at all (master-context.md sec 6,
# sec 9 decision 2), so `percentile()` can't look anything up statistically --
# it interpolates against hand-picked breakpoints instead. These are informed
# guesses (code-maat/CodeScene folk-wisdom ballparks for what a "busy,
# complex" file or a "strongly coupled" pair looks like), not measured from
# real data. Release C's CorpusBaseline replaces this table with real
# percentiles computed from the curated corpus -- same method signature, so
# nothing that calls percentile() needs to change.
#
# Each entry is a sorted list of (value, percentile) control points; values
# between two points are linearly interpolated, values past either end are
# clamped to the nearest point's percentile.
_PERCENTILE_BREAKPOINTS: dict[str, list[tuple[float, float]]] = {
    "churn_x_complexity": [
        (0.0, 0.0),
        (50.0, 0.10),
        (200.0, 0.25),
        (500.0, 0.50),
        (1000.0, 0.75),
        (2000.0, 0.90),
        (5000.0, 1.0),
    ],
    "coupling_degree": [
        (0.0, 0.0),
        (0.30, 0.10),  # CouplingEngine's own MIN_COUPLING_DEGREE floor
        (0.45, 0.25),
        (0.60, 0.50),
        (0.75, 0.75),
        (0.90, 0.90),
        (1.0, 1.0),
    ],
    "commit_count": [
        (0.0, 0.0),
        (2.0, 0.10),
        (5.0, 0.25),
        (10.0, 0.50),
        (25.0, 0.75),
        (50.0, 0.90),
        (100.0, 1.0),
    ],
}

_DEFAULT_BREAKPOINTS: list[tuple[float, float]] = _PERCENTILE_BREAKPOINTS["churn_x_complexity"]
"""Fallback shape for any metric this table doesn't explicitly know about --
never crash, just give an honest, clearly-heuristic estimate."""


def interpolate_breakpoints(breakpoints: list[tuple[float, float]], value: float) -> float:
    """Linear interpolation over a sorted (value, percentile) control-point
    list, clamped at both ends. Shared by HeuristicBaseline (fixed table)
    and SeedBaseline (per-metric rows read from the ``baselines`` table) --
    same interpolation shape either way, only the control points differ."""
    values = [v for v, _ in breakpoints]
    if value <= values[0]:
        return breakpoints[0][1]
    if value >= values[-1]:
        return breakpoints[-1][1]

    idx = bisect_left(values, value)
    (lo_v, lo_p), (hi_v, hi_p) = breakpoints[idx - 1], breakpoints[idx]
    if hi_v == lo_v:
        return lo_p
    fraction = (value - lo_v) / (hi_v - lo_v)
    return lo_p + fraction * (hi_p - lo_p)


# ---- Repo size bucketing (heuristic, used to key percentile()/risk_normalizer() calls) ----

SMALL_REPO_MAX_FILES = 20
MEDIUM_REPO_MAX_FILES = 200
"""Repo-size buckets by analyzed file count. Coarse and heuristic -- good
enough to key a lookup table by, not a claim of statistical significance.
Release C's corpus is stratified by the same three buckets (master-context.md
sec 6, CPDP needs like-for-like comparison groups)."""


def size_bucket_for(file_count: int) -> str:
    if file_count <= SMALL_REPO_MAX_FILES:
        return "small"
    if file_count <= MEDIUM_REPO_MAX_FILES:
        return "medium"
    return "large"


def _min_max_normalizer(values: Sequence[float]) -> list[float]:
    """The actual per-repo min-max placeholder math (master-context.md sec
    8.1) -- lives here, behind the interface, precisely so RiskEngine never
    hardcodes it directly (CLAUDE.md: "the Release-C swap breaks the
    'no rewrite' contract" otherwise).

    A constant list (max == min, including the empty/singleton case) has no
    spread to scale against; every value gets the neutral midpoint 0.5 rather
    than a division by zero or an arbitrary 0/1.
    """
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi == lo:
        return [0.5 for _ in values]
    return [(v - lo) / (hi - lo) for v in values]


class HeuristicBaseline(BaselineProvider):
    """Default BaselineProvider for Release A/B: no corpus, fixed thresholds
    for ``percentile()`` and a per-repo min-max scaler for
    ``risk_normalizer()``. ``language``/``size_bucket`` are accepted (per the
    ABC) but not yet used to vary behavior -- there's no corpus to
    differentiate on yet; a future CorpusBaseline is what actually keys off
    them.
    """

    def percentile(self, metric: str, language: str, size_bucket: str, value: float) -> float:
        breakpoints = _PERCENTILE_BREAKPOINTS.get(metric, _DEFAULT_BREAKPOINTS)
        return interpolate_breakpoints(breakpoints, value)

    def risk_normalizer(
        self, metric: str, language: str, size_bucket: str
    ) -> Callable[[Sequence[float]], list[float]]:
        return _min_max_normalizer
