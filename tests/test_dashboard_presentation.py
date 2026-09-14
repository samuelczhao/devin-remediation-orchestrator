import re
from collections.abc import Iterator
from html.parser import HTMLParser
from pathlib import Path
from typing import Literal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings
from app.devin_client import FakeDevinClient
from app.main import create_app
from app.outcomes import OutcomeReport, load_report
from app.schemas import TaskRecord, TaskState
from tests.test_outcome_dashboard import (
    AUTH,
    live_settings,
    register_proposal,
    use_snapshot_fixture,
)
from tests.test_outcomes import NOW, SHA, evidence, pull_request

VERIFIED_HEAD = "d6394296de8682e5ead171f20b4167bee7b7971c"
CHANGED_HEAD = "b" * 40


class DashboardHTML(HTMLParser):
    def __init__(self, html: str) -> None:
        super().__init__()
        self.details: dict[str, bool] = {}
        self.outside_details: list[str] = []
        self.depth = 0
        self.feed(html)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "details":
            attributes = dict(attrs)
            self.details[attributes.get("class") or ""] = "open" in attributes
            self.depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "details":
            self.depth -= 1

    def handle_data(self, data: str) -> None:
        if not self.depth:
            self.outside_details.append(data)


@pytest.fixture
def live_dashboard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[TestClient, FastAPI]]:
    monkeypatch.setattr("tests.test_outcomes.SHA", VERIFIED_HEAD)
    use_snapshot_fixture(tmp_path, monkeypatch)
    settings = live_settings(tmp_path)
    app = create_app(settings, FakeDevinClient(settings.github_repository))
    with TestClient(app) as client:
        for issue, pr in ((1, 4), (2, 5), (3, 6), (7, 8)):
            register_proposal(app.state.store, issue, pr)
        yield client, app


def test_five_outcome_cards_use_report_summary(
    live_dashboard: tuple[TestClient, FastAPI],
) -> None:
    client, _ = live_dashboard
    response = client.get("/", headers=AUTH)
    assert response.status_code == 200
    summary = client.get("/api/outcomes", headers=AUTH).json()["summary"]
    block = re.search(r'<div class="metrics outcome-metrics">(.*?)</div>', response.text, re.DOTALL)
    assert block
    cards = re.findall(r"<strong>([^<]+)</strong><span>([^<]+)</span>", block.group(1))
    assert cards == [
        (str(summary["regression_verified"]), "Regression verified"),
        (str(summary["approved"]), "GitHub approved"),
        (str(summary["merged"]), "Merged"),
        (str(summary["rejected"]), "Rejected · review notes"),
        (str(summary["needs_rework"]), "Needs rework · review notes"),
    ]
    assert "4 tasks received · 4 PRs produced · 0 active" in response.text
    assert "Manually refreshed, not live" in response.text
    assert "Verification, human review, and merge are separate signals" in response.text


@pytest.mark.parametrize("query", ["", "?presentation=false"])
def test_normal_dashboard_keeps_evidence_and_operations_closed(
    live_dashboard: tuple[TestClient, FastAPI], query: str
) -> None:
    client, _ = live_dashboard
    html = client.get(f"/{query}", headers=AUTH).text
    parsed = DashboardHTML(html)
    assert not parsed.details["panel proposal-details"]
    assert not parsed.details["export-evidence"]
    assert not parsed.details["operational-details"]
    assert "/static/dashboard.js" in html
    assert 'http-equiv="refresh"' not in html


