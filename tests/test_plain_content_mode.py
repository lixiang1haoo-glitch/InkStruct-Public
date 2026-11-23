"""The literal content mode uses the normal font, template, and output pipeline."""
import json
import re
import time
from xml.etree import ElementTree
import zipfile

import pytest

from inkstruct.assets.resolver import AssetResolver
from inkstruct.document.editing import SourceSession
from inkstruct.document.flow_template import PageLayout
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.package import load_package, save_package
from inkstruct.document.schema import PageProfile, StyleProfile
from inkstruct.document.styles import FlowStyle
from inkstruct.layout.blocks import layout_markdown
from test_flow_templates import frame, template
from test_symbol_provider import specimen


TEXT = "    实验报告\n\n姓名    日期\n# **原样** $x$ ![图](不存在.png)"


@pytest.fixture
def font(tmp_path):
    from inkstruct.fonts.importer import build_font

    samples = tmp_path / "symbols.zip"
    with zipfile.ZipFile(samples, "w") as archive:
        for char in sorted(set(TEXT) - {" ", "\n"}):
            name = str(ord(char))
            archive.writestr(f"symbols/{name}.json", json.dumps(specimen(char, name)))
    output = tmp_path / "literal.inkfont"
    build_font(output, name="literal", writer="fixture", symbols=samples)
    return output


def body_flow():
    return FlowStyle(content_mode="plain-text", paragraph_align="justify", template=template(
        start=("first",), loop=("loop",), layouts=(
            PageLayout("first", "first", (frame(w=100, h=18),)),
            PageLayout("loop", "loop", (frame(x=9, w=100, h=18),)),
        )))


def test_literal_syntax_source_spans_and_blank_lines():
    raw = "# 标题\r\n\r\n　- **a** $x^2$ [a](b) ![图](不存在.png) <b> [[双链]]\n:::field demo\n:::"
    session = SourceSession(raw)
    parsed = parse_markdown(session, dialect="plain-text", field_blocks=True)
    assert ["".join(o.text for o in node.children[0].occurrences) for node in parsed.nodes] == raw.splitlines()
    assert all(o.text == raw[o.span.start:o.span.end] for o in parsed.occurrences)
    assert {node.kind for top in parsed.nodes for node in top.walk()} == {"paragraph", "literal_text"}
    old_ids = [o.occurrence_id for o in parsed.occurrences]
    session.apply(0, 0, "前")
    assert [o.occurrence_id for o in parse_markdown(session, dialect="plain-text").occurrences][1:] == old_ids
    assert parse_markdown(session.source[1:]).nodes[0].kind == "heading"
    missing = layout_markdown(parsed, AssetResolver(), flow=FlowStyle(content_mode="plain-text"))
    assert any(d.span and raw[d.span.start:d.span.end] == "#" for d in missing.diagnostics)
    assert not any(d.code.startswith("image-") for d in missing.diagnostics)
    spaced = parse_markdown("1\n\n　1", dialect="plain-text")
    snap = layout_markdown(spaced, AssetResolver(builtin_numbers=True),
                           flow=FlowStyle(content_mode="plain-text", first_line_indent_mm=12,
                                          paragraph_gap_mm=10, paragraph_align="justify"))
    first, last = [f for f in snap.fragments if f.text == "1"]
    assert last.baseline_mm - first.baseline_mm == pytest.approx(2 * StyleProfile().line_height_mm)
    assert last.x_mm - first.x_mm == pytest.approx(StyleProfile().em_mm)


