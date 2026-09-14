import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.outcomes import Check, OutcomeReport, ci_status, load_report, pr_url
from app.schemas import TaskRecord, TaskState
from scripts import refresh_outcomes

NOW = datetime(2026, 9, 13, 12, tzinfo=UTC)
SHA = "a" * 40
SOURCE = (
    "https://github.com/samuelczhao/devin-remediation-orchestrator/blob/main/docs/REVIEW_REPORTS.md"
)


def pull_request(number: int = 4, **updates: object) -> dict[str, object]:
    return {
        "number": number,
        "url": pr_url(number),
        "state": "OPEN",
        "headRefOid": SHA,
        "mergedAt": None,
        "reviewDecision": "",
        "statusCheckRollup": [],
        "updatedAt": (NOW - timedelta(days=7)).isoformat(),
        **updates,
    }


def task(number: int = 4) -> TaskRecord:
    return TaskRecord(
        id=f"task-{number}",
        delivery_id=f"delivery-{number}",
        repository_id=1,
        repository="samuelczhao/superset",
        issue_id=number,
        issue_number=number,
        issue_title="Export regression",
        issue_body="",
        actor="samuelczhao",
        state=TaskState.COMPLETED_WITH_PR,
        pr_url=pr_url(number),
        session_url="https://app.devin.ai/sessions/example",
        created_at=NOW,
        updated_at=NOW,
    )


def evidence(
    tmp_path: Path,
    prs: list[dict[str, object]] | None = None,
    checked_at: datetime = NOW,
    verified: bool = False,
) -> tuple[Path, Path]:
    snapshot, reviews = tmp_path / "snapshot.json", tmp_path / "reviews.json"
    snapshot.write_text(
        json.dumps(
            {
                "checked_at": checked_at.isoformat(),
                "pull_requests": prs
                if prs is not None
                else [pull_request(n) for n in (4, 5, 6, 8)],
            }
        )
    )
    reviews.write_text(
        json.dumps(
            {
                "source": SOURCE,
                "notes": [
                    {
                        "pr_url": pr_url(n),
                        "head_sha": SHA,
                        "disposition": disposition,
                        "note": "Pinned review",
                        "independent_verification_url": (
                            "https://github.com/samuelczhao/devin-remediation-orchestrator/blob/f6933d143ed65477795d0e3eff3307e2e6842095/verification/pr4/README.md"
                            if n == 4 and verified
                            else None
                        ),
                    }
                    for n, disposition in (
                        (4, "candidate"),
                        (5, "rejected"),
                        (6, "candidate"),
                        (8, "needs_rework"),
                    )
                ],
            }
        )
    )
    return snapshot, reviews


def report(paths: tuple[Path, Path], tasks: list[TaskRecord] | None = None) -> OutcomeReport:
    return load_report(
        tasks if tasks is not None else [task()],
        "live",
        snapshot_path=paths[0],
        review_notes_path=paths[1],
        now=NOW,
    )


def test_only_matching_tasks_count_and_candidate_is_not_approval(tmp_path: Path) -> None:
    result = report(evidence(tmp_path))
    assert result.available and not result.stale and result.summary
    assert result.summary.tracked_prs == result.summary.candidates == result.summary.open == 1
    assert result.summary.approved == result.summary.merged == result.summary.rejected == 0
    assert result.rows[0].issue_title == "Export regression"
    assert result.rows[0].issue_number == 4
    assert result.rows[0].session_url == task().session_url
    assert result.rows[0].review_source == SOURCE


def test_approved_merged_and_closed_unmerged_are_separate(tmp_path: Path) -> None:
    prs = [
        pull_request(4, reviewDecision="APPROVED"),
        pull_request(5, state="CLOSED"),
        pull_request(6, state="MERGED", mergedAt=(NOW - timedelta(days=1)).isoformat()),
        pull_request(8),
    ]
    result = report(evidence(tmp_path, prs), [task(n) for n in (4, 5, 6, 8)])
    assert result.summary
    assert result.summary.approved == result.summary.merged == result.summary.closed_unmerged == 1
    assert result.summary.candidates == 2
    assert result.summary.rejected == result.summary.needs_rework == 1
    assert result.rows[0].github_state == "open"
    assert result.rows[1].github_state == "closed_unmerged"


