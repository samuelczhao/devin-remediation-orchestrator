# Implementation evidence

Evidence is separated into verified local behavior and live Devin outcomes. A simulated adapter
proves orchestration mechanics; it is not presented as proof that Devin remediated Superset.

## Verification refresh on 2026-09-13

- Strict typecheck, 130 orchestrator tests plus eight verifier guardrail tests, lint, and formatting pass.
- A fresh, isolated Docker simulation completed the signed event-to-PR loop. Replay reused the
  same task, and a container restart preserved the result and metrics. Live evidence was untouched.
- Basic authentication accepts a matching UTF-8 password and returns 401 for invalid credentials,
  including non-ASCII input.
- Crash tests now terminate the simulated remote session before stopping the process. A new
  reconciler completes cleanup from the saved evidence even if a later GET would omit it or fail.
- API adapter tests verify archival on DELETE, idempotent cleanup of a missing session, and
  propagation of permission failures. These are mocked API checks, not new paid Devin runs.
- The outcome snapshot distinguishes GitHub facts from SHA-pinned review notes. Missing coverage
  suppresses outcome counts; a mismatched PR head invalidates its review and regression evidence.
  Snapshots older than 24 hours retain their historical counts with a visible stale warning.

## Independent target-fix verification on 2026-09-14 UTC

The same unmodified regression introduced by PR #4 was run independently against base
`e7dccd44a7c212739147155548e689e9d6b3408f` and PR head
`d6394296de8682e5ead171f20b4167bee7b7971c`. The base failed the expected missing-dataset assertion;
the fixed code passed. Real Superset exporters and ORM models were loaded from the respective
source trees, using the project's unit fixtures and an in-memory SQLite database.

[Exact commands, captured logs, environment, and reproduction runner](../verification/pr4/README.md)
are included. This is independent execution of a Devin-authored test, not an independently authored
test or a hosted CI result. It does not verify HTTP/ZIP delivery, import round-trip, other database
dialects, or the complete Superset suite. Eight verifier guardrail tests are separate from the
130 orchestrator tests and the one Superset regression.

The recorded GitHub snapshot contains four proposals, zero approvals, zero merges, and no check
runs. One proposal is closed without merge. Separate review notes identify two candidates, one
rejected attempt, and one replacement needing rework. Only PR #4 has independent regression
execution evidence. The four attempts cover three original issues, not four resolved bugs.

## Repository setup

