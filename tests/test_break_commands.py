"""Source-exact line controls, physical pagination and body-frame advances."""

import io
import json
import zipfile
from collections import Counter
from hashlib import sha256

import pytest
from test_flow_templates import frame, render, template

from inkstruct.assets.resolver import AssetResolver
from inkstruct.document.editing import SourceSession
from inkstruct.document.flow_template import PageLayout
from inkstruct.document.markdown import dialect_version, parse_markdown
from inkstruct.document.package import load_package, package_bytes, save_package
from inkstruct.document.resources import inspect_resources
from inkstruct.document.schema import PageProfile, StyleProfile
from inkstruct.document.styles import FlowStyle
from inkstruct.layout.blocks import layout_markdown
from inkstruct.math.parser import parse_math
from inkstruct.plotter.adapters import plan_from_snapshot
from inkstruct.plotter.svg import page_svg


def multi_frame():
    return template(
        layouts=(
            PageLayout(
                "p1",
                "p1",
                (
                    frame("a", x=5, y=5, h=22, order=1),
                    frame("b", x=65, y=5, h=22, order=2),
                ),
            ),
        )
    )


def visible(snapshot):
    return [f for f in snapshot.fragments if f.text.isdecimal()]


@pytest.mark.parametrize("command", ["newline", "linebreak", "linebreak[4]"])
def test_text_line_controls_force_exactly_one_line_and_preserve_source(command):
    source = "1\\" + command + "\r\n2"
    doc = parse_markdown(source)
    assert not doc.diagnostics
    control = next(n for root in doc.nodes for n in root.walk() if n.kind == "hardbreak")
    assert source[control.span.start : control.span.end] == "\\" + command
    result = layout_markdown(doc, AssetResolver(builtin_numbers=True))
    assert result.plotter_exportable, result.diagnostics
    first, second = visible(result)
    assert second.line_index == first.line_index + 1
    assert second.baseline_mm > first.baseline_mm and second.x_mm == first.x_mm
    assert Counter(f.occurrence_id for f in result.fragments) == Counter(
        o.occurrence_id for o in doc.occurrences
    )
    assert not inspect_resources(doc, AssetResolver(builtin_numbers=True))["gaps"]
    plan_from_snapshot(result)


@pytest.mark.parametrize("command", ["framebreak"])
@pytest.mark.parametrize("standalone", [False, True])
def test_frame_commands_advance_to_next_box_on_same_physical_page(command, standalone):
    source = (
        "1" + ("\n" if standalone else "") + "\\" + command + ("\n" if standalone else "") + "2"
    )
    result = render(source, multi_frame())
    assert result.plotter_exportable, result.diagnostics
    first, second = visible(result)
    assert first.page_index == second.page_index == 0
    assert first.x_mm == 5 and second.x_mm == 65
    assert first.baseline_mm == second.baseline_mm
    assert len(result.pages) == 1
    plan_from_snapshot(result)


def test_frame_controls_continue_into_next_page_only_after_last_frame():
    result = render(r"1\framebreak2\framebreak3", multi_frame())
    assert result.plotter_exportable, result.diagnostics
    assert [(f.text, f.page_index, f.x_mm) for f in visible(result)] == [
        ("1", 0, 5),
        ("2", 0, 65),
        ("3", 1, 5),
    ]


def test_leading_consecutive_and_trailing_controls_have_bounded_cursor_semantics():
    leading = render(r"\framebreak1", multi_frame())
    assert visible(leading)[0].x_mm == 65 and len(leading.pages) == 1
    consecutive = render(r"1\framebreak\framebreak2\framebreak", multi_frame())
    assert [(f.text, f.page_index, f.x_mm) for f in visible(consecutive)] == [
        ("1", 0, 5),
        ("2", 1, 5),
    ]
    assert len(consecutive.pages) == 2
    assert len(render(r"\framebreak\framebreak", multi_frame()).pages) == 1


@pytest.mark.parametrize("command", ["framebreak"])
def test_frame_controls_are_inactive_in_ordinary_documents(command):
    result = layout_markdown(
        parse_markdown("1\\" + command + "2"), AssetResolver(builtin_numbers=True)
    )
    assert result.plotter_exportable, result.diagnostics
    first, second = visible(result)
    assert first.page_index == second.page_index == 0 and first.baseline_mm == second.baseline_mm
    assert any(
        d.code == "frame-break-inactive" and d.severity == "warning" for d in result.diagnostics
    )
    standalone = layout_markdown(
        parse_markdown("1\n\\" + command + "\n2"), AssetResolver(builtin_numbers=True)
    )
    assert len(standalone.pages) == 1


