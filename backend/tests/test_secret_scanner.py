"""Session 10, Part A/D/G. THE MOST IMPORTANT TEST in this session lives
here: ``test_secret_committed_then_deleted_is_found_with_still_in_head_false``
-- a fake-but-pattern-matching AWS key committed in commit 2 and deleted in
commit 4, found with ``still_in_head=False``. This is the demo, encoded.

Fixture secrets in this file are all obviously-fake, pattern-shaped values
(Part D.5) -- e.g. ``AKIAQPMNBVCXZLKJHGFD``, a syntactically valid AWS
access-key shape that was never issued by AWS and could never be a real
credential.
"""

import subprocess
from pathlib import Path

import pytest

from app.security.scanner import (
    ScanResult,
    _fingerprint,
    _is_allowlisted,
    _redact,
    _shannon_entropy,
    scan_history,
)

FAKE_AWS_KEY = "AKIAQPMNBVCXZLKJHGFD"
TEST_SALT = "test-fixture-salt"


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _init_repo(root: Path) -> Path:
    repo_dir = root / "secret-fixture-repo"
    repo_dir.mkdir()
    _git(repo_dir, "init", "-b", "main")
    _git(repo_dir, "config", "user.email", "test@example.com")
    _git(repo_dir, "config", "user.name", "Test User")
    _git(repo_dir, "config", "commit.gpgsign", "false")
    return repo_dir


@pytest.fixture
def deleted_secret_repo(tmp_path):
    """commit 1: a plain file. commit 2: adds a fake AWS key. commit 3: an
    unrelated change. commit 4: deletes the file containing the key."""
    repo_dir = _init_repo(tmp_path)

    (repo_dir / "app.py").write_text("print('hello')\n")
    _git(repo_dir, "add", "app.py")
    _git(repo_dir, "commit", "-m", "commit 1: initial")

    (repo_dir / "config.py").write_text(f'AWS_KEY = "{FAKE_AWS_KEY}"\n')
    _git(repo_dir, "add", "config.py")
    _git(repo_dir, "commit", "-m", "commit 2: add config with key")

    with open(repo_dir / "app.py", "a") as f:
        f.write("print('more')\n")
    _git(repo_dir, "add", "app.py")
    _git(repo_dir, "commit", "-m", "commit 3: unrelated change")

    _git(repo_dir, "rm", "config.py")
    _git(repo_dir, "commit", "-m", "commit 4: remove config")

    return repo_dir


def test_secret_committed_then_deleted_is_found_with_still_in_head_false(deleted_secret_repo):
    """THE MOST IMPORTANT TEST IN THIS SESSION (Part G). This is the demo:
    Compass finds a credential that was committed and later deleted, and
    it is still recoverable from public git history."""
    result = scan_history(str(deleted_secret_repo), salt=TEST_SALT)

    aws_hits = [h for h in result.hits if h.rule_id == "aws-access-key-id"]
    assert len(aws_hits) == 1
    hit = aws_hits[0]

    assert hit.still_in_head is False
    assert hit.path == "config.py"
    assert hit.line_number == 1
    assert result.commits_scanned == 4
    assert result.truncated is False


def test_stored_hit_contains_no_reconstructible_substring_of_the_secret(deleted_secret_repo):
    """Part D.1/D "assert the stored row contains no substring of the fake
    secret beyond the redacted preview's first 4 characters" -- checks
    every string field on the SecretHit dataclass itself (the same fields
    that get persisted verbatim to secret_hits)."""
    result = scan_history(str(deleted_secret_repo), salt=TEST_SALT)
    hit = next(h for h in result.hits if h.rule_id == "aws-access-key-id")

    # The only field allowed to contain any part of the secret at all is
    # redacted_preview, and even then only its first-4/last-2 characters.
    assert hit.redacted_preview == FAKE_AWS_KEY[:4] + "*" * 16 + FAKE_AWS_KEY[-2:]

    forbidden_middle = FAKE_AWS_KEY[4:-2]  # the masked-out middle portion
    assert forbidden_middle not in hit.redacted_preview
    assert FAKE_AWS_KEY not in hit.redacted_preview
    assert FAKE_AWS_KEY not in hit.fingerprint
    assert forbidden_middle not in hit.fingerprint
    assert FAKE_AWS_KEY not in hit.description
    assert FAKE_AWS_KEY not in (hit.path or "")

    # And the full secret must never appear ANYWHERE in the dataclass's repr
    # either -- the belt-and-suspenders check.
    assert FAKE_AWS_KEY not in repr(hit)


