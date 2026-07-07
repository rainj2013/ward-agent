from pathlib import Path

import pytest

import ward.services.analysis_job_service as job_module
from ward.core.config import Config, DatabaseConfig, LLMConfig
from ward.services.analysis_job_service import AnalysisJobService


@pytest.mark.asyncio
async def test_job_terminal_state_cannot_be_overwritten(tmp_path: Path, monkeypatch):
    config = Config(
        llm=LLMConfig(api_key="key", base_url="https://example.invalid", model="test-model"),
        database=DatabaseConfig(sqlite_path=tmp_path / "jobs.db"),
    )
    monkeypatch.setattr(job_module, "get_config", lambda: config)
    service = AnalysisJobService(concurrency=0)
    service.register_handler("test", lambda payload: {"ok": True, "report": "done"})
    job = await service.create_job("test", {})

    service._mark_running(job["id"])
    service._mark_succeeded(job["id"], {"ok": True, "report": "done"}, 10)
    service._mark_failed(job["id"], "late failure")

    stored = service.get_job(job["id"])
    assert stored["status"] == "succeeded"
    assert stored["error"] is None