@pytest.mark.parametrize("strength", [0, 1, 2, 3])
def test_optional_weak_requests_do_not_force_breaks(strength):
    result = render(
        r"1\linebreak[" + str(strength) + r"]2\pagebreak[" + str(strength) + "]3", multi_frame()
    )
    assert result.plotter_exportable, result.diagnostics
    assert {f.page_index for f in visible(result)} == {0}
    assert {f.x_mm < 65 for f in visible(result)} == {True}
    assert len({f.baseline_mm for f in visible(result)}) == 1


@pytest.mark.parametrize(
    "source", [r"1\linebreak[9]2", r"1\pagebreak[-1]2", r"1\linebreak[bad]2", r"1\pagebreak["]
)
def test_invalid_options_have_precise_diagnostics_and_are_not_captured_as_letters(source):
    doc = parse_markdown(source)
    issue = next(d for d in doc.diagnostics if d.code == "break-command-option")
    assert source[issue.span.start : issue.span.end].startswith("\\")
    assert not layout_markdown(doc, AssetResolver(builtin_numbers=True)).exportable
    assert not any(o.text.isalpha() for o in doc.occurrences)


def test_code_escapes_and_command_boundaries_remain_literal():
    for source in (r"`\newline \newpage \framebreak`", "```tex\n\\clearpage\n```", r"\\newline", r"\newpageX"):
        doc = parse_markdown(source)
        assert not any(
            n.kind in {"hardbreak", "pagebreak", "framebreak"} for root in doc.nodes for n in root.walk()
        )
        assert any(o.text.isalpha() for o in doc.occurrences)
    assert any(
        n.kind == "pagebreak" for root in parse_markdown(r"\newpage{}1").nodes for n in root.walk()
    )


@pytest.mark.parametrize(
    "source",
    [
        "|1|\n|---|\n|2\\newpage3|",

        ":::field box\n1\\clearpage2\n:::\n\n3",
    ],
)
def test_embedded_and_fixed_contexts_do_not_advance_the_body_cursor(source):
    doc = parse_markdown(source, field_blocks=True)
    controls = [n for root in doc.nodes for n in root.walk() if n.kind == "pagebreak"]
    assert controls and all(dict(n.attributes).get("blocked") == "true" for n in controls)
    assert any(d.code == "page-break-context" for d in doc.diagnostics)


@pytest.mark.parametrize("command", [r"\newline", r"\linebreak", r"\linebreak[4]"])
@pytest.mark.parametrize(
    "environment,body", [("aligned", "1&2"), ("matrix", "1&2"), ("cases", "1&2"), ("array", "1&2")]
)
def test_math_multiline_environments_accept_named_row_break_aliases(command, environment, body):
    source = (
        r"\begin{"
        + environment
        + "}"
        + ("{cc}" if environment == "array" else "")
        + body
        + command
        + body
        + r"\end{"
        + environment
        + "}"
    )
    parsed = parse_math(source)
    assert parsed.valid, parsed.diagnostics
    assert (
        len([n for n in parsed.root.walk() if n.kind in {"MatrixRow", "AlignmentRow", "ArrayRow"}])
        == 2
    )
    result = render("$$\n" + source + "\n$$", multi_frame())
    assert result.plotter_exportable, result.diagnostics


@pytest.mark.parametrize("command", ["newline", "linebreak", "newpage", "pagebreak", "clearpage", "framebreak"])
def test_math_controls_outside_multiline_or_body_context_fail_with_actionable_diagnostic(command):
    parsed = parse_math("1\\" + command + "2")
    assert not parsed.valid
    assert parsed.diagnostics[0].code in {"math-line-break-context", "math-frame-break-context", "math-page-break-context"}


def test_frame_commands_nested_in_emphasis_and_list_keep_content_order_and_marker():
    source = "- **1\\framebreak2**\n- 3"
    result = render(source, multi_frame())
    assert result.plotter_exportable, result.diagnostics
    assert [(f.text, f.x_mm < 65) for f in visible(result)] == [
        ("1", True),
        ("2", False),
        ("3", False),
    ]
    assert (
        len(
            [op for p in result.pages for op in p.paint_ops if op.occurrence_id.endswith(":bullet")]
        )
        == 2
    )


