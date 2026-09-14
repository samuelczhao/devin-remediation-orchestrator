"""Refresh the four public PRs without changing GitHub or starting agent work."""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from app.outcomes import PR_NUMBERS, REPOSITORY, SNAPSHOT_PATH, PullRequest, Snapshot

FIELDS = "number,url,state,headRefOid,mergedAt,reviewDecision,statusCheckRollup,updatedAt"
REQUEST_TIMEOUT_SECONDS = 30


def refresh(destination: Path = SNAPSHOT_PATH, numbers: Sequence[int] = PR_NUMBERS) -> None:
    if not numbers or len(set(numbers)) != len(numbers) or any(number <= 0 for number in numbers):
        raise ValueError("PR numbers must be positive and unique")
    pull_requests = []
    for number in numbers:
        response = subprocess.run(
            ["gh", "pr", "view", str(number), "--repo", REPOSITORY, "--json", FIELDS],
            capture_output=True,
            text=True,
            check=True,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        pr = PullRequest.model_validate_json(response.stdout)
        if pr.number != number:
            raise ValueError("GitHub returned a different pull request")
        pull_requests.append(pr)
    snapshot = Snapshot(checked_at=datetime.now(UTC), pull_requests=pull_requests)
    _atomic_write(destination, snapshot.model_dump_json(indent=2) + "\n")


def _atomic_write(destination: Path, content: str) -> None:
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=destination.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prs", nargs="+", type=int, default=list(PR_NUMBERS))
    numbers: list[int] = parser.parse_args().prs
    try:
        refresh(numbers=numbers)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(
            f"Snapshot refresh failed ({type(error).__name__}); old snapshot retained.",
            file=sys.stderr,
        )
        return 1
    print(json.dumps({"snapshot": str(SNAPSHOT_PATH), "pull_requests": len(numbers)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
