from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol

import httpx
from pydantic import ValidationError

from app.config import Settings
from app.prompt import build_prompt, canonical_issue_url
from app.schemas import DevinPullRequest, DevinSession, TaskRecord

RESULT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["result", "summary", "tests", "commit_sha", "pr_url", "failure_reason"],
    "properties": {
        "result": {"enum": ["pr_opened", "blocked", "no_change_needed", "failed"]},
        "summary": {"type": "string", "minLength": 1},
        "tests": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["command", "outcome"],
                "properties": {
                    "command": {"type": "string", "minLength": 1},
                    "outcome": {"enum": ["passed", "failed", "not_run"]},
                },
            },
        },
        "commit_sha": {"type": ["string", "null"]},
        "pr_url": {"type": ["string", "null"]},
        "failure_reason": {"type": ["string", "null"]},
    },
    "allOf": [
        {
            "if": {"properties": {"result": {"const": "pr_opened"}}},
            "then": {
                "properties": {
                    "commit_sha": {"type": "string", "pattern": ".*\\S.*"},
                    "pr_url": {"type": "string", "minLength": 1},
                }
            },
            "else": {"properties": {"pr_url": {"type": "null"}}},
        }
    ],
}
SESSION_PAGE_SIZE = 200
MAX_SESSION_LOOKUP_PAGES = 50
CREATED_AFTER_CLOCK_SKEW_SECONDS = 300


class DevinAPIError(RuntimeError):
    pass


class AmbiguousCreateError(DevinAPIError):
    pass


class RateLimitedCreateError(DevinAPIError):
    pass


class DevinClient(Protocol):
    async def create_session(self, task: TaskRecord) -> DevinSession: ...

    async def get_session(self, session_id: str) -> DevinSession: ...

    async def find_session_by_tag(
        self, tag: str, created_after: datetime
    ) -> DevinSession | None: ...

    async def terminate_session(self, session_id: str) -> None: ...

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
        if response.status_code == 429:
            raise RateLimitedCreateError("Devin API rate-limited session creation")
        if response.status_code >= 500:
            raise AmbiguousCreateError("Session creation returned a server error")
        self._raise(response)
        try:
            return _parse_session(_response_json(response))
        except DevinAPIError as error:
            raise AmbiguousCreateError(
                "Session creation returned an invalid success response"
            ) from error

    async def get_session(self, session_id: str) -> DevinSession:
        response = await self._request("GET", f"{self.base_path}/{session_id}")
        return _parse_session(_response_json(response))

    async def find_session_by_tag(self, tag: str, created_after: datetime) -> DevinSession | None:
        cursor: str | None = None
        seen_cursors: set[str] = set()
        match: DevinSession | None = None
        for _ in range(MAX_SESSION_LOOKUP_PAGES):
            page = await self._session_page(cursor, created_after, tag)
            for session in page["sessions"]:
                if tag not in session.tags:
                    continue
                if match:
                    raise DevinAPIError("Multiple Devin sessions have the same remediation tag")
                match = session
            if not page["has_next_page"]:
                return match
            cursor = page["end_cursor"]
            if not cursor or cursor in seen_cursors:
                raise DevinAPIError("Devin session pagination returned an invalid cursor")
            seen_cursors.add(cursor)
        raise DevinAPIError("Devin session lookup exceeded its page limit")

    async def terminate_session(self, session_id: str) -> None:
        await self._request("DELETE", f"{self.base_path}/{session_id}")

    async def aclose(self) -> None:
        await self.http.aclose()

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            response = await self.http.request(method, path, **kwargs)
        except httpx.TransportError as error:
            raise DevinAPIError("Devin API transport failure") from error
        self._raise(response)
        return response

    async def _session_page(
        self, cursor: str | None, created_after: datetime, tag: str
    ) -> dict[str, Any]:
        params: dict[str, int | str] = {
            "first": SESSION_PAGE_SIZE,
            "created_after": max(
                0,
                int(created_after.timestamp()) - CREATED_AFTER_CLOCK_SKEW_SECONDS,
            ),
        }
        if cursor:
            params["after"] = cursor
        response = await self._request("GET", self.base_path, params=params)
        return _parse_session_page(_response_json(response), tag)

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
        stored = self.sessions.get(session_id)
        session, polls = stored if stored else (self._rehydrate(session_id), 0)
        next_session = (
            self._finished(session) if polls else session.model_copy(update={"status": "running"})
        )
        self.sessions[session_id] = (next_session, polls + 1)
        return next_session

    async def find_session_by_tag(self, tag: str, created_after: datetime) -> DevinSession | None:
        del created_after
        return next((session for session, _ in self.sessions.values() if tag in session.tags), None)

    async def terminate_session(self, session_id: str) -> None:
        session, polls = self.sessions[session_id]
        terminated = session.model_copy(update={"status": "exit", "status_detail": None})
        self.sessions[session_id] = (terminated, polls)

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

    def _rehydrate(self, session_id: str) -> DevinSession:
        prefix = "devin-sim-"
        if not session_id.startswith(prefix) or len(session_id) == len(prefix):
            raise DevinAPIError("Simulated session cannot be reconstructed")
        task_id = session_id.removeprefix(prefix)
        return DevinSession(
            session_id=session_id,
            url=f"https://app.devin.ai/sessions/{session_id}",
            status="running",
            tags=[task_tag(task_id)],
        )


def task_tag(task_id: str) -> str:
    return f"remediation-task-{task_id}"


def _response_json(response: httpx.Response) -> object:
    try:
        return response.json()
    except ValueError as error:
        raise DevinAPIError("Devin API returned invalid JSON") from error


def _parse_session(value: object) -> DevinSession:
    try:
        return DevinSession.model_validate(value)
    except ValidationError as error:
        raise DevinAPIError("Devin API returned an invalid session") from error


def _parse_session_page(value: object, target_tag: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not isinstance(value.get("items"), list):
        raise DevinAPIError("Devin API returned an invalid session page")
    sessions = [
        _parse_session(item)
        for item in value["items"]
        if isinstance(item, dict)
        and isinstance(item.get("tags"), list)
        and target_tag in item["tags"]
    ]
    has_next_page = value.get("has_next_page", False)
    end_cursor = value.get("end_cursor")
    if not isinstance(has_next_page, bool):
        raise DevinAPIError("Devin API returned an invalid pagination flag")
    if end_cursor is not None and not isinstance(end_cursor, str):
        raise DevinAPIError("Devin API returned an invalid pagination cursor")
    return {
        "sessions": sessions,
        "has_next_page": has_next_page,
        "end_cursor": end_cursor,
    }
