import pytest

from scripts import simulate_webhook


def test_simulator_refuses_live_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        simulate_webhook,
        "request_json",
        lambda _path: {"status": "ready", "mode": "live"},
    )

    with pytest.raises(RuntimeError, match="non-simulation"):
        simulate_webhook.require_simulation_mode()


def test_simulator_accepts_ready_simulation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        simulate_webhook,
        "request_json",
        lambda _path: {"status": "ready", "mode": "simulation"},
    )

    simulate_webhook.require_simulation_mode()


@pytest.mark.parametrize("state", ["failed", "blocked", "completed_without_pr"])
def test_simulator_rejects_non_pr_terminal_state(state: str) -> None:
    with pytest.raises(RuntimeError, match="not completed_with_pr"):
        simulate_webhook.validate_success(
            {"state": state},
            {"pr_produced": 0, "failed": int(state == "failed")},
        )


def test_simulator_rejects_success_without_passing_test() -> None:
    task = {
        "state": "completed_with_pr",
        "pr_url": "https://github.com/samuelczhao/superset/pull/999",
        "structured_output": {"result": "pr_opened", "tests": []},
    }
    with pytest.raises(RuntimeError, match="passing test"):
        simulate_webhook.validate_success(task, {"pr_produced": 1, "failed": 0})
