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
| Trigger label | `devin:ready`, created but deliberately not applied before the live safety gate |
| Branch protection | One approval, conversation resolution, admins enforced, no force pushes/deletion |

## Verified locally on 2026-08-20

- Typecheck: passed.
- Tests: 32 passed.
- Lint: passed.
- Compose configuration: valid.
- Image: built successfully and ran as UID 10001 with a read-only root filesystem.
- Container health: healthy.
- Signed webhook simulation: `queued -> running -> completed_with_pr`.
- Simulated observability: one PR / one terminal task, 1.00 PR yield, 1.25 simulated ACUs.
- Repeated issue event: `created: false`; the original task/session was reused.
- Container restart: completed task, PR URL, ACUs, and metrics remained present.

The simulation's PR number, commit, tests, and ACUs are fixtures and are labeled as simulated in
the UI and output.

## Live remediation evidence

These rows must be completed only after token rotation, repository restriction, and the two paid
sessions. A terminal Devin session without a target-fork PR is not counted as a successful
remediation.

| Issue | Devin session | Pull request | Targeted checks | GitHub CI | Result |
| --- | --- | --- | --- | --- | --- |
| [#1](https://github.com/samuelczhao/superset/issues/1) | Pending live run | Pending | Pending | Pending | Pending |
| [#2](https://github.com/samuelczhao/superset/issues/2) | Pending live run | Pending | Pending | Pending | Pending |

For each completed row, inspect the diff, preserve the exact session-reported test command, and
link GitHub CI separately. Do not infer correctness from `status=exit` or from a PR existing.