def test_frame_and_line_controls_save_reopen_and_export_exactly(tmp_path):
    session = SourceSession(r"1\newline2\newpage3\linebreak4\clearpage5")
    t, resolver = multi_frame(), AssetResolver(builtin_numbers=True)
    flow = FlowStyle(template=t)
    before = layout_markdown(parse_markdown(session, field_blocks=True), resolver, flow=flow)
    assert before.plotter_exportable, before.diagnostics
    path = tmp_path / "controls.inkdoc"
    save_package(path, session, resolver, PageProfile(), StyleProfile(), flow=flow)
    restored = load_package(path)
    after = layout_markdown(
        parse_markdown(restored.session, field_blocks=True),
        restored.resolver,
        page=restored.page,
        style=restored.style,
        flow=restored.flow,
    )
    assert after == before
    plan = plan_from_snapshot(after)
    assert all("<path" in page_svg(page) for page in plan.pages)
    choices = resolver.selection_records()
    pos = session.source.index("newpage")
    session.apply(pos, pos + len("newpage"), "pagebreak")
    changed = layout_markdown(parse_markdown(session, field_blocks=True), resolver, flow=flow)
    geometry = lambda snapshot: [
        (f.text, f.page_index, f.x_mm, f.baseline_mm, f.advance_mm, f.ink_bounds, f.asset_id)
        for f in snapshot.fragments
    ]
    assert geometry(changed) == geometry(before)
    assert [op.points for page in changed.pages for op in page.paint_ops] == [
        op.points for page in before.pages for op in page.paint_ops
    ]
    assert resolver.selection_records() == choices


def test_weak_line_break_hint_allows_a_break_inside_a_numeric_run():
    from inkstruct.layout.inline import break_lines, inline_runs, measure_runs

    document = parse_markdown(r"1\linebreak[1]2")
    runs = inline_runs(document.nodes[0].children[0])
    boxes, diagnostics = measure_runs(runs, AssetResolver(builtin_numbers=True), StyleProfile())
    assert not diagnostics
    lines = break_lines(boxes, max(box.advance for box in boxes) + 0.1)
    assert len(lines) == 2
    assert [box.run.occurrence.text for box in lines[-1]] == ["2"]


def test_manual_controls_in_table_cells_do_not_move_main_flow():
    source = "1\\framebreak2\n\n|3|\n|---|\n|4\\newline5\\framebreak6|"
    from inkstruct.document.table_style import TableStyle

    t = template(
        layouts=(
            PageLayout(
                "p1",
                "p1",
                (
                    frame("a", x=5, y=5, h=100, order=1),
                    frame("b", x=65, y=5, h=100, order=2),
                ),
            ),
        )
    )
    result = render(source, t, flow=FlowStyle(template=t, table=TableStyle(width_mm=45)))
    assert not any(d.severity == "error" for d in result.diagnostics), result.diagnostics
    first = next(f for f in visible(result) if f.span.start == 0)
    second = next(f for f in visible(result) if f.text == "2")
    assert first.x_mm < 65 <= second.x_mm and first.page_index == second.page_index
    assert any(d.code == "frame-break-context" for d in result.diagnostics)


def test_weak_controls_preserve_following_space_and_require_no_resources():
    source = r"1\linebreak[1] 2\pagebreak[1] 3"
    doc = parse_markdown(source)
    assert not inspect_resources(doc, AssetResolver(builtin_numbers=True))["gaps"]
    result = layout_markdown(doc, AssetResolver(builtin_numbers=True))
    assert result.plotter_exportable, result.diagnostics
    one, two, three = visible(result)
    assert two.x_mm - one.x_mm > one.advance_mm
    assert three.x_mm - two.x_mm > two.advance_mm


