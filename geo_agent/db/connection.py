"""SQLite connection manager with schema migration support."""

import logging
import sqlite3
from pathlib import Path
from typing import Optional

from geo_agent.db.schema import apply_migrations

logger = logging.getLogger(__name__)

_PRAGMAS = [
    "PRAGMA journal_mode = WAL",
    "PRAGMA foreign_keys = ON",
    "PRAGMA busy_timeout = 5000",
]


class Database:
    """Thin wrapper around sqlite3 connection with migration support.

    Usage:
        db = Database("geo_agent.db")
        db.open()
        ...
        db.close()

    Context manager:
        with Database("geo_agent.db") as db:
            ...
    """

    def __init__(self, db_path: str | Path):
        self._path = Path(db_path)
        self._conn: Optional[sqlite3.Connection] = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("Database not opened. Call .open() first.")
        return self._conn

    @property
    def path(self) -> Path:
        return self._path

    def open(self) -> "Database":
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path))
        self._conn.row_factory = sqlite3.Row
        for pragma in _PRAGMAS:
            self._conn.execute(pragma)
        apply_migrations(self._conn)
        logger.info("Database opened: %s", self._path)
        return self

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "Database":
        return self.open()

    def __exit__(self, *exc) -> None:
        self.close()
