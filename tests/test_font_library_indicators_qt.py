import os
import subprocess
import sys

from test_font_packages import recorded

from inkstruct.fonts.core import to_user
from inkstruct.fonts.importer import build_font


def test_active_row_and_new_document_default_are_independent(tmp_path):
    fonts = tmp_path / "fonts"
    fonts.mkdir()
    symbols = recorded(tmp_path)
    old, latest, other = (fonts / name for name in ("a-old.inkfont", "b-new.inkfont", "c-other.inkfont"))
    build_font(old, writer="fixture", name="系列字体", symbols=symbols)
    to_user(old, latest)
    os.utime(old, (1_700_000_000, 1_700_000_000))
    build_font(other, writer="fixture", name="另一种字体", symbols=symbols)

    program = r"""
from dataclasses import replace
from pathlib import Path
import sys

from PySide6 import QtCore, QtTest, QtWidgets

from inkstruct.fonts.management_ui import DEFAULT_FONT_LABEL, DEFAULT_FONT_ROLE
from inkstruct.fonts.ui import FontLibrary
from inkstruct.global_defaults import GlobalDefaultsStore
from inkstruct.theme import use_platform_theme

old, latest, other = map(Path, sys.argv[1:])
app = QtWidgets.QApplication([])
QtCore.QSettings.setDefaultFormat(QtCore.QSettings.IniFormat)
QtCore.QSettings.setPath(QtCore.QSettings.IniFormat, QtCore.QSettings.UserScope, str(old.parent.parent))
store = GlobalDefaultsStore()
store.save(replace(store.load()[0], run=str(old)))
library = FontLibrary(old.parent)
library.resize(900, 600)
library.show()

def wait_until(ready):
    for _ in range(300):
        if ready():
            return
        QtTest.QTest.qWait(10)
    raise AssertionError("library background operation did not finish")

def row(path):
    return next(library.list.item(i) for i in range(library.list.count())
                if library.list.item(i).data(QtCore.Qt.UserRole) == str(path))

def select(path, modifier=QtCore.Qt.NoModifier):
    item = row(path)
    QtTest.QTest.mouseClick(library.list.viewport(), QtCore.Qt.LeftButton, modifier,
                            library.list.visualItemRect(item).center())
    assert library.selected() == path
    assert library.list.selectedItems() == [item]

wait_until(lambda: library.metadata_job is None and library.metadata_for(old) is not None)
assert not row(old).isHidden()
assert row(old).text() == "系列字体"
assert row(old).toolTip().splitlines()[0] == DEFAULT_FONT_LABEL
assert row(old).data(QtCore.Qt.AccessibleDescriptionRole) == DEFAULT_FONT_LABEL
assert row(old).data(DEFAULT_FONT_ROLE) and not row(latest).data(DEFAULT_FONT_ROLE)
library.search.setText("新文档默认")
assert [path for path in (old, latest, other) if not row(path).isHidden()] == [old]
library.search.clear()
select(old)
select(other, QtCore.Qt.ControlModifier)
select(other, QtCore.Qt.ControlModifier)
select(old, QtCore.Qt.ShiftModifier)
QtTest.QTest.keyClick(library.list, QtCore.Qt.Key_End, QtCore.Qt.ShiftModifier)
assert library.selected() == other
assert library.list.selectedItems() == [row(other)]
assert row(old).data(DEFAULT_FONT_ROLE)

for mode in ("light", "dark"):
    use_platform_theme(app, mode=mode)
    app.processEvents()
    for path in (old, other):
        option = QtWidgets.QStyleOptionViewItem()
        option.initFrom(library.list)
        library.list.itemDelegate().initStyleOption(option, library.list.indexFromItem(row(path)))
        assert option.icon.isNull() == (path != old)
        assert option.decorationSize == QtCore.QSize(17, 17)

library.default_button.click()
wait_until(lambda: library.job is None)
assert GlobalDefaultsStore().load()[0].run == str(other)
assert row(other).data(DEFAULT_FONT_ROLE) and not row(old).data(DEFAULT_FONT_ROLE)
assert row(old).isHidden()
assert library.list.selectedItems() == [row(other)]
library.show_history.setChecked(True)
assert not row(old).isHidden()
QtCore.QThreadPool.globalInstance().waitForDone()
library.close()
"""
    result = subprocess.run(
        [sys.executable, "-c", program, *map(str, (old, latest, other))],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_SCALE_FACTOR": "1"},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