def test_html_cells_support_lines_but_never_advance_body_frames():
    from inkstruct.document.table_style import TableStyle

    source = r"<table><tr><td>1\newline2\linebreak[4]3\newpage4</td></tr></table>"
    doc = parse_markdown(source)
    assert not [d for d in doc.diagnostics if d.severity == "error"], doc.diagnostics
    assert any(d.code == "page-break-context" for d in doc.diagnostics)
    assert not any(o.text.isalpha() for o in doc.occurrences)
    nodes = [n.node_id for root in doc.nodes for n in root.walk()]
    assert len(set(nodes)) == len(nodes)
    result = layout_markdown(
        doc, AssetResolver(builtin_numbers=True), flow=FlowStyle(table=TableStyle(width_mm=45))
    )
    assert result.plotter_exportable, result.diagnostics
    one, two, three, four = visible(result)
    assert one.baseline_mm < two.baseline_mm < three.baseline_mm == four.baseline_mm
    assert not inspect_resources(doc, AssetResolver(builtin_numbers=True))["gaps"]
    code = parse_markdown(r"<table><tr><td><code>\newline</code></td></tr></table>")
    assert not any(n.kind == "hardbreak" for root in code.nodes for n in root.walk())


def test_fixed_named_field_never_advances_its_frame_or_body_cursor():
    from inkstruct.document.flow_template import NamedField

    t = template(
        fields=(NamedField("box", "Fixed"),),
        layouts=(
            PageLayout(
                "p1",
                "p1",
                (
                    frame("a", x=5, y=5, h=22, order=1),
                    frame("b", x=65, y=5, h=22, order=2),
                    frame("fixed", x=5, y=50, h=22, field="box"),
                ),
            ),
        ),
    )
    result = render(":::field box\n1\\framebreak2\n:::\n\n3\\framebreak4", t)
    assert result.plotter_exportable, result.diagnostics
    one, two = sorted((f for f in visible(result) if f.text in "12"), key=lambda f: f.text)
    three = next(f for f in visible(result) if f.text == "3")
    four = next(f for f in visible(result) if f.text == "4")
    assert one.baseline_mm == two.baseline_mm and one.x_mm < two.x_mm < 65
    assert three.x_mm == 5 and four.x_mm == 65 and len(result.pages) == 1
    assert any(d.code == "frame-break-context" for d in result.diagnostics)


def test_live_edit_and_undo_with_measurement_and_continuation_caches():
    from inkstruct.layout.continuation import ContinuationCache, continuation_scope
    from inkstruct.layout.measurement_cache import MeasurementCache, measurement_scope

    session = SourceSession("12\\newline34\n\n56\\newpage78")
    resolver = AssetResolver(builtin_numbers=True)
    mc, cc = MeasurementCache(), ContinuationCache()

    def parity(flow):
        document = parse_markdown(session, field_blocks=True)
        baseline = layout_markdown(document, resolver, flow=flow)
        with measurement_scope(mc), continuation_scope(cc):
            cached = layout_markdown(document, resolver, flow=flow)
        assert cached == baseline
        return cached

    for flow in (FlowStyle(), FlowStyle(template=multi_frame())):
        original = parity(flow)
        start = session.source.index("newline")
        session.apply(start, start + len("newline"), "linebreak")
        parity(flow)
        session.undo()
        restored = parity(flow)
        assert restored.pages == original.pages



def test_list_label_follows_a_leading_frame_control():
    result = render("- \\framebreak\n  1", multi_frame())
    assert result.plotter_exportable, result.diagnostics
    one = visible(result)[0]
    assert one.x_mm >= 65
    bullets = [(page.index, op) for page in result.pages for op in page.paint_ops
               if op.occurrence_id.endswith(":bullet")]
    assert len(bullets) == 1 and bullets[0][0] == one.page_index
    assert min(x for x, _ in bullets[0][1].points) > 65


@pytest.mark.parametrize("command", ["newpage", "pagebreak", "pagebreak[4]", "clearpage"])
@pytest.mark.parametrize("standalone", [False, True])
@pytest.mark.parametrize("with_template", [False, True])
def test_page_controls_advance_physical_page_and_skip_remaining_frames(command, standalone, with_template):
    source = "1" + ("\n" if standalone else "") + "\\" + command + ("\n" if standalone else "") + "2"
    flow = FlowStyle(template=multi_frame()) if with_template else FlowStyle()
    doc = parse_markdown(source, field_blocks=True)
    result = layout_markdown(doc, AssetResolver(builtin_numbers=True), flow=flow)
    assert result.plotter_exportable, result.diagnostics
    first, second = visible(result)
    assert (first.page_index, second.page_index) == (0, 1)
    assert first.x_mm == second.x_mm and first.baseline_mm == second.baseline_mm
    assert len(result.pages) == 2
    control = next(n for root in doc.nodes for n in root.walk() if n.kind == "pagebreak")
    assert source[control.span.start:control.span.end] == "\\" + command
    plan_from_snapshot(result)


