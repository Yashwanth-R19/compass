import json
import os
import posixpath
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import tree_sitter_javascript as tsjavascript
import tree_sitter_typescript as tstypescript
from tree_sitter import Language, Node, Parser

from app.ingestion.miner import IGNORE_DIRS
from app.languages.base import LanguageAnalyzer, Symbol

_JS_LANGUAGE = Language(tsjavascript.language())
_TS_LANGUAGE = Language(tstypescript.language_typescript())
_TSX_LANGUAGE = Language(tstypescript.language_tsx())

_GRAMMAR_BY_EXT: dict[str, Language] = {
    ".js": _JS_LANGUAGE,
    ".jsx": _JS_LANGUAGE,
    ".mjs": _JS_LANGUAGE,
    ".cjs": _JS_LANGUAGE,
    ".ts": _TS_LANGUAGE,
    ".mts": _TS_LANGUAGE,
    ".cts": _TS_LANGUAGE,
    ".tsx": _TSX_LANGUAGE,
}

# Base extensions tried, in order, when a specifier doesn't already resolve
# literally -- APPENDED to the candidate path (never substituted), except
# for the dedicated .js->.ts swap below. Index-file extensions are a
# smaller, explicit list per Part B ("<spec>/index.ts /index.tsx /index.js
# /index.jsx") -- .mjs/.cjs index files are deliberately not tried, matching
# that literal list.
_APPEND_EXTENSIONS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")
_INDEX_EXTENSIONS = (".ts", ".tsx", ".js", ".jsx")
_KNOWN_EXTENSIONS = frozenset({".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"})

_CONFIG_FILENAMES = ("tsconfig.json", "jsconfig.json")


@dataclass(frozen=True)
class _AliasConfig:
    """One tsconfig/jsconfig's path-alias table. ``base_dir`` is the
    repo-relative posix directory ``paths`` entries resolve against --
    ``compilerOptions.baseUrl`` joined onto the config's own directory when
    present, or (TS 4.1+) the config's own directory directly when absent."""

    base_dir: str
    paths: dict[str, list[str]]


class JavaScriptAnalyzer(LanguageAnalyzer):
    """tree-sitter-backed import extractor for JavaScript AND TypeScript --
    ONE class, registered under both "javascript" and "typescript" registry
    keys (app/languages/scanner.py); only the tree-sitter grammar picked per
    file extension differs (Part B). Same conservatism as PythonAnalyzer
    (see its docstring): a specifier that doesn't resolve to a real file
    inside the repo is silently dropped, never guessed at.

    Path aliases (tsconfig/jsconfig ``compilerOptions.paths``) are
    discovered once per run in ``prepare()``, not per file -- the same
    O(n^2) hazard Java's class index guards against (Part C). The NEAREST
    config walking upward from the importing file is used, not the root
    one, since a monorepo can have several.
    """

    def __init__(self) -> None:
        self._alias_configs: dict[str, _AliasConfig] = {}

    @property
    def language(self) -> str:
        return "javascript"

    def prepare(self, repo_root: str) -> None:
        self._alias_configs = _discover_alias_configs(repo_root)

    def extract_imports(self, file_path: str, repo_root: str) -> list[str]:
        return [target for target, _kind in self._extract_resolved(file_path, repo_root)]

    def extract_import_edges(self, file_path: str, repo_root: str) -> list[tuple[str, str]]:
        """Non-ABC extension (session 03): the same resolved targets as
        ``extract_imports``, paired with "static"/"dynamic" import_kind, in
        one parse pass. ``app/languages/scanner.py`` calls this instead of
        ``extract_imports`` for JS/TS files (detected via ``isinstance``) so
        a dynamic ``import(...)`` edge can be tagged without re-parsing the
        file or widening the shared ``LanguageAnalyzer`` interface."""
        return self._extract_resolved(file_path, repo_root)

    def _extract_resolved(self, file_path: str, repo_root: str) -> list[tuple[str, str]]:
        root = Path(repo_root)
        grammar = _GRAMMAR_BY_EXT.get(Path(file_path).suffix.lower())
        if grammar is None:
            return []

        try:
            source = (root / file_path).read_bytes()
        except OSError:
            return []
        try:
            tree = Parser(grammar).parse(source)
        except Exception:
            return []

        importing_dir = posixpath.dirname(file_path)
        resolved: list[tuple[str, str]] = []
        for node in _walk_import_like_nodes(tree.root_node):
            extracted = _extract_import_target(node)
            if extracted is None:
                continue
            specifier, import_kind = extracted
            target = _resolve_specifier(specifier, importing_dir, root, self._alias_configs)
            if target is not None:
                resolved.append((target, import_kind))
        return resolved

    def extract_symbols(self, file_path: str, repo_root: str) -> list[Symbol]:
        root = Path(repo_root)
        grammar = _GRAMMAR_BY_EXT.get(Path(file_path).suffix.lower())
        if grammar is None:
            return []

        try:
            source = (root / file_path).read_bytes()
        except OSError:
            return []
        try:
            tree = Parser(grammar).parse(source)
        except Exception:
            return []

        symbols: list[Symbol] = []
        for node, kind, exported in _walk_symbol_nodes(tree.root_node):
            name_node = node.child_by_field_name("name")
            if name_node is None:
                continue
            name = cast(bytes, name_node.text).decode()
            symbols.append(
                Symbol(name=name, kind=kind, line=node.start_point[0] + 1, exported=exported)
            )
        return symbols


