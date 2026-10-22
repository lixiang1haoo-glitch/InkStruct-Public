import json
import threading
from collections import Counter
from dataclasses import asdict
from pathlib import Path

import pytest
from test_document_layout import provider

from inkstruct.assets.resolver import AssetResolver
from inkstruct.document.editing import SourceSession
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.schema import PageProfile, StyleProfile
from inkstruct.layout.blocks import layout_markdown
from inkstruct.layout.inline import LayoutCancelled
from inkstruct.plotter.adapters import plan_from_snapshot
from inkstruct.plotter.export import export_plan


def layout(source, *, page=None, style=None, resolver=None):
    document = parse_markdown(source)
    return document, layout_markdown(
        document, resolver or AssetResolver(builtin_numbers=True), page=page, style=style
    )


def test_body_flow_preserves_occurrences_and_generates_only_machine_paths(tmp_path):
    source = (
        "# 123\n\n**1.20** 0.005 `001`\n\n3. 12\n4. 34\n   - 56\n\n> 78\n\n---\n\n"
        + "123 456\n\n" * 12
    )
    document, snapshot = layout(source, page=PageProfile(90, 110, 10))
    assert snapshot.exportable and len(snapshot.pages) >= 2
    source_ids = {o.occurrence_id for o in document.occurrences}
    counts = Counter(f.occurrence_id for f in snapshot.fragments)
    assert all(counts[i] == 1 for i in source_ids)
    assert "".join(f.text for f in snapshot.fragments if ":marker:" in f.occurrence_id) == "3.4."
    ops = [op for p in snapshot.pages for op in p.paint_ops]
    assert any(":underline:" in o.occurrence_id for o in ops)
    assert any(":quote:" in o.occurrence_id for o in ops)
    assert any(":bullet" in o.occurrence_id for o in ops)
    plan = plan_from_snapshot(snapshot)
    export_plan(plan, tmp_path / "machine", optimize=True)
    report = json.loads((tmp_path / "machine" / "plotter.json").read_text())
    assert len(report["pages"]) == len(snapshot.pages)
    assert all(p["after_mm"] <= p["before_mm"] for p in report["pages"])
    for p in snapshot.pages:
        for f in p.fragments:
            if f.ink_bounds:
                x0, y0, x1, y1 = f.ink_bounds
                assert 10 - 1e-9 <= x0 <= x1 <= 80 + 1e-9
                assert 10 - 1e-9 <= y0 <= y1 <= 100 + 1e-9


def test_cjk_softbreak_has_zero_width_and_hardbreak_has_vertical_extent():
    resolver = AssetResolver(provider("人天"))
    _, soft = layout("人\r\n天", resolver=resolver)
    assert soft.fragments[1].advance_mm == 0
    assert soft.fragments[0].baseline_mm == soft.fragments[-1].baseline_mm
    _, hard = layout("人\\\n天", resolver=AssetResolver(provider("人天")))
    assert hard.fragments[0].baseline_mm < hard.fragments[-1].baseline_mm
    _, consecutive = layout("1\\\n\\\n2")
    assert consecutive.fragments[-1].line_index == consecutive.fragments[0].line_index + 2


def test_code_advance_and_underline_are_measured_not_font_effects():
    _, snapshot = layout("**1 2** `1.09`")
    code = snapshot.fragments[-4:]
    assert len({f.advance_mm for f in code}) == 1
    underline = [op for op in snapshot.pages[0].paint_ops if ":underline:" in op.occurrence_id]
    assert len(underline) == 1
    glyph_bottom = max(f.ink_bounds[3] for f in snapshot.fragments[:3] if f.ink_bounds)
    assert underline[0].points[0][1] > glyph_bottom


def test_punctuation_and_numeric_units_do_not_break_in_the_middle():
    source = "人人（天）人人（天）人人"
    _, snapshot = layout(
        source, page=PageProfile(51, 140, 10), resolver=AssetResolver(provider("人天（）"))
    )
    assert snapshot.exportable
    lines = {}
    for fragment in snapshot.fragments:
        lines.setdefault(fragment.line_index, []).append(fragment.text)
    assert len(lines) > 1
    assert all(chars[0] != "）" and chars[-1] != "（" for chars in lines.values())
    _, units = layout(
        "1 1 12.50V", page=PageProfile(70, 100, 10), resolver=AssetResolver(provider("12.50V"))
    )
    assert units.exportable
    suffix = units.fragments[-6:]
    assert "".join(f.text for f in suffix) == "12.50V"
    assert len({f.line_index for f in suffix}) == 1


