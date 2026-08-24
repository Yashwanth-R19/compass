"""tree-sitter-backed structural analyzer for Java (session 03, Part C).

Java is the most tractable of the three languages this session adds because
package structure mirrors directory structure: a fully-qualified class name
resolves to a repo path by simple string substitution once a
package -> path index exists.

LIMITATION, stated here and in master-context.md's limitations section:
same-package references need no ``import`` statement in Java, and this
analyzer does NOT attempt to infer them by scanning identifiers -- doing so
would require full type resolution (which local names are in scope, which
shadow an outer type, generics, ...) and is exactly the kind of guessing
that fabricates edges, which is worse than a missed one (the governing rule,
see ``app/languages/base.py``). Change-coupling (language-agnostic, driven
by co-committed files rather than parsed syntax) is what surfaces same-
package relationships instead.
"""

import os
from collections.abc import Iterator
from pathlib import Path
from typing import cast

import tree_sitter_java as tsjava
from tree_sitter import Language, Node, Parser

from app.ingestion.miner import IGNORE_DIRS, MAX_FILE_BYTES
from app.languages.base import LanguageAnalyzer, Symbol

_JAVA_LANGUAGE = Language(tsjava.language())

# Part C: "A package with 400 classes produces 400 edges from one import
# line and distorts the whole graph. The 50-edge cap is not optional."
MAX_WILDCARD_EDGES = 50

_SYMBOL_KINDS = {
    "class_declaration": "class",
    "interface_declaration": "interface",
    # Symbol.kind's vocabulary (app/languages/base.py) has no "enum"/"record"
    # entry -- both are class-like top-level type declarations in Java's
    # compiled model, so they map onto the existing "class" kind rather than
    # inventing a new one.
    "enum_declaration": "class",
    "record_declaration": "class",
    "method_declaration": "method",
}


class JavaAnalyzer(LanguageAnalyzer):
    """``prepare()`` builds a repository-wide ``fully.qualified.ClassName ->
    repo-relative path`` index ONCE per run (Part C) -- building it per file
    would be O(n^2) and blow the time budget on a real repository. Same
    conservatism as PythonAnalyzer/JavaScriptAnalyzer: anything that doesn't
    resolve to an indexed, real file is silently dropped.
    """

    def __init__(self) -> None:
        self._class_index: dict[str, str] = {}
        self._package_index: dict[str, list[str]] = {}

    @property
    def language(self) -> str:
        return "java"

    def prepare(self, repo_root: str) -> None:
        root = Path(repo_root)
        class_index: dict[str, str] = {}
        package_index: dict[str, list[str]] = {}

        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS]
            for fname in filenames:
                if not fname.endswith(".java"):
                    continue
                full_path = Path(dirpath) / fname
                try:
                    if full_path.stat().st_size > MAX_FILE_BYTES:
                        continue
                except OSError:
                    continue

                package = _read_package(full_path)
                if package is None:
                    continue

                # Java convention: a public top-level type's name matches
                # its file's stem -- used directly rather than parsing the
                # actual type declaration's name, which is what Part C's
                # "the class name is the file stem for the public top-level
                # type" specifies.
                class_name = full_path.stem
                fqn = f"{package}.{class_name}" if package else class_name

                class_index[fqn] = full_path.relative_to(root).as_posix()
                package_index.setdefault(package, []).append(fqn)

        for classes in package_index.values():
            classes.sort()  # deterministic wildcard-cap order

        self._class_index = class_index
        self._package_index = package_index

    def extract_imports(self, file_path: str, repo_root: str) -> list[str]:
        root = Path(repo_root)
        try:
            source = (root / file_path).read_bytes()
        except OSError:
            return []
        try:
            tree = Parser(_JAVA_LANGUAGE).parse(source)
        except Exception:
            return []

        targets: list[str] = []
        for node in tree.root_node.children:
            if node.type != "import_declaration":
                continue
            extracted = _parse_import_declaration(node)
            if extracted is None:
                continue
            dotted, is_static, is_wildcard = extracted
            targets.extend(self._resolve_import(dotted, is_static, is_wildcard))
        return targets

    def _resolve_import(self, dotted: str, is_static: bool, is_wildcard: bool) -> list[str]:
        if is_wildcard:
            classes = self._package_index.get(dotted, [])
            return [self._class_index[fqn] for fqn in classes[:MAX_WILDCARD_EDGES]]

        class_fqn = dotted.rsplit(".", 1)[0] if is_static else dotted
        path = self._class_index.get(class_fqn)
        return [path] if path is not None else []

    def extract_symbols(self, file_path: str, repo_root: str) -> list[Symbol]:
        root = Path(repo_root)
        try:
            source = (root / file_path).read_bytes()
        except OSError:
            return []
        try:
            tree = Parser(_JAVA_LANGUAGE).parse(source)
        except Exception:
            return []

        symbols: list[Symbol] = []
        for node in _walk_symbol_nodes(tree.root_node):
            name_node = node.child_by_field_name("name")
            if name_node is None:
                continue
            symbols.append(
                Symbol(
                    name=cast(bytes, name_node.text).decode(),
                    kind=_SYMBOL_KINDS[node.type],
                    line=node.start_point[0] + 1,
                    exported=_has_public_modifier(node),
                )
            )
        return symbols


def _read_package(full_path: Path) -> str | None:
    """Returns the dotted package name from a .java file's
    ``package_declaration`` (empty string for the default/unnamed package),
    or None if the file can't be read or parsed at all."""
    try:
        source = full_path.read_bytes()
    except OSError:
        return None
    try:
        tree = Parser(_JAVA_LANGUAGE).parse(source)
    except Exception:
        return None

    for child in tree.root_node.children:
        if child.type != "package_declaration":
            continue
        name_node = next(
            (c for c in child.children if c.type in ("scoped_identifier", "identifier")), None
        )
        return cast(bytes, name_node.text).decode() if name_node is not None else ""
    return ""


def _parse_import_declaration(node: Node) -> tuple[str, bool, bool] | None:
    """Returns (dotted_name, is_static, is_wildcard) for one
    ``import_declaration`` node. For a wildcard import, ``dotted_name`` is
    the package only (the ``scoped_identifier`` child's span never includes
    the trailing ``.*``). For a static import, ``dotted_name`` still
    includes the trailing member -- callers strip it (Part C: "strip the
    trailing member first")."""
    is_static = any(c.type == "static" for c in node.children)
    is_wildcard = any(c.type == "asterisk" for c in node.children)
    name_node = next(
        (c for c in node.children if c.type in ("scoped_identifier", "identifier")), None
    )
    if name_node is None:
        return None
    return cast(bytes, name_node.text).decode(), is_static, is_wildcard


def _has_public_modifier(node: Node) -> bool:
    modifiers = next((c for c in node.children if c.type == "modifiers"), None)
    if modifiers is None:
        return False
    return any(m.type == "public" for m in modifiers.children)


def _walk_symbol_nodes(node: Node) -> Iterator[Node]:
    if node.type in _SYMBOL_KINDS:
        yield node
    for child in node.children:
        yield from _walk_symbol_nodes(child)
