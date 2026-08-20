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
- PR yield, cycle time, and cumulative ACUs in `/api/metrics`.

Run the command again to demonstrate idempotency: `created` becomes `false`, and no second session
is created. After the task is terminal, `docker compose restart` demonstrates that its ledger,
session link, PR link, metrics, and ACUs survive a process restart. The in-memory fake adapter is
not intended to reconstruct an active simulated session across restart.

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

The suite covers signature verification, request bounds, stable repo and actor allowlists,
delivery/issue deduplication, ambiguous create recovery, Devin lifecycle mapping, structured
output validation, target-PR validation, metrics, HTML escaping, and full simulated issue-to-PR
progression.

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
   key, organization ID, or non-default webhook secret is missing.

This project uses macOS Keychain locally:

```bash
webhook_secret="$(openssl rand -hex 32)"
security add-generic-password -U \
  -s devin-remediation-orchestrator-webhook \
  -a superset-remediation-bot \
  -w "$webhook_secret"
unset webhook_secret

export DEVIN_API_KEY="$(security find-generic-password \
  -s devin-remediation-orchestrator -a superset-remediation-bot -w)"
export DEVIN_ORG_ID="$(security find-generic-password \
  -s devin-remediation-orchestrator-org-id -a superset-remediation-bot -w)"
export GITHUB_WEBHOOK_SECRET="$(security find-generic-password \
  -s devin-remediation-orchestrator-webhook -a superset-remediation-bot -w)"
export DEVIN_MAX_ACU_LIMIT=3
export DEVIN_BYPASS_APPROVAL=false
docker compose -f compose.yaml -f compose.live.yaml up --build -d
```

Expose `http://127.0.0.1:8000` through an HTTPS tunnel and add a repository webhook pointing to
`https://<tunnel-host>/webhooks/github`. Configure JSON content, the same webhook secret, SSL
verification, and only the Issues event. GitHub's
[signature validation guidance](https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries)
is implemented over the raw body.

Trigger a remediation by applying `devin:ready` once to a newly reviewed issue. The demonstrated
issues are already labeled, and the durable `(repository_id, issue_id)` key deliberately prevents
relabeling them from creating another session. The live delivery GUIDs are preserved in
[the evidence](docs/EVIDENCE.md).

Keep approvals enabled unless the Devin installation is repository-limited and an unattended
demo is required. Even with approval bypass enabled, sessions are ACU-capped, limited to one
repository, instructed not to merge, and constrained by protected `master`.

## Correctness and recovery guarantees

- SQLite persists the webhook delivery before any Devin API call.
- Delivery ID and `(repository_id, issue_id)` uniqueness prevent duplicate ACU spend.
- Session creation is not falsely described as exactly-once: a network timeout can make the
  remote result ambiguous because the API exposes no idempotency key.
- Every session receives a unique task tag. After an ambiguous create, the reconciler searches by
  that tag and never blindly repeats the paid create request.
- Live queued, creating, running, and attention-required tasks are reconciled after restart.
- Ambiguous creates remain attention-required and repeat tag-only discovery every 30 seconds;
  the paid create request is never repeated.
- The reconciler terminates completed conversational sessions through Devin's official endpoint
  only after validating their structured result and any claimed target PR.
- `exit` is not success. A successful task requires valid structured output and a PR URL for the
  allowlisted fork.
- Waiting, suspended, blocked, API error, invalid-output, and wrong-repository outcomes remain
  distinguishable.

The Devin API client follows the official
[session status endpoint](https://docs.devin.ai/api-reference/v3/sessions/get-organizations-session).
The GitHub webhook follows GitHub's
[webhook delivery guidance](https://docs.github.com/en/webhooks/using-webhooks/best-practices-for-using-webhooks).

## What engineering leadership can see

The dashboard and `/api/metrics` answer whether the workflow is operating:

- accepted, queued, active, attention-required, blocked, and failed task counts;
- PR count and PR yield among terminal tasks;
- median issue-to-terminal cycle time;
- cumulative ACUs;
- per-task links to the source issue, Devin session, and PR;
- worker health plus safe error/status fields.

PR yield is intentionally not labeled “success rate.” Devin-reported test commands are agent
claims until confirmed by the PR's CI and reviewer inspection. The submission reports observed
results from a small live sample rather than generalized productivity claims.

## Observed live result

Four signed issue events produced four target-fork PR artifacts. Independent review accepted
[PR #4](https://github.com/samuelczhao/superset/pull/4) and
[PR #6](https://github.com/samuelczhao/superset/pull/6), rejected and closed
[PR #5](https://github.com/samuelczhao/superset/pull/5), then accepted its corrected replacement
[PR #8](https://github.com/samuelczhao/superset/pull/8) after a second review-driven amendment.
The final dashboard snapshot showed no active or failed tasks, 617.96-second median cycle time,
and 0.0 cumulative ACUs as reported by the Devin API. The fork has no GitHub checks configured,
so exact session-reported tests and independent review limits remain explicit in the evidence.

## Evidence and presentation

- [Implementation evidence](docs/EVIDENCE.md)
- [Five-minute Loom runbook](docs/LOOM_SCRIPT.md)
- [Issue #1 technical specification](docs/issues/database-export-dataset-collision.md)
- [Issue #2 technical specification](docs/issues/sync-tags-favorite-type.md)
- [Issue #3 technical specification](docs/issues/dashboard-export-global-tag-state.md)
- [Issue #7 corrective technical specification](docs/issues/sync-tags-sqlalchemy2-portability.md)

## Production extension

The demo intentionally uses one process and SQLite. A customer rollout would add Postgres,
lease-based workers, SSO/RBAC, GitHub App identity, alerts and SLOs, CI/reviewer outcome ingestion,
policy templates by repository, and a shadow-mode phase before expanding beyond low-risk
maintenance work.
