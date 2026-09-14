# Independent PR #4 regression verification

**Verified:** the unchanged regression added by [PR #4](https://github.com/samuelczhao/superset/pull/4)
fails on the original implementation and passes on the fix, using real Superset exporters,
models, and SQLite writes. This is independent execution of Devin's regression, not an
independently authored test or a hosted CI result.

| Source | Commit | Observed result |
| --- | --- | --- |
| Base | `e7dccd44a7c212739147155548e689e9d6b3408f` | Expected assertion failure: only `datasets/my_database/users.yaml` survives instead of two distinct dataset paths |
| PR #4 | `d6394296de8682e5ead171f20b4167bee7b7971c` | One test passed, including distinct paths and normalized dataset JSON fields |

The fixture creates `prod.users` and `dev.users` in one database. The base assigns both
the same path. The fixed exporter produces `users_1.yaml` and `users_2.yaml`; the test also
asserts dictionary values for `params`, `template_params`, and `extra`, plus the database UUID.
The base fails at the filename assertion before reaching those JSON assertions.

## Evidence

- [Base pytest output](evidence/base.log) and [head pytest output](evidence/head.log).
- [Machine-readable result](evidence/result.json): exact commands, environment, commits,
  archive/test checksums, exit codes, Python version, platform, and verification timestamp.
- [Base JUnit](evidence/base.xml), [head JUnit](evidence/head.xml), and
  [installed dependency inventory](evidence/dependencies.txt).

Recorded environment: macOS arm64, Python 3.12.13, SQLAlchemy 2.0.51, Flask 2.3.3,
Flask-AppBuilder 5.2.2, pytest 9.1.1, PyYAML 6.0.3. Dependencies come from the pinned
Superset `requirements/base.txt`, which is identical at both commits, plus pinned pytest plugins.

## Reproduce

Prerequisites: `uv`, `curl`, and Python 3.12 or newer. From the orchestrator repository root:

```sh
uv run --no-project --python 3.12 verification/pr4/verify.py
```

The runner creates a fresh temporary workspace, downloads two public SHA-pinned source archives
(about 330 MB compressed combined), verifies their checksums, creates an isolated Python 3.12
environment, installs dependencies, and runs the same selected head test against each source tree.
No Superset production source or test file is modified. It prints the evidence directory on success;
expect several GB of temporary disk capacity for both extracted trees and dependencies.
There are no Devin calls, GitHub mutations, application credentials, or production database access.
The printed temporary directory remains available for inspection; the runner does not delete it.

The relevant pytest invocation is recorded in full in `result.json`. Its key options are:

```text
--import-mode=importlib
--confcutdir=<head>/tests/unit_tests
<head>/tests/unit_tests/datasets/commands/export_test.py::test_export_database_with_same_named_datasets
-p source_guard -p pytest_mock.plugin -p pytest_asyncio.plugin
```

`PYTHONPATH` selects the base or head production source, including its matching `superset-core`.
The source guard asserts the actual loaded exporter/model/core paths after each run. A setup or
teardown error, skipped test, wrong imported tree, or unrelated base failure makes verification fail.
Pytest plugins are explicitly selected, and test subprocesses receive an allowlisted environment
with a public disposable test-only secret and temporary Superset data directory.

To retain output at a chosen location, add `--output /absolute/path/to/evidence`.
This overwrites generated evidence files at that location. The result manifest is marked
`incomplete` at the beginning, so an interrupted rerun cannot leave a stale success claim.
`--workspace` can reuse a previously created `pr4-independent.*` directory directly under the
system temporary directory; its source archives are checked and re-extracted before every run.
If a download checksum changes, the runner stops rather than silently accepting different input.

## Scope and limits

This verifies one focused regression through `ExportDatabasesCommand._export`. It does not
exercise the HTTP endpoint, downloadable ZIP, import round-trip, the full Superset test suite,
or PostgreSQL/MySQL. Superset's existing unit fixtures substitute the global database session
with a real in-memory SQLite session and create tables from ORM metadata. The exporter and
models themselves are not mocked or extracted into a substitute implementation.

The `--confcutdir` option excludes the unrelated integration-test bootstrap while retaining
the existing Superset unit fixtures. The captured logs retain normal app-initialization warnings
about pending migrations and legacy test encryption; neither prevented the selected test from
running. A passing test here does not establish production migration readiness or approval to merge.

## Verifier checks

These eight tests check that the evidence parser rejects setup errors, skips, unrelated failures,
an unexpectedly passing base, a failing head, and a missing test. They are separate from both
the Superset regression and the orchestrator's own test count.

```sh
uv run python -m mypy --explicit-package-bases --follow-imports=silent verification/pr4/verify.py verification/pr4/source_guard.py verification/pr4/test_verify.py
uv run python -m pytest verification/pr4/test_verify.py -q
uv run python -m ruff check verification/pr4
uv run python -m ruff format --check verification/pr4
```
