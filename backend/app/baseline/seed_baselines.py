"""Loads ``app/baseline/corpus_breakpoints.json`` (built by
``build_corpus.py``) into the ``baselines`` table -- run as::

    python -m app.baseline.seed_baselines

The JSON file is the single source of truth (session 14, Part C.3); this
script's whole job is to make the ``baselines`` table a materialized copy of
it, never edited by hand. Upserts by ``(metric, language, size_bucket)`` --
safe to re-run after a fresh ``build_corpus.py`` run without first
truncating the table by hand.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

from sqlalchemy import select

from app.db.base import SessionLocal
from app.db.models import Baseline

logger = logging.getLogger(__name__)

DEFAULT_INPUT_PATH = Path(__file__).parent / "corpus_breakpoints.json"


def seed_baselines(input_path: Path = DEFAULT_INPUT_PATH) -> int:
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    cells = payload["cells"]

    session = SessionLocal()
    written = 0
    try:
        for cell in cells:
            row = session.scalar(
                select(Baseline).where(
                    Baseline.metric == cell["metric"],
                    Baseline.language == cell["language"],
                    Baseline.size_bucket == cell["size_bucket"],
                )
            )
            if row is None:
                row = Baseline(
                    metric=cell["metric"],
                    language=cell["language"],
                    size_bucket=cell["size_bucket"],
                )
                session.add(row)
            row.p10 = cell["p10"]
            row.p25 = cell["p25"]
            row.p50 = cell["p50"]
            row.p75 = cell["p75"]
            row.p90 = cell["p90"]
            row.n_repos = cell["n_repos"]
            row.n_files = cell["n_files"]
            written += 1
        session.commit()
    finally:
        session.close()

    logger.info("seeded %d baseline cells from %s", written, input_path)
    return written


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    seed_baselines()
    return 0


if __name__ == "__main__":
    sys.exit(main())
