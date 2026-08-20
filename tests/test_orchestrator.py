from decimal import Decimal
from pathlib import Path

import pytest

from app.config import Settings
from app.database import TaskStore
from app.devin_client import FakeDevinClient
from app.orchestrator import Orchestrator, evaluate_session, should_terminate_session
from app.schemas import DevinPullRequest, DevinSession, TaskState
from tests.factories import issue_payload

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


def test_finished_session_evaluates_terminal_result() -> None:
    result: dict[str, object] = {
        "result": "no_change_needed",
        "summary": "Already fixed",
        "tests": [],
        "commit_sha": None,
        "pr_url": None,
        "failure_reason": None,
    }
    observation = evaluate_session(
        session(status_detail="finished", structured_output=result), REPOSITORY
    )
    assert observation.state == TaskState.COMPLETED_WITHOUT_PR


def test_finished_session_with_invalid_result_needs_attention() -> None:
    finished = session(status_detail="finished", structured_output=None)
    observation = evaluate_session(finished, REPOSITORY)
    assert observation.state == TaskState.NEEDS_ATTENTION
    assert observation.error_code == "invalid_finished_result"
    assert should_terminate_session(finished, REPOSITORY) is False


def test_waiting_session_with_target_pr_is_ready_to_terminate() -> None:
    pr_url = f"https://github.com/{REPOSITORY}/pull/4"
    result: dict[str, object] = {
        "result": "pr_opened",
        "summary": "Done",
        "tests": [],
        "commit_sha": "abc",
        "pr_url": pr_url,
        "failure_reason": None,
    }
    waiting = session(
        status_detail="waiting_for_user",
        structured_output=result,
        pull_requests=[DevinPullRequest(pr_url=pr_url, pr_state="open")],
    )
    assert should_terminate_session(waiting, REPOSITORY) is True


def test_working_session_is_not_terminated_early() -> None:
    working = session(status_detail="working", structured_output={"result": "pr_opened"})
    assert should_terminate_session(working, REPOSITORY) is False


async def test_reconciler_terminates_completed_waiting_session(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "tasks.db")
    store.initialize()
    task, _ = store.register("delivery-1", issue_payload())
    assert store.claim_queued() is not None
    store.attach_session(task.id, "devin-test", "https://app.devin.ai/sessions/devin-test")
    pr_url = f"https://github.com/{REPOSITORY}/pull/4"
    completed = session(
        status_detail="waiting_for_user",
        structured_output={
            "result": "pr_opened",
            "summary": "Done",
            "tests": [],
            "commit_sha": "abc",
            "pr_url": pr_url,
            "failure_reason": None,
        },
        pull_requests=[DevinPullRequest(pr_url=pr_url, pr_state="open")],
    )
    client = FakeDevinClient(REPOSITORY)
    client.sessions["devin-test"] = (completed, 0)
    await Orchestrator(store, client, Settings()).run_once()
    updated = store.get(task.id)
    assert updated is not None
    assert updated.state == TaskState.COMPLETED_WITH_PR


async def test_reconciler_recovers_ambiguous_create_after_lookup_lag(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "tasks.db"
    store = TaskStore(database_path)
    store.initialize()
    task, _ = store.register("delivery-1", issue_payload())
    assert store.claim_queued() is not None
    store.mark_create_unknown(task.id, "Initial tag lookup missed the session")
    settings = Settings(ambiguous_recovery_interval_seconds=0)
    client = FakeDevinClient(REPOSITORY)
    recovered = session(tags=[f"remediation-task-{task.id}"])
    client.sessions[recovered.session_id] = (recovered, 0)
    restarted_store = TaskStore(database_path)
    restarted_store.initialize()

    await Orchestrator(restarted_store, client, settings).run_once()

    updated = restarted_store.get(task.id)
    assert updated is not None
    assert updated.state == TaskState.RUNNING
    assert updated.session_id == recovered.session_id


async def test_fake_client_progresses_to_target_pr() -> None:
    client = FakeDevinClient(REPOSITORY)
    assert await client.find_session_by_tag("missing") is None