def test_still_in_head_true_when_secret_survives(tmp_path):
    repo_dir = _init_repo(tmp_path)
    (repo_dir / "config.py").write_text(f'AWS_KEY = "{FAKE_AWS_KEY}"\n')
    _git(repo_dir, "add", "config.py")
    _git(repo_dir, "commit", "-m", "add key, never removed")

    result = scan_history(str(repo_dir), salt=TEST_SALT)
    hit = next(h for h in result.hits if h.rule_id == "aws-access-key-id")
    assert hit.still_in_head is True


def test_still_in_head_is_false_when_line_removed_but_file_survives(tmp_path):
    """Session 10 Known Hazard #7: still_in_head must NOT be inferred from
    "does the file still exist" -- a file can survive while the specific
    secret line is removed from it."""
    repo_dir = _init_repo(tmp_path)
    (repo_dir / "config.py").write_text(f'AWS_KEY = "{FAKE_AWS_KEY}"\nOTHER = 1\n')
    _git(repo_dir, "add", "config.py")
    _git(repo_dir, "commit", "-m", "add key")

    (repo_dir / "config.py").write_text("OTHER = 1\n")
    _git(repo_dir, "add", "config.py")
    _git(repo_dir, "commit", "-m", "remove key line, keep file")

    result = scan_history(str(repo_dir), salt=TEST_SALT)
    hit = next(h for h in result.hits if h.rule_id == "aws-access-key-id")
    assert hit.still_in_head is False


# ---------------------------------------------------------------------------
# Allowlist (Part A)
# ---------------------------------------------------------------------------


def test_allowlisted_aws_docs_example_key_produces_no_hit(tmp_path):
    repo_dir = _init_repo(tmp_path)
    (repo_dir / "docs.py").write_text('AWS_KEY = "AKIAIOSFODNN7EXAMPLE"\n')
    _git(repo_dir, "add", "docs.py")
    _git(repo_dir, "commit", "-m", "add docs example")

    result = scan_history(str(repo_dir), salt=TEST_SALT)
    assert result.hits == []


def test_allowlisted_env_example_file_produces_no_hit(tmp_path):
    repo_dir = _init_repo(tmp_path)
    (repo_dir / ".env.example").write_text(f'AWS_KEY="{FAKE_AWS_KEY}"\n')
    _git(repo_dir, "add", ".env.example")
    _git(repo_dir, "commit", "-m", "add env example")

    result = scan_history(str(repo_dir), salt=TEST_SALT)
    assert result.hits == []


def test_allowlisted_test_fixtures_path_produces_no_hit(tmp_path):
    repo_dir = _init_repo(tmp_path)
    fixtures_dir = repo_dir / "tests" / "fixtures"
    fixtures_dir.mkdir(parents=True)
    (fixtures_dir / "creds.py").write_text(f'AWS_KEY = "{FAKE_AWS_KEY}"\n')
    _git(repo_dir, "add", "tests/fixtures/creds.py")
    _git(repo_dir, "commit", "-m", "add fixture creds")

    result = scan_history(str(repo_dir), salt=TEST_SALT)
    assert result.hits == []


