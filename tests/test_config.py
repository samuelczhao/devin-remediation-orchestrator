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


@pytest.mark.parametrize(
    "secret",
    ["", "x", "local-demo-secret", "replace-with-openssl-rand-hex-32"],
)
def test_live_mode_rejects_weak_or_shipped_secrets(secret: str) -> None:
    with pytest.raises(ValidationError, match="GITHUB_WEBHOOK_SECRET"):
        Settings(
            app_mode="live",
            devin_api_key=SecretStr("cog_test"),
            devin_org_id="org-test",
            github_webhook_secret=SecretStr(secret),
            control_plane_password=SecretStr("p" * 32),
        )


def test_live_mode_requires_strong_control_plane_password() -> None:
    with pytest.raises(ValidationError, match="CONTROL_PLANE_PASSWORD"):
        Settings(
            app_mode="live",
            devin_api_key=SecretStr("cog_test"),
            devin_org_id="org-test",
            github_webhook_secret=SecretStr("w" * 32),
            control_plane_password=SecretStr("weak"),
        )
