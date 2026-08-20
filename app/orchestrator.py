import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from pydantic import ValidationError

from app.config import Settings
from app.database import TaskStore
from app.devin_client import AmbiguousCreateError, DevinAPIError, DevinClient, task_tag
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
        self.last_successful_run: datetime | None = None
        self.last_error: str | None = None

    async def run_once(self) -> None:
        try:
            task = self.store.claim_queued()
            if task:
                await self._create(task)
            for active in self.store.list_active():
                await self._reconcile(active)
            self.last_successful_run = datetime.now(UTC)
            self.last_error = None
        except Exception:
            self.last_error = "unexpected_reconciler_error"
            logger.exception("reconciler_failed")

    async def _create(self, task: TaskRecord) -> None:
        try:
            session = await self.client.create_session(task)
        except AmbiguousCreateError:
            await self._recover_ambiguous(task)
        except DevinAPIError as error:
            self.store.mark_failed(task.id, "session_create_failed", str(error))
        else:
            self.store.attach_session(task.id, session.session_id, session.url)

    async def _recover_ambiguous(self, task: TaskRecord) -> None:
        try:
            session = await self.client.find_session_by_tag(task_tag(task.id))
        except DevinAPIError:
            session = None
        if session:
            self.store.attach_session(task.id, session.session_id, session.url)
            return
        self.store.mark_create_unknown(task.id, "Creation outcome unknown; no retry attempted")

    async def _reconcile(self, task: TaskRecord) -> None:
        if task.state == TaskState.CREATING:
            await self._recover_ambiguous(task)
            return
        if self._ambiguous_recovery_due(task):
            await self._recover_ambiguous(task)
            return
        if not task.session_id:
            return
        try:
            session = await self.client.get_session(task.session_id)
        except DevinAPIError as error:
            self.store.record_error(task.id, "session_poll_failed", str(error))
            return
        if should_terminate_session(session, self.settings.github_repository):
            try:
                session = await self.client.terminate_session(task.session_id)
            except DevinAPIError as error:
                self.store.record_error(task.id, "session_terminate_failed", str(error))
                return
        observation = evaluate_session(session, self.settings.github_repository)
        self.store.observe_session(task.id, **observation.__dict__)

    def _ambiguous_recovery_due(self, task: TaskRecord) -> bool:
        if task.state != TaskState.NEEDS_ATTENTION or task.session_id:
            return False
        if task.error_code != "session_create_unknown":
            return False
        elapsed = (datetime.now(UTC) - task.updated_at).total_seconds()
        return elapsed >= self.settings.ambiguous_recovery_interval_seconds


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
    if session.status_detail == "finished":
        if not _has_valid_terminal_result(session, repository):
            return _with_error(
                base,
                TaskState.NEEDS_ATTENTION,
                "invalid_finished_result",
                "Finished session lacks valid output or a target-repository PR",
            )
        return _evaluate_terminal(base, session.structured_output, pr_url)
    if session.status != "exit":
        return base
    return _evaluate_terminal(base, session.structured_output, pr_url)


def should_terminate_session(session: DevinSession, repository: str) -> bool:
    if session.status != "running":
        return False
    if session.status_detail not in {"finished", "waiting_for_user"}:
        return False
    return _has_valid_terminal_result(session, repository)


def _has_valid_terminal_result(session: DevinSession, repository: str) -> bool:
    try:
        result = DevinResult.model_validate(session.structured_output)
    except ValidationError:
        return False
    return result.result != "pr_opened" or _target_pr(session, repository)[0] is not None


def _evaluate_terminal(
    base: SessionObservation,
    structured_output: dict[str, object] | None,
    pr_url: str | None,
) -> SessionObservation:
    try:
        result = DevinResult.model_validate(structured_output)
    except ValidationError:
        return _with_error(
            base,
            TaskState.FAILED,
            "invalid_structured_output",
            "Missing or invalid result",
        )
    if result.result == "pr_opened" and pr_url:
        return _with_state(base, TaskState.COMPLETED_WITH_PR)
    if result.result == "blocked":
        return _with_error(base, TaskState.BLOCKED, "devin_blocked", result.failure_reason)
    if result.result == "no_change_needed":
        return _with_state(base, TaskState.COMPLETED_WITHOUT_PR)
    detail = result.failure_reason or "Terminal session did not produce a target-repository PR"
    return _with_error(base, TaskState.FAILED, "remediation_failed", detail)


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