| Item | Evidence |
| --- | --- |
| Challenge fork | [`samuelczhao/superset`](https://github.com/samuelczhao/superset) |
| Inspected fork commit | `e7dccd44a7c212739147155548e689e9d6b3408f` |
| Defect 1 | [Issue #1](https://github.com/samuelczhao/superset/issues/1) |
| Defect 2 | [Issue #2](https://github.com/samuelczhao/superset/issues/2) |
| Defect 3 | [Issue #3](https://github.com/samuelczhao/superset/issues/3) |
| Corrective issue | [Issue #7](https://github.com/samuelczhao/superset/issues/7), created after review rejected the first #2 fix |
| Trigger label | `devin:ready`, applied through GitHub and received by the then-active live signed webhook |
| Branch protection | One approval, conversation resolution, admins enforced, no force pushes/deletion |

GitHub recorded HTTP 202 for the four `issues.labeled` deliveries persisted by the service:
`875240b0-9cbe-11f1-9aaa-c06248d8f279`, `8f9e46b0-9cbe-11f1-9438-e41d23da87d4`,
`906407b0-9cbe-11f1-8541-6dcade638c7a`, and
`ce4e7c20-9cc0-11f1-859c-d3228e8978a3`. The original live hook also recorded HTTP 400 for
out-of-scope `issues.opened` and `issues.edited` deliveries because those payloads omit `label`.
The hardening pass corrected that operator-facing defect: realistic signed non-labeled actions now
return HTTP 202 `ignored_action` without creating a task.

## Verified locally on 2026-08-22

- Typecheck: passed.
- Tests: 80 passed.
- Lint: passed.
- Simulation and explicit live-override Compose configurations: valid.
- Image: built successfully and ran as UID 10001 with a read-only root filesystem.
- Container health: healthy.
- Default Compose omitted Devin credentials even with ambient live variables; the simulator
  accepted the isolated simulation backend and refused the live backend before posting.
- Signed webhook simulation: `queued -> running -> completed_with_pr`.
- Simulated observability: one PR / one terminal task, 1.00 PR yield, 1.25 simulated ACUs.
- Repeated issue event: `created: false`; the original task/session was reused.
- Container restart: completed task, PR URL, ACUs, and metrics remained present.
- Active simulated sessions reconstruct after a process restart and continue to terminal state.
- Malformed Devin responses are isolated per task, and ambiguous-session lookup follows cursors.
- Live operator routes reject unauthenticated access; realistic non-labeled issue actions return
  an accepted ignore response instead of a failed delivery.

The simulation's PR number, commit, tests, and ACUs are fixtures and are labeled as simulated in
the UI and output.

## Live remediation evidence

A terminal Devin session without a target-fork PR is not counted as PR-producing. A produced PR
is not treated as approved, merged, or fully correct. The independent PR #4 check is scoped above;
the session-reported checks below remain distinct claims.

| Issue | Devin session | Pull request | Devin-reported checks | GitHub CI | Review result |
| --- | --- | --- | --- | --- | --- |
| [#1](https://github.com/samuelczhao/superset/issues/1) | [Session](https://app.devin.ai/sessions/37720c2d94d14b8bb8b305235f58e60a) | [PR #4](https://github.com/samuelczhao/superset/pull/4) | Focused dataset export tests, nearby command tests, and pre-commit passed | No checks configured on fork | No blocking defect found; coverage and stale skipped-test gaps recorded |
| [#2](https://github.com/samuelczhao/superset/issues/2) | [Session](https://app.devin.ai/sessions/d4433b04e98e45a0ba2023436f4cde92) | [PR #5](https://github.com/samuelczhao/superset/pull/5), closed unmerged | Focused tag tests and pre-commit reported passed | No checks configured on fork | Rejected: command remained broken end to end; corrective issue #7 opened |
| [#3](https://github.com/samuelczhao/superset/issues/3) | [Session](https://app.devin.ai/sessions/3326b28309b04ff4bddf25f8903882a9) | [PR #6](https://github.com/samuelczhao/superset/pull/6) | 22 focused tests and 2 export tests passed; integration suite could not initialize its metadata DB | No checks configured on fork | No blocking defect found; two optional coverage improvements recorded |
| [#7](https://github.com/samuelczhao/superset/issues/7) | [Session](https://app.devin.ai/sessions/2c66abc4f7274ef2807dbc8cb9f2fc6b) | [PR #8](https://github.com/samuelczhao/superset/pull/8) | 13 focused tests, 279 nearby tests, and pre-commit passed | No checks configured on fork | Initial blockers corrected; later audit found migration and reserved-name operator-flow gaps, so the PR is not upstream merge-ready |

The targeted checks in that table are structured claims returned by each Devin session, not
independently executed Superset CI. The separate PR #4 verification above used an isolated Superset
environment to execute one regression before and after the fix. It does not independently confirm
the broader test counts returned by Devin.

The orchestration repository includes a public quality workflow. Superset PRs still have no hosted
checks configured, so that workflow does not convert Devin-reported Superset tests into CI proof.

## Review feedback loop

PR #5 is the deliberate negative case. It fixed the immediate enum assignment but disclosed and
left a broken string-plus-integer association join. Independent inspection found additional
SQLAlchemy 2 call failures before that code path, transaction-poisoning risk, and a stale ORM test
assertion. The workflow therefore did not merge it or label it a successful remediation. Those
findings became issue #7 and re-entered the same signed webhook-to-Devin path.

The first PR #8 review found another exact-name collision: a custom tag named
`favorited_by:<id>` could receive an implicit association that runtime cleanup would never remove.
Devin amended the same PR to reject unexpected reserved-name types, re-read and validate a tag
after an insert race, type-filter association joins, and add four regression tests. A second
review found no blocker within its take-home scope. A later audit expanded the production gate:

- existing favorite associations stored with legacy object type `slice` are not migrated before
  the new `chart` anti-join runs, so they can remain unreadable and receive a duplicate association;
- users can create custom tags such as `editor:7`, while the backfill treats that reserved-name
  collision as a fatal phase error. A production change needs an explicit preflight, validation,
  migration, or skip-and-report policy rather than an implicit operational surprise.

These gaps make PR #8 a review-feedback artifact and take-home candidate, not an upstream-ready
change.

This distinction is visible in the product: PR production measures output, while the outcomes
panel separately reports verification, reviews, merges, and CI from a manually refreshed snapshot.
A production rollout would automate that refresh.

## Live control-plane snapshot

After reconciliation completed on 2026-08-20 in the earlier live control-plane build:

- 4 accepted events, 4 terminal tasks, 0 active, 0 attention-required, and 0 failed;
- 4 target-fork PR artifacts and 1.00 PR yield;
- 617.96-second median issue-to-terminal cycle time;
- self-serve usage delegated to Devin Billing; the enterprise ACU API field returned 0.0 and is
  not treated as cost evidence.

The control plane correctly counts PR #5 as produced; the separate review record marks it
rejected and closed. The current dashboard separates PRs produced from engineering outcomes.
The current hardening changes were subsequently verified by typecheck, automated tests, CI, and
the deterministic simulation; they were not exercised through another paid Devin session.

## Known evidence limits

- The fork has no GitHub checks configured. Apart from the independent PR #4 regression above,
  the reported Superset test results have not been independently executed.
- Self-serve quota, credits, and dollar cost are visible in Devin Billing, not the organization
  ACU field. The submission makes no cost claim from the API's 0.0 value.
- PR #8 exercised SQLite at runtime and compiled SQL for PostgreSQL/MySQL, not live servers.
- PR #8 does not migrate legacy `tagged_object.object_type='slice'` favorite associations before
  using the normalized `chart` value for new anti-joins.
- A user-created custom tag with an implicit reserved name causes the relevant PR #8 backfill
  phase to fail until an operator renames or removes it; the API does not prevent that collision.
- Its conflict re-read uses an ordinary `SELECT`; a concurrent administrative `sync-tags` run at
  `REPEATABLE READ` can retain an old snapshot. Production hardening should use a locking read,
  require the winner row, type-filter type-tag joins, and add two-session database tests.
- Superset's PostgreSQL migrations convert tag enum columns to `VARCHAR`; a test database created
  directly from ORM metadata can retain native enums and does not match that production schema.
