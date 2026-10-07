"""Export real source/16-point/8-point/spline compression evidence for selected glyphs.

The compression probe isolates sampling loss. It is NOT the full production
decoder: layout, prototype averaging and mixing are separate mechanisms.
Actual production before/after-canvas trajectories and selected routes are saved
alongside it. All evidence is private and should stay under artifacts/.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from inkstruct.alignment import align_sample
from inkstruct.generate import DeterministicGenerator
from inkstruct.geometry import cubic_bspline, path_length, resample
from inkstruct.profile import load_profile
from inkstruct.samples import iter_index, sha256_file
from inkstruct.source_trajectory import source_trajectory
from inkstruct.structures import StructureRepository


def max_deviation(source, target) -> float:
    """Maximum source vertex distance to the target polyline (one-way)."""
    points, curve = np.asarray(source), np.asarray(target)
    starts, vectors = curve[:-1], curve[1:] - curve[:-1]
    lengths = np.sum(vectors * vectors, axis=1)
    fractions = np.clip(
        np.sum((points[:, None] - starts) * vectors, axis=2) / np.maximum(lengths, 1e-20), 0, 1
    )
    projections = starts + fractions[:, :, None] * vectors
    return float(np.linalg.norm(points[:, None] - projections, axis=2).min(axis=1).max())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--writer", required=True)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--database", type=Path, default=Path("artifacts/structures/characters.sqlite3"))
    parser.add_argument("--characters", default="岛尴熟尬勾匈囊丢侈黧徹徼徽")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    structures, profile = StructureRepository(args.database), load_profile(args.profile)
    if profile.writer_id != args.writer:
        raise ValueError("profile writer mismatch")
    generator = DeterministicGenerator(profile, structures.metadata()["source_version"], "adaptive")
    evidence, exclusions = [], []
    found = set()
    for sample in iter_index(args.index):
        if sample.character not in args.characters or sample.writer_id != args.writer:
            continue
        found.add(sample.character)
        graph = structures.get(sample.character)
        aligned = align_sample(sample, graph)
        source, reason = source_trajectory(sample, aligned, graph)
        if source is None:
            exclusions.append({"sample_id": sample.sample_id, "character": sample.character, "reason": reason})
            continue
        rows = []
        for stroke in source.strokes:
            points16 = resample(stroke.points, 16)
            controls8 = resample(points16, 8)
            smoothed = resample(cubic_bspline(controls8, 128, clip=False), 128)
            stages = {"source": stroke.points, "points16": points16,
                      "controls8": controls8, "spline128": smoothed}
            rows.append({
                "standard_stroke_id": stroke.standard_stroke_id,
                "stages": stages,
                "lengths": {key: path_length(points) for key, points in stages.items()},
                "max_source_vertex_deviation": {
                    key: max_deviation(stroke.points, points)
                    for key, points in stages.items() if key != "source"
                },
            })
        raw, final = generator._generate_raw(graph), generator.generate(graph)
        result = {"source": asdict(source), "compression_probe": rows,
                  "production_before_canvas": asdict(raw), "production_after_canvas": asdict(final)}
        # sample_id is data, never a filesystem path.
        name = f"{graph.codepoint}-{len(evidence):03d}"
        (args.output / f"{name}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        # Shared glyph coordinate frame and scale across the four probe panels.
        image = Image.new("RGB", (1200, 330), "white")
        draw = ImageDraw.Draw(image)
        for column, stage in enumerate(("source", "points16", "controls8", "spline128")):
            draw.text((column * 300 + 18, 10), f"{graph.codepoint}  {stage}", fill="#334155")
            for row in rows:
                xy = [(column * 300 + 20 + x * 260, 40 + y * 260) for x, y in row["stages"][stage]]
                draw.line(xy, fill="#111827", width=2)
        image.save(args.output / f"{name}.png")
        evidence.append({"sample_id": sample.sample_id, "character": sample.character,
                         "json": f"{name}.json", "preview": f"{name}.png", "strokes": [
                             {k: v for k, v in row.items() if k != "stages"} for row in rows
                         ]})
    report = {"scope": __doc__, "writer": args.writer,
              "index_sha256": sha256_file(args.index), "profile_sha256": sha256_file(args.profile),
              "structure_content_sha256": structures.content_sha256(),
              "missing_characters": sorted(set(args.characters) - found),
              "excluded": exclusions, "samples": evidence}
    (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"samples": len(evidence), "excluded": exclusions,
                      "missing_characters": report["missing_characters"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
