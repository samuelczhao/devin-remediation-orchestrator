import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from verification.pr4.verify import TEST_NAME, validate_result

EXPECTED_FAILURE = (
    "AssertionError: users.yaml != users_1.yaml; Right contains one more item: users_2.yaml"
)


def junit_file(tmp_path: Path, status: str | None, detail: str = "") -> Path:
    suite = ET.Element("testsuite")
    case = ET.SubElement(suite, "testcase", name=TEST_NAME)
    if status:
        ET.SubElement(case, status).text = detail
    path = tmp_path / "result.xml"
    ET.ElementTree(suite).write(path)
    return path


@pytest.mark.parametrize(
    ("label", "exit_code", "status", "detail"),
    [
        ("base", 1, "failure", EXPECTED_FAILURE),
        ("head", 0, None, ""),
    ],
)
def test_accepts_only_expected_outcomes(
    tmp_path: Path, label: str, exit_code: int, status: str | None, detail: str
) -> None:
    result = subprocess.CompletedProcess(["pytest"], exit_code, "")
    validate_result(label, result, junit_file(tmp_path, status, detail))


@pytest.mark.parametrize(
    ("label", "exit_code", "status", "detail"),
    [
        ("base", 1, "error", EXPECTED_FAILURE),
        ("base", 0, "skipped", ""),
        ("base", 1, "failure", "ImportError"),
        ("base", 0, None, ""),
        ("head", 1, "failure", EXPECTED_FAILURE),
    ],
)
def test_rejects_non_evidence(
    tmp_path: Path, label: str, exit_code: int, status: str | None, detail: str
) -> None:
    result = subprocess.CompletedProcess(["pytest"], exit_code, "")
    with pytest.raises(RuntimeError):
        validate_result(label, result, junit_file(tmp_path, status, detail))


def test_rejects_missing_test(tmp_path: Path) -> None:
    path = tmp_path / "result.xml"
    path.write_text("<testsuite />")
    with pytest.raises(RuntimeError, match="exact single regression did not run"):
        validate_result("head", subprocess.CompletedProcess(["pytest"], 0, ""), path)
