"""Task syntax, source-only patches, physical boxes and persistent identity."""

from collections import Counter
from dataclasses import replace

import pytest

from inkstruct.assets.resolver import AssetResolver
from inkstruct.document.editing import SourceSession
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.schema import PageProfile
from inkstruct.document.styles import FlowStyle
from inkstruct.document.tasks import task_patch
from inkstruct.layout.blocks import layout_markdown
from inkstruct.plotter.adapters import plan_from_snapshot


def tasks(doc):
    return [n for root in doc.nodes for n in root.walk() if n.kind == "task_checkbox"]


def test_task_source_markers_and_empty_nested_ordered_items():
    source = "- [ ] 12\r\n- [X] **3**\r\n  - [x] 4\r\n\r\n1. [ ] 5\r\n2. [ ]"
    doc = parse_markdown(source)
    assert [source[n.span.start : n.span.end] for n in tasks(doc)] == [
        "[ ]",
        "[X]",
        "[x]",
        "[ ]",
        "[ ]",
    ]
    r = layout_markdown(doc, AssetResolver(builtin_numbers=True))
    assert r.plotter_exportable, r.diagnostics
    boxes = [f for f in r.fragments if f.status.startswith("task-")]
    assert len(boxes) == 5
    for box in boxes:
        ops = [o for p in r.pages for o in p.paint_ops if o.occurrence_id == box.occurrence_id]
        assert len(ops) == (2 if box.status == "task-checked" else 1)
        assert len(ops[0].points) == 5 and ops[0].points[0] == ops[0].points[-1]
    plan_from_snapshot(r)


@pytest.mark.parametrize(
    "source",
    [
        "[x] 1",
        "- \\[x] 1",
        "- &#91;x] 1",
        "- `[x] 1`",
        "- [y] 1",
        "- [x]1",
        "```\n- [x] 1\n```",
        "- 1\n\n  [x] 2",
    ],
)
def test_task_like_literals_are_not_interpreted(source):
    assert not tasks(parse_markdown(source))


def test_one_character_toggle_preserves_all_other_atoms_occurrences_and_samples():
    s = SourceSession("- [X] 1\r\n- [ ] 2")
    before = parse_markdown(s)
    n = tasks(before)[0]
    atoms = s.atom_ids
    patch = task_patch(before, n.occurrences[0].occurrence_id)
    assert patch == (3, 4, " ")
    s.apply(*patch, expected_revision=before.revision)
    after = parse_markdown(s)
    assert s.source == "- [ ] 1\r\n- [ ] 2"
    assert [o.occurrence_id for o in before.occurrences] == [
        o.occurrence_id for o in after.occurrences
    ]
    assert s.atom_ids[:3] == atoms[:3] and s.atom_ids[4:] == atoms[4:]
    s.undo()
    assert s.source == before.source and s.atom_ids == atoms
    s.redo()
    assert s.source == after.source
    with pytest.raises(ValueError):
        task_patch(after, "stale")


def test_task_marker_only_draws_once_across_pages_and_low_indent_stays_inside():
    doc = parse_markdown("- [x] " + "1234567890 " * 40)
    result = layout_markdown(
        doc,
        AssetResolver(builtin_numbers=True),
        page=PageProfile(50, 50, 5),
        flow=replace(FlowStyle(), list_indent_mm=0.01),
    )
    assert result.plotter_exportable, result.diagnostics
    assert len(result.pages) > 1
    assert len([f for f in result.fragments if f.status.startswith("task-")]) == 1
    assert Counter(f.occurrence_id for f in result.fragments) == Counter(
        o.occurrence_id for o in doc.occurrences
    )
    plan_from_snapshot(result)


@pytest.mark.parametrize("source", ["- [ ]\n  12", "> - [X]\r\n>   12", "- [\t]\t12", "-   [ ] 12"])
def test_task_whitespace_source_mapping_and_toggle(source):
    session = SourceSession(source)
    doc = parse_markdown(session)
    node = tasks(doc)[0]
    marker = source[node.span.start : node.span.end]
    assert marker in {"[ ]", "[X]", "[\t]"}
    assert "".join(o.text for o in doc.occurrences) == "\ufffc12"
    start, end, text = task_patch(doc, node.occurrences[0].occurrence_id)
    assert end - start == 1
    session.apply(start, end, text)
    assert (
        tasks(parse_markdown(session))[0].occurrences[0].occurrence_id
        == node.occurrences[0].occurrence_id
    )
    session.undo()
    assert session.source == source


def test_reference_links_emphasis_math_and_multi_paragraph_tasks():
    from test_math_layout import resolver

    source = "- [x] **12** $3+4$ [5](target)\n\n  67\n\n  - [ ] 8\n\n[x]: /target"
    doc = parse_markdown(source)
    assert len(tasks(doc)) == 2  # First marker is not consumed as a reference link.
    result = layout_markdown(doc, resolver())
    assert result.plotter_exportable, result.diagnostics
    assert Counter(o.occurrence_id for o in doc.occurrences) == Counter(
        f.occurrence_id for f in result.fragments
    )
    assert any(":underline:" in p.occurrence_id for page in result.pages for p in page.paint_ops)


def test_repeated_template_task_has_one_source_state_and_portable_geometry(tmp_path):
    from test_template_fields import setup

    from inkstruct.document.package import load_package, save_package
    from inkstruct.document.schema import StyleProfile

    session, doc, resolver, flow = setup("- [ ] 12\n\n3\n\n4\n\n5\n\n6\n\n7\n\n8", repeat=True)
    before = layout_markdown(doc, resolver, flow=flow)
    assert before.plotter_exportable, before.diagnostics
    boxes = [f for f in before.fragments if f.status.startswith("task-")]
    assert len(boxes) == len(before.pages) > 1 and len({f.occurrence_id for f in boxes}) == 1
    assert all(f.repeated == (f.page_index > 0) for f in boxes)
    session.apply(*task_patch(doc, boxes[-1].occurrence_id))
    after = layout_markdown(parse_markdown(session), resolver, flow=flow)
    assert after.plotter_exportable
    assert all(f.status == "task-checked" for f in after.fragments if f.status.startswith("task-"))
    project = tmp_path / "tasks.inkdoc"
    save_package(project, session, resolver, after.page_profile, StyleProfile(), flow=flow)
    loaded = load_package(project)
    assert (
        layout_markdown(
            parse_markdown(loaded.session),
            loaded.resolver,
            page=loaded.page,
            style=loaded.style,
            flow=loaded.flow,
        )
        == after
    )
