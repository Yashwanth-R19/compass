"""Pure-Python tests for app/analysis/identities.py -- no DB needed, since
resolve_identities is deliberately DB-agnostic (session 05, Part A/G)."""

from datetime import UTC, datetime

from app.analysis.identities import (
    is_bot_name,
    mask_email,
    most_frequent_recent,
    resolve_identities,
)


def test_same_person_merges_across_email_name_and_noreply_alias():
    """Session 05 Part G's required positive fixture: three aliases of the
    same person must land in one identity.

    The merge chain: (Jane Doe, jane@corp.com) <-> (Jane Doe,
    1234+janedoe@users.noreply.github.com) via rule 3 (exact name match);
    (Jane Doe, jane@corp.com) <-> (jane, jane@gmail.com) via rule 4 (shared
    email local part "jane" across different domains) -- transitively all
    three land in the same union-find group.
    """
    commits = [
        ("Jane Doe", "jane@corp.com"),
        ("jane", "jane@gmail.com"),
        ("Jane Doe", "1234+janedoe@users.noreply.github.com"),
    ]
    identity_map = resolve_identities(commits)

    ids = {identity_map[pair] for pair in commits}
    assert (
        len(ids) == 1
    ), f"expected all three aliases to merge into one identity, got {identity_map}"


def test_generic_placeholder_name_does_not_merge_distinct_people():
    """Session 05 Part G's required negative fixture: two different people
    who both typed the generic placeholder name "Unknown" must NOT merge --
    conservatism is correct here even though it means an undercount."""
    commits = [("Unknown", "a@x.com"), ("Unknown", "b@y.com")]
    identity_map = resolve_identities(commits)

    assert identity_map[("Unknown", "a@x.com")] != identity_map[("Unknown", "b@y.com")]


def test_rule1_exact_email_match_merges():
    commits = [("Bob Smith", "bob@corp.com"), ("Robert Smith", "bob@corp.com")]
    identity_map = resolve_identities(commits)
    assert (
        identity_map[("Bob Smith", "bob@corp.com")]
        == identity_map[("Robert Smith", "bob@corp.com")]
    )


def test_rule2_noreply_login_merges_with_other_email_sharing_local_part():
    commits = [
        ("Alice", "999+alicedev@users.noreply.github.com"),
        ("Alice W", "alicedev@personal.example.com"),
    ]
    identity_map = resolve_identities(commits)
    assert (
        identity_map[("Alice", "999+alicedev@users.noreply.github.com")]
        == identity_map[("Alice W", "alicedev@personal.example.com")]
    )


def test_rule4_short_local_part_does_not_merge():
    """ "dev" is both short (<4 chars would fail, but "dev" is exactly 3) AND
    on the generic-word blocklist -- either reason alone is enough to block
    the merge; different people using dev@ addresses at two companies must
    not become one identity."""
    commits = [("Dev One", "dev@company-a.com"), ("Dev Two", "dev@company-b.com")]
    identity_map = resolve_identities(commits)
    assert (
        identity_map[("Dev One", "dev@company-a.com")]
        != identity_map[("Dev Two", "dev@company-b.com")]
    )


def test_rule4_generic_word_local_part_does_not_merge_even_if_long_enough():
    commits = [("CI Bot A", "no-reply@service-a.com"), ("CI Bot B", "no-reply@service-b.com")]
    identity_map = resolve_identities(commits)
    assert (
        identity_map[("CI Bot A", "no-reply@service-a.com")]
        != identity_map[("CI Bot B", "no-reply@service-b.com")]
    )


def test_no_fuzzy_matching_of_similar_but_distinct_names():
    """Two genuinely different people whose names merely look similar must
    never merge -- there is no fuzzy-matching rule in this module at all."""
    commits = [("Jon Smith", "jon.smith@a.com"), ("John Smith", "john.smith@b.com")]
    identity_map = resolve_identities(commits)
    assert (
        identity_map[("Jon Smith", "jon.smith@a.com")]
        != identity_map[("John Smith", "john.smith@b.com")]
    )


def test_bot_names_are_flagged():
    assert is_bot_name("dependabot[bot]")
    assert is_bot_name("  Github-Actions[BOT]  ")
    assert not is_bot_name("Jane Doe")


def test_two_different_bots_do_not_merge_by_name_alone():
    """Both "renovate[bot]"-style names are excluded from rule 3's name-match
    entirely (anything ending [bot]), so two distinct bot accounts with
    different emails stay distinct identities."""
    commits = [("renovate[bot]", "1@bots.example.com"), ("renovate[bot]", "2@bots.example.com")]
    identity_map = resolve_identities(commits)
    assert (
        identity_map[("renovate[bot]", "1@bots.example.com")]
        != identity_map[("renovate[bot]", "2@bots.example.com")]
    )


def test_most_frequent_recent_picks_majority_then_latest():
    t1 = datetime(2020, 1, 1, tzinfo=UTC)
    t2 = datetime(2021, 1, 1, tzinfo=UTC)
    t3 = datetime(2022, 1, 1, tzinfo=UTC)
    # "Jane Doe" appears twice (more frequent) -- wins outright.
    assert most_frequent_recent([("Jane Doe", t1), ("jane", t2), ("Jane Doe", t3)]) == "Jane Doe"
    # A tie in count: whichever occurred most recently wins.
    assert most_frequent_recent([("A", t1), ("B", t2)]) == "B"


def test_mask_email_shows_first_char_and_domain_only():
    assert mask_email("jane@corp.com") == "j***@corp.com"
    assert mask_email("a@b.co") == "a***@b.co"


def test_mask_email_never_returns_a_malformed_value_unmasked():
    """A value with no "@" is still masked from its first character rather
    than returned as-is -- it could just as easily BE the sensitive raw
    value, and plan/RULES.md sec 11.2 says no unmasked email leaves the
    server, full stop, not "unless it looks malformed"."""
    assert mask_email("not-an-email") == "n***"
    assert mask_email("@corp.com") == "***@corp.com"
    assert mask_email("") == ""