@pytest.mark.parametrize("mode", ["simulation", "unknown"])
def test_simulation_never_reads_live_evidence(tmp_path: Path, mode: str) -> None:
    snapshot, reviews = evidence(tmp_path)
    result = load_report([task()], mode, snapshot_path=snapshot, review_notes_path=reviews, now=NOW)
    assert not result.available and result.summary is None
    assert result.rows == [] and result.checked_at is None and result.stale is None


@pytest.mark.parametrize(
    "damage", ["missing", "invalid_json", "wrong_repo", "missing_field", "duplicate"]
)
def test_bad_snapshot_is_unavailable_not_zero(tmp_path: Path, damage: str) -> None:
    paths = evidence(tmp_path)
    if damage == "missing":
        paths[0].unlink()
    elif damage == "invalid_json":
        paths[0].write_text("{")
    else:
        prs = [pull_request(n) for n in (4, 5, 6, 8)]
        if damage == "wrong_repo":
            prs[0]["url"] = "https://github.com/other/repo/pull/4"
        elif damage == "missing_field":
            del prs[0]["statusCheckRollup"]
        else:
            prs[0] = pull_request(5)
        paths = evidence(tmp_path, prs)
    result = report(paths)
    assert not result.available and result.warning and result.summary is None and not result.rows


def test_stale_snapshot_remains_explicitly_timestamped(tmp_path: Path) -> None:
    checked = NOW - timedelta(hours=25)
    result = report(evidence(tmp_path, checked_at=checked))
    assert result.available and result.stale and result.checked_at == checked
    assert result.warning and "24 hours" in result.warning


@pytest.mark.parametrize(
    "checked", [NOW + timedelta(minutes=1), NOW - timedelta(days=30), NOW.replace(tzinfo=None)]
)
def test_invalid_timestamps_are_unavailable(tmp_path: Path, checked: datetime) -> None:
    assert not report(evidence(tmp_path, checked_at=checked)).available


def test_head_change_invalidates_pinned_review(tmp_path: Path) -> None:
    prs = [pull_request(4, headRefOid="b" * 40), *[pull_request(n) for n in (5, 6, 8)]]
    result = report(evidence(tmp_path, prs))
    assert result.summary and result.summary.candidates == 0 and result.summary.stale_reviews == 1
    assert result.rows[0].review_disposition == "stale" and result.rows[0].review_note is None


@pytest.mark.parametrize(("head", "count"), [(SHA, 1), ("b" * 40, 0)])
def test_independent_verification_requires_matching_head(
    tmp_path: Path, head: str, count: int
) -> None:
    prs = [pull_request(4, headRefOid=head), *[pull_request(n) for n in (5, 6, 8)]]
    result = report(evidence(tmp_path, prs, verified=True))
    assert result.summary and result.summary.regression_verified == count
    assert bool(result.rows[0].independent_verification_url) == bool(count)
    assert result.summary.approved == result.summary.ci_passed == 0


def test_agent_reported_tests_do_not_count_as_independent_verification(tmp_path: Path) -> None:
    item = task()
    item.structured_output = {"tests": [{"command": "pytest", "outcome": "passed"}]}
    result = report(evidence(tmp_path), [item])
    assert result.summary and result.summary.regression_verified == 0


def test_unrelated_link_is_not_independent_verification(tmp_path: Path) -> None:
    paths = evidence(tmp_path, verified=True)
    paths[1].write_text(
        paths[1].read_text().replace("verification/pr4/README.md", "docs/EVIDENCE.md")
    )
    assert not report(paths).available


def test_no_tasks_or_uncovered_task_are_unavailable(tmp_path: Path) -> None:
    paths = evidence(tmp_path)
    for tasks in ([], [task(999)]):
        result = report(paths, tasks)
        assert not result.available and result.summary is None and result.rows == []


