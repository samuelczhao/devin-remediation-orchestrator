"""Reject results if pytest imported the wrong Superset source tree."""

import os
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def check_source_tree() -> Iterator[None]:
    yield
    source = Path(os.environ["PR4_SOURCE_ROOT"]).resolve()
    for module_name in (
        "superset.commands.database.export",
        "superset.commands.dataset.export",
        "superset.connectors.sqla.models",
        "superset.models.core",
        "superset_core",
    ):
        module = sys.modules[module_name]
        filename = module.__file__
        assert filename is not None, f"Module has no source file: {module_name}"
        actual = Path(filename).resolve()
        if module_name == "superset_core":
            expected = source / "superset-core/src/superset_core/__init__.py"
        else:
            expected = source.joinpath(*module_name.split(".")).with_suffix(".py")
        assert actual == expected, f"Wrong source imported: {actual} != {expected}"
        print(f"SOURCE VERIFIED: {module_name} from {source.name}")
