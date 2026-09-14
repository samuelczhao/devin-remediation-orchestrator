import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, BaseModel, Field, model_validator

from app.schemas import TaskRecord

REPOSITORY = "samuelczhao/superset"
PR_NUMBERS = (4, 5, 6, 8)
EVIDENCE_DIR = Path(__file__).parent / "evidence"
SNAPSHOT_PATH = EVIDENCE_DIR / "github_outcomes.json"
REVIEW_PATH = EVIDENCE_DIR / "review_notes.json"
MAX_SNAPSHOT_AGE = timedelta(hours=24)
CIStatus = Literal["no_checks", "pending", "passed", "failed", "unknown"]
ReviewDisposition = Literal["candidate", "rejected", "needs_rework", "stale", "unreviewed"]
GitHubState = Literal["open", "merged", "closed_unmerged"]
GitHubReview = Literal["approved", "changes_requested", "review_required", "none", "unknown"]
GITHUB_STATES: dict[str, GitHubState] = {
    "OPEN": "open",
    "CLOSED": "closed_unmerged",
    "MERGED": "merged",
}
GITHUB_REVIEWS: dict[str | None, GitHubReview] = {
    "APPROVED": "approved",
    "CHANGES_REQUESTED": "changes_requested",
    "REVIEW_REQUIRED": "review_required",
    "": "none",
    None: "unknown",
}


class Check(BaseModel):
    status: str | None = None
    conclusion: str | None = None
    state: str | None = None


class PullRequest(BaseModel):
    number: int = Field(gt=0, strict=True)
    url: str
    state: Literal["OPEN", "CLOSED", "MERGED"]
    headRefOid: str = Field(pattern=r"^[0-9a-f]{40}$")
    mergedAt: AwareDatetime | None
    reviewDecision: Literal["APPROVED", "CHANGES_REQUESTED", "REVIEW_REQUIRED", ""] | None
    statusCheckRollup: list[Check] | None
    updatedAt: AwareDatetime

    @model_validator(mode="after")
    def validate_identity(self) -> "PullRequest":
        if self.url != pr_url(self.number):
            raise ValueError("Unexpected pull request identity")
        if (self.state == "MERGED") != (self.mergedAt is not None):
            raise ValueError("Inconsistent merge state")
        return self


class Snapshot(BaseModel):
    checked_at: AwareDatetime
    pull_requests: list[PullRequest] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_coverage(self) -> "Snapshot":
        numbers = [pr.number for pr in self.pull_requests]
        if len(set(numbers)) != len(numbers):
            raise ValueError("Snapshot contains duplicate pull requests")
        self.checked_at = self.checked_at.astimezone(UTC)
        if any(pr.updatedAt > self.checked_at for pr in self.pull_requests):
            raise ValueError("Snapshot timestamp precedes its GitHub observations")
        return self


class ReviewNote(BaseModel):
    pr_url: str = Field(pattern=r"^https://github\.com/samuelczhao/superset/pull/[1-9][0-9]*$")
    head_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    disposition: Literal["candidate", "rejected", "needs_rework"]
    note: str = Field(min_length=1)
    independent_verification_url: str | None = None


class ReviewNotes(BaseModel):
    source: str = Field(pattern=r"^https://github\.com/samuelczhao/")
    notes: list[ReviewNote]

    @model_validator(mode="after")
    def validate_identity(self) -> "ReviewNotes":
        urls = [note.pr_url for note in self.notes]
        if len(set(urls)) != len(urls):
            raise ValueError("Duplicate review identity")
        for note in self.notes:
            if note.independent_verification_url:
                number = note.pr_url.rsplit("/", 1)[-1]
                expected = (
                    r"https://github\.com/samuelczhao/devin-remediation-orchestrator/"
                    rf"blob/[0-9a-f]{{40}}/verification/pr{number}/README\.md"
                )
                if not re.fullmatch(expected, note.independent_verification_url):
                    raise ValueError("Verification link must pin the PR-specific evidence commit")
        return self


class OutcomeRow(BaseModel):
    issue_number: int
    issue_title: str
    session_url: str | None
    pr_url: str
    number: int
    head_sha: str
    github_state: GitHubState
    github_review: GitHubReview
    ci_status: CIStatus
    review_disposition: ReviewDisposition
    review_note: str | None
    review_source: str | None
    independent_verification_url: str | None = None


class OutcomeSummary(BaseModel):
    tracked_prs: int
    open: int
    approved: int | None
    merged: int
    closed_unmerged: int
    ci_passed: int
    ci_failed: int
    ci_pending: int
    ci_no_checks: int
    ci_unknown: int
    candidates: int
    rejected: int
    needs_rework: int
    stale_reviews: int
    regression_verified: int


class OutcomeReport(BaseModel):
    available: bool = False
    checked_at: datetime | None = None
    stale: bool | None = None
    warning: str | None = None
    summary: OutcomeSummary | None = None
    rows: list[OutcomeRow] = Field(default_factory=list)


