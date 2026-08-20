from pathlib import Path

import httpx
import pytest
import respx
from pydantic import SecretStr

from app.config import Settings
from app.database import TaskStore
from app.devin_client import AmbiguousCreateError, LiveDevinClient, task_tag
from app.schemas import TaskRecord
from tests.factories import issue_payload


def live_settings() -> Settings:
    return Settings(
        app_mode="live",
        devin_api_key=SecretStr("cog_test"),
        devin_org_id="org-test",
        github_webhook_secret=SecretStr("not-the-demo-secret"),
    )


def create_task(path: Path) -> TaskRecord:
    store = TaskStore(path)
    store.initialize()
    task, _ = store.register("delivery-1", issue_payload())
    return task


@respx.mock
async def test_create_session_sends_bounded_request(tmp_path: Path) -> None:
    route = respx.post("https://api.devin.ai/v3/organizations/org-test/sessions").mock(
        return_value=httpx.Response(
            200,
            json={
                "session_id": "devin-1",
                "url": "https://app.devin.ai/sessions/devin-1",
                "status": "new",
            },
        )
    )
    task = create_task(tmp_path / "tasks.db")
    client = LiveDevinClient(live_settings())
    session = await client.create_session(task)
    request = route.calls.last.request
    body = httpx.Response(200, content=request.content).json()
    assert session.session_id == "devin-1"
    assert body["repos"] == ["samuelczhao/superset"]
    assert body["max_acu_limit"] == 3
    assert body["bypass_approval"] is False
    assert task_tag(task.id) in body["tags"]
    assert "session_secrets" not in body
    await client.aclose()


@respx.mock
async def test_transport_failure_is_ambiguous(tmp_path: Path) -> None:
    respx.post("https://api.devin.ai/v3/organizations/org-test/sessions").mock(
        side_effect=httpx.ReadTimeout("timeout")
    )
    client = LiveDevinClient(live_settings())
    with pytest.raises(AmbiguousCreateError):
        await client.create_session(create_task(tmp_path / "tasks.db"))
    await client.aclose()