def test_allowlisted_lockfile_integrity_hash_produces_no_hit(tmp_path):
    repo_dir = _init_repo(tmp_path)
    lockfile_content = (
        '{"name": "x", "lockfileVersion": 2, "packages": {"node_modules/foo": '
        '{"integrity": "sha512-abcXYZ0123456789abcXYZ0123456789abcXYZ0123456789abcXYZ0123456789=="}}}\n'
    )
    (repo_dir / "package-lock.json").write_text(lockfile_content)
    _git(repo_dir, "add", "package-lock.json")
    _git(repo_dir, "commit", "-m", "add lockfile")

    result = scan_history(str(repo_dir), salt=TEST_SALT)
    assert result.hits == []


def test_is_allowlisted_directly_for_each_documented_case():
    assert _is_allowlisted("k = AKIAIOSFODNN7EXAMPLE", None, "AKIAIOSFODNN7EXAMPLE")
    assert _is_allowlisted("k = x", "config.sample.json", "somevalue1234567890")
    assert _is_allowlisted("k = x", "settings.template.yaml", "somevalue1234567890")
    assert _is_allowlisted("k = x", "a/b/__fixtures__/c.py", "somevalue1234567890")
    assert _is_allowlisted(
        "data:image/png;base64,AAAABBBBCCCCDDDDEEEEFFFF", None, "AAAABBBBCCCCDDDDEEEEFFFF"
    )
    assert not _is_allowlisted("k = " + FAKE_AWS_KEY, "config.py", FAKE_AWS_KEY)


# ---------------------------------------------------------------------------
# Redaction / entropy
# ---------------------------------------------------------------------------


def test_redact_short_value_produces_no_preview_at_all():
    assert _redact("short1") is None  # < 12 chars


def test_redact_produces_fixed_length_mask_regardless_of_secret_length():
    short = _redact("a" * 12)
    long = _redact("b" * 60)
    assert short is not None and long is not None
    assert short.count("*") == long.count("*") == 16


def test_shannon_entropy_low_for_repeated_character():
    assert _shannon_entropy("aaaaaaaaaa") == 0.0


def test_shannon_entropy_positive_for_varied_string():
    assert _shannon_entropy("Tr0ub4dor&3xyz123") > 2.0


def test_fingerprint_is_stable_for_same_salt_rule_and_value():
    a = _fingerprint(TEST_SALT, "aws-access-key-id", FAKE_AWS_KEY)
    b = _fingerprint(TEST_SALT, "aws-access-key-id", FAKE_AWS_KEY)
    assert a == b


def test_fingerprint_differs_across_salts():
    a = _fingerprint("salt-one", "aws-access-key-id", FAKE_AWS_KEY)
    b = _fingerprint("salt-two", "aws-access-key-id", FAKE_AWS_KEY)
    assert a != b


def test_fingerprint_never_contains_the_raw_value():
    fp = _fingerprint(TEST_SALT, "aws-access-key-id", FAKE_AWS_KEY)
    assert FAKE_AWS_KEY not in fp


# ---------------------------------------------------------------------------
# Budget guard (Part A / Known Hazard #1)
# ---------------------------------------------------------------------------


def test_scan_caps_engage_and_are_reported_honestly(monkeypatch, tmp_path):
    """Caps must engage and truncation must be reported -- never silent."""
    import app.security.scanner as scanner_module

    repo_dir = _init_repo(tmp_path)
    for i in range(5):
        (repo_dir / f"file{i}.py").write_text(f"x = {i}\n")
        _git(repo_dir, "add", f"file{i}.py")
        _git(repo_dir, "commit", "-m", f"commit {i}")

    # A byte budget small enough that even the first commit's header line
    # trips it -- forces truncated=True deterministically.
    monkeypatch.setattr(scanner_module, "MAX_SCAN_BYTES", 1)

    result = scan_history(str(repo_dir), salt=TEST_SALT)
    assert result.truncated is True
    assert result.truncation_reason is not None
    assert "scanned the most recent" in result.truncation_reason


def test_scan_result_is_the_documented_dataclass_shape():
    result = ScanResult(hits=[], commits_scanned=0, truncated=False)
    assert result.truncation_reason is None
