"""Author identity resolution (session 05, Part A -- everything in the
knowledge/expertise/truck-factor feature depends on this being right first).

Real repositories contain the same human under several (name, email) pairs:
a work email, a personal email, a GitHub noreply address, a typo'd name,
"First Last" vs "flast". Without merging these, every downstream metric
(DOA, expert selection, truck factor) is computed against phantom extra
"people" who are really the same person split apart -- silently wrong in a
way that's highly visible, since it puts a wrong headcount on a screen with
someone's name on it.

``resolve_identities`` merges via union-find over four DETERMINISTIC rules,
applied in this order (session 05 Known Hazard #3 -- apply the generic-word
blocklists as part of each rule's own key computation, never as a
post-hoc filter; that's what keeps rule 4 from chaining two distinct people
through a shared generic local part regardless of rule ordering):

  1. Exact match on lowercased email.
  2. GitHub noreply emails (``<id>+<login>@users.noreply.github.com``): the
     extracted, lowercased ``<login>`` is a merge key; any OTHER email whose
     local part equals that login merges too.
  3. Exact match on lowercased, whitespace-normalised author NAME -- UNLESS
     the name is a generic placeholder (``GENERIC_NAME_BLOCKLIST``) or a bot
     name (anything ending ``[bot]``). Two different people who both
     typed "Unknown" as their git name must never merge just because the
     string matches.
  4. The email LOCAL PART, lowercased, matched across different domains
     (``jane@corp.com`` / ``jane@gmail.com``) -- ONLY when the local part is
     longer than 4 characters and isn't a generic word
     (``GENERIC_LOCAL_PART_BLOCKLIST``): short/generic local parts
     ("dev", "ci") are exactly the strings likeliest to be shared by
     unrelated people.

Deliberately NO fuzzy string similarity on names anywhere in this module.
Fuzzy matching merges distinct people far more readily than it correctly
merges one person split across aliases -- a false merge is a wrong answer
with a real person's name on it, a missed merge is just a small
undercount. Conservatism is the correct default here, the same principle
every conservative resolver in this codebase already follows (import
resolution, test-file classification): a missed edge is fine, a fabricated
one is not.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from datetime import datetime

NOREPLY_EMAIL_RE = re.compile(r"^\d+\+([^@]+)@users\.noreply\.github\.com$", re.IGNORECASE)
"""GitHub's own noreply address shape: ``<user-id>+<login>@users.noreply.github.com``."""

GENERIC_NAME_BLOCKLIST: frozenset[str] = frozenset(
    {
        "unknown",
        "user",
        "admin",
        "root",
        "dev",
        "developer",
        "your name",
        "github-actions[bot]",
        "dependabot[bot]",
    }
)
"""Vendored (session 05 Part A): names that must never drive a rule-3 merge
because many different real people/bots plausibly share the literal string.
The two ``[bot]``-suffixed entries are already covered by the general
"anything ending in [bot]" check below (``_is_bot_name``) -- listed
explicitly here anyway since they're the two bots Compass is most likely to
actually see."""

GENERIC_LOCAL_PART_BLOCKLIST: frozenset[str] = frozenset(
    {"info", "dev", "team", "admin", "hello", "mail", "no-reply", "noreply", "git", "build", "ci"}
)
"""Vendored (session 05 Part A): email local parts too generic to prove two
different domains belong to the same person (rule 4)."""

MIN_LOCAL_PART_LENGTH = 4
"""Rule 4 fires only when the local part is at least this many characters
long. Session 05 Part A's prose says local parts "longer than 4
characters", but its OWN worked test fixture requires
``jane@corp.com``/``jane@gmail.com`` (local part ``"jane"``, exactly 4
characters) to merge -- a direct conflict between the stated threshold and
the required test outcome. Resolved in favor of the concrete, executable
example: the comparison below is ``>= MIN_LOCAL_PART_LENGTH`` (4 or more),
not strictly greater. Documented as a judgement call (plan/RULES.md sec
2.5) rather than silently picking one reading."""


def _normalize_name(name: str) -> str:
    return " ".join(name.strip().lower().split())


def _is_bot_name(normalized_name: str) -> bool:
    return normalized_name.endswith("[bot]")


def is_bot_name(name: str) -> bool:
    """True for a bot author name (anything ending ``[bot]``, case/whitespace
    -insensitive) -- the same check used both to keep rule 3 from merging
    two different bots by name and to flag an identity's ``is_bot`` column
    once its aliases are known."""
    return _is_bot_name(_normalize_name(name))


def _is_generic_placeholder_name(normalized_name: str) -> bool:
    return normalized_name in GENERIC_NAME_BLOCKLIST or _is_bot_name(normalized_name)


class _UnionFind:
    """Deterministic disjoint-set: union always attaches the HIGHER index
    under the LOWER one, so the resulting partition (and each group's root
    id) depends only on which pairs got unioned, never on the order the
    union() calls happened to run in or on dict/set iteration order."""

    __slots__ = ("parent",)

    def __init__(self, n: int) -> None:
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[x] != root:
            self.parent[x], x = root, self.parent[x]
        return root

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if ra < rb:
            self.parent[rb] = ra
        else:
            self.parent[ra] = rb