# ---------------------------------------------------------------------------
# Import/require/dynamic-import extraction
# ---------------------------------------------------------------------------


def _walk_import_like_nodes(node: Node) -> Iterator[Node]:
    """Unlike PythonAnalyzer's import walk, keeps recursing into every
    node's children -- a require()/import() call can itself be nested
    inside another expression's arguments, and export_statement/
    import_statement never nest further import statements inside them
    anyway, so unconditional recursion is safe and simplest."""
    if node.type in ("import_statement", "export_statement", "call_expression"):
        yield node
    for child in node.children:
        yield from _walk_import_like_nodes(child)


def _string_literal_text(node: Node) -> str | None:
    """The literal value of a plain (non-template) JS/TS string node --
    ``string`` wraps quotes around one or more ``string_fragment`` children.
    Returns None for anything else (a template_string, a concatenation
    expression, an identifier, ...) -- those aren't statically resolvable
    and must be dropped, never guessed at (Part B's template-literal
    dynamic-import case)."""
    if node.type != "string":
        return None
    fragments = [cast(bytes, c.text).decode() for c in node.children if c.type == "string_fragment"]
    return "".join(fragments)


def _extract_import_target(node: Node) -> tuple[str, str] | None:
    """Returns (specifier, import_kind) for one relevant node, or None when
    this particular node isn't a resolvable import/require/dynamic-import
    (e.g. a plain `export {x}` with no `from` clause, or a require()/
    import() call with zero or more than one argument)."""
    if node.type in ("import_statement", "export_statement"):
        source = node.child_by_field_name("source")
        if source is None:
            return None
        specifier = _string_literal_text(source)
        return (specifier, "static") if specifier is not None else None

    if node.type == "call_expression":
        func = node.child_by_field_name("function")
        args = node.child_by_field_name("arguments")
        if func is None or args is None:
            return None
        arg_nodes = [c for c in args.children if c.type not in ("(", ")", ",")]
        if len(arg_nodes) != 1:
            return None

        if func.type == "identifier" and cast(bytes, func.text).decode() == "require":
            specifier = _string_literal_text(arg_nodes[0])
            return (specifier, "static") if specifier is not None else None

        if func.type == "import":
            specifier = _string_literal_text(arg_nodes[0])
            return (specifier, "dynamic") if specifier is not None else None

    return None


# ---------------------------------------------------------------------------
# Specifier resolution: relative paths, path aliases, extension guessing
# ---------------------------------------------------------------------------


