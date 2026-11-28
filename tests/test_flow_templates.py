import io
import json
import zipfile
from dataclasses import asdict, replace

import pytest

from inkstruct.assets.resolver import AssetResolver
from inkstruct.document.editing import SourceSession
from inkstruct.document.flow_template import FlowTemplate, NamedField, PageLayout, TextFrame
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.package import TEMPLATE_VERSION, load_package, package_bytes
from inkstruct.document.schema import StyleProfile
from inkstruct.document.styles import FlowStyle
from inkstruct.document.template import Region, template_from_record
from inkstruct.layout.blocks import layout_markdown
from inkstruct.plotter.adapters import plan_from_snapshot
from inkstruct.plotter.export import export_plan


def frame(key="body", x=5, y=5, w=50, h=20, order=1, field="", role="body"):
    return TextFrame(key, key, Region(key, x, y, w, h), "field" if field else role, order, field)


def template(*, start=(), loop=("p1",), layouts=None, fields=(), finish=False):
    layouts = layouts or tuple(PageLayout(k, k, (frame(),)) for k in dict.fromkeys((*start, *loop)))
    return FlowTemplate(
        name="test",
        kind="custom",
        width_mm=120,
        height_mm=120,
        layouts=layouts,
        start_pages=start,
        loop_pages=loop,
        fields=fields,
        finish_cycle=finish,
    )


def render(source, t, **options):
    session = source if isinstance(source, SourceSession) else SourceSession(source)
    doc = parse_markdown(session, field_blocks=True)
    resolver = options.pop("resolver", AssetResolver(builtin_numbers=True))
    flow = options.pop("flow", FlowStyle(template=t))
    return layout_markdown(doc, resolver, flow=flow, **options)


def codes(s):
    return {d.code for d in s.diagnostics if d.severity == "error"}


def test_simple_uses_same_mm_renderer():
    s = SourceSession("123 " * 90)
    t = FlowTemplate(width_mm=80, height_mm=70, margins_mm=(10, 10, 10, 10))
    snap = render(s, t)
    from inkstruct.document.schema import PageProfile

    plain = layout_markdown(
        parse_markdown(s), AssetResolver(builtin_numbers=True), page=PageProfile(80, 70, 10)
    )
    assert len(snap.pages) > 1
    assert [p.paint_ops for p in snap.pages] == [
        tuple(replace(o, execution_domain="template-body") for o in p.paint_ops)
        for p in plain.pages
    ]
    assert not codes(snap)


@pytest.mark.parametrize("finish", [False, True])
def test_start_group_four_layout_cycle_and_completion(finish):
    t = template(
        start=("cover",),
        loop=("1", "2", "3", "4"),
        finish=finish,
        layouts=(
            PageLayout("cover", "cover"),
            *(PageLayout(k, k, (frame(h=10),)) for k in ("1", "2", "3", "4")),
        ),
    )
    snap = render("\n\n".join("123" for _ in range(6)), t)
    names = [p.source_layout for p in snap.pages]
    assert names == (
        ["cover", "1", "2", "3", "4", "1", "2", "3", "4"]
        if finish
        else ["cover", "1", "2", "3", "4", "1", "2"]
    )
    assert [p.index for p in snap.pages] == list(range(len(names)))
    assert not codes(snap)


def test_multi_frame_width_reflow_preserves_identity_and_sample():
    t = template(
        layouts=(
            PageLayout("p1", "p1", (frame("a", w=25, h=20), frame("b", x=60, w=50, h=20, order=2))),
        )
    )
    session = SourceSession("1 2 3 4 5 6 7 8 9 " * 5)
    resolver = AssetResolver(builtin_numbers=True)
    snap = render(session, t, resolver=resolver)
    assert not codes(snap)
    primary = [f for f in snap.fragments if not f.repeated]
    doc = parse_markdown(session, field_blocks=True)
    assert [f.occurrence_id for f in primary] == [o.occurrence_id for o in doc.occurrences]
    assert len({f.x_mm for f in primary if f.x_mm >= 60}) > 2
    before = resolver.selection_records()
    again = render(
        session,
        replace(
            t,
            layouts=(
                replace(
                    t.layouts[0],
                    frames=(frame("a", w=30, h=20), frame("b", x=60, w=50, h=20, order=2)),
                ),
            ),
        ),
        resolver=resolver,
    )
    assert not codes(again)
    assert resolver.selection_records() == before