def test_heading_stays_with_body_and_setext_levels_match_atx():
    _, snapshot = layout("1\n\n2\n\n3\n\n## 4\n\n5", page=PageProfile(80, 74, 10))
    heading = next(f for f in snapshot.fragments if f.text == "4")
    body = next(f for f in snapshot.fragments if f.text == "5")
    assert heading.page_index == body.page_index == 1
    _, atx = layout("## 12")
    _, setext = layout("12\n--")
    assert [f.advance_mm for f in atx.fragments] == [f.advance_mm for f in setext.fragments]


def test_widow_orphan_control_and_atomic_number_overflow():
    _, snapshot = layout("1\n\n" + "1 " * 35, page=PageProfile(55, 64, 10))
    assert snapshot.exportable
    lines_per_page = [len({f.line_index for f in p.fragments}) for p in snapshot.pages]
    assert all(n >= 2 for n in lines_per_page)
    _, overflow = layout("123456789012345678901234567890", page=PageProfile(50, 60, 10))
    assert not overflow.exportable and len(overflow.pages) == 1
    assert any(d.code == "line-width-overflow" for d in overflow.diagnostics)


@pytest.mark.parametrize(
    "source", ["A", "![image](missing.png)", "```\nmissing\n```", r"$\overbrace{1}$"]
)
def test_unsupported_and_missing_content_cannot_silently_export(source):
    _, snapshot = layout(source)
    assert not snapshot.exportable
    assert any(d.severity == "error" for d in snapshot.diagnostics)
    with pytest.raises(ValueError):
        plan_from_snapshot(snapshot)


def test_cancellation_and_too_tall_line_make_bounded_progress():
    cancelled = threading.Event()
    cancelled.set()
    with pytest.raises(LayoutCancelled):
        layout_markdown(
            parse_markdown("123"), AssetResolver(builtin_numbers=True), cancelled=cancelled
        )
    _, snapshot = layout("# 1", page=PageProfile(50, 25, 10), style=StyleProfile(6, 9, 0.3))
    assert len(snapshot.pages) == 1 and not snapshot.exportable
    assert any(d.code == "line-height-overflow" for d in snapshot.diagnostics)


def test_content_key_does_not_include_request_or_revision():
    session = SourceSession("12 34")
    resolver = AssetResolver(builtin_numbers=True)
    first = layout_markdown(parse_markdown(session), resolver)
    session.apply(0, 0, "56 ")
    session.undo()
    second = layout_markdown(parse_markdown(session), resolver)
    assert first.job_key == second.job_key
    assert first.revision < second.revision
    assert [asdict(p) for p in first.pages] == [asdict(p) for p in second.pages]


def test_fixed_f01_nested_body_unit_document_and_missing_resource_boundary():
    source = (Path(__file__).parent / "fixtures/markdown_mixed/F01_body.md").read_text()
    document = parse_markdown(source)
    visible = "".join(o.text for o in document.occurrences)
    resolver = AssetResolver(provider(visible), builtin_numbers=True)
    snapshot = layout_markdown(document, resolver, page=PageProfile(210, 297, 20))
    assert snapshot.exportable and len(snapshot.pages) == 2
    counts = Counter(f.occurrence_id for f in snapshot.fragments)
    assert all(counts[o.occurrence_id] == 1 for o in document.occurrences)
    assert "".join(f.text for f in snapshot.fragments if ":marker:" in f.occurrence_id) == "3.4.5."
    assert any(":quote:1:" in op.occurrence_id for p in snapshot.pages for op in p.paint_ops)
    # The same fixture without resources must expose gaps and block formal export.
    unavailable = AssetResolver(builtin_numbers=True)
    gaps = unavailable.gaps(document.occurrences)
    assert {"V", "A"} <= {g["character"] for g in gaps}
    assert all(g["source_ranges"] for g in gaps)
    blocked = layout_markdown(document, unavailable)
    assert not blocked.exportable
