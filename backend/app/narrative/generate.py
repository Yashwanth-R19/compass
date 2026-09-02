"""Prompting and output validation (session 12, Part C) -- the piece that
makes narrative rule 1 ("the model never produces a number/rank/file
list/count/finding/recommendation that wasn't already computed") true of the
actual generated TEXT, not just of the fact pack's shape.

``factpack.py``'s field-type allowlist guarantees the INPUT to a prompt can
only ever be numbers/booleans/fixed labels. This module guarantees the
OUTPUT stays grounded in exactly that input: every numeric token and every
path/identifier-shaped token in a generated narrative must trace back to the
fact pack, or the whole generation is rejected and never cached.

**No stage in ``app/jobs/stages.py`` calls anything in this module.**
Generation happens only when ``GET /repos/{id}/narrative`` (or session 16's
pre-generation endpoint) asks for it -- "the analysis pipeline contains no
LLM call" is a real, verifiable property of this codebase, not just a claim,
because nothing in ``app/jobs/`` imports ``app.narrative``.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from math import floor, log10
from typing import get_args

from pydantic import BaseModel

from app.config import settings
from app.jobs.log_redaction import redact
from app.narrative import pool, providers
from app.narrative.factpack import validate_factpack_allowlist

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are given already-computed metrics about a code repository, listed "
    "below as plain key/value facts. Write 2-4 sentences of plain prose "
    "explaining what these metrics mean for someone joining this codebase.\n\n"
    "Rules, followed exactly:\n"
    "- Do NOT introduce any number, percentage, filename, or person's name "
    "that is not present in the facts given below.\n"
    "- Do NOT make recommendations, predictions, or judgements about code "
    "quality beyond what the metrics state.\n"
    "- Do NOT speculate about what the code does, what language features it "
    "uses, or its purpose.\n"
    "- Do not repeat every fact verbatim as a list -- write connected prose.\n"
    "- Keep it under 600 characters."
)

# How many DISTINCT keys this process will try before giving up as
# "pool_exhausted" -- a small, bounded cap so a run of unlucky provider
# failures can't loop indefinitely. Infra plumbing, not a locked/heuristic
# PRODUCT number.
MAX_KEY_ATTEMPTS = 4

MAX_OUTPUT_CHARS = 600

# Part C, step 2: words that soften a number into an approximation rather
# than asserting it exactly. Documented here, deliberately NOT wired into
# the validator's number-extraction regex, because none of them contain a
# digit -- they never produce a numeric token in the first place, so no
# special-casing is needed for the validator to already accept
# "roughly half" or "about 12" freely. This list exists so that fact is
# written down rather than left implicit, and so a future session extending
# the validator has a canonical place to check before tightening the
# numeric-token regex in a way that would start flagging these words.
APPROXIMATION_WORDS = frozenset(
    {"about", "roughly", "nearly", "almost", "over", "under", "a third", "half", "most"}
)

_NUMBER_RE = re.compile(r"(?<![\w.])\d{1,3}(?:,\d{3})*(?:\.\d+)?%?(?![\w])")
_KNOWN_EXTENSIONS = (
    "py",
    "js",
    "jsx",
    "ts",
    "tsx",
    "mjs",
    "cjs",
    "java",
    "json",
    "toml",
    "yml",
    "yaml",
    "md",
    "txt",
    "lock",
    "xml",
    "gradle",
    "kts",
    "cfg",
    "ini",
    "env",
)
_EXTENSION_RE = re.compile(
    r"\b[\w][\w.\-]*\.(?:" + "|".join(_KNOWN_EXTENSIONS) + r")\b", re.IGNORECASE
)
_PATH_RE = re.compile(r"\b[\w.\-]+/[\w./\-]+\b")
_SNAKE_CASE_RE = re.compile(r"\b[a-zA-Z][a-zA-Z0-9]*_[a-zA-Z0-9_]*[a-zA-Z0-9]\b")
_CAMEL_CASE_RE = re.compile(r"\b[a-zA-Z]*[a-z][A-Z][a-zA-Z0-9]*\b")

_ROUNDING_BUCKETS = (5, 10, 25, 50, 100, 1000, 10000)


def _round_sig(value: float, sig: int) -> float:
    if value == 0:
        return 0.0
    digits = sig - int(floor(log10(abs(value)))) - 1
    return round(value, digits)


def _rounded_variants(value: float) -> set[float]:
    """Every "reasonable rounding" of ``value`` a model might plausibly
    write -- 2-significant-figure rounding (Part C step 1a) plus rounding to
    the nearest integer or to a coarser bucket (step 1b's "12.4 -> about
    12", "0.62 -> roughly 60%" examples, generalised)."""
    variants = {value, _round_sig(value, 2), float(round(value))}
    for bucket in _ROUNDING_BUCKETS:
        if bucket <= max(abs(value), 1.0) * 10:
            variants.add(round(value / bucket) * bucket)
    return variants


def _numeric_leaves(obj: object) -> list[float]:
    if isinstance(obj, bool):
        return []
    if isinstance(obj, int | float):
        return [float(obj)]
    if isinstance(obj, BaseModel):
        return _numeric_leaves(obj.model_dump())
    if isinstance(obj, dict):
        leaves: list[float] = []
        for v in obj.values():
            leaves.extend(_numeric_leaves(v))
        return leaves
    if isinstance(obj, list | tuple):
        leaves = []
        for v in obj:
            leaves.extend(_numeric_leaves(v))
        return leaves
    return []


def _acceptable_numbers(fact_pack: BaseModel) -> set[float]:
    """Every number a generated narrative may use without being rejected --
    every fact-pack leaf value, its rounded variants, AND (for any ratio-
    shaped float in [0, 1]) the same rounded variants of its percentage
    form, since a model is equally likely to phrase ``0.62`` as "62%" as it
    is to phrase it as "0.62"."""
    acceptable: set[float] = set()
    for value in _numeric_leaves(fact_pack):
        acceptable |= _rounded_variants(value)
        if 0.0 <= value <= 1.0:
            acceptable |= _rounded_variants(value * 100)
    return acceptable


def _string_leaves(obj: object) -> set[str]:
    if isinstance(obj, str):
        return {obj}
    if isinstance(obj, dict):
        names: set[str] = set()
        for v in obj.values():
            names |= _string_leaves(v)
        return names
    if isinstance(obj, list | tuple):
        names = set()
        for v in obj:
            names |= _string_leaves(v)
        return names
    return set()


def _known_identifiers(fact_pack: BaseModel) -> set[str]:
    """The vocabulary a narrative is allowed to use identifier/path-shaped
    tokens from: every field NAME on the fact pack (Compass's own metric
    vocabulary -- "risk_score", "is_orphaned_knowledge", ... -- never text
    pulled from the repository) plus every ``Literal[...]`` string VALUE any
    field can take (the full fixed set, not just whichever value this
    particular fact pack happens to hold, so e.g. a risk fact pack for a
    Java file is still allowed to say "python" if it ever needed to -- it
    won't, but the allowlist is defined by the type, not the instance).
    Lower-cased for case-insensitive matching."""
    names: set[str] = set()
    for field_name, field_info in type(fact_pack).model_fields.items():
        names.add(field_name)
        annotation = field_info.annotation
        args = get_args(annotation)
        for arg in args:
            if isinstance(arg, str):
                names.add(arg)
    names |= _string_leaves(fact_pack.model_dump())
    return {n.lower() for n in names}


def _extract_numbers(text: str) -> list[float]:
    values = []
    for match in _NUMBER_RE.finditer(text):
        raw = match.group(0).rstrip("%").replace(",", "")
        try:
            values.append(float(raw))
        except ValueError:
            continue
    return values


def _extract_identifier_like_tokens(text: str) -> list[str]:
    tokens: set[str] = set()
    for regex in (_EXTENSION_RE, _PATH_RE, _SNAKE_CASE_RE, _CAMEL_CASE_RE):
        tokens.update(match.group(0) for match in regex.finditer(text))
    return sorted(tokens)


def _matches_any(value: float, acceptable: set[float]) -> bool:
    return any(abs(value - a) < 1e-6 for a in acceptable)


RejectionReason = str


def validate_output(text: str, fact_pack: BaseModel) -> tuple[bool, RejectionReason | None]:
    """The technical mechanism behind "the model never produces a number" --
    see the module docstring. Returns ``(True, None)`` when ``text`` is safe
    to cache verbatim, or ``(False, reason)`` naming exactly which check
    failed (never the text itself -- callers must log only ``reason``)."""
    if len(text) > MAX_OUTPUT_CHARS:
        return False, "too_long"

    acceptable_numbers = _acceptable_numbers(fact_pack)
    for value in _extract_numbers(text):
        if not _matches_any(value, acceptable_numbers):
            return False, "ungrounded_number"

    known_identifiers = _known_identifiers(fact_pack)
    for token in _extract_identifier_like_tokens(text):
        cleaned = token.strip(".,;:()").lower()
        if cleaned not in known_identifiers:
            return False, "ungrounded_reference"

    return True, None


def build_prompt(fact_pack: BaseModel) -> str:
    """Validates the fact pack's own type shape (Part B) before ever
    touching a prompt string, then renders it as plain ``key: value`` lines
    -- rule 4's "prompts contain ONLY already-computed numbers" is satisfied
    here by construction: ``fact_pack.model_dump()`` can only ever yield
    numbers/booleans/fixed labels once ``validate_factpack_allowlist`` has
    passed, so there is nothing else this function could accidentally
    embed."""
    validate_factpack_allowlist(fact_pack)
    lines = [SYSTEM_PROMPT, "", "Computed metrics for this repository:"]
    for key, value in fact_pack.model_dump().items():
        lines.append(f"- {key}: {value}")
    return "\n".join(lines)


@dataclass
class GenerationResult:
    ok: bool
    content: str | None
    provider: str | None
    model: str | None
    reason: str | None  # "no_keys" | "pool_exhausted" | "rejected"


def _model_name_for(provider: str) -> str:
    if provider == "gemini":
        return settings.COMPASS_GEMINI_MODEL
    if provider == "groq":
        return settings.COMPASS_GROQ_MODEL
    return provider


def _call_provider(key: pool.ProviderKey, prompt: str) -> str | None:
    try:
        text = providers.generate(prompt, key, providers.DEFAULT_MAX_TOKENS)
    except providers.ProviderError as exc:
        pool.report_failure(key, exc.kind)
        logger.warning(
            "narrative provider failure: provider=%s kind=%s detail=%s",
            key.provider,
            exc.kind,
            redact(str(exc)),
        )
        return None
    pool.report_success(key)
    return text


def generate_narrative(fact_pack: BaseModel) -> GenerationResult:
    """Orchestrates one narrative generation attempt (Part C, rule 6: no
    fallback model, no retry storm).

    - Zero keys configured at all -> ``"no_keys"``, no attempt made.
    - Tries up to ``MAX_KEY_ATTEMPTS`` distinct keys; a PROVIDER-level
      failure (rate limit / auth / server / timeout) reports it to the pool
      and moves on to the next key.
    - Once a provider call SUCCEEDS, its output is validated; a rejection is
      retried exactly ONCE with the SAME key (Part C step 5), and if that
      retry also fails validation, generation gives up entirely as
      ``"rejected"`` -- it does NOT fall through to another key, per the
      spec's literal "retry once... then give up."
    - Exhausting every key attempt without a successful provider call ->
      ``"pool_exhausted"``.
    """
    if not pool.has_any_keys():
        return GenerationResult(False, None, None, None, "no_keys")

    prompt = build_prompt(fact_pack)

    for _ in range(MAX_KEY_ATTEMPTS):
        key = pool.get_key()
        if key is None:
            return GenerationResult(False, None, None, None, "pool_exhausted")

        text = _call_provider(key, prompt)
        if text is None:
            continue

        ok, reason = validate_output(text, fact_pack)
        if ok:
            return GenerationResult(
                True, text.strip(), key.provider, _model_name_for(key.provider), None
            )
        logger.warning("narrative generation rejected: reason=%s", reason)

        retry_text = _call_provider(key, prompt)
        if retry_text is not None:
            ok2, reason2 = validate_output(retry_text, fact_pack)
            if ok2:
                return GenerationResult(
                    True, retry_text.strip(), key.provider, _model_name_for(key.provider), None
                )
            logger.warning("narrative generation rejected on retry: reason=%s", reason2)
        return GenerationResult(False, None, None, None, "rejected")

    return GenerationResult(False, None, None, None, "pool_exhausted")


__all__ = [
    "APPROXIMATION_WORDS",
    "MAX_OUTPUT_CHARS",
    "SYSTEM_PROMPT",
    "GenerationResult",
    "build_prompt",
    "generate_narrative",
    "validate_output",
]
