"""Configuration management loaded exclusively from the project .env file."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from dotenv import dotenv_values
from pydantic import BaseModel

_project_root = Path(__file__).parent.parent.parent.parent
_env_path = _project_root / ".env"


class LLMConfig(BaseModel):
    api_key: str
    base_url: str = "https://api.deepseek.com/anthropic"
    model: str = "deepseek-v4-flash"


class DatabaseConfig(BaseModel):
    sqlite_path: Path = Path("~/.ward/conversations.db")


class Config(BaseModel):
    llm: LLMConfig
    database: DatabaseConfig = DatabaseConfig()
    public_mode: bool = False  # True = 绑定 0.0.0.0（允许外部访问），默认 False = 仅本地
    web_host: str = "0.0.0.0"
    web_port: int = 8000


def load_config() -> Config:
    """Load configuration directly from .env, ignoring process environment."""
    values = dotenv_values(_env_path)
    api_key = (
        values.get("ANTHROPIC_AUTH_TOKEN")
        or values.get("DEEPSEEK_API_KEY")
        or values.get("API_KEY")
        or values.get("MINIMAX_API_KEY")
        or values.get("MINIMAX_PORTAL_API_KEY")
        or ""
    )
    base_url = (
        values.get("ANTHROPIC_BASE_URL")
        or values.get("DEEPSEEK_API_URL")
        or values.get("URL")
        or "https://api.deepseek.com/anthropic"
    )
    model = values.get("LLM_MODEL") or "deepseek-v4-flash"

    # Web server
    # PUBLIC_MODE=1 或 WARD_PUBLIC_MODE=1 时绑定 0.0.0.0（允许外部访问），默认只绑定 127.0.0.1
    public_mode = values.get("PUBLIC_MODE") == "1" or values.get("WARD_PUBLIC_MODE") == "1"
    web_host = values.get("WEB_HOST") or ("0.0.0.0" if public_mode else "127.0.0.1")
    web_port = int(values.get("WEB_PORT") or "8000")

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