def test_repeated_fields_and_page_number_do_not_add_pages():
    layouts = tuple(
        PageLayout(
            k,
            k,
            (
                frame("field", y=40, w=50, h=20, field="name"),
                frame("page", y=70, role="page_number"),
            ),
        )
        for k in ("p1", "p2")
    )
    t = template(
        loop=("p1", "p2"), layouts=layouts, fields=(NamedField("name", "姓名", True),), finish=True
    )
    snap = render(":::field name\n123\n:::\n", t)
    assert len(snap.pages) == 2
    assert not codes(snap)
    fields = [f for f in snap.fragments if f.container_id == "template-field:name"]
    assert len(fields) == 6
    assert all(f.repeated for f in fields[3:])
    assert len({f.occurrence_id for f in fields}) == 3


@pytest.mark.parametrize(
    "source,expected",
    [
        (":::field name\n123\n:::\n\n:::field name\n456\n:::", "template-field-duplicate"),
        ("123", "template-field-required"),
        (":::field name\n\n:::", "template-field-required"),
        (":::field other\n123\n:::", "template-field-unknown"),
        (":::field name\n123\n\n456", "template-field-syntax"),
        (":::field name\n:::field other\n123\n:::\n:::", "template-field-syntax"),
    ],
)
def test_protocol_errors(source, expected):
    t = template(fields=(NamedField("name", "姓名", True),))
    snap = render(source, t)
    assert expected in codes(snap)
    assert all(0 <= d.span.start <= d.span.end <= len(source) for d in snap.diagnostics)


def test_code_fence_and_unclosed_field_do_not_swallow_body():
    doc = parse_markdown("```\n:::field name\n123\n:::\n```", field_blocks=True)
    assert not any(n.kind == "named_field" for n in doc.nodes)
    doc = parse_markdown(":::field name\n\n# 123\n\n456", field_blocks=True)
    assert any(n.kind == "heading" for n in doc.nodes)
    assert any(n.kind == "paragraph" for n in doc.nodes)
    assert any(d.code == "template-field-syntax" for d in doc.diagnostics)
    old = parse_markdown(":::field name\n123\n:::")
    assert not any(n.kind == "named_field" for n in old.nodes)


def test_field_overflow_and_optional_missing():
    t = template(
        layouts=(PageLayout("p1", "p1", (frame("f", h=10, field="name"),)),),
        fields=(NamedField("name", "姓名"),),
    )
    snap = render("", t)
    assert len(snap.pages) == 1 and not codes(snap)
    snap = render(":::field name\n" + "123 " * 60 + "\n:::", t)
    assert len(snap.pages) == 1
    assert "template-field-overflow" in codes(snap)
    assert sum(f.text.isdigit() for f in snap.fragments) == 180


def test_full_loop_no_progress_and_later_large_frame():
    from test_math_sample_constructions import resolver

    source = "$$\n\\frac{123}{456}\n$$"
    tiny = template(layouts=(PageLayout("p1", "p1", (frame(w=10, h=3),)),))
    failed = render(source, tiny, resolver=resolver())
    assert "template-body-no-progress" in codes(failed)
    assert len(failed.pages) == 1
    large = replace(
        tiny,
        layouts=(*tiny.layouts, PageLayout("p2", "p2", (frame(w=80, h=60),))),
        loop_pages=("p1", "p2"),
    )
    snap = render(source, large, resolver=resolver())
    assert not codes(snap), snap.diagnostics
    assert len(snap.pages) == 2


def test_empty_body_no_body_frames_and_fields_only_are_finite():
    t = template(layouts=(PageLayout("p1", "p1"),))
    assert len(render("", t).pages) == 1
    assert "template-body-no-progress" in codes(render("123", t))


def test_different_frame_width_table_rows_and_body():
    t = template(
        loop=("p1", "p2"),
        layouts=(
            PageLayout("p1", "p1", (frame(w=20, h=15),)),
            PageLayout("p2", "p2", (frame(w=100, h=75),)),
        ),
    )
    from inkstruct.document.table_style import TableStyle

    flow = FlowStyle(template=t, table=TableStyle(width_mm=60))
    snap = render("|1|2|\n|---|---|\n|3|4|\n|5|6|\n\n123 456", t, flow=flow)
    assert not codes(snap), snap.diagnostics
    assert len(snap.pages) >= 2
    assert any(op.points for p in snap.pages for op in p.paint_ops)


