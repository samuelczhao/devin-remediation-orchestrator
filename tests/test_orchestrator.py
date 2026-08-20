from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.database import TaskStore
from app.devin_client import DevinAPIError, FakeDevinClient, RateLimitedCreateError
from app.orchestrator import Orchestrator, evaluate_session, should_terminate_session
from app.schemas import DevinPullRequest, DevinSession, TaskRecord, TaskState
from tests.factories import issue_payload

REPOSITORY = "samuelczhao/superset"
TESTS = [{"command": "pytest targeted.py", "outcome": "passed"}]


def session(**updates: object) -> DevinSession:
    values: dict[str, object] = {
        "session_id": "devin-test",
        "url": "https://app.devin.ai/sessions/devin-test",
        "status": "running",
        "acus_consumed": Decimal("0.5"),
    }
    values.update(updates)
    return DevinSession.model_validate(values)


@pytest.mark.parametrize("status", ["new", "creating", "claimed", "running", "resuming"])
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


@pytest.mark.parametrize(
    "updates",
    [
        {"url": "javascript:alert(1)"},
        {"url": "https://evil.example/sessions/devin-test"},
        {"acus_consumed": Decimal("-0.01")},
    ],
)
def test_session_boundary_rejects_unsafe_links_and_acus(updates: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        session(**updates)


def test_exit_requires_target_repository_pr() -> None:
    result: dict[str, object] = {
        "result": "pr_opened",
        "summary": "done",
        "tests": TESTS,
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
        "tests": TESTS,
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
        "tests": TESTS,
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
            "tests": TESTS,
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
    assert await client.find_session_by_tag("missing", datetime.now(UTC)) is None


@pytest.mark.parametrize(
    ("result_pr", "session_prs"),
    [
        (
            f"https://github.com/{REPOSITORY}/pull/5",
            [DevinPullRequest(pr_url=f"https://github.com/{REPOSITORY}/pull/4", pr_state="open")],
        ),
        (
            f"https://github.com/{REPOSITORY}/pull/4",
            [
                DevinPullRequest(pr_url=f"https://github.com/{REPOSITORY}/pull/4", pr_state="open"),
                DevinPullRequest(pr_url="https://github.com/other/repo/pull/1", pr_state="open"),
            ],
        ),
        (
            f"https://github.com/{REPOSITORY}/pull/4",
            [DevinPullRequest(pr_url=f"https://github.com/{REPOSITORY}/pull/4", pr_state="closed")],
        ),
    ],
)
def test_terminal_result_rejects_pr_contradictions(
    result_pr: str, session_prs: list[DevinPullRequest]
) -> None:
    result = {
        "result": "pr_opened",
        "summary": "Done",
        "tests": TESTS,
        "commit_sha": "abc",
        "pr_url": result_pr,
        "failure_reason": None,
    }
    observation = evaluate_session(
        session(status="exit", structured_output=result, pull_requests=session_prs),
        REPOSITORY,
    )
    assert observation.state == TaskState.FAILED
    assert observation.error_code == "invalid_structured_output"


async def test_fake_client_rehydrates_running_session_after_restart() -> None:
    client = FakeDevinClient(REPOSITORY)
    first = await client.get_session("devin-sim-task-1")
    second = await client.get_session("devin-sim-task-1")
    assert first.status == "running"
    assert second.status == "exit"
    assert second.structured_output is not None


class MalformedFirstClient(FakeDevinClient):
    async def get_session(self, session_id: str) -> DevinSession:
        if session_id == "devin-bad":
            raise ValueError("malformed upstream payload")
        if stored := self.sessions.get(session_id):
            return stored[0]
        return await super().get_session(session_id)


async def test_one_malformed_task_does_not_starve_later_tasks(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "tasks.db")
    store.initialize()
    bad, _ = store.register("delivery-1", issue_payload(issue_id=1, issue_number=1))
    good, _ = store.register("delivery-2", issue_payload(issue_id=2, issue_number=2))
    assert store.claim_queued(max_active_sessions=2) is not None
    store.attach_session(bad.id, "devin-bad", "https://app.devin.ai/sessions/devin-bad")
    assert store.claim_queued(max_active_sessions=2) is not None
    store.attach_session(good.id, "devin-good", "https://app.devin.ai/sessions/devin-good")
    pr_url = f"https://github.com/{REPOSITORY}/pull/4"
    completed = session(
        session_id="devin-good",
        url="https://app.devin.ai/sessions/devin-good",
        status="exit",
        structured_output={
            "result": "pr_opened",
            "summary": "Done",
            "tests": TESTS,
            "commit_sha": "abc",
            "pr_url": pr_url,
            "failure_reason": None,
        },
        pull_requests=[DevinPullRequest(pr_url=pr_url, pr_state="open")],
    )
    client = MalformedFirstClient(REPOSITORY)
    client.sessions["devin-good"] = (completed, 0)

    orchestrator = Orchestrator(store, client, Settings(max_active_sessions=2))
    await orchestrator.run_once()

    bad_result = store.get(bad.id)
    good_result = store.get(good.id)
    assert bad_result is not None and bad_result.error_code == "unexpected_task_error"
    assert good_result is not None and good_result.state == TaskState.COMPLETED_WITH_PR
    assert orchestrator.last_error == "reconciliation_errors"


class FlakyLookupClient(FakeDevinClient):
    def __init__(self, repository: str) -> None:
        super().__init__(repository)
        self.lookup_attempts = 0

    async def find_session_by_tag(self, tag: str, created_after: datetime) -> DevinSession | None:
        self.lookup_attempts += 1
        if self.lookup_attempts == 1:
            raise DevinAPIError("temporary lookup failure")
        return await super().find_session_by_tag(tag, created_after)


async def test_ambiguous_recovery_retries_after_lookup_failure(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "tasks.db")
    store.initialize()
    task, _ = store.register("delivery-1", issue_payload())
    assert store.claim_queued() is not None
    store.mark_create_unknown(task.id, "unknown")
    client = FlakyLookupClient(REPOSITORY)
    recovered = session(tags=[f"remediation-task-{task.id}"])
    client.sessions[recovered.session_id] = (recovered, 0)
    settings = Settings(ambiguous_recovery_interval_seconds=0)
    orchestrator = Orchestrator(store, client, settings)

    await orchestrator.run_once()
    after_failure = store.get(task.id)
    assert after_failure is not None
    assert after_failure.error_code == "session_lookup_failed"

    await orchestrator.run_once()
    after_recovery = store.get(task.id)
    assert after_recovery is not None
    assert after_recovery.state == TaskState.RUNNING
    assert after_recovery.session_id == recovered.session_id
    assert client.lookup_attempts == 2


class FlakyTerminateClient(FakeDevinClient):
    def __init__(self, repository: str) -> None:
        super().__init__(repository)
        self.terminate_attempts = 0

    async def get_session(self, session_id: str) -> DevinSession:
        return self.sessions[session_id][0]

    async def terminate_session(self, session_id: str) -> None:
        self.terminate_attempts += 1
        if self.terminate_attempts == 1:
            raise DevinAPIError("temporary termination failure")
        await super().terminate_session(session_id)


async def test_termination_failure_preserves_result_and_retries(tmp_path: Path) -> None:
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
            "tests": TESTS,
            "commit_sha": "abc",
            "pr_url": pr_url,
            "failure_reason": None,
        },
        pull_requests=[DevinPullRequest(pr_url=pr_url, pr_state="open")],
    )
    client = FlakyTerminateClient(REPOSITORY)
    client.sessions["devin-test"] = (completed, 0)
    orchestrator = Orchestrator(store, client, Settings())

    await orchestrator.run_once()
    pending = store.get(task.id)
    assert pending is not None
    assert pending.state == TaskState.NEEDS_ATTENTION
    assert pending.error_code == "session_terminate_failed"
    assert pending.pr_url == pr_url
    assert pending.structured_output == completed.structured_output

    await orchestrator.run_once()
    terminal = store.get(task.id)
    assert terminal is not None
    assert terminal.state == TaskState.COMPLETED_WITH_PR
    assert client.terminate_attempts == 2


