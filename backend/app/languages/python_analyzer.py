from collections.abc import Iterator
from pathlib import Path
from typing import cast

import tree_sitter_python as tspython
from tree_sitter import Language, Node, Parser

from app.languages.base import LanguageAnalyzer

_PY_LANGUAGE = Language(tspython.language())


class PythonAnalyzer(LanguageAnalyzer):
    """tree-sitter-backed import extractor for ``.py`` files.

    Best-effort resolution only: a dotted module target is mapped to a
    repo-relative file (``a.b.c`` -> ``a/b/c.py`` or ``a/b/c/__init__.py``)
    only when that path actually exists under ``repo_root``. Anything that
    doesn't resolve inside the repo -- stdlib, third-party packages,
    src/-layout re-rooting, sys.path manipulation -- is silently dropped
    rather than guessed at: a missed edge is fine here, a fabricated one is
    not (it would corrupt both the architecture graph and the
    hidden-dependency overlay, which specifically looks for the *absence* of
    a structural edge).
    """

    @property
    def language(self) -> str:
        return "python"

    def extract_imports(self, file_path: str, repo_root: str) -> list[str]:
        root = Path(repo_root)
        try:
            source = (root / file_path).read_bytes()
        except OSError:
            return []

        try:
            tree = Parser(_PY_LANGUAGE).parse(source)
        except Exception:
            return []

        current_dir = Path(file_path).parent
        targets: list[str] = []
        for node in _walk_import_nodes(tree.root_node):
            targets.extend(_resolve(node, current_dir, root))
        return targets


def _walk_import_nodes(node: Node) -> Iterator[Node]:
    if node.type in ("import_statement", "import_from_statement"):
        yield node
        return  # these nodes don't nest further import statements inside them
    for child in node.children:
        yield from _walk_import_nodes(child)


def _dotted_parts(node: Node) -> list[str]:
    """``a.b.c`` (a dotted_name node, possibly wrapped in aliased_import) -> ["a", "b", "c"]."""
    if node.type == "aliased_import":
        node = node.children[0]
    return [cast(bytes, c.text).decode() for c in node.children if c.type == "identifier"]


def _resolve_module(repo_root: Path, rel_dir: Path, parts: list[str]) -> str | None:
    """Try ``rel_dir/parts`` as a module (``.py``) then a package (``/__init__.py``)."""
    candidate = rel_dir.joinpath(*parts) if parts else rel_dir

    if candidate != Path("."):
        as_module = candidate.with_suffix(".py")
        if (repo_root / as_module).is_file():
            return as_module.as_posix()

    as_package = candidate / "__init__.py"
    if (repo_root / as_package).is_file():
        return as_package.as_posix()

    return None


def _resolve(node: Node, current_dir: Path, repo_root: Path) -> list[str]:
    if node.type == "import_statement":
        targets = []
        for child in node.children:
            if child.type in ("dotted_name", "aliased_import"):
                resolved = _resolve_module(repo_root, Path("."), _dotted_parts(child))
                if resolved:
                    targets.append(resolved)
        return targets

    # import_from_statement: split children at the literal 'import' keyword --
    # everything before is the source module (relative dots and/or a dotted
    # module path), everything after is the list of imported names.
    children = node.children
    import_idx = next(i for i, c in enumerate(children) if c.type == "import")
    before, after = children[:import_idx], children[import_idx + 1 :]

    relative = next((c for c in before if c.type == "relative_import"), None)
    if relative is not None:
        dots = sum(
            1
            for prefix in relative.children
            if prefix.type == "import_prefix"
            for tok in prefix.children
            if tok.type == "."
        )
        base_dir = current_dir
        for _ in range(dots - 1):
            base_dir = base_dir.parent
        nested = next((c for c in relative.children if c.type == "dotted_name"), None)
        if nested is not None:
            base_dir = base_dir.joinpath(*_dotted_parts(nested))
    else:
        module_name = next((c for c in before if c.type == "dotted_name"), None)
        if module_name is None:
            return []
        base_dir = Path(".").joinpath(*_dotted_parts(module_name))

    # Each imported name might itself be a submodule (`from pkg import sub`
    # where sub is pkg/sub.py) -- try that first per name, since it's the
    # more specific/accurate edge.
    resolved_targets: list[str] = []
    for name_node in after:
        if name_node.type not in ("dotted_name", "aliased_import"):
            continue  # skips ',' tokens and wildcard_import ('*')
        parts = _dotted_parts(name_node)
        if not parts:
            continue
        resolved = _resolve_module(repo_root, base_dir, [parts[-1]])
        if resolved:
            resolved_targets.append(resolved)

    if not resolved_targets:
        # No imported name resolved as its own submodule (or this was a
        # bare `from X import *`) -- fall back to the module itself, e.g.
        # `from pkg.utils import CONSTANT` resolving to pkg/utils.py.
        fallback = _resolve_module(repo_root, base_dir, [])
        if fallback:
            resolved_targets.append(fallback)

    return resolved_targets