def _resolve_candidate(repo_root: Path, spec_path: str) -> str | None:
    """``spec_path`` is a repo-relative posix path candidate BEFORE any
    extension guessing. Tries, in order: the literal path (only if it
    already ends in a known JS/TS extension), the path with each resolvable
    extension appended, the path as a directory's index file, and -- only
    when the specifier itself ends in ``.js`` -- the same path with ``.js``
    swapped for ``.ts`` (extremely common in TypeScript-compiled-to-ESM
    projects). Returns the first that exists as a real file, else None."""
    _, ext = posixpath.splitext(spec_path)

    if ext in _KNOWN_EXTENSIONS and (repo_root / spec_path).is_file():
        return spec_path

    for append_ext in _APPEND_EXTENSIONS:
        candidate = spec_path + append_ext
        if (repo_root / candidate).is_file():
            return candidate

    for index_ext in _INDEX_EXTENSIONS:
        candidate = f"{spec_path}/index{index_ext}"
        if (repo_root / candidate).is_file():
            return candidate

    if ext == ".js":
        swapped = spec_path[: -len(".js")] + ".ts"
        if (repo_root / swapped).is_file():
            return swapped

    return None


def _apply_path_aliases(specifier: str, config: _AliasConfig) -> list[str]:
    """Candidate repo-relative base paths (pre-extension-resolution) for
    ``specifier`` under one tsconfig's ``paths`` map, tried in the map's own
    declared order -- tsconfig authors list patterns in priority order and
    this honors that as-is rather than re-deriving a "most specific" order."""
    candidates: list[str] = []
    for pattern, replacements in config.paths.items():
        if "*" in pattern:
            prefix, _, suffix = pattern.partition("*")
            if not specifier.startswith(prefix) or not specifier.endswith(suffix):
                continue
            matched = (
                specifier[len(prefix) : len(specifier) - len(suffix)]
                if suffix
                else specifier[len(prefix) :]
            )
            for replacement in replacements:
                resolved = (
                    replacement.replace("*", matched, 1) if "*" in replacement else replacement
                )
                candidates.append(posixpath.normpath(posixpath.join(config.base_dir, resolved)))
        elif specifier == pattern:
            for replacement in replacements:
                candidates.append(posixpath.normpath(posixpath.join(config.base_dir, replacement)))
    return candidates


def _find_alias_config(configs: dict[str, _AliasConfig], from_dir: str) -> _AliasConfig | None:
    """Walks upward from ``from_dir`` (a repo-relative posix directory)
    toward the repo root, returning the NEAREST config -- not the root one.
    A monorepo can have several tsconfigs, and picking the wrong one
    resolves aliases into the wrong package (a known hazard, Part B)."""
    current = from_dir
    while True:
        if current in configs:
            return configs[current]
        if current == "":
            return None
        current = posixpath.dirname(current)


def _resolve_specifier(
    specifier: str,
    importing_dir: str,
    repo_root: Path,
    alias_configs: dict[str, _AliasConfig],
) -> str | None:
    if specifier.startswith("."):
        spec_path = posixpath.normpath(posixpath.join(importing_dir, specifier))
        return _resolve_candidate(repo_root, spec_path)

    if specifier.startswith("/"):
        spec_path = posixpath.normpath(specifier.lstrip("/"))
        return _resolve_candidate(repo_root, spec_path)

    # Not relative -- either a configured path alias, or a bare package
    # specifier (npm dependency / Node builtin), which Compass never models
    # since it only tracks intra-repository edges. Silently dropped if no
    # alias matches or none of its candidates resolve to a real file.
    alias_config = _find_alias_config(alias_configs, importing_dir)
    if alias_config is not None:
        for candidate_base in _apply_path_aliases(specifier, alias_config):
            resolved = _resolve_candidate(repo_root, candidate_base)
            if resolved is not None:
                return resolved

    return None


# ---------------------------------------------------------------------------
# tsconfig/jsconfig discovery (Part B: path aliases)
# ---------------------------------------------------------------------------


def _strip_jsonc(text: str) -> str:
    """Strips // and /* */ comments and trailing commas from tsconfig/
    jsconfig text so json.loads can parse it -- both are routinely
    JSON-with-comments, which the stdlib json module rejects outright.
    String-aware: a // or /* sequence inside a quoted string is left alone."""
    result: list[str] = []
    in_string = False
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if in_string:
            result.append(ch)
            if ch == "\\" and i + 1 < n:
                result.append(text[i + 1])
                i += 2
                continue
            if ch == '"':
                in_string = False
            i += 1
            continue

        if ch == '"':
            in_string = True
            result.append(ch)
            i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] not in "\r\n":
                i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "*":
            i += 2
            while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
            continue
        result.append(ch)
        i += 1

    return re.sub(r",(\s*[}\]])", r"\1", "".join(result))


