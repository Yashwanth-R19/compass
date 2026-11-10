"""Infrastructure and actor nodes for the Map (``app/analysis/diagram.py``).

**This is a documented HEURISTIC, not a measurement.** Infrastructure boxes
are detected from file NAMES (a ``Dockerfile``, a ``render.yaml``, workflow
files under ``.github/workflows/``) and from DECLARED dependencies (a
``psycopg`` row in ``dependencies_declared``) -- never from file contents,
which Compass does not keep. The UI says so next to every infra box.

The only arrows an infra box ever gets are evidence-backed "runs" arrows:
``infra:docker``/``infra:procfile`` point at the groups holding entry points
whose OWN evidence string says a Dockerfile/Procfile references them
(``app/engines/entrypoints.py`` writes exactly ``"Dockerfile CMD"`` /
``"Dockerfile ENTRYPOINT"`` / ``"Procfile references this file"``). A
datastore box never gets an arrow: Compass cannot see which files talk to a
database, and drawing one anyway would be a guess presented as a fact.

Pure functions only -- no DB access, no I/O -- so the rules are trivially
deterministic: same inputs, same output, in the same order.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from app.schemas.diagram import DiagramActorOut, DiagramInfraOut, InfraCategory

MAX_INFRA_EVIDENCE = 5
MAX_INFRA_PATHS = 10

ACTOR_ENTRY_KINDS: tuple[str, ...] = ("web_server", "ui_root", "cli")
"""Entry-point kinds (``EntryPoint.kind``) that represent something a person
or another program actually starts -- the "Users & callers" actor points at
the groups holding these. ``test_root``/``build`` are deliberately excluded:
a test runner or build script isn't a caller of the product."""

ACTOR_FALLBACK_KIND = "graph_inferred"
"""Used only when no manifest/convention-detected entry point exists at all
-- a graph-inferred entry point is weaker evidence, so it never mixes with
the stronger kinds above."""


@dataclass(frozen=True)
class _PathRule:
    infra_id: str
    category: InfraCategory
    label: str
    matches: Callable[[str, PurePosixPath], bool]
    evidence: str


def _basename(p: PurePosixPath) -> str:
    return p.name.lower()


_PATH_RULES: tuple[_PathRule, ...] = (
    _PathRule(
        "infra:docker",
        "container",
        "Docker",
        lambda _path, p: _basename(p) == "dockerfile"
        or _basename(p).startswith("dockerfile.")
        or _basename(p).endswith(".dockerfile"),
        "Dockerfile present",
    ),
    _PathRule(
        "infra:compose",
        "container",
        "Docker Compose",
        lambda _path, p: _basename(p)
        in {"docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"},
        "Compose file present",
    ),
    _PathRule(
        "infra:procfile",
        "deploy",
        "Procfile",
        lambda _path, p: _basename(p) == "procfile",
        "Procfile present",
    ),
    _PathRule(
        "infra:render",
        "deploy",
        "Render",
        lambda _path, p: _basename(p) == "render.yaml",
        "render.yaml present",
    ),
    _PathRule(
        "infra:vercel",
        "deploy",
        "Vercel",
        lambda _path, p: _basename(p) == "vercel.json",
        "vercel.json present",
    ),
    _PathRule(
        "infra:netlify",
        "deploy",
        "Netlify",
        lambda _path, p: _basename(p) == "netlify.toml",
        "netlify.toml present",
    ),
    _PathRule(
        "infra:fly",
        "deploy",
        "Fly.io",
        lambda _path, p: _basename(p) == "fly.toml",
        "fly.toml present",
    ),
    _PathRule(
        "infra:railway",
        "deploy",
        "Railway",
        lambda _path, p: _basename(p) in {"railway.json", "railway.toml"},
        "Railway config present",
    ),
    _PathRule(
        "infra:helm",
        "deploy",
        "Helm chart",
        lambda _path, p: _basename(p) == "chart.yaml",
        "Helm Chart.yaml present",
    ),
    _PathRule(
        "infra:terraform",
        "deploy",
        "Terraform",
        lambda _path, p: p.suffix.lower() == ".tf",
        "Terraform files present",
    ),
    _PathRule(
        "infra:serverless",
        "deploy",
        "Serverless Framework",
        lambda _path, p: _basename(p) in {"serverless.yml", "serverless.yaml"},
        "serverless.yml present",
    ),
    _PathRule(
        "infra:github-actions",
        "ci",
        "GitHub Actions",
        lambda path, p: path.startswith(".github/workflows/")
        and p.suffix.lower() in {".yml", ".yaml"},
        # Replaced with a counted string in detect_infra -- see there.
        "workflow files in .github/workflows",
    ),
    _PathRule(
        "infra:gitlab-ci",
        "ci",
        "GitLab CI",
        lambda path, _p: path == ".gitlab-ci.yml",
        ".gitlab-ci.yml present",
    ),
    _PathRule(
        "infra:jenkins",
        "ci",
        "Jenkins",
        lambda _path, p: _basename(p) == "jenkinsfile",
        "Jenkinsfile present",
    ),
    _PathRule(
        "infra:circleci",
        "ci",
        "CircleCI",
        lambda path, _p: path == ".circleci/config.yml",
        ".circleci/config.yml present",
    ),
    _PathRule(
        "infra:azure-pipelines",
        "ci",
        "Azure Pipelines",
        lambda _path, p: _basename(p) in {"azure-pipelines.yml", "azure-pipelines.yaml"},
        "azure-pipelines.yml present",
    ),
)

