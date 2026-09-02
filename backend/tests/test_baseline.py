import uuid

import pytest

from app.baseline.corpus import MIN_CORPUS_REPOS_PER_CELL, CorpusBaseline
from app.baseline.heuristic import HeuristicBaseline, size_bucket_for
from app.baseline.provider import calibration_label, get_baseline_provider
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


# ---------------------------------------------------------------------------
# CorpusBaseline (session 14, Part C.4)
# ---------------------------------------------------------------------------


def _add_baseline_row(
    db_session,
    *,
    metric: str,
    language: str,
    size_bucket: str,
    n_repos: int,
    n_files: int = 100,
    p10: float = 1.0,
    p25: float = 2.0,
    p50: float = 5.0,
    p75: float = 10.0,
    p90: float = 20.0,
) -> Baseline:
    row = Baseline(
        id=uuid.uuid4(),
        metric=metric,
        language=language,
        size_bucket=size_bucket,
        p10=p10,
        p25=p25,
        p50=p50,
        p75=p75,
        p90=p90,
        n_repos=n_repos,
        n_files=n_files,
    )
    db_session.add(row)
    db_session.commit()
    return row


def test_corpus_baseline_falls_back_to_heuristic_when_no_row_exists(db_session):
    corpus = CorpusBaseline(db_session)
    heuristic = HeuristicBaseline()

    values = [10.0, 20.0, 30.0]
    corpus_norm = corpus.risk_normalizer("churn_x_complexity", "python", "small")
    heuristic_norm = heuristic.risk_normalizer("churn_x_complexity", "python", "small")
    assert corpus_norm(values) == heuristic_norm(values)
    assert corpus.percentile(
        "churn_x_complexity", "python", "small", 500.0
    ) == heuristic.percentile("churn_x_complexity", "python", "small", 500.0)


def test_corpus_baseline_cell_size_gate_widens_then_falls_back(db_session):
    """MIN_CORPUS_REPOS_PER_CELL=5 -- a cell backed by fewer repositories
    than that must never be presented as a real corpus answer (session 14
    Known Hazard #4): the lookup widens first (drop size_bucket, then
    language), and only falls all the way back to HeuristicBaseline when
    even the widest cell is still under-powered."""
    # Exact cell under-powered (3 repos) -- but the SAME language has a
    # well-powered row at a DIFFERENT size bucket (8 repos): widen to it.
    _add_baseline_row(
        db_session, metric="risk_score", language="python", size_bucket="small", n_repos=3
    )
    _add_baseline_row(
        db_session,
        metric="risk_score",
        language="python",
        size_bucket="medium",
        n_repos=8,
        p10=10.0,
        p25=25.0,
        p50=42.0,
        p75=60.0,
        p90=90.0,
    )

    corpus = CorpusBaseline(db_session)
    pct, widened, n_repos, n_files = corpus.percentile_with_provenance(
        "risk_score", "python", "small", 42.0
    )
    assert widened is True
    assert n_repos == 8
    assert pct == pytest.approx(0.50)

    # Now a metric where EVERY cell for this language is under-powered --
    # must fall back to HeuristicBaseline entirely, not present a
    # three-repository answer as if it were real.
    _add_baseline_row(
        db_session, metric="complexity", language="java", size_bucket="small", n_repos=2
    )
    heuristic = HeuristicBaseline()
    corpus_pct, widened2, n_repos2, n_files2 = corpus.percentile_with_provenance(
        "complexity", "java", "small", 15.0
    )
    assert widened2 is False
    assert n_repos2 == 0
    assert n_files2 == 0
    assert corpus_pct == heuristic.percentile("complexity", "java", "small", 15.0)
    assert MIN_CORPUS_REPOS_PER_CELL == 5  # documents the floor this test exercises


def test_corpus_baseline_risk_normalizer_differs_from_heuristic(db_session):
    """Proves the swap actually does something (session 14 Part F): given
    the SAME raw values, CorpusBaseline's corpus-relative normalization
    must differ from HeuristicBaseline's per-repo min-max."""
    _add_baseline_row(
        db_session,
        metric="churn_x_complexity",
        language="python",
        size_bucket="small",
        n_repos=10,
        p10=100.0,
        p25=200.0,
        p50=500.0,
        p75=1000.0,
        p90=2000.0,
    )
    values = [50.0, 500.0, 5000.0]

    corpus = CorpusBaseline(db_session)
    heuristic = HeuristicBaseline()
    corpus_scaled = corpus.risk_normalizer("churn_x_complexity", "python", "small")(values)
    heuristic_scaled = heuristic.risk_normalizer("churn_x_complexity", "python", "small")(values)

    assert corpus_scaled != pytest.approx(heuristic_scaled)
    # Heuristic is a pure per-repo min-max: the smallest value always maps
    # to 0.0 and the largest to 1.0, regardless of what they actually are.
    assert heuristic_scaled[0] == pytest.approx(0.0)
    assert heuristic_scaled[-1] == pytest.approx(1.0)
    # Corpus-relative: 50.0 is below this cell's own p10 (100.0), so it
    # does NOT map to 0.0 the way the heuristic's min-max forces it to.
    assert corpus_scaled[0] == pytest.approx(0.10)


# ---------------------------------------------------------------------------
# Provider selection + runtime-derived calibration label (session 14, Part C.5)
# ---------------------------------------------------------------------------


def test_get_baseline_provider_selects_by_setting(db_session, monkeypatch):
    import app.baseline.provider as provider_module

    monkeypatch.setattr(provider_module.settings, "COMPASS_BASELINE_PROVIDER", "heuristic")
    assert isinstance(get_baseline_provider(db_session), HeuristicBaseline)

    monkeypatch.setattr(provider_module.settings, "COMPASS_BASELINE_PROVIDER", "seed")
    assert isinstance(get_baseline_provider(db_session), SeedBaseline)

    monkeypatch.setattr(provider_module.settings, "COMPASS_BASELINE_PROVIDER", "corpus")
    assert isinstance(get_baseline_provider(db_session), CorpusBaseline)

    # An unrecognized value must not take the pipeline down -- falls back
    # to heuristic.
    monkeypatch.setattr(provider_module.settings, "COMPASS_BASELINE_PROVIDER", "bogus")
    assert isinstance(get_baseline_provider(db_session), HeuristicBaseline)


def test_calibration_label_derives_from_active_provider(monkeypatch):
    import app.baseline.provider as provider_module

    monkeypatch.setattr(provider_module.settings, "COMPASS_BASELINE_PROVIDER", "heuristic")
    assert calibration_label() == "heuristic"

    monkeypatch.setattr(provider_module.settings, "COMPASS_BASELINE_PROVIDER", "seed")
    assert calibration_label() == "heuristic"

    monkeypatch.setattr(provider_module.settings, "COMPASS_BASELINE_PROVIDER", "corpus")
    assert calibration_label() == "corpus"
