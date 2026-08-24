import shutil
import tempfile

import git

from app.jobs.log_redaction import redact


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
    """
    tmp_dir = tempfile.mkdtemp(prefix="compass-clone-")
    try:
        git.Repo.clone_from(url, tmp_dir, multi_options=["--single-branch", "--no-tags"])
    except git.exc.GitCommandError as exc:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise RuntimeError(redact(f"git clone failed: {exc}")) from None
    return tmp_dir
