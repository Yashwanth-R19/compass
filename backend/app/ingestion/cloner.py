import tempfile

import git


def clone_repo(url: str) -> str:
    """Clone the default branch's full commit history into a fresh temp dir.

    Single-branch (not all refs) but no --depth limit: coupling (A3) needs
    the complete history of the branch being analyzed. Caller owns cleanup —
    always delete the returned path once mining is done; the clone is
    disposable and source code must never persist past ingestion.
    """
    tmp_dir = tempfile.mkdtemp(prefix="compass-clone-")
    git.Repo.clone_from(url, tmp_dir, multi_options=["--single-branch"])
    return tmp_dir
