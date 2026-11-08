"""Footnote semantics are source exact; layout readiness is independently gated."""

import json
from dataclasses import asdict

import pytest

from inkstruct.assets.resolver import AssetResolver
from inkstruct.document.editing import SourceSession
from inkstruct.document.markdown import parse_markdown
from inkstruct.layout.blocks import layout_markdown
from inkstruct.plotter.adapters import plan_from_snapshot


def nodes(doc, kind):
    return [n for root in doc.nodes for n in root.walk() if n.kind == kind]


def test_forward_definitions_repeated_references_and_first_reference_order():
    source = "[^later]: 12\n\n3[^first] 4[^later] 5[^first]\n\n[^first]: 67"
    doc = parse_markdown(source)
    assert not doc.diagnostics
    refs = nodes(doc, "footnote_reference")
    defs = nodes(doc, "footnote_definition")
    assert [dict(n.attributes)["number"] for n in refs] == ["1", "2", "1"]
    assert [dict(n.attributes)["number"] for n in defs] == ["2", "1"]
    assert dict(refs[0].attributes)["definition_id"] == defs[1].node_id
    assert dict(refs[2].attributes)["definition_id"] == defs[1].node_id
    assert len({o.occurrence_id for o in doc.occurrences}) == len(doc.occurrences)
    assert [source[n.span.start : n.span.end] for n in refs] == ["[^first]", "[^later]", "[^first]"]
    assert [source[n.occurrences[0].span.start : n.occurrences[0].span.end] for n in defs] == [
        "[^later]:",
        "[^first]:",
    ]


def test_continuation_crlf_tabs_entities_math_code_and_multiple_paragraphs():
    source = "12[^注]\r\n\r\n[^注]: **3** &amp; $4+5$\r\n\t6\r\n\r\n    - [x] 7\r\n\r\n    `[^literal]`\r\n\r\n89"
    doc = parse_markdown(source)
    assert not doc.diagnostics
    definition = nodes(doc, "footnote_definition")[0]
    assert [c.kind for c in definition.children] == ["paragraph", "bullet_list", "paragraph"]
    assert len(nodes(doc, "footnote_reference")) == 1
    assert len(nodes(doc, "task_checkbox")) == 1
    for o in doc.occurrences:
        original = source[o.span.start : o.span.end]
        assert original == o.text or original in {"[^注]", "[^注]:", "&amp;", "\r\n", "[x]"}
    assert nodes(doc, "math_inline")
    assert "".join(o.text for o in doc.nodes[-1].walk() for o in o.occurrences) == "89"
    # The definition's body source range still includes original indentation.
    assert source[definition.span.start : definition.span.end].startswith("[^注]:")
    assert source[definition.span.start : definition.span.end].endswith("`[^literal]`")


@pytest.mark.parametrize(
    "source",
    [
        r"\[^a]",
        "`[^a]`",
        "```\n[^a]: 1\n```",
        "    [^a]: 1",
        "[^two words]",
        "[^]",
        "[^a\\b]",
        "[^" + "a" * 65 + "]",
        "$[^a]$",
        "<div>[^a]</div>",
    ],
)
def test_literals_and_invalid_labels_do_not_create_footnotes(source):
    doc = parse_markdown(source)
    assert not nodes(doc, "footnote_reference") and not nodes(doc, "footnote_definition")


@pytest.mark.parametrize(
    "source,code",
    [
        ("1[^a]", "footnote-missing-definition"),
        ("1[^A]\n\n[^a]: 2", "footnote-missing-definition"),
        ("1[^a]\n\n[^a]: 2\n\n[^a]: 3", "footnote-duplicate-definition"),
        ("[^a]: 2", "footnote-unused-definition"),
        ("1[^a]\n\n[^a]:", "footnote-empty-definition"),
        ("1[^a]\n\n[^a]: 2[^a]", "footnote-recursive-reference"),
        ("1[^a]\n\n> [^a]: 2", "footnote-definition-context"),
        ("1[^a]\n\n[^a]: 2\n\n    [^b]: 3", "footnote-definition-context"),
    ],
)
def test_invalid_relationships_are_actionable_source_errors(source, code):
    doc = parse_markdown(source)
    issue = next(d for d in doc.diagnostics if d.code == code)
    assert issue.severity == "error" and "[^" in source[issue.span.start : issue.span.end]
    snapshot = layout_markdown(doc, AssetResolver(builtin_numbers=True))
    assert not snapshot.exportable


