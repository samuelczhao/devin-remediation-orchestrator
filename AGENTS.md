# Project Guidance

## Known Pitfalls

- The runtime filesystem is read-only. Invoke executables from `/app/.venv/bin` directly;
  `uv run` attempts to initialize a cache and causes a container restart loop.
- The local macOS shell may not expose a bare `python` command. Use `uv run python` for
  project scripts and verification commands.
- Simulation and live mode share a named volume but must use different database paths. Set
  `DATABASE_PATH=/data/live-orchestrator.db` before starting live mode so fixture evidence cannot
  contaminate live metrics.
- Devin may leave a completed API session at `finished` or `waiting_for_user` after publishing a
  structured result. Validate the result and target PR, then use the v3 termination endpoint;
  otherwise the task remains active indefinitely.
