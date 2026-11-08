"""The isolated frozen-font check must not dispatch legacy generation fixtures."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def run_check(arguments):
    paths = (ROOT / "src", ROOT / "artifacts/external/data_collection", ROOT / "packaging")
    return subprocess.run(
        [sys.executable, "-B", "-X", "utf8", str(ROOT / "packaging/inkstruct_smoke.py"), *arguments],
        cwd=ROOT, env={**os.environ, "QT_QPA_PLATFORM": "offscreen",
                      "PYTHONPATH": os.pathsep.join(map(str, paths))},
        capture_output=True, text=True, encoding="utf-8", timeout=20, check=False,
    )


def test_large_font_mode_is_documented():
    result = run_check(["--help"])
    assert result.returncode == 0
    assert "--large-font-check" in result.stdout and "--large-font" in result.stdout


@pytest.mark.parametrize("mode", ["missing", "unselected", "legacy-conflict"])
def test_large_font_arguments_fail_before_creating_private_workspace(tmp_path, mode):
    output = tmp_path / "not-created"
    arguments = ["--output", str(output)]
    if mode == "missing":
        arguments += ["--large-font-check", "--large-font", str(tmp_path / "missing-a"),
                      "--large-font", str(tmp_path / "missing-b")]
        expected = "two distinct existing"
    elif mode == "unselected":
        arguments += ["--large-font", str(tmp_path / "missing-a")]
        expected = "--large-font requires --large-font-check"
    else:
        a, b = tmp_path / "a.inkfont", tmp_path / "b.inkfont"
        a.write_bytes(b"not parsed in an incompatible mode")
        b.write_bytes(b"not parsed in an incompatible mode")
        arguments += ["--large-font-check", "--large-font", str(a), "--large-font", str(b), "--export-only"]
        expected = "separate from the legacy"
    result = run_check(arguments)
    assert result.returncode == 2 and expected in result.stderr
    assert not output.exists()