def _load_jsonc(path: Path) -> dict | None:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        data = json.loads(_strip_jsonc(raw))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _discover_alias_configs(repo_root: str) -> dict[str, _AliasConfig]:
    """Walks the whole checkout (monorepo-aware) for tsconfig.json/
    jsconfig.json files, keyed by their own repo-relative directory. A
    directory with both prefers tsconfig.json. A config with no
    ``compilerOptions.paths`` is skipped entirely -- there's nothing for
    ``_find_alias_config`` to apply. On any parse error, that one file is
    skipped silently rather than failing the whole run."""
    root = Path(repo_root)
    configs: dict[str, _AliasConfig] = {}

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS]

        config_name = next((f for f in _CONFIG_FILENAMES if f in filenames), None)
        if config_name is None:
            continue

        data = _load_jsonc(Path(dirpath) / config_name)
        if data is None:
            continue
        compiler_options = data.get("compilerOptions")
        if not isinstance(compiler_options, dict):
            continue
        paths = compiler_options.get("paths")
        if not isinstance(paths, dict) or not paths:
            continue
        normalized_paths = {
            pattern: replacements
            for pattern, replacements in paths.items()
            if isinstance(replacements, list) and replacements
        }
        if not normalized_paths:
            continue

        config_dir = Path(dirpath).relative_to(root).as_posix()
        config_dir = "" if config_dir == "." else config_dir

        base_url = compiler_options.get("baseUrl")
        if isinstance(base_url, str):
            base_dir = posixpath.normpath(posixpath.join(config_dir, base_url))
            base_dir = "" if base_dir == "." else base_dir
        else:
            # TS 4.1+: paths are relative to the tsconfig's own directory
            # when baseUrl is absent.
            base_dir = config_dir

        configs[config_dir] = _AliasConfig(base_dir=base_dir, paths=normalized_paths)

    return configs


# ---------------------------------------------------------------------------
# Symbol extraction
# ---------------------------------------------------------------------------

_SIMPLE_SYMBOL_KINDS = {
    "class_declaration": "class",
    "function_declaration": "function",
    "interface_declaration": "interface",
    "type_alias_declaration": "type",
}


def _is_exported(node: Node) -> bool:
    """True when ``node``'s immediate parent is an export_statement -- both
    a plain ``export X`` and an ``export default X`` wrap X directly in an
    export_statement (no separate "default" nesting level), so one check
    covers both (verified against tree-sitter-typescript's actual node
    shapes for this session)."""
    return node.parent is not None and node.parent.type == "export_statement"


def _walk_symbol_nodes(node: Node) -> Iterator[tuple[Node, str, bool]]:
    """Yields (node, kind, exported) for every symbol-bearing declaration --
    the simple node-type-to-kind cases, a lexical_declaration's
    variable_declarator when its initializer is an arrow function, and a
    method_definition inside a class body. Keeps recursing into every
    node's children, same reasoning as ``_walk_import_like_nodes``."""
    if node.type in _SIMPLE_SYMBOL_KINDS:
        yield node, _SIMPLE_SYMBOL_KINDS[node.type], _is_exported(node)
    elif node.type == "lexical_declaration":
        # export wraps the lexical_declaration itself, not the
        # variable_declarator inside it -- `export const f = () => {}` is
        # export_statement -> lexical_declaration -> variable_declarator, so
        # the declarator's GRANDPARENT is checked, not its parent.
        declaration_exported = _is_exported(node)
        for declarator in node.children:
            if declarator.type != "variable_declarator":
                continue
            value = declarator.child_by_field_name("value")
            if value is not None and value.type == "arrow_function":
                yield declarator, "function", declaration_exported
    elif node.type == "method_definition":
        # A method is never itself directly wrapped in an export_statement
        # -- only its containing class can be -- so this is always False,
        # correctly reflecting JS/TS semantics without special-casing.
        yield node, "method", False

    for child in node.children:
        yield from _walk_symbol_nodes(child)
