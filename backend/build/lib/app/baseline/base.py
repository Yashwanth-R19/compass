from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence


class BaselineProvider(ABC):
    """The seam Release C plugs a corpus-calibrated model behind (master-context.md
    sec 9, decision 2: "Baseline is an injected interface").

    Every consumer -- today just RiskEngine, later Benchmark/Percentile too --
    depends on this ABC, never on a concrete provider. Release A/B ship
    ``HeuristicBaseline`` (no corpus, fixed documented thresholds) as the
    default; Release C swaps in a ``CorpusBaseline`` built on CPDP/transfer
    normalization with zero changes to the engines that consume it.
    """

    @abstractmethod
    def percentile(self, metric: str, language: str, size_bucket: str, value: float) -> float:
        """Where ``value`` falls in [0, 1] against the reference distribution
        for ``metric`` within repos of this ``language``/``size_bucket``.

        Used by the (future) Benchmark/Percentile module ("your complexity is
        in the 90th percentile of Python repos this size" -- master-context.md
        sec 8). Not exercised by RiskEngine, which uses ``risk_normalizer``
        instead, but part of the interface every provider must honor.
        """
        raise NotImplementedError

    @abstractmethod
    def risk_normalizer(
        self, metric: str, language: str, size_bucket: str
    ) -> Callable[[Sequence[float]], list[float]]:
        """Returns ``norm``: a function that scales a list of raw values for
        ``metric`` to ``[0, 1]``.

        The caller (RiskEngine) passes it the *current repo's* full list of
        raw values for that metric and gets back a parallel list of scaled
        values -- this is what makes "per-repo min-max, against that repo's
        own distribution" (master-context.md sec 8.1) live behind the
        interface instead of hardcoded inside the engine. A heuristic
        provider's ``norm`` only looks at the values it's handed (ignoring
        ``language``/``size_bucket``, since it has no corpus to key off of);
        a corpus-backed provider's ``norm`` can instead ignore the repo's own
        distribution entirely and map each value through pre-computed
        corpus percentiles for that ``language``/``size_bucket`` -- same
        call site, same return shape, no RiskEngine changes either way.
        """
        raise NotImplementedError
