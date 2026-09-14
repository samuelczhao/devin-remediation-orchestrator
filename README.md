# Devin Remediation Control Plane

An event-driven control plane that turns a trusted GitHub issue label into a bounded Devin
coding session, then reconciles the result into a pull request and leadership-facing metrics.
It never merges code.

The challenge target is the public [Superset fork](https://github.com/samuelczhao/superset).
Defects were inspected at fork commit `e7dccd44a7c212739147155548e689e9d6b3408f`.
The selected defects are:

- [#1: database export can silently drop same-named datasets](https://github.com/samuelczhao/superset/issues/1)
- [#2: sync-tags assigns favorite tags the wrong type](https://github.com/samuelczhao/superset/issues/2)
- [#3: dashboard export mutates process-global chart tag state](https://github.com/samuelczhao/superset/issues/3)
- [#7: sync-tags backfill is incompatible with SQLAlchemy 2 and portable SQL](https://github.com/samuelczhao/superset/issues/7),
  opened after independent review showed that the first #2 remediation was incomplete

## Why this workflow

Maintenance backlogs contain valuable fixes that are individually understandable but expensive
to reproduce, implement, test, and shepherd into review. This system leaves prioritization with
the engineering team—the `devin:ready` label is the control point—while Devin owns the bounded
repository work needed to produce a reviewable PR. Reviewer judgment stays outside the agent:
independent review can reject a PR, create a better-scoped follow-up issue, and send that issue
through the same workflow.

```text
GitHub issues.labeled webhook
            |
            v
 HMAC + repo/actor allowlist
            |
            v
 SQLite task/event ledger ---> durable reconciler ---> Devin v3 Sessions API
                                                        |
                                                        v
 dashboard + JSON metrics <---------------------- structured result + PR
```

See [the architecture and acceptance gate](docs/ARCHITECTURE.md) for failure semantics,
idempotency boundaries, and assignment traceability.

The demo produced four PRs from three initial issues and one corrective attempt. One focused
Superset regression has now been [independently executed before and after the fix](verification/pr4/README.md).
No PR is GitHub-approved or merged in the recorded snapshot. Review rejected the first tagging fix;
the replacement still needs work. The dashboard separates these engineering outcomes from agent activity.

## Reading the code

Start with `app/main.py`: it accepts the webhook and serves the dashboard. Then follow:

- `github_webhook.py`: checks the signature, label, repository, and approving actor.
- `database.py`: stores tasks, prevents duplicate work, and calculates metrics.
- `orchestrator.py`: starts Devin, polls progress, and records results.
- `devin_client.py`: contains the live API adapter and deterministic simulation adapter.
- `prompt.py` and `schemas.py`: define the task instructions and validated data shapes.
- `outcomes.py`: joins a read-only GitHub snapshot and commit-specific review notes to task PRs.

The application runs one worker in one process with SQLite. GitHub holds the issues and PRs;
Devin performs the repository work. There is no separate queue server or frontend application.

## Run the complete simulation with Docker

Prerequisite: Docker with Compose.

```bash
docker compose up --build -d
docker compose exec orchestrator /app/.venv/bin/python scripts/simulate_webhook.py
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). The simulator signs a realistic
`issues.labeled` payload and sends it through the production webhook path. The fake Devin adapter
then follows the same persisted session lifecycle as live mode. The default Compose file is fixed
to simulation mode, passes no Devin credentials, and the simulator refuses any server that does
not report `mode=simulation`. Expected terminal evidence:

- task state `completed_with_pr`;
- a target-repository PR URL;
- one Devin-reported passing test;
- PR yield, cycle time, and simulated ACUs in `/api/metrics`.

Simulated sessions and PRs are fixtures, not clickable external artifacts. The Engineering outcomes
panel explicitly withholds real approval, merge, and regression claims in simulation and links to
the separately recorded real-run evidence.

If port 8000 is already in use, bind a different loopback port without changing the container:

```bash
REMEDIATION_HOST_PORT=8001 docker compose up --build -d
```

Run the command again to demonstrate idempotency: `created` becomes `false`, and no second session
is created. After the task is terminal, `docker compose restart` demonstrates that its ledger,
session link, PR link, metrics, and simulated usage survive a process restart. The in-memory fake
adapter is deterministic: if restart occurs while a simulated task is active, it reconstructs
that task's fake remote session from the persisted session ID and continues to terminal state.

```bash
docker compose down
```

The named SQLite volume is preserved. Use `docker compose down --volumes` only when you explicitly
want to delete local demo state.

## Run the checks

The quality target always runs typecheck, tests, then lint:

```bash
uv sync
make quality
```

The suite covers signature verification, realistic ignored GitHub actions, request bounds, stable
repo and actor allowlists, delivery/issue deduplication, paginated ambiguous-create recovery,
malformed-response isolation, active-session restart, Devin lifecycle mapping, strict structured
output/target-PR validation, operator authentication, metrics, HTML escaping, and full simulated
issue-to-PR progression. GitHub Actions runs the same typecheck → tests → lint gate.

## Live mode

Live mode uses the official organization-scoped
[Devin v3 Sessions API](https://docs.devin.ai/api-reference/v3/sessions/post-organizations-sessions)
and its documented [polling lifecycle](https://docs.devin.ai/api-reference/common-flows). Complete
this safety gate before spending ACUs:

1. Rotate any Devin token that has appeared in chat or shell output.
2. Restrict Devin's GitHub installation to `samuelczhao/superset`.
3. Keep `master` branch protection enabled. It currently requires one approval, enforces the rule
   for admins, and blocks force pushes and deletion.
4. Store secrets outside the repository. The application fails closed in live mode when the API
   key, organization ID, non-default webhook secret, or control-plane password is missing.

This project uses macOS Keychain locally:

The live commands below are the runbook for this existing account and fork, not a fresh-account
installer. They assume the Devin token and organization ID have already been stored in Keychain.
On another machine, supply the required `REMEDIATION_` environment variables directly instead.
To use a different fork or approving actor, update the identity settings and forward them through
the Compose override. The default simulation needs neither Keychain nor a Devin account.

```bash
webhook_secret="$(openssl rand -hex 32)"
control_plane_password="$(openssl rand -hex 32)"
security add-generic-password -U \
  -s devin-remediation-orchestrator-webhook \
  -a superset-remediation-bot \
  -w "$webhook_secret"
security add-generic-password -U \
  -s devin-remediation-orchestrator-control-plane \
  -a superset-remediation-bot \
  -w "$control_plane_password"
unset webhook_secret control_plane_password

export REMEDIATION_DEVIN_API_KEY="$(security find-generic-password \
  -s devin-remediation-orchestrator -a superset-remediation-bot -w)"
export REMEDIATION_DEVIN_ORG_ID="$(security find-generic-password \
  -s devin-remediation-orchestrator-org-id -a superset-remediation-bot -w)"
export REMEDIATION_GITHUB_WEBHOOK_SECRET="$(security find-generic-password \
  -s devin-remediation-orchestrator-webhook -a superset-remediation-bot -w)"
export REMEDIATION_CONTROL_PLANE_PASSWORD="$(security find-generic-password \
  -s devin-remediation-orchestrator-control-plane -a superset-remediation-bot -w)"
export REMEDIATION_DEVIN_MAX_ACU_LIMIT=3
export REMEDIATION_MAX_ACTIVE_SESSIONS=3
export REMEDIATION_DEVIN_BYPASS_APPROVAL=false
export REMEDIATION_USAGE_MODEL=self_serve
docker compose -f compose.yaml -f compose.live.yaml up --build -d
```

Expose `http://127.0.0.1:8000` through an HTTPS tunnel and add a repository webhook pointing to
`https://<tunnel-host>/webhooks/github`. Configure JSON content, the same webhook secret, SSL
verification, and only the Issues event. GitHub's
[signature validation guidance](https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries)
is implemented over the raw body.

The challenge webhook is disabled between live demonstrations because its HTTPS tunnel is
ephemeral. Re-establish the tunnel and verify the current hardened container before re-enabling
it. The recorded live deliveries remain in the evidence; simulation exercises the same signed
ingress without creating a paid session.

In live mode, the dashboard and JSON APIs require HTTP Basic authentication with username
`operator` and `REMEDIATION_CONTROL_PLANE_PASSWORD`; API documentation is disabled. Health checks
remain public and contain no task data. The webhook route remains public but requires its
independent HMAC secret.

Trigger a remediation by applying `devin:ready` once to a newly reviewed issue. The demonstrated
issues are already labeled, and the durable `(repository_id, issue_id)` key deliberately prevents
relabeling them from creating another session. The live delivery GUIDs are preserved in
[the evidence](docs/EVIDENCE.md).

Keep approvals enabled unless the Devin installation is repository-limited and an unattended
demo is required. Each request specifies the target fork and a per-session ACU limit. Actual
repository access must be restricted in the Devin GitHub installation; the `repos` field alone
is not an access-control boundary. Sessions are instructed not to merge, and `master` is protected.

## Correctness and recovery guarantees

- SQLite persists the webhook delivery before any Devin API call.
- Delivery ID and `(repository_id, issue_id)` uniqueness prevent retries and relabeling from
  creating another task or paid session for the same issue.
- Session creation is not falsely described as exactly-once: a network timeout can make the
  remote result ambiguous because the API exposes no idempotency key.
- Every session receives a unique task tag. After an ambiguous create, the reconciler searches by
  that tag across cursor-paginated results and never blindly repeats the paid create request.
- An atomic active-session limit bounds concurrent ACU exposure; the human label remains the
  authorization and aggregate-budget gate for this demo.
- HTTP 429 create responses are retried only after a configured backoff. Before retrying, the task
  is durably reclaimed as `creating`, so a crash triggers tag recovery instead of another POST;
  authentication, authorization, and validation failures remain terminal.
- Live queued, creating, running, and attention-required tasks are reconciled after restart.
- Ambiguous creates remain attention-required and repeat tag-only discovery every 30 seconds;
  the paid create request is never repeated.
- The reconciler terminates completed conversational sessions through Devin's official endpoint
  only after validating their structured result and any claimed target PR.
- `exit` is not success. A PR-producing task requires valid structured output and a PR URL for the
  allowlisted fork. Its reported checks can still fail; this is not a correctness or approval gate.
- Waiting, suspended, blocked, API error, invalid-output, and wrong-repository outcomes remain
  distinguishable.
- A malformed response for one task cannot prevent later tasks in the same sweep from progressing.
- Validated terminal evidence is persisted as `session_termination_pending` before the cleanup
  call. Cleanup retries use that saved evidence rather than fetching and overwriting it after
  termination. DELETE requests archive the session; an already-missing session completes cleanup,
  while permission and transient errors retain the evidence and remain attention-required.

Sessionless ambiguous creates count against the active limit on purpose: the service cannot know
whether a paid remote session exists. If the limit fills with unresolved ambiguous tasks, intake
stops as a visible fail-closed circuit breaker. This MVP does not provide an automated “abandon”
button because retrying without a human verifying Devin's session list could duplicate spend.

The Devin API client follows the official
[session status endpoint](https://docs.devin.ai/api-reference/v3/sessions/get-organizations-session).
The GitHub webhook follows GitHub's
[webhook delivery guidance](https://docs.github.com/en/webhooks/using-webhooks/best-practices-for-using-webhooks).

## What engineering leadership can see

The first dashboard panel and `/api/outcomes` show what happened to proposed fixes:

- independently executed, SHA-matched regression evidence, separately from hosted CI;
- GitHub approval, merge, and closed-without-merge counts;
- current-at-snapshot PR and CI status, including unknown or absent checks;
- recorded candidate, rejected, and needs-rework assessments with review evidence;
- snapshot time and a warning after 24 hours. These are manual snapshots, not live GitHub polling.

The lower activity panel and `/api/metrics` show whether the automation is operating:

- accepted, queued, active, attention-required, blocked, and failed task counts;
- PR count and PR yield among terminal tasks;
- median issue-to-terminal cycle time;
- simulated ACUs in demo mode, or enterprise ACUs when configured;
- per-task links to the source issue, Devin session, and PR;
- Devin-reported test counts, session-time PR state, and per-task error detail;
- current worker attempt/healthy timestamps plus stale/error-aware readiness.

PR yield is an output metric, not a success rate. A failed test can accompany a produced PR. The
median time runs from accepted webhook to agent completion, excludes human review, and is not
engineering labor saved. Unknown cost and unmeasured reviewer effort are not presented as zero.

### Refresh the outcome snapshot

From the repository, with an authenticated GitHub CLI that can read the public fork:

```bash
uv run python -m scripts.refresh_outcomes
```

This performs read-only GitHub requests and atomically replaces `app/evidence/github_outcomes.json`.
It does not create Devin sessions or change any PR. Failed refreshes retain the previous snapshot.
Use `--prs 4 5 6 8 9` to include a new task's PR. Rebuild the Docker image with your chosen Compose
configuration to include the refreshed file; use the explicit live override for an existing live
container. GitHub credentials remain on the operator's machine, not in the application image.

`app/evidence/review_notes.json` contains separate, manually recorded review assessments. They count
only while the PR head matches the reviewed commit; a new head makes the assessment stale and
invalidates the previous regression-verification count. A candidate never counts as approved.
Missing snapshot coverage displays unavailable outcomes, while task progress remains visible.

## Observed live result

Four signed issue events produced four target-fork PR artifacts. Independent review found no
take-home blocker in
[PR #4](https://github.com/samuelczhao/superset/pull/4) and
[PR #6](https://github.com/samuelczhao/superset/pull/6), rejected and closed
[PR #5](https://github.com/samuelczhao/superset/pull/5), then used the findings to produce and amend
[PR #8](https://github.com/samuelczhao/superset/pull/8). Later review found that PR #8 still needs
a legacy association migration and an explicit reserved-name collision policy before upstream
merge.
The final dashboard snapshot showed no active or failed tasks and a 617.96-second median cycle
time. This self-serve account returned 0.0 in the API's enterprise ACU field, so the submission
does not infer usage or cost from it; Devin Billing is authoritative. The fork has no GitHub checks
configured, so exact session-reported tests and review limits remain explicit in the evidence.
The live sessions used an earlier control-plane build; current hardening is verified by automated
tests and simulation rather than another paid run. PR #4's regression was independently executed
against both pinned commits using real Superset code and SQLite fixtures: expected failure on the
base, pass on the fix. This is one unit-level acceptance check, not full-suite or merge approval.

## Evidence and presentation

- [Implementation evidence](docs/EVIDENCE.md)
- [SHA-pinned remediation review report](docs/REVIEW_REPORTS.md)
- [Independent PR #4 regression and reproduction instructions](verification/pr4/README.md)
- Loom video supplied separately with the assignment submission
- [Issue #1 technical specification](docs/issues/database-export-dataset-collision.md)
- [Issue #2 technical specification](docs/issues/sync-tags-favorite-type.md)
- [Issue #3 technical specification](docs/issues/dashboard-export-global-tag-state.md)
- [Issue #7 corrective technical specification](docs/issues/sync-tags-sqlalchemy2-portability.md)

## Production extension

The next step is a narrow pilot with a code owner, comparing implementation effort saved against
review, rework, and agent cost. Expand only categories that produce acceptable fixes with a net
reduction in engineering effort. Continuous GitHub review/CI updates and notifications would
replace the manual snapshot. Stronger identity, audit retention, and worker infrastructure should
follow the customer's deployment and scale requirements; one process and SQLite suffice here.