def test_presentation_opens_proof_and_disables_refresh(
    live_dashboard: tuple[TestClient, FastAPI],
) -> None:
    client, _ = live_dashboard
    response = client.get("/?presentation=true", headers=AUTH)
    assert response.status_code == 200
    parsed = DashboardHTML(response.text)
    assert parsed.details["panel proposal-details"]
    assert parsed.details["export-evidence"]
    assert "operational-details" not in parsed.details
    assert "/static/dashboard.js" not in response.text
    assert 'http-equiv="refresh"' not in response.text
    assert "page auto-refresh paused" in response.text
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    ("mode", "head", "review_head", "verified", "show_proof"),
    [
        ("live", VERIFIED_HEAD, VERIFIED_HEAD, True, True),
        ("live", VERIFIED_HEAD, VERIFIED_HEAD, False, False),
        ("live", CHANGED_HEAD, VERIFIED_HEAD, True, False),
        ("live", CHANGED_HEAD, CHANGED_HEAD, True, False),
        ("simulation", VERIFIED_HEAD, VERIFIED_HEAD, True, False),
    ],
)
def test_export_proof_requires_real_verified_original_head(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: Literal["live", "simulation"],
    head: str,
    review_head: str,
    verified: bool,
    show_proof: bool,
) -> None:
    snapshot, notes = evidence(tmp_path, [pull_request(4, headRefOid=head)], verified=verified)
    notes.write_text(notes.read_text().replace(SHA, review_head))

    def fixture_report(tasks: list[TaskRecord], report_mode: str) -> OutcomeReport:
        return load_report(
            tasks, report_mode, snapshot_path=snapshot, review_notes_path=notes, now=NOW
        )

    monkeypatch.setattr("app.main.load_report", fixture_report)
    settings = (
        live_settings(tmp_path)
        if mode == "live"
        else Settings(database_path=tmp_path / "tasks.db", poll_interval_seconds=100)
    )
    app = create_app(settings, FakeDevinClient(settings.github_repository))
    with TestClient(app) as client:
        register_proposal(app.state.store, 1, 4)
        response = client.get("/?presentation=true", headers=AUTH)
    assert response.status_code == 200
    assert ('id="verified-example"' in response.text) is show_proof
    if show_proof:
        assert "skip_id=True" in response.text
        assert "ExportDatasetsCommand._file_name(dataset)" in response.text
        assert "1 failed" in response.text and "1 passed" in response.text
        assert "Same Devin-authored regression, independently executed" in response.text
        assert "not full-suite coverage or merge approval" in response.text
    if mode == "simulation":
        assert "This run uses fixture outputs" in response.text
        assert "GitHub approved" not in response.text


def test_unavailable_outcomes_omit_proof_and_expand_operations(
    live_dashboard: tuple[TestClient, FastAPI], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _ = live_dashboard
    report = OutcomeReport(warning="GitHub snapshot is unavailable.")
    monkeypatch.setattr("app.main.load_report", lambda *_: report)
    html = client.get("/?presentation=true", headers=AUTH).text
    parsed = DashboardHTML(html)
    assert "panel proposal-details" not in parsed.details
    assert "export-evidence" not in parsed.details
    assert parsed.details["operational-details"]
    assert "GitHub snapshot is unavailable." in "".join(parsed.outside_details)


@pytest.mark.parametrize("path", ["/?presentation=true", "/api/outcomes?presentation=true"])
def test_presentation_does_not_bypass_operator_auth(
    live_dashboard: tuple[TestClient, FastAPI], path: str
) -> None:
    client, _ = live_dashboard
    response = client.get(path)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == 'Basic realm="control"'
    assert "Regression verified" not in response.text


@pytest.mark.parametrize(
    ("state", "attention"),
    [
        (TaskState.FAILED, "1 failed · 0 blocked · 0 awaiting input"),
        (TaskState.BLOCKED, "0 failed · 1 blocked · 0 awaiting input"),
        (TaskState.NEEDS_ATTENTION, "0 failed · 0 blocked · 1 awaiting input"),
    ],
)
def test_worker_and_run_errors_remain_visible_with_details_closed(
    live_dashboard: tuple[TestClient, FastAPI],
    state: TaskState,
    attention: str,
) -> None:
    client, app = live_dashboard
    app.state.orchestrator.last_error = "reconciliation_errors"
    task = app.state.store.list_tasks()[0]
    app.state.store.observe_session(
        task.id,
        state=state,
        status="exit",
        status_detail="Agent stopped unexpectedly",
        acus=task.acus_consumed,
        pr_url=task.pr_url,
        pr_state=task.pr_state,
        structured_output=task.structured_output,
    )
    html = client.get("/", headers=AUTH).text
    parsed = DashboardHTML(html)
    visible = "".join(parsed.outside_details)
    assert not parsed.details["operational-details"]
    assert "Worker error: reconciliation_errors" in visible
    assert f"Run attention: {attention}" in visible
    assert "These are session states, separate from PR review" in visible
