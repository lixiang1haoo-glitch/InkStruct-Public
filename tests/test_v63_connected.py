"""Controlled pen-down truth and end-to-end physical trajectory preservation."""

import json
from pathlib import Path

import numpy as np
import pytest

from inkstruct.assets.resolver import AssetResolver
from inkstruct.document.editing import SourceSession
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.package import load_package, save_package
from inkstruct.document.schema import PageProfile, StyleProfile
from inkstruct.fonts.core import FontPackage, decode
from inkstruct.fonts.library import publish_font
from inkstruct.fonts.publication import publication_stamp, review_selection
from inkstruct.generation_workflow import read, write
from inkstruct.layout.blocks import layout_markdown
from inkstruct.samples import load_raw_sample, sha256_file
from inkstruct.structure_corrections import POLICY
from inkstruct.structures import StructureRepository, build_database
from inkstruct.v63 import generate, make_archive, new_relationships, sample_units


@pytest.fixture
def setup(tmp_path):
    graphics = tmp_path / "graphics.txt"
    dictionary = tmp_path / "dictionary.txt"
    database = tmp_path / "structures.sqlite3"
    # Two top-level components with two spatially distinct strokes each.
    medians = [
        [[170, 720], [400, 720]], [[170, 470], [400, 470]],
        [[620, 790], [620, 300]], [[810, 750], [810, 360]],
    ]
    graphics.write_text(json.dumps({"character": "明", "medians": medians, "strokes": [""] * 4},
                                   ensure_ascii=False) + "\n", encoding="utf-8")
    dictionary.write_text(json.dumps({"character": "明", "decomposition": "⿰日月", "radical": "日",
                                      "matches": [[0], [0], [1], [1]]}, ensure_ascii=False) + "\n",
                          encoding="utf-8")
    build_database(graphics, dictionary, database, source_version="v63 test")
    repo = StructureRepository(database)
    config = tmp_path / "corrections.json"
    write(config, {"policy": POLICY, "graphics_sha256": sha256_file(graphics),
                   "dictionary_sha256": sha256_file(dictionary), "database_content_sha256": repo.content_sha256(),
                   "outline_repairs": []})
    graph = repo.get("明")
    return repo, graph, (graphics, dictionary, config)


def record(path, graph, *, join, omit=()):
    traces = [[(x*80+10, y*80+10) for x, y in s.median] for s in graph.strokes]
    traces[join:join+2] = [traces[join]+traces[join+1]]
    clock = 0
    strokes = []
    for index, trace in enumerate(traces):
        if index in omit:
            continue
        points = []
        for x, y in trace:
            points.append({"x": x, "y": y, "pressure": .4+clock/2000, "t_ms": clock})
            clock += 20
        strokes.append({"points": points})
        clock += 60
    write(path, {"schema_version": "handwriting_single_v1", "sample_id": path.stem,
                 "character": graph.character, "writer_id": "alice",
                 "capture": {"canvas_width": 100, "canvas_height": 100}, "strokes": strokes})
    return load_raw_sample(path)


def test_only_locally_complete_contiguous_units_enter_archive(setup, tmp_path):
    _, graph, _ = setup
    joined = record(tmp_path / "joined.json", graph, join=0, omit=(2,))
    units = {path: points for path, _, points in sample_units(joined, graph)}
    assert set(units) == {"root.0"}
    assert units["root.0"][0]["slots"] == ["s1", "s2"]
    assert [p["pressure"] for p in units["root.0"][0]["points"]] == [p.pressure for p in joined.strokes[0].points]
    crossing = record(tmp_path / "cross.json", graph, join=1)
    assert [path for path, _, _ in sample_units(crossing, graph)] == ["whole"]
    missing = record(tmp_path / "missing.json", graph, join=0, omit=(0,))
    assert sample_units(missing, graph) == []


def test_transfer_rejects_new_neighbor_crossing_and_close_contact():
    neighbor = np.array([[.5, .1], [.5, .9]])
    before = np.array([[.2, .5], [.3, .5]])
    close = np.array([[.2, .5], [.499, .5]])
    crossed = np.array([[.3, .5], [.7, .5]])
    assert not new_relationships([before], [neighbor], [[before]])
    assert new_relationships([close], [neighbor], [[before]])
    assert new_relationships([crossed], [neighbor], [[before]])


def test_build_font_publish_and_freeze_unsplit_path(setup, tmp_path, monkeypatch):
    repo, graph, refs = setup
    source = tmp_path / "raw" / "connected.json"
    sample = record(source, graph, join=0)
    archive, run, library = (tmp_path / n for n in ("archive", "run", "library"))
    summary = make_archive(source.parent, "alice", repo, archive)
    assert summary["connected_whole"] == 1 and summary["split_donors"] == 0
    assert load_raw_sample(source) == sample
    result = generate(archive, repo, "明", run, refs, same_character=True)
    assert result["methods"] == {"same_character": 1}
    grouped = read(run / "U+660E.json")
    assert grouped["segments"][0]["standard_slots"] == ["s1", "s2"]
    points = grouped["segments"][0]["points"]
    assert [p["pen_state"] for p in points] == ["down"]*(len(points)-1)+["up"]
    assert [p["pressure"] for p in points] == [p.pressure for p in sample.strokes[0].points]
    assert [p["t_ms"] for p in points] == [p.t_ms for p in sample.strokes[0].points]
    review = review_selection("alice", run, None, "connected", {"han"})
    assert review["batch"]["method"] == "v6.3 exp"
    stamp = publication_stamp("alice", run, None)
    kwargs = dict(writer="alice", run=run, symbols=None, name="connected", package_kind="user",
                  groups={"han"}, stamp=stamp, expected=review["coverage"], progress=lambda _: None)
    with monkeypatch.context() as mp:
        def fail(*_args, **_kwargs):
            raise ValueError("injected")
        mp.setattr(FontPackage, "verify", fail)
        with pytest.raises(ValueError, match="injected"):
            publish_font(library, **kwargs)
    assert list(library.glob("*.inkfont")) == []
    report = publish_font(library, **kwargs)
    assert not report["difference"] and report["verification"]["candidates"] == 1
    font = FontPackage(Path(report["path"]))
    asset = next(font.glyphs())
    font_core = decode(asset.original_json)
    assert font_core["trajectory"]["strokes"][0]["points"] == points
    assert font_core["summary"]["v63_standard_slots"] == ["s1", "s2", "s3", "s4"]

    session = SourceSession("明明")
    resolver = AssetResolver(embedded=[asset])
    before = layout_markdown(parse_markdown(session), resolver)
    assert before.exportable
    document = tmp_path / "connected.inkdoc"
    save_package(document, session, resolver, PageProfile(), StyleProfile())
    reopened = load_package(document)
    assert layout_markdown(parse_markdown(reopened.session), reopened.resolver) == before
    with monkeypatch.context() as mp:
        # Recreate the stamp after tampering. The batch's own digest still fails.
        grouped["segments"][0]["points"][0]["x"] += .01
        write(run / "U+660E.json", grouped)
        mp.setitem(kwargs, "stamp", publication_stamp("alice", run, None))
        with pytest.raises(ValueError, match="摘要不符"):
            publish_font(library, **kwargs)
    assert len(list(library.glob("*.inkfont"))) == 1
