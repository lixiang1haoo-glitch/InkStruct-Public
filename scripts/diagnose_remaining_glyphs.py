"""Trace the four remaining reviewed glyphs; isolated causal ablations only."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

import numpy as np
from report_review_repairs import curves, render_grid

from inkstruct.component_style import component_for_stroke, component_trajectory_key
from inkstruct.control_repair import ControlRepairGenerator
from inkstruct.generate import DeterministicGenerator
from inkstruct.geometry import cubic_bspline, resample, signature_key
from inkstruct.profile import load_profile
from inkstruct.structures import StructureRepository
from inkstruct.trajectory_experiment import curve_error, point_distances


def write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False))


def run(out):
    out.mkdir(parents=True, exist_ok=False)
    inputs = Path("artifacts/full_library_20261010/inputs")
    profile = load_profile(inputs / "user_001.json")
    repo = StructureRepository(inputs / "characters.sqlite3")
    version = repo.metadata()["source_version"]
    no_residual = copy.deepcopy(profile)
    for proto in no_residual.prototypes.values():
        proto.residual = [(0.0, 0.0)] * 8
    rows, results, zooms = [], [], []
    for c in "而相儒荡":
        graph = repo.get(c)
        engines = {
            "A": DeterministicGenerator(profile, version),
            "B": ControlRepairGenerator(profile, version),
            "no_legacy": DeterministicGenerator(no_residual, version),
            "no_geometry": DeterministicGenerator(profile, version),
            "no_relation": DeterministicGenerator(profile, version),
            "no_spline": DeterministicGenerator(profile, version),
        }
        engines["no_geometry"]._stroke_geometry_controls = lambda g, c, s, controls, box: (
            controls,
            None,
            False,
        )
        engines["no_relation"]._relation_prototype = lambda g, c: (None, 0.0)
        record = {
            "character": c,
            "decomposition": graph.decomposition,
            "components": [],
            "strokes": [],
            "outputs": {},
            "controls": {},
        }
        for label, engine in engines.items():
            control_log = []

            def spy(control, samples, *, clip=True, control_log=control_log, label=label):
                control_log.append([tuple(p) for p in control])
                return (
                    resample(control, samples)
                    if label == "no_spline"
                    else cubic_bspline(control, samples, clip=clip)
                )

            with patch("inkstruct.generate.cubic_bspline", spy):
                glyph = engine.generate(graph)
            record["outputs"][label] = asdict(glyph)
            record["controls"][label] = control_log[: len(graph.strokes)]
        frozen = (
            Path("artifacts/review_repairs_20261010/validation_v1/comparisons")
            / f"{ord(c):04X}.json"
        )
        old = json.loads(frozen.read_text())
        assert record["outputs"]["A"] == old["A"]
        assert record["outputs"]["B"] == old["B"]
        engine = engines["A"]
        whole = engine._whole_component_controls(graph)
        for comp in graph.components:
            tp, damping, _exact, _direct = engine._component_trajectory_prototype(graph, comp)
            lp, ld, _le = engine._layout_prototype(graph, comp)
            rp, rd = engine._relation_prototype(graph, comp)
            stored = profile.component_trajectories.get(component_trajectory_key(graph, comp))
            record["components"].append(
                {
                    **asdict(comp),
                    "selected_trajectory": asdict(tp) if tp else None,
                    "trajectory_weight": damping,
                    "exact_stored_sources": stored.source_character_count if stored else None,
                    "available_trajectory_candidates": [
                        {
                            "key": t.key,
                            "source_characters": t.source_character_count,
                            "stroke_count": t.stroke_count,
                        }
                        for t in engine.component_trajectories_by_canonical.get(comp.canonical, [])
                    ],
                    "layout_key": lp.key if lp else None,
                    "layout_weight": ld,
                    "relation_key": rp.key if rp else None,
                    "relation_weight": rd,
                    "whole_component_eligible": comp.path != "root"
                    and not comp.children_ids
                    and len(comp.stroke_ids) >= 2,
                }
            )
        for st, output in zip(graph.strokes, record["outputs"]["A"]["strokes"], strict=True):
            co = component_for_stroke(graph, st)
            sig = signature_key(st.signature)
            lp, _exact = engine._prototype(sig, st.component_path)
            gp, weight, _ = (
                engine._component_geometry_prototype(graph, co, st.stroke_id, sig)
                if co
                else (None, 0.0, False)
            )
            record["strokes"].append(
                {
                    "order": st.order,
                    "id": st.stroke_id,
                    "signature": sig,
                    "component_path": st.component_path,
                    "style_source": output["style_source"],
                    "whole_component_used": st.stroke_id in whole,
                    "legacy_key": lp.key if lp else None,
                    "legacy_samples": lp.sample_count if lp else None,
                    "legacy_residual_endpoints": [lp.residual[0], lp.residual[-1]] if lp else None,
                    "geometry_key_selected": gp.key if gp else None,
                    "geometry_weight": weight,
                    "geometry_used": st.stroke_id not in whole and gp is not None,
                    "standard_median": st.median,
                }
            )
        # Distance from relevant stroke endpoints to frame centerline, in glyph units.
        if c == "相":
            contacts = [("bottom_right", 8, -1, 5), ("top_left", 4, 0, 5)]
        elif c == "而":
            contacts = [("inner_left_top", 4, 0, 3), ("inner_right_top", 5, 0, 3)]
        elif c == "儒":
            contacts = [("lower_inner_left_top", 14, 0, 13), ("lower_inner_right_top", 15, 0, 13)]
        else:
            contacts = []
        record["contact_distances"] = {}
        all_curves = {
            "reference": [s.median for s in graph.strokes],
            **{k: curves(v) for k, v in record["outputs"].items()},
            "pre_spline": record["controls"]["A"],
        }
        for label, cs in all_curves.items():
            record["contact_distances"][label] = {
                name: float(point_distances([cs[stroke][endpoint]], cs[target])[0])
                for name, stroke, endpoint, target in contacts
            }
        rows.append({"title": c, "curves": [curves(record["outputs"][k]) for k in engines]})
        indices = {"而": [3, 4, 5], "相": [4, 5, 8], "儒": [12, 13, 14, 15], "荡": [6, 7, 8]}[c]
        pair = [curves(record["outputs"][k]) for k in ["A", "B", "no_legacy", "no_spline"]]
        xy = np.array([p for cs in pair for k in indices for p in cs[k]])
        lo, hi = xy.min(axis=0) - 0.05, xy.max(axis=0) + 0.05
        size = max(hi - lo)
        mid = (hi + lo) / 2
        zooms.append(
            {
                "title": c,
                "curves": pair,
                "indices": indices,
                "bounds": (*list(mid - size / 2), *list(mid + size / 2)),
            }
        )
        results.append(record)
    render_grid(
        rows,
        ["原输出", "上轮修复", "去通用残差", "去单笔几何", "去部件关系", "去样条"],
        out / "ablation.png",
    )
    render_grid(
        zooms, ["原输出", "上轮修复", "去通用残差", "去样条"], out / "local.png", local=True
    )
    d = results[-1]
    g = repo.get("荡")
    median = g.strokes[6].median
    control = resample(median, 8)
    smooth = cubic_bspline(control, 128, clip=False)
    d["s7_representation"] = {
        "median_count": len(median),
        "controls_count": 8,
        "median_to_8_mean_max": curve_error(control, median),
        "median_to_smooth_mean_max": curve_error(smooth, median),
    }
    render_grid(
        [{"title": "荡第7笔", "curves": [[median], [control], [smooth]]}],
        ["参考原折线", "8点折线", "8点+样条"],
        out / "dang_s7.png",
    )
    write(out / "trace.json", results)
    write(
        out / "manifest.json",
        {
            "inputs_sha256": {
                str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in [inputs / "user_001.json", inputs / "characters.sqlite3", Path(__file__)]
            },
            "scope": "four previously observed regression characters; diagnostic ablations, not repair products",
            "A_and_B_exactly_reproduced": True,
        },
    )
    for r in results:
        print(r["character"], r["contact_distances"])
    print("dang s7", d["s7_representation"])


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    run(p.parse_args().output)
