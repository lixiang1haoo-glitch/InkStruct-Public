"""Run the installed editor, native roundtrip, strict SVG and PDF worker without network."""

import argparse
import hashlib
import importlib.metadata
import json
import sys
import time
from dataclasses import replace
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)

    def offline(event, values):
        if event in {"socket.connect", "socket.getaddrinfo"}:
            raise RuntimeError("Offline verification forbids network access")

    sys.addaudithook(offline)
    from PySide6 import QtCore, QtGui, QtTest, QtWidgets

    import inkstruct
    from inkstruct.document.markdown import parse_markdown
    from inkstruct.document.package import load_package, save_package
    from inkstruct.document.template import Region
    from inkstruct.document.template_authoring import new_template, template_json
    from inkstruct.editor.mixed import MixedWindow
    from inkstruct.editor.template_pdf_process import import_pdf
    from inkstruct.editor.template_settings import TemplateSettingsDialog
    from inkstruct.layout.blocks import layout_markdown
    from inkstruct.plotter.adapters import plan_from_snapshot
    from inkstruct.plotter.export import export_plan

    if not getattr(sys, "frozen", False) and not Path(inkstruct.__file__).resolve().is_relative_to(
        Path(sys.prefix).resolve()
    ):
        raise ValueError("请使用离线安装目录 runtime 中的 Python；不能以源码工作区代替已安装包验证")
    app = QtWidgets.QApplication([])

    class SmokeWindow(MixedWindow):
        def write_recovery(self):
            # The fixture belongs to the check directory, never the user's recovery folder.
            pass

    window = SmokeWindow()
    window.show()

    def ready():
        end = time.monotonic() + 20
        while time.monotonic() < end:
            app.processEvents()
            if window.source_error:
                raise ValueError(window.source_error)
            if (
                window.snapshot
                and window.canvas.isEnabled()
                and not window.worker
                and not window.timer.isActive()
            ):
                return
            QtTest.QTest.qWait(10)
        raise ValueError("Installed editor did not finish the preview: " + window.status.text())

    ready()
    if app.focusWidget() is not window.editor:
        raise ValueError("Blank startup did not focus the source editor")
    QtTest.QTest.keyClicks(app.focusWidget(), "12.3")
    ready()
    if window.buffer.raw != "12.3":
        raise ValueError("Blank startup keyboard input did not reach the source")
    app.clipboard().setText("45.6")
    window.editor.selectAll()
    window.findChild(QtWidgets.QToolButton, "paste_source").click()
    ready()
    if window.buffer.raw != "45.6" or window.editor.toPlainText() != "45.6":
        raise ValueError("Source paste button failed")
    window.editor.undo()
    ready()
    if window.buffer.raw != "12.3":
        raise ValueError("Paste undo failed")
    window.replace_text("12.3\n\n| 1 | 2 |\n| --- | --- |\n| 3.4 | 5.6 |\n\n$$\n\\frac{1}{2}\n$$")
    ready()
    if (
        not window.snapshot
        or not window.canvas.isEnabled()
        or not window.snapshot.plotter_exportable
    ):
        raise ValueError(
            "Installed editor failed to build the public numeric fixture: " + window.status.text()
        )
    window.recovery_timer.stop()
    original_source = window.buffer.raw
    original_atoms = window.source_session.atom_ids
    original_pages = window.snapshot.pages
    for use_ime in (False, True):
        event = window.cancelled
        if event.is_set():
            raise ValueError("The accepted request was unexpectedly cancelled")
        cursor = window.editor.textCursor()
        cursor.movePosition(QtGui.QTextCursor.MoveOperation.End)
        window.editor.setTextCursor(cursor)
        if use_ime:
            QtWidgets.QApplication.sendEvent(window.editor, QtGui.QInputMethodEvent("si", []))
            if event.is_set() or window.source_session.atom_ids != original_atoms:
                raise ValueError("IME preedit changed source identity or cancelled work")
        original_apply = window.source_session.apply
        calls = []

        def apply(*args, event=event, original_apply=original_apply, calls=calls, **kwargs):
            if not event.is_set():
                raise ValueError("Old work was not cancelled before source identity mapping")
            calls.append(True)
            return original_apply(*args, **kwargs)

        window.source_session.apply = apply
        try:
            if use_ime:
                commit = QtGui.QInputMethodEvent()
                commit.setCommitString("4")
                QtWidgets.QApplication.sendEvent(window.editor, commit)
            else:
                window.editor.insertPlainText("4")
        finally:
            window.source_session.apply = original_apply
        if len(calls) != 1 or window.buffer.raw != original_source + "4":
            raise ValueError("Installed editor failed to apply the source transaction")
        ready()
        window.editor.undo()
        ready()
        if (
            window.buffer.raw != original_source
            or window.source_session.atom_ids != original_atoms
            or window.snapshot.pages != original_pages
        ):
            raise ValueError("Undo changed original source identity or page geometry")
    # Exercise the shipped controls, so a stale bundle cannot pass using only layout code.
    frozen_snapshot = window.snapshot
    window.resize(1000, 700)
    app.processEvents()
    if window.width() != 1000 or window.height() != 700:
        raise ValueError("Installed editor controls force the window beyond 1000 x 700")
    for index in range(window.zoom.count()):
        window.zoom.setCurrentIndex(index)
        app.processEvents()
        if window.snapshot is not frozen_snapshot:
            raise ValueError("Preview zoom changed the accepted document snapshot")
    template = new_template()
    template = replace(
        template,
        first=replace(template.first, reserved=(Region("sample-field", 20, 10, 60, 10),)),
    )
    dialog = TemplateSettingsDialog(template, document=parse_markdown(window.source_session))
    dialog.show()
    app.processEvents()
    editor = dialog.binding_editor
    if editor.apply_button.isEnabled():
        raise ValueError("Binding is enabled without selected source")
    QtTest.QTest.mouseClick(
        editor.nodes.viewport(),
        QtCore.Qt.LeftButton,
        pos=editor.nodes.visualItemRect(editor.nodes.item(0)).center(),
    )
    if not editor.apply_button.isEnabled():
        raise ValueError("Source selection did not enable binding")
    editor.apply_button.click()
    if len(editor.bindings) != 1 or editor.error.text():
        raise ValueError("Installed template controls failed to bind source")
    editor.nodes.clearSelection()
    if editor.apply_button.isEnabled():
        raise ValueError("Clearing selection left binding enabled")
    dialog.reject()
    dialog.deleteLater()
    export_plan(plan_from_snapshot(window.snapshot), root / "machine", optimize=True)
    save_package(
        root / "smoke.inkdoc",
        window.source_session,
        window.resolver,
        window.page,
        window.style,
        flow=window.flow,
        optimize=True,
    )
    reopened = load_package(root / "smoke.inkdoc")
    snapshot = layout_markdown(
        parse_markdown(reopened.session),
        reopened.resolver,
        page=reopened.page,
        style=reopened.style,
        flow=reopened.flow,
    )
    export_plan(plan_from_snapshot(snapshot), root / "reopened-machine", optimize=True)
    for path in (root / "machine").glob("*.svg"):
        if path.read_bytes() != (root / "reopened-machine" / path.name).read_bytes():
            raise ValueError("Native project roundtrip changed machine SVG")
    # Small public PDF with explicit dimensions, no external assets.
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 400] /Resources << >> /Contents 4 0 R >>",
        b"<< /Length 0 >>\nstream\nendstream",
    ]
    raw = b"%PDF-1.4\n"
    offsets = []
    for i, obj in enumerate(objects, 1):
        offsets.append(len(raw))
        raw += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(raw)
    raw += b"xref\n0 5\n0000000000 65535 f \n" + b"".join(
        f"{v:010d} 00000 n \n".encode() for v in offsets
    )
    raw += f"trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    (root / "reference.pdf").write_bytes(raw)
    pdf = import_pdf(
        {
            "action": "import",
            "path": str(root / "reference.pdf"),
            "template": template_json(new_template()),
            "index": 0,
            "face": "first",
            "mode": "new",
        }
    )
    if pdf["page_count"] != 1:
        raise ValueError("Installed PDF worker failed")
    window.dirty = False
    window.close()
    window.pool.waitForDone(10000)
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
    report = {
        "blank_startup_keyboard_paste_undo": True,
        "installed_module": str(Path(inkstruct.__file__).resolve()),
        "python": sys.version,
        "versions": {
            n: importlib.metadata.version(n)
            for n in ("inkstruct", "numpy", "Pillow", "markdown-it-py", "mdurl", "PySide6")
        },
        "gui_build": True,
        "early_cancellation_on_source_edit": True,
        "early_cancellation_on_ime_commit": True,
        "ime_preedit_preserves_source": True,
        "edit_undo_preserves_identity_and_pages": True,
        "window_1000x700": True,
        "zoom_preserves_snapshot": True,
        "template_binding_selection_guard": True,
        "native_roundtrip_svg_identical": True,
        "pdf_subprocess": True,
        "network_forbidden_in_smoke_parent": True,
        "physical_alignment_verified": False,
        "machine_svg_sha256": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (root / "machine").glob("*.svg")
        },
    }
    (root / "verification.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
