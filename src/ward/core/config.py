"""Configuration management — loads from env via python-dotenv."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from pydantic import BaseModel

# Load .env file from project root
_project_root = Path(__file__).parent.parent.parent.parent
load_dotenv(_project_root / ".env", override=False)


class LLMConfig(BaseModel):
    api_key: str
    base_url: str = "https://api.minimaxi.com/anthropic"
    model: str = "babog-3.1-chat"


class DatabaseConfig(BaseModel):
    sqlite_path: Path = Path("~/.ward/conversations.db")


class Config(BaseModel):
    llm: LLMConfig
    database: DatabaseConfig = DatabaseConfig()
    public_mode: bool = False  # True = 绑定 0.0.0.0（允许外部访问），默认 False = 仅本地
    web_host: str = "0.0.0.0"
    web_port: int = 8000


def load_config() -> Config:
    """Load config from environment variables (loaded from .env by python-dotenv)."""
    api_key = os.environ.get("MINIMAX_API_KEY") or os.environ.get("MINIMAX_PORTAL_API_KEY", "")
    base_url = os.environ.get("ANTHROPIC_BASE_URL", "https://api.minimaxi.com/anthropic")
    model = os.environ.get("LLM_MODEL", "MiniMax-M2.7-highspeed")

    # Web server
    # PUBLIC_MODE=1 或 WARD_PUBLIC_MODE=1 时绑定 0.0.0.0（允许外部访问），默认只绑定 127.0.0.1
    public_mode = os.environ.get("PUBLIC_MODE", "") == "1" or os.environ.get("WARD_PUBLIC_MODE", "") == "1"
    web_host = os.environ.get("WEB_HOST", "0.0.0.0" if public_mode else "127.0.0.1")
    web_port = int(os.environ.get("WEB_PORT", "8000"))

    return Config(
        llm=LLMConfig(api_key=api_key, base_url=base_url, model=model),
        public_mode=public_mode,
        web_host=web_host,
        web_port=web_port,
    )


# Global config instance
_config: Optional[Config] = None


def get_config() -> Config:
    global _config
    if _config is None:
        _config = load_config()
    return _config