def test_reference_numbering_changes_do_not_invalidate_persisted_asset_selection():
    session = SourceSession("1[^a]\n\n[^a]: 23")
    before = parse_markdown(session)
    ref = nodes(before, "footnote_reference")[0]
    definition = nodes(before, "footnote_definition")[0]
    resolver = AssetResolver(builtin_numbers=True)
    resolver.resolve(ref.occurrences[0])
    resolver.resolve(definition.occurrences[0])
    old_body_ids = [
        o.occurrence_id
        for n in definition.children
        for child in n.walk()
        for o in child.occurrences
    ]
    session.apply(0, 0, "4[^b]\n\n[^b]: 5\n\n")
    after = parse_markdown(session)
    new_ref = nodes(after, "footnote_reference")[1]
    new_def = nodes(after, "footnote_definition")[1]
    assert new_ref.node_id == ref.node_id and new_def.node_id == definition.node_id
    assert new_ref.occurrences[0].text == "2"
    assert resolver.resolve(new_ref.occurrences[0]).character == "2"
    assert resolver.resolve(new_def.occurrences[0]).character == "2"
    assert [
        o.occurrence_id for n in new_def.children for child in n.walk() for o in child.occurrences
    ] == old_body_ids
    session.undo()
    restored = parse_markdown(session)
    assert restored.nodes == before.nodes
    assert (
        parse_markdown(SourceSession.restore(session.source, session.identity_record())) == restored
    )


def test_multi_digit_numbering_is_individually_mapped_and_unique():
    source = (
        " ".join(f"1[^a{i}]" for i in range(11))
        + "\n\n"
        + "\n\n".join(f"[^a{i}]: 2" for i in range(11))
    )
    doc = parse_markdown(source)
    ref = nodes(doc, "footnote_reference")[-1]
    assert "".join(o.text for o in ref.occurrences) == "11"
    assert len({o.occurrence_id for o in doc.occurrences}) == len(doc.occurrences)
    assert all(source[o.span.start : o.span.end] == "[^a10]" for o in ref.occurrences)


def test_parser_calls_do_not_share_definitions_or_counters():
    assert not parse_markdown("1[^a]\n\n[^a]: 2").diagnostics
    assert any(d.code == "footnote-missing-definition" for d in parse_markdown("1[^a]").diagnostics)
    with pytest.raises(ValueError, match="128 definition budget"):
        parse_markdown("\n\n".join(f"[^a{i}]: 1" for i in range(129)))
    with pytest.raises(ValueError, match="1024 reference budget"):
        parse_markdown("1[^a] " * 1025)


def test_link_definitions_and_pipe_table_references_have_exact_mapping():
    source = "[link]: /url\n\n| 1[^a] | [2][link] |\n|---|---|\n|3|4|\n\n[^a]: 5"
    doc = parse_markdown(source)
    assert not doc.diagnostics
    assert len(nodes(doc, "link")) == 1
    ref = nodes(doc, "footnote_reference")[0]
    assert source[ref.span.start : ref.span.end] == "[^a]"


