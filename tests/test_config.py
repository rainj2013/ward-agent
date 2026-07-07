from pathlib import Path

import ward.core.config as config_module


def test_config_reads_project_env_file_only(tmp_path: Path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "ANTHROPIC_AUTH_TOKEN=file-key\n"
        "ANTHROPIC_BASE_URL=https://file.example/anthropic\n"
        "LLM_MODEL=file-model\n"
        "WEB_PORT=9001\n"
    )
    monkeypatch.setattr(config_module, "_env_path", env_path)
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "process-key")

    cfg = config_module.load_config()

    assert cfg.llm.api_key == "file-key"
    assert cfg.llm.base_url == "https://file.example/anthropic"
    assert cfg.llm.model == "file-model"
    assert cfg.web_port == 9001