def test_page_and_frame_controls_can_be_mixed_without_aliasing():
    result = render(r"1\framebreak2\newpage3\framebreak4\pagebreak5\clearpage6", multi_frame())
    assert result.plotter_exportable, result.diagnostics
    assert [(f.text, f.page_index, f.x_mm) for f in visible(result)] == [
        ("1", 0, 5), ("2", 0, 65), ("3", 1, 5),
        ("4", 1, 65), ("5", 2, 5), ("6", 3, 5),
    ]


@pytest.mark.parametrize("with_template", [False, True])
def test_page_controls_on_empty_pages_and_at_end_do_not_emit_blank_pages(with_template):
    flow = FlowStyle(template=multi_frame()) if with_template else FlowStyle()
    result = layout_markdown(
        parse_markdown(r"\newpage\clearpage1\pagebreak\newpage2\clearpage"),
        AssetResolver(builtin_numbers=True), flow=flow,
    )
    assert result.plotter_exportable, result.diagnostics
    assert [(f.text, f.page_index) for f in visible(result)] == [("1", 0), ("2", 1)]
    assert len(result.pages) == 2
    only_controls = layout_markdown(
        parse_markdown(r"\newpage\clearpage"), AssetResolver(builtin_numbers=True), flow=flow,
    )
    assert len(only_controls.pages) == 1


def test_page_break_after_empty_frame_still_respects_content_on_current_physical_page():
    result = render(r"1\framebreak\newpage2", multi_frame())
    assert result.plotter_exportable, result.diagnostics
    assert [(f.text, f.page_index, f.x_mm) for f in visible(result)] == [("1", 0, 5), ("2", 1, 5)]


def test_page_break_skips_template_pages_without_body_frames():
    t = template(
        start=("body", "blank"), loop=("body",),
        layouts=(PageLayout("body", "body", multi_frame().layouts[0].frames),
                 PageLayout("blank", "blank")),
    )
    result = render(r"1\newpage2", t)
    assert result.plotter_exportable, result.diagnostics
    assert [(f.text, f.page_index) for f in visible(result)] == [("1", 0), ("2", 2)]
    assert len(result.pages) == 3


@pytest.mark.parametrize("command", ["newpage", "pagebreak", "clearpage", "framebreak"])
def test_flow_controls_are_blocked_in_html_cells_only(command):
    source = r"1[^a]" + "\n\n<table><tr><td>2\\" + command + "3</td></tr></table>\n\n[^a]: 4\\" + command + "5"
    doc = parse_markdown(source, field_blocks=True)
    controls = [n for root in doc.nodes for n in root.walk() if n.kind in {"pagebreak", "framebreak"}]
    assert len(controls) == 2
    assert [dict(n.attributes).get("blocked") == "true" for n in controls] == [True, False]
    assert sum(d.code.endswith("break-context") for d in doc.diagnostics) == 1


def _historical_package(session, resolver, flow, suffix):
    data = package_bytes(session, resolver, PageProfile(), StyleProfile(), flow=flow)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    manifest = json.loads(members["manifest.json"])
    manifest["dialect"] = dialect_version(flow.markdown_dialect).removesuffix("/break-commands-v2") + suffix
    members["manifest.json"] = json.dumps(manifest).encode("utf-8")
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, value in members.items():
            archive.writestr(name, value)
    return output.getvalue()


@pytest.mark.parametrize("dialect", ["markdown"])
def test_legacy_paging_aliases_migrate_explicitly_without_modifying_original_or_choices(tmp_path, dialect):
    session = SourceSession(r"1\newpage2\pagebreak[4]3\clearpage4")
    resolver = AssetResolver(builtin_numbers=True)
    flow = FlowStyle(template=multi_frame(), markdown_dialect=dialect)
    before_doc = parse_markdown(session, dialect=dialect, field_blocks=True)
    layout_markdown(before_doc, resolver, flow=flow)
    selections = resolver.selection_records()
    path = tmp_path / "legacy.inkdoc"
    data = _historical_package(session, resolver, flow, "/break-commands-v1")
    path.write_bytes(data)
    loaded = load_package(path)
    assert path.read_bytes() == data and loaded.file_hash == sha256(data).hexdigest()
    assert loaded.session.source == r"1\framebreak{}2\framebreak{}3\framebreak{}4"
    assert "3" in loaded.migration_notice and "另存" in loaded.migration_notice
    after_doc = parse_markdown(loaded.session, dialect=dialect, field_blocks=True)
    assert [o.occurrence_id for o in before_doc.occurrences] == [o.occurrence_id for o in after_doc.occurrences]
    result = layout_markdown(after_doc, loaded.resolver, flow=loaded.flow)
    assert result.plotter_exportable, result.diagnostics
    assert [(f.text, f.page_index, f.x_mm) for f in visible(result)] == [
        ("1", 0, 5), ("2", 0, 65), ("3", 1, 5), ("4", 1, 65),
    ]
    assert loaded.resolver.selection_records() == selections
    assert not loaded.session.undo()
    migrated = tmp_path / "migrated.inkdoc"
    save_package(migrated, loaded.session, loaded.resolver, loaded.page, loaded.style, flow=loaded.flow)
    reopened = load_package(migrated)
    assert reopened.session.source == loaded.session.source and not reopened.migration_notice
    assert path.read_bytes() == data


