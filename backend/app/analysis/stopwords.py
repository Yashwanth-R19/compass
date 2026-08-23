"""Shared identifier tokenization + stopword list (session 04, Part B).

``SubsystemEngine``'s identifier-frequency naming fallback (used when no
path-prefix name is confident enough -- see app/engines/subsystems.py) tokenizes
file stems and ``symbols.name`` values into lowercase words, drops anything in
``STOPWORDS``, and takes the most frequent remaining token. Session 06's
domain-glossary module reuses both ``tokenize_identifier`` and ``STOPWORDS``
rather than reimplementing tokenization a second time -- "what counts as a
word" and "what counts as noise" must agree between the two features, or a
subsystem label and a glossary term could disagree about the same identifier.

``STOPWORDS`` is HEURISTIC (plan/RULES.md sec 3): a hand-picked union of
Python/JavaScript-TypeScript/Java reserved words (repo-agnostic noise that
tokenizes out of nearly every source file regardless of what the codebase
actually does) plus a vendored list of generic, structurally-common English
terms (session 04 spec) that name almost nothing about a *specific* domain --
"model", "service", "util" appear in every third repository's file tree and
would otherwise dominate the frequency count without ever being a useful
subsystem name.
"""

import keyword
import re

_PYTHON_KEYWORDS: frozenset[str] = frozenset(keyword.kwlist) | frozenset(keyword.softkwlist)

_JS_TS_KEYWORDS: frozenset[str] = frozenset(
    {
        "break", "case", "catch", "class", "const", "continue", "debugger",
        "default", "delete", "do", "else", "export", "extends", "finally",
        "for", "function", "if", "import", "in", "instanceof", "let", "new",
        "return", "super", "switch", "this", "throw", "try", "typeof", "var",
        "void", "while", "with", "yield", "async", "await", "enum",
        "implements", "interface", "package", "private", "protected",
        "public", "static", "as", "from", "of", "readonly", "namespace",
        "declare", "abstract", "module", "require", "exports",
    }
)  # fmt: skip

_JAVA_KEYWORDS: frozenset[str] = frozenset(
    {
        "abstract", "assert", "boolean", "break", "byte", "case", "catch",
        "char", "class", "const", "continue", "default", "do", "double",
        "else", "enum", "extends", "final", "finally", "float", "for", "goto",
        "if", "implements", "import", "instanceof", "int", "interface", "long",
        "native", "new", "package", "private", "protected", "public", "return",
        "short", "static", "strictfp", "super", "switch", "synchronized",
        "this", "throw", "throws", "transient", "try", "void", "volatile",
        "while", "var", "record", "sealed", "permits", "yield",
    }
)  # fmt: skip

_DOMAIN_STOPWORDS: frozenset[str] = frozenset(
    {
        "index", "main", "app", "util", "utils", "helper", "helpers",
        "common", "core", "base", "test", "tests", "spec", "types",
        "config", "constants", "model", "models", "service", "services",
        "component", "components",
    }
)  # fmt: skip
"""Session 04 Part B's literal list -- generic, structurally-common terms
that name a file's ROLE, not the domain it belongs to."""

STOPWORDS: frozenset[str] = _PYTHON_KEYWORDS | _JS_TS_KEYWORDS | _JAVA_KEYWORDS | _DOMAIN_STOPWORDS

# Inserts a split point between a lowercase/digit and a following uppercase
# letter ("fooBar" -> "foo Bar"), and between a run of uppercase letters and
# a trailing capitalized word ("XMLParser" -> "XML Parser") -- the standard
# two-rule camelCase/PascalCase boundary regex.
_CAMEL_BOUNDARY_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_NON_ALNUM_RE = re.compile(r"[^a-zA-Z0-9]+")


def tokenize_identifier(text: str) -> list[str]:
    """Splits a file stem or symbol name into lowercase words -- handles
    camelCase, PascalCase, snake_case, and kebab-case uniformly (session 04
    Part B). Does not drop stopwords itself; callers filter against
    ``STOPWORDS`` separately, since not every caller wants the same
    filtering applied at the same point (e.g. a caller counting raw token
    frequency across many identifiers before filtering)."""
    spaced = _CAMEL_BOUNDARY_RE.sub(" ", text)
    spaced = _NON_ALNUM_RE.sub(" ", spaced)
    return [tok.lower() for tok in spaced.split() if tok]
