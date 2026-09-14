# Run with the Devin API

Use the [README simulation](../README.md#try-it-locally) first. Live mode can spend credits and
open real PRs. It is not needed to inspect the recorded results.

The supplied configuration targets `samuelczhao/superset` and accepts labels applied by
`samuelczhao`. These name and numeric-ID checks are intentional. For another fork or operator,
change the corresponding [settings](../app/config.py), forward them through
[compose.live.yaml](../compose.live.yaml), and update the repository-specific outcome report.
This is a take-home configured for one fork, not a general-purpose installer.

## Credentials and permissions

1. Give Devin's GitHub integration access only to the target fork. The session's `repos` field
   selects the working repository; it does not restrict the integration's permissions.
2. Keep the target branch protected with a human approval required. The service never merges,
   and the task instructions tell Devin not to merge or deploy.
3. Rotate any token that has appeared in chat or logs before live use.
4. Copy [.env.example](../.env.example) to `.env` and fill in the following values, or supply them
   through your shell's secret manager. `.env` is ignored by Git; do not commit it.

| Variable | Value |
| --- | --- |
| `REMEDIATION_DEVIN_API_KEY` | Your Devin API credential |
| `REMEDIATION_DEVIN_ORG_ID` | Your `org-...` organization ID |
| `REMEDIATION_GITHUB_WEBHOOK_SECRET` | A new random secret, at least 32 bytes |
| `REMEDIATION_CONTROL_PLANE_PASSWORD` | A different random secret, at least 32 bytes |

`openssl rand -hex 32` can generate each random secret. Keep both values private. Live mode rejects
missing credentials, short secrets, and the example placeholders. The default dashboard username
is `operator`. Sessions default to a 3-ACU limit, at most three active sessions, and approvals enabled
(`REMEDIATION_DEVIN_BYPASS_APPROVAL=false`). This is not an aggregate daily spending limit.

For the existing macOS setup, the four values are stored in Keychain under account
`superset-remediation-bot`, with service names `devin-remediation-orchestrator`,
`devin-remediation-orchestrator-org-id`, `devin-remediation-orchestrator-webhook`, and
`devin-remediation-orchestrator-control-plane`. Those entries are local to the owner's machine,
not prerequisites for a fresh setup.

## Start the live service

From the repository root, with the credentials supplied:

```bash
docker compose -f compose.yaml -f compose.live.yaml up --build -d
```

Open [localhost:8000](http://127.0.0.1:8000) and sign in with `operator` and your control-plane
password. The dashboard and `/api/tasks`, `/api/metrics`, and `/api/outcomes` require this login.
Health checks contain no task data and remain public.

The live override uses `/data/live-orchestrator.db`, separate from simulation data. Do not omit
the override when updating an existing live instance: the base Compose file starts simulation.
The README's `devin-demo` project on port 8001 can run alongside this instance.

## Connect the event trigger

Expose port 8000 through an HTTPS tunnel. In the target fork's webhook settings, configure:

- Payload URL: `https://<tunnel-host>/webhooks/github`
- Content type: `application/json`
- Secret: the same `REMEDIATION_GITHUB_WEBHOOK_SECRET`
- SSL verification: enabled
- Events: Issues only

The handler verifies the signature over the raw request body, then checks the repository,
label, and labeling actor. Authentication for the dashboard is separate from webhook signing.

Apply `devin:ready` to a newly scoped issue from the allowed GitHub account. A successful delivery
returns HTTP 202 and the task appears in the dashboard. Applying the label authorizes paid work.
The demonstrated issues have already been processed; relabeling them deliberately does not start
another session. Use the simulation to test replay behavior without spending credits.

Keep the challenge webhook disabled when its tunnel is stopped. Before re-enabling it, check
`/health/ready`, confirm the dashboard says LIVE, and verify that the tunnel reaches this build.
The existing recording uses historical runs and does not need the webhook enabled.

## Refresh review outcomes

The service polls Devin progress, not GitHub reviews. On the operator's machine, install `uv`
and authenticate the GitHub CLI with access to the fork, then run:

```bash
uv run python -m scripts.refresh_outcomes
docker compose -f compose.yaml -f compose.live.yaml up --build -d
```

This replaces `app/evidence/github_outcomes.json` using read-only GitHub requests and loads the
new snapshot into the image. Failed refreshes retain the previous file. To include another PR,
pass the complete set, for example `uv run python -m scripts.refresh_outcomes --prs 4 5 6 8 9`.
GitHub CLI credentials stay on the operator's machine and are not copied into the image.

`app/evidence/review_notes.json` holds separate manual assessments tied to exact PR commits.
A changed head makes an old assessment stale and removes its previous regression-verification
credit. Missing snapshot coverage displays unavailable outcomes rather than an invented zero.
Snapshots older than 24 hours retain their historical values with a visible warning.

## Stop safely

Check for active sessions before stopping the worker. Stopping Docker does not stop a running
Devin session; manage it in Devin if needed. Then:

```bash
docker compose -f compose.yaml -f compose.live.yaml down
```

Do not add `--volumes` unless you intend to delete the local task history.

API references: [Devin session creation](https://docs.devin.ai/api-reference/v3/sessions/post-organizations-sessions),
[session lifecycle](https://docs.devin.ai/api-reference/common-flows), and
[GitHub webhook signing](https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries).