def test_legacy_migration_preserves_code_escaping_weak_options_and_command_boundaries(tmp_path):
    source = r"1\pagebreak[4]abc `\newpage` \\newpage \newpageX \pagebreak[2]2" + "\n\n```tex\n\\clearpage\n```"
    session, resolver, flow = SourceSession(source), AssetResolver(), FlowStyle()
    path = tmp_path / "legacy.inkdoc"
    path.write_bytes(_historical_package(session, resolver, flow, "/break-commands-v1"))
    loaded = load_package(path)
    assert loaded.session.source == source.replace(r"\pagebreak[4]", r"\framebreak{}")
    assert len(loaded.migration_notice) > 0


@pytest.mark.parametrize("dialect", ["markdown"])
@pytest.mark.parametrize("suffix", ["", "/break-commands-v1", "/break-commands-v2"])
def test_known_historical_grammars_without_controls_open_unchanged(tmp_path, dialect, suffix):
    session, resolver = SourceSession("123"), AssetResolver(builtin_numbers=True)
    flow = FlowStyle(markdown_dialect=dialect)
    path = tmp_path / "known.inkdoc"
    path.write_bytes(_historical_package(session, resolver, flow, suffix))
    loaded = load_package(path)
    assert loaded.session.source == "123" and not loaded.migration_notice
    assert loaded.session.atom_ids == session.atom_ids


def test_unknown_grammar_is_still_rejected(tmp_path):
    path = tmp_path / "unknown.inkdoc"
    path.write_bytes(_historical_package(SourceSession("1"), AssetResolver(), FlowStyle(), "/break-commands-v999"))
    with pytest.raises(ValueError, match="Unsupported document package or dialect"):
        load_package(path)




def test_migration_keeps_leading_control_anchor_and_ordered_marker_choices(tmp_path):
    session = SourceSession(r"1. \newpage{}2")
    resolver = AssetResolver(builtin_numbers=True)
    flow = FlowStyle(template=multi_frame())
    render(session, multi_frame(), resolver=resolver)
    choices = resolver.selection_records()
    slash = session.source.index("\\")
    path = tmp_path / "list.inkdoc"
    path.write_bytes(_historical_package(session, resolver, flow, "/break-commands-v1"))
    loaded = load_package(path)
    assert loaded.session.atom_ids[slash] == session.atom_ids[slash]
    result = render(loaded.session, multi_frame(), resolver=loaded.resolver)
    assert result.plotter_exportable, result.diagnostics
    assert loaded.resolver.selection_records() == choices
    assert next(f for f in visible(result) if f.text == "2").x_mm >= 65


@pytest.mark.parametrize("command", ["newpage", "pagebreak", "pagebreak[4]", "clearpage", "framebreak"])
def test_legacy_fixed_region_bindings_ignore_both_flow_controls(command):
    from test_template_fields import setup

    source = "1\\" + command + "2\n\n3"
    session, document, resolver, flow = setup(source)
    result = layout_markdown(document, resolver, flow=flow)
    assert result.plotter_exportable, result.diagnostics
    assert len(result.pages) == 1
    fixed = [f for f in visible(result) if f.container_id == "template-field:header"]
    assert [f.text for f in fixed] == ["1", "2"]
    assert fixed[0].baseline_mm == fixed[1].baseline_mm
    code = "frame-break-context" if command == "framebreak" else "page-break-context"
    assert any(d.code == code for d in result.diagnostics)
    assert session.source == source
