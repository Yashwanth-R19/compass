from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class DependencyEdge:
    """One structural (import) edge, both ends repo-relative paths."""

    from_path: str
    to_path: str
    dep_type: str = "import"


class LanguageAnalyzer(ABC):
    """Plugin seam for structural (import-graph) analysis.

    All structural analysis goes through this one interface, backed by a
    tree-sitter grammar per language (master-context.md sec 9, decision 3).
    Python ships first (``python_analyzer.py``); Java/JS/TS drop in later as
    new ``LanguageAnalyzer`` implementations registered in
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
