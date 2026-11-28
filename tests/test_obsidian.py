"""An explicit static dialect, mapped source labels, and no implicit external reads."""

import io
import json
import subprocess
import sys
import zipfile
from collections import Counter
from dataclasses import replace
from hashlib import sha256

import pytest
from test_math_layout import resolver

from inkstruct.document.editing import SourceSession
from inkstruct.document.markdown import DIALECT_VERSION, parse_markdown
from inkstruct.document.obsidian import OBSIDIAN_VERSION
from inkstruct.document.package import load_package, package_bytes, save_package
from inkstruct.document.schema import PageProfile, StyleProfile
from inkstruct.document.styles import FlowStyle
from inkstruct.layout.blocks import body_blocks, layout_markdown
from inkstruct.plotter.adapters import plan_from_snapshot
from inkstruct.plotter.export import route_page
from inkstruct.plotter.svg import page_svg

FLOW = FlowStyle(markdown_dialect="obsidian")


def parse(source):
    return parse_markdown(source, dialect="obsidian")


def visible(d):
    return "".join(o.text for o in d.occurrences)


def test_opt_in_and_exact_target_alias_and_non_bmp_crlf_source_ranges():
    source = "> [!note]- **12**\r\n> [[库/文件#标题|34😀]] ![[其他#^块|56]]\r\n"
    regular = parse_markdown(source)
    doc = parse(source)
    assert regular.dialect == DIALECT_VERSION and doc.dialect == OBSIDIAN_VERSION
    assert regular.content_key != doc.content_key
    assert not any(n.kind == "wiki_link" for r in regular.nodes for n in r.walk())
    assert visible(doc) == "1234😀 56"
    callout = doc.nodes[0]
    assert callout.kind == "callout" and dict(callout.attributes)["fold"] == "collapsed"
    refs = [n for n in callout.walk() if n.kind.startswith("wiki_")]
    assert [dict(n.attributes)["target"] for n in refs] == ["库/文件#标题", "其他#^块"]
    for o in doc.occurrences:
        assert source[o.span.start : o.span.end] == o.text
    assert source[refs[0].span.start : refs[0].span.end] == "[[库/文件#标题|34😀]]"
    assert {d.code for d in doc.diagnostics} == {"obsidian-embed-label-only"}


@pytest.mark.parametrize(
    "source,text",
    [
        ("[[12]]", "12"),
        ("[[#标题|12]]", "12"),
        ("[[文件#^块|12]]", "12"),
        ("[[路径/12#34]]", "路径/12#34"),
        ("[[1|**12**]]", "**12**"),
        ("|1|\n|---|\n|[[路径\\|12.50]]|", "112.50"),
        ("[[[1]]]", "[1]"),
    ],
)
def test_static_wiki_display_contract(source, text):
    assert visible(parse(source)) == text


@pytest.mark.parametrize(
    "source",
    ["![[文件]]", "![[image.png|400]]", "![[image.png|400x300]]", "[[|1]]", "[[1|]]", "[[1|2|3]]"],
)
def test_unresolved_or_ambiguous_reference_has_explicit_error(source):
    d = parse(source)
    assert any(
        i.code == "obsidian-reference-invalid" and i.severity == "error" for i in d.diagnostics
    )
    assert not layout_markdown(d, resolver(source), flow=FLOW).plotter_exportable


@pytest.mark.parametrize(
    "source",
    ["`[[1|2]]`", "```\n[[1|2]]\n```", r"\[[1|2]]", "$1+2$", "> 1\n> [!note] 2", "[!note] 12"],
)
def test_code_escapes_math_and_non_callout_positions_are_not_reinterpreted(source):
    assert not any(
        n.kind in {"wiki_link", "wiki_embed", "callout"}
        for r in parse(source).nodes
        for n in r.walk()
    )


def test_nested_callouts_default_title_empty_body_and_keep_next():
    source = "> [!NOTE]\n>\n> > [!custom-tip]+ 12\n> > 34\n\n> [!info] 56"
    doc = parse(source)
    assert visible(doc) == "Note123456"
    nodes = [n for r in doc.nodes for n in r.walk()]
    assert len([n for n in nodes if n.kind == "callout"]) == 3
    title = doc.nodes[0].children[0]
    for o in next(n for n in title.walk() if n.occurrences).occurrences:
        assert source[o.span.start : o.span.end].lower() == o.text.lower()
    blocks = body_blocks(doc, FLOW)
    titles = [b for b in blocks if b.node.kind == "callout_title"]
    assert len(titles) == 3 and all(b.keep_next for b in titles)
    s = layout_markdown(doc, resolver("Note123456"), flow=FLOW)
    assert s.exportable, s.diagnostics
    assert Counter(f.occurrence_id for f in s.fragments) == Counter(
        o.occurrence_id for o in doc.occurrences
    )


def test_callout_title_math_tasks_and_table_share_layout():
    source = "> [!tip]- $\\vec{12}$\n>\n> - [x] [[远处|34]]\n>\n> |5|\n> |---|\n> |![[附件\\|6.5]]|\n\n> [!note] 7\n> [[文件|89]]"
    doc = parse(source)
    s = layout_markdown(doc, resolver(), flow=FLOW)
    assert s.plotter_exportable, s.diagnostics
    actual = Counter(f.occurrence_id for f in s.fragments if not f.repeated)
    assert actual == Counter(o.occurrence_id for o in doc.occurrences)
    task = next(n for r in doc.nodes for n in r.walk() if n.kind == "task_checkbox")
    assert any(
        op.occurrence_id == task.occurrences[0].occurrence_id for p in s.pages for op in p.paint_ops
    )


