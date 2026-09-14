"""Run the unchanged PR #4 regression against both pinned Superset source trees."""

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
COMMITS = {
    "base": "e7dccd44a7c212739147155548e689e9d6b3408f",
    "head": "d6394296de8682e5ead171f20b4167bee7b7971c",
}
ARCHIVE_SHA256 = {
    "base": "8f59da60de81957d59ca7568913851c8705b4b8f373ed51bb936fc6f09016347",
    "head": "065640b20dafedca7f09d892aca30c425cddeefe8d0c0a5e69b02b65fec7fd01",
}
TEST_FILE = "tests/unit_tests/datasets/commands/export_test.py"
TEST_NAME = "test_export_database_with_same_named_datasets"
TEST_SHA256 = "e9ca2fc984463f7ff2af2701d55aa0396ba3032bde8797789c427382468a3b81"
TEST_DEPENDENCIES = ["pytest==9.1.1", "pytest-mock==3.15.1", "pytest-asyncio==1.4.0"]


def run(
    command: list[str], cwd: Path, log: Path, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=300,
        check=False,
        env=env,
    )
    log.write_text(result.stdout)
    return result


def require_ok(result: subprocess.CompletedProcess[str], label: str) -> None:
    if result.returncode:
        raise RuntimeError(f"{label} failed (exit {result.returncode}):\n{result.stdout}")


def digest(path: Path) -> str:
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def obtain_source(workspace: Path, label: str, output: Path) -> Path:
    archive = workspace / f"superset-{label}.tar.gz"
    if not archive.exists():
        url = f"https://codeload.github.com/samuelczhao/superset/tar.gz/{COMMITS[label]}"
        result = run(
            ["curl", "--fail", "--location", "--max-time", "180", "--output", str(archive), url],
            workspace,
            output / f"download-{label}.log",
        )
        require_ok(result, f"Download {label}")
    if digest(archive) != ARCHIVE_SHA256[label]:
        raise RuntimeError(f"Archive checksum mismatch: {archive}")
    with tarfile.open(archive) as source:
        source.extractall(workspace, filter="data")
    return workspace / f"superset-{COMMITS[label]}"


def validate_result(label: str, result: subprocess.CompletedProcess[str], junit: Path) -> None:
    cases = ET.parse(junit).findall(".//testcase")
    if len(cases) != 1 or cases[0].attrib.get("name") != TEST_NAME:
        raise RuntimeError(f"{label}: the exact single regression did not run")
    case = cases[0]
    if case.find("error") is not None or case.find("skipped") is not None:
        raise RuntimeError(f"{label}: setup, teardown, or skip is not regression evidence")
    failure = case.find("failure")
    if label == "head":
        if result.returncode != 0 or failure is not None:
            raise RuntimeError("Head did not pass")
        return
    detail = "" if failure is None else (failure.text or "")
    expected = (
        "AssertionError",
        "users.yaml",
        "users_1.yaml",
        "users_2.yaml",
        "Right contains one more item",
    )
    if result.returncode != 1 or not all(fragment in detail for fragment in expected):
        raise RuntimeError("Base did not fail for the expected missing-dataset assertion")


