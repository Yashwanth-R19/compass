import tempfile

import git


def clone_repo(url: str) -> str:
    """Clone the default branch's full commit history into a fresh temp dir.

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

    Caller owns cleanup — always delete the returned path once mining is
    done; the clone is disposable and source code must never persist past
    ingestion.
    """
    tmp_dir = tempfile.mkdtemp(prefix="compass-clone-")
    git.Repo.clone_from(url, tmp_dir, multi_options=["--single-branch", "--no-tags"])
    return tmp_dir
