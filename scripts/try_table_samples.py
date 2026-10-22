"""Build a local, reproducible table trial from a collector ZIP (no machine control)."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
from collections import Counter
from dataclasses import asdict
from itertools import pairwise
from pathlib import Path
from xml.etree import ElementTree as ET

from inkstruct.table_editor.app import EXAMPLE
from inkstruct.table_editor.core import compile_html, drawing_svg
from inkstruct.table_editor.routing import optimize_paths, travel_distance
from inkstruct.table_editor.samples import load_sample_zip


def render_png(svg, path, height_mm):
    from PySide6.QtCore import QByteArray, QRectF
    from PySide6.QtGui import QColor, QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer

    renderer = QSvgRenderer(QByteArray(svg.encode()))
    renderer.setViewBox(QRectF(10, 10, 170, height_mm))
    image = QImage(1700, round(height_mm * 10), QImage.Format.Format_ARGB32)
    image.fill(QColor("white"))
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()
    image.save(str(path))


def visual_svg(svg, paths=None, height=58):
    root = ET.fromstring(svg)
    root.attrib.update(width="100%", height="auto", viewBox=f"10 10 170 {height}")
    if paths:
        start = (0, 0)
        overlay = ET.SubElement(
            root,
            "g",
            {
                "class": "travel",
                "fill": "none",
                "stroke": "#2563eb",
                "stroke-width": "0.15",
                "stroke-dasharray": "0.7 0.5",
            },
        )
        for p in paths:
            ET.SubElement(overlay, "path", {"d": f"M {start[0]} {start[1]} L {p[0][0]} {p[0][1]}"})
            start = p[-1]
    return ET.tostring(root, encoding="unicode").replace("ns0:", "").replace(":ns0", "")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("samples", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source_hash = hashlib.sha256(args.samples.read_bytes()).hexdigest()
    bank = load_sample_zip(args.samples)
    if args.samples.resolve() != (out / "samples.zip"):
        shutil.copyfile(args.samples, out / "samples.zip")
    bank = load_sample_zip(out / "samples.zip")
    source = EXAMPLE.replace(
        "</table>",
        """  <tr><td>3</td><td align="right">6789.01</td><td align="right">2345.67</td></tr>
  <tr><td>4</td><td align="right">111.11</td><td align="right">888.88</td></tr>
  <tr><td>5</td><td align="right">9876.54</td><td align="right">3210.09</td></tr>
</table>""",
    )
    (out / "table.html").write_text(source)
    selection = bank.select(args.seed)
    drawing, original = compile_html(source, glyphs=selection)
    baseline = (*drawing.borders, *drawing.numbers)
    forward = optimize_paths(baseline, allow_reverse=False)
    reverse = optimize_paths(baseline, allow_reverse=True)
    _, builtin = compile_html(source)
    results = [
        ("original", "原始顺序", original, baseline),
        ("optimized", "仅排序", drawing_svg(drawing, paths=forward.paths), forward.paths),
        ("reversed", "排序并允许反转", drawing_svg(drawing, paths=reverse.paths), reverse.paths),
    ]
    canonical = lambda paths: Counter(min(p, p[::-1]) for p in paths)
    assert canonical(baseline) == canonical(forward.paths) == canonical(reverse.paths)
    assert Counter(baseline) == Counter(forward.paths)
    assert reverse.after_mm <= forward.after_mm <= travel_distance(baseline)
    verification = {
        "source_sha256": source_hash,
        "seed": args.seed,
        "writer": bank.writer_id,
        "inventory": bank.counts,
        "normalization": {
            "top_em": bank.top_em,
            "bottom_em": bank.bottom_em,
            "method": "shared isotropic scale; shared baseline; horizontal bearings estimated",
        },
        "selection": selection.trace,
        "paths": len(baseline),
        "point_count": sum(map(len, baseline)),
        "routes": {},
        "geometry_unchanged": True,
        "svg_path_ml_only": True,
        "machine_tested": False,
    }
    for name, _, svg, paths in results:
        root = ET.fromstring(svg)
        assert len(root) == len(baseline)
        for child in root:
            assert child.tag == "{http://www.w3.org/2000/svg}path"
            assert set(re.findall("[A-Za-z]", child.attrib["d"])) == {"M", "L"}
        (out / f"table_{name}.svg").write_text(svg)
        route = None if name == "original" else (forward if name == "optimized" else reverse)
        verification["routes"][name] = {
            "pen_up_mm": travel_distance(paths),
            "reversed_count": sum(route.reversed_paths) if route else 0,
            "source_indices": list(route.source_indices) if route else list(range(len(paths))),
            "reversed": list(route.reversed_paths) if route else [False] * len(paths),
        }
    verification["ink_length_mm"] = sum(math.dist(a, b) for p in baseline for a, b in pairwise(p))
    (out / "table_builtin.svg").write_text(builtin)
    project = {
        "schema_version": "inkstruct_table_v1",
        "html": source,
        "settings": asdict(drawing.settings),
        "routing": {"optimize": True, "allow_reverse": False},
        "samples": {"path": "samples.zip", "sha256": bank.sha256, "seed": args.seed},
    }
    (out / "trial.inktable").write_text(json.dumps(project, ensure_ascii=False, indent=2))

    # Each row shows one digit's five original variants, with the same scale.
    class Grid:
        def __init__(self):
            self.counts = Counter()

        def __contains__(self, ch):
            return ch in bank.samples

        def __getitem__(self, ch):
            index = self.counts[ch]
            self.counts[ch] += 1
            return bank.samples[ch][index].glyph

    grid_source = (
        "<table>"
        + "".join("<tr>" + f"<td>{c}</td>" * len(bank.samples[c]) + "</tr>" for c in "0123456789")
        + "</table>"
    )
    _, specimen = compile_html(grid_source, glyphs=Grid())
    (out / "all_samples.svg").write_text(specimen)
    assert source_hash == hashlib.sha256(args.samples.read_bytes()).hexdigest()
    (out / "verification.json").write_text(json.dumps(verification, ensure_ascii=False, indent=2))
    cards = []
    before = travel_distance(baseline)
    for name, label, svg, paths in results:
        distance = travel_distance(paths)
        cards.append(
            f'<section><h2>{label}</h2><p>空行程 {distance:.1f} mm · 减少 {(before - distance) / before * 100:.1f}%</p>{visual_svg(svg, paths)}<a href="table_{name}.svg" download>下载写字机 SVG</a></section>'
        )
    page = """<!doctype html><html lang="zh-CN"><meta charset="UTF-8"><title>user_001 手写数字排版试用</title><style>
