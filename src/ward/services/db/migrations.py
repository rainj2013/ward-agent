"""Small component-scoped SQLite migration runner."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable


Migration = tuple[int, Callable[[sqlite3.Connection], None]]


def apply_migrations(conn: sqlite3.Connection, component: str, migrations: list[Migration]) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            component TEXT NOT NULL,
            version INTEGER NOT NULL,
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (component, version)
        )
        """
    )
    row = conn.execute(
        "SELECT COALESCE(MAX(version), 0) FROM schema_migrations WHERE component = ?",
        (component,),
    ).fetchone()
    current = int(row[0] or 0)
    for version, migration in sorted(migrations, key=lambda item: item[0]):
        if version <= current:
            continue
        migration(conn)
        conn.execute(
            "INSERT INTO schema_migrations (component, version) VALUES (?, ?)",
            (component, version),
        )
        current = version
