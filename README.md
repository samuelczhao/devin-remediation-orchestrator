# Devin Remediation Control Plane

This service takes maintenance issues from GitHub and asks Devin to implement them. A maintainer
adds `devin:ready`, the service starts and tracks a Devin session, and Devin returns a pull request
with its test results. The team decides whether the fix is good enough to merge.

I built it against a [fork of Apache Superset](https://github.com/samuelczhao/superset). The goal
is to take implementation work off the team's backlog without taking away prioritization or review.

## Try it locally

You need Git and Docker with Compose. No Devin account or API key is needed for the simulation.

```bash
git clone https://github.com/samuelczhao/devin-remediation-orchestrator.git
cd devin-remediation-orchestrator
REMEDIATION_HOST_PORT=8001 docker compose -p devin-demo up --build -d
docker compose -p devin-demo exec orchestrator /app/.venv/bin/python scripts/simulate_webhook.py
```

Open the [dashboard at localhost:8001](http://127.0.0.1:8001). Within about 15 seconds, the command
should finish with `state=completed_with_pr`. You'll see one task, one simulated PR, and 1.25
simulated ACUs. The page is marked **SIMULATION**: no real session, PR, or bill is created.

The script sends a signed GitHub event through the same webhook handler used in live mode.
Only the Devin adapter is fake. Real approvals and merges are not shown as simulation results;
the four real runs are documented below.

To check duplicate handling, rerun the simulation command (the last line above). It returns `created: false` and keeps
the original task. To check persistence, restart the service and refresh the dashboard:

```bash
docker compose -p devin-demo restart
```

When finished:

```bash
docker compose -p devin-demo down
```

This keeps the task history. Add `--volumes` only if you want to delete this demo's saved state.
If port 8001 is busy, change `REMEDIATION_HOST_PORT` in the startup command and open that port.
The separate `devin-demo` project leaves an existing live instance on port 8000 alone.

## What happened in the real runs

Three original issues and one follow-up produced four Devin sessions and four PRs. These were
real defects in the fork's upstream base, not bugs planted for the demo. I supplied the issue
scope and suggested repair directions; Devin implemented the changes and wrote regression tests.

| Issue | Devin's PR | Result so far |
| --- | --- | --- |
| [#1: same-named datasets disappear from exports](https://github.com/samuelczhao/superset/issues/1) | [#4](https://github.com/samuelczhao/superset/pull/4) | One regression independently fails on the original code and passes on the fix |
| [#2: favorite tags receive the wrong type](https://github.com/samuelczhao/superset/issues/2) | [#5](https://github.com/samuelczhao/superset/pull/5) | Rejected and closed without merge; findings became issue #7 |
| [#3: dashboard export changes shared chart-tag state](https://github.com/samuelczhao/superset/issues/3) | [#6](https://github.com/samuelczhao/superset/pull/6) | Candidate after code review; tests remain Devin-reported |
| [#7: repair the tagging command more completely](https://github.com/samuelczhao/superset/issues/7) | [#8](https://github.com/samuelczhao/superset/pull/8) | Still needs work on legacy data and reserved-name handling |

The [PR #4 verification report](verification/pr4/README.md) includes commands, logs, and pinned
commits. It runs the same Devin-authored regression against real Superset code and SQLite before
and after the fix. It is one focused check, not the full Superset suite.

The recorded GitHub snapshot has **zero approvals, zero merges, and no CI checks on the fork**.
Four PRs does not mean four resolved bugs. The [full evidence](docs/EVIDENCE.md) and
[review notes](docs/REVIEW_REPORTS.md) include session links and remaining limitations.

## How it works

```text
Maintainer labels an issue: devin:ready
                 |
                 v
Python service verifies the webhook and records the task in SQLite
                 |
                 v
Background worker starts Devin through the API and tracks progress
                 |
                 v
Devin implements the fix, runs tests, and opens a PR
                 |
                 v
Team reviews the PR and decides what merges
```

The service contains no Superset repair logic. Devin does the repository work; the service
handles intake, session limits, progress, and reporting. It's one Python process with SQLite
and a server-rendered dashboard, not a separate frontend and queue service.

GitHub can retry deliveries, so tasks are deduplicated before starting Devin. If a session-create
request times out, the worker searches for that task's session tag instead of blindly starting
another paid run. A valid PR result still needs human review. See [architecture](docs/ARCHITECTURE.md)
for the state model, failure handling, and access boundaries.

## Reading the dashboard

The top panel shows engineering outcomes: independently verified regressions, GitHub approvals,
merges, closed PRs, and fixes needing rework. Review notes are separate from GitHub decisions.
Below that are the operational details: queued and active tasks, failures, PRs produced, session
links, and time to the agent's result.

GitHub outcomes come from a **manually refreshed snapshot**, with its timestamp shown. Missing
checks are not counted as passing, and a changed PR commit invalidates its old review evidence.
To refresh the snapshot, install `uv`, authenticate the GitHub CLI, and run:

```bash
uv run python -m scripts.refresh_outcomes
```

This reads GitHub without changing PRs or starting Devin. Rebuild the container to load the new
snapshot, using the same Compose configuration you started with. The [live-mode guide](docs/LIVE_SETUP.md)
has the exact command. Snapshots older than 24 hours show a warning.

Agent turnaround is not engineering time saved. Reviewer effort and actual cost haven't been
measured here, and the self-serve account's API ACU field is not a reliable billing figure.

## Run the checks and explore the code

With [uv](https://docs.astral.sh/uv/getting-started/installation/) installed:

```bash
uv sync --frozen
make quality
```

This runs strict typechecking, 138 tests, lint, and formatting checks. GitHub Actions runs the
same checks. The [separate Superset verification](verification/pr4/README.md#reproduce) requires
a larger source download and its own environment.

Start with [app/main.py](app/main.py), then follow the flow through
[webhook validation](app/github_webhook.py), [task storage](app/database.py), and
[the worker](app/orchestrator.py). [devin_client.py](app/devin_client.py) contains the API request
and simulation adapter; [outcomes.py](app/outcomes.py) builds the review report.

## Running against Devin

The [live-mode guide](docs/LIVE_SETUP.md) covers credentials, GitHub permissions, webhook setup,
and Docker commands. Live runs can spend credits. The existing challenge webhook is disabled;
the local simulation remains available without it.

The real sessions ran on an earlier version of this service. Later recovery changes are covered
by tests and simulation, not another paid run. This is a single-worker demo, not a multi-replica
production service. In a customer pilot, I'd start with a code owner and measure whether review,
rework, and agent cost leave the team better off before expanding to more issue categories.

The Loom link is supplied separately with the assignment submission.
