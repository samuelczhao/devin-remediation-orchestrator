import base64
import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from uuid import uuid4

import httpx
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.config import Settings
from app.devin_client import FakeDevinClient
from app.main import create_app
from app.security import sign_payload
from tests.factories import issue_payload_data

SECRET = "test-webhook-secret"


def make_settings(path: Path) -> Settings:
    return Settings(
        database_path=path,
        github_webhook_secret=SecretStr(SECRET),
        poll_interval_seconds=0.01,
    )


def post_webhook(
    client: TestClient, payload: dict[str, object], secret: str = SECRET
) -> httpx.Response:
    raw = json.dumps(payload).encode()
    headers = {
        "x-github-event": "issues",
        "x-github-delivery": str(uuid4()),
        "x-hub-signature-256": sign_payload(raw, secret),
        "content-type": "application/json",
    }
    return cast(httpx.Response, client.post("/webhooks/github", content=raw, headers=headers))


def test_valid_webhook_is_accepted_and_deduplicated(tmp_path: Path) -> None:
    settings = make_settings(tmp_path / "tasks.db")
    app = create_app(settings, FakeDevinClient(settings.github_repository))
    with TestClient(app) as client:
        first = post_webhook(client, issue_payload_data())
        second = post_webhook(client, issue_payload_data())
        assert first.status_code == 202
        assert first.json()["created"] is True
        assert second.json()["created"] is False
        assert len(client.get("/api/tasks").json()) == 1


def test_readiness_exposes_simulation_mode(tmp_path: Path) -> None:
    settings = make_settings(tmp_path / "tasks.db")
    with TestClient(create_app(settings)) as client:
        response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "mode": "simulation"}


def test_invalid_signature_is_rejected(tmp_path: Path) -> None:
    settings = make_settings(tmp_path / "tasks.db")
    with TestClient(create_app(settings)) as client:
        response = post_webhook(client, issue_payload_data(), secret="wrong")
    assert response.status_code == 401


def test_untrusted_repository_is_rejected(tmp_path: Path) -> None:
    settings = make_settings(tmp_path / "tasks.db")
    with TestClient(create_app(settings)) as client:
        response = post_webhook(client, issue_payload_data(repository_id=999))
    assert response.status_code == 403


def test_untrusted_actor_is_rejected(tmp_path: Path) -> None:
    settings = make_settings(tmp_path / "tasks.db")
    with TestClient(create_app(settings)) as client:
        response = post_webhook(client, issue_payload_data(actor_id=404))
    assert response.status_code == 403


def test_pull_request_payload_is_ignored(tmp_path: Path) -> None:
    settings = make_settings(tmp_path / "tasks.db")
    payload = issue_payload_data(pull_request={"url": "https://api.github.test/pulls/1"})
    with TestClient(create_app(settings)) as client:
        response = post_webhook(client, payload)
    assert response.json() == {"accepted": False, "reason": "ignored_pull_request"}


def test_malformed_delivery_id_is_rejected(tmp_path: Path) -> None:
    settings = make_settings(tmp_path / "tasks.db")
    raw = json.dumps(issue_payload_data()).encode()
    headers = {
        "x-github-event": "issues",
        "x-github-delivery": "not-a-uuid",
        "x-hub-signature-256": sign_payload(raw, SECRET),
    }
    with TestClient(create_app(settings)) as client:
        response = client.post("/webhooks/github", content=raw, headers=headers)
    assert response.status_code == 400


def test_oversized_payload_is_rejected(tmp_path: Path) -> None:
    settings = make_settings(tmp_path / "tasks.db").model_copy(update={"max_webhook_bytes": 8})
    with TestClient(create_app(settings)) as client:
        response = post_webhook(client, issue_payload_data())
    assert response.status_code == 413


def test_wrong_label_is_ignored(tmp_path: Path) -> None:
    settings = make_settings(tmp_path / "tasks.db")
    with TestClient(create_app(settings)) as client:
        response = post_webhook(client, issue_payload_data(label="triage"))
    assert response.status_code == 202
    assert response.json() == {"accepted": False, "reason": "ignored_label"}


def test_realistic_non_labeled_issue_action_is_ignored(tmp_path: Path) -> None:
    settings = make_settings(tmp_path / "tasks.db")
    payload = issue_payload_data(action="opened")
    payload.pop("label")
    with TestClient(create_app(settings)) as client:
        response = post_webhook(client, payload)
    assert response.status_code == 202
    assert response.json() == {"accepted": False, "reason": "ignored_action"}


def test_dashboard_escapes_issue_title(tmp_path: Path) -> None:
    settings = make_settings(tmp_path / "tasks.db")
    app = create_app(settings, FakeDevinClient(settings.github_repository))
    with TestClient(app) as client:
        post_webhook(client, issue_payload_data(title="<script>alert(1)</script>"))
        html = client.get("/").text
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_dashboard_exposes_operational_signals_and_security_headers(tmp_path: Path) -> None:
    settings = make_settings(tmp_path / "tasks.db")
    with TestClient(create_app(settings)) as client:
        response = client.get("/")
    assert "Queued" in response.text
    assert "Median cycle" in response.text
    assert "Last attempt" in response.text
    assert 'http-equiv="refresh"' in response.text
    assert response.headers["cache-control"] == "no-store"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]


def test_live_control_plane_requires_basic_auth(tmp_path: Path) -> None:
    password = "p" * 32
    settings = Settings(
        app_mode="live",
        database_path=tmp_path / "tasks.db",
        devin_api_key=SecretStr("cog_test"),
        devin_org_id="org-test",
        github_webhook_secret=SecretStr("w" * 32),
        control_plane_password=SecretStr(password),
        poll_interval_seconds=100,
    )
    credentials = base64.b64encode(f"operator:{password}".encode()).decode()
    app = create_app(settings, FakeDevinClient(settings.github_repository))
    with TestClient(app) as client:
        assert client.get("/api/tasks").status_code == 401
        assert client.get("/").status_code == 401
        assert client.get("/health/live").status_code == 200
        assert client.get("/openapi.json").status_code == 404
        authorized = client.get("/api/tasks", headers={"authorization": f"Basic {credentials}"})
    assert authorized.status_code == 200


def test_readiness_rejects_stale_or_failing_worker(tmp_path: Path) -> None:
    settings = make_settings(tmp_path / "tasks.db").model_copy(
        update={"poll_interval_seconds": 100, "worker_stale_after_seconds": 1}
    )
    app = create_app(settings)
    with TestClient(app) as client:
        orchestrator = app.state.orchestrator
        orchestrator.last_run_at = datetime.now(UTC) - timedelta(seconds=2)
        orchestrator.last_error = None
        assert client.get("/health/ready").status_code == 503
        orchestrator.last_run_at = datetime.now(UTC)
        orchestrator.last_error = "reconciliation_errors"
        assert client.get("/health/ready").status_code == 503


def test_simulation_completes_issue_to_pr_flow(tmp_path: Path) -> None:
    settings = make_settings(tmp_path / "tasks.db")
    with TestClient(create_app(settings)) as client:
        assert post_webhook(client, issue_payload_data()).status_code == 202
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            task = client.get("/api/tasks").json()[0]
            if task["state"] == "completed_with_pr":
                break
            time.sleep(0.01)
        metrics = client.get("/api/metrics").json()
    assert task["pr_url"] == "https://github.com/samuelczhao/superset/pull/999"
    assert task["structured_output"]["tests"][0]["outcome"] == "passed"
    assert metrics["pr_produced"] == 1
    assert metrics["worker_last_successful_run"] is not None
