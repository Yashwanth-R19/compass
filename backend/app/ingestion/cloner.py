import shutil
import sys
import tempfile

import git

from app.config import settings
from app.jobs.log_redaction import redact

CLONE_TIMEOUT_SECONDS = 120
"""Session 16, Part C: a clone that hasn't finished after this long is
hard-killed rather than left to run indefinitely -- an abuse vector (a
repository engineered to be slow to clone, or a network partition mid-clone)
that plan/RULES.md sec 14's size cap alone doesn't cover, since size is
checked BEFORE cloning via the GitHub API and can't catch a slow transfer.
Implemented via GitPython's own ``kill_after_timeout`` (``git.cmd.execute``'s
recognized kwarg, passed straight through ``clone_from``'s ``**kwargs`` --
not a separate ``threading``/``subprocess`` wrapper), which sends the
underlying git subprocess SIGKILL after this many seconds and raises the
same ``GitCommandError`` an ordinary clone failure would, so it's caught and
redacted by the existing ``except`` block below with no special-casing."""


def get_available_disk_bytes(path: str) -> int:
    """Session 16, Part C: the free-space check ``clone_repo`` runs before
    ever invoking ``git clone`` -- a full disk fails a clone deep inside
    GitPython with an unhelpful, potentially credential-leaking OSError
    (session 10's redaction net doesn't cover every possible libc error
    string), whereas checking first fails cleanly with an honest message
    naming the actual problem."""
    return shutil.disk_usage(path).free


def get_remote_head_sha(url: str) -> str:
    """Resolve the remote default branch's HEAD commit sha WITHOUT a full
    clone -- a single `git ls-remote <url> HEAD` network call.

    Used by the job runner to decide whether Facts (repo_paths/commits/
    files/dependencies) can be reused as-is: if this matches the repo's
    already-persisted ``repos.head_sha``, cloning and mining are skipped
    entirely (Phase 02 progressive reveal / near-instant re-analysis).

    ``url`` may be a credentialed URL for a private repo (session 02, Part
    D, ``app/ingestion/clone_url.py::resolve_clone_url``) -- on failure,
    ``git.exc.GitCommandError``'s own string form embeds the full command
    line, INCLUDING that URL, so it's redacted before propagating, same as
    ``clone_repo`` below.
    """
    try:
        output = git.Git().ls_remote(url, "HEAD")
    except git.exc.GitCommandError as exc:
        raise RuntimeError(redact(f"git ls-remote failed: {exc}")) from None
    return output.split()[0]


def clone_repo(url: str) -> str:
    """Clone the default branch's full commit history into a fresh temp dir.

    ``url`` is a fully-resolved clone URL from
    ``app/ingestion/clone_url.py::resolve_clone_url`` -- the plain https URL
    for a public repo, or an ``https://x-access-token:<token>@...`` URL for
    a private one. This function never decides which; it just clones
    whatever it's given.

    ``git clone --single-branch --no-tags``: single-branch (not all refs,
    and skip tag refs we never use) but no --depth limit -- coupling (A3)
    needs the complete history of the branch being analyzed.

    Deliberately NOT `--filter=blob:none`. A blobless partial clone would
    shrink the clone itself, but `git log --numstat` (app/ingestion/miner.py)
    needs every historical blob to compute per-commit line counts -- with a
    blobless clone, that forces git to lazily fetch each one on demand during
    the log walk, which is dramatically slower than fetching them all up
    front in one clone. Blobless-plus-fast would only work with `--name-only`
    (file names, no line counts), and churn is an input to the locked risk
    formula, so that's not on the table. Do not "optimize" this away.

    **Never leaks a credentialed URL.** GitPython's ``GitCommandError`` (a
    failed clone -- bad credentials, network error, repo doesn't exist)
    stringifies to the full command line it ran, which for a private repo
    includes the embedded ``x-access-token:<token>@`` URL -- and a failed
    clone's stderr from git itself can also echo the remote URL back. Both
    are redacted (``app/jobs/log_redaction.py``, including the
    ``x-access-token:...@`` pattern added for this) before the error message
    ever propagates into a log line or ``analysis_stages``/``analysis_runs.error``
    (plan/RULES.md sec 10's "known hazard": a raw exception here would put a
    live GitHub token in the database and in this repo's public Actions
    logs). The partial clone directory is also removed on failure -- it
    would otherwise leak, since the caller only learns the tmp dir's path
    from this function's return value, which a raised exception never gives it.

    Caller owns cleanup on SUCCESS — always delete the returned path once
    mining is done; the clone is disposable and source code must never
    persist past ingestion.

    Session 16, Part C hardens this with two independent checks, both
    deliberately BEFORE the clone starts: a disk-space guard (a full runner
    disk fails a clone deep inside GitPython with an unhelpful error) and a
    hard ``CLONE_TIMEOUT_SECONDS`` kill (a repository engineered to be slow,
    or a network partition mid-transfer, must not hang the run forever --
    the same "reject/fail cleanly rather than run slowly" discipline
    plan/RULES.md sec 14 already applies to the size cap).
    """
    tmp_root = tempfile.gettempdir()
    min_free_bytes = max(1024**3, settings.COMPASS_MAX_REPO_MB * 3 * 1024**2)
    available = get_available_disk_bytes(tmp_root)
    if available < min_free_bytes:
        raise RuntimeError(
            f"Not enough disk space to clone safely "
            f"({available / 1024**2:.0f} MB free, need at least {min_free_bytes / 1024**2:.0f} MB)."
        )

    clone_kwargs: dict[str, object] = {"multi_options": ["--single-branch", "--no-tags"]}
    if sys.platform != "win32":
        # GitPython's kill_after_timeout raises outright on Windows ("feature
        # is not supported") rather than silently no-op'ing -- confirmed
        # directly (every test that clones a repo failed identically until
        # this guard was added). Every real deployment target for this
        # project is Linux (Render, GitHub Actions ubuntu-latest -- DEPLOY.md)
        # so the timeout is enforced there unconditionally; Windows (local
        # dev only, never a deployment target) clones without a hard timeout
        # rather than crashing every clone outright. A genuinely self-hosted
        # Windows deployment would not get this protection -- an honest,
        # documented gap (README limitations), not a silent one.
        clone_kwargs["kill_after_timeout"] = CLONE_TIMEOUT_SECONDS

    tmp_dir = tempfile.mkdtemp(prefix="compass-clone-")
    try:
        git.Repo.clone_from(url, tmp_dir, **clone_kwargs)
    except git.exc.GitCommandError as exc:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise RuntimeError(redact(f"git clone failed: {exc}")) from None
    return tmp_dir
