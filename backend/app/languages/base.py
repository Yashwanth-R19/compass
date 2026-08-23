from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class DependencyEdge:
    """One structural (import) edge, both ends repo-relative paths."""

    from_path: str
    to_path: str
    dep_type: str = "import"
    # "static" for a normal import/require/import-from, "dynamic" for a JS
    # dynamic `import(...)` call whose argument was a plain string literal
    # that resolved to a real file (session 03, Part B) -- a template
    # literal or variable argument is dropped entirely, never guessed at, so
    # every edge with import_kind="dynamic" really is one.
    import_kind: str = "static"


@dataclass(frozen=True)
class Symbol:
    """One class/function/etc. declaration found in a source file
    (session 03) -- best-effort, same conservatism as ``extract_imports``:
    only declarations tree-sitter can identify unambiguously are returned.

    ``kind`` is one of "class", "function", "method", "interface", "type",
    "constant". ``exported`` is best-effort per language (True when the
    language makes visibility explicit -- a JS ``export``, a Java
    ``public`` modifier -- see each analyzer for its own rule).
    """

    name: str
    kind: str
    line: int
    exported: bool


class LanguageAnalyzer(ABC):
    """Plugin seam for structural (import-graph) analysis.

    All structural analysis goes through this one interface, backed by a
    tree-sitter grammar per language (master-context.md sec 9, decision 3).
    Python ships first (``python_analyzer.py``); Java/JS/TS drop in later
    (session 03) as new ``LanguageAnalyzer`` implementations registered in
    ``app/languages/scanner.py``. Neither ``ArchEngine`` nor the overlay
    engine ever import a concrete analyzer -- they only read the
    ``dependencies`` table -- so adding a language never touches them.
    """

    @property
    @abstractmethod
    def language(self) -> str:
        """The ``files.language`` value this analyzer handles (e.g. "python")."""
        raise NotImplementedError

    @abstractmethod
    def extract_imports(self, file_path: str, repo_root: str) -> list[str]:
        """Repo-relative paths this file imports, best-effort.

        ``file_path`` is repo-relative (posix separators); ``repo_root`` is
        the absolute path to the checkout on disk. Only imports that resolve
        to an actual file inside the repo are returned -- stdlib/third-party
        imports, or anything ambiguous, are silently dropped rather than
        guessed at.
        """
        raise NotImplementedError

    def extract_symbols(self, file_path: str, repo_root: str) -> list[Symbol]:
        """Best-effort declarations in this file (session 03) -- feeds the
        ``symbols`` Facts table, used by later sessions (e.g. session 04's
        entry-point detection). Default: no symbols -- adding a language
        analyzer does not force implementing this too (Part A)."""
        return []

    def prepare(self, repo_root: str) -> None:
        """Optional one-time-per-run setup hook (session 03), called once
        by ``app/languages/scanner.py`` before any file in the repo is
        walked -- e.g. ``JavaAnalyzer``'s repository-wide class index (Part
        C), which must be built once per run, not once per file, or it's
        O(n^2). Default no-op."""
        return None
