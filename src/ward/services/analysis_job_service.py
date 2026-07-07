"""Low-rate analysis job runtime for slow AI report generation."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from time import perf_counter
from typing import Any

from ward.core.config import get_config
from ward.services.db.connection import database_connection
from ward.services.db.migrations import apply_migrations
from ward.services.report_verifier import ReportVerifier


JobHandler = Callable[[dict[str, Any]], dict[str, Any]]


class AnalysisJobService:
    """Persist, queue, and execute slow analysis jobs with low concurrency."""

    _JOBS_TABLE = """
        CREATE TABLE IF NOT EXISTS analysis_jobs (
            id          TEXT PRIMARY KEY,
            type        TEXT NOT NULL,
            payload     TEXT NOT NULL,
            status      TEXT NOT NULL,
            result      TEXT,
            error       TEXT,
            cache_hit   INTEGER NOT NULL DEFAULT 0,
            stage       TEXT,
            stage_message TEXT,
            queue_position INTEGER,
            duration_ms INTEGER,
            input_tokens INTEGER NOT NULL DEFAULT 0,
            output_tokens INTEGER NOT NULL DEFAULT 0,
            total_tokens INTEGER NOT NULL DEFAULT 0,
            estimated_cost REAL NOT NULL DEFAULT 0,
            provider    TEXT,
            model       TEXT,
            created_at  TEXT NOT NULL,
            started_at  TEXT,
            finished_at TEXT,
            updated_at  TEXT NOT NULL
        )
    """

    _EVENTS_TABLE = """
        CREATE TABLE IF NOT EXISTS analysis_job_events (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id     TEXT NOT NULL,
            event      TEXT NOT NULL,
            message    TEXT NOT NULL,
            stage      TEXT,
            data       TEXT,
            duration_ms INTEGER,
            created_at TEXT NOT NULL
        )
    """

    _AVG_JOB_SECONDS = 30
    _MODEL_PRICING = {
        # Fill in real plan/unit pricing later. Keeping cost at 0 avoids
        # pretending precision for subscription or promotional billing.
        "deepseek-v4-flash": {"input_per_1m": 0.0, "output_per_1m": 0.0, "currency": "CNY"},
    }

    def __init__(self, concurrency: int = 1):
        cfg = get_config()
        self.db_path = cfg.database.sqlite_path.expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._handlers: dict[str, JobHandler] = {}
        self._workers_started = False
        self._concurrency = concurrency
        self._init_db()

    def _init_db(self) -> None:
        with database_connection(self.db_path) as conn:
            apply_migrations(conn, "analysis_jobs", [(1, self._create_job_schema), (2, self._upgrade_job_schema)])
            now = self._now()
            conn.execute(
                """
                UPDATE analysis_jobs
                SET status = ?, error = ?, finished_at = ?, updated_at = ?
                WHERE status IN ('queued', 'running')
                """,
                ("failed", "服务重启，未完成任务已终止", now, now),
            )
            conn.commit()

    def _create_job_schema(self, conn: sqlite3.Connection) -> None:
        conn.execute(self._JOBS_TABLE)
        conn.execute(self._EVENTS_TABLE)

    def _upgrade_job_schema(self, conn: sqlite3.Connection) -> None:
        self._ensure_columns(conn, "analysis_jobs", {
            "stage": "TEXT", "stage_message": "TEXT", "queue_position": "INTEGER",
            "duration_ms": "INTEGER", "input_tokens": "INTEGER NOT NULL DEFAULT 0",
            "output_tokens": "INTEGER NOT NULL DEFAULT 0", "total_tokens": "INTEGER NOT NULL DEFAULT 0",
            "estimated_cost": "REAL NOT NULL DEFAULT 0", "provider": "TEXT", "model": "TEXT",
        })
        self._ensure_columns(conn, "analysis_job_events", {"stage": "TEXT", "duration_ms": "INTEGER"})

    def _ensure_columns(self, conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        for name, ddl in columns.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")

    def register_handler(self, job_type: str, handler: JobHandler) -> None:
        """Register a sync handler for a job type."""
        self._handlers[job_type] = handler

    async def ensure_workers_started(self) -> None:
        """Start background workers once the app event loop is running."""
        if self._workers_started:
            return
        self._workers_started = True
        for idx in range(self._concurrency):
            asyncio.create_task(self._worker(idx))

    async def create_job(self, job_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Create and enqueue a job."""
        if job_type not in self._handlers:
            raise ValueError(f"Unknown analysis job type: {job_type}")

        await self.ensure_workers_started()
        job_id = f"job_{uuid.uuid4().hex[:16]}"
        now = self._now()
        queue_position = self._queue.qsize() + 1
        cfg = get_config()
        with database_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO analysis_jobs
                    (id, type, payload, status, stage, stage_message, queue_position,
                     provider, model, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    job_type,
                    json.dumps(payload, ensure_ascii=False),
                    "queued",
                    "queued",
                    "任务已进入队列",
                    queue_position,
                    "anthropic-compatible",
                    cfg.llm.model,
                    now,
                    now,
                ),
            )
            conn.commit()
        self._add_event(
            job_id,
            "queued",
            "任务已进入队列",
            "queued",
            {"queue_position": queue_position, "estimated_wait_seconds": queue_position * self._AVG_JOB_SECONDS},
        )
        await self._queue.put(job_id)
        return self.get_job(job_id) or {"id": job_id, "status": "queued"}

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        """Return a job snapshot."""
        with database_connection(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT id, type, payload, status, result, error, cache_hit,
                       stage, stage_message, queue_position, duration_ms,
                       input_tokens, output_tokens, total_tokens, estimated_cost,
                       provider, model, created_at, started_at, finished_at, updated_at
                FROM analysis_jobs
                WHERE id = ?
                """,
                (job_id,),
            ).fetchone()

        if row is None:
            return None

        return {
            "id": row["id"],
            "type": row["type"],
            "payload": json.loads(row["payload"]),
            "status": row["status"],
            "result": json.loads(row["result"]) if row["result"] else None,
            "error": row["error"],
            "cache_hit": bool(row["cache_hit"]),
            "stage": row["stage"],
            "stage_message": row["stage_message"],
            "queue_position": row["queue_position"],
            "duration_ms": row["duration_ms"],
            "usage": {
                "provider": row["provider"],
                "model": row["model"],
                "input_tokens": row["input_tokens"],
                "output_tokens": row["output_tokens"],
                "total_tokens": row["total_tokens"],
                "estimated_cost": row["estimated_cost"],
                "currency": self._currency(row["model"]),
            },
            "created_at": row["created_at"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
            "updated_at": row["updated_at"],
        }

    def get_events(self, job_id: str, after_id: int = 0) -> list[dict[str, Any]]:
        """Return events after an event id."""
        with database_connection(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT id, event, message, stage, data, duration_ms, created_at
                FROM analysis_job_events
                WHERE job_id = ? AND id > ?
                ORDER BY id ASC
                """,
                (job_id, after_id),
            ).fetchall()

        return [
            {
                "id": row["id"],
                "event": row["event"],
                "message": row["message"],
                "stage": row["stage"],
                "data": json.loads(row["data"]) if row["data"] else None,
                "duration_ms": row["duration_ms"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def get_trace(self, job_id: str) -> dict[str, Any] | None:
        """Return a job with all trace events."""
        job = self.get_job(job_id)
        if not job:
            return None
        return {"job": job, "events": self.get_events(job_id)}

    def get_stats(self, range_: str = "1d") -> dict[str, Any]:
        """Return aggregate runtime stats for recent jobs."""
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - self._range_delta(range_)
        with database_connection(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT type, status, cache_hit, duration_ms,
                       input_tokens, output_tokens, total_tokens, estimated_cost
                FROM analysis_jobs
                WHERE created_at >= ?
                """,
                (cutoff.isoformat(),),
            ).fetchall()

        by_type: dict[str, dict[str, Any]] = {}
        durations = [row["duration_ms"] for row in rows if row["duration_ms"] is not None]
        for row in rows:
            bucket = by_type.setdefault(row["type"], {
                "jobs_total": 0,
                "jobs_succeeded": 0,
                "jobs_failed": 0,
                "cache_hits": 0,
                "llm_calls": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "estimated_cost": 0,
            })
            bucket["jobs_total"] += 1
            if row["status"] == "succeeded":
                bucket["jobs_succeeded"] += 1
            if row["status"] == "failed":
                bucket["jobs_failed"] += 1
            if row["cache_hit"]:
                bucket["cache_hits"] += 1
            if row["total_tokens"]:
                bucket["llm_calls"] += 1
            bucket["input_tokens"] += row["input_tokens"] or 0
            bucket["output_tokens"] += row["output_tokens"] or 0
            bucket["total_tokens"] += row["total_tokens"] or 0
            bucket["estimated_cost"] += row["estimated_cost"] or 0

        total = {
            "range": range_,
            "jobs_total": len(rows),
            "jobs_succeeded": sum(1 for row in rows if row["status"] == "succeeded"),
            "jobs_failed": sum(1 for row in rows if row["status"] == "failed"),
            "cache_hits": sum(1 for row in rows if row["cache_hit"]),
            "llm_calls": sum(1 for row in rows if row["total_tokens"]),
            "input_tokens": sum(row["input_tokens"] or 0 for row in rows),
            "output_tokens": sum(row["output_tokens"] or 0 for row in rows),
            "total_tokens": sum(row["total_tokens"] or 0 for row in rows),
            "estimated_cost": sum(row["estimated_cost"] or 0 for row in rows),
            "avg_duration_ms": int(sum(durations) / len(durations)) if durations else 0,
            "by_type": by_type,
        }
        total["cache_hit_rate"] = round(total["cache_hits"] / total["jobs_total"], 4) if total["jobs_total"] else 0
        return total

    async def _worker(self, idx: int) -> None:
        while True:
            job_id = await self._queue.get()
            try:
                await self._run_job(job_id, idx)
            finally:
                self._queue.task_done()

    async def _run_job(self, job_id: str, worker_id: int) -> None:
        job = self.get_job(job_id)
        if not job or job["status"] != "queued":
            return

        handler = self._handlers.get(job["type"])
        if handler is None:
            self._mark_failed(job_id, f"No handler registered for {job['type']}")
            return

        self._mark_running(job_id)
        started = perf_counter()
        self._set_stage(job_id, "running", "开始执行分析任务")
        self._add_event(job_id, "running", "开始执行分析任务", "running", {"worker_id": worker_id})
        try:
            result = await asyncio.to_thread(self._execute_handler, job_id, handler, job["payload"])
        except Exception as exc:
            self._mark_failed(job_id, str(exc))
            return

        duration_ms = int((perf_counter() - started) * 1000)
        if result.get("ok"):
            verification = self._verify_result(job_id, job["type"], result)
            result["verification"] = verification
            if not verification.get("passed"):
                self._mark_failed(job_id, "分析报告验证未通过", result, duration_ms)
                return
            self._mark_succeeded(job_id, result, duration_ms)
        else:
            self._mark_failed(job_id, result.get("error") or "分析任务失败", result, duration_ms)

    def _execute_handler(self, job_id: str, handler: JobHandler, payload: dict[str, Any]) -> dict[str, Any]:
        self._trace(job_id, "cache_check", "正在检查是否已有可复用分析", "cache_check")
        payload = dict(payload)
        payload["_trace"] = lambda event, message, stage=None, data=None, duration_ms=None: self._trace(
            job_id, event, message, stage, data, duration_ms
        )
        with self._stage_timer(job_id, "execute_handler", "执行分析处理器"):
            return handler(payload)

    def _verify_result(self, job_id: str, job_type: str, result: dict[str, Any]) -> dict[str, Any]:
        """Run deterministic report verification and persist it in the trace."""
        started = perf_counter()
        self._trace(job_id, "stage_start", "开始验证分析报告", "verifying")
        verification = ReportVerifier().verify(job_type, result).to_dict()
        duration_ms = int((perf_counter() - started) * 1000)
        if verification["passed"]:
            message = "分析报告验证通过"
            event = "verification_passed"
        else:
            message = "分析报告验证未通过"
            event = "verification_failed"
        self._trace(job_id, event, message, "verifying", verification, duration_ms)
        return verification

    def _mark_running(self, job_id: str) -> None:
        now = self._now()
        with database_connection(self.db_path) as conn:
            conn.execute(
                """
                UPDATE analysis_jobs
                SET status = ?, stage = ?, stage_message = ?, queue_position = 0,
                    started_at = ?, updated_at = ?
                WHERE id = ? AND status = 'queued'
                """,
                ("running", "running", "开始执行分析任务", now, now, job_id),
            )
            conn.commit()

    def _mark_succeeded(self, job_id: str, result: dict[str, Any], duration_ms: int) -> None:
        now = self._now()
        cache_hit = 1 if result.get("cached") else 0
        usage = self._usage_from_result(result)
        with database_connection(self.db_path) as conn:
            cursor = conn.execute(
                """
                UPDATE analysis_jobs
                SET status = ?, result = ?, error = NULL, cache_hit = ?,
                    stage = ?, stage_message = ?, duration_ms = ?,
                    input_tokens = ?, output_tokens = ?, total_tokens = ?, estimated_cost = ?,
                    finished_at = ?, updated_at = ?
                WHERE id = ? AND status = 'running'
                """,
                (
                    "succeeded",
                    json.dumps(result, ensure_ascii=False, default=str),
                    cache_hit,
                    "succeeded",
                    "分析任务完成",
                    duration_ms,
                    usage["input_tokens"],
                    usage["output_tokens"],
                    usage["total_tokens"],
                    usage["estimated_cost"],
                    now,
                    now,
                    job_id,
                ),
            )
            conn.commit()
        if cursor.rowcount:
            message = "命中缓存，已复用现有分析" if cache_hit else "分析任务完成"
            self._add_event(job_id, "succeeded", message, "succeeded", {"cache_hit": bool(cache_hit), "usage": usage}, duration_ms)

    def _mark_failed(
        self,
        job_id: str,
        error: str,
        result: dict[str, Any] | None = None,
        duration_ms: int | None = None,
    ) -> None:
        now = self._now()
        usage = self._usage_from_result(result or {})
        with database_connection(self.db_path) as conn:
            cursor = conn.execute(
                """
                UPDATE analysis_jobs
                SET status = ?, result = ?, error = ?, stage = ?, stage_message = ?,
                    duration_ms = ?, input_tokens = ?, output_tokens = ?, total_tokens = ?,
                    estimated_cost = ?, finished_at = ?, updated_at = ?
                WHERE id = ? AND status IN ('queued', 'running')
                """,
                (
                    "failed",
                    json.dumps(result, ensure_ascii=False, default=str) if result else None,
                    error,
                    "failed",
                    error,
                    duration_ms,
                    usage["input_tokens"],
                    usage["output_tokens"],
                    usage["total_tokens"],
                    usage["estimated_cost"],
                    now,
                    now,
                    job_id,
                ),
            )
            conn.commit()
        if cursor.rowcount:
            self._add_event(job_id, "failed", error, "failed", {"usage": usage}, duration_ms)

    def _add_event(
        self,
        job_id: str,
        event: str,
        message: str,
        stage: str | None = None,
        data: dict[str, Any] | None = None,
        duration_ms: int | None = None,
    ) -> None:
        with database_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO analysis_job_events (job_id, event, message, stage, data, duration_ms, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    event,
                    message,
                    stage,
                    json.dumps(data, ensure_ascii=False, default=str) if data else None,
                    duration_ms,
                    self._now(),
                ),
            )
            conn.commit()

    def _set_stage(self, job_id: str, stage: str, message: str) -> None:
        with database_connection(self.db_path) as conn:
            conn.execute(
                """
                UPDATE analysis_jobs
                SET stage = ?, stage_message = ?, updated_at = ?
                WHERE id = ?
                """,
                (stage, message, self._now(), job_id),
            )
            conn.commit()

    def _trace(
        self,
        job_id: str,
        event: str,
        message: str,
        stage: str | None = None,
        data: dict[str, Any] | None = None,
        duration_ms: int | None = None,
    ) -> None:
        if stage:
            self._set_stage(job_id, stage, message)
        self._add_event(job_id, event, message, stage, data, duration_ms)

    @contextmanager
    def _stage_timer(self, job_id: str, stage: str, message: str):
        started = perf_counter()
        self._trace(job_id, "stage_start", message, stage)
        try:
            yield
        finally:
            duration_ms = int((perf_counter() - started) * 1000)
            self._add_event(job_id, "stage_end", message, stage, duration_ms=duration_ms)

    def _usage_from_result(self, result: dict[str, Any]) -> dict[str, Any]:
        usage = result.get("usage") or {}
        input_tokens = int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
        output_tokens = int(usage.get("output_tokens") or usage.get("completion_tokens") or 0)
        total_tokens = int(usage.get("total_tokens") or input_tokens + output_tokens)
        model = usage.get("model") or result.get("model") or get_config().llm.model
        estimated_cost = self._estimate_cost(model, input_tokens, output_tokens)
        return {
            "provider": usage.get("provider") or "anthropic-compatible",
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "estimated_cost": estimated_cost,
            "currency": self._currency(model),
        }

    def _estimate_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        pricing = self._MODEL_PRICING.get(model, {})
        return round(
            input_tokens / 1_000_000 * float(pricing.get("input_per_1m", 0))
            + output_tokens / 1_000_000 * float(pricing.get("output_per_1m", 0)),
            8,
        )

    def _currency(self, model: str | None) -> str:
        return self._MODEL_PRICING.get(model or "", {}).get("currency", "CNY")

    def _range_delta(self, range_: str) -> timedelta:
        if range_ == "7d":
            return timedelta(days=7)
        if range_ == "30d":
            return timedelta(days=30)
        return timedelta(days=1)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