def test_cli_inspection_resource_numbers_and_native_roundtrip(tmp_path, capsys):
    from inkstruct.cli import main
    from inkstruct.document.package import load_package, save_package
    from inkstruct.document.schema import PageProfile, StyleProfile

    source = tmp_path / "footnotes.md"
    source.write_bytes(b"1[^a]\r\n\r\n[^a]: 2")
    assert main(["document", "inspect", str(source)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["document"]["source"].encode() == source.read_bytes()
    assert main(["document", "resources", str(source)]) == 0
    gaps = json.loads(capsys.readouterr().out)["gaps"]
    assert {g["character"] for g in gaps} == {"1", "2"}
    session = SourceSession(source.read_bytes().decode())
    resolver = AssetResolver(builtin_numbers=True)
    snapshot = layout_markdown(parse_markdown(session), resolver)
    assert snapshot.plotter_exportable, snapshot.diagnostics
    plan_from_snapshot(snapshot)
    project = tmp_path / "footnotes.inkdoc"
    save_package(project, session, resolver, PageProfile(), StyleProfile())
    loaded = load_package(project)
    assert asdict(parse_markdown(loaded.session)) == asdict(parse_markdown(session))


def test_definition_boundaries_empty_first_line_and_adjacent_definitions():
    source = "1[^a] 2[^b]\n[^a]:\n    34\n[^b]: 56\n78"
    doc = parse_markdown(source)
    assert not doc.diagnostics
    definitions = nodes(doc, "footnote_definition")
    assert len(definitions) == 2
    assert (
        "".join(
            o.text for n in definitions[0].children for child in n.walk() for o in child.occurrences
        )
        == "34"
    )
    assert (
        "".join(
            o.text for n in definitions[1].children for child in n.walk() for o in child.occurrences
        )
        == "56"
    )
    assert doc.nodes[-1].kind == "paragraph"
    assert doc.source[doc.nodes[-1].span.start : doc.nodes[-1].span.end] == "78"


def test_deep_definition_recursion_is_bounded():
    source = "\n".join("    " * i + f"[^a{i}]: " for i in range(18))
    with pytest.raises(ValueError, match="nesting"):
        parse_markdown(source)


def test_reference_numbers_are_atomic_raised_handwriting_and_attach_to_preceding_text():
    from inkstruct.document.schema import StyleProfile
    from inkstruct.layout.inline import break_lines, inline_runs, measure_runs

    doc = parse_markdown("1 2[^a]\n\n[^a]: 3")
    inline = doc.nodes[0].children[0]
    boxes, issues = measure_runs(
        inline_runs(inline), AssetResolver(builtin_numbers=True), StyleProfile()
    )
    assert not issues
    reference = boxes[-1]
    assert reference.run.kind == "footnote_reference"
    assert reference.math.glyphs[0].em_mm == pytest.approx(4.2)
    assert reference.math.glyphs[0].baseline_mm == pytest.approx(-2.7)
    assert reference.math.glyphs[0].occurrence == nodes(doc, "footnote_reference")[0].occurrences[0]
    # Enough for all ordinary text, insufficient for text plus reference: the
    # preceding 2 must accompany its marker onto the next line.
    lines = break_lines(boxes, sum(b.advance for b in boxes[:-1]) + 0.01)
    assert len(lines) == 2
    assert [b.run.occurrence.text for b in lines[-1]] == ["2", "\ufffc"]
    snapshot = layout_markdown(doc, AssetResolver(builtin_numbers=True))
    marker = next(f for f in snapshot.fragments if f.node_id == reference.run.occurrence.node_id)
    previous = next(f for f in snapshot.fragments if f.text == "2")
    assert marker.baseline_mm < previous.baseline_mm
    assert marker.asset_id is not None
    assert snapshot.exportable
    assert any(
        f.container_id and f.container_id.startswith("footnote:") for f in snapshot.fragments
    )


def test_small_and_missing_footnote_digit_are_diagnosed_without_fallback():
    from inkstruct.document.schema import StyleProfile
    from inkstruct.layout.inline import inline_runs, measure_runs

    doc = parse_markdown("1[^a]\n\n[^a]: 2")
    ref = nodes(doc, "footnote_reference")[0]
    _, issues = measure_runs(inline_runs(ref), AssetResolver(), StyleProfile(em_mm=1))
    assert {d.code for d in issues} == {"asset-missing", "footnote-size-limit"}
