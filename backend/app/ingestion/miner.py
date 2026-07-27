import os
import re
import subprocess
from collections.abc import Iterator
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import lizard

IGNORE_DIRS = {
    "node_modules",
    ".git",
    "dist",
    "build",
    "venv",
    ".venv",
    "__pycache__",
    "migrations",
    "vendor",
    "target",
    ".next",
    ".gradle",
    "coverage",
    ".mypy_cache",
    ".pytest_cache",
}
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

RECORD_SEP = "\x1e"
UNIT_SEP = "\x1f"

# git log flags, in order, and why each one is load-bearing:
#   --no-merges    merge commits duplicate changesets and would inflate
#                  co-change counts; matches code-maat's behaviour.
#   --no-renames   master-context.md documents that a rename is treated as
#                  delete-old-path + add-new-path. Leaving rename detection
#                  off keeps --numstat output as plain paths instead of
#                  `src/{a => b}.py` rewrite syntax.
#   --numstat      per-file added/deleted line counts for every commit --
#                  the input to churn (and to the locked risk formula).
#   --date=iso-strict / %aI / %cI  unambiguous, parseable timestamps.
#   %x1e (record separator) / %x1f (unit separator): commit subjects and
#   bodies contain almost any printable character -- including newlines and
#   pipes -- so a newline- or pipe-delimited format corrupts on real repos.
#   These two control characters effectively never appear in commit
#   metadata, so they're safe to split on unconditionally.
GIT_LOG_FORMAT = f"{RECORD_SEP}%H{UNIT_SEP}%an{UNIT_SEP}%ae{UNIT_SEP}%aI{UNIT_SEP}%cI{UNIT_SEP}%s{UNIT_SEP}%b{UNIT_SEP}"

GIT_LOG_CMD = [
    "git",
    "log",
    "--no-merges",
    "--no-renames",
    "--numstat",
    "--date=iso-strict",
    f"--format={GIT_LOG_FORMAT}",
]

READ_CHUNK_SIZE = 1 << 16  # 64 KiB


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
    # Parallel to file_paths: file_added_lines[i]/file_deleted_lines[i] are
    # the added/deleted line counts for file_paths[i] in this commit. Feeds
    # commits.added_lines/deleted_lines (persist.py), which are parallel to
    # commits.changed_path_ids the same way.
    file_added_lines: list[int] = field(default_factory=list)
    file_deleted_lines: list[int] = field(default_factory=list)


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


def _is_ignored_path(path: str) -> bool:
    """True if any segment of ``path`` (not just the first) names a
    directory in IGNORE_DIRS -- matches os.walk's ``dirnames[:] = [...]``
    pruning behaviour used for the final tree, now applied to historical
    --numstat paths too."""
    return any(segment in IGNORE_DIRS for segment in path.split("/"))


def _normalize_path(path: str) -> str:
    # git itself always emits forward-slash paths in --numstat output, even
    # on Windows, but normalize defensively anyway -- this is what lets a
    # coupling pair match its import edge in app/languages/scanner.py, which
    # always produces posix paths.
    return path.replace("\\", "/")


def _iter_commit_records(stdout) -> Iterator[str]:
    """Split the raw git-log stream on RECORD_SEP, one commit record per
    yield. Reads fixed-size chunks (never the whole stream at once) and
    handles a record split across two reads by holding the trailing,
    possibly-incomplete piece back in ``buffer`` until either the next
    RECORD_SEP arrives or EOF is reached.
    """
    buffer = ""
    while True:
        chunk = stdout.read(READ_CHUNK_SIZE)
        if not chunk:
            break
        buffer += chunk
        parts = buffer.split(RECORD_SEP)
        buffer = parts.pop()
        for part in parts:
            if part:  # the empty string before the very first RECORD_SEP
                yield part
    if buffer:
        yield buffer


def _parse_numstat_block(rest: str) -> list[tuple[str, int, int]]:
    """Parses the --numstat lines following a commit's metadata fields.
    Binary files report ``-`` for both counts -- treated as 0/0 added/
    deleted but still counted as touched. Paths under an IGNORE_DIRS
    segment are dropped entirely (not counted toward churn/commit_count).
    """
    touches: list[tuple[str, int, int]] = []
    for line in rest.split("\n"):
        if not line.strip():
            continue
        added_s, deleted_s, path = line.split("\t", 2)
        path = _normalize_path(path)
        if _is_ignored_path(path):
            continue
        added = 0 if added_s == "-" else int(added_s)
        deleted = 0 if deleted_s == "-" else int(deleted_s)
        touches.append((path, added, deleted))
    return touches