def test_two_page_font_project_visual_and_machine_coordinates(tmp_path, font):
    from matplotlib import rc_context
    from inkstruct.editor.mixed import build_markdown
    from inkstruct.plotter.adapters import plan_from_snapshot
    from inkstruct.plotter.grbl import GrblLink, MotionControl
    from test_plotter_machine import SimulatedGrbl
    from inkstruct.plotter.parallel import ExportControl
    from inkstruct.plotter.physical import PaperRegistration, WorkArea, position_page
    from inkstruct.plotter.svg import page_svg
    from inkstruct.renderers.pages import page_draw
    from inkstruct.renderers.visual_export import export_visual

    session = SourceSession(TEXT)
    page, style, flow = PageProfile(), StyleProfile(), body_flow()
    data = build_markdown(session, 1, AssetResolver(), str(font), "", page, style, flow, None)
    snapshot = data["snapshot"]
    assert snapshot.plotter_exportable and len(snapshot.pages) == 2
    first = snapshot.pages[0].fragments
    assert "".join(f.text for f in first) == TEXT.splitlines()[0]
    assert [f.logical_bounds[0] for f in first[:5]] == pytest.approx([5, 8, 11, 14, 17])
    assert snapshot.pages[1].fragments[0].logical_bounds[0] == pytest.approx(9)
    for fragment in snapshot.fragments:
        if fragment.text.isspace():
            assert fragment.ink_bounds is None and fragment.asset_id is None
    for path in (tmp_path / "first.inkdoc", tmp_path / "copy.inkdoc"):
        save_package(path, session, data["resolver"], page, style, flow=flow)
        restored = load_package(path)
        assert restored.flow == flow and restored.session.source == TEXT
        rerender = build_markdown(restored.session, 1, restored.resolver, "", "",
                                  restored.page, restored.style, restored.flow, None)
        assert rerender["snapshot"].pages == snapshot.pages

    pdf = tmp_path / "literal.pdf"
    with rc_context({"pdf.compression": 0}):
        export_visual(snapshot, pdf, (0, 1), "pdf", control=ExportControl(), progress=lambda *_: None)
    pdf_points = {(round(float(x), 4), round(float(y), 4))
                  for x, y in re.findall(rb"(?m)^([\d.]+) ([\d.]+) [ml]\s*$", pdf.read_bytes())}
    for i, plotted in enumerate(plan_from_snapshot(snapshot).pages):
        draw = page_draw(snapshot, i, False)
        machine = position_page(plotted, PaperRegistration((0, 0)))
        serial = SimulatedGrbl()
        landings = []
        def on_write(command):
            serial.run_reports = 0
            if command.startswith(b"G1 Z-"):
                landings.append(tuple(serial.position[:2]))
        serial.on_write = on_write
        controller = GrblLink(serial)
        controller.connect()
        controller.run_page(machine, WorkArea(0, 0, draw.width_mm, draw.height_mm), MotionControl())
        for landing, op in zip(landings, draw.strokes, strict=True):
            assert landing == pytest.approx(op.points[0], abs=.0001)
        paths = ElementTree.fromstring(page_svg(plotted))
        assert len(draw.strokes) == len(machine.strokes) == len(paths)
        for stroke, placed, path in zip(draw.strokes, machine.strokes, paths, strict=True):
            svg_points = re.findall(r"[ML] ([\d.]+) ([\d.]+)", path.attrib["d"])
            for (x, y), actual, pair in zip(stroke.points, placed.points, svg_points, strict=True):
                assert actual == pytest.approx((x, y), abs=.0001)
                assert tuple(map(float, pair)) == pytest.approx((x, y), abs=.00001)
                assert (round(x * 72 / 25.4, 4), round((draw.height_mm - y) * 72 / 25.4, 4)) in pdf_points


def test_editor_input_paste_import_switch_font_save_and_recover(tmp_path, monkeypatch, font):
    from PySide6 import QtCore, QtWidgets
    from inkstruct.global_defaults import GlobalDefaultsStore
    from inkstruct.settings_dialog import SettingsDialog
    from inkstruct.editor.mixed import MixedWindow

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    settings = QtCore.QSettings(str(tmp_path / "defaults.ini"), QtCore.QSettings.Format.IniFormat)
    monkeypatch.setattr(GlobalDefaultsStore, "make_settings", staticmethod(lambda: settings))
    monkeypatch.setattr("inkstruct.editor.mixed.recovery_directory", lambda: tmp_path)
    window = MixedWindow(mode="plain-text")
    window.flow = body_flow()
    window.use_font(font)

    def ready(condition):
        end = time.monotonic() + 30
        while time.monotonic() < end:
            app.processEvents()
            if condition():
                return
            time.sleep(.01)
        pytest.fail(window.status.text())

    def updated():
        return (window.snapshot and window.snapshot.revision == window.revision
                and not window.worker and not window.timer.isActive())

    try:
        assert window.editor.placeholderText() == "输入或粘贴文字"
        window.editor.insertPlainText(TEXT)
        assert window.buffer.raw == TEXT
        window.write_recovery()
        early = load_package(window.recovery_path)
        assert early.session.source == TEXT and early.resolver.font_identity
        window.editor.selectAll()
        app.clipboard().setText(TEXT)
        window.editor.paste()
        assert window.buffer.raw == TEXT
        source = tmp_path / "input.txt"
        source.write_bytes(TEXT.replace("\n", "\r\n").encode())
        monkeypatch.setattr(QtWidgets.QFileDialog, "getOpenFileName", lambda *_: (str(source), ""))
        window.open_text()
        ready(updated)
        assert window.snapshot.plotter_exportable and len(window.snapshot.pages) == 2
        assert window.buffer.raw == source.read_bytes().decode()
        path = tmp_path / "current.inkdoc"
        monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName", lambda *_: (str(path), ""))
        window.save_project_as()
        ready(lambda: window.project_save is None and path.exists())
        window.load_project_path(path)
        ready(updated)
        assert window.mode == "plain-text"
        before = window.snapshot.pages
        for scope in ("defaults", "document"):
            dialog = SettingsDialog(window, category="body", scope=scope)
            picker = dialog.pages["body"].mode
            assert picker.isEnabled()
            target = "plain-text" if scope == "defaults" else "markdown"
            picker.setCurrentIndex(picker.findData(target))
            assert dialog.apply()
            dialog.close()
        assert GlobalDefaultsStore().load()[0].mode == "plain-text"
        assert window.mode == "markdown" and window.session_path == path
        for mode in ("plain-text", "markdown"):
            window.mode_picker.setCurrentIndex(window.mode_picker.findData(mode))
        ready(updated)
        assert any(n.kind == "heading" for n in window.markdown_document.nodes)
        window.mode_picker.setCurrentIndex(window.mode_picker.findData("plain-text"))
        ready(updated)
        assert window.snapshot.pages == before and window.session_path == path
        window.write_recovery()
        recovered = load_package(window.recovery_path)
        assert recovered.session.source == window.buffer.raw
        assert recovered.flow.content_mode == "plain-text" and recovered.resolver.font_identity
    finally:
        window.dirty = False
        window.close()
        app.processEvents()
