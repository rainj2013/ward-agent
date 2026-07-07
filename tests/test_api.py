from pathlib import Path

from fastapi.testclient import TestClient

import ward.core.config as config_module
from ward.app import create_app
from ward.core.config import Config, DatabaseConfig, LLMConfig


def test_core_pages_and_stock_search(tmp_path: Path):
    previous = config_module._config
    config_module._config = Config(
        llm=LLMConfig(api_key="test-key", base_url="https://example.invalid", model="test-model"),
        database=DatabaseConfig(sqlite_path=tmp_path / "ward.db"),
    )
    try:
        with TestClient(create_app()) as client:
            assert client.get("/").status_code == 200
            assert client.get("/runtime").status_code == 200
            result = client.get("/api/stock/search", params={"q": "MU"})
            assert result.status_code == 200
            assert result.json()["results"][0]["symbol"] == "MU"
            stats = client.get("/api/runtime/stats", params={"range": "1d"})
            assert stats.status_code == 200
            assert stats.json()["ok"] is True
            paths = client.get("/openapi.json").json()["paths"]
            assert {
                "/api/market-overview",
                "/api/stock/{symbol}/quote",
                "/api/analysis-jobs/{job_id}",
                "/api/chat/stream",
                "/api/settings/llm",
            } <= set(paths)
    finally:
        config_module._config = previous