def _parse_commit_record(record: str) -> MinedCommit:
    sha, author_name, author_email, author_date, committer_date, subject, body, rest = record.split(
        UNIT_SEP, 7
    )
    touches = _parse_numstat_block(rest)

    message = subject if not body else f"{subject}\n\n{body}"
    committed_at = datetime.fromisoformat(committer_date)

    file_paths = [t[0] for t in touches]
    added_lines = [t[1] for t in touches]
    deleted_lines = [t[2] for t in touches]

    return MinedCommit(
        sha=sha,
        author_name=author_name,
        author_email=author_email,
        committed_at=committed_at,
        message=message,
        is_fix=bool(FIX_RE.search(message)),
        is_revert=bool(REVERT_RE.match(message)),
        files_changed=len(file_paths),
        insertions=sum(added_lines),
        deletions=sum(deleted_lines),
        file_paths=file_paths,
        file_added_lines=added_lines,
        file_deleted_lines=deleted_lines,
    )


def _run_git_log(repo_path: str) -> subprocess.Popen:
    # Never subprocess.run(capture_output=True): a 25k-commit repo's numstat
    # output can be hundreds of MB, and capture_output buffers all of it in
    # memory before we get to parse a single line. Popen + streaming stdout
    # keeps peak memory bounded to one read chunk at a time.
    return subprocess.Popen(
        GIT_LOG_CMD,
        cwd=repo_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def mine_repo(repo_path: str) -> MinedRepo:
    """Pure(ish): reads the local clone at ``repo_path``, returns mined facts.
    Never touches the DB -- persist.py is the only thing that writes them.
    """
    commits: list[MinedCommit] = []
    file_agg: dict[str, dict] = {}

    proc = _run_git_log(repo_path)
    try:
        assert proc.stdout is not None
        for record in _iter_commit_records(proc.stdout):
            commit = _parse_commit_record(record)
            commits.append(commit)

            for path, added, deleted in zip(
                commit.file_paths, commit.file_added_lines, commit.file_deleted_lines, strict=True
            ):
                agg = file_agg.setdefault(
                    path,
                    {
                        "churn_total": 0,
                        "commit_count": 0,
                        "first_seen": commit.committed_at,
                        "last_seen": commit.committed_at,
                    },
                )
                agg["churn_total"] += added + deleted
                agg["commit_count"] += 1
                agg["first_seen"] = min(agg["first_seen"], commit.committed_at)
                agg["last_seen"] = max(agg["last_seen"], commit.committed_at)
    finally:
        if proc.stdout is not None:
            proc.stdout.close()
        returncode = proc.wait()
        if returncode != 0:
            stderr = proc.stderr.read() if proc.stderr else ""
            raise RuntimeError(f"git log failed with exit code {returncode}: {stderr}")
        if proc.stderr is not None:
            proc.stderr.close()

    existing_paths = _final_tree_paths(repo_path)
    analyzed = _analyze_files(repo_path, [p for p in file_agg if p in existing_paths])

    files: list[MinedFile] = []
    for path, agg in file_agg.items():
        is_deleted = path not in existing_paths
        loc, complexity = (0, 0.0) if is_deleted else analyzed.get(path, (0, 0.0))
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


def _analyze_file_worker(full_path: str) -> tuple[int, float]:
    try:
        if os.path.getsize(full_path) > MAX_FILE_BYTES:
            return 0, 0.0
    except OSError:
        return 0, 0.0

    try:
        analysis = lizard.analyze_file(full_path)
    except Exception:
        return 0, 0.0

    loc = analysis.nloc
    # File-level complexity = max cyclomatic complexity across its functions
    # (not the average) -- a single hot function should not be diluted by
    # many trivial ones sitting in the same file.
    complexity = max((fn.cyclomatic_complexity for fn in analysis.function_list), default=0)
    return loc, float(complexity)


def _analyze_files(repo_path: str, paths: list[str]) -> dict[str, tuple[int, float]]:
    """lizard is CPU-bound and pure, so it parallelizes safely across a
    process pool. Chunked via ``executor.map(..., chunksize=...)`` so we pay
    IPC per chunk, not per file. Below a small-repo threshold, spawning the
    pool at all (a real cost on Windows, which uses spawn not fork) would
    cost more than it saves, so those run inline.
    """
    if not paths:
        return {}

    full_paths = [str(Path(repo_path) / p) for p in paths]
    max_workers = min(4, os.cpu_count() or 1)

    if max_workers <= 1 or len(full_paths) < 2 * max_workers:
        return dict(zip(paths, (_analyze_file_worker(fp) for fp in full_paths), strict=True))

    chunksize = max(1, len(full_paths) // (max_workers * 4))
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        results = executor.map(_analyze_file_worker, full_paths, chunksize=chunksize)
        return dict(zip(paths, results, strict=True))
