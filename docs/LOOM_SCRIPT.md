# Five-minute VP demo runbook

The narration is 652 words: about 4:30 at a conversational 145 words per minute. The preloaded
clickthrough should finish at 4:45–4:55. The buying thesis is: **turn an authorized maintenance
issue into a governed, review-ready pull request without taking approval away from engineering.**

This is a planning case, not a claim about Apache or a measured customer. Say that explicitly.
The live sample proves workflow viability; it does not prove organization-wide ROI.

## Before recording

Open these tabs in order:

1. the disposable local dashboard at [http://127.0.0.1:8001](http://127.0.0.1:8001);
2. [Superset issue #7](https://github.com/samuelczhao/superset/issues/7);
3. its [Devin session](https://app.devin.ai/sessions/2c66abc4f7274ef2807dbc8cb9f2fc6b);
4. [Superset PR #8](https://github.com/samuelczhao/superset/pull/8);
5. [the Devin session payload](https://github.com/samuelczhao/devin-remediation-orchestrator/blob/main/app/devin_client.py#L165-L178);
6. [`docs/ARCHITECTURE.md`](ARCHITECTURE.md).

Prepare a clean simulation before recording:

```bash
docker compose -p devin-demo down --volumes
REMEDIATION_HOST_PORT=8001 docker compose -p devin-demo up --build -d
docker compose -p devin-demo exec orchestrator \
  /app/.venv/bin/python scripts/simulate_webhook.py
```

Wait for `state=completed_with_pr`, then load every browser tab before recording. Port 8001
deliberately avoids stopping a preserved default project on port 8000. The recording requires no
terminal commands, live API calls, or waits.

## 0:00–0:40 — What: the VP problem

Show the dashboard, then say:

“Let me start with the engineering economics. Known maintenance keeps losing to roadmap work
because each fix still needs reproduction, repository context, tests, review, and an audit trail.

Here is an illustrative model, not customer data. For 100 engineers spending two hours a week
across 48 weeks, that is 9,600 hours a year. Recovering 25 percent returns 2,400 hours, or 240 to
480 thousand dollars at an assumed loaded cost of 100 to 200 dollars an hour. In discovery I
would replace those assumptions with the customer’s backlog, time-in-state, and labor data.”

## 0:40–1:20 — Status quo and market

“The status quo is a senior engineer reconstructing the failure, changing code, finding tests,
and shepherding a PR. Deterministic bots handle known transforms. Agent plans overlap in price:
GitHub is 19 to 39 dollars per user monthly; Cursor and Devin full seats are 40, with an 80-dollar
Devin Teams minimum. The buying question is not the cheapest
autocomplete; it is governed, accepted throughput. So I designed this around the unit a VP
actually cares about: the cost and review quality of an accepted PR.”

## 1:20–2:00 — The solution

Open issue #7 and point to `devin:ready`.

“The engineering team still decides what work is authorized. One `devin:ready` label sends a
signed event here. The service creates a Devin v3 session with a repository allowlist, ACU ceiling,
correlation tag, and strict result schema. It validates the target PR and never merges.

Devin is the execution primitive. It reads the unfamiliar repository, reproduces the issue,
edits across files, runs checks, and packages the PR. This control plane adds customer policy,
durability, budget, and evidence. From the team’s perspective, prioritization stays familiar;
the implementation work becomes an asynchronous, observable queue.”

## 2:00–2:30 — How: show the completed loop

Return to the already-loaded dashboard. Point across the task state, issue, session, PR, test, and
metric fields.

“This row shows the complete operator loop. A signed payload followed the production webhook and
state machine from queued, to running, to `completed_with_pr`. We store a unique delivery ID and
a unique repository-and-issue pair, so retries cannot create a second task, and state survives a
restart. This proves the control plane is repeatable; the simulated PR is not Devin evidence.”

Do not open the simulated issue, session, or PR links. The next three tabs contain the real public
evidence.

## 2:30–3:15 — Proof: real Devin outcomes

Move through the issue #7, Devin session, and PR #8 tabs.

“Now I’ll switch from the simulation to the actual work. The live sample was four signed events,
four Devin sessions, and four target-fork PR artifacts, with a 10.3-minute median issue-to-terminal
time. Fresh-context review accepted three take-home candidates and rejected one.

That rejection proves the control loop. The first fix left the command broken, so it was closed,
not merged. The findings became issue #7; Devin produced PR #8, then amended it after review found
another collision. This is only a four-task feasibility sample, and without fork CI the displayed
tests remain Devin-reported claims.”

## 3:15–4:00 — Trust and observability

Open the session-payload code and point to `repos`, `max_acu_limit`, the structured schema, and
`tags`. Move to the architecture diagram, then return to the dashboard.

“Here is the actual session contract: repository, cap, schema, and tag are API fields, not prompt
suggestions. At the boundary, the service verifies the raw-body signature and stable repository
and actor IDs. SQLite is canonical state; a transaction enforces the active-session limit. GitHub is
at-least-once, but Devin create has no idempotency key. After an ambiguous timeout, the worker
searches paginated sessions by durable tag and never blindly posts again. `Exit` is not success
without valid structured output and an allowlisted PR.

The dashboard exposes queue, attention, failures, PR yield, cycle time, usage source, and the
issue-to-session-to-PR trail. PR yield stays separate from review and CI, so rejection remains
visible.”

## 4:00–4:45 — When: customer pilot and federal deployment

“I would not jump from four issues to broad autonomy. I would run a two-week shadow pilot on one
repository and about 20 low-risk issues. I would judge it on unauthorized writes, cycle time,
acceptance and CI by issue class, reviewer minutes, and cost per accepted PR. Only categories that
clear those gates would expand.

For a federal customer, discovery starts with code classification, approved hosts and egress,
identity, audit retention, and authorization. This public SaaS demo is not an ATO. Production
must fit the approved environment, then add SSO/RBAC, audit export, durable workers, CI and review
ingestion, and alerts.”

## 4:45–4:55 — Close

End on the dashboard.

“This converts an explicit engineering decision into a bounded autonomous workstream, while
preserving review and giving leadership evidence for where Devin should scale.”

## Assumptions and pricing sources

- Capacity model: `100 engineers × 2 hours/week × 48 weeks = 9,600 hours/year`;
  `9,600 × 25% = 2,400 hours`; `2,400 × $100–$200/hour = $240,000–$480,000`.
  These are illustrative inputs to replace during discovery, not observed savings.
- [GitHub Copilot organization pricing](https://docs.github.com/en/copilot/concepts/billing/organizations-and-enterprises):
  Business is $19/user/month and Enterprise is $39/user/month.
- [Cursor pricing](https://cursor.com/pricing): Teams is $40/user/month and Enterprise is custom.
- [Devin self-serve pricing](https://docs.devin.ai/admin/billing/self-serve): Teams has an $80/month
  minimum; full seats are $40/month and flex seats draw from shared on-demand credits.

The competitive point is deliberately narrow: agent products have comparable entry pricing, but
a VP should evaluate accepted throughput, reviewer effort, policy violations, and cost per
accepted PR—not seat price alone.

## What this demo signals in a federal deployed-engineering interview

- **Customer ownership:** start with a quantified operating problem and replace assumptions with
  discovery data.
- **Product instinct:** use Devin for autonomous engineering and build only the integration and
  governance layer the customer lacks.
- **Technical depth:** show trust boundaries, durable state, bounded spend, ambiguous-side-effect
  recovery, and validated outcomes.
- **Credibility:** preserve the rejected PR, separate agent claims from CI, and avoid extrapolating
  from four tasks.
- **Deployment judgment:** distinguish a working commercial-cloud prototype from an authorized
  federal deployment and name the decisions needed to cross that gap.
- **Expansion discipline:** earn broader autonomy with measurable pilot gates instead of asking
  the customer to trust a polished demo.

These qualities align with Cognition’s
[federal deployed-engineer role](https://jobs.ashbyhq.com/cognition/f1430967-f367-4afe-9107-e58da423633c):
owning account outcomes, building API/platform extensions, handling difficult deployments,
translating field pain into product direction, and maintaining credibility with customer
engineering teams.

After recording, remove only the disposable demo project:

```bash
docker compose -p devin-demo down --volumes
```
