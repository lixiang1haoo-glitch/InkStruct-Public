"""M5 cross-feature acceptance, including sampled equation-bracket identity."""

import json
import re
import threading
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import replace
from pathlib import Path

import pytest
from test_footnote_pages import assert_bands
from test_math_layout import resolver as basic_resolver
from test_math_sample_constructions import STYLE, assets

from inkstruct.assets.resolver import AssetResolver
from inkstruct.assets.symbol_provider import adapt_symbol
from inkstruct.document.editing import SourceSession
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.package import load_package, save_package
from inkstruct.document.schema import PageProfile, StyleProfile
from inkstruct.document.styles import FlowStyle
from inkstruct.editor.build_cache import MarkdownBuildCache
from inkstruct.editor.mixed import build_markdown
from inkstruct.layout.blocks import layout_markdown
from inkstruct.math.handwritten import measure_math
from inkstruct.plotter.adapters import plan_from_snapshot
from inkstruct.plotter.export import route_page
from inkstruct.plotter.svg import page_svg

FIXTURE = Path(__file__).parent / "fixtures/markdown_mixed/m5_acceptance.md"


def resources():
    by = {c: pool for c, pool in basic_resolver().pools.items()}
    for glyph in assets():
        raw = json.loads(glyph.original_json)
        raw["sample_id"] += "-variant"
        raw["strokes"][0]["points"][0]["x"] += 3
        by[glyph.character] = (glyph, adapt_symbol(json.dumps(raw).encode()))
    return AssetResolver(embedded=[g for pool in by.values() for g in pool])


def numbered_source():
    return r"""$$
\begin{equation}12\label{a}\end{equation}
$$

$$
\begin{align}3\\4\tag{20}\label{b}\end{align}
$$

$\eqref{a}$ $\eqref{b}$
"""


def rules(session, r):
    doc = parse_markdown(session)
    result = {}
    for root in doc.nodes:
        for n in root.walk():
            if n.math:
                box = measure_math(n.math, r, owner=n.node_id, style=STYLE)
                assert box.ready, box.diagnostics
                result.update(
                    {rule.occurrence_id: rule.asset_id for rule in box.rules if rule.asset_id}
                )
    return result


def test_number_tags_and_references_keep_bracket_choices_across_edits_and_reopen(tmp_path):
    s, r = SourceSession(numbered_source()), resources()
    before = rules(s, r)
    assert len(before) == 10  # Three tags and two references, left and right.
    prefix = "$$\n\\begin{equation}5\\end{equation}\n$$\n\n"
    s.apply(0, 0, prefix)
    after = rules(s, r)
    assert before.items() <= after.items()  # Renumbering changes digits, not brackets.
    at = s.source.index("12")
    s.apply(at + 1, at + 2, "234")
    assert before.items() <= rules(s, r).items()
    s.undo()
    s.undo()
    assert rules(s, r) == before
    s.redo()
    assert rules(s, r) == after
    flow = FlowStyle(math=STYLE)
    file = tmp_path / "numbered.inkdoc"
    save_package(file, s, r, PageProfile(), StyleProfile(), flow=flow)
    loaded = load_package(file)
    assert loaded.resolver.selection_records() == r.selection_records()
    assert rules(loaded.session, loaded.resolver) == after
    # Repeated identical references still own separate bracket instances.
    loaded.session.apply(len(s.source), len(s.source), "\n$\\eqref{a}$")
    final = rules(loaded.session, loaded.resolver)
    assert after.items() <= final.items() and len(final) == len(after) + 2


def test_legacy_sampled_number_brackets_migrate_before_first_edit(tmp_path):
    s, r = SourceSession(numbered_source()), resources()
    doc = parse_markdown(s)

    def legacy(n):
        return replace(
            n,
            occurrence_id=None
            if n.kind in {"EquationTag", "EquationReference"}
            else n.occurrence_id,
            children=tuple(legacy(c) for c in n.children),
        )

    expected = []
    for n in (n for root in doc.nodes for n in root.walk()):
        if n.math:
            box = measure_math(legacy(n.math), r, owner=n.node_id, style=STYLE)
            expected.extend(rule.asset_id for rule in box.rules if rule.asset_id)
    old = r.selection_records()
    file = tmp_path / "legacy.inkdoc"
    save_package(file, s, r, PageProfile(), StyleProfile(), flow=FlowStyle(math=STYLE))
    original = file.read_bytes()
    loaded = load_package(file)
    # No layout before this edit: loading must migrate while offsets are valid.
    loaded.session.apply(0, 0, "9\n\n")
    assert list(rules(loaded.session, loaded.resolver).values()) == expected
    assert all(record in loaded.resolver.selection_records() for record in old)
    assert file.read_bytes() == original


@pytest.mark.parametrize("sample", [False, True])
def test_m5_combination_coverage_paging_routing_edit_undo_and_roundtrip(sample, tmp_path):
    s, r = SourceSession(FIXTURE.read_text()), resources()
    flow = FlowStyle(
        markdown_dialect="obsidian",
        math=STYLE
        if sample
        else replace(
            STYLE,
            fraction_source="geometric",
            radical_source="geometric",
            delimiter_source="geometric",
        ),
    )
    cache = MarkdownBuildCache()
    args = {
        "session": s,
        "revision": 0,
        "resolver": r,
        "run": "",
        "symbols": "",
        "page": PageProfile(),
        "style": StyleProfile(),
        "flow": flow,
        "cancelled": threading.Event(),
    }
    result = build_markdown(**args, cache=cache)
    doc, snapshot, r = result["document"], result["snapshot"], result["resolver"]
    assert snapshot.plotter_exportable, snapshot.diagnostics
    assert len(snapshot.pages) >= 2
    assert Counter(f.occurrence_id for f in snapshot.fragments if not f.repeated) == Counter(
        o.occurrence_id for o in doc.occurrences
    )
    assert_bands(snapshot)
    expected_choices = r.selection_records()
    canonical = lambda points: min(points, tuple(reversed(points)))
    for page in plan_from_snapshot(snapshot).pages:
        routed = route_page(page, optimize=True)
        assert routed.after_mm <= routed.before_mm
        assert Counter(canonical(p.points) for p in routed.page.strokes) == Counter(
            canonical(p.points) for p in page.strokes
        )
        assert sorted(routed.source_indices) == list(range(len(page.strokes)))
        xml = ET.fromstring(page_svg(routed.page))
        for path in xml:
            assert path.tag.endswith("}path") and "transform" not in path.attrib
            commands = re.findall(r"[A-Za-z]", path.attrib["d"])
            assert commands[0] == "M" and set(commands[1:]) == {"L"}
    at = s.source.index("[ ]") + 1
    s.apply(at, at + 1, "x")
    args.update(resolver=r, revision=1)
    edited = build_markdown(**args, cache=cache)
    full = build_markdown(**args)
    assert edited["snapshot"] == full["snapshot"]
    s.undo()
    args["revision"] = 2
    restored = build_markdown(**args, cache=cache)
    assert restored["snapshot"] == replace(snapshot, revision=2)
    assert restored["resolver"].selection_records() == expected_choices
    file = tmp_path / "m5.inkdoc"
    save_package(file, s, r, args["page"], args["style"], flow=flow, optimize=True)
    loaded = load_package(file)
    again = layout_markdown(
        parse_markdown(loaded.session, dialect="obsidian"),
        loaded.resolver,
        page=loaded.page,
        style=loaded.style,
        flow=loaded.flow,
    )
    assert replace(again, revision=0) == snapshot
