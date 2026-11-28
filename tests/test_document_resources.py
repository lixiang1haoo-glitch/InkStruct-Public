"""Source-accurate, read-only capture requirements for portable math settings."""

import csv
import json
from collections import Counter
from dataclasses import replace

import pytest
from test_math_sample_constructions import STYLE, resolver

from inkstruct.assets.resolver import AssetResolver, SelectedAsset
from inkstruct.cli import main
from inkstruct.document.editing import SourceSession
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.package import save_package
from inkstruct.document.resources import construction_requirements, inspect_resources
from inkstruct.document.schema import PageProfile, StyleProfile
from inkstruct.document.styles import FlowStyle
from inkstruct.math.handwritten import measure_math
from inkstruct.math.style import MathStyle


@pytest.mark.parametrize(
    "formula,chars",
    [
        (r"\sqrt{\frac{1}{2}}", "√−"),
        (r"\left.1\right)", ")"),
        (r"\begin{matrix}1\end{matrix}", ""),
        (r"\begin{smallmatrix}1\end{smallmatrix}", ""),
        (r"\begin{pmatrix}1\end{pmatrix}", "()"),
        (r"\begin{bmatrix}1\end{bmatrix}", "[]"),
        (r"\begin{Bmatrix}1\end{Bmatrix}", "{}"),
        (r"\begin{vmatrix}1\end{vmatrix}", "||"),
        (r"\begin{Vmatrix}1\end{Vmatrix}", "‖‖"),
        (r"\begin{cases}1&2\end{cases}", "{"),
        (r"\begin{array}{|r|}1\end{array}", ""),
    ],
)
def test_required_characters_match_selected_structure_modes(formula, chars):
    doc = parse_markdown("$" + formula + "$")
    assert not doc.diagnostics
    requirements = construction_requirements(doc, STYLE)
    assert "".join(o.text for o in requirements) == chars
    assert not construction_requirements(doc, MathStyle(fraction_source="geometric"))
    assert [o.text for o in construction_requirements(doc, MathStyle())] == [c for c in chars if c == '−']
    assert all(0 <= o.span.start < o.span.end <= len(doc.source) for o in requirements)


def test_requirements_reuse_layout_identities_and_exact_left_right_spans():
    source = "$$\n\\begin{equation}\\sqrt{\\frac{1}{2}}\\label{a}\\end{equation}\n$$\n\n$\\eqref{a}$ $\\left[1\\right.$"
    s, r = SourceSession(source), resolver()
    doc = parse_markdown(s)
    before = r.selection_records()
    report = inspect_resources(doc, r, flow=FlowStyle(math=STYLE))
    assert not report["gaps"]
    assert r.selection_records() == before
    for n in (n for root in doc.nodes for n in root.walk() if n.math):
        box = measure_math(n.math, r, owner=n.node_id, style=STYLE)
        assert box.ready, box.diagnostics
    by = {record["occurrence_id"]: record for record in r.selection_records()}
    assert all(
        by[o["occurrence_id"]]["character"] == o["text"]
        for o in report["construction_requirements"]
    )
    left = next(o for o in construction_requirements(doc, STYLE) if o.text == "[")
    assert source[left.span.start : left.span.end] == "["
    assert len(report["construction_requirements"]) == 7
    assert not report["machine_export_ready"]


def test_missing_selected_specimen_reports_restore_without_reselecting():
    doc, r = parse_markdown(r"$\sqrt{1}$"), resolver()
    occurrence = construction_requirements(doc, STYLE)[0]
    r.selections[occurrence.occurrence_id] = SelectedAsset(
        occurrence.occurrence_id, "√", "gone", "old", "old-metrics"
    )
    old = r.selection_records()
    report = inspect_resources(doc, r, flow=FlowStyle(math=STYLE))
    assert r.selection_records() == old
    gap = next(g for g in report["gaps"] if g["character"] == "√")
    assert gap["action"] == "restore-selected-resource"
    assert "no reselection" in gap["reason"]


