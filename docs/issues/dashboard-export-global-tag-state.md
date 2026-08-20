# Dashboard export mutates process-global chart tag state

## Problem

With `TAGGING_SYSTEM` enabled, dashboard export suppresses a nested chart command's `tags.yaml`
so it can emit one combined chart-and-dashboard tag file. That suppression is mutable class state,
so an interrupted or concurrent dashboard export can change another request's output.

Relevant code:

- `superset/commands/chart/export.py:84-107`
- `superset/commands/dashboard/export.py:393-403`
- `superset/commands/export/models.py:68-73`

Closing the dashboard generator after entering its nested chart export leaves
`ExportChartsCommand._include_tags` false. A later standalone chart export in the same worker then
omits `tags.yaml`. Interleaved exports can instead emit chart-only tags early, causing filename
deduplication to discard the correct combined file.

## Acceptance criteria

- Tag emission is command-instance state, not class/module/process-global state.
- Standalone chart exports include `tags.yaml` by default when tagging is enabled.
- A dashboard's nested chart export suppresses tags only for that command instance.
- Dashboard exports emit exactly one combined tag file.
- Aborted or interleaved dashboard generators cannot affect another export.
- Behavior remains unchanged when `TAGGING_SYSTEM` is disabled.

## Verification

```bash
pytest tests/unit_tests/commands/dashboard/export_test.py \
  tests/unit_tests/charts/commands/export_test.py -q
pytest tests/integration_tests/charts/commands_tests.py -q
```

A `try/finally` alone is insufficient because concurrent requests would still race on shared
class state. Prefer an instance-level `include_tags=True` option and disable it only for the
dashboard's nested chart command.
