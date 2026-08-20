## Problem

`ExportDatabasesCommand` reimplements related-dataset export instead of using the canonical
`ExportDatasetsCommand` serialization path.

Two correctness problems follow:

1. Related dataset filenames call `get_filename(..., skip_id=True)`. Datasets such as
   `prod.users` and `dev.users` therefore map to the same archive path. The generic export loop
   deduplicates paths with a `seen` set, silently dropping one dataset.
2. The duplicate serializer omits the canonical JSON normalization for fields including
   `params`, `template_params`, `extra`, and nested column/metric extras. The resulting YAML can
   disagree with the import schema, which expects dictionary values.

Relevant code:

- `superset/commands/database/export.py`
- `superset/commands/dataset/export.py`
- `superset/commands/export/models.py`
- `tests/unit_tests/datasets/commands/export_test.py`

## Acceptance criteria

- Exporting a database containing same-named datasets in different schemas includes both
  datasets at distinct paths.
- Related datasets exported through a database use the canonical dataset filename and content
  behavior, including JSON-backed field normalization.
- A focused regression test fails on the current implementation and passes after the fix.
- The change remains scoped to database/dataset export behavior and does not merge or deploy.

## Verification

Run at minimum:

```bash
pytest tests/unit_tests/datasets/commands/export_test.py -q
```
