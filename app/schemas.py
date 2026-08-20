from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


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


class DevinPullRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    pr_url: str
    pr_state: str


class DevinSession(BaseModel):
    model_config = ConfigDict(extra="ignore")
    session_id: str
    url: str
    status: str
    status_detail: str | None = None
    acus_consumed: Decimal = Decimal("0")
    pull_requests: list[DevinPullRequest] = Field(default_factory=list)
    structured_output: dict[str, Any] | None = None
    tags: list[str] = Field(default_factory=list)


class DevinTestResult(BaseModel):
    command: str
    outcome: Literal["passed", "failed", "not_run"]


class DevinResult(BaseModel):
    result: Literal["pr_opened", "blocked", "no_change_needed", "failed"]
    summary: str
    tests: list[DevinTestResult]
    commit_sha: str | None
    pr_url: str | None
    failure_reason: str | None


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
