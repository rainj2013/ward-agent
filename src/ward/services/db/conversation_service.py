"""SQLite conversation history for chat."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from ward.core.config import get_config


class ConversationService:
    """Store and retrieve chat history via SQLite."""

    def __init__(self):
        cfg = get_config()
        self.db_path = cfg.database.sqlite_path.expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (conversation_id) REFERENCES conversations(id)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS conversation_summaries (
                    conversation_id INTEGER PRIMARY KEY,
                    summary TEXT NOT NULL,
                    summarized_until_message_id INTEGER,
                    input_tokens INTEGER DEFAULT 0,
                    output_tokens INTEGER DEFAULT 0,
                    total_tokens INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (conversation_id) REFERENCES conversations(id)
                )
            """)
            conn.commit()

    def create_conversation(self) -> int:
        now = datetime.utcnow().isoformat()
        with sqlite3.connect(str(self.db_path)) as conn:
            cur = conn.execute(
                "INSERT INTO conversations (created_at, updated_at) VALUES (?, ?)",
                (now, now),
            )
            conn.commit()
            return cur.lastrowid

    def add_message(self, conversation_id: int, role: str, content: str) -> int:
        now = datetime.utcnow().isoformat()
        with sqlite3.connect(str(self.db_path)) as conn:
            cur = conn.execute(
                "INSERT INTO messages (conversation_id, role, content, created_at) VALUES (?, ?, ?, ?)",
                (conversation_id, role, content, now),
            )
            conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (now, conversation_id),
            )
            conn.commit()
            return cur.lastrowid

    def update_message(self, conversation_id: int, message_id: int, role: str, content: str) -> bool:
        now = datetime.utcnow().isoformat()
        with sqlite3.connect(str(self.db_path)) as conn:
            cur = conn.execute(
                """
                UPDATE messages
                SET content = ?
                WHERE id = ? AND conversation_id = ? AND role = ?
                """,
                (content, message_id, conversation_id, role),
            )
            if cur.rowcount:
                conn.execute(
                    "UPDATE conversations SET updated_at = ? WHERE id = ?",
                    (now, conversation_id),
                )
            conn.commit()
            return cur.rowcount > 0

    def get_messages(self, conversation_id: int, limit: int | None = None) -> list[dict[str, Any]]:
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            if limit is None:
                rows = conn.execute(
                    "SELECT id, role, content, created_at FROM messages WHERE conversation_id = ? ORDER BY created_at ASC",
                    (conversation_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, role, content, created_at FROM messages WHERE conversation_id = ? ORDER BY created_at DESC, id DESC LIMIT ?",
                    (conversation_id, limit),
                ).fetchall()
                rows = list(reversed(rows))
            return [dict(row) for row in rows]

    def get_summary(self, conversation_id: int) -> dict[str, Any] | None:
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT conversation_id, summary, summarized_until_message_id,
                       input_tokens, output_tokens, total_tokens, created_at, updated_at
                FROM conversation_summaries
                WHERE conversation_id = ?
                """,
                (conversation_id,),
            ).fetchone()
            return dict(row) if row else None

    def upsert_summary(
        self,
        conversation_id: int,
        summary: str,
        summarized_until_message_id: int | None,
        usage: dict[str, int] | None = None,
    ) -> None:
        now = datetime.utcnow().isoformat()
        usage = usage or {}
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                """
                INSERT INTO conversation_summaries (
                    conversation_id, summary, summarized_until_message_id,
                    input_tokens, output_tokens, total_tokens, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(conversation_id) DO UPDATE SET
                    summary = excluded.summary,
                    summarized_until_message_id = excluded.summarized_until_message_id,
                    input_tokens = excluded.input_tokens,
                    output_tokens = excluded.output_tokens,
                    total_tokens = excluded.total_tokens,
                    updated_at = excluded.updated_at
                """,
                (
                    conversation_id,
                    summary,
                    summarized_until_message_id,
                    int(usage.get("input_tokens", 0)),
                    int(usage.get("output_tokens", 0)),
                    int(usage.get("total_tokens", 0)),
                    now,
                    now,
                ),
            )
            conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (now, conversation_id),
            )
            conn.commit()

    def get_messages_paginated(self, conversation_id: int, limit: int = 20, before_id: int | None = None) -> tuple[list[dict[str, Any]], bool, int | None]:
        """Fetch messages older than before_id (cursor pagination). Returns (messages, has_more, next_before_id) in ASC order (oldest first)."""
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            if before_id is None:
                # Initial load: get newest messages first (DESC)
                rows = conn.execute(
                    "SELECT id, role, content, created_at FROM messages WHERE conversation_id = ? ORDER BY created_at DESC, id DESC LIMIT ?",
                    (conversation_id, limit + 1),
                ).fetchall()
            else:
                # Load the next page immediately older than before_id, then
                # reverse to ASC so the UI can prepend chronological chunks.
                rows = conn.execute(
                    "SELECT id, role, content, created_at FROM messages WHERE conversation_id = ? AND id < ? ORDER BY created_at DESC, id DESC LIMIT ?",
                    (conversation_id, before_id, limit + 1),
                ).fetchall()
            has_more = len(rows) > limit
            if has_more:
                rows = rows[:limit]
            if before_id is not None:
                rows = list(reversed(rows))
            next_before_id = (rows[0]["id"] if before_id is not None else rows[-1]["id"]) if rows and has_more else None
            return [dict(row) for row in rows], has_more, next_before_id

    def list_conversations(self, limit: int = 20) -> list[dict[str, Any]]:
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT id, created_at, updated_at FROM conversations ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]
