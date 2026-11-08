"""Defaults survive new store instances and never carry document-owned state."""

import os
import subprocess
import sys
from dataclasses import replace

import pytest
from PySide6 import QtCore

from inkstruct.document.images import ImageStyle
from inkstruct.document.styles import FlowStyle
from inkstruct.document.table_style import TableStyle
from inkstruct.global_defaults import GlobalDefaultsStore, LayoutDefaults, document_flow


@pytest.fixture
def store(tmp_path):
    QtCore.QSettings.setDefaultFormat(QtCore.QSettings.Format.IniFormat)
    QtCore.QSettings.setPath(
        QtCore.QSettings.Format.IniFormat, QtCore.QSettings.Scope.UserScope, str(tmp_path)
    )
    return GlobalDefaultsStore()


def test_roundtrip_preserves_precise_values(store):
    defaults = LayoutDefaults(
        style=replace(LayoutDefaults().style, em_mm=6.123456789),
        flow=replace(FlowStyle(), table=TableStyle(width_mm=123.123456789)),
        run="C:/Fonts/my.inkfont",
    )
    store.save(defaults)
    assert GlobalDefaultsStore().load() == (defaults, None)


def test_persistence_in_fresh_process(store, tmp_path):
    store.save(LayoutDefaults(style=replace(LayoutDefaults().style, em_mm=7.123456789)))
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import sys
from PySide6 import QtCore
from inkstruct.global_defaults import GlobalDefaultsStore
QtCore.QSettings.setDefaultFormat(QtCore.QSettings.Format.IniFormat)
QtCore.QSettings.setPath(QtCore.QSettings.Format.IniFormat, QtCore.QSettings.Scope.UserScope, sys.argv[1])
defaults, warning = GlobalDefaultsStore().load()
assert warning is None and defaults.style.em_mm == 7.123456789
""",
            str(tmp_path),
        ],
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_concurrent_update_is_not_overwritten(store):
    other = GlobalDefaultsStore()
    store.save(LayoutDefaults())
    with pytest.raises(ValueError, match="其他窗口"):
        other.save(replace(LayoutDefaults(), mode="plain-text"))


def test_corrupt_record_is_preserved(store):
    store.settings.setValue(store.KEY, "invalid json")
    store.settings.sync()
    broken = GlobalDefaultsStore()
    defaults, warning = broken.load()
    assert warning and defaults == LayoutDefaults()
    assert broken.settings.value(broken.KEY) == "invalid json"


@pytest.mark.parametrize("kind", ["table", "image"])
def test_document_overrides_cannot_enter_global_defaults(kind):
    style = TableStyle() if kind == "table" else ImageStyle()
    with pytest.raises(ValueError, match="不能包含文档元素"):
        LayoutDefaults(flow=replace(FlowStyle(), **{kind + "_overrides": (("node-id", style),)}))


def test_copy_defaults_preserves_document_overrides():
    flow = replace(
        FlowStyle(),
        table_overrides=(("t", TableStyle(width_mm=110)),),
        image_overrides=(("i", ImageStyle(width_mm=45)),),
    )
    defaults = LayoutDefaults(
        flow=replace(FlowStyle(), table=TableStyle(width_mm=140), image=ImageStyle(width_mm=70))
    )
    result = document_flow(defaults, flow)
    assert result.table.width_mm == 140 and result.image.width_mm == 70
    assert result.table_for("t").width_mm == 110 and result.image_for("i").width_mm == 45
