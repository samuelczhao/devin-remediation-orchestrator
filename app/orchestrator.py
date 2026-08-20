import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from pydantic import ValidationError

from app.config import Settings
from app.database import TaskStore
from app.devin_client import (
    AmbiguousCreateError,
    DevinAPIError,
    DevinClient,
    RateLimitedCreateError,
    task_tag,
)
from app.schemas import DevinResult, DevinSession, TaskRecord, TaskState

logger = logging.getLogger(__name__)
MAX_ERROR_DETAIL = 500


@dataclass(frozen=True)
class SessionObservation:
    state: TaskState
    status: str
    status_detail: str | None
    acus: Decimal
    pr_url: str | None
    pr_state: str | None
    structured_output: dict[str, object] | None
    error_code: str | None = None
    error_detail: str | None = None


class Orchestrator:
    def __init__(self, store: TaskStore, client: DevinClient, settings: Settings) -> None:
        self.store = store
        self.client = client
        self.settings = settings
        self.last_run_at: datetime | None = None
        self.last_successful_run: datetime | None = None
        self.last_error: str | None = None

    async def run_once(self) -> None:
        healthy = True
        self.last_run_at = datetime.now(UTC)
        try:
            for _ in range(self.settings.max_active_sessions):
                task = self.store.claim_queued(self.settings.max_active_sessions)
                if not task:
                    break
                healthy = await self._run_task(task, self._create) and healthy
            for active in self.store.list_active():
                healthy = await self._run_task(active, self._reconcile) and healthy
        except Exception:
            healthy = False
            logger.exception("reconciler_sweep_failed")
        self.last_run_at = datetime.now(UTC)
        if healthy:
            self.last_successful_run = self.last_run_at
            self.last_error = None
        else:
            self.last_error = "reconciliation_errors"

    async def _run_task(
        self,
        task: TaskRecord,
        operation: Callable[[TaskRecord], Awaitable[bool]],
    ) -> bool:
        self.last_run_at = datetime.now(UTC)
        try:
            return await operation(task)
        except Exception:
            logger.exception("task_reconciliation_failed", extra={"task_id": task.id})
            try:
                self.store.record_error(
                    task.id,
                    "unexpected_task_error",
                    "Unexpected task reconciliation error",
                )
            except Exception:
                logger.exception("task_error_record_failed", extra={"task_id": task.id})
            return False

    async def _create(self, task: TaskRecord) -> bool:
        try:
            session = await self.client.create_session(task)
        except AmbiguousCreateError:
            return await self._recover_ambiguous(task)
        except RateLimitedCreateError as error:
            self.store.mark_needs_attention(
                task.id,
                "session_create_rate_limited",
                str(error),
            )
            return False
        except DevinAPIError as error:
            self.store.mark_failed(task.id, "session_create_failed", str(error))
            return True
        else:
            self.store.attach_session(task.id, session.session_id, session.url)
            return True

    async def _recover_ambiguous(self, task: TaskRecord) -> bool:
        try:
            session = await self.client.find_session_by_tag(task_tag(task.id), task.created_at)
        except DevinAPIError as error:
            detail = "Paid create not retried; tagged-session discovery failed"
            if task.state == TaskState.CREATING:
                self.store.mark_create_unknown(task.id, detail)
            else:
                self.store.record_error(task.id, "session_lookup_failed", str(error))
            return False
        if session:
            self.store.attach_session(task.id, session.session_id, session.url)
            return True
        self.store.mark_create_unknown(
            task.id,
            "Creation outcome unknown; paid create not retried; tag discovery will repeat",
        )
        return True

    async def _reconcile(self, task: TaskRecord) -> bool:
        if task.state == TaskState.CREATING:
            return await self._recover_ambiguous(task)
        if self._create_retry_due(task):
            retry = self.store.prepare_create_retry(task.id)
            return await self._create(retry)
        if self._ambiguous_recovery_due(task):
            return await self._recover_ambiguous(task)
        if not task.session_id:
            return True
        try:
            session = await self.client.get_session(task.session_id)
        except DevinAPIError as error:
            self.store.record_error(task.id, "session_poll_failed", str(error))
            return False
        if should_terminate_session(session, self.settings.github_repository):
            observation = _terminal_observation(session, self.settings.github_repository)
            pending = _termination_pending_observation(session, self.settings.github_repository)
            self.store.observe_session(task.id, **pending.__dict__)
            try:
                await self.client.terminate_session(task.session_id)
            except DevinAPIError as error:
                observation = _termination_failure_observation(
                    session,
                    self.settings.github_repository,
                    str(error),
                )
                self.store.observe_session(task.id, **observation.__dict__)
                return False
        else:
            observation = evaluate_session(session, self.settings.github_repository)
        self.store.observe_session(task.id, **observation.__dict__)
        return True

    def _ambiguous_recovery_due(self, task: TaskRecord) -> bool:
        if task.state != TaskState.NEEDS_ATTENTION or task.session_id:
            return False
        if task.error_code not in {"session_create_unknown", "session_lookup_failed"}:
            return False
        elapsed = (datetime.now(UTC) - task.updated_at).total_seconds()
        return elapsed >= self.settings.ambiguous_recovery_interval_seconds

    def _create_retry_due(self, task: TaskRecord) -> bool:
        if task.state != TaskState.NEEDS_ATTENTION or task.session_id:
            return False
        if task.error_code != "session_create_rate_limited":
            return False
        elapsed = (datetime.now(UTC) - task.updated_at).total_seconds()
        return elapsed >= self.settings.create_retry_interval_seconds


