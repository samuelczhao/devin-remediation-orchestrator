## Problem

The `superset sync-tags` backfill creates `favorited_by:<user_id>` tags with `TagType.type` in
`add_favorites()`. Runtime favorite creation and deletion use `TagType.favorited_by`.

Because tag names are unique and tag lookup includes both name and type, a misclassified backfill
can make runtime operations miss the row, leave stale associations, or attempt to create a
duplicate tag name.

Relevant code:

- `superset/common/tags.py`
- `superset/tags/models.py`
- `superset/cli/update.py`

## Acceptance criteria

- Newly backfilled `favorited_by:<user_id>` tags use `TagType.favorited_by`.
- Existing matching tags misclassified as `TagType.type` are repaired without creating duplicate
  names.
- Re-running the backfill is idempotent.
- Focused tests cover creation, repair, and repeat execution.
- The change does not alter unrelated custom or implicit tags and does not merge or deploy.

## Verification

Run the focused tag backfill test added for this regression, plus the nearest existing tag tests.
