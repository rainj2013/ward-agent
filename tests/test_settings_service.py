from pathlib import Path

import pytest

from ward.services.settings_service import SettingsService


def test_save_settings_preserves_key_when_input_is_blank(tmp_path: Path):
    env_path = tmp_path / ".env"
    service = SettingsService(env_path)
    service.save_llm_settings("https://example.com/anthropic", "model-a", "secret")
    service.save_llm_settings("https://example.com/v2", "model-b", "")

    text = env_path.read_text()
    assert "ANTHROPIC_AUTH_TOKEN='secret'" in text
    assert "ANTHROPIC_BASE_URL='https://example.com/v2'" in text
    assert "LLM_MODEL='model-b'" in text
    assert env_path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("base_url", ["", "not-a-url", "ftp://example.com"])
def test_save_settings_rejects_invalid_base_url(tmp_path: Path, base_url: str):
    with pytest.raises(ValueError):
        SettingsService(tmp_path / ".env").save_llm_settings(base_url, "model")


def test_mask_secret_never_returns_full_secret():
    assert SettingsService._mask_secret("abcdefghijk") == "abcd********hijk"
