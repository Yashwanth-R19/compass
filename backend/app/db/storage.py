"""Postgres storage introspection (session 16, Part B/D) -- shared by
``app/jobs/eviction.py``'s high/low-water trigger and
``GET /internal/storage``. Pure read-only queries against Postgres's own
catalog (``pg_total_relation_size``/``pg_database_size``); never mutates
anything, same discipline ``app/baseline/build_corpus.py``'s own
``_database_size_bytes`` already established for the corpus-build budget
check -- this module is the general-purpose version of that one query, not a
replacement for it (build_corpus.py's own inline helper is left as-is, out of
this session's scope).
"""

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

NEON_FREE_TIER_LIMIT_BYTES = int(0.5 * 1024**3)
"""Neon's free-tier storage cap (CLAUDE.md/plan/SESSION_16, matching the
0.5 GB figure ``app/baseline/build_corpus.py``'s own tighter 0.4 GB build-time
budget is deliberately measured against)."""

EVICTION_HIGH_WATER = 0.75
"""Fraction of ``NEON_FREE_TIER_LIMIT_BYTES`` at which the reaper triggers an
eviction pass (session 16, Part B)."""

EVICTION_LOW_WATER = 0.55
"""Fraction of ``NEON_FREE_TIER_LIMIT_BYTES`` eviction stops at once storage
drops back below it -- a hysteresis band (0.75 -> 0.55) so eviction doesn't
fire every single reaper tick right at the edge of the high-water mark."""


@dataclass
class TableSize:
    name: str
    total_bytes: int


@dataclass
class StorageReport:
    total_bytes: int
    limit_bytes: int
    tables: list[TableSize]

    @property
    def headroom_bytes(self) -> int:
        return self.limit_bytes - self.total_bytes

    @property
    def fraction_used(self) -> float:
        return self.total_bytes / self.limit_bytes if self.limit_bytes else 0.0


def get_database_size_bytes(session: Session) -> int:
    """Total on-disk size of the current database, in bytes -- the single
    number the eviction trigger and ``GET /internal/storage`` both compare
    against ``NEON_FREE_TIER_LIMIT_BYTES``."""
    return session.execute(text("SELECT pg_database_size(current_database())")).scalar_one()


def get_table_sizes(session: Session) -> list[TableSize]:
    """Per-table size (``pg_total_relation_size`` -- the table itself plus
    its indexes and TOAST data, which is what actually accounts for disk
    usage), largest first. Restricted to ordinary tables in the ``public``
    schema so this never lists a Postgres-internal relation."""
    rows = session.execute(
        text(
            """
            SELECT relname, pg_total_relation_size(c.oid) AS total_bytes
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relkind = 'r' AND n.nspname = 'public'
            ORDER BY total_bytes DESC
            """
        )
    ).all()
    return [TableSize(name=row.relname, total_bytes=row.total_bytes) for row in rows]


def get_storage_report(session: Session) -> StorageReport:
    return StorageReport(
        total_bytes=get_database_size_bytes(session),
        limit_bytes=NEON_FREE_TIER_LIMIT_BYTES,
        tables=get_table_sizes(session),
    )


def vacuum(engine: Engine, table_names: list[str] | None = None) -> None:
    """Runs plain ``VACUUM`` (never ``VACUUM FULL``, which takes an
    ACCESS EXCLUSIVE lock and can take the API down -- session 16 Known
    Hazard #3) so Postgres actually returns freed pages to be reused instead
    of just marking them dead.

    Takes the raw ``Engine``, not an ORM ``Session`` -- ``VACUUM`` cannot run
    inside a transaction block at all, and every ``Session`` in this codebase
    is opened with ``autocommit=False`` (app/db/base.py), so this opens its
    own connection with ``isolation_level="AUTOCOMMIT"`` rather than trying
    to coerce an existing transactional session into running it.

    Without this, storage does not visibly shrink after a large eviction
    (session 16 Known Hazard #2) -- Postgres holds the now-dead pages until
    something vacuums them, which looks exactly like eviction having failed
    even though the rows are genuinely gone.
    """
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        if table_names:
            for name in table_names:
                conn.execute(text(f'VACUUM "{name}"'))
        else:
            conn.execute(text("VACUUM"))


__all__ = [
    "EVICTION_HIGH_WATER",
    "EVICTION_LOW_WATER",
    "NEON_FREE_TIER_LIMIT_BYTES",
    "StorageReport",
    "TableSize",
    "get_database_size_bytes",
    "get_storage_report",
    "get_table_sizes",
    "vacuum",
]
