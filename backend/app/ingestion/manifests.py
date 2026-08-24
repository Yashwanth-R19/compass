"""Manifest extraction (session 03, Part D): pulls a small, named set of
fields out of a repo's project manifests -- package.json, pyproject.toml,
a Dockerfile, a Procfile, pom.xml, build.gradle(.kts), setup.py, any
requirements*.txt, README*, LICENSE* -- and NEVER the whole file. Feeds the
``repo_manifests`` Facts table (app/db/models.py::RepoManifest).

Same conservatism as the LanguageAnalyzer plugins: a manifest that fails to
parse in its expected format (invalid JSON/TOML/XML) is silently skipped,
never guessed at, and a manifest field that isn't trivially extractable
(setup.py's entry_points when it isn't a literal) is simply omitted rather
than approximated.

Designed to be extensible -- the ``kind``/``data`` generic (tag, JSON blob)
shape was anticipated to make session 10's dependency data reuse this same
table. That didn't happen: session 10's actual spec (``dependencies_declared``,
app/db/models.py) creates a DEDICATED Facts table instead, since dependency
rows need a structured, directly-queryable shape (ecosystem/package/version/
is_direct/scope) for OSV lookups and joins -- a JSON blob keyed by manifest
kind would need re-parsing on every read. ``extract_declared_dependencies``
below is a SEPARATE extraction pass for exactly that reason; this stale note
is left here (not deleted) as the documented record of that plan-vs-actual
divergence, per plan/RULES.md sec 2.5.

Session 10, Part C also adds ``extract_declared_dependencies`` -- a
dedicated pass over the same four manifest FORMATS this module already
partially recognizes (``requirements*.txt``, ``pyproject.toml``, plus two
new ones this session cares about, ``package-lock.json`` and ``pom.xml``),
extracting STRUCTURED dependency rows (ecosystem/package_name/version/
is_direct/scope) rather than the shallow untyped field dump ``extract_manifests``
above performs. It is a genuinely separate walk (same IGNORE_DIRS/
MAX_FILE_BYTES discipline) because its output shape and purpose are
different, not because the two couldn't share a walk -- see that function's
own docstring for the four formats' exact parsing rules and Known Hazard #5
(package-lock.json's three format versions).
"""

import ast
import json
import os
import re
import tomllib
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app.ingestion.miner import IGNORE_DIRS, MAX_FILE_BYTES

_EXACT_NAME_KIND: dict[str, str] = {
    "package.json": "package_json",
    "pyproject.toml": "pyproject",
    "Dockerfile": "dockerfile",
    "Procfile": "procfile",
    "pom.xml": "pom_xml",
    "build.gradle": "build_gradle",
    "build.gradle.kts": "build_gradle",
    "setup.py": "setup_py",
}


@dataclass(frozen=True)
class ManifestRow:
    """One extracted manifest -- ``path`` is repo-relative, ``kind`` is one
    of the ``_EXACT_NAME_KIND`` values plus "requirements"/"readme"/
    "license", ``data`` holds only the fields that manifest's extractor
    pulled out, never the raw file content."""

    path: str
    kind: str
    data: dict


def _classify_filename(name: str) -> str | None:
    if name in _EXACT_NAME_KIND:
        return _EXACT_NAME_KIND[name]
    if name.startswith("requirements") and name.endswith(".txt"):
        return "requirements"
    upper = name.upper()
    if upper.startswith("README"):
        return "readme"
    if upper.startswith("LICENSE") or upper.startswith("LICENCE"):
        return "license"
    return None


