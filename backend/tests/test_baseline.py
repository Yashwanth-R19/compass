import uuid

import pytest

from app.baseline.heuristic import HeuristicBaseline, size_bucket_for
from app.baseline.seed import SeedBaseline
from app.db.models import Baseline


def test_heuristic_min_max_normalizer_scales_to_unit_interval():
    baseline = HeuristicBaseline()
    norm = baseline.risk_normalizer("churn_x_complexity", "python", "small")
    assert norm([10.0, 20.0, 30.0, 40.0]) == pytest.approx([0.0, 1 / 3, 2 / 3, 1.0])


def test_heuristic_normalizer_constant_values_map_to_midpoint():
    baseline = HeuristicBaseline()
    norm = baseline.risk_normalizer("commit_count", "python", "small")
    assert norm([5.0, 5.0, 5.0]) == [0.5, 0.5, 0.5]
    assert norm([]) == []


def test_heuristic_percentile_is_monotonic_and_bounded():
    baseline = HeuristicBaseline()
    low = baseline.percentile("churn_x_complexity", "python", "small", 10.0)
    mid = baseline.percentile("churn_x_complexity", "python", "small", 500.0)
    high = baseline.percentile("churn_x_complexity", "python", "small", 10_000.0)
    assert 0.0 <= low < mid < high <= 1.0
    assert high == pytest.approx(1.0)


def test_size_bucket_thresholds():
    assert size_bucket_for(1) == "small"
    assert size_bucket_for(20) == "small"
    assert size_bucket_for(21) == "medium"
    assert size_bucket_for(200) == "medium"
    assert size_bucket_for(201) == "large"


def test_seed_baseline_falls_back_to_heuristic_when_table_empty(db_session):
    """The baselines table ships empty in Release A/B (see the Baseline model
    docstring) -- SeedBaseline must behave exactly like HeuristicBaseline
    until Release C's corpus pipeline populates it."""
    seed = SeedBaseline(db_session)
    heuristic = HeuristicBaseline()

    seed_norm = seed.risk_normalizer("churn_x_complexity", "python", "small")
    heuristic_norm = heuristic.risk_normalizer("churn_x_complexity", "python", "small")
    values = [10.0, 20.0, 30.0]
    assert seed_norm(values) == heuristic_norm(values)

    assert seed.percentile("churn_x_complexity", "python", "small", 500.0) == heuristic.percentile(
        "churn_x_complexity", "python", "small", 500.0
    )


def test_seed_baseline_uses_corpus_row_when_present(db_session):
    """Once a row exists for (metric, language, size_bucket), SeedBaseline
    must use it instead of falling back -- proving the interface swap the
    whole BaselineProvider abstraction exists for (master-context.md sec 9,
    decision 2) works with zero RiskEngine changes."""
    row = Baseline(
        id=uuid.uuid4(),
        metric="commit_count",
        language="python",
        size_bucket="small",
        p10=1.0,
        p25=2.0,
        p50=5.0,
        p75=10.0,
        p90=20.0,
    )
    db_session.add(row)
    db_session.commit()

    seed = SeedBaseline(db_session)
    norm = seed.risk_normalizer("commit_count", "python", "small")
    # Corpus-backed: maps through the stored percentile curve, NOT a
    # per-repo min-max over the values handed in.
    assert norm([5.0]) == pytest.approx([0.50])
    assert seed.percentile("commit_count", "python", "small", 5.0) == pytest.approx(0.50)
