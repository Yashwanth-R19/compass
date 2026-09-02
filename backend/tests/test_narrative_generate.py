"""Session 12, Part C/F: prompting and, above all, the output validator --
"test this harder than anything else in the session... it is the
guarantee." Table-driven, with at least as many carefully-constructed
ACCEPTED examples as REJECTED ones (Known Hazard #1: a validator whose
acceptance tests are thin looks correct while shipping a dead feature).

No network, no DB -- ``validate_output``/``build_prompt`` are pure
functions over a fact pack and a candidate string.
"""

import pytest

from app.narrative.factpack import PassportFactPack, RiskFactPack, SecurityFactPack
from app.narrative.generate import (
    MAX_OUTPUT_CHARS,
    build_prompt,
    validate_output,
)

PASSPORT_PACK = PassportFactPack(
    onboarding_difficulty=62.4,
    calibration="heuristic",
    file_count=248,
    loc=41000,
    commit_count=1893,
    contributor_count=12,
    subsystem_count=7,
    age_days=812.0,
    commits_last_30d=14,
    commits_last_90d=61,
    commits_last_365d=340,
    is_dormant=False,
    active_contributor_count=5,
    stale_contributor_count=7,
    bot_commit_ratio=0.08,
    truck_factor=2,
    modularity=0.41,
    entry_point_count=3,
    top_risk_file_count=5,
    churn_concentration=0.62,
    health_score=71.0,
    high_risk_ratio=0.18,
    cycle_count=2,
    hidden_dependency_count=4,
    primary_language="python",
)

RISK_PACK = RiskFactPack(
    risk_score=0.85,
    risk_confidence=0.9,
    hotspot_rank=0,
    churn_total=1200,
    churn_weighted=900.0,
    complexity=34.0,
    commit_count=112,
    max_coupling_degree=0.55,
    instability_score=0.4,
    revert_cycle_count=2,
    test_classification="stale_test",
    test_cochange_ratio=0.15,
    expert_count=1,
    is_orphaned_knowledge=True,
    language="python",
    calibration="heuristic",
)

SECURITY_PACK = SecurityFactPack(
    secret_count_total=3,
    secret_count_still_in_head=1,
    secret_count_history_only=2,
    vulnerability_count_total=5,
    vulnerability_count_high=2,
    vulnerability_count_med=2,
    vulnerability_count_low=1,
    vulnerability_count_unknown=0,
    vulnerability_count_direct=3,
    vulnerability_count_transitive=2,
    no_supported_manifest=False,
    secrets_truncated=False,
)


# ---------------------------------------------------------------------------
# ACCEPTED cases -- written as carefully as the rejected ones (Known Hazard #1).
# ---------------------------------------------------------------------------


def test_accepts_fully_grounded_output_with_exact_numbers():
    text = (
        "This repository has 248 files and 12 contributors, with 2 as the truck factor. "
        "Onboarding difficulty is 62.4 out of 100, reflecting a health score of 71."
    )
    ok, reason = validate_output(text, PASSPORT_PACK)
    assert ok, reason


def test_accepts_rounded_integer_from_a_decimal_fact_value():
    # 62.4 -> "about 62" (Part C step 1b's literal example, generalised).
    text = (
        "Onboarding difficulty here is about 62, which is on the higher side for a repo this size."
    )
    ok, reason = validate_output(text, PASSPORT_PACK)
    assert ok, reason


def test_accepts_percentage_phrasing_of_a_ratio_rounded_to_the_nearest_ten():
    # churn_concentration=0.62 -> "roughly 60%" (Part C step 1b's own example).
    text = "Roughly 60% of churn is concentrated in a small slice of the codebase."
    ok, reason = validate_output(text, PASSPORT_PACK)
    assert ok, reason


def test_accepts_approximation_words_like_roughly_and_half():
    text = "Almost half of the repository's history is fairly recent, with most contributors still active."
    ok, reason = validate_output(text, PASSPORT_PACK)
    assert ok, reason


def test_accepts_known_enum_labels_appearing_in_prose():
    # "python" and "heuristic" are real fact-pack values -- snake_case/plain
    # words drawn from the fact pack itself must never be flagged.
    text = "This is a python codebase, and the difficulty score uses a heuristic formula."
    ok, reason = validate_output(text, PASSPORT_PACK)
    assert ok, reason