def test_v3_package_frozen_reopen_and_svg(tmp_path):
    session = SourceSession(":::field name\n123\n:::\n\n456 " * 1)
    t = template(
        layouts=(PageLayout("p1", "p1", (frame(), frame("f", y=40, h=20, field="name"))),),
        fields=(NamedField("name", "姓名"),),
    )
    resolver = AssetResolver(builtin_numbers=True)
    flow = FlowStyle(template=t)
    first = render(session, t, resolver=resolver, flow=flow)
    assert not codes(first), first.diagnostics
    raw = package_bytes(session, resolver, first.page_profile, StyleProfile(), flow=flow)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        assert json.loads(archive.read("manifest.json"))["schema_version"] == TEMPLATE_VERSION
    path = tmp_path / "record.inkdoc"
    path.write_bytes(raw)
    loaded = load_package(path)
    second = render(
        loaded.session, loaded.flow.template, resolver=loaded.resolver, flow=loaded.flow
    )
    assert first == second
    export_plan(plan_from_snapshot(second), tmp_path / "svg")
    assert list((tmp_path / "svg").glob("*.svg"))
    assert template_from_record(asdict(t)) == t


def test_schema_unknown_fields_and_bad_order_are_rejected():
    data = asdict(template())
    data["unknown"] = True
    with pytest.raises(TypeError):
        template_from_record(data)
    with pytest.raises(ValueError):
        template(layouts=(PageLayout("p1", "p1", (frame("a"), frame("b", x=60))),))
    with pytest.raises(ValueError):
        template(loop=())


def test_start_group_stops_with_body_and_empty_document_has_explicit_pages():
    t = template(start=("s1", "s2"), loop=("p1",))
    assert [p.source_layout for p in render("123", t).pages] == ["s1"]
    assert [p.source_layout for p in render("", t).pages] == ["s1", "s2"]


def test_explicit_migration_copies_geometry_without_source_guessing():
    from inkstruct.document.flow_template import migrate_layout
    from inkstruct.document.template_authoring import new_template
    from inkstruct.document.template_slots import SlottedPageTemplate, TemplateSlot

    old = new_template()
    old = replace(
        old,
        first=replace(
            old.first,
            body=Region("body", 20, 60, 170, 217),
            reserved=(Region("student", 20, 20, 100, 20),),
        ),
        continuation=replace(
            old.continuation,
            body=Region("body", 20, 60, 170, 217),
            reserved=(Region("other", 20, 20, 100, 20),),
        ),
    )
    migrated = migrate_layout(old)
    assert migrated.layouts[0].frames[1].field_id != migrated.layouts[1].frames[1].field_id
    assert migrated.migration and migrated.layouts[0].frames[0].region == old.first.body
    slotted = SlottedPageTemplate(
        **{
            **asdict(old),
            "schema_version": "inkstruct_page_template_v2",
            "slots": [
                asdict(TemplateSlot("student_id", "学号", "student", kind="text", required=True))
            ],
        }
    )
    assert migrate_layout(slotted).fields[0] == NamedField("student_id", "学号", True, "text")


def test_image_atomicity_reference_gate_and_field_overflow(tmp_path):
    from PIL import Image

    from inkstruct.document.images import ImageStyle, import_local_images

    Image.new("RGB", (80, 60), "blue").save(tmp_path / "plot.png")
    t = template(
        loop=("p1", "p2"),
        layouts=(
            PageLayout("p1", "p1", (frame(w=20, h=10),)),
            PageLayout("p2", "p2", (frame(w=90, h=90),)),
        ),
    )
    session = SourceSession("![1](plot.png)")
    doc = parse_markdown(session, field_blocks=True)
    flow, issues = import_local_images(
        doc, FlowStyle(template=t, image=ImageStyle(width_mm=60)), tmp_path
    )
    assert not issues
    snap = render(session, t, flow=flow)
    assert not codes(snap), snap.diagnostics
    assert len(snap.pages) == 2 and snap.pages[1].images
    assert not snap.plotter_exportable
    too_small = replace(t, layouts=(t.layouts[0],), loop_pages=("p1",))
    failed = render(session, too_small, flow=replace(flow, template=too_small))
    assert "template-body-no-progress" in codes(failed)


def test_correction_cannot_escape_text_frame_inside_paper():
    from inkstruct.document.glyph_corrections import GlyphCorrection

    t = template(layouts=(PageLayout("p1", "p1", (frame(h=10),)),))
    session = SourceSession("123")
    doc = parse_markdown(session, field_blocks=True)
    rule = GlyphCorrection(
        scope="occurrence", character="1", occurrence_id=doc.occurrences[0].occurrence_id, dy_em=1
    )
    snap = render(session, t, flow=FlowStyle(template=t, glyph_corrections=(rule,)))
    assert "template-correction-frame-overflow" in codes(snap)


