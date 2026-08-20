# Project Guidance

## Known Pitfalls

- The runtime filesystem is read-only. Invoke executables from `/app/.venv/bin` directly;
  `uv run` attempts to initialize a cache and causes a container restart loop.
- The local macOS shell may not expose a bare `python` command. Use `uv run python` for
  project scripts and verification commands.
