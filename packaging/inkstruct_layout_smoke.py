"""Portable preview check using synthetic fixtures, never user fonts or samples."""
import argparse
import io
import json
import os
import sys
import time
import zipfile
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

from PySide6 import QtCore, QtGui, QtTest, QtWidgets

from inkstruct.application import InkStructWindow
from inkstruct.assets.resolver import AssetResolver
from inkstruct.assets.symbol_provider import adapt_symbol
from inkstruct.document.editing import SourceSession
from inkstruct.document.flow_template import FlowTemplate, PageLayout, TextFrame
from inkstruct.document.han_variation import HanVariation
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.package import load_package, save_package
from inkstruct.document.schema import PageProfile, StyleProfile
from inkstruct.document.styles import FlowStyle
from inkstruct.document.template import Region
from inkstruct.fonts import APP_VERSION
from inkstruct.fonts.core import FontPackage
from inkstruct.fonts.importer import build_font
from inkstruct.global_defaults import GlobalDefaultsStore, LayoutDefaults
from inkstruct.layout.blocks import layout_markdown
from inkstruct.math.parser import parse_math
from inkstruct.math.style import MathStyle
from inkstruct.plotter.adapters import plan_from_snapshot
from inkstruct.plotter.export import export_plan
from inkstruct.plotter.options import ExportOptions
from inkstruct.renderers.pages import export_pages
from inkstruct.settings_dialog import SettingsDialog


def symbols():
    points = {
        "h": [(20,10),(20,80),(35,45),(50,55),(50,80)],
        "−": [(20,45),(40,44),(60,45)],
        "{": [(50,10),(30,10),(30,35),(20,45),(30,55),(30,80),(50,80)],
        "}": [(20,10),(40,10),(40,35),(50,45),(40,55),(40,80),(20,80)],
    }
    points.update({c: [(20,20),(65,25),(40,45),(55,65),(25,75)] for c in "中文测试后文汉字"})
    result = []
    for char, xy in points.items():
        sample = {
            "schema_version": "inkstruct_symbol_sample_v1", "character": char,
            "sample_id": "preview-" + str(ord(char)), "writer_id": "preview-fixture",
            "capture": {"coordinate_space": "logical_px"},
            "guides": {"em_px":100,"origin_x_px":10,"baseline_y_px":80,"math_axis_em":0.25},
            "strokes": [{"points":[{"x":x,"y":y,"t_ms":i*10,"pressure":0.3+i*0.05}
                                    for i,(x,y) in enumerate(xy)]}],
        }
        result.append(adapt_symbol(json.dumps(sample,ensure_ascii=False).encode()))
    return result


