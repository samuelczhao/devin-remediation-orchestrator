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
