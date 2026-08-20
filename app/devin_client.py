from collections.abc import Sequence
from decimal import Decimal
from typing import Any, Protocol

import httpx

from app.config import Settings
from app.prompt import build_prompt, canonical_issue_url
from app.schemas import DevinPullRequest, DevinSession, TaskRecord

RESULT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["result", "summary", "tests", "commit_sha", "pr_url", "failure_reason"],
    "properties": {
        "result": {"enum": ["pr_opened", "blocked", "no_change_needed", "failed"]},
        "summary": {"type": "string"},
        "tests": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["command", "outcome"],
                "properties": {
                    "command": {"type": "string"},
                    "outcome": {"enum": ["passed", "failed", "not_run"]},
                },
            },
        },
        "commit_sha": {"type": ["string", "null"]},
        "pr_url": {"type": ["string", "null"]},
        "failure_reason": {"type": ["string", "null"]},
    },
}


class DevinAPIError(RuntimeError):
    pass


class AmbiguousCreateError(DevinAPIError):
    pass


class DevinClient(Protocol):
    async def create_session(self, task: TaskRecord) -> DevinSession: ...

    async def get_session(self, session_id: str) -> DevinSession: ...

    async def find_session_by_tag(self, tag: str) -> DevinSession | None: ...

    async def terminate_session(self, session_id: str) -> DevinSession: ...

    async def aclose(self) -> None: ...


class LiveDevinClient:
    def __init__(self, settings: Settings) -> None:
        if not settings.devin_api_key or not settings.devin_org_id:
            raise ValueError("Live Devin credentials are required")
        self.settings = settings
        self.base_path = f"/v3/organizations/{settings.devin_org_id}/sessions"
        self.http = httpx.AsyncClient(
            base_url="https://api.devin.ai",
            headers={
                "Authorization": f"Bearer {settings.devin_api_key.get_secret_value()}",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(30),
        )

    async def create_session(self, task: TaskRecord) -> DevinSession:
        try:
            response = await self.http.post(self.base_path, json=self._create_payload(task))
        except httpx.TransportError as error:
            raise AmbiguousCreateError("Session creation outcome is unknown") from error
        if response.status_code >= 500:
            raise AmbiguousCreateError("Session creation returned a server error")
        self._raise(response)
        return DevinSession.model_validate(response.json())

    async def get_session(self, session_id: str) -> DevinSession:
        response = await self.http.get(f"{self.base_path}/{session_id}")
        self._raise(response)
        return DevinSession.model_validate(response.json())

    async def find_session_by_tag(self, tag: str) -> DevinSession | None:
        response = await self.http.get(self.base_path, params={"first": 100})
        self._raise(response)
        sessions = _parse_sessions(response.json().get("items", []))
        return next((session for session in sessions if tag in session.tags), None)

    async def terminate_session(self, session_id: str) -> DevinSession:
        response = await self.http.delete(f"{self.base_path}/{session_id}")
        self._raise(response)
        return DevinSession.model_validate(response.json())

    async def aclose(self) -> None:
        await self.http.aclose()

    def _create_payload(self, task: TaskRecord) -> dict[str, Any]:
        tag = task_tag(task.id)
        return {
            "prompt": build_prompt(task, self.settings),
            "title": f"Superset remediation #{task.issue_number} [{task.id}]",
            "repos": [self.settings.github_repository],
            "session_links": [canonical_issue_url(self.settings, task.issue_number)],
            "max_acu_limit": self.settings.devin_max_acu_limit,
            "resumable": True,
            "bypass_approval": self.settings.devin_bypass_approval,
            "structured_output_required": True,
            "structured_output_schema": RESULT_SCHEMA,
            "tags": ["superset-remediation", tag, f"github-issue-{task.issue_number}"],
        }

    @staticmethod
    def _raise(response: httpx.Response) -> None:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            raise DevinAPIError(f"Devin API returned HTTP {response.status_code}") from error


class FakeDevinClient:
    def __init__(self, repository: str) -> None:
        self.repository = repository
        self.sessions: dict[str, tuple[DevinSession, int]] = {}

    async def create_session(self, task: TaskRecord) -> DevinSession:
        session_id = f"devin-sim-{task.id}"
        session = DevinSession(
            session_id=session_id,
            url=f"https://app.devin.ai/sessions/{session_id}",
            status="new",
            tags=[task_tag(task.id)],
        )
        self.sessions[session_id] = (session, 0)
        return session

    async def get_session(self, session_id: str) -> DevinSession:
        session, polls = self.sessions[session_id]
        next_session = (
            self._finished(session)
            if polls
            else session.model_copy(update={"status": "running"})
        )
        self.sessions[session_id] = (next_session, polls + 1)
        return next_session

    async def find_session_by_tag(self, tag: str) -> DevinSession | None:
        return next(
            (session for session, _ in self.sessions.values() if tag in session.tags), None
        )

    async def terminate_session(self, session_id: str) -> DevinSession:
        session, polls = self.sessions[session_id]
        terminated = session.model_copy(update={"status": "exit", "status_detail": None})
        self.sessions[session_id] = (terminated, polls)
        return terminated

    async def aclose(self) -> None:
        return None

    def _finished(self, session: DevinSession) -> DevinSession:
        pr_url = f"https://github.com/{self.repository}/pull/999"
        result = {
            "result": "pr_opened",
            "summary": "Simulated remediation completed.",
            "tests": [{"command": "pytest targeted_test.py", "outcome": "passed"}],
            "commit_sha": "simulated",
            "pr_url": pr_url,
            "failure_reason": None,
        }
        return session.model_copy(
            update={
                "status": "exit",
                "status_detail": "finished",
                "acus_consumed": Decimal("1.25"),
                "pull_requests": [DevinPullRequest(pr_url=pr_url, pr_state="open")],
                "structured_output": result,
            }
        )


def task_tag(task_id: str) -> str:
    return f"remediation-task-{task_id}"


def _parse_sessions(items: Sequence[object]) -> list[DevinSession]:
    return [DevinSession.model_validate(item) for item in items]
