# Five-minute Loom runbook

Target length: 4:30–4:50. Keep the dashboard, fork issues, one Devin session, one PR, and the
architecture file open before recording.

## 0:00–0:40 — What

“Engineering teams accumulate maintenance work that is valuable but expensive to reproduce,
implement, test, and move into review. I chose three real Superset defects: a database export path
that can silently omit a dataset, a tag backfill that writes the wrong enum, and shared export
state that can corrupt concurrent results. The team retains control through one label:
`devin:ready`.”

Show the three public issues and their acceptance criteria.

## 0:40–1:35 — How: architecture

Show the diagram in `docs/ARCHITECTURE.md`.

“GitHub sends a signed issue event. The service checks the raw-body HMAC, stable repository and
actor IDs, exact label, event shape, and body limit before it writes anything. SQLite is the
canonical task ledger. A single reconciler launches an ACU-capped Devin v3 session and polls it
through terminal state. The control plane never merges.”

Open `app/github_webhook.py`, `app/devin_client.py`, and `app/orchestrator.py`. Point out:

- the unique task tag and no-blind-retry rule for ambiguous session creation;
- the repository-scoped prompt and structured output schema;
- the rule that `exit` is not success without valid output and a target-fork PR.

## 1:35–2:40 — Demo

Show a GitHub webhook delivery or replay the deterministic Docker simulation:

```bash
docker compose exec orchestrator /app/.venv/bin/python scripts/simulate_webhook.py
```

Show the dashboard move through queued/running/terminal states. Then open a real Devin session and
its Superset PR. Explain the code change and show the focused regression test. Do not call the
simulated PR real; use it only to demonstrate repeatability when the live task is already done.

## 2:40–3:30 — Observability and failure behavior

“A VP can see queue depth, active and attention-required tasks, failures, PR yield, cycle time, and
ACUs. Every row links back to the issue, session, and PR. PR yield means workflow output, not code
quality; Devin-reported tests remain labeled as agent claims until GitHub CI confirms them.”

Show `/api/metrics`, one completed task, and—if available—one waiting/failure mapping in tests.
Mention that duplicate webhook delivery cannot spend twice and state survives restart.

## 3:30–4:15 — Why Devin

“A conventional bot can bump a version or apply a codemod. These issues require reading a large
repository, reproducing behavior, choosing the canonical abstraction, adapting tests, running the
right checks, and packaging the result for review. Devin is the core execution primitive: the
control plane supplies policy, durability, budget, and evidence; Devin supplies autonomous
repository-level engineering.”

## 4:15–4:50 — When: customer rollout

“I would start in shadow mode on labeled, low-risk maintenance issues and measure PR yield,
reviewer acceptance, CI pass rate, cycle time, and ACUs by issue class. Next I would move state to
Postgres, add lease-based workers and SSO/RBAC, ingest CI and review outcomes, alert on stuck tasks,
and expand repository policies only after the evidence supports it.”

End on the three live evidence rows. Keep claims limited to what the three runs actually demonstrate.
