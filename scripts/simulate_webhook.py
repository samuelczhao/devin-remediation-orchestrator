#!/usr/bin/env python3
import hashlib
import hmac
import json
import os
import time
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8000")
WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET", "local-demo-secret")
POLL_SECONDS = 0.25
TIMEOUT_SECONDS = 15
TERMINAL_STATES = {
    "blocked",
    "completed_with_pr",
    "completed_without_pr",
    "failed",
}


def payload() -> dict[str, object]:
    return {
        "action": "labeled",
        "issue": {
            "id": 9_000_000_001,
            "number": 1,
            "title": "Database export can silently drop same-named datasets",
            "body": "Reproduce the collision, delegate to the canonical exporter, and test it.",
        },
        "label": {"name": "devin:ready"},
        "repository": {"id": 1_340_946_845, "full_name": "samuelczhao/superset"},
        "sender": {"id": 30_126_000, "login": "samuelczhao"},
    }


def request_json(path: str, *, body: bytes | None = None) -> Any:
    headers = {"accept": "application/json"}
    if body is not None:
        digest = hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
        headers.update(
            {
                "content-type": "application/json",
                "x-github-event": "issues",
                "x-github-delivery": str(uuid4()),
                "x-hub-signature-256": f"sha256={digest}",
            }
        )
    request = Request(
        f"{BASE_URL}{path}", data=body, headers=headers, method="POST" if body else "GET"
    )
    try:
        with urlopen(request, timeout=5) as response:
            return json.load(response)
    except HTTPError as error:
        detail = error.read().decode()
        raise RuntimeError(f"HTTP {error.code}: {detail}") from error


def wait_for_terminal(task_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        tasks = request_json("/api/tasks")
        task = next(item for item in tasks if item["id"] == task_id)
        print(f"state={task['state']} acus={task['acus_consumed']}")
        if task["state"] in TERMINAL_STATES:
            return task
        time.sleep(POLL_SECONDS)
    raise TimeoutError(f"Task {task_id} did not finish within {TIMEOUT_SECONDS}s")


def main() -> None:
    raw = json.dumps(payload(), separators=(",", ":")).encode()
    accepted = request_json("/webhooks/github", body=raw)
    print(json.dumps(accepted, indent=2))
    task = wait_for_terminal(accepted["task_id"])
    metrics = request_json("/api/metrics")
    print(json.dumps({"task": task, "metrics": metrics}, indent=2))


if __name__ == "__main__":
    main()
