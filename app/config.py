from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_WEBHOOK_SECRET = "local-demo-secret"
ENV_PREFIX = "REMEDIATION_"
MIN_LIVE_SECRET_BYTES = 32
SHIPPED_SECRET_PLACEHOLDERS = {
    DEFAULT_WEBHOOK_SECRET,
    "replace-with-openssl-rand-hex-32",
    "replace-with-another-openssl-rand-hex-32",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix=ENV_PREFIX,
        extra="ignore",
    )

    app_mode: Literal["simulation", "live"] = "simulation"
    database_path: Path = Path("data/orchestrator.db")
    devin_api_key: SecretStr | None = None
    devin_org_id: str | None = None
    devin_max_acu_limit: int = Field(default=3, gt=0)
    devin_bypass_approval: bool = False
    usage_model: Literal["self_serve", "enterprise"] = "self_serve"
    github_webhook_secret: SecretStr = SecretStr(DEFAULT_WEBHOOK_SECRET)
    control_plane_username: str = "operator"
    control_plane_password: SecretStr | None = None
    github_repository: str = "samuelczhao/superset"
    github_repository_id: int = Field(default=1_340_946_845, gt=0)
    github_default_branch: str = "master"
    github_allowed_actor: str = "samuelczhao"
    github_allowed_actor_id: int = Field(default=30_126_000, gt=0)
    trigger_label: str = "devin:ready"
    poll_interval_seconds: float = Field(default=2.0, gt=0)
    worker_stale_after_seconds: float = Field(default=60.0, gt=0)
    ambiguous_recovery_interval_seconds: float = Field(default=30.0, ge=0)
    create_retry_interval_seconds: float = Field(default=60.0, ge=0)
    max_active_sessions: int = Field(default=3, gt=0)
    max_webhook_bytes: int = Field(default=1_000_000, gt=0)

    @model_validator(mode="after")
    def validate_live_credentials(self) -> "Settings":
        if self.app_mode == "live" and not self.devin_api_key:
            raise ValueError(f"{ENV_PREFIX}DEVIN_API_KEY is required in live mode")
        if self.app_mode == "live" and not self.devin_org_id:
            raise ValueError(f"{ENV_PREFIX}DEVIN_ORG_ID is required in live mode")
        if self.app_mode == "live":
            self._validate_live_secret(
                f"{ENV_PREFIX}GITHUB_WEBHOOK_SECRET",
                self.github_webhook_secret.get_secret_value(),
            )
            if not self.control_plane_password:
                raise ValueError(f"{ENV_PREFIX}CONTROL_PLANE_PASSWORD is required in live mode")
            self._validate_live_secret(
                f"{ENV_PREFIX}CONTROL_PLANE_PASSWORD",
                self.control_plane_password.get_secret_value(),
            )
        return self

    @staticmethod
    def _validate_live_secret(name: str, value: str) -> None:
        if value in SHIPPED_SECRET_PLACEHOLDERS or len(value.encode()) < MIN_LIVE_SECRET_BYTES:
            raise ValueError(f"{name} must contain at least 32 bytes and not be a placeholder")

    @field_validator("devin_org_id")
    @classmethod
    def validate_org_id(cls, value: str | None) -> str | None:
        if value and not value.startswith("org-"):
            raise ValueError(f"{ENV_PREFIX}DEVIN_ORG_ID must start with org-")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