def evaluate_session(session: DevinSession, repository: str) -> SessionObservation:
    pr_url, pr_state = _target_pr(session, repository)
    base = _base_observation(session, pr_url, pr_state)
    if session.status == "error" or session.status_detail == "error":
        return _with_error(base, TaskState.FAILED, "devin_error", "Devin reported an error")
    if session.status == "suspended":
        return _with_error(
            base, TaskState.NEEDS_ATTENTION, "devin_suspended", session.status_detail
        )
    if session.status_detail in {"waiting_for_user", "waiting_for_approval"}:
        return _with_error(base, TaskState.NEEDS_ATTENTION, "devin_waiting", session.status_detail)
    result = _terminal_result(session, repository)
    if session.status_detail == "finished":
        if not result:
            return _with_error(
                base,
                TaskState.NEEDS_ATTENTION,
                "invalid_finished_result",
                "Finished session lacks valid output or a target-repository PR",
            )
        return _evaluate_terminal(base, result, pr_url)
    if session.status != "exit":
        return base
    if not result:
        return _with_error(
            base,
            TaskState.FAILED,
            "invalid_structured_output",
            "Missing, contradictory, or invalid terminal result",
        )
    return _evaluate_terminal(base, result, pr_url)


def should_terminate_session(session: DevinSession, repository: str) -> bool:
    if session.status != "running":
        return False
    if session.status_detail not in {"finished", "waiting_for_user"}:
        return False
    return _has_valid_terminal_result(session, repository)


def _has_valid_terminal_result(session: DevinSession, repository: str) -> bool:
    return _terminal_result(session, repository) is not None


def _terminal_result(session: DevinSession, repository: str) -> DevinResult | None:
    try:
        result = DevinResult.model_validate(session.structured_output)
    except ValidationError:
        return None
    pr_url, pr_state = _target_pr(session, repository)
    if result.result == "pr_opened":
        valid_pr = (
            len(session.pull_requests) == 1
            and result.pr_url == pr_url
            and pr_state is not None
            and pr_state.casefold() == "open"
        )
        return result if valid_pr else None
    return result if not session.pull_requests else None


def _evaluate_terminal(
    base: SessionObservation,
    result: DevinResult,
    pr_url: str | None,
) -> SessionObservation:
    if result.result == "pr_opened" and pr_url:
        return _with_state(base, TaskState.COMPLETED_WITH_PR)
    if result.result == "blocked":
        return _with_error(base, TaskState.BLOCKED, "devin_blocked", result.failure_reason)
    if result.result == "no_change_needed":
        return _with_state(base, TaskState.COMPLETED_WITHOUT_PR)
    detail = result.failure_reason or "Terminal session did not produce a target-repository PR"
    return _with_error(base, TaskState.FAILED, "remediation_failed", detail)


def _terminal_observation(session: DevinSession, repository: str) -> SessionObservation:
    terminal = session.model_copy(update={"status": "exit", "status_detail": "finished"})
    return evaluate_session(terminal, repository)


def _termination_failure_observation(
    session: DevinSession,
    repository: str,
    detail: str,
) -> SessionObservation:
    pr_url, pr_state = _target_pr(session, repository)
    base = _base_observation(session, pr_url, pr_state)
    return _with_error(
        base,
        TaskState.NEEDS_ATTENTION,
        "session_terminate_failed",
        detail,
    )


def _termination_pending_observation(
    session: DevinSession,
    repository: str,
) -> SessionObservation:
    pr_url, pr_state = _target_pr(session, repository)
    base = _base_observation(session, pr_url, pr_state)
    return _with_error(
        base,
        TaskState.NEEDS_ATTENTION,
        "session_termination_pending",
        "Validated result persisted; Devin session termination pending",
    )


def _base_observation(
    session: DevinSession,
    pr_url: str | None,
    pr_state: str | None,
) -> SessionObservation:
    output = session.structured_output
    return SessionObservation(
        state=TaskState.RUNNING,
        status=session.status,
        status_detail=session.status_detail,
        acus=session.acus_consumed,
        pr_url=pr_url,
        pr_state=pr_state,
        structured_output=output,
    )


def _target_pr(session: DevinSession, repository: str) -> tuple[str | None, str | None]:
    pattern = re.compile(rf"^https://github\.com/{re.escape(repository)}/pull/[1-9][0-9]*$")
    for pull_request in session.pull_requests:
        if pattern.fullmatch(pull_request.pr_url):
            return pull_request.pr_url, pull_request.pr_state
    return None, None


def _with_state(base: SessionObservation, state: TaskState) -> SessionObservation:
    return SessionObservation(**{**base.__dict__, "state": state})


def _with_error(
    base: SessionObservation,
    state: TaskState,
    code: str,
    detail: str | None,
) -> SessionObservation:
    safe_detail = (detail or code)[:MAX_ERROR_DETAIL]
    return SessionObservation(
        **{**base.__dict__, "state": state, "error_code": code, "error_detail": safe_detail}
    )
