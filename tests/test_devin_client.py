from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx
from pydantic import SecretStr

from app.config import Settings
from app.database import TaskStore
from app.devin_client import (
    RESULT_SCHEMA,
    AmbiguousCreateError,
    DevinAPIError,
    LiveDevinClient,
    RateLimitedCreateError,
    task_tag,
)
from app.schemas import TaskRecord
from tests.factories import issue_payload


def live_settings() -> Settings:
    return Settings(
        app_mode="live",
        devin_api_key=SecretStr("cog_test"),
        devin_org_id="org-test",
        github_webhook_secret=SecretStr("w" * 32),
        control_plane_password=SecretStr("p" * 32),
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


@respx.mock
async def test_create_rate_limit_is_retryable(tmp_path: Path) -> None:
    respx.post("https://api.devin.ai/v3/organizations/org-test/sessions").mock(
        return_value=httpx.Response(429, json={"detail": "slow down"})
    )
    client = LiveDevinClient(live_settings())
    with pytest.raises(RateLimitedCreateError):
        await client.create_session(create_task(tmp_path / "tasks.db"))
    await client.aclose()


@respx.mock
async def test_terminate_session_uses_organization_endpoint() -> None:
    route = respx.delete("https://api.devin.ai/v3/organizations/org-test/sessions/devin-1").mock(
        return_value=httpx.Response(
            200,
            json={
                "session_id": "devin-1",
                "url": "https://app.devin.ai/sessions/devin-1",
                "status": "exit",
            },
        )
    )
    client = LiveDevinClient(live_settings())
    await client.terminate_session("devin-1")
    assert route.called
    await client.aclose()


@respx.mock
async def test_get_transport_failure_is_a_recoverable_api_error() -> None:
    respx.get("https://api.devin.ai/v3/organizations/org-test/sessions/devin-1").mock(
        side_effect=httpx.ReadError("connection dropped")
    )
    client = LiveDevinClient(live_settings())
    with pytest.raises(DevinAPIError, match="transport failure"):
        await client.get_session("devin-1")
    await client.aclose()


@respx.mock
async def test_invalid_create_success_response_is_ambiguous(tmp_path: Path) -> None:
    respx.post("https://api.devin.ai/v3/organizations/org-test/sessions").mock(
        return_value=httpx.Response(200, text="not-json")
    )
    client = LiveDevinClient(live_settings())
    with pytest.raises(AmbiguousCreateError, match="invalid success response"):
        await client.create_session(create_task(tmp_path / "tasks.db"))
    await client.aclose()


@respx.mock
async def test_invalid_get_response_is_recoverable() -> None:
    respx.get("https://api.devin.ai/v3/organizations/org-test/sessions/devin-1").mock(
        return_value=httpx.Response(200, json={"session_id": "devin-1"})
    )
    client = LiveDevinClient(live_settings())
    with pytest.raises(DevinAPIError, match="invalid session"):
        await client.get_session("devin-1")
    await client.aclose()


@respx.mock
async def test_tag_lookup_follows_cursor_pagination() -> None:
    route = respx.get("https://api.devin.ai/v3/organizations/org-test/sessions").mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "session_id": "unrelated",
                            "url": "javascript:alert(1)",
                            "status": "future-status",
                            "tags": ["other-tag"],
                        }
                    ],
                    "has_next_page": True,
                    "end_cursor": "page-2",
                },
            ),
            httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "session_id": "devin-2",
                            "url": "https://app.devin.ai/sessions/devin-2",
                            "status": "running",
                            "tags": ["target-tag"],
                        }
                    ],
                    "has_next_page": False,
                    "end_cursor": None,
                },
            ),
        ]
    )
    client = LiveDevinClient(live_settings())
    found = await client.find_session_by_tag("target-tag", datetime.now(UTC))
    assert found is not None
    assert found.session_id == "devin-2"
    assert route.call_count == 2
    assert route.calls[1].request.url.params["after"] == "page-2"
    await client.aclose()


def test_advertised_result_schema_matches_local_minimums() -> None:
    properties = RESULT_SCHEMA["properties"]
    assert properties["summary"]["minLength"] == 1
    assert properties["tests"]["minItems"] == 1
    assert properties["tests"]["items"]["properties"]["command"]["minLength"] == 1
    assert RESULT_SCHEMA["allOf"]
