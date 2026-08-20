import pytest
from pydantic import SecretStr, ValidationError

from app.config import Settings


def test_simulation_mode_does_not_require_devin_credentials() -> None:
    settings = Settings(app_mode="simulation")
    assert settings.devin_api_key is None


def test_live_mode_requires_devin_credentials() -> None:
    with pytest.raises(ValidationError, match="DEVIN_API_KEY"):
        Settings(app_mode="live")


def test_live_mode_rejects_demo_webhook_secret() -> None:
    with pytest.raises(ValidationError, match="GITHUB_WEBHOOK_SECRET"):
        Settings(
            app_mode="live",
            devin_api_key=SecretStr("cog_test"),
            devin_org_id="org-test",
        )
