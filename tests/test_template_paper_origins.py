"""Paper calibration is shared with the library and independent of layout revisions."""
from dataclasses import replace
import os
from pathlib import Path
import subprocess
import sys

import pytest

from inkstruct.document.flow_template import FlowTemplate, PageLayout
from inkstruct.document.template_authoring import parse_template, template_json
from inkstruct.document.template_revision import version_template
from inkstruct.plotter.profiles import PageAlignment
from inkstruct.resource_catalog import TemplateStore


def test_calibration_identity_and_concurrent_updates(tmp_path):
    store = TemplateStore(tmp_path / "templates")
    template = version_template(FlowTemplate(kind="custom", layouts=(PageLayout("a", "甲"), PageLayout("b", "乙")),
                                             loop_pages=("a", "b")))
    src = tmp_path / "source.json"
    src.write_text(template_json(template), encoding="utf8")
    entry = store.add(src)
    raw = store.path(entry["id"]).read_bytes()
    a, b = PageAlignment((8, 9)), PageAlignment((25, 30))
    one = store.save_paper_origins(template, template.with_paper_origin("a", a))
    two = store.save_paper_origins(template, template.with_paper_origin("b", b))
    from inkstruct.document.styles import FlowStyle
    assert FlowStyle(template=template).layout_record() == FlowStyle(template=two).layout_record()
    assert one.revision == two.revision == template.revision and len(store.entries()) == 1
    assert two.layout(0).plotter_alignment == a and two.layout(3).plotter_alignment == b
    assert parse_template(template_json(two)) == two and store.path(entry["id"]).read_bytes() == raw
    with pytest.raises(ValueError, match="另一窗口"):
        store.save_paper_origins(template, template.with_paper_origin("a", b))
    current = store.entries()[0]
    assert store.read(current) == two
    edited = store.save_revision(current["id"], replace(two, name="修改后的版式"))
    assert store.read(edited).revision.number == 2 and store.read(edited).layout(1).plotter_alignment == b


@pytest.mark.skipif(sys.platform != "win32", reason="Windows plotter sidebar")
def test_sidebar_origin_keeps_snapshot_and_syncs_library(tmp_path):
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "INKSTRUCT_LAYOUT_PREVIEW_HOME": str(tmp_path / "preview")}
    result = subprocess.run([sys.executable, __file__, str(tmp_path)], env=env, timeout=70,
                            capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stdout + result.stderr


def exercise(root):
    from time import monotonic, sleep
    from unittest.mock import patch
    from PySide6 import QtCore, QtWidgets
    from inkstruct.application import InkStructWindow
    from inkstruct.document.package import save_package
    from inkstruct.editor.machine_alignment import TemplateOriginDialog

    app = QtWidgets.QApplication([])
    QtCore.QSettings.setDefaultFormat(QtCore.QSettings.IniFormat)
    QtCore.QSettings.setPath(QtCore.QSettings.IniFormat, QtCore.QSettings.UserScope, str(root / "settings"))
    shell = InkStructWindow(workspace=root / "workspace")
    shell.show()
    editor = shell.editor
    library = shell.template_library
    template = version_template(FlowTemplate(name="报告", mode="blank"))
    shell.tabs.setCurrentWidget(library)
    source = root / "report.json"
    source.write_text(template_json(template), encoding="utf8")
    library.select_entry(library.store.add(source))
    assert library.template == template
    shell.tabs.setCurrentWidget(editor)
    editor.replace_text("123")
    report = root / "report.inkdoc"
    save_package(report, editor.source_session, editor.resolver, editor.page, editor.style,
                 flow=replace(editor.flow, template=template))
    editor.load_project_path(report)
    editor.machine_dock.show()
    editor.machine_dock.raise_()
    panel = editor.machine_panel

    def wait_ready():
        deadline = monotonic() + 25
        while monotonic() < deadline:
            app.processEvents()
            if panel.current_page_ready() and not editor.timer.isActive() and not editor.worker:
                return
            sleep(.01)
        raise AssertionError(editor.status.text())

    wait_ready()
    snapshot, plan = editor.snapshot, panel.plan

    def pick(dialog):
        dialog.pick(17., 23.)
        dialog.save.click()
        return dialog.result()

    with patch.object(editor, "schedule_layout", wraps=editor.schedule_layout) as schedule:
        with patch.object(TemplateOriginDialog, "exec", pick):
            panel.add_origin_button.click()
        revised = editor.flow.template
        assert revised.revision == template.revision and revised.layout(0).plotter_alignment.a == (17., 23.)
        assert panel.plan is plan and editor.snapshot is snapshot and editor.dirty
        editor.template_content_panel.template_history(False)
        assert editor.flow.template == template
        editor.template_content_panel.template_history(True)
        assert editor.flow.template == revised
        assert not schedule.called and editor.snapshot is snapshot
    shell.tabs.setCurrentWidget(library)
    app.processEvents()
    assert library.template == revised and "17.000" in library.origin_info.text()
    assert len(library.store.entries()) == 1
    shell.tabs.setCurrentWidget(editor)
    assert editor.save_project()
    editor.load_project_path(report)
    wait_ready()
    assert editor.flow.template == revised
    shell.tabs.blockSignals(True)
    shell.close()


if __name__ == "__main__":
    exercise(Path(sys.argv[1]))
