from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class TaskState(StrEnum):
    QUEUED = "queued"
    CREATING = "creating"
    RUNNING = "running"
    NEEDS_ATTENTION = "needs_attention"
    BLOCKED = "blocked"
    COMPLETED_WITH_PR = "completed_with_pr"
    COMPLETED_WITHOUT_PR = "completed_without_pr"
    FAILED = "failed"


class GitHubActor(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: int
    login: str


class GitHubLabel(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str


class GitHubIssue(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: int
    number: int = Field(gt=0)
    title: str
    body: str | None = None
    pull_request: dict[str, Any] | None = None


class GitHubRepository(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: int
    full_name: str


class IssueLabeledPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")
    action: str
    issue: GitHubIssue
    label: GitHubLabel
    repository: GitHubRepository
    sender: GitHubActor


class GitHubIssueEventEnvelope(BaseModel):
    model_config = ConfigDict(extra="ignore")
    action: str


class DevinPullRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    pr_url: str
    pr_state: str = Field(min_length=1)


class DevinSession(BaseModel):
    model_config = ConfigDict(extra="ignore")
    session_id: str
    url: str
    status: Literal[
        "new",
        "creating",
        "claimed",
        "running",
        "exit",
        "error",
        "suspended",
        "resuming",
    ]
    status_detail: str | None = None
    acus_consumed: Decimal = Field(default=Decimal("0"), ge=0, allow_inf_nan=False)
    pull_requests: list[DevinPullRequest] = Field(default_factory=list)
    structured_output: dict[str, Any] | None = None
    tags: list[str] = Field(default_factory=list)

    @field_validator("url")
    @classmethod
    def validate_session_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        valid_path = parsed.path.startswith("/sessions/") and len(parsed.path) > len("/sessions/")
        if (
            parsed.scheme != "https"
            or parsed.hostname != "app.devin.ai"
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or not valid_path
        ):
            raise ValueError("Session URL must be an app.devin.ai HTTPS session link")
        return value


class DevinTestResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command: str = Field(min_length=1)
    outcome: Literal["passed", "failed", "not_run"]


class DevinResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    result: Literal["pr_opened", "blocked", "no_change_needed", "failed"]
    summary: str = Field(min_length=1)
    tests: list[DevinTestResult] = Field(min_length=1)
    commit_sha: str | None
    pr_url: str | None
    failure_reason: str | None

    @model_validator(mode="after")
    def validate_result_consistency(self) -> "DevinResult":
        if self.result == "pr_opened":
            if not self.pr_url or not self.commit_sha or not self.commit_sha.strip():
                raise ValueError("pr_opened requires a PR URL and non-empty commit SHA")
        elif self.pr_url is not None:
            raise ValueError("Only pr_opened may report a PR URL")
        return self


class TaskRecord(BaseModel):
    id: str
    delivery_id: str
    repository_id: int
    repository: str
    issue_id: int
    issue_number: int
    issue_title: str
    issue_body: str
    actor: str
    state: TaskState
    session_id: str | None = None
    session_url: str | None = None
    pr_url: str | None = None
    pr_state: str | None = None
    acus_consumed: Decimal = Decimal("0")
    devin_status: str | None = None
    devin_status_detail: str | None = None
    structured_output: dict[str, Any] | None = None
    error_code: str | None = None
    error_detail: str | None = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


class TaskMetrics(BaseModel):
    total: int
    queued: int
    active: int
    needs_attention: int
    blocked: int
    failed: int
    pr_produced: int
    terminal: int
    pr_yield: Decimal
    total_acus: Decimal
    median_cycle_seconds: Decimal | None
