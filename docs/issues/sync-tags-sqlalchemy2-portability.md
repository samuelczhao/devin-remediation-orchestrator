# sync-tags backfill is incompatible with SQLAlchemy 2 and portable SQL

## Problem

Independent review of the first favorite-tag remediation found that `superset sync-tags` still
could not complete on the supported database stack:

1. `add_types()` and `add_owners()` pass values to `Session.execute()` using a SQLAlchemy 1.x
   keyword form that raises `TypeError` under SQLAlchemy 2.
2. Owner and favorite joins build names with string-plus-integer expressions such as
   `"favorited_by:" + favstar.user_id`. PostgreSQL rejects those expressions, while other
   dialects can coerce them and fail to match the intended tag name.
3. A late association failure rolls back the earlier tag creation or repair because the command
   is transaction-wrapped.
4. Suppressing an `IntegrityError` without a savepoint can leave a PostgreSQL transaction
   unusable.

Relevant code:

- `superset/cli/update.py:56-69`
- `superset/common/tags.py:148-517`
- PR #5 and issue #2

## Acceptance criteria

- Type, owner, and favorite backfills use SQLAlchemy 2-compatible execution.
- `type:`, `editor:`, and `favorited_by:` names are constructed portably.
- Only favorite tags misclassified as `TagType.type` are repaired.
- Tag and `tagged_object` rows persist together without a poisoned transaction.
- Re-running the backfill is idempotent.
- Tests assert persisted associations and reload repaired ORM state before checking it.
- The replacement PR closes issues #2 and #7 and supersedes PR #5.

## Verification

Run focused type, owner, and favorite backfill tests, the nearest tag and CLI tests, and
repository lint. Record environment-limited checks separately from passing checks.
