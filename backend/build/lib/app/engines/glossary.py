"""Domain glossary (session 06, Part C): the repository's own vocabulary,
extracted from identifier names -- never file contents (engines have no
filesystem access, and the clone is long gone by the time this runs).

Source of terms: ``symbols.name`` (class/function/method/interface/type
declarations, session 03) and file stems from ``repo_paths``, tokenized via
``app/analysis/stopwords.py::tokenize_identifier`` (camelCase/PascalCase/
snake_case/kebab-case boundaries, lowercased) and filtered against
``STOPWORDS`` -- the SAME shared module ``SubsystemEngine`` already uses for
identifier-based subsystem naming (session 04), so "what counts as a word"
and "what counts as noise" never disagree between the two features.

**Honest limitation (surface this in the API response, session 08 must
reflect it in the UI copy too):** this extracts VOCABULARY, not
DEFINITIONS. Compass does not claim to know what "settlement" means in this
domain -- it claims "settlement" is a word this codebase revolves around,
and shows the handful of files that would tell a reader what it means.

**Test-code and placeholder-identifier filtering (manual-QA follow-up,
post-session-06).** Manual acceptance testing against expressjs/express
found `fn1`/`fn2`/`fn3` -- literal, repeated throwaway middleware-stub names
from that repo's own test suite (e.g. `test/app.use.js`) -- ranking in the
top 10 glossary terms, alongside `should` (leaked from Mocha/Chai assertion
chains). Two independent fixes, both HEURISTIC (plan/RULES.md sec 3):
(1) a symbol's name only contributes to occurrence/spread counting (and
`defining_path_ids` candidacy) when its file is NOT `files.is_test` --
file-stem tokens are unaffected, since a file's own name/directory
placement is not test-authored throwaway code the way an inline stub
function name is; (2) `_PLACEHOLDER_TOKEN_RE` drops any token matching a
short-base-word-plus-trailing-digits shape (`fn1`, `tmp3`, `x1`), the
auto-numbered-placeholder convention no fixed stopword list can ever catch
because it is a *pattern*, not a finite vocabulary.
"""

from __future__ import annotations

import math
import re
import uuid
from collections import Counter
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, insert, select
from sqlalchemy.orm import Session

from app.analysis.stopwords import STOPWORDS, tokenize_identifier
from app.db.models import File, GlossaryTerm, Subsystem, SubsystemMember, Symbol
from app.engines.base import Engine

if TYPE_CHECKING:
    from app.engines.context import RunContext

MAX_GLOSSARY_TERMS = 40
"""Session 06 spec: the top-N ranked terms kept, same anti-alert-fatigue
discipline every other capped list in this codebase follows."""

MIN_TOKEN_LENGTH = 3
"""Session 06 Part C step 1: tokens shorter than this are dropped outright
(too short to carry domain meaning -- "id", "ok", "db" read as noise more
often than signal)."""

MAX_DEFINING_PATHS_PER_TERM = 5
"""Session 06 Part C step 5: up to 5 "go read this" file links per term."""

_PREFERRED_DEFINING_KINDS = frozenset({"class", "interface", "type"})
"""Session 06 Part C step 5: defining_path_ids prefers symbols of these
kinds (and ``exported=True``) over a term that only ever appears inside a
function/method body -- a class/interface/type declaration is what a reader
actually wants pointed at when looking up a domain term."""

_PLACEHOLDER_TOKEN_RE = re.compile(r"^[a-z]{1,3}\d+$")
"""HEURISTIC (manual-QA follow-up, post-session-06; plan/RULES.md sec 3):
matches short, auto-numbered placeholder identifiers like "fn1"/"fn2"/
"tmp3" -- see the module docstring's "Test-code and placeholder-identifier
filtering" section."""


def _score(occurrences: int, subsystem_spread: int, total_subsystems: int) -> float:
    """HEURISTIC (plan/RULES.md sec 3), not a locked formula:

        score = log(1 + occurrences) * (1 + subsystem_spread / total_subsystems)

    A term appearing many times AND across several subsystems is the shared
    vocabulary of the domain -- the orientation aid this feature exists to
    surface. A term appearing many times in exactly one subsystem is that
    subsystem's internal jargon: real, but less useful for getting oriented
    across the whole codebase, so it earns a smaller multiplier.
    ``total_subsystems == 0`` (a repo with no subsystems at all, e.g. zero
    files) has nothing to spread across -- the multiplier degrades to the
    neutral 1.0 rather than dividing by zero.
    """
    spread_bonus = (subsystem_spread / total_subsystems) if total_subsystems else 0.0
    return math.log(1 + occurrences) * (1 + spread_bonus)


