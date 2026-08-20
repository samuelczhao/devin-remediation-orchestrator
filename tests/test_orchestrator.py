from decimal import Decimal

import pytest

from app.devin_client import FakeDevinClient
from app.orchestrator import evaluate_session
from app.schemas import DevinPullRequest, DevinSession, TaskState

REPOSITORY = "samuelczhao/superset"


def session(**updates: object) -> DevinSession:
    values: dict[str, object] = {
        "session_id": "devin-test",
        "url": "https://app.devin.ai/sessions/devin-test",
        "status": "running",
        "acus_consumed": Decimal("0.5"),
    }
    values.update(updates)
    return DevinSession.model_validate(values)


@pytest.mark.parametrize("status", ["new", "claimed", "running", "resuming"])
def test_active_statuses_remain_running(status: str) -> None:
    assert evaluate_session(session(status=status), REPOSITORY).state == TaskState.RUNNING


@pytest.mark.parametrize("detail", ["waiting_for_user", "waiting_for_approval"])
def test_waiting_statuses_need_attention(detail: str) -> None:
    observation = evaluate_session(session(status_detail=detail), REPOSITORY)
    assert observation.state == TaskState.NEEDS_ATTENTION


def test_exit_requires_valid_structured_output() -> None:
    observation = evaluate_session(session(status="exit"), REPOSITORY)
    assert observation.state == TaskState.FAILED
    assert observation.error_code == "invalid_structured_output"


def test_exit_requires_target_repository_pr() -> None:
    result: dict[str, object] = {
        "result": "pr_opened",
        "summary": "done",
        "tests": [],
        "commit_sha": "abc",
        "pr_url": "https://github.com/other/repo/pull/1",
        "failure_reason": None,
    }
    observation = evaluate_session(
        session(
            status="exit",
            structured_output=result,
            pull_requests=[
                DevinPullRequest(pr_url="https://github.com/other/repo/pull/1", pr_state="open")
            ],
        ),
        REPOSITORY,
    )
    assert observation.state == TaskState.FAILED


async def test_fake_client_progresses_to_target_pr() -> None:
    client = FakeDevinClient(REPOSITORY)
    assert await client.find_session_by_tag("missing") is None
