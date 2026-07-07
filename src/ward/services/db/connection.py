"""Shared SQLite connection policy for Ward services."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


@contextmanager
def database_connection(path: Path, *, rows: bool = False) -> Iterator[sqlite3.Connection]:
    """Open a configured connection and always close it."""
    conn = sqlite3.connect(str(path), timeout=10.0)
    try:
        conn.execute("PRAGMA busy_timeout = 10000")
        conn.execute("PRAGMA journal_mode = WAL")
        if rows:
            conn.row_factory = sqlite3.Row
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
