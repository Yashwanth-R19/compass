from collections.abc import Callable, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.baseline.base import BaselineProvider
from app.baseline.heuristic import HeuristicBaseline, interpolate_breakpoints
from app.db.models import Baseline


class SeedBaseline(BaselineProvider):
    """Reads corpus percentiles from the ``baselines`` table when present,
    falling back to ``HeuristicBaseline`` per (metric, language, size_bucket)
    when it isn't.

    The table is populated by Release C's corpus pipeline and is empty in
    Release A/B (see ``Baseline`` model docstring) -- so today every call
    falls through to the heuristic every time, and this class exists purely
    to prove the interface swap works with zero RiskEngine changes once rows
    start landing. Takes a ``Session`` at construction (unlike
    ``HeuristicBaseline``, which needs no DB access) since reading
    ``baselines`` is its whole job.
    """

    def __init__(self, session: Session) -> None:
        self._session = session
        self._heuristic = HeuristicBaseline()

    def _lookup(self, metric: str, language: str, size_bucket: str) -> Baseline | None:
        return self._session.scalar(
            select(Baseline).where(
                Baseline.metric == metric,
                Baseline.language == language,
                Baseline.size_bucket == size_bucket,
            )
        )

    def percentile(self, metric: str, language: str, size_bucket: str, value: float) -> float:
        row = self._lookup(metric, language, size_bucket)
        if row is None:
            return self._heuristic.percentile(metric, language, size_bucket, value)

        breakpoints = [
            (row.p10, 0.10),
            (row.p25, 0.25),
            (row.p50, 0.50),
            (row.p75, 0.75),
            (row.p90, 0.90),
        ]
        return interpolate_breakpoints(breakpoints, value)

    def risk_normalizer(
        self, metric: str, language: str, size_bucket: str
    ) -> Callable[[Sequence[float]], list[float]]:
        row = self._lookup(metric, language, size_bucket)
        if row is None:
            return self._heuristic.risk_normalizer(metric, language, size_bucket)

        breakpoints = [
            (row.p10, 0.10),
            (row.p25, 0.25),
            (row.p50, 0.50),
            (row.p75, 0.75),
            (row.p90, 0.90),
        ]

        def corpus_normalizer(values: Sequence[float]) -> list[float]:
            # Corpus-backed path: each value is mapped through the STORED
            # percentile curve, ignoring the current repo's own min/max --
            # this is the real cross-project normalization the placeholder
            # per-repo min-max (HeuristicBaseline) exists to be replaced by.
            return [interpolate_breakpoints(breakpoints, v) for v in values]

        return corpus_normalizer