def test_native_scan_inherits_dialect_sources_assets_and_does_not_write_project(tmp_path, capsys):
    s = SourceSession("[12](https://example.org) $\\sqrt{\\frac{1}{2}}$ $\\left(3\\right)$")
    flow = FlowStyle(math=STYLE, markdown_dialect="markdown")
    file, capture = tmp_path / "draft.inkdoc", tmp_path / "capture.csv"
    save_package(
        file, s, AssetResolver(builtin_numbers=True), PageProfile(), StyleProfile(), flow=flow
    )
    original = file.read_bytes()
    assert main(["document", "resources", str(file), "--capture-csv", str(capture)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["dialect"] == "markdown"
    assert {g["character"] for g in report["gaps"]} == {"√", "−", "(", ")"}
    rows = list(csv.DictReader(capture.open(encoding="utf-8-sig")))
    assert len(rows) == 4 and all(row["repeats"] == "5" for row in rows)
    assert file.read_bytes() == original
    assert main(["document", "resources", str(file), "--fraction-source", "geometric"]) == 0
    overridden = json.loads(capsys.readouterr().out)
    assert {g["character"] for g in overridden["gaps"]} == {"√", "(", ")"}
    assert file.read_bytes() == original
    rejected = tmp_path / "rejected.csv"
    assert (
        main(
            [
                "document",
                "resources",
                str(file),
                "--symbols",
                "any.zip",
                "--capture-csv",
                str(rejected),
            ]
        )
        == 2
    )
    capsys.readouterr()
    assert not rejected.exists() and file.read_bytes() == original


def test_raw_mode_is_explicit_and_unicode_requirements_do_not_alias(tmp_path, capsys):
    source = tmp_path / "formula.md"
    source.write_text(r"$\frac{1}{2}\begin{Vmatrix}3\end{Vmatrix}$")
    assert main(["document", "resources", str(source)]) == 0
    baseline = json.loads(capsys.readouterr().out)
    assert [o['text'] for o in baseline["construction_requirements"]] == ['−']
    assert (
        main(
            [
                "document",
                "resources",
                str(source),
                "--fraction-source",
                "sample",
                "--delimiter-source",
                "sample",
            ]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert [o["text"] for o in report["construction_requirements"]] == ["−", "‖", "‖"]
    assert {"−", "‖"} <= {g["character"] for g in report["gaps"]}
    assert not {"-", "∥"} & {g["character"] for g in report["gaps"]}


def test_literal_markers_and_fixed_source_requirements_are_not_lost_and_geometric_rules_need_no_assets():
    doc = parse_markdown("1[^a]\n\n[^a]: $\\sqrt{2}$ $\\overline{3}$")
    r = AssetResolver(builtin_numbers=True)
    report = inspect_resources(doc, r, flow=FlowStyle(math=STYLE))
    literal = {"[", "^", "a", "]", ":"}
    assert {g["character"] for g in report["gaps"]} == literal | {"√", "−"}
    assert len(report["construction_requirements"]) == 2
    geometric = FlowStyle(math=MathStyle(fraction_source="geometric"))
    assert {g["character"] for g in inspect_resources(doc, r, flow=geometric)["gaps"]} == literal


def test_existing_choices_are_returned_unchanged_and_geometry_is_not_claimed():
    doc, r = parse_markdown(r"$\sqrt{1}$"), resolver()
    requirement = construction_requirements(doc, STYLE)[0]
    glyph = r.resolve(requirement)
    # Deliberately invalid geometry with the same identity: resource availability
    # is not a validation of sampled root segmentation or page readiness.
    invalid = replace(glyph, strokes=(((0, 0), (0, 1)),))
    altered = AssetResolver(embedded=[invalid, *r.pools["1"]], selections=r.selections.values())
    report = inspect_resources(doc, altered, flow=FlowStyle(math=STYLE))
    assert not report["gaps"] and not report["machine_export_ready"]
    # Find semantic math without assuming renderer structure.
    node = next(n for root in doc.nodes for n in root.walk() if n.math)
    assert not measure_math(node.math, altered, owner=node.node_id, style=STYLE).ready


@pytest.mark.parametrize("samples", [False, True])
def test_legacy_table_resource_scan_preserves_imported_choices(tmp_path, capsys, samples):
    from test_table_import import legacy_project

    from inkstruct.document.table_import import import_table_project

    path, _ = legacy_project(tmp_path, samples=samples)
    before = path.read_bytes()
    imported = import_table_project(path)
    imported.resolver.gaps(parse_markdown(imported.session).occurrences)
    expected = imported.resolver.selection_records()
    assert main(["document", "resources", str(path)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert not report["gaps"] and not report["construction_requirements"]
    # Each legacy import creates a new document identity; asset choices stay fixed.
    key = lambda value: (
        value["character"],
        value["asset_id"],
        value["sample_id"],
        value["metrics_key"],
    )
    assert Counter(map(key, report["selections"])) == Counter(map(key, expected))
    assert path.read_bytes() == before