class RateLimitOnceClient(FakeDevinClient):
    def __init__(self, repository: str, store: TaskStore) -> None:
        super().__init__(repository)
        self.store = store
        self.create_attempts = 0

    async def create_session(self, task: TaskRecord) -> DevinSession:
        self.create_attempts += 1
        if self.create_attempts == 1:
            raise RateLimitedCreateError("rate limited")
        persisted = self.store.get(task.id)
        assert persisted is not None and persisted.state == TaskState.CREATING
        return await super().create_session(task)


async def test_rate_limited_create_retries_after_backoff(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "tasks.db")
    store.initialize()
    task, _ = store.register("delivery-1", issue_payload())
    client = RateLimitOnceClient(REPOSITORY, store)

    await Orchestrator(
        store,
        client,
        Settings(create_retry_interval_seconds=3_600),
    ).run_once()
    waiting = store.get(task.id)
    assert waiting is not None
    assert waiting.state == TaskState.NEEDS_ATTENTION
    assert waiting.error_code == "session_create_rate_limited"

    await Orchestrator(
        store,
        client,
        Settings(create_retry_interval_seconds=0),
    ).run_once()
    retried = store.get(task.id)
    assert retried is not None
    assert retried.state == TaskState.RUNNING
    assert client.create_attempts == 2


