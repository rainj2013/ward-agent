"""Local-only persistence for Ward runtime settings."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

from dotenv import set_key

from ward.core.config import get_config


class SettingsService:
    """Read effective LLM settings and persist canonical values to .env."""

    def __init__(self, env_path: Path | None = None):
        self.env_path = env_path or Path(__file__).resolve().parents[3] / ".env"

    def get_llm_settings(self) -> dict:
        cfg = get_config()
        return {
            "base_url": cfg.llm.base_url,
            "api_key_configured": bool(cfg.llm.api_key),
            "api_key_masked": self._mask_secret(cfg.llm.api_key),
            "model": cfg.llm.model,
            "env_path": str(self.env_path),
        }

    def save_llm_settings(self, base_url: str, model: str, api_key: str | None = None) -> dict:
        base_url = base_url.strip().rstrip("/")
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("BASE API 必须是有效的 HTTP(S) URL")
        model = model.strip()
        if not model:
            raise ValueError("模型名称不能为空")

        self.env_path.parent.mkdir(parents=True, exist_ok=True)
        self.env_path.touch(exist_ok=True, mode=0o600)
        set_key(str(self.env_path), "ANTHROPIC_BASE_URL", base_url, quote_mode="always")
        set_key(str(self.env_path), "LLM_MODEL", model, quote_mode="always")

        api_key = api_key.strip() if api_key is not None else None
        if api_key:
            set_key(str(self.env_path), "ANTHROPIC_AUTH_TOKEN", api_key, quote_mode="always")

        os.chmod(self.env_path, 0o600)
        return {
            "base_url": base_url,
            "model": model,
            "api_key_updated": bool(api_key),
            "env_path": str(self.env_path),
            "restart_required": True,
        }

    @staticmethod
    def _mask_secret(value: str) -> str:
        if not value:
            return ""
        if len(value) <= 8:
            return "*" * len(value)
        return f"{value[:4]}{'*' * 8}{value[-4:]}"
