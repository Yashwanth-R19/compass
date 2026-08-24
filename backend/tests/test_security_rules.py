"""Session 10, Part A/G: the keyword gate is not an optimization that can be
bolted on later -- without it, 25 regexes over millions of diff lines blows
the scan budget (Known Hazard #2). This asserts the gate is ACTUALLY used:
a rule whose keyword is absent from a line must never have its regex
evaluated at all.
"""

from dataclasses import replace
from unittest.mock import MagicMock

import app.security.scanner as scanner_module
from app.security.rules import RULES
from app.security.scanner import _match_line


def test_every_rule_has_at_least_one_keyword():
    for rule in RULES:
        assert rule.keywords, f"{rule.id} has no keywords -- the gate can't work for it"


def _rules_with_spied_regex(rule_id: str) -> tuple[list, MagicMock]:
    """``re.Pattern`` is a C-extension type and refuses attribute
    assignment (``patch.object`` on a compiled pattern raises
    "attribute 'search' is read-only") -- so the spy has to live on a
    stand-in object substituted for that one rule's ``regex`` field
    instead, wired in by swapping scanner.py's own module-level ``RULES``
    binding (its own ``from ... import RULES``, not the rules module's)."""
    original = next(r for r in RULES if r.id == rule_id)
    spy = MagicMock(wraps=original.regex.search)
    fake_regex = MagicMock()
    fake_regex.search = spy
    patched = replace(original, regex=fake_regex)
    new_rules = [patched if r.id == rule_id else r for r in RULES]
    return new_rules, spy


def test_keyword_gate_skips_regex_when_keyword_absent(monkeypatch):
    """A line containing NONE of a rule's keywords must never reach that
    rule's ``regex.search`` at all."""
    new_rules, spy = _rules_with_spied_regex("github-pat")
    monkeypatch.setattr(scanner_module, "RULES", new_rules)

    line_without_keyword = "this line has nothing interesting on it whatsoever"
    assert "ghp_" not in line_without_keyword

    hits = _match_line(line_without_keyword, path=None)
    spy.assert_not_called()
    assert hits == []


def test_keyword_gate_lets_matching_line_through_to_the_regex(monkeypatch):
    new_rules, spy = _rules_with_spied_regex("github-pat")
    monkeypatch.setattr(scanner_module, "RULES", new_rules)

    line_with_keyword = "token = ghp_" + "a" * 36
    _match_line(line_with_keyword, path=None)
    spy.assert_called_once()


def test_aws_access_key_id_matches_and_carries_no_entropy_threshold():
    hits = _match_line('aws_key = "AKIAQPMNBVCXZLKJHGFD"', path=None)
    assert len(hits) == 1
    rule, value, entropy = hits[0]
    assert rule.id == "aws-access-key-id"
    assert value == "AKIAQPMNBVCXZLKJHGFD"
    assert entropy is None


def test_github_fine_grained_pat_matches():
    token = "github_pat_" + "a" * 82
    hits = _match_line(f'export GITHUB_TOKEN="{token}"', path=None)
    assert any(rule.id == "github-pat-fine-grained" for rule, _, _ in hits)


def test_private_key_pem_matches():
    hits = _match_line("-----BEGIN RSA PRIVATE KEY-----", path=None)
    assert any(rule.id == "private-key-pem" for rule, _, _ in hits)


def test_postgres_connection_uri_with_credentials_matches():
    hits = _match_line(
        'DATABASE_URL = "postgres://myuser:mypassword123@db.internal-host.io:5432/prod"',
        path=None,
    )
    assert any(rule.id == "postgres-connection-uri" for rule, _, _ in hits)


def test_generic_high_entropy_rule_requires_entropy_threshold():
    rule = next(r for r in RULES if r.id == "generic-high-entropy-assignment")
    assert rule.entropy_threshold is not None

    # A low-entropy "secret" (all the same character) matches the shape but
    # must be rejected by the entropy check.
    hits = _match_line('secret_key = "aaaaaaaaaaaaaaaaaaaa"', path=None)
    assert not any(r.id == "generic-high-entropy-assignment" for r, _, _ in hits)


def test_lines_over_max_length_are_never_examined():
    """Known Hazard #3: a checked-in minified bundle emits enormous `+`
    lines -- these must be skipped before the keyword gate even runs, not
    just before the regex."""
    huge_line = 'token = "ghp_' + "a" * 36 + '"' + " " * 3000
    assert len(huge_line) > 2000
    assert _match_line(huge_line, path=None) == []
