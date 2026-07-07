from pathlib import Path

import pytest

from ward.services.db.connection import database_connection
from ward.services.db.migrations import apply_migrations
from ward.services.db.conversation_service import ConversationService


def test_database_connection_enables_concurrency_pragmas_without_foreign_keys(tmp_path: Path):
    path = tmp_path / "ward.db"
    with database_connection(path) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 0
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 10000


def test_database_connection_rolls_back_on_error(tmp_path: Path):
    path = tmp_path / "ward.db"
    with database_connection(path) as conn:
        conn.execute("CREATE TABLE values_table (value INTEGER)")

    try:
        with database_connection(path) as conn:
            conn.execute("INSERT INTO values_table VALUES (1)")
            raise RuntimeError("rollback")
    except RuntimeError:
        pass

    with database_connection(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM values_table").fetchone()[0] == 0


def test_migrations_are_ordered_and_idempotent(tmp_path: Path):
    path = tmp_path / "ward.db"
    calls = []
    migrations = [
        (1, lambda conn: (calls.append(1), conn.execute("CREATE TABLE sample (value INTEGER)"))),
        (2, lambda conn: (calls.append(2), conn.execute("ALTER TABLE sample ADD COLUMN note TEXT"))),
    ]
    with database_connection(path) as conn:
        apply_migrations(conn, "sample", migrations)
        apply_migrations(conn, "sample", migrations)
        versions = conn.execute(
            "SELECT version FROM schema_migrations WHERE component = 'sample' ORDER BY version"
        ).fetchall()

    assert calls == [1, 2]
    assert versions == [(1,), (2,)]


def test_conversation_schema_has_no_database_foreign_keys(tmp_path: Path):
    path = tmp_path / "ward.db"
    with database_connection(path) as conn:
        ConversationService._create_schema(conn)
        assert conn.execute("PRAGMA foreign_key_list(messages)").fetchall() == []
        assert conn.execute("PRAGMA foreign_key_list(conversation_summaries)").fetchall() == []


def test_conversation_relationship_is_enforced_by_service(tmp_path: Path):
    service = object.__new__(ConversationService)
    service.db_path = tmp_path / "ward.db"
    service._init_db()

    with pytest.raises(ValueError, match="does not exist"):
        service.add_message(999, "user", "orphan")

    conversation_id = service.create_conversation()
    assert service.conversation_exists(conversation_id)
    assert not service.conversation_exists(999)
    message_id = service.add_message(conversation_id, "user", "valid")
    assert message_id > 0
