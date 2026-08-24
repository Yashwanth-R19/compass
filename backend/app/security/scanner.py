"""Secret scanning over a repository's FULL commit history, including
deleted secrets (session 10, Part A) -- the demo this session exists to
build: *"we found a credential that was committed and later deleted, and
it's still recoverable from public git history."*

======================================================================
NEVER RE-LEAK A SECRET (Part D) -- read this before changing anything here
======================================================================

Compass finds credentials. It must not become a way to read them. Five
rules, enforced structurally, not by convention:

1. **Never store the raw secret value.** Only a salted SHA-256
   ``fingerprint`` (``_fingerprint``, salt from ``app.config.settings``) and
   a ``redacted_preview`` -- the first 4 and last 2 characters, with a
   FIXED-length mask in between (``ghp_****************Xq``), regardless of
   the real secret's length -- are ever computed or persisted. A captured
   value shorter than ``MIN_PREVIEW_LENGTH`` (12) gets NO preview at all
   (``_redact`` returns ``None``).
2. **Never log a secret value, at any log level, in any environment.** This
   module contains no ``logging``/``print`` call that could receive one --
   verified by ``tests/test_secret_scanner.py``.
3. **Never include a secret value in an API response, an error message, or
   ``analysis_runs.error``.** ``SecretHit`` (this module's return type) and
   ``app.db.models.SecretHit`` (the persisted row) both carry only
   ``fingerprint``/``redacted_preview``/metadata -- there is no field either
   could put a raw value in even by accident.
4. **Secret findings on a private repository are visible only to the
   repository owner -- never through a share link.** Enforced in
   ``app/auth/deps.py::secret_findings_visible``, called explicitly by
   ``GET /repos/{id}/secrets`` on top of (not instead of)
   ``require_repo_access``. A share link is for showing someone your
   architecture, not your leaked credentials.
5. **This module's own test fixtures use obviously-fake values** that match
   the rule shapes but could never be real credentials (see
   ``tests/test_secret_scanner.py``'s fixture generator).

======================================================================

``scan_history(repo_path, salt) -> ScanResult`` streams ``git log -p -U0``
(never buffers the whole diff -- the same streaming discipline
``app/ingestion/miner.py::_run_git_log`` already established for
``--numstat``), examines only ADDED lines, and reports which hits are
``still_in_head`` via a second pass over the current working tree.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
import subprocess
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from sqlalchemy import insert
from sqlalchemy.orm import Session

from app.db.models import SecretHit as SecretHitRow
from app.ingestion.miner import IGNORE_DIRS, MAX_FILE_BYTES
from app.ingestion.miner import _parse_git_datetime as _parse_commit_datetime
from app.security.rules import RULES, SecretRule

MAX_SCAN_BYTES = 2_000_000_000
"""Budget guard (Part A): total bytes of diff text read before the scan
stops early and reports a partial result -- never silently truncates, see
ScanResult.truncated/truncation_reason."""

MAX_SCAN_SECONDS = 60.0
"""Wall-clock budget guard, checked alongside MAX_SCAN_BYTES."""

MAX_LINE_LENGTH = 2000
"""Session 10 Known Hazard #3: a checked-in minified bundle or a large JSON
fixture can emit a single enormous `+` line. Every rule's regex is at worst
linear-ish in line length, but 25 rules over a multi-megabyte single line
(itself already a code smell, never a real credential) is a real, avoidable
cost -- lines longer than this are skipped entirely, before the keyword
gate even runs."""

_GIT_LOG_P_FORMAT = "%x1eCOMMIT%x1f%H%x1f%aI"
GIT_LOG_P_CMD = [
    "git",
    "log",
    "-p",
    "-U0",
    "--no-merges",
    "--no-color",
    # --no-renames: same determinism reasoning as miner.py's own git log
    # command -- without it, a repo/global `diff.renames=true` config could
    # turn an add+delete into a rename diff (`rename from`/`rename to`,
    # possibly no `+` lines at all for an unmodified-but-renamed file),
    # which would silently make a still-present secret look deleted.
    "--no-renames",
    f"--format={_GIT_LOG_P_FORMAT}",
]

_COMMIT_HEADER_RE = re.compile(r"^\x1eCOMMIT\x1f([0-9a-fA-F]{40})\x1f(.+)$")
_HUNK_HEADER_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")

FIXED_MASK_LENGTH = 16
MIN_PREVIEW_LENGTH = 12
"""Part D.1: a captured value shorter than this gets no preview at all --
there isn't enough room to redact a meaningful middle section without the
"preview" being most of the secret."""


@dataclass
class SecretHit:
    """One detected secret occurrence -- never carries the raw value, only
    ``fingerprint``/``redacted_preview`` (Part D.1). ``path`` is
    repo-relative; resolved to a ``repo_paths.id`` (nullable) only at
    persistence time (``persist_secret_hits``), since this module has no DB
    access at all."""

    rule_id: str
    description: str
    path: str | None
    commit_sha: str
    committed_at: datetime
    line_number: int | None
    fingerprint: str
    redacted_preview: str | None
    entropy: float | None
    still_in_head: bool = False


@dataclass
class ScanResult:
    hits: list[SecretHit]
    commits_scanned: int
    truncated: bool
    truncation_reason: str | None = None


def _shannon_entropy(value: str) -> float:
    if not value:
        return 0.0
    length = len(value)
    counts = Counter(value)
    return -sum((c / length) * math.log2(c / length) for c in counts.values())


def _normalize_secret_value(value: str) -> str:
    return value.strip()


def _fingerprint(salt: str, rule_id: str, value: str) -> str:
    """Salted SHA-256 over (salt, rule_id, normalized value) -- Known Hazard
    #8: the salt MUST be stable across the history scan and the working-tree
    scan within one run (both call this with the SAME ``salt``, read once
    from config), or ``still_in_head`` matching silently breaks, and stable
    across runs/repos, or cross-run deduplication silently breaks."""
    normalized = _normalize_secret_value(value)
    digest = hashlib.sha256(f"{salt}:{rule_id}:{normalized}".encode()).hexdigest()
    return digest


def _redact(value: str) -> str | None:
    normalized = _normalize_secret_value(value)
    if len(normalized) < MIN_PREVIEW_LENGTH:
        return None
    return f"{normalized[:4]}{'*' * FIXED_MASK_LENGTH}{normalized[-2:]}"


# ---- False-positive allowlist (Part A), each entry documented ----

_ALLOWLIST_VALUE_MARKERS = (
    "example",
    "sample",
    "dummy",
    "test",
    "placeholder",
    "changeme",
    "xxxx",
    "your-key-here",
)
"""A captured value containing any of these (case-insensitively) is a
documentation/sample credential, not a real one -- covers the canonical AWS
docs key ``AKIAIOSFODNN7EXAMPLE`` and the usual placeholder vocabulary."""

_ALLOWLIST_PATH_SEGMENTS = ("fixtures", "__fixtures__", "testdata", "test_data")
"""Paths under a test-fixtures directory, at any depth."""

_ALLOWLIST_PATH_MARKERS = (".example", ".sample", ".template")
"""``.env.example``, ``config.sample.json``, ``settings.template.yaml`` --
a file whose own name says "this is a template," not a live config. Checked
as a substring of the basename (not just a suffix): ``config.sample.json``
carries a real extension AFTER ``.sample``, so a suffix-only check would
miss it."""


def _is_allowlisted(line: str, path: str | None, value: str) -> bool:
    value_lower = value.lower()
    if any(marker in value_lower for marker in _ALLOWLIST_VALUE_MARKERS):
        return True

    if path is not None:
        path_lower = path.lower()
        if any(seg in path_lower.split("/") for seg in _ALLOWLIST_PATH_SEGMENTS):
            return True
        basename = path_lower.rsplit("/", 1)[-1]
        if any(marker in basename for marker in _ALLOWLIST_PATH_MARKERS):
            return True
        # Lockfile integrity hashes (npm's package-lock.json "integrity"
        # field) are content hashes, not credentials -- sha512-/sha256-
        # prefixed base64, specifically in that one file.
        if path.endswith("package-lock.json") and (
            value.startswith("sha512-") or value.startswith("sha256-")
        ):
            return True

    # Base64 image data URIs are high-entropy by construction but are image
    # bytes, never a credential.
    return "data:image/" in line and ";base64," in line


def _match_line(text: str, path: str | None) -> list[tuple[SecretRule, str, float | None]]:
    """Applies the keyword gate, then every rule's regex, then its entropy
    threshold (if any), then the allowlist. Returns (rule, value, entropy)
    for every surviving hit -- a line can match more than one rule."""
    if len(text) > MAX_LINE_LENGTH:
        return []

    text_lower = text.lower()
    hits: list[tuple[SecretRule, str, float | None]] = []
    for rule in RULES:
        # THE KEYWORD GATE (Known Hazard #2): a cheap substring pre-check
        # before the comparatively expensive regex. Without this, 25 regexes
        # x millions of diff lines blows the 60s budget on a medium repo --
        # see tests/test_security_rules.py's spy-based proof this is
        # actually load-bearing, not decorative.
        if not any(keyword in text_lower for keyword in rule.keywords):
            continue

        match = rule.regex.search(text)
        if match is None:
            continue
        value = match.group(1) if match.lastindex else match.group(0)

        entropy: float | None = None
        if rule.entropy_threshold is not None:
            entropy = _shannon_entropy(value)
            if entropy < rule.entropy_threshold:
                continue

        if _is_allowlisted(text, path, value):
            continue

        hits.append((rule, value, entropy))
    return hits


def _run_git_log_p(repo_path: str) -> subprocess.Popen:
    # Never subprocess.run(capture_output=True) -- see miner.py's own
    # _run_git_log docstring for why: a `git log -p` on a 10k-commit repo
    # can be hundreds of MB, and buffering it all defeats the whole point of
    # a budget guard. Popen + line-by-line iteration keeps peak memory
    # bounded regardless of the budget caps below.
    return subprocess.Popen(
        GIT_LOG_P_CMD,
        cwd=repo_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


@dataclass
class _RawHit:
    rule_id: str
    description: str
    path: str | None
    commit_sha: str
    committed_at: datetime
    line_number: int | None
    value: str
    entropy: float | None


@dataclass
class _ScanState:
    current_sha: str | None = None
    current_committed_at: datetime | None = None
    current_path: str | None = None
    next_line_number: int | None = None
    commits_scanned: int = 0
    raw_hits: list[_RawHit] = field(default_factory=list)


def _process_line(line: str, state: _ScanState) -> None:
    header_match = _COMMIT_HEADER_RE.match(line)
    if header_match:
        state.current_sha = header_match.group(1)
        state.current_committed_at = _parse_commit_datetime(header_match.group(2))
        state.current_path = None
        state.next_line_number = None
        state.commits_scanned += 1
        return

    if line.startswith("diff --git "):
        state.current_path = None
        state.next_line_number = None
        return

    if line.startswith("+++ "):
        target = line[4:]
        state.current_path = None if target == "/dev/null" else target.removeprefix("b/")
        return

    hunk_match = _HUNK_HEADER_RE.match(line)
    if hunk_match:
        state.next_line_number = int(hunk_match.group(1))
        return

    # Only ADDED lines are ever examined (Part A) -- a removed line means
    # the secret, if any, was already counted the commit it was added in.
    # "+++ " (the file header) is excluded by the branch above running first.
    if line.startswith("+"):
        added_text = line[1:]
        path = state.current_path
        if _is_ignored_path(path):
            pass
        elif state.current_sha is not None and state.current_committed_at is not None:
            for rule, value, entropy in _match_line(added_text, path):
                state.raw_hits.append(
                    _RawHit(
                        rule_id=rule.id,
                        description=rule.description,
                        path=path,
                        commit_sha=state.current_sha,
                        committed_at=state.current_committed_at,
                        line_number=state.next_line_number,
                        value=value,
                        entropy=entropy,
                    )
                )
        if state.next_line_number is not None:
            state.next_line_number += 1
        return

    # "-" (removed) lines never advance next_line_number -- with -U0, only
    # +/- lines appear at all (no context lines), and new-file line numbers
    # only advance on lines that exist in the NEW file.


def _is_ignored_path(path: str | None) -> bool:
    if path is None:
        return False
    return any(segment in IGNORE_DIRS for segment in path.split("/"))


def _scan_diff_stream(repo_path: str) -> tuple[_ScanState, bool, str | None]:
    start = time.monotonic()
    bytes_scanned = 0
    truncated = False
    truncation_reason: str | None = None
    state = _ScanState()

    proc = _run_git_log_p(repo_path)
    try:
        assert proc.stdout is not None
        for raw_line in proc.stdout:
            line = raw_line.rstrip("\n")
            bytes_scanned += len(line.encode("utf-8", errors="replace")) + 1

            _process_line(line, state)

            if bytes_scanned >= MAX_SCAN_BYTES:
                truncated = True
                truncation_reason = (
                    f"scanned the most recent {state.commits_scanned} commits "
                    "(byte budget reached)"
                )
                break
            if time.monotonic() - start >= MAX_SCAN_SECONDS:
                truncated = True
                truncation_reason = (
                    f"scanned the most recent {state.commits_scanned} commits "
                    "(time budget reached)"
                )
                break
    finally:
        if proc.stdout is not None:
            proc.stdout.close()
        if proc.poll() is None:
            proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        if proc.stderr is not None:
            proc.stderr.close()

    return state, truncated, truncation_reason


def _scan_working_tree(repo_path: str) -> set[tuple[str, str]]:
    """Second pass (Part A: "determine for each hit whether the secret is
    still present in HEAD") -- runs the SAME rules over the checked-out
    working tree (the clone IS a checkout of HEAD) and returns the set of
    (rule_id, value) pairs found, so ``scan_history`` can match by
    (rule_id, fingerprint) after fingerprinting both sides with the same
    salt. Reuses the miner's own IGNORE_DIRS/MAX_FILE_BYTES walk discipline.
    """
    root = Path(repo_path)
    found: set[tuple[str, str]] = set()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS]
        for fname in filenames:
            full_path = Path(dirpath) / fname
            try:
                if full_path.stat().st_size > MAX_FILE_BYTES:
                    continue
                content = full_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            rel_path = full_path.relative_to(root).as_posix()
            for line in content.splitlines():
                for rule, value, _entropy in _match_line(line, rel_path):
                    found.add((rule.id, _normalize_secret_value(value)))
    return found


def scan_history(repo_path: str, *, salt: str) -> ScanResult:
    """Streams ``git log -p -U0`` for ``repo_path`` (a local clone),
    detects secrets in every ADDED line across the full history, then scans
    the current working tree to determine ``still_in_head`` per hit.

    Budget-guarded (MAX_SCAN_BYTES/MAX_SCAN_SECONDS) -- if a cap engages,
    ``truncated=True`` and ``truncation_reason`` states honestly that only
    the most recent N commits were scanned (git's own default traversal
    order is newest-first, which is what makes "truncated early" mean
    "scanned the most recent N commits" rather than an arbitrary subset).
    Never silently drops the fact that it was truncated.
    """
    state, truncated, truncation_reason = _scan_diff_stream(repo_path)

    hits = [
        SecretHit(
            rule_id=h.rule_id,
            description=h.description,
            path=h.path,
            commit_sha=h.commit_sha,
            committed_at=h.committed_at,
            line_number=h.line_number,
            fingerprint=_fingerprint(salt, h.rule_id, h.value),
            redacted_preview=_redact(h.value),
            entropy=h.entropy,
        )
        for h in state.raw_hits
    ]

    head_values = _scan_working_tree(repo_path)
    head_fingerprints = {
        (rule_id, _fingerprint(salt, rule_id, value)) for rule_id, value in head_values
    }
    for hit in hits:
        hit.still_in_head = (hit.rule_id, hit.fingerprint) in head_fingerprints

    return ScanResult(
        hits=hits,
        commits_scanned=state.commits_scanned,
        truncated=truncated,
        truncation_reason=truncation_reason,
    )


def persist_secret_hits(
    repo_id: uuid.UUID,
    hits: list[SecretHit],
    path_id_map: dict[str, int],
    session: Session,
) -> None:
    """Bulk-inserts ``secret_hits`` rows -- the "secrets" FACT stage's own
    persistence step (app/jobs/runner.py), run AFTER ``persist_facts`` so
    ``path_id_map`` (built from ``repo_paths``) is already complete.

    Resolves each hit's ``path`` string to its interned ``repo_paths.id``;
    a path that doesn't resolve (e.g. under an IGNORE_DIRS-pruned directory,
    or a pure-deletion diff header) gets ``path_id=None`` rather than
    failing the insert (the column is nullable for exactly this).

    Deduplicates by ``(fingerprint, commit_sha)`` before inserting -- the
    same physical secret string can be matched by the same rule on more
    than one line/file within a single commit, but ``secret_hits``' own
    unique constraint is ``(repo_id, fingerprint, commit_sha)``, one row per
    that triple, not one row per occurrence.
    """
    seen: set[tuple[str, str]] = set()
    rows: list[dict] = []
    for hit in hits:
        key = (hit.fingerprint, hit.commit_sha)
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "repo_id": repo_id,
                "rule_id": hit.rule_id,
                "description": hit.description,
                "path_id": path_id_map.get(hit.path) if hit.path is not None else None,
                "commit_sha": hit.commit_sha,
                "committed_at": hit.committed_at,
                "line_number": hit.line_number,
                "fingerprint": hit.fingerprint,
                "redacted_preview": hit.redacted_preview,
                "entropy": hit.entropy,
                "still_in_head": hit.still_in_head,
            }
        )
    if rows:
        session.execute(insert(SecretHitRow), rows)