def pr_url(number: int) -> str:
    return f"https://github.com/{REPOSITORY}/pull/{number}"


def ci_status(checks: list[Check] | None) -> CIStatus:
    if checks is None:
        return "unknown"
    if not checks:
        return "no_checks"
    results = {_check_status(check) for check in checks}
    precedence: tuple[CIStatus, ...] = ("failed", "pending", "unknown", "passed")
    for outcome in precedence:
        if outcome in results:
            return outcome
    return "unknown"


def _check_status(check: Check) -> CIStatus:
    value = check.conclusion if check.status == "COMPLETED" else check.state
    if value in {"FAILURE", "ERROR", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED", "STALE"}:
        return "failed"
    if check.status in {"QUEUED", "IN_PROGRESS", "WAITING", "PENDING", "REQUESTED"} or (
        value in {"PENDING", "EXPECTED"}
    ):
        return "pending"
    return "passed" if value == "SUCCESS" else "unknown"


def load_report(
    tasks: list[TaskRecord],
    mode: str,
    *,
    snapshot_path: Path = SNAPSHOT_PATH,
    review_notes_path: Path = REVIEW_PATH,
    now: datetime | None = None,
) -> OutcomeReport:
    if mode != "live":
        return OutcomeReport(warning="Live GitHub outcomes are not shown in simulation.")
    urls = {task.pr_url for task in tasks if task.pr_url}
    if not urls:
        return OutcomeReport(warning="No task PRs are available for GitHub outcome matching.")
    observed_now = now or datetime.now(UTC)
    try:
        snapshot = Snapshot.model_validate_json(snapshot_path.read_text())
        reviews = ReviewNotes.model_validate_json(review_notes_path.read_text())
        if observed_now.tzinfo is None or snapshot.checked_at > observed_now:
            raise ValueError("Invalid snapshot timestamp")
    except (OSError, ValueError):
        return OutcomeReport(warning="GitHub outcome snapshot or review notes are unavailable.")
    if not urls.issubset({pr.url for pr in snapshot.pull_requests}):
        return OutcomeReport(
            warning="GitHub snapshot does not cover all task PRs; refresh required."
        )
    task_by_url = {task.pr_url: task for task in tasks if task.pr_url}
    rows = [
        _row(pr, reviews, task_by_url[pr.url]) for pr in snapshot.pull_requests if pr.url in urls
    ]
    stale = observed_now - snapshot.checked_at > MAX_SNAPSHOT_AGE
    return OutcomeReport(
        available=True,
        checked_at=snapshot.checked_at,
        stale=stale,
        warning="Snapshot is over 24 hours old; refresh before relying on it." if stale else None,
        rows=rows,
        summary=_summary(rows),
    )


def _row(pr: PullRequest, reviews: ReviewNotes, task: TaskRecord) -> OutcomeRow:
    note = next((note for note in reviews.notes if note.pr_url == pr.url), None)
    disposition: ReviewDisposition = "unreviewed"
    if note:
        disposition = note.disposition if note.head_sha == pr.headRefOid else "stale"
    return OutcomeRow(
        issue_number=task.issue_number,
        issue_title=task.issue_title,
        session_url=task.session_url,
        pr_url=pr.url,
        number=pr.number,
        head_sha=pr.headRefOid,
        github_state=GITHUB_STATES[pr.state],
        github_review=GITHUB_REVIEWS[pr.reviewDecision],
        ci_status=ci_status(pr.statusCheckRollup),
        review_disposition=disposition,
        review_note=note.note if note and disposition != "stale" else None,
        review_source=reviews.source if note else None,
        independent_verification_url=(
            note.independent_verification_url if note and disposition != "stale" else None
        ),
    )


def _summary(rows: list[OutcomeRow]) -> OutcomeSummary:
    return OutcomeSummary(
        tracked_prs=len(rows),
        open=sum(row.github_state == "open" for row in rows),
        approved=(
            None
            if any(row.github_review == "unknown" for row in rows)
            else sum(row.github_review == "approved" for row in rows)
        ),
        merged=sum(row.github_state == "merged" for row in rows),
        closed_unmerged=sum(row.github_state == "closed_unmerged" for row in rows),
        ci_passed=sum(row.ci_status == "passed" for row in rows),
        ci_failed=sum(row.ci_status == "failed" for row in rows),
        ci_pending=sum(row.ci_status == "pending" for row in rows),
        ci_no_checks=sum(row.ci_status == "no_checks" for row in rows),
        ci_unknown=sum(row.ci_status == "unknown" for row in rows),
        candidates=sum(row.review_disposition == "candidate" for row in rows),
        rejected=sum(row.review_disposition == "rejected" for row in rows),
        needs_rework=sum(row.review_disposition == "needs_rework" for row in rows),
        stale_reviews=sum(row.review_disposition == "stale" for row in rows),
        regression_verified=sum(row.independent_verification_url is not None for row in rows),
    )
