"""Frozen PDF workers use the bundled console companion, never the system PATH."""

import sys

import pytest

from inkstruct.editor.template_pdf_process import worker_command


@pytest.mark.parametrize(
    "platform,filename", [("darwin", "InkStructTool"), ("win32", "InkStructTool.exe")]
)
def test_frozen_pdf_command_requires_exact_sibling(tmp_path, monkeypatch, platform, filename):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "InkStructEditor"))
    with pytest.raises(ValueError, match="缺失"):
        worker_command()
    companion = tmp_path / filename
    companion.write_bytes(b"placeholder for path test only")
    assert worker_command() == [str(companion), "--inkstruct-pdf-worker"]


def test_python_mode_keeps_module_entry(monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    assert worker_command() == [sys.executable, "-m", "inkstruct.editor.template_pdf_worker"]


def test_frozen_recovery_uses_user_data_not_launch_directory(tmp_path, monkeypatch):
    from PySide6 import QtCore

    from inkstruct.editor.mixed import recovery_directory

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    assert recovery_directory() == tmp_path / "artifacts/editor_recovery"
    monkeypatch.setattr(sys, "frozen", True)
    monkeypatch.setattr(
        QtCore.QStandardPaths, "writableLocation", lambda _: str(tmp_path / "user-data")
    )
    assert recovery_directory() == tmp_path / "user-data/InkStruct/editor_recovery"
    monkeypatch.setattr(QtCore.QStandardPaths, "writableLocation", lambda _: "")
    with pytest.raises(ValueError, match="恢复目录"):
        recovery_directory()
