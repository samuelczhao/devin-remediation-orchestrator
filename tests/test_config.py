from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from app.config import Settings


def test_simulation_mode_does_not_require_devin_credentials() -> None:
    settings = Settings(app_mode="simulation")
    assert settings.devin_api_key is None


def test_unprefixed_environment_does_not_override_app_config(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("REMEDIATION_GITHUB_REPOSITORY", raising=False)
    monkeypatch.delenv("REMEDIATION_GITHUB_ALLOWED_ACTOR", raising=False)
    monkeypatch.delenv("REMEDIATION_APP_MODE", raising=False)
    monkeypatch.delenv("REMEDIATION_DEVIN_API_KEY", raising=False)
    monkeypatch.delenv("REMEDIATION_GITHUB_WEBHOOK_SECRET", raising=False)
    monkeypatch.setenv("GITHUB_REPOSITORY", "samuelczhao/devin-remediation-orchestrator")
    monkeypatch.setenv("GITHUB_ALLOWED_ACTOR", "github-actions")
    monkeypatch.setenv("APP_MODE", "live")
    monkeypatch.setenv("DEVIN_API_KEY", "cog_runner_value")
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "runner-owned-value")

    settings = Settings()

    assert settings.app_mode == "simulation"
    assert settings.devin_api_key is None
    assert settings.github_repository == "samuelczhao/superset"
    assert settings.github_allowed_actor == "samuelczhao"


def test_prefixed_environment_overrides_app_config(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("REMEDIATION_APP_MODE", "live")
    monkeypatch.setenv("REMEDIATION_DEVIN_API_KEY", "cog_test")
    monkeypatch.setenv("REMEDIATION_DEVIN_ORG_ID", "org-test")
    monkeypatch.setenv("REMEDIATION_GITHUB_WEBHOOK_SECRET", "w" * 32)
    monkeypatch.setenv("REMEDIATION_CONTROL_PLANE_PASSWORD", "p" * 32)
    monkeypatch.setenv("REMEDIATION_GITHUB_REPOSITORY", "example/superset-fork")
    monkeypatch.setenv("REMEDIATION_GITHUB_ALLOWED_ACTOR", "release-operator")

    settings = Settings()

    assert settings.app_mode == "live"
    assert settings.devin_api_key is not None
    assert settings.devin_api_key.get_secret_value() == "cog_test"
    assert settings.github_repository == "example/superset-fork"
    assert settings.github_allowed_actor == "release-operator"


def test_live_mode_requires_devin_credentials() -> None:
    with pytest.raises(ValidationError, match="REMEDIATION_DEVIN_API_KEY"):
        Settings(app_mode="live")


def test_live_mode_rejects_demo_webhook_secret() -> None:
    with pytest.raises(ValidationError, match="REMEDIATION_GITHUB_WEBHOOK_SECRET"):
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
    with pytest.raises(ValidationError, match="REMEDIATION_GITHUB_WEBHOOK_SECRET"):
        Settings(
            app_mode="live",
            devin_api_key=SecretStr("cog_test"),
            devin_org_id="org-test",
            github_webhook_secret=SecretStr(secret),
            control_plane_password=SecretStr("p" * 32),
        )


def test_live_mode_requires_strong_control_plane_password() -> None:
    with pytest.raises(ValidationError, match="REMEDIATION_CONTROL_PLANE_PASSWORD"):
        Settings(
            app_mode="live",
            devin_api_key=SecretStr("cog_test"),
            devin_org_id="org-test",
            github_webhook_secret=SecretStr("w" * 32),
            control_plane_password=SecretStr("weak"),
        )
