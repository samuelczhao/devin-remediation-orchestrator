# Architecture and acceptance gate

## Outcome

This system turns a trusted GitHub issue label into a bounded Devin remediation session,
then reconciles the session into a pull request and leadership-facing operational metrics.
It never merges code.

```text
GitHub issue labeled devin:ready
               |
               v
signed webhook ingress -----> SQLite delivery/task/event ledger
                                      |
                                      v
                              durable reconciler
                                      |
                                      v
                         Devin v3 organization API
                                      |
                                      v
                    pull request + dashboard + JSON metrics
```

## Requirement traceability

| Assignment requirement | Implementation | Completion evidence |
| --- | --- | --- |
| Fork Apache Superset | Public `samuelczhao/superset` fork pinned to the inspected commit | Fork URL and commit SHA in README |
| Identify issues | Two reproducible defects with bounded acceptance criteria | Public issues in the fork |
| Event trigger | `issues.labeled` webhook for `devin:ready` | GitHub delivery plus persisted delivery ID |
| Initiate Devin | `POST /v3/organizations/{org_id}/sessions` | Session ID and link |
| Manage Devin | Durable polling and explicit blocked/failure mapping | State-transition history and current status |
| Observable output | Devin-created PR against the fork | PR URL, state, and structured result |
| Analytics | Counts, PR yield, cycle time, ACUs, progress, failures | HTML dashboard and `/api/metrics` |
| Working remediation | Two real live sessions, not only a fake demo | Issue-to-session-to-PR evidence table |
| Docker | One-worker application image with persistent SQLite volume | Container smoke and restart tests |
| Reproducible demo | Signed deterministic fake webhook through the real ingress path | README command and automated test |
| Five-minute presentation | What, How, Why, When narrative grounded in observed results | Loom script and recording checklist |

## Trust boundaries

GitHub issue text is untrusted. A request is accepted only when all of these checks pass:

1. Payload size is within the configured limit.
2. HMAC-SHA256 over the raw request bytes matches `X-Hub-Signature-256`.
3. `X-GitHub-Event` is `issues` and `X-GitHub-Delivery` is a valid GUID.
4. The action is `labeled`, the label is exactly `devin:ready`, and the item is not a PR.
5. Repository name and numeric ID both match the allowlist.
6. The labeling actor's login and numeric ID both match the allowlist.

The issue body is truncated and control characters are removed before prompting. Devin gets no
session secrets. Its GitHub installation is restricted to the fork. Sessions have an ACU cap,
operate on one repository, create PRs only, and cannot merge.

## Ownership and idempotency

SQLite is the canonical orchestration state. Webhook delivery ID and `(repository_id, issue_id)`
are unique, so redelivery or relabeling cannot spend ACUs twice. A transaction persists the task
before any external call.

Session creation is the only ambiguous operation: a timeout may occur after Devin accepted the
request. Every session uses the task ID in its title and tags. The reconciler searches recent
sessions for that tag before deciding that operator attention is required; it never blindly
retries an ambiguous creation.

On restart, the reconciler sweeps queued, creating, running, and needs-attention tasks. This is
separate from request error handling because process termination can bypass in-process cleanup.

## State model

```text
queued -> creating -> running -> completed_with_pr
                    |       \-> completed_without_pr
                    |        -> needs_attention <-> running
                    \--------> failed
```

- `new`, `claimed`, `running`, and `resuming` remain active.
- `waiting_for_user` and `waiting_for_approval` require attention.
- `suspended` requires attention with its reason preserved.
- `error` is a failed session.
- `exit` is only lifecycle completion; it is not automatically business success.

## Success semantics

The dashboard reports **PR production rate**, not correctness. A task is
`completed_with_pr` only when Devin is terminal, structured output is valid, and the PR URL points
to `samuelczhao/superset`. Devin-reported tests are labeled as such. The final evidence separately
records targeted test and GitHub CI results; no two-run sample is used to claim broad productivity
or quality improvements.

## Observability

The dashboard and JSON API expose:

- accepted, queued, active, needs-attention, failed, and PR-producing task counts;
- progress for each issue and links to the Devin session and PR;
- cumulative ACUs per session and in total;
- median issue-to-PR cycle time and PR production rate;
- safe error codes and status details.

Logs are structured around delivery, task, issue, and session IDs. Tokens, signatures, raw bodies,
issue bodies, and full prompts are never logged.

## Deliberate MVP limits

- One application process and one reconciler. Production would use Postgres plus a dedicated
  worker and lease-based claims.
- Local SQLite is durable for the demo but not a multi-replica queue.
- An HTTPS tunnel provides the live GitHub delivery; deterministic simulation remains available.
- No auto-merge, issue-comment bot, authentication platform, frontend framework, or enterprise
  analytics are included.