def compute_glossary(
    repo_id: uuid.UUID, run_id: uuid.UUID, session: Session
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Pure computation (no writes) -- the module-level ``compute_*`` core
    every engine follows. Returns ``(rows, summary)`` ready for a bulk
    insert into ``glossary_terms``."""
    files = session.scalars(
        select(File).where(File.repo_id == repo_id, File.is_deleted.is_(False))
    ).all()
    if not files:
        return [], {"terms": 0}

    subsystem_of_path: dict[int, int] = {
        path_id: subsystem_id
        for path_id, subsystem_id in session.execute(
            select(SubsystemMember.path_id, SubsystemMember.subsystem_id)
            .join(Subsystem, Subsystem.id == SubsystemMember.subsystem_id)
            .where(Subsystem.analysis_run_id == run_id)
        ).all()
    }
    total_subsystems = (
        session.scalar(
            select(func.count()).select_from(Subsystem).where(Subsystem.analysis_run_id == run_id)
        )
        or 0
    )

    test_path_ids = {f.path_id for f in files if f.is_test}

    occurrences: Counter[str] = Counter()
    spread_by_term: dict[str, set[int]] = {}

    def _record(term: str, path_id: int) -> None:
        occurrences[term] += 1
        subsystem_id = subsystem_of_path.get(path_id)
        if subsystem_id is not None:
            spread_by_term.setdefault(term, set()).add(subsystem_id)

    def _is_noise(token: str) -> bool:
        return (
            len(token) < MIN_TOKEN_LENGTH
            or token in STOPWORDS
            or bool(_PLACEHOLDER_TOKEN_RE.match(token))
        )

    for f in files:
        stem = PurePosixPath(f.path).stem
        for token in tokenize_identifier(stem):
            if _is_noise(token):
                continue
            _record(token, f.path_id)

    # defining_path_ids candidates: (term) -> list of (path_id, exported, kind)
    # Symbols from test files are skipped entirely -- a throwaway stub
    # defined only in a test file is not vocabulary this codebase's domain
    # revolves around, and shouldn't be a "go read this" link either (see
    # module docstring's "Test-code and placeholder-identifier filtering").
    defining_candidates: dict[str, list[tuple[int, bool, str]]] = {}
    symbol_rows = session.execute(
        select(Symbol.name, Symbol.path_id, Symbol.exported, Symbol.kind).where(
            Symbol.repo_id == repo_id
        )
    ).all()
    for name, path_id, exported, kind in symbol_rows:
        if path_id in test_path_ids:
            continue
        for token in tokenize_identifier(name):
            if _is_noise(token):
                continue
            _record(token, path_id)
            defining_candidates.setdefault(token, []).append((path_id, exported, kind))

    if not occurrences:
        return [], {"terms": 0}

    scored: list[tuple[str, float, int, int]] = []
    for term, count in occurrences.items():
        spread = len(spread_by_term.get(term, ()))
        scored.append((term, _score(count, spread, total_subsystems), count, spread))

    # Ranked score desc, ties broken by term asc -- determinism (session 06
    # Part C step 4).
    scored.sort(key=lambda t: (-t[1], t[0]))
    top = scored[:MAX_GLOSSARY_TERMS]

    rows: list[dict[str, Any]] = []
    for rank, (term, score, count, spread) in enumerate(top):
        candidates = defining_candidates.get(term, [])
        # Preferred: exported AND a class/interface/type declaration first;
        # path asc within a tier for determinism. Deduplicated by path_id
        # (a term can match more than one symbol in the same file).
        ordered_candidates = sorted(
            candidates,
            key=lambda c: (
                c[2] not in _PREFERRED_DEFINING_KINDS,
                not c[1],
                c[0],
            ),
        )
        defining_path_ids: list[int] = []
        seen: set[int] = set()
        for path_id, _exported, _kind in ordered_candidates:
            if path_id in seen:
                continue
            seen.add(path_id)
            defining_path_ids.append(path_id)
            if len(defining_path_ids) >= MAX_DEFINING_PATHS_PER_TERM:
                break

        rows.append(
            {
                "analysis_run_id": run_id,
                "repo_id": repo_id,
                "term": term,
                "score": score,
                "occurrences": count,
                "subsystem_spread": spread,
                "defining_path_ids": defining_path_ids,
                "rank": rank,
            }
        )

    return rows, {"terms": len(rows)}


class GlossaryEngine(Engine):
    """Extracts and ranks the repository's own domain vocabulary (session
    06, Part C) -- see the module docstring for the source data, the
    HEURISTIC scoring formula, and the honest "vocabulary, not definitions"
    limitation. Runs second in the "onboarding" stage, right after
    ``TourEngine``; reads ``subsystems``/``subsystem_members`` from the
    "subsystems" stage earlier in this same run, writes no findings.
    """

    def run(self, ctx: RunContext, session: Session) -> dict[str, Any]:
        rows, summary = compute_glossary(ctx.repo_id, ctx.run_id, session)
        if rows:
            session.execute(insert(GlossaryTerm), rows)
        return summary
