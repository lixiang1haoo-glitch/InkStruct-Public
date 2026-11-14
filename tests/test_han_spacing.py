import json
from dataclasses import replace
from zipfile import ZipFile

import pytest

from inkstruct.assets.glyph_provider import GlyphProvider, adapt_glyph
from inkstruct.assets.resolver import AssetResolver
from inkstruct.document.editing import SourceSession
from inkstruct.document.han_variation import HanVariation
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.package import load_package, save_package
from inkstruct.document.schema import PageProfile, StyleProfile
from inkstruct.document.styles import FlowStyle
from inkstruct.layout.blocks import layout_markdown
from inkstruct.layout.inline import inline_runs, measure_runs
from inkstruct.layout.measurement_cache import MeasurementCache, measurement_scope
from test_document_layout import glyph, provider
from test_template_paper_grid import template


def narrow_provider():
    narrow = glyph("人")
    for stroke in narrow["strokes"]:
        for point in stroke["points"]:
            point["x"] = 0.2 + point["x"] / 4
    return GlyphProvider({**provider("大").assets, "人": adapt_glyph(narrow)})


def test_width_mode_and_natural_spacing_are_independent():
    doc = parse_markdown(SourceSession(r"人大人 `人大` $\text{人}$"))
    runs = inline_runs(doc.nodes[0].children[0])
    resolver = AssetResolver(generated=narrow_provider())
    style = StyleProfile()
    with measurement_scope(MeasurementCache()):
        full, _ = measure_runs(runs, resolver, style)
        compact, _ = measure_runs(runs, resolver, style, han_spacing="handwriting")
        assert measure_runs(runs, resolver, style)[0] == full
        assert measure_runs(runs, resolver, style, han_spacing="handwriting")[0] == compact
    narrow, wide = compact[:2]
    left, _, right, _ = narrow.glyph.layout_bounds
    assert narrow.advance == pytest.approx((right - left + .08) * narrow.em + style.stroke_width_mm)
    assert narrow.advance < wide.advance < full[1].advance
    assert narrow.em == full[0].em and narrow.ascent == full[0].ascent and narrow.descent == full[0].descent
    assert narrow.glyph == full[0].glyph
    assert {box.run.kind for box in compact[3:]} >= {"code_inline", "math_inline"}
    assert compact[3:] == full[3:]

    variation = HanVariation(enabled=True, seed=7, strength=0, size_strength=0,
                             spacing_strength=1, baseline_strength=0)
    for mode, before in (("full", full), ("handwriting", compact)):
        varied, _ = measure_runs(runs, resolver, style, han_spacing=mode, han_variation=variation)
        assert [box.advance for box in varied[:2]] != [box.advance for box in before[:2]]
        assert [box.origin_offset for box in varied] == [box.origin_offset for box in before]


@pytest.mark.parametrize("paper", [None, template()])
def test_save_reopen_both_modes_and_legacy_documents(tmp_path, paper):
    session = SourceSession("人" * 30)
    page, style = PageProfile(width_mm=54, margin_mm=8), StyleProfile()
    resolver = AssetResolver(generated=narrow_provider())
    legacy = FlowStyle(template=paper, paragraph_align="justify", punctuation_spacing="handwriting",
                       latin_spacing="handwriting")
    document = parse_markdown(session, field_blocks=legacy.named_fields)

    def render(flow, loaded_session=session, assets=resolver):
        parsed = parse_markdown(loaded_session, field_blocks=flow.named_fields)
        return layout_markdown(parsed, assets, page=page, style=style, flow=flow)

    full, compact = (render(flow) for flow in (legacy, replace(legacy, han_spacing="handwriting")))
    assert len({f.baseline_mm for f in full.fragments}) > len({f.baseline_mm for f in compact.fragments})
    assert all(f.status == "ready" and f.ink_bounds for f in compact.fragments)
    assert [f.occurrence_id for f in full.fragments] == [o.occurrence_id for o in document.occurrences]
    for key, flow, snapshot in (("legacy", legacy, full), ("compact", replace(legacy, han_spacing="handwriting"), compact),
                                 ("full", replace(legacy, schema_version="inkstruct_flow_style_v6"), None)):
        path = tmp_path / f"{key}.inkdoc"
        save_package(path, session, resolver, page, style, flow=flow)
        with ZipFile(path) as archive:
            record = json.loads(archive.read("styles.json"))["flow"]
        if key == "legacy":
            assert "han_spacing" not in record and record["schema_version"] == "inkstruct_flow_style_v5"
        else:
            assert record["han_spacing"] == flow.han_spacing
        restored = load_package(path)
        assert restored.flow == flow
        assert render(restored.flow, restored.session, restored.resolver) == (snapshot or render(flow))