body{font-family:system-ui,sans-serif;background:#f2f4f7;color:#17212f;max-width:1250px;margin:32px auto;padding:0 24px;line-height:1.65}h1{margin-bottom:4px}h2{font-size:20px;margin:0}section{background:white;border:1px solid #d9dfe7;border-radius:12px;margin:18px 0;padding:20px}svg{display:block;max-width:100%}.travel{display:none}body.show-travel .travel{display:inline}p{color:#4b596a}a{color:#2563eb}label{position:sticky;top:0;background:#e4edff;display:block;padding:12px;border-radius:8px}code{background:#e8ecf1;padding:2px 5px}
</style><h1>user_001 · 手写数字表格</h1>"""
    page += f'<p>数字 0–9 每字 5 份；随机种子 {args.seed}。表宽 160 mm，行高 8 mm，数字区域高 3.8 mm，格内留白 0.3 mm。{bank.summary}。</p><p>三种顺序使用完全相同的样本和坐标。保留原始折线、笔画分段和重复点；未平滑、未重绘。原始笔压和时间保存在 ZIP，SVG 采用统一笔宽，不模拟压力。以下为软件预览，尚未实机试写。</p><label><input type="checkbox" onchange="document.body.classList.toggle(\'show-travel\',this.checked)"> 显示蓝色虚线空行程（仅诊断预览，下载的 SVG 不含这些线）</label>'
    page += "".join(cards)
    page += f"<section><h2>内置数字对照</h2>{visual_svg(builtin)}</section><section><h2>全部 50 份数字样本</h2><p>从上到下为 0–9；每行按样本 ID 排序展示 5 个写法。统一尺度和基线，保留字高差异。此表不包含另外 17 类数学符号。</p>{visual_svg(specimen, height=90)}</section>"
    page += "<p>距离按纸张左上角起点、不含回零计算。排序可能改变墨迹覆盖先后；反转可能改变落笔收笔。导出的机器文件仅含 path、绝对 M/L。打开 <code>trial.inktable</code> 可继续编辑，需与 <code>samples.zip</code> 放在同一文件夹。</p></html>"
    (out / "comparison.html").write_text(page)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    render_png(original, out / "preview.png", 58)
    render_png(specimen, out / "all_samples.png", 90)
    app.processEvents()
    print(
        json.dumps(
            {name: verification["routes"][name]["pen_up_mm"] for name in verification["routes"]},
            ensure_ascii=False,
        )
    )
    print(out / "comparison.html")


if __name__ == "__main__":
    main()
