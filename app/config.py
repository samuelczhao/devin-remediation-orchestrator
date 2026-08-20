from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_WEBHOOK_SECRET = "local-demo-secret"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_mode: Literal["simulation", "live"] = "simulation"
    database_path: Path = Path("data/orchestrator.db")
    devin_api_key: SecretStr | None = None
    devin_org_id: str | None = None
    devin_max_acu_limit: int = Field(default=3, gt=0)
    devin_bypass_approval: bool = False
    github_webhook_secret: SecretStr = SecretStr(DEFAULT_WEBHOOK_SECRET)
    github_repository: str = "samuelczhao/superset"
    github_repository_id: int = Field(default=1_340_946_845, gt=0)
    github_default_branch: str = "master"
    github_allowed_actor: str = "samuelczhao"
    github_allowed_actor_id: int = Field(default=30_126_000, gt=0)
    trigger_label: str = "devin:ready"
    poll_interval_seconds: float = Field(default=2.0, gt=0)
    max_webhook_bytes: int = Field(default=1_000_000, gt=0)

    @model_validator(mode="after")
    def validate_live_credentials(self) -> "Settings":
        if self.app_mode == "live" and not self.devin_api_key:
            raise ValueError("DEVIN_API_KEY is required in live mode")
        if self.app_mode == "live" and not self.devin_org_id:
            raise ValueError("DEVIN_ORG_ID is required in live mode")
        if (
            self.app_mode == "live"
            and self.github_webhook_secret.get_secret_value() == DEFAULT_WEBHOOK_SECRET
        ):
            raise ValueError("GITHUB_WEBHOOK_SECRET must be changed in live mode")
        return self

    @field_validator("devin_org_id")
    @classmethod
    def validate_org_id(cls, value: str | None) -> str | None:
        if value and not value.startswith("org-"):
            raise ValueError("DEVIN_ORG_ID must start with org-")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
