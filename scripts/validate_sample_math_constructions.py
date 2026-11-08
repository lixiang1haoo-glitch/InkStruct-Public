"""Compare recorded structural glyphs against geometric mode using a saved real project."""

import argparse
import json
from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path

from validate_symbol_samples import publish, write_json

from inkstruct.assets.resolver import AssetResolver
from inkstruct.assets.symbol_provider import SymbolProvider
from inkstruct.document.editing import SourceSession
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.package import load_package
from inkstruct.math.handwritten import measure_math


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    original_hash = sha256(args.project.read_bytes()).hexdigest()
    loaded = load_package(args.project)
    symbols = SymbolProvider.from_zip(args.archive)
    style = replace(
        loaded.flow.math,
        fraction_source="sample",
        radical_source="sample",
        delimiter_source="sample",
    )
    flow = replace(loaded.flow, math=style)
    baseline = publish("geometric", loaded.session, loaded.resolver, loaded.flow, args.output)
    recorded = publish("sampled", loaded.session, loaded.resolver, flow, args.output)
    provenance = []
    doc = parse_markdown(loaded.session)
    for node in (n for root in doc.nodes for n in root.walk() if n.math):
        box = measure_math(
            node.math,
            loaded.resolver,
            owner=node.node_id,
            style=style,
            stroke_width=loaded.style.stroke_width_mm,
            display=node.kind == "math_block",
        )
        assert box.ready
        provenance.extend(asdict(rule) for rule in box.rules)
    write_json(args.output / "construction-provenance.json", provenance)
    # Every available specimen of the requested constructs, not just the random
    # choices in a single document; raw JSON is never rewritten or recalibrated.
    records = []
    for character in "−√()[]{}|":
        for glyph in symbols.pools[character]:
            others = [g for c, pool in symbols.pools.items() if c != character for g in pool]
            r = AssetResolver(symbols=SymbolProvider([glyph, *others]))
            formulas = (
                [r"\frac{123.45}{67}", r"\frac{1}{\frac{2}{3}}"]
                if character == "−"
                else [r"\sqrt{1}", r"\sqrt{12345.6789}", r"\sqrt[3]{\frac{12}{3}}"]
                if character == "√"
                else [
                    r"\left"
                    + ("\\" if character in "{}" else "")
                    + character
                    + r"\frac{12}{3}\right."
                ]
            )
            for formula in formulas:
                session = SourceSession("$" + formula + "$")
                node = next(
                    n for root in parse_markdown(session).nodes for n in root.walk() if n.math
                )
                box = measure_math(node.math, r, owner=node.node_id, style=style)
                assert box.ready, (character, glyph.sample_id, box.diagnostics)
                assert any(rule.asset_id == glyph.asset_id for rule in box.rules)
                records.append(
                    {
                        "character": character,
                        "sample_id": glyph.sample_id,
                        "formula": formula,
                        "rules": len(box.rules),
                        "width": box.width,
                        "height": box.ascent + box.descent,
                    }
                )
    write_json(args.output / "all-specimen-probes.json", records)
    assert sha256(args.project.read_bytes()).hexdigest() == original_hash
    assert sha256(args.archive.read_bytes()).hexdigest() == symbols.archive_hash
    write_json(
        args.output / "verification.json",
        {
            "input_project": str(args.project),
            "input_sha256": original_hash,
            "archive_sha256": symbols.archive_hash,
            "geometric": baseline,
            "sampled": recorded,
            "specimen_probes": len(records),
            "construction_rules": len(provenance),
            "sampled_rules": sum(bool(r["asset_id"]) for r in provenance),
            "math_style": asdict(style),
            "physical_plotter_test": False,
            "provenance": "Rules reference the selected immutable specimen and explicit stretch transform.",
        },
    )
    (args.output / "compare.html").write_text(
        '<!doctype html><meta charset="utf-8"><title>公式构件对照</title><style>body{font:18px system-ui;margin:24px;background:#eef1f5}main{display:flex;gap:20px}section{width:50%}img{width:100%}</style><h1>几何构件 / 录制字形</h1><p>两侧源码与普通字符选择一致；右侧仅更换根号、分数线与伸缩括号。</p><main>'
        + "".join(
            "<section><h2>"
            + label
            + "</h2>"
            + "".join(
                f'<img src="{name}/preview/page-{i + 1:03d}.png">' for i in range(record["pages"])
            )
            + "</section>"
            for name, label, record in [
                ("geometric", "几何构件", baseline),
                ("sampled", "录制字形", recorded),
            ]
        )
        + "</main>"
    )
    print(
        json.dumps({"pages": recorded["pages"], "probes": len(records), "rules": len(provenance)})
    )


if __name__ == "__main__":
    main()
