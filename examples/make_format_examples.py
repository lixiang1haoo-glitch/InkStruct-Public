"""Write two synthetic exchange examples with the application package writers."""

import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from inkstruct.assets.resolver import AssetResolver, SelectedAsset
from inkstruct.document.editing import SourceSession
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.package import load_package, save_package
from inkstruct.document.schema import PageProfile, StyleProfile
from inkstruct.fonts.core import FontPackage
from inkstruct.fonts.identity import release_identity
from inkstruct.fonts.importer import build_font


def sample(number, bars):
    return {
        "schema_version": "inkstruct_symbol_sample_v1",
        "character": "A",
        "sample_id": f"synthetic-{number}",
        "writer_id": "format-example",
        "variant": {"letter_style": "upright"},
        "capture": {"coordinate_space": "logical_px"},
        "guides": {"em_px": 100, "origin_x_px": 10, "baseline_y_px": 80},
        "strokes": [
            {"points": [{"x": x, "y": y} for x, y in points]}
            for points in bars
        ],
    }


def make_examples(output):
    font_path = output / "two-shapes.inkfont"
    doc_path = output / "two-shapes.inkdoc"
    if font_path.exists() or doc_path.exists():
        raise FileExistsError("Choose a directory without existing two-shapes examples")
    output.mkdir(parents=True, exist_ok=True)
    variants = (
        [[(12, 80), (40, 16), (68, 80)], [(23, 53), (58, 53)]],
        [[(16, 80), (34, 13), (72, 80)], [(24, 55), (57, 48)]],
    )
    with TemporaryDirectory() as directory:
        symbols = Path(directory)
        for number, strokes in enumerate(variants):
            (symbols / f"{number}.json").write_text(
                json.dumps(sample(number, strokes)), encoding="utf-8"
            )
        build_font(
            font_path, writer="format-example", name="Two Shapes", symbols=symbols,
            package_kind="user",
        )

    font = FontPackage(font_path, verify_all=False)
    assert font.verify()["candidates"] == 2
    glyphs = tuple(font.glyphs("A"))
    session = SourceSession("A A\n")
    occurrences = [o for o in parse_markdown(session).occurrences if o.text == "A"]
    selections = [
        SelectedAsset(
            occurrence.occurrence_id, "A", glyph.asset_id, glyph.sample_id,
            glyph.metrics_key, requested_style="upright", resolved_style="upright",
        )
        for occurrence, glyph in zip(occurrences, glyphs, strict=True)
    ]
    resolver = AssetResolver(
        embedded=glyphs, selections=selections, font_identity=release_identity(font.identity)
    )
    save_package(doc_path, session, resolver, PageProfile(), StyleProfile())
    restored = load_package(doc_path)
    assert restored.resolver.selection_records() == resolver.selection_records()
    reopened = [o for o in parse_markdown(restored.session).occurrences if o.text == "A"]
    assert [restored.resolver.resolve(o).strokes for o in reopened] == [g.strokes for g in glyphs]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    make_examples(parser.parse_args().output)
