# Project Guidance

## Known Pitfalls

- The runtime filesystem is read-only. Invoke executables from `/app/.venv/bin` directly;
  `uv run` attempts to initialize a cache and causes a container restart loop.
- The local macOS shell may not expose a bare `python` command. Use `uv run python` for
  project scripts and verification commands.
- Simulation and live mode share a named volume but must use different database paths. Set
  `REMEDIATION_DATABASE_PATH=/data/live-orchestrator.db` before starting live mode so fixture
  evidence cannot contaminate live metrics.
- Keep every application environment variable under the `REMEDIATION_` prefix. GitHub Actions
  injects `GITHUB_REPOSITORY`; an unprefixed settings model will silently target the workflow
  repository instead of the configured remediation fork.
- Devin may leave a completed API session at `finished` or `waiting_for_user` after publishing a
  structured result. Validate the result and target PR, then use the v3 termination endpoint;
  otherwise the task remains active indefinitely.
- A target PR plus passing agent-reported tests is an output signal, not a correctness signal.
  Review exact reserved-name collisions and production-database semantics; a broad "unrelated
  tags unchanged" test missed a same-name custom tag that would receive invalid associations.
- Never let the default simulation Compose path inherit ambient live credentials or mode. Keep
  live settings in an explicit override and make the simulator verify server mode before posting.
- A tag lookup immediately after an ambiguous session POST can miss an eventually visible session.
  Reconcile by repeating tag-only discovery with backoff; never repeat the paid create request.
- Keep private rehearsal scripts and interview-positioning notes outside the submitted repository;
  public documentation should contain implementation, evidence, and the final video link only.