def test_dialog_source_transaction_preserves_unchanged_identity_and_one_undo():
    s = SourceSession(":::field name\n123\n:::\n\n456 789\n\n:::field x\n12\n:::")
    source = s.source
    body = next(n for n in parse_markdown(s, field_blocks=True).nodes if n.kind == "paragraph")
    ids = tuple(o.occurrence_id for n in body.walk() for o in n.occurrences)
    s.apply_preserving(source.replace("123", "321").replace("\n12\n", "\n21\n"))
    body2 = next(n for n in parse_markdown(s, field_blocks=True).nodes if n.kind == "paragraph")
    assert ids == tuple(o.occurrence_id for n in body2.walk() for o in n.occurrences)
    assert s.undo() and s.source == source
    assert s.redo() and s.source != source


def test_protocol_exact_crlf_emoji_offsets_and_code_inside_field():
    source = (
        ":::field name\r\n😀 123\r\n\r\n```\r\n:::field literal\r\n::: \r\n```\r\n:::\r\n\r\n456"
    )
    doc = parse_markdown(source, field_blocks=True)
    assert not doc.diagnostics
    assert [n.kind for n in doc.nodes] == ["named_field", "paragraph"]
    for occurrence in doc.occurrences:
        assert (
            source[occurrence.span.start : occurrence.span.end].replace("\r\n", "\n")
            == occurrence.text
        )
    assert doc.nodes[-1].span.start == source.index("456")


def test_body_list_code_and_notes_cross_ordered_frames():
    t = template(
        layouts=(
            PageLayout("p1", "p1", (frame("a", w=35, h=40), frame("b", x=60, w=45, h=40, order=2))),
        )
    )
    snap = render(
        "1. 123 456 789 123 456\n2. 789 123 456\n\n123 456\n\n```\n123456\n789\n```",
        t,
    )
    assert not codes(snap), snap.diagnostics
    from collections import Counter

    primary = Counter(f.occurrence_id for f in snap.fragments if not f.repeated)
    assert all(v == 1 for v in primary.values())
    notes = [f for f in snap.fragments if f.container_id and f.container_id.startswith("footnote:")]
    assert not notes


def test_unplaced_field_content_is_not_silently_ignored():
    t = template(fields=(NamedField("name", "姓名"),))
    snap = render(":::field name\n123\n:::\n\n456", t)
    assert "template-field-not-placed" in codes(snap)


def test_v3_cli_authoring_validate_and_preview(tmp_path, capsys):
    from inkstruct.cli import main

    source = tmp_path / "simple.json"
    assert main(["document", "template", "new", "--format", "v3", "--output", str(source)]) == 0
    assert main(["document", "template", "validate", str(source)]) == 0
    assert (
        main(
            ["document", "template", "preview", str(source), "--output", str(tmp_path / "preview")]
        )
        == 0
    )
    assert (tmp_path / "preview/simple.svg").is_file()
    assert main(["document", "template", "new", "--format", "v3", "--output", str(source)]) == 2


def test_table_note_no_progress_stops_before_page_limit():
    from inkstruct.document.table_style import TableStyle

    t = template(layouts=(PageLayout("p1", "p1", (frame(w=60, h=10),)),))
    source = "|1|\n|---|\n|2[^x]|\n\n[^x]: 123 456"
    snap = render(source, t, flow=FlowStyle(template=t, table=TableStyle(width_mm=40)))
    assert "template-body-no-progress" in codes(snap)
    assert len(snap.pages) == 1


def test_preprinted_reference_rules_stay_fixed_and_blank_rules_translate():
    from inkstruct.document.template import TemplateRule

    t = template(
        layouts=(
            PageLayout(
                "p1", "p1", (frame(x=15, y=15),), rules=(TemplateRule("r", ((10, 10), (80, 10))),)
            ),
        )
    )
    t = replace(t, offset_x_mm=2, offset_y_mm=3)
    source=SourceSession('123')
    pre = render(source, t)
    blank = render(source, replace(t, mode="blank"))
    assert pre.pages[0].preview_ops[0].points == ((10, 10), (80, 10))
    assert blank.pages[0].paint_ops[0].points == ((12, 13), (82, 13))
    assert pre.pages[0].fragments == blank.pages[0].fragments


@pytest.mark.parametrize('value,valid',[('2026-10-19',True),('20261019',False),('2026-02-30',False)])
def test_date_field_format_and_calendar_are_checked(value,valid):
    t=template(fields=(NamedField('date','日期',value_type='date'),),layouts=(PageLayout('p1','p1',(frame(field='date'),)),))
    snap=render(':::field date\n'+value+'\n:::',t)
    assert ('template-field-type' not in codes(snap))==valid
