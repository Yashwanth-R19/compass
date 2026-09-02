"""``CorpusBaseline`` (session 14, Part C.4) -- the real Release C swap:
percentiles computed from a curated corpus of ~30 real repositories
(``app/baseline/corpus_repos.yaml``, built by ``build_corpus.py``, seeded
into the ``baselines`` table by ``seed_baselines.py``), behind the exact
same ``BaselineProvider`` interface ``RiskEngine``/``HygieneEngine``/
``PassportEngine`` already depend on.

Reuses ``interpolate_breakpoints`` (app/baseline/heuristic.py) -- the same
linear-interpolation-over-control-points shape ``HeuristicBaseline`` and
``SeedBaseline`` already use, just fed the corpus's real p10/p25/p50/p75/p90
instead of hand-picked or per-repo values.

**What this class is NOT**: a trained model, a defect classifier, transfer
learning. It is percentile lookup over a small, hand-curated, checked-in
list -- see this module's docstring in ``build_corpus.py`` and
``master-context.md`` sec 6/11 for what "corpus" honestly means here.
"""

from collections.abc import Callable, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.baseline.base import BaselineProvider
from app.baseline.heuristic import HeuristicBaseline, interpolate_breakpoints
from app.db.models import Baseline

MIN_CORPUS_REPOS_PER_CELL = 5
"""Session 14, Known Hazard #4: with ~30 repositories across 3 languages and
3 size buckets, several (language, size_bucket) cells will have only 2-3
repositories -- expected, not a bug. Below this floor, a percentile derived
from so few repositories is not honestly presentable as "the corpus says"
-- the comparison is widened first (drop size_bucket, then language) before
falling back to HeuristicBaseline entirely. Never respond to a sparse cell
by pretending it is full, and never respond by scraping more repositories
at runtime (Known Hazard #8) -- the corpus is fixed and checked in."""


def _breakpoints_from_row(row: Baseline) -> list[tuple[float, float]]:
    return [
        (row.p10, 0.10),
        (row.p25, 0.25),
        (row.p50, 0.50),
        (row.p75, 0.75),
        (row.p90, 0.90),
    ]


class CorpusBaseline(BaselineProvider):
    """Reads corpus percentiles from the ``baselines`` table (populated by
    ``python -m app.baseline.seed_baselines``), widening the lookup -- first
    dropping ``size_bucket``, then ``language`` too -- whenever the matching
    cell is backed by fewer than ``MIN_CORPUS_REPOS_PER_CELL`` repositories,
    and falling back to ``HeuristicBaseline`` entirely when even the widest
    cell doesn't clear that floor (or no corpus data exists for the metric
    at all).
    """

    def __init__(self, session: Session) -> None:
        self._session = session
        self._heuristic = HeuristicBaseline()

    def _candidate_rows(self, metric: str, language: str, size_bucket: str) -> list[Baseline]:
        """Every row for this metric, widest-first-eligible order not yet
        applied -- ``_lookup`` below picks the narrowest one that clears the
        floor. A metric the corpus never measured (e.g. an engine-local
        metric like "instability" that isn't one of the ten corpus metrics)
        simply returns nothing here, which correctly falls through to
        HeuristicBaseline every time."""
        return list(self._session.scalars(select(Baseline).where(Baseline.metric == metric)))

    def _lookup(self, metric: str, language: str, size_bucket: str) -> tuple[Baseline | None, bool]:
        """Returns ``(row, widened)``. Tries the exact (language, size_bucket)
        cell first; if it's missing or under-powered, widens to "any size
        bucket for this language" (rows summed... no -- corpus rows are
        already one row per exact cell, so "widening" here means PREFERRING
        a same-language, any-size row when the exact cell is too small, and
        finally any-language, any-size when even that is too small. Each
        widening step picks the row with the LARGEST n_repos among its
        candidates -- the most-supported approximation available at that
        widening level, not an arbitrary one."""
        rows = self._candidate_rows(metric, language, size_bucket)
        if not rows:
            return None, False

        def _best(candidates: list[Baseline]) -> Baseline | None:
            if not candidates:
                return None
            return max(candidates, key=lambda r: r.n_repos or 0)

        exact = [r for r in rows if r.language == language and r.size_bucket == size_bucket]
        exact_row = _best(exact)
        if exact_row is not None and (exact_row.n_repos or 0) >= MIN_CORPUS_REPOS_PER_CELL:
            return exact_row, False

        same_language = [r for r in rows if r.language == language]
        widened_row = _best(same_language)
        if widened_row is not None and (widened_row.n_repos or 0) >= MIN_CORPUS_REPOS_PER_CELL:
            return widened_row, True

        any_row = _best(rows)
        if any_row is not None and (any_row.n_repos or 0) >= MIN_CORPUS_REPOS_PER_CELL:
            return any_row, True

        # Nothing clears the floor even at the widest level -- fall back to
        # HeuristicBaseline entirely rather than presenting a percentile
        # from a handful of repositories as if it were corpus-backed.
        return None, False

    def percentile(self, metric: str, language: str, size_bucket: str, value: float) -> float:
        row, _widened = self._lookup(metric, language, size_bucket)
        if row is None:
            return self._heuristic.percentile(metric, language, size_bucket, value)
        return interpolate_breakpoints(_breakpoints_from_row(row), value)

    def percentile_with_provenance(
        self, metric: str, language: str, size_bucket: str, value: float
    ) -> tuple[float, bool, int, int]:
        """Like ``percentile``, but also returns ``(widened, n_repos,
        n_files)`` -- the honesty fields ``GET /repos/{id}/benchmark``
        (Part D) reports alongside every comparison. Not part of the
        ``BaselineProvider`` ABC (RiskEngine/HygieneEngine/PassportEngine
        never need this level of detail, only the scaled/interpolated
        value) -- a CorpusBaseline-specific extension the benchmark endpoint
        calls directly."""
        row, widened = self._lookup(metric, language, size_bucket)
        if row is None:
            return (
                self._heuristic.percentile(metric, language, size_bucket, value),
                False,
                0,
                0,
            )
        pct = interpolate_breakpoints(_breakpoints_from_row(row), value)
        return pct, widened, row.n_repos or 0, row.n_files or 0

    def risk_normalizer(
        self, metric: str, language: str, size_bucket: str
    ) -> Callable[[Sequence[float]], list[float]]:
        row, _widened = self._lookup(metric, language, size_bucket)
        if row is None:
            return self._heuristic.risk_normalizer(metric, language, size_bucket)

        breakpoints = _breakpoints_from_row(row)

        def corpus_relative_normalizer(values: Sequence[float]) -> list[float]:
            # The actual upgrade over HeuristicBaseline's per-repo min-max:
            # each value is mapped through the CORPUS's percentile curve,
            # ignoring the current repo's own distribution entirely -- "high
            # churn compared to similar repositories", not just "high churn
            # compared to its own siblings".
            return [interpolate_breakpoints(breakpoints, v) for v in values]

        return corpus_relative_normalizer
