import base64
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import SecretStr
from pytest import MonkeyPatch

from app.config import Settings
from app.database import TaskStore
from app.devin_client import FakeDevinClient
from app.main import create_app
from app.outcomes import OutcomeReport, load_report
from app.schemas import TaskRecord, TaskState
from tests.factories import issue_payload
from tests.test_outcomes import NOW, evidence, pull_request

PASSWORD = "p" * 32
AUTH = {"authorization": "Basic " + base64.b64encode(f"operator:{PASSWORD}".encode()).decode()}


def live_settings(tmp_path: Path) -> Settings:
    return Settings(
        app_mode="live",
        database_path=tmp_path / "tasks.db",
        devin_api_key=SecretStr("test-key"),
        devin_org_id="org-test",
        github_webhook_secret=SecretStr("w" * 32),
        control_plane_password=SecretStr(PASSWORD),
        poll_interval_seconds=100,
    )


def register_proposal(store: TaskStore, issue: int, pr: int) -> None:
    task, _ = store.register(str(issue), issue_payload(issue_id=issue, issue_number=issue))
    store.attach_session(task.id, f"test-{issue}", f"https://app.devin.ai/sessions/test-{issue}")
    store.observe_session(
        task.id,
        state=TaskState.COMPLETED_WITH_PR,
        status="exit",
        status_detail="finished",
        acus=Decimal("0"),
        pr_url=f"https://github.com/samuelczhao/superset/pull/{pr}",
        pr_state="open",
        structured_output={"result": "pr_opened"},
    )


def use_snapshot_fixture(
    tmp_path: Path, monkeypatch: MonkeyPatch, *, unknown_review: bool = False
) -> None:
    prs = [pull_request(number, reviewDecision="REVIEW_REQUIRED") for number in (4, 5, 6, 8)]
    prs[1]["state"] = "CLOSED"
    if unknown_review:
        prs[0]["reviewDecision"] = None
    snapshot, notes = evidence(tmp_path, prs, verified=True)

    def fixture_report(tasks: list[TaskRecord], mode: str) -> OutcomeReport:
        return load_report(tasks, mode, snapshot_path=snapshot, review_notes_path=notes, now=NOW)

    monkeypatch.setattr("app.main.load_report", fixture_report)


def test_dashboard_shows_four_outcomes_separately_from_run_completion(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    use_snapshot_fixture(tmp_path, monkeypatch)
    settings = live_settings(tmp_path)
    app = create_app(settings, FakeDevinClient(settings.github_repository))
    with TestClient(app) as client:
        for issue, pr in [(1, 4), (2, 5), (3, 6), (7, 8)]:
            register_proposal(app.state.store, issue, pr)
        response = client.get("/", headers=AUTH)
        report = client.get("/api/outcomes", headers=AUTH).json()
        metrics = client.get("/api/metrics", headers=AUTH).json()

    assert response.status_code == 200
    assert metrics["total"] == metrics["pr_produced"] == 4
    assert [row["number"] for row in report["rows"]] == [4, 5, 6, 8]
    assert report["summary"]["approved"] == report["summary"]["merged"] == 0
    assert report["summary"]["needs_rework"] == report["summary"]["closed_unmerged"] == 1
    assert report["summary"]["regression_verified"] == 1
    assert report["summary"]["ci_no_checks"] == 4
    for pr in [4, 5, 6, 8]:
        assert response.text.count(f">PR #{pr}</a>") == 1
    assert "Manually refreshed, not live" in response.text
    assert "Regression verified" in response.text
    assert "fail before / pass after" in response.text
    assert "closed unmerged" in response.text
    assert "Needs Rework" in response.text
    assert "No checks reported" in response.text
    assert "Tasks received" in response.text


def test_missing_outcomes_do_not_hide_operational_tasks(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    report = OutcomeReport(warning="GitHub snapshot is unavailable.")
    monkeypatch.setattr("app.main.load_report", lambda *_: report)
    settings = live_settings(tmp_path)
    app = create_app(settings, FakeDevinClient(settings.github_repository))
    with TestClient(app) as client:
        register_proposal(app.state.store, 1, 4)
        response = client.get("/", headers=AUTH)
        data = client.get("/api/outcomes", headers=AUTH).json()
    assert response.status_code == 200
    assert data["summary"] is None
    assert "GitHub snapshot is unavailable" in response.text
    assert "GitHub approved" not in response.text
    assert "Pull request" in response.text


def test_review_notes_are_escaped_in_outcome_table(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    settings = live_settings(tmp_path)
    app = create_app(settings, FakeDevinClient(settings.github_repository))
    with TestClient(app) as client:
        register_proposal(app.state.store, 1, 4)
        snapshot, notes = evidence(tmp_path, verified=True)
        report = load_report(
            app.state.store.list_tasks(),
            "live",
            snapshot_path=snapshot,
            review_notes_path=notes,
            now=NOW,
        )
        report.rows[0].review_note = "<script>untrusted()</script>"
        monkeypatch.setattr("app.main.load_report", lambda *_: report)
        response = client.get("/", headers=AUTH)
    assert "<script>untrusted()</script>" not in response.text
    assert "&lt;script&gt;untrusted()&lt;/script&gt;" in response.text


def test_unknown_approval_is_not_rendered_as_zero(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    use_snapshot_fixture(tmp_path, monkeypatch, unknown_review=True)
    settings = live_settings(tmp_path)
    app = create_app(settings, FakeDevinClient(settings.github_repository))
    with TestClient(app) as client:
        register_proposal(app.state.store, 1, 4)
        html = client.get("/", headers=AUTH).text
    assert "<strong>Unknown</strong><span>GitHub approved</span>" in html
