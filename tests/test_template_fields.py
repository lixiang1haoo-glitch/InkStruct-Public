"""Fixed source fields preserve identity, repeat explicitly and fail closed."""

from collections import Counter
from dataclasses import replace

import pytest
from test_math_layout import resolver
from test_templates import template

from inkstruct.document.editing import SourceSession
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.package import load_package, save_package
from inkstruct.document.schema import StyleProfile
from inkstruct.document.styles import FlowStyle
from inkstruct.document.template import Anchor, Region, TemplateBinding
from inkstruct.layout.blocks import layout_markdown
from inkstruct.plotter.adapters import plan_from_snapshot
from inkstruct.plotter.export import route_page


def setup(source="123\n\n4\n\n5\n\n6\n\n7\n\n8", *, repeat=False, mode="preprinted", **kwargs):
    session = SourceSession(source)
    doc = parse_markdown(session)
    t = template(mode)
    t = replace(
        t,
        continuation=replace(
            t.continuation,
            reserved=(Region("header", 15, 95, 60, 10),),
            anchors=(Anchor("signature", 20, 100),),
        ),
    )
    binding = TemplateBinding(
        "header", (doc.nodes[0].node_id,), pages="all" if repeat else "first", **kwargs
    )
    return session, doc, resolver(), FlowStyle(template=t, template_bindings=(binding,))


def test_fixed_field_moves_whole_source_and_repeats_without_double_counting():
    session, doc, r, flow = setup(repeat=True)
    result = layout_markdown(doc, r, flow=flow)
    assert result.exportable, result.diagnostics
    assert len(result.pages) == 2
    ids = {o.occurrence_id for n in doc.nodes[0].walk() for o in n.occurrences}
    primary = [f for f in result.fragments if not f.repeated]
    assert Counter(f.occurrence_id for f in primary) == Counter(
        o.occurrence_id for o in doc.occurrences
    )
    for page in result.pages:
        field = [f for f in page.fragments if f.occurrence_id in ids]
        assert len(field) == 3
        assert all(f.container_id == "template-field:header" for f in field)
        assert all(f.repeated == (page.index > 0) for f in field)
        region = flow.template.face(page.index).reserved[0]
        assert all(
            region.y_mm <= f.ink_bounds[1] < f.ink_bounds[3] <= region.bounds[3] for f in field
        )
    assert session.source == "123\n\n4\n\n5\n\n6\n\n7\n\n8"


def test_fixed_fields_keep_frame_field_body_routing_domains():
    _, doc, r, flow = setup(repeat=True, mode="blank")
    result = layout_markdown(doc, r, flow=flow)
    for page in plan_from_snapshot(result).pages:
        routed = route_page(page, optimize=True)
        domains = [s.execution_domain for s in routed.page.strokes]
        assert domains[0] == "template-frame"
        assert domains[1] == "template-field:header"
        assert domains[-1] == "template-body"
        assert routed.after_mm <= routed.before_mm
        for s, i, reverse in zip(routed.page.strokes, routed.source_indices, routed.reversed_paths):
            assert s.points == (page.strokes[i].points[::-1] if reverse else page.strokes[i].points)


def test_anchor_sets_logical_start_and_baseline_without_ink_fitting():
    _, doc, r, flow = setup(anchor="signature", scale=0.65)
    a = layout_markdown(doc, r, flow=flow)
    assert a.exportable, a.diagnostics
    f = next(f for f in a.fragments if f.container_id)
    assert f.x_mm == 45 and f.baseline_mm == 30
    shifted = replace(flow, template=replace(flow.template, offset_x_mm=1.25, offset_y_mm=-2))
    b = layout_markdown(doc, r, flow=shifted)
    assert b.exportable
    for p, q in zip(a.pages, b.pages):
        assert p.preview_ops == q.preview_ops
        for op, oq in zip(p.paint_ops, q.paint_ops):
            for (x, y), point in zip(op.points, oq.points):
                assert point == pytest.approx((x + 1.25, y - 2))


def test_oversized_field_preserves_every_source_instance_but_blocks_export():
    _, doc, r, flow = setup("1\n\n2\n\n3\n\n4\n\n5\n\n6")
    binding = replace(flow.template_bindings[0], node_ids=tuple(n.node_id for n in doc.nodes))
    result = layout_markdown(doc, r, flow=replace(flow, template_bindings=(binding,)))
    assert any(d.code == "template-field-height-overflow" for d in result.diagnostics)
    assert Counter(f.occurrence_id for f in result.fragments if not f.repeated) == Counter(
        o.occurrence_id for o in doc.occurrences
    )
    with pytest.raises(ValueError):
        plan_from_snapshot(result)


@pytest.mark.parametrize(
    "change,code",
    [
        ({"region": "absent"}, "template-binding-region-missing"),
        ({"anchor": "absent"}, "template-binding-anchor-missing"),
        ({"node_ids": ("removed",)}, "template-binding-source-missing"),
    ],
)
def test_stale_or_invalid_bindings_never_silently_drop_source(change, code):
    _, doc, r, flow = setup()
    result = layout_markdown(
        doc,
        r,
        flow=replace(flow, template_bindings=(replace(flow.template_bindings[0], **change),)),
    )
    assert not result.exportable and any(d.code == code for d in result.diagnostics)
    assert Counter(f.occurrence_id for f in result.fragments if not f.repeated) == Counter(
        o.occurrence_id for o in doc.occurrences
    )