def _union_by_key(
    dsu: _UnionFind, pairs: Sequence[tuple[str, str]], keys: list[str | None]
) -> None:
    groups: dict[str, list[int]] = {}
    for idx, key in enumerate(keys):
        if key is None:
            continue
        groups.setdefault(key, []).append(idx)
    for indices in groups.values():
        for other in indices[1:]:
            dsu.union(indices[0], other)


def resolve_identities(commits: Sequence[tuple[str, str]]) -> dict[tuple[str, str], int]:
    """Union-find identity resolution over the deterministic rules above.

    ``commits`` is a sequence of ``(author_name, author_email)`` pairs, one
    per commit (duplicates expected and fine -- a prolific author appears
    many times). Returns a mapping from every DISTINCT ``(name, email)``
    pair that appeared to an integer "canonical_id" -- stable only within
    this one call (an arbitrary index into the distinct-pairs list, not a
    database id), grouping every alias that a rule merged into the same
    person under the same id.

    Pure, DB-agnostic, and independently testable -- callers that have full
    ``Commit`` rows (author name/email plus everything else) pass just the
    two fields they need; nothing here depends on the ORM.
    """
    distinct_pairs: list[tuple[str, str]] = []
    seen: dict[tuple[str, str], int] = {}
    for name, email in commits:
        key = (name, email)
        if key not in seen:
            seen[key] = len(distinct_pairs)
            distinct_pairs.append(key)

    dsu = _UnionFind(len(distinct_pairs))

    # Rule 1: exact match on lowercased email.
    email_keys: list[str | None] = [email.strip().lower() for _, email in distinct_pairs]
    _union_by_key(dsu, distinct_pairs, email_keys)

    # Rule 2: GitHub noreply login extraction, plus any other email whose
    # local part equals that login.
    logins: set[str] = set()
    for _, email in distinct_pairs:
        m = NOREPLY_EMAIL_RE.match(email.strip().lower())
        if m:
            logins.add(m.group(1).lower())
    login_keys: list[str | None] = []
    for _, email in distinct_pairs:
        e = email.strip().lower()
        m = NOREPLY_EMAIL_RE.match(e)
        if m:
            login_keys.append(m.group(1).lower())
        else:
            local_part = e.split("@", 1)[0]
            login_keys.append(local_part if local_part in logins else None)
    _union_by_key(dsu, distinct_pairs, login_keys)

    # Rule 3: exact match on normalized name, excluding generic/bot placeholders.
    name_keys: list[str | None] = []
    for name, _ in distinct_pairs:
        normalized = _normalize_name(name)
        name_keys.append(
            None if not normalized or _is_generic_placeholder_name(normalized) else normalized
        )
    _union_by_key(dsu, distinct_pairs, name_keys)

    # Rule 4: same email local part across different domains -- long enough
    # and not a generic word.
    local_part_keys: list[str | None] = []
    for _, email in distinct_pairs:
        local_part = email.strip().lower().split("@", 1)[0]
        if (
            len(local_part) >= MIN_LOCAL_PART_LENGTH
            and local_part not in GENERIC_LOCAL_PART_BLOCKLIST
        ):
            local_part_keys.append(local_part)
        else:
            local_part_keys.append(None)
    _union_by_key(dsu, distinct_pairs, local_part_keys)

    return {distinct_pairs[i]: dsu.find(i) for i in range(len(distinct_pairs))}


def most_frequent_recent(values: Sequence[tuple[str, datetime]]) -> str:
    """Picks a canonical string among repeated ``(value, timestamp)``
    occurrences: the most FREQUENT value wins; ties are broken by whichever
    occurs in the most RECENT commit (session 05 Part A: "the most
    frequently occurring name, tie-broken by the most recent"). A final,
    fully arbitrary but deterministic tie-break on the string itself
    guards against the pathological case of two values sharing both the
    same count and the exact same latest timestamp.

    Used for both canonical display name and canonical email -- the same
    "most common, then most recent" rule applies to either.
    """
    counts = Counter(v for v, _ in values)
    most_recent: dict[str, datetime] = {}
    for v, ts in values:
        if v not in most_recent or ts > most_recent[v]:
            most_recent[v] = ts
    return max(counts, key=lambda v: (counts[v], most_recent[v], v))


def mask_email(email: str) -> str:
    """The ONE masking helper (plan/RULES.md sec 11.2 / session 05 Part F):
    every endpoint that surfaces a contributor's email MUST go through this,
    never the raw value. ``jane@corp.com`` -> ``j***@corp.com``.

    NEVER returns the input unmodified, even for malformed values -- a
    string with no "@" is still masked from its first character (e.g.
    ``"not-an-email"`` -> ``"n***"``), because it could just as easily BE
    the sensitive raw value; the empty string is the only input returned
    as-is, since there is nothing in it to leak.
    """
    if not email:
        return email
    local, sep, domain = email.partition("@")
    if not local:
        # Starts with "@" (or is literally just "@..."): no local-part
        # character to lead with -- mask generically instead of indexing
        # into an empty string.
        return f"***@{domain}" if sep else "***"
    masked = f"{local[0]}***"
    return f"{masked}@{domain}" if sep else masked