_DATASTORE_RULES: tuple[tuple[str, str, frozenset[str]], ...] = (
    (
        "infra:postgresql",
        "PostgreSQL",
        frozenset(
            {
                "psycopg",
                "psycopg2",
                "psycopg2-binary",
                "psycopg-binary",
                "asyncpg",
                "pg",
                "postgres",
                "pg-promise",
                "postgresql",
            }
        ),
    ),
    (
        "infra:mysql",
        "MySQL",
        frozenset(
            {
                "mysqlclient",
                "pymysql",
                "mysql2",
                "mysql",
                "mysql-connector-python",
                "mysql-connector-j",
                "mysql-connector-java",
            }
        ),
    ),
    ("infra:mongodb", "MongoDB", frozenset({"pymongo", "motor", "mongoose", "mongodb"})),
    ("infra:redis", "Redis", frozenset({"redis", "ioredis", "aioredis"})),
)

_RUNS_EVIDENCE_PREFIX: dict[str, str] = {
    "infra:docker": "Dockerfile",
    "infra:procfile": "Procfile",
}


@dataclass
class _InfraAccumulator:
    category: InfraCategory
    label: str
    evidence: list[str] = field(default_factory=list)
    paths: set[str] = field(default_factory=set)


def _normalise_package(ecosystem: str, name: str) -> str:
    normalised = name.lower().replace("_", "-")
    if ecosystem == "Maven":
        normalised = normalised.split(":")[-1]
    return normalised


def detect_infra(
    live_paths: list[str],
    declared: list[tuple[str, str, str]],
    entry_points: list[tuple[str, str]],
    group_of_path: dict[str, str],
) -> list[DiagramInfraOut]:
    """``declared`` is ``(ecosystem, package_name, manifest_path)`` for every
    DIRECT declared dependency; ``entry_points`` is ``(path, evidence)`` for
    this run's entry points. Returns infra nodes sorted by id."""
    found: dict[str, _InfraAccumulator] = {}

    for path in sorted(live_paths):
        posix = PurePosixPath(path)
        for rule in _PATH_RULES:
            if not rule.matches(path, posix):
                continue
            acc = found.setdefault(rule.infra_id, _InfraAccumulator(rule.category, rule.label))
            acc.paths.add(path)
            if rule.evidence not in acc.evidence:
                acc.evidence.append(rule.evidence)

    workflows = found.get("infra:github-actions")
    if workflows is not None:
        workflows.evidence = [f"{len(workflows.paths)} workflow file(s) in .github/workflows"]

    for ecosystem, package_name, manifest_path in sorted(declared):
        normalised = _normalise_package(ecosystem, package_name)
        for infra_id, label, names in _DATASTORE_RULES:
            if normalised not in names:
                continue
            acc = found.setdefault(infra_id, _InfraAccumulator("datastore", label))
            acc.paths.add(manifest_path)
            line = f"declared dependency {package_name} in {manifest_path}"
            if line not in acc.evidence:
                acc.evidence.append(line)

    result: list[DiagramInfraOut] = []
    for infra_id in sorted(found):
        acc = found[infra_id]
        runs: set[str] = set()
        prefix = _RUNS_EVIDENCE_PREFIX.get(infra_id)
        if prefix is not None:
            for path, evidence in entry_points:
                group = group_of_path.get(path)
                if group is not None and evidence.startswith(prefix):
                    runs.add(group)
        result.append(
            DiagramInfraOut(
                id=infra_id,
                category=acc.category,
                label=acc.label,
                evidence=sorted(acc.evidence)[:MAX_INFRA_EVIDENCE],
                paths=sorted(acc.paths)[:MAX_INFRA_PATHS],
                runs_group_ids=sorted(runs),
            )
        )
    return result


def detect_actor(
    entry_points: list[tuple[str, str]],
    group_of_path: dict[str, str],
) -> DiagramActorOut | None:
    """``entry_points`` is ``(path, kind)``. The actor points at every group
    holding a strong-kind entry point, or (only when there are none) a
    graph-inferred one. ``None`` when the run has neither."""

    def _collect(kinds: tuple[str, ...]) -> list[tuple[str, str]]:
        return [
            (group_of_path[path], kind)
            for path, kind in entry_points
            if kind in kinds and path in group_of_path
        ]

    hits = _collect(ACTOR_ENTRY_KINDS) or _collect((ACTOR_FALLBACK_KIND,))
    if not hits:
        return None
    return DiagramActorOut(
        id="actor",
        label="Users & callers",
        group_ids=sorted({g for g, _ in hits}),
        entry_kinds=sorted({k for _, k in hits}),
    )
