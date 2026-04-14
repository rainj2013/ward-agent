"""SQLite cache for AI analysis reports — index, stock, and market reports."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Any

from ward.core.config import get_config


class AnalysisCacheService:
    """Cache AI-generated analysis reports keyed by (type, id, trade_date)."""

    _TABLE = """
        CREATE TABLE IF NOT EXISTS analysis_cache (
            cache_key   TEXT PRIMARY KEY,   -- e.g. "index:ixic", "stock:AAPL", "market:report"
            report      TEXT NOT NULL,
            trade_date  TEXT NOT NULL,       -- "YYYY-MM-DD" of the trading session this data represents
            raw_data    TEXT,                -- JSON of the full context/response data
            created_at  TEXT NOT NULL
        )
    """

    # trade_date of "1900-01-01" means "no specific trade date" (never expires)
    _NO_DATE = "1900-01-01"

    def __init__(self):
        cfg = get_config()
        self.db_path = cfg.database.sqlite_path.expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(self._TABLE)
            conn.commit()

    def _key(type_: str, id_: str | None = None) -> str:
        """Build cache key: 'type:id' or just 'type' for un-keyed reports."""
        if id_:
            return f"{type_}:{id_.upper()}"
        return type_

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    # Cache expires after 5 minutes (300 seconds)
    _TTL_SECONDS = 300

    def get(self, cache_key: str) -> dict[str, Any] | None:
        """
        Return cached report if it was created within _TTL_SECONDS.
        Returns dict with 'report' and 'data' keys, or None on miss/expired.
        """
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT report, raw_data, created_at FROM analysis_cache WHERE cache_key = ?",
                (cache_key,),
            ).fetchone()

        if row is None:
            return None

        # Check TTL expiration
        created = datetime.fromisoformat(row["created_at"])
        age = (datetime.utcnow() - created).total_seconds()
        if age > self._TTL_SECONDS:
            return None  # expired

        return {
            "report": row["report"],
            "data": json.loads(row["raw_data"]) if row["raw_data"] else None,
        }

    def set(
        self,
        cache_key: str,
        report: str,
        raw_data: dict | None = None,
        trade_date: str | None = None,
    ) -> None:
        """
        Upsert a cache entry. Expires after _TTL_SECONDS.
        """
        if trade_date is None:
            trade_date = date.today().isoformat()

        raw_json = json.dumps(raw_data, ensure_ascii=False, default=str) if raw_data else None
        now = datetime.utcnow().isoformat()

        with sqlite3.connect(str(self.db_path)) as conn:
            # Clean up expired entries before writing
            cutoff = datetime.utcnow().timestamp() - self._TTL_SECONDS
            conn.execute(
                "DELETE FROM analysis_cache WHERE created_at < ?",
                (datetime.utcfromtimestamp(cutoff).isoformat(),),
            )
            conn.execute(
                """
                INSERT INTO analysis_cache (cache_key, report, trade_date, raw_data, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    report     = excluded.report,
                    trade_date = excluded.trade_date,
                    raw_data   = excluded.raw_data,
                    created_at  = excluded.created_at
                """,
                (cache_key, report, trade_date, raw_json, now),
            )
            conn.commit()
