# Implementation evidence

Evidence is separated into verified local behavior and live Devin outcomes. A simulated adapter
proves orchestration mechanics; it is not presented as proof that Devin remediated Superset.

## Repository setup

| Item | Evidence |
| --- | --- |
| Challenge fork | [`samuelczhao/superset`](https://github.com/samuelczhao/superset) |
| Inspected fork commit | `e7dccd44a7c212739147155548e689e9d6b3408f` |
| Defect 1 | [Issue #1](https://github.com/samuelczhao/superset/issues/1) |
| Defect 2 | [Issue #2](https://github.com/samuelczhao/superset/issues/2) |
| Defect 3 | [Issue #3](https://github.com/samuelczhao/superset/issues/3) |
| Corrective issue | [Issue #7](https://github.com/samuelczhao/superset/issues/7), created after review rejected the first #2 fix |
| Trigger label | `devin:ready`, applied through GitHub and received by the live signed webhook |
| Branch protection | One approval, conversation resolution, admins enforced, no force pushes/deletion |

GitHub recorded HTTP 202 for the four `issues.labeled` deliveries persisted by the service:
`875240b0-9cbe-11f1-9aaa-c06248d8f279`, `8f9e46b0-9cbe-11f1-9438-e41d23da87d4`,
`906407b0-9cbe-11f1-8541-6dcade638c7a`, and
`ce4e7c20-9cc0-11f1-859c-d3228e8978a3`. Out-of-scope `issues.opened` and `issues.edited`
deliveries received HTTP 400, demonstrating that the live ingress failed closed rather than
starting extra sessions.

## Verified locally on 2026-08-20

- Typecheck: passed.
- Tests: 43 passed.
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

The simulation's PR number, commit, tests, and ACUs are fixtures and are labeled as simulated in
the UI and output.

## Live remediation evidence

A terminal Devin session without a target-fork PR is not counted as PR-producing. A PR is not
called correct until reviewer and CI evidence support it.

| Issue | Devin session | Pull request | Devin-reported checks | GitHub CI | Review result |
| --- | --- | --- | --- | --- | --- |
| [#1](https://github.com/samuelczhao/superset/issues/1) | [Session](https://app.devin.ai/sessions/37720c2d94d14b8bb8b305235f58e60a) | [PR #4](https://github.com/samuelczhao/superset/pull/4) | Focused dataset export tests, nearby command tests, and pre-commit passed | No checks configured on fork | No blocking defect found; coverage and stale skipped-test gaps recorded |
| [#2](https://github.com/samuelczhao/superset/issues/2) | [Session](https://app.devin.ai/sessions/d4433b04e98e45a0ba2023436f4cde92) | [PR #5](https://github.com/samuelczhao/superset/pull/5), closed unmerged | Focused tag tests and pre-commit reported passed | No checks configured on fork | Rejected: command remained broken end to end; corrective issue #7 opened |
| [#3](https://github.com/samuelczhao/superset/issues/3) | [Session](https://app.devin.ai/sessions/3326b28309b04ff4bddf25f8903882a9) | [PR #6](https://github.com/samuelczhao/superset/pull/6) | 22 focused tests and 2 export tests passed; integration suite could not initialize its metadata DB | No checks configured on fork | No blocking defect found; two optional coverage improvements recorded |
| [#7](https://github.com/samuelczhao/superset/issues/7) | [Session](https://app.devin.ai/sessions/2c66abc4f7274ef2807dbc8cb9f2fc6b) | [PR #8](https://github.com/samuelczhao/superset/pull/8) | 13 focused tests, 279 nearby tests, and pre-commit passed | No checks configured on fork | Initial review blocker corrected; amended-head review found no remaining take-home blocker |

The targeted checks above are structured claims returned by each Devin session, not independently
executed Superset CI. Local inspection confirmed the #1 and #3 diffs were architecturally sound,
but this checkout does not contain a configured Superset Python environment. That limitation is
preserved instead of turning an agent report into a CI claim.

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
independent review accepted that amended head.

This distinction is visible in the product: PR yield measures whether the system produced a
review artifact; reviewer acceptance and CI are separate quality signals. A production rollout
would ingest both into the dashboard.

## Live control-plane snapshot

After reconciliation completed on 2026-08-20:

- 4 accepted events, 4 terminal tasks, 0 active, 0 attention-required, and 0 failed;
- 4 target-fork PR artifacts and 1.00 PR yield;
- 617.96-second median issue-to-terminal cycle time;
- 0.0 cumulative ACUs as reported by the Devin API.

The control plane correctly counts PR #5 as produced; the separate review record marks it
rejected and closed. That is why the dashboard calls the metric PR yield rather than success rate.

## Known evidence limits

- The fork has no GitHub checks configured, so Superset test results remain session-reported.
- PR #8 exercised SQLite at runtime and compiled SQL for PostgreSQL/MySQL, not live servers.
- Its conflict re-read uses an ordinary `SELECT`; a concurrent administrative `sync-tags` run at
  `REPEATABLE READ` can retain an old snapshot. Production hardening should use a locking read,
  require the winner row, type-filter type-tag joins, and add two-session database tests.
- Superset's PostgreSQL migrations convert tag enum columns to `VARCHAR`; a test database created
  directly from ORM metadata can retain native enums and does not match that production schema.
