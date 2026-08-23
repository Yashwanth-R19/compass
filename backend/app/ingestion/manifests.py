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

Designed to be extensible -- session 10 reuses ``repo_manifests`` for
dependency-manifest data rather than inventing a parallel table, which is
why ``kind``/``data`` is a generic (tag, JSON blob) shape instead of one
column per manifest type.
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
