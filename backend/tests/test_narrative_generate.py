"""Prompting and, above all, the output validator -- "test this harder than
anything else in this package... it is the guarantee." Table-driven, with at
least as many carefully-constructed ACCEPTED examples as REJECTED ones
(Known Hazard #1: a validator whose acceptance tests are thin looks correct
while shipping a dead feature).

No network, no DB -- ``validate_output``/``build_prompt`` are pure functions
over a fact pack and a candidate string.
"""

import pytest

from app.narrative.factpack import RepoFactPack
from app.narrative.generate import (
    MAX_OUTPUT_CHARS,
    build_prompt,
    validate_output,
)

REPO_PACK = RepoFactPack(
    calibration="heuristic",
    file_count=248,
    loc=41000,
    commit_count=1893,
    contributor_count=12,
    subsystem_count=7,
    truck_factor=2,
    health_score=71.0,
    high_risk_ratio=0.18,
    cycle_count=2,
    hidden_dependency_count=4,
    onboarding_difficulty=62.4,
    finding_count_high=3,
    finding_count_med=8,
    finding_count_low=5,
    secret_count_still_in_head=1,
    secret_count_history_only=2,
    vulnerability_count_high=2,
    vulnerability_count_med=2,
    vulnerability_count_low=1,
    vulnerability_count_unknown=0,
)


# ---------------------------------------------------------------------------
# ACCEPTED cases -- written as carefully as the rejected ones (Known Hazard #1).
# ---------------------------------------------------------------------------


def test_accepts_fully_grounded_output_with_exact_numbers():
    text = (
        "This repository has 248 files and 12 contributors, with 2 as the truck factor. "
        "Onboarding difficulty is 62.4 out of 100, reflecting a health score of 71."
    )
    ok, reason = validate_output(text, REPO_PACK)
    assert ok, reason


def test_accepts_rounded_integer_from_a_decimal_fact_value():
    # 62.4 -> "about 62" (the rounding tolerance's own worked example).
    text = (
        "Onboarding difficulty here is about 62, which is on the higher side for a repo this size."
    )
    ok, reason = validate_output(text, REPO_PACK)
    assert ok, reason


def test_accepts_percentage_phrasing_of_a_ratio_rounded_to_the_nearest_ten():
    # high_risk_ratio=0.18 -> "roughly 20%".
    text = "Roughly 20% of files are flagged as high risk."
    ok, reason = validate_output(text, REPO_PACK)
    assert ok, reason


def test_accepts_approximation_words_like_roughly_and_half():
    text = "Almost half of the findings here are lower severity, with most of the history clean."
    ok, reason = validate_output(text, REPO_PACK)
    assert ok, reason


def test_accepts_known_enum_labels_appearing_in_prose():
    # "heuristic" is a real fact-pack value -- a fixed calibration label
    # drawn from the fact pack itself must never be flagged as ungrounded.
    text = "The difficulty and risk scores here use a heuristic calibration, not a live corpus."
    ok, reason = validate_output(text, REPO_PACK)
    assert ok, reason


def test_accepts_security_and_health_counts_stated_plainly():
    text = (
        "Health scores 71 out of 100, with 2 dependency cycles and 4 hidden dependencies. "
        "History scanning turned up 1 credential still present today and 2 only in past "
        "commits, alongside 2 high-severity dependency vulnerabilities."
    )
    ok, reason = validate_output(text, REPO_PACK)
    assert ok, reason


# ---------------------------------------------------------------------------
# REJECTED cases.
# ---------------------------------------------------------------------------


def test_rejects_a_number_with_no_basis_in_the_fact_pack():
    text = "This repository was created by 47 different organizations over its lifetime."
    ok, reason = validate_output(text, REPO_PACK)
    assert not ok
    assert reason == "ungrounded_number"


def test_rejects_a_filename_not_in_the_fact_pack():
    text = "The riskiest part of this codebase is clearly app/services/billing.py."
    ok, reason = validate_output(text, REPO_PACK)
    assert not ok
    assert reason == "ungrounded_reference"


def test_rejects_a_path_shaped_token_even_without_a_known_extension():
    text = "Most of the risk here traces back to src/core/engine, which is heavily coupled."
    ok, reason = validate_output(text, REPO_PACK)
    assert not ok
    assert reason == "ungrounded_reference"


def test_rejects_a_person_name_shaped_as_an_unlisted_identifier():
    text = "The lead maintainer JaneDoe has driven most of the recent activity here."
    ok, reason = validate_output(text, REPO_PACK)
    assert not ok
    assert reason == "ungrounded_reference"


def test_rejects_output_over_the_length_cap():
    text = "This repository is healthy. " * 30
    assert len(text) > MAX_OUTPUT_CHARS
    ok, reason = validate_output(text, REPO_PACK)
    assert not ok
    assert reason == "too_long"


def test_rejects_a_plausible_but_wrong_rounding():
    # 0.18 (high_risk_ratio) does not round to 45% under any tolerance this
    # validator grants -- a model inventing a nearby-sounding number is
    # exactly the failure mode the rounding tolerance must NOT paper over.
    text = "About 45% of files here are high risk."
    ok, reason = validate_output(text, REPO_PACK)
    assert not ok
    assert reason == "ungrounded_number"


def test_rejects_a_hallucinated_percentage_close_to_but_not_derived_from_any_fact():
    text = "Confidence in this repository's health sits at around 83%."
    ok, reason = validate_output(text, REPO_PACK)
    assert not ok
    assert reason == "ungrounded_number"


def test_rejects_text_cut_off_mid_sentence():
    # A real, observed failure mode: a provider hits its token ceiling
    # before finishing (e.g. a "thinking" model's visible answer gets cut
    # off after a few words) and the fragment can still be fully grounded
    # and under the length cap -- no other check here would catch it.
    text = "This repository has 248 files and 12"
    ok, reason = validate_output(text, REPO_PACK)
    assert not ok
    assert reason == "looks_truncated"


def test_accepts_a_sentence_ending_in_a_quoted_question_mark():
    # The terminal-punctuation check must not be so strict it rejects a
    # normal closing quotation mark or parenthesis after the punctuation.
    text = 'Health scores 71 out of 100 here — is that "healthy enough?"'
    ok, reason = validate_output(text, REPO_PACK)
    assert ok, reason


# ---------------------------------------------------------------------------
# build_prompt: rule 4 -- only computed numbers ever reach the prompt text.
# ---------------------------------------------------------------------------


def test_build_prompt_embeds_every_factpack_field_and_nothing_else():
    prompt = build_prompt(REPO_PACK)
    for key in REPO_PACK.model_dump():
        assert key in prompt
    # Never a path in the DATA section -- RepoFactPack has no field that
    # could ever hold one. The fixed system-instructions text above this
    # section is allowed to contain an ordinary "/" (e.g. "key/value"), so
    # only the rendered facts are checked here.
    facts_section = prompt.split("Computed metrics for this repository:")[-1]
    assert "/" not in facts_section


def test_build_prompt_includes_the_system_instructions_verbatim_once():
    from app.narrative.generate import SYSTEM_PROMPT

    prompt = build_prompt(REPO_PACK)
    assert prompt.count(SYSTEM_PROMPT) == 1


def test_build_prompt_never_raises_for_a_well_formed_factpack():
    build_prompt(REPO_PACK)


@pytest.mark.parametrize("calibration", ["heuristic", "corpus"])
def test_build_prompt_never_raises_for_either_calibration_label(calibration):
    build_prompt(REPO_PACK.model_copy(update={"calibration": calibration}))