def test_new_task_pr_can_be_refreshed_without_a_review_note(tmp_path: Path) -> None:
    result = report(evidence(tmp_path, [pull_request(9)]), [task(9)])
    assert result.available and result.summary and result.summary.tracked_prs == 1
    assert result.rows[0].number == 9 and result.rows[0].review_disposition == "unreviewed"
    assert result.rows[0].review_source is None and result.summary.candidates == 0


@pytest.mark.parametrize("numbers", [[], [4, 4], [0], [-1]])
def test_refresh_rejects_invalid_pr_selection(tmp_path: Path, numbers: list[int]) -> None:
    with pytest.raises(ValueError, match="positive and unique"):
        refresh_outcomes.refresh(tmp_path / "snapshot.json", numbers)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize(
    ("checks", "expected"),
    [
        (None, "unknown"),
        ([], "no_checks"),
        ([{}], "unknown"),
        ([{"status": "COMPLETED", "conclusion": "SUCCESS"}], "passed"),
        ([{"status": "COMPLETED", "conclusion": "FAILURE"}], "failed"),
        ([{"status": "COMPLETED", "conclusion": "SKIPPED"}], "unknown"),
        ([{"status": "IN_PROGRESS"}], "pending"),
        ([{"state": "PENDING"}], "pending"),
        ([{"state": "SUCCESS"}], "passed"),
        ([{"state": "ERROR"}], "failed"),
        ([{"state": "SUCCESS"}, {"state": "PENDING"}], "pending"),
        ([{"state": "SUCCESS"}, {}], "unknown"),
        ([{"state": "PENDING"}, {"state": "FAILURE"}], "failed"),
    ],
)
def test_check_statuses(checks: list[dict[str, str]] | None, expected: str) -> None:
    parsed = [Check.model_validate(check) for check in checks] if checks is not None else None
    assert ci_status(parsed) == expected


def test_unknown_review_and_checks_are_not_known_zero(tmp_path: Path) -> None:
    prs = [pull_request(4, reviewDecision=None, statusCheckRollup=None)]
    result = report(evidence(tmp_path, prs + [pull_request(n) for n in (5, 6, 8)]))
    assert result.rows[0].github_review == "unknown"
    assert result.summary and result.summary.ci_unknown == 1 and result.summary.ci_passed == 0
    assert result.summary.approved is None


def test_unknown_review_only_invalidates_approval_total_when_included(tmp_path: Path) -> None:
    paths = evidence(
        tmp_path,
        [
            pull_request(4, reviewDecision=None),
            pull_request(6, reviewDecision="APPROVED"),
        ],
    )
    mixed = report(paths, [task(4), task(6)])
    assert mixed.summary and mixed.summary.approved is None
    known_only = report(paths, [task(6)])
    assert known_only.summary and known_only.summary.approved == 1


def test_refresh_replaces_snapshot_only_after_all_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "snapshot.json"
    destination.write_text("old snapshot")
    calls: list[int] = []

    def run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert args[:3] == ["gh", "pr", "view"] and kwargs["check"] is True
        assert destination.read_text() == "old snapshot"
        number = int(args[3])
        calls.append(number)
        return subprocess.CompletedProcess(args, 0, json.dumps(pull_request(number)))

    monkeypatch.setattr(subprocess, "run", run)
    refresh_outcomes.refresh(destination)
    assert calls == [4, 5, 6, 8]
    assert json.loads(destination.read_text())["checked_at"].endswith("Z")


def test_partial_refresh_failure_retains_previous_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "snapshot.json"
    destination.write_text("old snapshot")

    def run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if args[3] == "5":
            raise subprocess.CalledProcessError(1, args, stderr="private diagnostic")
        return subprocess.CompletedProcess(args, 0, json.dumps(pull_request(4)))

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(subprocess.CalledProcessError):
        refresh_outcomes.refresh(destination)
    assert destination.read_text() == "old snapshot"


def test_failed_atomic_replace_preserves_previous_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "snapshot.json"
    destination.write_text("old snapshot")

    def fail_replace(self: Path, target: Path) -> Path:
        raise OSError("read-only directory")

    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(OSError):
        refresh_outcomes._atomic_write(destination, "new snapshot")
    assert destination.read_text() == "old snapshot"
    assert list(tmp_path.iterdir()) == [destination]