class CrashAfterAcceptedRetryClient(FakeDevinClient):
    def __init__(self, repository: str) -> None:
        super().__init__(repository)
        self.create_attempts = 0
        self.lookup_attempts = 0

    async def create_session(self, task: TaskRecord) -> DevinSession:
        self.create_attempts += 1
        if self.create_attempts == 1:
            raise RateLimitedCreateError("rate limited")
        await super().create_session(task)
        raise SystemExit("simulated crash after accepted retry")

    async def find_session_by_tag(self, tag: str, created_after: datetime) -> DevinSession | None:
        self.lookup_attempts += 1
        return await super().find_session_by_tag(tag, created_after)


async def test_crash_after_rate_limit_retry_recovers_without_second_post(
    tmp_path: Path,
) -> None:
    store = TaskStore(tmp_path / "tasks.db")
    store.initialize()
    task, _ = store.register("delivery-1", issue_payload())
    client = CrashAfterAcceptedRetryClient(REPOSITORY)
    await Orchestrator(
        store,
        client,
        Settings(create_retry_interval_seconds=3_600),
    ).run_once()

    with pytest.raises(SystemExit, match="accepted retry"):
        await Orchestrator(
            store,
            client,
            Settings(create_retry_interval_seconds=0),
        ).run_once()
    creating = store.get(task.id)
    assert creating is not None and creating.state == TaskState.CREATING

    await Orchestrator(store, client, Settings()).run_once()
    recovered = store.get(task.id)
    assert recovered is not None and recovered.state == TaskState.RUNNING
    assert client.create_attempts == 2
    assert client.lookup_attempts == 1


class CrashOnceTerminateClient(FakeDevinClient):
    def __init__(self, repository: str) -> None:
        super().__init__(repository)
        self.crashed = False

    async def get_session(self, session_id: str) -> DevinSession:
        return self.sessions[session_id][0]

    async def terminate_session(self, session_id: str) -> None:
        if not self.crashed:
            self.crashed = True
            raise SystemExit("simulated process death after remote termination")
        await super().terminate_session(session_id)


async def test_crash_during_termination_preserves_pending_evidence(tmp_path: Path) -> None:
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
            "tests": TESTS,
            "commit_sha": "abc",
            "pr_url": pr_url,
            "failure_reason": None,
        },
        pull_requests=[DevinPullRequest(pr_url=pr_url, pr_state="open")],
    )
    client = CrashOnceTerminateClient(REPOSITORY)
    client.sessions["devin-test"] = (completed, 0)
    orchestrator = Orchestrator(store, client, Settings())

    with pytest.raises(SystemExit, match="simulated process death"):
        await orchestrator.run_once()
    pending = store.get(task.id)
    assert pending is not None
    assert pending.state == TaskState.NEEDS_ATTENTION
    assert pending.error_code == "session_termination_pending"
    assert pending.pr_url == pr_url
    assert pending.structured_output == completed.structured_output

    await orchestrator.run_once()
    terminal = store.get(task.id)
    assert terminal is not None
    assert terminal.state == TaskState.COMPLETED_WITH_PR
