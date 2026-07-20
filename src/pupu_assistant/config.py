from pathlib import Path

from pydantic import Field
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
    pupu_evidence_path: Path = Path(".local/evidence")
    pupu_allow_live_mutation: bool = False
    pupu_app_version: str = "6.4.5"
    pupu_os_type: str = "Android"