def verify(workspace: Path, output: Path, uv: str) -> None:
    sources = {label: obtain_source(workspace, label, output) for label in COMMITS}
    test = sources["head"] / TEST_FILE
    if digest(test) != TEST_SHA256:
        raise RuntimeError("Upstream regression file checksum mismatch")
    requirements = sources["head"] / "requirements/base.txt"
    if digest(requirements) != digest(sources["base"] / "requirements/base.txt"):
        raise RuntimeError("The dependency inputs differ between base and head")

    python = workspace / "venv/bin/python"
    if not python.exists():
        require_ok(
            run(
                [uv, "venv", "--python", "3.12", str(workspace / "venv")],
                workspace,
                output / "venv.log",
            ),
            "Virtual environment",
        )
    install = [
        uv,
        "pip",
        "install",
        "--python",
        str(python),
        "-r",
        "requirements/base.txt",
        *TEST_DEPENDENCIES,
    ]
    require_ok(run(install, sources["head"], output / "install.log"), "Dependencies")
    runtime = workspace / "runtime"
    runtime.mkdir(exist_ok=True)
    runs: dict[str, dict[str, object]] = {}
    report: dict[str, object] = {
        "status": "verified",
        "verified_at_utc": datetime.now(UTC).isoformat(),
        "platform": platform.platform(),
        "commits": COMMITS,
        "archive_sha256": ARCHIVE_SHA256,
        "test_file_sha256": TEST_SHA256,
        "requirements_sha256": digest(requirements),
        "install_command": install,
        "runs": runs,
    }
    for label, source in sources.items():
        junit = output / f"{label}.xml"
        command = [
            str(python),
            "-m",
            "pytest",
            "--import-mode=importlib",
            f"--confcutdir={sources['head'] / 'tests/unit_tests'}",
            f"{test}::{TEST_NAME}",
            "-p",
            "source_guard",
            "-p",
            "pytest_mock.plugin",
            "-p",
            "pytest_asyncio.plugin",
            "-q",
            "-rA",
            "-p",
            "no:cacheprovider",
            f"--junitxml={junit}",
        ]
        environment = {
            "PATH": os.defpath,
            "SUPERSET_HOME": str(runtime),
            "SUPERSET_SECRET_KEY": "pr4-public-disposable-verification-only",
            "PR4_SOURCE_ROOT": str(source),
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "PYTHONPATH": os.pathsep.join(map(str, (source, source / "superset-core/src", HERE))),
        }
        result = run(command, source, output / f"{label}.log", env=environment)
        validate_result(label, result, junit)
        outcome = "expected assertion failure" if label == "base" else "passed"
        runs[label] = {
            "command": command,
            "cwd": str(source),
            "environment": environment,
            "exit_code": result.returncode,
            "outcome": outcome,
        }
        print(f"{label} {COMMITS[label]}: {outcome}", flush=True)
    versions = run([str(python), "--version"], workspace, output / "python-version.txt")
    require_ok(versions, "Python version")
    report["python"] = versions.stdout.strip()
    freeze = run(
        [uv, "pip", "freeze", "--python", str(python)], workspace, output / "dependencies.txt"
    )
    require_ok(freeze, "Dependency inventory")
    (output / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"Evidence: {output}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workspace", type=Path, help="Reuse an existing pr4-independent.* temp directory"
    )
    parser.add_argument(
        "--output", type=Path, help="Evidence directory; defaults to WORKSPACE/evidence"
    )
    args = parser.parse_args()
    if sys.version_info < (3, 12):  # noqa: UP036 - standalone runner outside this project's venv
        parser.error("Run with Python 3.12 or newer")
    uv = shutil.which("uv")
    if uv is None:
        parser.error("uv is required")
    workspace = (args.workspace or Path(tempfile.mkdtemp(prefix="pr4-independent."))).resolve()
    temp_roots = {Path(tempfile.gettempdir()).resolve(), Path("/tmp").resolve()}
    if workspace.parent not in temp_roots or not workspace.name.startswith("pr4-independent."):
        parser.error(
            "Workspace must be a pr4-independent.* directory directly in the system temp directory"
        )
    if not workspace.is_dir():
        parser.error("Workspace does not exist")
    output = (args.output or workspace / "evidence").resolve()
    output.mkdir(parents=True, exist_ok=True)
    (output / "result.json").write_text(
        json.dumps({"status": "incomplete", "attempted_at_utc": datetime.now(UTC).isoformat()})
        + "\n"
    )
    print(f"Isolated workspace: {workspace}", flush=True)
    verify(workspace, output, uv)


if __name__ == "__main__":
    main()