def test_no_template_blocks_instead_of_ignoring_field_binding():
    _, doc, r, flow = setup()
    result = layout_markdown(doc, r, flow=replace(flow, template=None))
    assert not result.exportable and any(
        d.code == "template-binding-no-template" for d in result.diagnostics
    )


def test_deleting_source_anchor_invalidates_binding_undo_restores_and_package_is_exact(tmp_path):
    session, doc, r, flow = setup()
    a = layout_markdown(doc, r, flow=flow)
    node = doc.nodes[0]
    session.apply(node.span.start, node.span.end, "")
    invalid = layout_markdown(parse_markdown(session), r, flow=flow)
    assert any(d.code == "template-binding-source-missing" for d in invalid.diagnostics)
    session.undo()
    restored = layout_markdown(parse_markdown(session), r, flow=flow)
    assert restored.pages == a.pages
    path = tmp_path / "bound.inkdoc"
    save_package(path, session, r, flow.template.page, StyleProfile(), flow=flow)
    loaded = load_package(path)
    assert loaded.flow == flow
    b = layout_markdown(
        parse_markdown(loaded.session),
        loaded.resolver,
        page=loaded.page,
        style=loaded.style,
        flow=loaded.flow,
    )
    assert restored == b


def test_binding_is_stable_when_editing_inside_its_source_block():
    session, doc, r, flow = setup()
    session.apply(1, 2, "9")
    current = parse_markdown(session)
    assert current.nodes[0].node_id == doc.nodes[0].node_id
    result = layout_markdown(current, r, flow=flow)
    assert result.exportable
    assert "".join(f.text for f in result.fragments if f.container_id) == "193"


def test_binding_rejects_ambiguous_duplicates():
    _, doc, _, flow = setup()
    with pytest.raises(ValueError, match="share"):
        replace(flow, template_bindings=flow.template_bindings * 2)
    with pytest.raises(ValueError, match="share"):
        replace(
            flow,
            template_bindings=(
                *flow.template_bindings,
                TemplateBinding("other", (doc.nodes[0].node_id,)),
            ),
        )


def test_bound_math_and_code_use_field_scale_and_keep_semantic_instances():
    _, doc, r, flow = setup("$1+2$\n\n```\n12\n```\n\n3", scale=0.65)
    flow = replace(
        flow,
        template_bindings=(
            replace(
                flow.template_bindings[0], node_ids=(doc.nodes[0].node_id, doc.nodes[1].node_id)
            ),
        ),
    )
    result = layout_markdown(doc, r, flow=flow)
    assert result.exportable, result.diagnostics
    assert Counter(f.occurrence_id for f in result.fragments if not f.repeated) == Counter(
        o.occurrence_id for o in doc.occurrences
    )
    field = [f for f in result.fragments if f.container_id]
    assert "".join(f.text for f in field) == "1+212\n"
    first = next(f for f in field if f.text == "1")
    glyph = next(g for pool in r.pools.values() for g in pool if g.asset_id == first.asset_id)
    ops = [op for op in result.pages[0].paint_ops if op.occurrence_id == first.occurrence_id]
    for op, stroke in zip(ops, glyph.strokes):
        for (x, y), (sx, sy) in zip(op.points, stroke):
            assert (x - op.points[0][0], y - op.points[0][1]) == pytest.approx(
                ((sx - stroke[0][0]) * 3.9, (sy - stroke[0][1]) * 3.9)
            )


def test_tiny_region_is_a_diagnostic_and_leaves_source_visible():
    _, doc, r, flow = setup()
    face = replace(flow.template.first, reserved=(Region("header", 10, 10, 0.1, 1),))
    result = layout_markdown(
        doc, r, flow=replace(flow, template=replace(flow.template, first=face))
    )
    assert not result.exportable
    assert any(d.code == "template-field-configuration-invalid" for d in result.diagnostics)
    assert Counter(f.occurrence_id for f in result.fragments if not f.repeated) == Counter(
        o.occurrence_id for o in doc.occurrences
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"node_ids": "abc"},
        {"pages": "odd"},
        {"scale": float("nan")},
        {"scale": 0},
        {"schema_version": "v2"},
    ],
)
def test_invalid_binding_configuration_is_rejected(changes):
    with pytest.raises(ValueError):
        TemplateBinding(**({"region": "field", "node_ids": ("node",)} | changes))


def test_first_layout_then_immediate_save_reload_has_identical_snapshot(tmp_path):
    session, doc, r, flow = setup()
    first = layout_markdown(doc, r, flow=flow)
    path = tmp_path / "first-save.inkdoc"
    save_package(path, session, r, flow.template.page, StyleProfile(), flow=flow)
    loaded = load_package(path)
    after = layout_markdown(
        parse_markdown(loaded.session),
        loaded.resolver,
        page=loaded.page,
        style=loaded.style,
        flow=loaded.flow,
    )
    assert after == first
