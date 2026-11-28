from dataclasses import replace
from hashlib import sha256
import json
import zipfile

import pytest

from test_math_layout import resolver as handwriting
from inkstruct.document.editing import SourceSession
from inkstruct.document.flow_template import PageLayout, PaperGrid
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.package import load_package, save_package
from inkstruct.document.schema import PageProfile, StyleProfile
from inkstruct.document.styles import FlowStyle
from inkstruct.layout.blocks import layout_markdown
from test_flow_templates import frame, template


@pytest.mark.parametrize("grid", [None, PaperGrid(8, 48, 5), PaperGrid(5, 45, 5, 12)])
def test_markers_keep_text_and_spans_after_reopen(tmp_path, grid):
    text = "见[^1]\n\n[^1]: 注文\n\n[链接][url] $x^2$\n\n[url]: https://example.org"
    doc = SourceSession(text)
    box = replace(frame(w=100, h=50), paper_grid=grid)
    flow = FlowStyle(template=template(layouts=(PageLayout("p1", "paper", (box,)),)))
    resolver = handwriting("见[^1]:注文链接x2")
    path = tmp_path / "sample.inkdoc"
    save_package(path, doc, resolver, PageProfile(), StyleProfile(), flow=flow)
    with zipfile.ZipFile(path) as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    styles = json.loads(files["styles.json"])
    assert "footnote" not in styles["flow"]
    styles["flow"]["footnote"] = {
        "schema_version": "inkstruct_footnote_style_v1",
        "text_scale": 0.75,
    }
    files["styles.json"] = json.dumps(styles).encode()
    manifest = json.loads(files["manifest.json"])
    manifest["sha256"]["styles.json"] = sha256(files["styles.json"]).hexdigest()
    files["manifest.json"] = json.dumps(manifest).encode()
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    original = path.read_bytes()
    saved = load_package(path)
    assert path.read_bytes() == original
    copy = tmp_path / "resaved.inkdoc"
    save_package(copy, saved.session, saved.resolver, saved.page, saved.style, flow=saved.flow)
    with zipfile.ZipFile(copy) as archive:
        assert "footnote" not in json.loads(archive.read("styles.json"))["flow"]
    saved = load_package(copy)
    assert saved.session.source == text and saved.flow == flow
    for dialect in ("markdown", "obsidian"):
        parsed = parse_markdown(saved.session, dialect=dialect)
        kinds = {n.kind for root in parsed.nodes for n in root.walk()}
        assert {"math_inline", "link"} <= kinds
        assert not any("footnote" in k for k in kinds)
        snap = layout_markdown(parsed, resolver, flow=flow)
        literal = "".join(f.text for f in snap.fragments)
        assert "见[^1][^1]: 注文" in literal
        assert snap.plotter_exportable, snap.diagnostics
        from inkstruct.renderers.pages import page_draw

        assert page_draw(snap, 0, False).strokes
        assert len([n for root in parsed.nodes for n in root.walk() if n.kind == "link"]) == 1
        assert not any("footnote" in d.code for d in snap.diagnostics)
    plain = parse_markdown(saved.session, dialect="plain-text")
    assert "[链接][url] $x^2$" in "".join(o.text for o in plain.occurrences)
