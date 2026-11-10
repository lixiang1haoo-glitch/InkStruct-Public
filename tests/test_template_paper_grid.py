import json
from dataclasses import replace

import pytest
from test_document_layout import provider
from inkstruct.assets.resolver import AssetResolver
from inkstruct.document.flow_template import FlowTemplate, PageLayout, PaperGrid, TextFrame
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.schema import StyleProfile
from inkstruct.document.styles import FlowStyle
from inkstruct.document.table_style import TableStyle
from inkstruct.document.template import Region
from inkstruct.document.template_authoring import parse_template, template_json
from inkstruct.document.template_revision import version_template
from inkstruct.layout.blocks import layout_markdown
from inkstruct.math.style import MathStyle


STYLE = StyleProfile(em_mm=5, line_height_mm=6)
FRACTION = r"\frac{\frac{1}{2}}{\frac{3}{4}}"


def template(grid=None, height=44):
    frame = TextFrame("body", "正文框 1", Region("body", 5, 10, 90, height), paper_grid=grid)
    layout = PageLayout("paper", "信纸", (frame,))
    return FlowTemplate(kind="custom", width_mm=100, height_mm=80, layouts=(layout,), loop_pages=("paper",))


def layout(source, paper):
    resolver = AssetResolver(generated=provider("甲乙丙丁后一二三表头"), builtin_numbers=True)
    return layout_markdown(parse_markdown(source), resolver,
                           style=STYLE, flow=FlowStyle(template=paper, table=TableStyle(width_mm=80),
                                                       math=MathStyle(fraction_source="geometric")))


def find(snapshot, text):
    return next(item for item in snapshot.fragments if item.text == text)


def horizontal_table_rules(page):
    return sorted({
        round(op.points[0][1], 6)
        for op in page.paint_ops
        if ":border:" in op.occurrence_id and op.points[0][1] == op.points[-1][1]
    })


def test_default_frame_record_and_revision_are_unchanged():
    original = version_template(template())
    record = json.loads(template_json(original))
    assert "paper_grid" not in record["template"]["layouts"][0]["frames"][0]
    reopened = parse_template(json.dumps(record))
    assert reopened == original
    assert template_json(reopened) == template_json(original)
    paper = template(PaperGrid(7, 34, 4))
    assert parse_template(template_json(paper)) == paper
    with pytest.raises(ValueError, match="基线"):
        template(PaperGrid(7, 46, 4))


def test_ordinary_baselines_follow_grid_and_keep_original_size():
    source = "甲\n\n乙\n\n丙"
    plain = layout(source, template())
    lined = layout(source, replace(template(PaperGrid(7, 34, 4)), offset_y_mm=1))
    assert [find(lined, c).baseline_mm for c in "甲乙丙"] == pytest.approx([18, 27, 36])
    assert [find(lined, c).glyph_em_mm for c in "甲乙丙"] == [find(plain, c).glyph_em_mm for c in "甲乙丙"]


def test_display_formula_moves_to_next_page_and_inline_line_uses_multiple_slots():
    paper = template(PaperGrid(7, 25, 3))
    display = layout(f"甲\n\n乙\n\n$$\n{FRACTION}\n$$\n\n丙", paper)
    assert [find(display, c).page_index for c in "甲乙丙"] == [0, 0, 2]
    assert find(display, "1").page_index == 1
    assert find(display, "丙").baseline_mm == pytest.approx(17)
    inline = layout(f"甲 ${FRACTION}$\n\n乙", template(PaperGrid(7, 43, 5), 48))
    first, following = (find(inline, c) for c in "甲乙")
    assert first.page_index == following.page_index == 0
    assert following.baseline_mm >= 35
    assert (following.baseline_mm - 17) % 9 == pytest.approx(0)


def test_repeat_table_header_counts_toward_grid_and_next_text_resumes_on_a_baseline():
    source = "| 表 | 头 |\n| --- | --- |\n" + "| 一 | 二 |\n" * 11 + "\n后"
    result = layout(source, template(PaperGrid(7, 43, 5), 48))
    headers = [f for f in result.fragments if f.text == "表"]
    assert [f.page_index for f in headers] == [0, 1, 2, 3]
    assert not headers[0].repeated and all(f.repeated for f in headers[1:])
    assert horizontal_table_rules(result.pages[0]) == pytest.approx([17, 26, 35, 44, 53])
    assert horizontal_table_rules(result.pages[3]) == pytest.approx([17, 26, 35, 44])
    following = find(result, "后")
    assert following.baseline_mm == pytest.approx(53)
    assert following.page_index == headers[-1].page_index
    assert not any(d.code == "template-body-no-progress" for d in result.diagnostics)


def test_tall_cell_rounds_up_and_remeasures_in_the_next_frame():
    paper = template(PaperGrid(7, 61, 7), 66)
    continuation = paper.layouts[0].frames[0]
    first = replace(continuation, frame_id="first", region=Region("body", 5, 5, 90, 9),
                    paper_grid=PaperGrid(5, 5, 1))
    second = replace(continuation, order=2, region=Region("body", 5, 14, 90, 66))
    paper = replace(paper, height_mm=85, layouts=(replace(paper.layouts[0], frames=(first, second)),))
    source = f"| 表 | 头 |\n| --- | --- |\n| ${FRACTION}$ | 甲 |\n\n后"
    result = layout(source, paper)
    assert result.exportable
    assert len(result.pages) == 1
    rules = horizontal_table_rules(result.pages[0])
    assert rules[:2] == pytest.approx([21, 30])
    assert rules[-1] - rules[-2] > 9
    assert (rules[-1] - rules[-2]) % 9 == pytest.approx(0)
    assert find(result, "后").baseline_mm == pytest.approx(rules[-1] + 9)


def test_impossible_formula_stops_with_location_and_required_size():
    source = f"甲\n\n$$\n{FRACTION}\n$$\n\n乙"
    result = layout(source, template(PaperGrid(5, 5, 1), 8))
    assert len(result.pages) == 1 and find(result, "甲").page_index == 0
    assert not any(f.text == "乙" for f in result.fragments)
    error = next(d for d in result.diagnostics if d.code == "template-body-no-progress")
    assert "正文框 1" in error.message and "需要" in error.message and "mm" in error.message
    assert source[error.span.start:error.span.end].lstrip().startswith("$$")
    assert not result.exportable