def test_accepts_risk_file_narrative_with_no_filename_mentioned():
    text = (
        "This file carries a high risk score of 0.85 with strong confidence, driven by "
        "substantial churn and complexity. It currently has a single expert, who is stale."
    )
    ok, reason = validate_output(text, RISK_PACK)
    assert ok, reason


def test_accepts_security_summary_counts_stated_plainly():
    text = (
        "History scanning turned up 3 credentials, 1 of which is still present today. "
        "Dependency scanning found 5 known vulnerabilities, 2 of them high severity."
    )
    ok, reason = validate_output(text, SECURITY_PACK)
    assert ok, reason


# ---------------------------------------------------------------------------
# REJECTED cases.
# ---------------------------------------------------------------------------


def test_rejects_a_number_with_no_basis_in_the_fact_pack():
    text = "This repository was created by 47 different organizations over its lifetime."
    ok, reason = validate_output(text, PASSPORT_PACK)
    assert not ok
    assert reason == "ungrounded_number"


def test_rejects_a_filename_not_in_the_fact_pack():
    text = "The riskiest part of this codebase is clearly app/services/billing.py."
    ok, reason = validate_output(text, RISK_PACK)
    assert not ok
    assert reason == "ungrounded_reference"


def test_rejects_a_path_shaped_token_even_without_a_known_extension():
    text = "Most of the risk here traces back to src/core/engine, which is heavily coupled."
    ok, reason = validate_output(text, RISK_PACK)
    assert not ok
    assert reason == "ungrounded_reference"


def test_rejects_a_person_name_shaped_as_an_unlisted_identifier():
    text = "The lead maintainer JaneDoe has driven most of the recent activity here."
    ok, reason = validate_output(text, PASSPORT_PACK)
    assert not ok
    assert reason == "ungrounded_reference"


def test_rejects_output_over_the_length_cap():
    text = "This repository is healthy. " * 30
    assert len(text) > MAX_OUTPUT_CHARS
    ok, reason = validate_output(text, PASSPORT_PACK)
    assert not ok
    assert reason == "too_long"


def test_rejects_a_plausible_but_wrong_rounding():
    # 0.62 (churn_concentration) does not round to 45 under any tolerance
    # this validator grants -- a model inventing a nearby-sounding number is
    # exactly the failure mode the rounding tolerance must NOT paper over.
    text = "About 45% of churn is concentrated in a handful of files."
    ok, reason = validate_output(text, PASSPORT_PACK)
    assert not ok
    assert reason == "ungrounded_number"


def test_rejects_a_hallucinated_percentage_close_to_but_not_derived_from_any_fact():
    text = "Confidence in this score sits at around 83%."
    ok, reason = validate_output(text, RISK_PACK)
    assert not ok
    assert reason == "ungrounded_number"


# ---------------------------------------------------------------------------
# build_prompt: rule 4 -- only computed numbers ever reach the prompt text.
# ---------------------------------------------------------------------------


def test_build_prompt_embeds_every_factpack_field_and_nothing_else():
    prompt = build_prompt(RISK_PACK)
    for key in RISK_PACK.model_dump():
        assert key in prompt
    # Never a path in the DATA section -- RiskFactPack has no field that
    # could ever hold one (the file itself is deliberately unnamed, see the
    # fact pack's own docstring). The fixed system-instructions text above
    # this section is allowed to contain an ordinary "/" (e.g. "key/value"),
    # so only the rendered facts are checked here.
    facts_section = prompt.split("Computed metrics for this repository:")[-1]
    assert "/" not in facts_section


def test_build_prompt_includes_the_system_instructions_verbatim_once():
    from app.narrative.generate import SYSTEM_PROMPT

    prompt = build_prompt(PASSPORT_PACK)
    assert prompt.count(SYSTEM_PROMPT) == 1


@pytest.mark.parametrize("fact_pack", [PASSPORT_PACK, RISK_PACK, SECURITY_PACK])
def test_build_prompt_never_raises_for_a_well_formed_factpack(fact_pack):
    build_prompt(fact_pack)