def test_callout_can_continue_pages_but_title_keeps_first_body_line():
    source = "1\n\n2\n\n3\n\n> [!note] 4\n> 5\n>\n> " + ("6 " * 120)
    doc = parse(source)
    s = layout_markdown(doc, resolver(), flow=FLOW, page=PageProfile(60, 60, 5))
    assert s.exportable, s.diagnostics
    title = next(o for o in doc.occurrences if o.text == "4")
    first = next(o for o in doc.occurrences if o.text == "5")
    by = {f.occurrence_id: f for f in s.fragments}
    assert by[title.occurrence_id].page_index == by[first.occurrence_id].page_index
    assert len(s.pages) > 1


def test_switch_edit_undo_and_native_package_preserve_source_choices_and_mode(tmp_path):
    session = SourceSession("> [!note] 12\n> [[目标|34]] ![[附件|56]]")
    r = resolver()
    doc = parse(session)
    s = layout_markdown(doc, r, flow=FLOW)
    old = [o.occurrence_id for o in doc.occurrences]
    choices = r.selection_records()
    at = session.source.index("目标")
    session.apply(at, at + 2, "更长的目标")
    assert [o.occurrence_id for o in parse(session).occurrences] == old
    layout_markdown(parse(session), r, flow=FLOW)
    assert r.selection_records() == choices
    session.undo()
    assert parse(session).occurrences == doc.occurrences
    path = tmp_path / "obsidian.inkdoc"
    save_package(path, session, r, s.page_profile, StyleProfile(), flow=FLOW, optimize=True)
    p = load_package(path)
    assert p.flow.markdown_dialect == "obsidian"
    again = layout_markdown(
        parse_markdown(p.session, dialect=p.flow.markdown_dialect),
        p.resolver,
        page=p.page,
        style=p.style,
        flow=p.flow,
    )
    assert replace(again, revision=s.revision) == s and p.session.source == session.source
    canonical = lambda pts: min(pts, tuple(reversed(pts)))
    for page in plan_from_snapshot(s).pages:
        routed = route_page(page, optimize=True).page
        assert Counter(canonical(st.points) for st in page.strokes) == Counter(
            canonical(st.points) for st in routed.strokes
        )
        assert "<path" in page_svg(routed)


def test_manifest_dialect_mismatch_is_rejected_and_legacy_default_is_preserved(tmp_path):
    raw = package_bytes(SourceSession("1"), resolver(), PageProfile(), StyleProfile(), flow=FLOW)
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        members = {n: z.read(n) for n in z.namelist()}
    manifest = json.loads(members["manifest.json"])
    manifest["dialect"] = DIALECT_VERSION
    members["manifest.json"] = json.dumps(manifest).encode()
    path = tmp_path / "bad.inkdoc"
    with zipfile.ZipFile(path, "w") as z:
        for name, data in members.items():
            z.writestr(name, data)
    with pytest.raises(ValueError, match="dialect disagree"):
        load_package(path)
    raw = package_bytes(SourceSession("1"), resolver(), PageProfile(), StyleProfile())
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        members = {n: z.read(n) for n in z.namelist()}
    styles = json.loads(members["styles.json"])
    styles["flow"].pop("markdown_dialect")
    members["styles.json"] = json.dumps(styles).encode()
    manifest = json.loads(members.pop("manifest.json"))
    manifest["sha256"] = {n: sha256(data).hexdigest() for n, data in members.items()}
    members["manifest.json"] = json.dumps(manifest).encode()
    with zipfile.ZipFile(path, "w") as z:
        for name, data in members.items():
            z.writestr(name, data)
    assert load_package(path).flow.markdown_dialect == "markdown"
    with pytest.raises(ValueError):
        replace(FLOW, markdown_dialect="unknown")


def test_cli_inspection_resources_and_render_use_only_visible_labels(tmp_path):
    source = tmp_path / "labels.md"
    source.write_text(
        "> [!note] 12\n> [[/nonexistent/秘密|34]] ![[https://invalid.example/a|56.5]]"
    )
    for mode in ("inspect", "resources"):
        p = subprocess.run(
            [sys.executable, "-m", "inkstruct.cli", "document", mode, str(source), "--dialect", "obsidian"],
            capture_output=True,
            check=False,
            text=True,
        )
        assert p.returncode == 0, p.stderr + p.stdout
        result = json.loads(p.stdout)
        if mode == "inspect":
            assert result["document"]["dialect"] == OBSIDIAN_VERSION
        else:
            assert all(g["character"] not in "秘密notehttps" for g in result["gaps"])
    output = tmp_path / "out"
    native = tmp_path / "labels.inkdoc"
    args = [
        sys.executable, "-m", "inkstruct.cli",
        "document",
        "render",
        str(source),
        "--mode",
        "markdown",
        "--dialect",
        "obsidian",
        "--plotter",
        "--output",
        str(output),
        "--save-project",
        str(native),
    ]
    p = subprocess.run(args, capture_output=True, check=False, text=True)
    assert p.returncode == 0, p.stderr + p.stdout
    assert load_package(native).flow.markdown_dialect == "obsidian"
    p = subprocess.run(
        [
            sys.executable, "-m", "inkstruct.cli",
            "document",
            "render",
            str(native),
            "--plotter",
            "--output",
            str(tmp_path / "again"),
        ],
        capture_output=True,
        check=False,
        text=True,
    )
    assert p.returncode == 0, p.stderr + p.stdout
    assert (output / "page-001.svg").read_bytes() == (tmp_path / "again/page-001.svg").read_bytes()