def verify_new_features(editor, out, ready, template):
    samples = out/"synthetic-han-samples"
    samples.mkdir()
    for glyph in symbols():
        if glyph.character in "中文测试后文汉字−":
            (samples/(str(ord(glyph.character))+".json")).write_bytes(glyph.original_json)
    font_path = out/"synthetic-han.inkfont"
    build_font(font_path,writer="preview-fixture",name="Synthetic Han validation fixture",symbols=samples)
    font_hash = sha256(font_path.read_bytes()).hexdigest()
    font = FontPackage(font_path)
    font.verify()
    resolver = AssetResolver(embedded=font.glyphs(),builtin_numbers=True)
    page = PageProfile(38,160,5)
    session = SourceSession(r"中文测试 $\frac{1234}{56}$ 后文")
    document = parse_markdown(session)
    left = layout_markdown(document,resolver,page=page,flow=FlowStyle())
    aligned = layout_markdown(document,resolver,page=page,flow=FlowStyle(paragraph_align="justify"))
    assert aligned.plotter_exportable,aligned.diagnostics
    row = [f for f in aligned.fragments if f.line_index==0 and f.asset_id]
    assert [f.text for f in row] == list("中文测试")
    assert abs(row[-1].logical_bounds[2]-33)<1e-8
    assert row[-1].x_mm>next(f.x_mm for f in left.fragments if f.text=="试")
    export_pages(aligned,out/"justified-preview",dpi=140)
    export_plan(plan_from_snapshot(aligned),out/"justified-svg")
    han_session = SourceSession("汉"*12)
    han_doc = parse_markdown(han_session)
    off = layout_markdown(han_doc,resolver,page=page,flow=FlowStyle())
    flow = FlowStyle(paragraph_align="justify",han_variation=HanVariation(enabled=True,seed=314,strength=.4))
    varied = layout_markdown(han_doc,resolver,page=page,flow=flow)
    assert varied.plotter_exportable,varied.diagnostics
    assert varied.pages!=off.pages
    assert varied==layout_markdown(han_doc,resolver,page=page,flow=flow)
    alternate = layout_markdown(han_doc,resolver,page=page,flow=replace(flow,han_variation=replace(flow.han_variation,seed=315)))
    assert alternate.pages!=varied.pages
    frozen_choices = resolver.selection_records()
    path = out/"han-varied.inkdoc"
    save_package(path,han_session,resolver,page,StyleProfile(),flow=flow)
    loaded=load_package(path)
    reopened=layout_markdown(parse_markdown(loaded.session),loaded.resolver,page=loaded.page,style=loaded.style,flow=loaded.flow)
    assert reopened==varied and resolver.selection_records()==frozen_choices
    export_pages(varied,out/"varied-preview",dpi=140)
    export_plan(plan_from_snapshot(varied),out/"varied-svg")
    assert sha256(font_path.read_bytes()).hexdigest()==font_hash

    # Global parameter changes must not replace a document-owned template/page.
    editor.resolver=AssetResolver(builtin_numbers=True)
    editor.flow=FlowStyle(template=template)
    editor.page=template.page
    editor.editor.setPlainText(r"1\framebreak2\newpage3")
    editor.schedule_layout();ready()
    previous_page=editor.page;anchors=editor.source_session.atom_ids
    other=replace(template,name="Other global template",width_mm=130)
    GlobalDefaultsStore().save(LayoutDefaults(flow=FlowStyle(template=other)))
    dialog=SettingsDialog(editor,category="body")
    body=dialog.pages["body"]
    body.han_enabled.setChecked(True);body.han_seed.setValue(314);body.han_strength.setValue(40)
    body.paragraph_align.setCurrentIndex(body.paragraph_align.findData("justify"))
    assert dialog.apply(to_document=True),dialog.error.text();ready()
    assert editor.flow.template is template and editor.page==previous_page
    assert editor.flow.han_variation==HanVariation(enabled=True,seed=314,strength=.4)
    body.han_strength.setValue(35)
    assert dialog.apply(),dialog.error.text();ready()
    assert editor.flow.han_variation.strength==.35 and editor.flow.template is template
    dialog.select("paper");assert dialog.apply(),dialog.error.text();ready()
    assert editor.flow.template is template and editor.page==previous_page
    assert editor.source_session.atom_ids==anchors
    dialog.reject()
    editor.element_inspector.apply_defaults();ready()
    assert editor.flow.template is template and editor.page==previous_page
    explicit=replace(template,name="Explicit replacement",height_mm=125)
    dialog=SettingsDialog(editor,category="paper")
    dialog.pages["paper"].template.set_template(explicit)
    assert dialog.apply(to_document=True),dialog.error.text();ready()
    assert editor.flow.template==explicit
    dialog.reject()

    # Force export uses the real asynchronous GUI handler and writes a gap report.
    editor.flow=FlowStyle();editor.page=PageProfile()
    editor.resolver=AssetResolver(builtin_numbers=True)
    editor.editor.setPlainText("1缺2");editor.schedule_layout();ready(allow_errors=True)
    assert not editor.snapshot.exportable and not editor.machine_export.isEnabled()
    assert editor.force_machine_export.isEnabled()
    editor.force_svg_action.parent().aboutToShow.emit()
    assert editor.force_svg_action.isEnabled()
    before=editor.source_session.identity_record();choices=editor.resolver.selection_records()
    picker=QtWidgets.QFileDialog.getSaveFileName
    configure=editor.configure_svg_export
    message=editor.message_error
    errors=[]
    QtWidgets.QFileDialog.getSaveFileName=lambda *a,**k:(str(out/"forced-svg"),"")
    editor.configure_svg_export=lambda snapshot,force=False:(ExportOptions(tuple(range(len(snapshot.pages))),force=force),False)
    editor.message_error=lambda text:errors.append(str(text))
    try:
        editor.force_svg_action.trigger()
        deadline=time.monotonic()+45
        while editor.export_job is not None and time.monotonic()<deadline:
            QtWidgets.QApplication.processEvents();QtTest.QTest.qWait(10)
        assert editor.export_job is None and not errors,errors
        assert editor.last_export_result["error"] is None,editor.last_export_result
    finally:
        QtWidgets.QFileDialog.getSaveFileName=picker
        editor.configure_svg_export=configure
        editor.message_error=message
    report=json.loads((out/"forced-svg/issues.json").read_text(encoding="utf-8"))
    assert report["forced"] and any(d["code"]=="asset-missing" for d in report["diagnostics"])
    assert (out/"forced-svg/issues.txt").is_file()
    assert before==editor.source_session.identity_record() and choices==editor.resolver.selection_records()
    assert not editor.snapshot.exportable and not editor.machine_export.isEnabled()
    return {"justification":True,"han_variation_seeded":True,"han_seed_changes_shape":True,
            "han_roundtrip_exact":True,"font_package_unchanged":True,"han_font_sha256":font_hash,
            "body_settings_preserve_template_and_page":True,"right_sidebar_preserves_template":True,
            "explicit_template_replacement":True,"force_svg_real_handler":True,
            "force_svg_missing_blank_and_issue_report":True,"force_svg_source_and_choices_unchanged":True,
            "regular_svg_remains_blocked_on_errors":True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(["InkStruct Layout Check"])
    app.setApplicationVersion(APP_VERSION)
    for name in ("arial.ttf", "msyh.ttc"):
        path = Path("C:/Windows/Fonts") / name
        if path.is_file():
            QtGui.QFontDatabase.addApplicationFont(str(path))
    if sys.platform == "win32":
        app.setFont(QtGui.QFont("Microsoft YaHei",9))
    private = Path(os.environ["INKSTRUCT_LAYOUT_PREVIEW_HOME"]).resolve()
    settings = QtCore.QSettings("InkStruct", "InkStruct")
    assert settings.format() == QtCore.QSettings.IniFormat
    assert Path(settings.fileName()).resolve().is_relative_to(private)
    from inkstruct.editor.mixed import recovery_directory
    assert recovery_directory().resolve().is_relative_to(private)
    settings.setValue("preview_smoke_version", APP_VERSION)
    settings.sync()
    assert settings.status() == QtCore.QSettings.NoError
    w = InkStructWindow(workspace=out/"workspace")
    assert "Layout Preview" in w.windowTitle() and APP_VERSION in w.windowTitle()
    assert w.tabs.count() == 4
    w.resize(1200,800)
    w.show()
    w.tabs.setCurrentIndex(3)
    editor = w.editor
    frames = (
        TextFrame("a","A",Region("a",5,5,50,44),order=1),
        TextFrame("b","B",Region("b",65,5,50,44),order=2),
    )
    template = FlowTemplate(kind="custom",name="Preview check",width_mm=120,height_mm=120,
                            layouts=(PageLayout("two","Two frames",frames),),loop_pages=("two",))
    source = r"1\newline2\framebreak3\linebreak4\newpage5\framebreak6\pagebreak7\clearpage8"
    editor.resolver = AssetResolver(builtin_numbers=True)
    editor.flow = FlowStyle(template=template)
    editor.editor.setPlainText(source)
    editor.schedule_layout()

    def ready(*, allow_errors=False):
        stop = time.monotonic()+45
        while time.monotonic()<stop:
            app.processEvents()
            if (editor.snapshot and not editor.timer.isActive() and not editor.worker
                    and editor.canvas.isEnabled() and editor.canvas.viewport_ready()):
                if not allow_errors:
                    assert editor.snapshot.plotter_exportable, editor.snapshot.diagnostics
                return editor.snapshot
            QtTest.QTest.qWait(10)
        raise AssertionError(editor.status.text())

    snapshot = ready()
    values = [f for f in snapshot.fragments if f.text.isdecimal()]
    assert [(f.text,f.page_index,f.x_mm) for f in values] == [
        ("1",0,5),("2",0,5),("3",0,65),("4",0,65),
        ("5",1,5),("6",1,65),("7",2,5),("8",3,5)]
    project = out/"page-frame.inkdoc"
    save_package(project,editor.source_session,editor.resolver,editor.page,editor.style,flow=editor.flow)
    editor.load_project_path(project)
    assert ready().pages == snapshot.pages
    export_pages(snapshot,out/"preview",dpi=120)
    export_plan(plan_from_snapshot(snapshot),out/"machine")
    assert w.grab().save(str(out/"editor.png"))
    editor.flow = FlowStyle()
    editor.schedule_layout()
    ordinary = ready()
    assert len(ordinary.pages) == 4
    assert sum(d.code == "frame-break-inactive" for d in ordinary.diagnostics) == 2

    # Manufacture an exact v1 grammar marker from a new fixture package.
    old = out/"legacy.inkdoc"
    legacy_source = r"1\newpage2\pagebreak3\clearpage4"
    legacy_session = SourceSession(legacy_source)
    save_package(old,legacy_session,AssetResolver(builtin_numbers=True),PageProfile(),StyleProfile(),flow=FlowStyle(template=template))
    with zipfile.ZipFile(old) as archive:
        members = {n:archive.read(n) for n in archive.namelist()}
    manifest = json.loads(members["manifest.json"])
    manifest["dialect"] = manifest["dialect"].replace("/break-commands-v2","/break-commands-v1")
    members["manifest.json"] = json.dumps(manifest).encode()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer,"w") as archive:
        for name,data in members.items():
            archive.writestr(name,data)
    old.write_bytes(buffer.getvalue())
    before_hash = sha256(old.read_bytes()).hexdigest()
    editor.load_project_path(old)
    migrated = ready()
    assert editor.project_migration_notice and editor.dirty and editor.session_path is None
    assert [(f.text,f.page_index,f.x_mm) for f in migrated.fragments if f.text.isdecimal()] == [
        ("1",0,5),("2",0,65),("3",1,5),("4",1,65)]
    assert sha256(old.read_bytes()).hexdigest() == before_hash

    glyphs = symbols()
    originals = [g.original_json for g in glyphs]
    resolver = AssetResolver(embedded=glyphs,builtin_numbers=True)
    math_source = r"$\sqrt6$ $\frac12$ $\hbar$ $\overline{12}$ $\underline{3}$ $\left\{\frac12\right\}$" + "\n\n1．2"
    session = SourceSession(math_source)
    math_flow = FlowStyle(math=MathStyle(radical_source="geometric",delimiter_source="sample",fraction_source="sample"))
    math_snapshot = layout_markdown(parse_markdown(session),resolver,flow=math_flow)
    assert math_snapshot.plotter_exportable, math_snapshot.diagnostics
    assert "ℏ" in resolver.pools and "．" in resolver.pools
    assert [g.original_json for g in glyphs] == originals
    assert any(s["character"] == "−" for s in resolver.selection_records())
    math_path = out/"math.inkdoc"
    save_package(math_path,session,resolver,PageProfile(),StyleProfile(),flow=math_flow)
    loaded = load_package(math_path)
    again = layout_markdown(parse_markdown(loaded.session),loaded.resolver,page=loaded.page,style=loaded.style,flow=loaded.flow)
    assert again == math_snapshot
    export_plan(plan_from_snapshot(math_snapshot),out/"math-machine")
    export_pages(math_snapshot,out/"math-preview",dpi=160)
    assert not parse_math(r"\frac1").valid
    assert parse_math(r"\sqrt6").valid and parse_math(r"\frac12").valid
    assert parse_math(r"\begin{aligned}1&2\newline3&4\end{aligned}").valid
    blocked = parse_markdown("|1|\n|---|\n|2\\newpage3\\framebreak4|")
    assert {d.code for d in blocked.diagnostics} >= {"page-break-context","frame-break-context"}
    new_features = verify_new_features(editor,out,ready,template)
    report = {
        **new_features,
        "app_version":APP_VERSION,"frozen":bool(getattr(sys,"frozen",False)),
        "executable":sys.executable,"private_settings":settings.fileName(),"preview_home":str(private),
        "tabs":4,"version_title":True,"async_preview_ready":True,"recovery_private":True,
        "physical_pagination":True,"framebreak_same_page":True,"ordinary_pagination":True,
        "frozen_roundtrip_exact":True,"strict_svg_export":True,"legacy_migration_notice":True,
        "legacy_original_unchanged":True,"legacy_save_as_required":True,
        "math_single_token_arguments":True,"hbar_composed":True,"fullwidth_dot_reuse":True,
        "sampled_accents_and_delimiters":True,"source_glyphs_unchanged":True,
        "math_frozen_roundtrip_exact":True,"blocked_contexts":True,
        "fixtures":"synthetic symbols and builtin digits; no user data; no physical-device claim",
    }
    (out/"verification.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    editor.dirty=False
    w.hide()
    editor.canvas.stop_rendering()
    QtCore.QThreadPool.globalInstance().waitForDone()
    print(json.dumps(report,ensure_ascii=False),flush=True)


if __name__ == "__main__":
    main()
