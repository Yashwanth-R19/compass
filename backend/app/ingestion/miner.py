import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import lizard
from pydriller import Repository

IGNORE_DIRS = {"node_modules", ".git", "dist", "build", "venv", ".venv", "__pycache__", "migrations"}
MAX_FILE_BYTES = 1_000_000

LANGUAGE_BY_EXT = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".java": "java",
}

FIX_RE = re.compile(r"\b(fix|bug|patch|resolve|close[sd]?)\b", re.IGNORECASE)
REVERT_RE = re.compile(r"^\s*revert\b", re.IGNORECASE)


@dataclass
class MinedCommit:
    sha: str
    author_name: str
    author_email: str
    committed_at: datetime
    message: str
    is_fix: bool
    is_revert: bool
    files_changed: int
    insertions: int
    deletions: int
    file_paths: list[str] = field(default_factory=list)


@dataclass
class MinedFile:
    path: str
    language: str
    current_loc: int
    complexity: float
    churn_total: int
    commit_count: int
    first_seen: datetime
    last_seen: datetime
    is_deleted: bool


@dataclass
class MinedRepo:
    commits: list[MinedCommit]
    files: list[MinedFile]


def infer_language(path: str) -> str:
    return LANGUAGE_BY_EXT.get(Path(path).suffix.lower(), "other")


def mine_repo(repo_path: str) -> MinedRepo:
    """Pure(ish): reads the local clone at ``repo_path``, returns mined facts.
    Never touches the DB — persist.py is the only thing that writes them.
    """
    commits: list[MinedCommit] = []
    file_agg: dict[str, dict] = {}

    for commit in Repository(repo_path).traverse_commits():
        file_paths: list[str] = []
        insertions = 0
        deletions = 0

        for mf in commit.modified_files:
            path = mf.new_path or mf.old_path
            if path is None:
                continue

            added = mf.added_lines or 0
            deleted = mf.deleted_lines or 0
            insertions += added
            deletions += deleted
            file_paths.append(path)

            agg = file_agg.setdefault(
                path,
                {
                    "churn_total": 0,
                    "commit_count": 0,
                    "first_seen": commit.committer_date,
                    "last_seen": commit.committer_date,
                },
            )
            agg["churn_total"] += added + deleted
            agg["commit_count"] += 1
            agg["first_seen"] = min(agg["first_seen"], commit.committer_date)
            agg["last_seen"] = max(agg["last_seen"], commit.committer_date)

        message = commit.msg or ""
        commits.append(
            MinedCommit(
                sha=commit.hash,
                author_name=commit.author.name or "",
                author_email=commit.author.email or "",
                committed_at=commit.committer_date,
                message=message,
                is_fix=bool(FIX_RE.search(message)),
                is_revert=bool(REVERT_RE.match(message)),
                files_changed=len(file_paths),
                insertions=insertions,
                deletions=deletions,
                file_paths=file_paths,
            )
        )

    existing_paths = _final_tree_paths(repo_path)

    files: list[MinedFile] = []
    for path, agg in file_agg.items():
        is_deleted = path not in existing_paths
        loc, complexity = (0, 0.0) if is_deleted else _analyze_file(Path(repo_path) / path)
        files.append(
            MinedFile(
                path=path,
                language=infer_language(path),
                current_loc=loc,
                complexity=complexity,
                churn_total=agg["churn_total"],
                commit_count=agg["commit_count"],
                first_seen=agg["first_seen"],
                last_seen=agg["last_seen"],
                is_deleted=is_deleted,
            )
        )

    return MinedRepo(commits=commits, files=files)


def _final_tree_paths(repo_path: str) -> set[str]:
    root = Path(repo_path)
    paths: set[str] = set()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS]
        for fname in filenames:
            rel = (Path(dirpath) / fname).relative_to(root).as_posix()
            paths.add(rel)
    return paths


def _analyze_file(full_path: Path) -> tuple[int, float]:
    try:
        if full_path.stat().st_size > MAX_FILE_BYTES:
            return 0, 0.0
    except OSError:
        return 0, 0.0

    try:
        analysis = lizard.analyze_file(str(full_path))
    except Exception:
        return 0, 0.0

    loc = analysis.nloc
    # File-level complexity = max cyclomatic complexity across its functions
    # (not the average) — a single hot function should not be diluted by
    # many trivial ones sitting in the same file.
    complexity = max((fn.cyclomatic_complexity for fn in analysis.function_list), default=0)
    return loc, float(complexity)
