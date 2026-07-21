from pathlib import Path

from pydantic import SecretStr

from pupu_assistant.config import Settings


def test_settings_use_safe_non_secret_defaults(monkeypatch) -> None:
    for name in (
        "PUPU_BASE_URL",
        "PUPU_CREDENTIALS_PATH",
        "PUPU_DATABASE_PATH",
        "PUPU_EVIDENCE_PATH",
        "PUPU_ALLOW_LIVE_MUTATION",
        "LLM_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = Settings(_env_file=None)

    assert settings.pupu_base_url == "https://j1.pupuapi.com"
    assert settings.pupu_allow_live_mutation is False
    assert settings.pupu_credentials_path == Path(".local/pupu-credentials.json")
    assert settings.pupu_database_path == Path(".local/pupu-assistant.db")
    assert settings.pupu_evidence_path == Path(".local/evidence")
    assert settings.llm_provider == "deepseek"
    assert settings.llm_base_url == "https://api.deepseek.com"
    assert settings.llm_model == "deepseek-v4-flash"
    assert settings.llm_api_key is None
    assert settings.llm_max_tool_rounds == 6

    serialized = repr(settings).lower()
    assert "refresh_token" not in serialized
    assert "access_token" not in serialized
    assert "phone" not in serialized


def test_settings_allow_environment_override(monkeypatch) -> None:
    monkeypatch.setenv("PUPU_TIMEOUT_SECONDS", "12.5")
    monkeypatch.setenv("PUPU_VERIFY_TLS", "false")
    monkeypatch.setenv("PUPU_ALLOW_LIVE_MUTATION", "true")
    monkeypatch.setenv("PUPU_APP_VERSION", "6.4.5")
    monkeypatch.setenv("PUPU_OS_TYPE", "Android")
    monkeypatch.setenv("PUPU_DATABASE_PATH", "/tmp/pupu-test.db")
    monkeypatch.setenv("LLM_BASE_URL", "https://deepseek.example.test")
    monkeypatch.setenv("LLM_API_KEY", "never-print-this")
    monkeypatch.setenv("LLM_MODEL", "configured-model")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "33")
    monkeypatch.setenv("LLM_MAX_TOOL_ROUNDS", "4")

    settings = Settings(_env_file=None)

    assert settings.pupu_timeout_seconds == 12.5
    assert settings.pupu_verify_tls is False
    assert settings.pupu_allow_live_mutation is True
    assert settings.pupu_app_version == "6.4.5"
    assert settings.pupu_os_type == "Android"
    assert settings.pupu_database_path == Path("/tmp/pupu-test.db")
    assert settings.llm_base_url == "https://deepseek.example.test"
    assert settings.llm_api_key == SecretStr("never-print-this")
    assert settings.llm_model == "configured-model"
    assert settings.llm_timeout_seconds == 33
    assert settings.llm_max_tool_rounds == 4
    assert "never-print-this" not in repr(settings)
