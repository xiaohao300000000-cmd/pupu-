from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings with live writes disabled by default."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    pupu_base_url: str = "https://j1.pupuapi.com"
    pupu_timeout_seconds: float = Field(default=20.0, gt=0)
    pupu_verify_tls: bool = True
    pupu_credentials_path: Path = Path(".local/pupu-credentials.json")
    pupu_database_path: Path = Path(".local/pupu-assistant.db")
    pupu_evidence_path: Path = Path(".local/evidence")
    pupu_allow_live_mutation: bool = False
    pupu_app_version: str = "6.4.5"
    pupu_os_type: str = "Android"

    feishu_app_instance_name: str | None = None
    feishu_app_id: str | None = None
    feishu_app_secret: SecretStr | None = None
    feishu_verification_token: SecretStr | None = None
    feishu_encrypt_key: SecretStr | None = None

    llm_provider: str = "deepseek"
    llm_base_url: str = "https://api.deepseek.com"
    llm_api_key: SecretStr | None = None
    llm_model: str = "deepseek-v4-flash"
    llm_timeout_seconds: float = Field(default=60.0, gt=0)
    llm_max_tool_rounds: int = Field(default=6, ge=1, le=20)