def _extract_package_json(content: bytes) -> dict | None:
    try:
        data = json.loads(content.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    fields = {}
    for key in (
        "name",
        "main",
        "module",
        "scripts",
        "workspaces",
        "dependencies",
        "devDependencies",
    ):
        if key in data:
            fields[key] = data[key]
    return fields


def _extract_pyproject(content: bytes) -> dict | None:
    try:
        data = tomllib.loads(content.decode("utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError):
        return None

    fields: dict = {}
    project = data.get("project")
    if isinstance(project, dict):
        for key in ("name", "scripts", "dependencies"):
            if key in project:
                fields[key] = project[key]

    tool = data.get("tool")
    poetry = tool.get("poetry") if isinstance(tool, dict) else None
    if isinstance(poetry, dict):
        poetry_fields = {
            key: poetry[key] for key in ("name", "scripts", "dependencies") if key in poetry
        }
        if poetry_fields:
            fields["poetry"] = poetry_fields

    return fields


def _extract_requirements(content: bytes) -> dict | None:
    text = content.decode("utf-8", errors="replace")
    lines = [line.strip() for line in text.splitlines()]
    return {"lines": [line for line in lines if line]}


_DOCKERFILE_INSTRUCTION_RE = re.compile(r"^(CMD|ENTRYPOINT)\s+(.*)$", re.IGNORECASE)


def _extract_dockerfile(content: bytes) -> dict | None:
    text = content.decode("utf-8", errors="replace")
    result: dict[str, list[str]] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = _DOCKERFILE_INSTRUCTION_RE.match(line)
        if match is None:
            continue
        instruction = match.group(1).upper()
        result.setdefault(instruction, []).append(match.group(2).strip())
    return result


def _extract_procfile(content: bytes) -> dict | None:
    text = content.decode("utf-8", errors="replace")
    return {"lines": [line.strip() for line in text.splitlines() if line.strip()]}


def _local_tag(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _extract_pom_xml(content: bytes) -> dict | None:
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return None

    result: dict = {}

    for elem in root.iter():
        if _local_tag(elem.tag) == "mainClass" and elem.text and elem.text.strip():
            result["mainClass"] = elem.text.strip()
            break

    dependencies = []
    for child in root:
        if _local_tag(child.tag) != "dependencies":
            continue
        for dep in child:
            if _local_tag(dep.tag) != "dependency":
                continue
            entry = {}
            for field in dep:
                name = _local_tag(field.tag)
                if name in ("groupId", "artifactId", "version") and field.text:
                    entry[name] = field.text.strip()
            if entry:
                dependencies.append(entry)
        break  # only the top-level <project><dependencies> block, not <dependencyManagement>
    if dependencies:
        result["dependencies"] = dependencies

    return result


_GRADLE_COORDINATE_RE = re.compile(
    r"""['"]([a-zA-Z0-9_.\-]+:[a-zA-Z0-9_.\-]+:[a-zA-Z0-9_.+\-]+)['"]"""
)


def _extract_build_gradle(content: bytes) -> dict | None:
    text = content.decode("utf-8", errors="replace")
    coordinates = sorted(set(_GRADLE_COORDINATE_RE.findall(text)))
    return {"dependencies": coordinates}


def _extract_setup_py(content: bytes) -> dict | None:
    try:
        tree = ast.parse(content.decode("utf-8"))
    except (UnicodeDecodeError, SyntaxError):
        return {}

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if keyword.arg != "entry_points":
                continue
            try:
                value = ast.literal_eval(keyword.value)
            except (ValueError, SyntaxError):
                return {}
            return {"entry_points": value}
    return {}


_MD_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$")
_UNDERLINE_RE = re.compile(r"^[=\-~^\"'`#*+.:_]{3,}\s*$")


def _extract_readme(content: bytes) -> dict | None:
    text = content.decode("utf-8", errors="replace")
    lines = text.splitlines()

    heading = None
    for i, line in enumerate(lines):
        md_match = _MD_HEADING_RE.match(line)
        if md_match:
            heading = md_match.group(1).strip()
            break
        stripped = line.strip()
        next_line = lines[i + 1].strip() if i + 1 < len(lines) else ""
        if stripped and _UNDERLINE_RE.match(next_line) and len(next_line) >= len(stripped):
            heading = stripped
            break

    return {"heading": heading, "line_count": len(lines)}


# Simple keyword match, no external service -- ordered so a more specific
# license (e.g. BSD-3-Clause, whose text is a superset of BSD-2-Clause's) is
# checked before the license it's a superset of.
_SPDX_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("Apache-2.0", ("apache license", "version 2.0")),
    ("MPL-2.0", ("mozilla public license", "version 2.0")),
    ("GPL-3.0", ("gnu general public license", "version 3")),
    ("GPL-2.0", ("gnu general public license", "version 2")),
    ("LGPL-3.0", ("gnu lesser general public license", "version 3")),
    ("LGPL-2.1", ("gnu lesser general public license", "version 2.1")),
    ("BSD-3-Clause", ("redistribution and use in source and binary forms", "neither the name")),
    ("BSD-2-Clause", ("redistribution and use in source and binary forms",)),
    ("MIT", ("permission is hereby granted, free of charge",)),
    ("ISC", ("permission to use, copy, modify, and/or distribute",)),
    ("Unlicense", ("this is free and unencumbered software",)),
]


def _extract_license(content: bytes) -> dict | None:
    text = content.decode("utf-8", errors="replace").lower()
    for spdx_id, keywords in _SPDX_KEYWORDS:
        if all(keyword in text for keyword in keywords):
            return {"spdx_id": spdx_id}
    return {"spdx_id": None}


_EXTRACTORS: dict[str, Callable[[bytes], dict | None]] = {
    "package_json": _extract_package_json,
    "pyproject": _extract_pyproject,
    "dockerfile": _extract_dockerfile,
    "procfile": _extract_procfile,
    "pom_xml": _extract_pom_xml,
    "build_gradle": _extract_build_gradle,
    "setup_py": _extract_setup_py,
    "requirements": _extract_requirements,
    "readme": _extract_readme,
    "license": _extract_license,
}


def extract_manifests(repo_root: str) -> list[ManifestRow]:
    """Walks the checkout (same IGNORE_DIRS pruning as the miner/scanner)
    looking for known manifest filenames at any depth -- monorepos routinely
    have more than one package.json/requirements.txt. A manifest that fails
    to parse in its expected format, or throws for any other reason, is
    silently skipped rather than guessed at or allowed to fail the whole
    structure stage.
    """
    root = Path(repo_root)
    rows: list[ManifestRow] = []

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS]
        for fname in filenames:
            kind = _classify_filename(fname)
            if kind is None:
                continue

            full_path = Path(dirpath) / fname
            try:
                if full_path.stat().st_size > MAX_FILE_BYTES:
                    continue
                content = full_path.read_bytes()
            except OSError:
                continue

            try:
                data = _EXTRACTORS[kind](content)
            except Exception:
                continue
            if data is None:
                continue

            rel_path = full_path.relative_to(root).as_posix()
            rows.append(ManifestRow(path=rel_path, kind=kind, data=data))

    rows.sort(key=lambda r: r.path)
    return rows


# ======================================================================
# Declared-dependency parsing (session 10, Part C) -- feeds
# dependencies_declared, NOT repo_manifests (see this module's docstring).
# ======================================================================


@dataclass(frozen=True)
class DeclaredDependency:
    """One parsed dependency declaration, ready for
    ``app/ingestion/persist.py::persist_facts`` to intern
    ``manifest_path`` and insert. ``ecosystem`` is OSV's exact,
    case-sensitive ecosystem name (``"PyPI"``/``"npm"``/``"Maven"`` --
    session 10 Known Hazard #4). ``version`` is ``None`` for a declared
    RANGE (recorded for completeness, never queryable against OSV -- see
    app/engines/security.py::load_declared_dependencies). ``scope`` is one
    of "runtime"/"dev"/"test"."""

    manifest_path: str
    ecosystem: str
    package_name: str
    version: str | None
    is_direct: bool
    scope: str


_REQUIREMENT_LINE_RE = re.compile(
    r"^([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]*\])?\s*(==\s*([^\s;#,]+))?"
)


def _requirements_scope_for_filename(name: str) -> str:
    lower = name.lower()
    if "dev" in lower:
        return "dev"
    if "test" in lower:
        return "test"
    return "runtime"


def _parse_requirements_file(path: Path, *, visited: set[Path]) -> list[tuple[str, str | None]]:
    """Handles ``==``/``>=``/extras/``-r`` includes (session 10 Part C);
    skips URLs and editable installs (``-e``/``--editable``). ``-r other.txt``
    is resolved relative to the INCLUDING file's own directory and parsed
    recursively -- ``visited`` (shared across the whole recursion) guards
    against a self-referential/circular include looping forever."""
    resolved = path.resolve()
    if resolved in visited or not path.is_file():
        return []
    visited.add(resolved)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    deps: list[tuple[str, str | None]] = []
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("-r ") or line.startswith("--requirement "):
            included = line.split(None, 1)[1].strip()
            deps.extend(_parse_requirements_file(path.parent / included, visited=visited))
            continue
        if line.startswith("-") or "://" in line:
            # Other pip flags (-c/--constraint, --index-url, ...), editable
            # installs, and URL/VCS requirements -- never guessed at.
            continue
        match = _REQUIREMENT_LINE_RE.match(line)
        if not match:
            continue
        deps.append((match.group(1), match.group(3)))
    return deps


_PEP508_NAME_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)")


def _parse_requirement_spec(spec: str) -> tuple[str, str | None] | None:
    """One PEP 508 dependency string from ``[project.dependencies]``, e.g.
    ``"requests>=2.0"`` or ``"requests==2.31.0; python_version >= '3.8'"``."""
    spec = spec.split(";", 1)[0].strip()  # drop environment markers
    match = _PEP508_NAME_RE.match(spec)
    if not match:
        return None
    name = match.group(1)
    rest = re.sub(r"^\[[^\]]*\]", "", spec[len(name) :]).strip()  # drop extras
    version = rest[2:].split(",")[0].strip() if rest.startswith("==") else None
    return name, version or None


def _extract_pyproject_dependencies(content: bytes) -> list[tuple[str, str | None]]:
    try:
        data = tomllib.loads(content.decode("utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError):
        return []
    project = data.get("project")
    raw_deps = project.get("dependencies") if isinstance(project, dict) else None
    if not isinstance(raw_deps, list):
        return []
    deps = []
    for entry in raw_deps:
        if not isinstance(entry, str):
            continue
        parsed = _parse_requirement_spec(entry)
        if parsed is not None:
            deps.append(parsed)
    return deps


def _extract_pom_dependencies(content: bytes) -> list[tuple[str, str | None, str]]:
    """Top-level ``<project><dependencies>`` only (never
    ``<dependencyManagement>``, same restriction ``_extract_pom_xml`` above
    already applies), resolving ``${property}`` placeholders defined in this
    SAME file's ``<properties>`` block. A dependency whose version can't be
    resolved this way (inherited from a parent POM/BOM, or a property
    defined elsewhere) is skipped entirely -- never guessed at (session 10
    Part C: "skip ones you cannot resolve")."""
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return []

    properties: dict[str, str] = {}
    for child in root:
        if _local_tag(child.tag) != "properties":
            continue
        for prop in child:
            if prop.text:
                properties[_local_tag(prop.tag)] = prop.text.strip()

    def _resolve(raw: str) -> str | None:
        match = re.fullmatch(r"\$\{([^}]+)\}", raw.strip())
        return properties.get(match.group(1)) if match else raw.strip()

    results: list[tuple[str, str | None, str]] = []
    for child in root:
        if _local_tag(child.tag) != "dependencies":
            continue
        for dep in child:
            if _local_tag(dep.tag) != "dependency":
                continue
            fields = {_local_tag(f.tag): f.text.strip() for f in dep if f.text and f.text.strip()}
            group_id, artifact_id = fields.get("groupId"), fields.get("artifactId")
            if not group_id or not artifact_id:
                continue
            raw_version = fields.get("version")
            version = _resolve(raw_version) if raw_version else None
            if raw_version and version is None:
                continue
            scope = "test" if fields.get("scope") == "test" else "runtime"
            results.append((f"{group_id}:{artifact_id}", version, scope))
        break  # top-level <project><dependencies> only
    return results


def _parse_package_lock(content: bytes) -> list[tuple[str, str | None, bool, str]]:
    """``(package_name, version, is_direct, scope)`` tuples. Handles v2/v3
    (``"packages"``, keyed by path, ``node_modules/``-prefixed) preferentially,
    falling back to v1 (``"dependencies"``, a nested tree) -- session 10
    Known Hazard #5. Any other/unrecognized shape yields nothing, never a
    guess."""
    try:
        data = json.loads(content.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return []
    if not isinstance(data, dict):
        return []

    packages = data.get("packages")
    if isinstance(packages, dict):
        return _parse_package_lock_v2_v3(packages)

    dependencies = data.get("dependencies")
    if isinstance(dependencies, dict):
        return _parse_package_lock_v1(dependencies)

    return []


def _parse_package_lock_v2_v3(packages: dict) -> list[tuple[str, str | None, bool, str]]:
    root = packages.get("", {})
    direct_names: set[str] = set()
    if isinstance(root, dict):
        for key in ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies"):
            deps = root.get(key)
            if isinstance(deps, dict):
                direct_names.update(deps.keys())

    results: list[tuple[str, str | None, bool, str]] = []
    for pkg_path, entry in packages.items():
        if pkg_path == "" or not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if not name:
            if "node_modules/" not in pkg_path:
                continue
            name = pkg_path.rsplit("node_modules/", 1)[-1]
        version = entry.get("version")
        scope = "dev" if entry.get("dev") else "runtime"
        results.append((name, version, name in direct_names, scope))
    return results


def _parse_package_lock_v1(
    dependencies: dict, *, _depth: int = 0
) -> list[tuple[str, str | None, bool, str]]:
    results: list[tuple[str, str | None, bool, str]] = []
    for name, entry in dependencies.items():
        if not isinstance(entry, dict):
            continue
        version = entry.get("version")
        scope = "dev" if entry.get("dev") else "runtime"
        results.append((name, version, _depth == 0, scope))
        nested = entry.get("dependencies")
        if isinstance(nested, dict):
            results.extend(_parse_package_lock_v1(nested, _depth=_depth + 1))
    return results


_SUPPORTED_DEPENDENCY_MANIFEST_NAMES = {"pyproject.toml", "package-lock.json", "pom.xml"}


def extract_declared_dependencies(repo_root: str) -> tuple[list[DeclaredDependency], bool]:
    """Walks the checkout (same IGNORE_DIRS/MAX_FILE_BYTES discipline as
    every other walk in this module) looking for the four supported
    dependency-manifest formats. Returns ``(rows, manifest_found)`` --
    ``manifest_found`` is True the moment ANY of the four file types is
    found on disk, REGARDLESS of whether it yielded any parseable
    dependency rows: an empty/malformed ``requirements.txt`` is still "a
    supported manifest was present," which must read as an honest empty
    result at the API layer, not "no supported manifest" (session 10 Part
    C: "an empty vulnerability list because nothing was scanned must not
    look like an empty list because nothing was found").
    """
    root = Path(repo_root)
    rows: list[DeclaredDependency] = []
    manifest_found = False
    visited_requirements: set[Path] = set()

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS]
        for fname in filenames:
            is_requirements = fname.startswith("requirements") and fname.endswith(".txt")
            if not (is_requirements or fname in _SUPPORTED_DEPENDENCY_MANIFEST_NAMES):
                continue

            full_path = Path(dirpath) / fname
            try:
                if full_path.stat().st_size > MAX_FILE_BYTES:
                    continue
            except OSError:
                continue
            manifest_found = True
            rel_path = full_path.relative_to(root).as_posix()

            try:
                if is_requirements:
                    if full_path.resolve() in visited_requirements:
                        continue
                    scope = _requirements_scope_for_filename(fname)
                    for name, version in _parse_requirements_file(
                        full_path, visited=visited_requirements
                    ):
                        rows.append(
                            DeclaredDependency(rel_path, "PyPI", name, version, True, scope)
                        )
                elif fname == "pyproject.toml":
                    for name, version in _extract_pyproject_dependencies(full_path.read_bytes()):
                        rows.append(
                            DeclaredDependency(rel_path, "PyPI", name, version, True, "runtime")
                        )
                elif fname == "package-lock.json":
                    for name, version, is_direct, scope in _parse_package_lock(
                        full_path.read_bytes()
                    ):
                        rows.append(
                            DeclaredDependency(rel_path, "npm", name, version, is_direct, scope)
                        )
                elif fname == "pom.xml":
                    for package_name, version, scope in _extract_pom_dependencies(
                        full_path.read_bytes()
                    ):
                        rows.append(
                            DeclaredDependency(
                                rel_path, "Maven", package_name, version, True, scope
                            )
                        )
            except Exception:
                # Same conservatism as extract_manifests above: a manifest
                # that fails to parse in its expected format never fails the
                # whole "structure" stage.
                continue

    rows.sort(key=lambda r: (r.manifest_path, r.ecosystem, r.package_name))
    return rows, manifest_found
