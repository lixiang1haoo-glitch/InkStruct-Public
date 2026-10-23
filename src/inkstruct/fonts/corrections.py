"""Derive a fully verified font without overwriting its source or hiding provenance."""

import copy
import os
import tempfile
import uuid
import zipfile
from dataclasses import asdict
from pathlib import Path

from .core import (
    FontPackage,
    decode,
    encoded,
    semantic_hash,
    trajectory_hashes,
    validate_candidate,
    write_archive,
)
from .parallel_verify import verify_font


def correct_font(source, output, glyph, correction, *, all_samples=False,
                 include_styles=False, progress=lambda _: None):
    output = Path(output)
    if output.exists():
        raise FileExistsError(output)
    if (type(all_samples) is not bool or type(include_styles) is not bool or
            (include_styles and not all_samples) or glyph.font_core is None):
        raise ValueError("写入字体包需要已验证的字体候选")
    font = FontPackage(source, verify_all=False)
    progress("正在完整校验来源字体…")
    verify_font(font, progress=progress)
    core = glyph.font_core
    if font.identity != core["identity"]:
        raise ValueError("来源字体与所选字形版本不一致；请使用该文档的原始字体包")
    selected = next((r for r in font.records if r == core["record"]), None)
    if selected is None:
        raise ValueError("来源字体缺少所选候选")
    if correction.scope != "character" or correction.character != glyph.character:
        raise ValueError("字体包校正必须指定所选字符")
    # Another style is included only by an explicit, separate choice.
    targets = [r for r in font.records if r["character"] == glyph.character and
               (include_styles or r["letter_style"] == selected["letter_style"]) and
               (all_samples or r["candidate_id"] == selected["candidate_id"])]
    index, metrics, provenance = copy.deepcopy(font.index), copy.deepcopy(font.metrics), copy.deepcopy(font.provenance)
    manifest = {k: v for k, v in font.manifest.items()
                if k not in {"members", "content_hash", "core_hash", "core_members"}}
    manifest.update(release_id=str(uuid.uuid4()), package_id=str(uuid.uuid4()),
                    name=manifest["name"] + " · 校正",
                    derived_from_package={"package_id": font.manifest["package_id"],
                                          "content_hash": font.manifest["content_hash"]})
    result_stats = []
    with tempfile.TemporaryDirectory(dir=Path(output).parent) as folder, zipfile.ZipFile(font.path) as archive:
        members = {}
        for i, name in enumerate(font.manifest["members"]):
            progress(f"正在保留字体成员 {i+1}/{len(font.manifest['members'])}…") if i % 512 == 0 else None
            path = Path(folder) / str(i)
            path.write_bytes(font._checked(archive, name))
            members[name] = path
        for record in targets:
            old_id, new_id = record["candidate_id"], str(uuid.uuid4())
            trajectory = decode(font._checked(archive, record["file"]))
            before = {"record": record, "trajectory": copy.deepcopy(trajectory),
                      "metrics": metrics[old_id], "summary": provenance[old_id],
                      "identity": font.identity}
            members[f"correction_sources/{new_id}.json"] = encoded(before)
            m = copy.deepcopy(metrics.pop(old_id))
            for stroke in trajectory["strokes"]:
                for point in stroke["points"]:
                    point["x"], point["y"] = correction.point(point["x"], point["y"], baseline=m["baseline"])
            summary = copy.deepcopy(provenance.pop(old_id))
            if "optical_layout_frame" not in summary:
                points = [p for s in before["trajectory"]["strokes"] for p in s["points"]]
                summary["optical_layout_frame"] = {
                    "bounds": [min(p["x"] for p in points), min(p["y"] for p in points),
                               max(p["x"] for p in points), max(p["y"] for p in points)],
                    "metrics": copy.deepcopy(m)}
            summary.setdefault("geometric_corrections", []).append({
                "source_candidate_id": old_id, "source_trajectory_hash": record["trajectory_hash"],
                "transform": asdict(correction), "source_record": f"correction_sources/{new_id}.json"})
            replacement = {**record, "candidate_id": new_id, "file": f"glyphs/{new_id}.json",
                           **trajectory_hashes(trajectory), "metrics_id": semantic_hash(m),
                           "source_summary_hash": semantic_hash(summary)}
            validate_candidate(replacement, trajectory, m, summary)
            index["candidates"][font.records.index(record)] = replacement
            metrics[new_id], provenance[new_id] = m, summary
            members[replacement["file"]] = encoded(trajectory)
            result_stats.append({"source_candidate_id": old_id, "candidate_id": new_id})
        members.update({"index.json": encoded(index), "metrics.json": encoded(metrics),
                        "provenance.json": encoded(provenance)})
        if font.fingerprint != (font.path.stat().st_size, font.path.stat().st_mtime_ns):
            raise ValueError("来源字体在校正期间变化，未发布新字体")
        progress("正在写入并校验新的校正字体包…")
        staged = Path(folder) / "corrected.inkfont"
        manifest = write_archive(staged, members, manifest)
        verified = FontPackage(staged, verify_all=False)
        statistics = verify_font(verified, progress=progress)
        # Publish only a fully verified snapshot; never overwrite a concurrent
        # publication or expose a failed verification as a usable font package.
        os.link(staged, output)
    return {"path": str(output), "manifest": manifest, "verification": statistics,
            "corrected_candidates": result_stats,
            "message": f"已另存校正字体：{output}；原包和当前文档保持原样"}
