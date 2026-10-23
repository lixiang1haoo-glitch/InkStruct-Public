"""Freeze a seen/unseen writer set and compare archived, pre-fix and current output.

Writes private evidence only under --output. The source archive is read-only.
This is a geometry/protocol regression check, not a human quality acceptance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import types
from dataclasses import asdict
from html import escape
from pathlib import Path

from inkstruct.evaluate import evaluate_run
from inkstruct.generate import DeterministicGenerator, generate_run
from inkstruct.profile import load_profile
from inkstruct.render import render_svg
from inkstruct.samples import iter_index, sha256_file
from inkstruct.structures import StructureRepository

BASELINE = "c2c180d14701026599b1bf7095aeb490a9119efc"
CASES = "岛尴徹徼徽勾匈囊丢侈黧劓乌熟尬"


def compare_archived_strokes(archived: list[dict], recomputed: list[dict]) -> str:
    if archived == recomputed:
        return "exact"
    # Across NumPy/platform versions, tie rounding of pressure can differ at
    # the last serialized decimal. Geometry, timestamps and metadata stay exact.
    normalized = json.loads(json.dumps(archived))
    if len(normalized) != len(recomputed):
        return "mismatch"
    for left, right in zip(normalized, recomputed, strict=True):
        if len(left["points"]) != len(right["points"]):
            return "mismatch"
        for a, b in zip(left["points"], right["points"], strict=True):
            if abs(a["pressure"] - b["pressure"]) > 1.000001e-6:
                return "mismatch"
            a["pressure"] = b["pressure"]
    return "pressure_rounding_only" if normalized == recomputed else "mismatch"


def select_characters(supported: list[str], seen: set[str], count: int) -> list[str]:
    selected = [c for c in CASES if c in supported]
    if count < len(selected):
        raise ValueError(f"count must be at least {len(selected)}")
    def ranked(values):
        return sorted(values, key=lambda c: hashlib.sha256(("mac-baseline-v1:" + c).encode()).digest())
    # Balanced strata; all repeats of a character have the same seen/unseen label.
    pools = [ranked(set(supported) & seen), ranked(set(supported) - seen)]
    for pool, in_seen in zip(pools, (True, False), strict=True):
        needed = count // 2 - sum((c in seen) == in_seen for c in selected)
        selected.extend([c for c in pool if c not in selected][:max(0, needed)])
    selected.extend([c for c in ranked(supported) if c not in selected][:count - len(selected)])
    return selected


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--writer", required=True)
    parser.add_argument("--old-run", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--database", type=Path, default=Path("artifacts/structures/characters.sqlite3"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--count", type=int, default=256)
    args = parser.parse_args()
    # A new output directory avoids overwriting an earlier audit or gallery.
    args.output.mkdir(parents=True, exist_ok=False)
    structures = StructureRepository(args.database)
    profile = load_profile(args.profile)
    if profile.writer_id != args.writer:
        raise ValueError("profile writer mismatch")
    if profile.source_index_sha256 != sha256_file(args.index):
        raise ValueError("index differs from the archived profile's source index")
    old_manifest = json.loads((args.old_run / "manifest.json").read_text(encoding="utf-8"))
    expected = {"writer_id": args.writer, "profile_version": profile.profile_version,
                "component_mode": "adaptive", "component_strength": 1.0, "checkpoint": None}
    if any(old_manifest.get(key) != value for key, value in expected.items()):
        raise ValueError("archived run identity is not the requested deterministic adaptive profile")
    excluded = {s["sample_id"] for s in profile.excluded_samples}
    seen = {s.character for s in iter_index(args.index)
            if s.writer_id == args.writer and s.sample_id not in excluded}
    characters = select_characters(structures.characters(), seen, args.count)
    source = subprocess.check_output(
        ["git", "show", f"{BASELINE}:src/inkstruct/generate.py"], text=True, encoding="utf-8"
    )
    module = types.ModuleType("inkstruct._writer_baseline")
    module.__package__ = "inkstruct"
    exec(compile(source, "baseline_generate.py", "exec"), module.__dict__)  # noqa: S102
    version = structures.metadata().get("source_version", "unknown")
    old_generator = module.DeterministicGenerator(profile, version, "adaptive")
    current_generator = DeterministicGenerator(profile, version, "adaptive")
    manifest, run = generate_run(
        args.writer, characters, structures, args.profile,
        output_root=args.output / "current", run_id="boundary_v1", png=False,
    )
    evaluation = evaluate_run(run, structures)
    archive = args.output / "archived"
    archive.mkdir()
    shutil.copyfile(args.old_run / "manifest.json", archive / "manifest.json")
    rows, gallery = [], []
    for character in characters:
        graph = structures.get(character)
        old = old_generator.generate(graph)
        current = current_generator.generate(graph)
        archived_path = args.old_run / "trajectories" / f"{graph.codepoint}.json"
        archived = json.loads(archived_path.read_text(encoding="utf-8"))
        shutil.copyfile(archived_path, archive / archived_path.name)
        old_strokes, new_strokes = asdict(old)["strokes"], asdict(current)["strokes"]
        archive_comparison = compare_archived_strokes(archived["strokes"], old_strokes)
        changed = old_strokes != new_strokes
        fit = current.canvas_fit
        rows.append({
            "character": character, "seen": character in seen,
            "archive_sha256": sha256_file(archive / archived_path.name),
            "archive_comparison": archive_comparison,
            "changed": changed, "canvas_fit": fit,
        })
        # A/B labels vary deterministically; the private report contains the key.
        swap = ord(character) % 2 == 1
        rows[-1]["gallery_a"] = "current" if swap else "baseline"
        for label, glyph in zip(("A", "B"), (current, old) if swap else (old, current), strict=True):
            render_svg(glyph, args.output / "gallery" / f"{graph.codepoint}-{label}.svg", 240)
        gallery.append(
            f'<article><h2>{escape(character)} · {"已见" if character in seen else "未见"}</h2>'
            + ''.join(f'<figure><img src="gallery/{graph.codepoint}-{label}.svg">'
                      f'<figcaption>{label}</figcaption></figure>' for label in ("A", "B"))
            + '</article>'
        )
    report = {
        "writer": args.writer, "baseline_commit": BASELINE,
        "current_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "current_generate_sha256": sha256_file(Path("src/inkstruct/generate.py")),
        "profile_sha256": sha256_file(args.profile), "index_sha256": sha256_file(args.index),
        "database_sha256": sha256_file(args.database),
        "archived_manifest_sha256": sha256_file(archive / "manifest.json"),
        "characters": characters, "seen_count": sum(c in seen for c in characters),
        "archive_mismatches": [r["character"] for r in rows if r["archive_comparison"] == "mismatch"],
        "archive_pressure_rounding_only": [
            r["character"] for r in rows if r["archive_comparison"] == "pressure_rounding_only"
        ],
        "changed_characters": [r["character"] for r in rows if r["changed"]],
        "changed_without_fit": [r["character"] for r in rows if r["changed"] and not r["canvas_fit"]["applied"]],
        "evaluation": evaluation, "generation_failed_count": manifest["failed_count"],
        "human_quality_review": "pending; sampled comparison set is not an approved protection set",
        "rows": rows,
    }
    (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    (args.output / "comparison.html").write_text(
        '<!doctype html><meta charset="utf-8"><title>InkStruct 作者回归对照</title>'
        '<style>body{font-family:system-ui;margin:32px;background:#f4f5f7}'
        'main{display:flex;flex-wrap:wrap;gap:16px}article{background:white;padding:16px}'
        'figure{display:inline-block;margin:8px;text-align:center}h2{font-size:18px}</style>'
        '<h1>作者回归 A/B 对照</h1><p>固定抽样；A/B 顺序逐字变化。'
        '用于人工检查，未完成字形质量验收。对应关系及输入哈希保存在 report.json。</p><main>'
        + ''.join(gallery) + '</main>', encoding="utf-8"
    )
    print(json.dumps({k: v for k, v in report.items() if k not in ("rows", "characters")}, ensure_ascii=False))
    return int(bool(report["archive_mismatches"] or report["changed_without_fit"]
                    or manifest["failed_count"] or evaluation["structural_failure_count"]))


if __name__ == "__main__":
    raise SystemExit(main())
