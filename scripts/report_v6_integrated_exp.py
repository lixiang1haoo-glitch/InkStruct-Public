"""Same-scale whole glyph, corner, hook and natural-curve regression report."""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from run_v6_exp import sha, write
from run_v6_integrated_exp import WRITERS, curves

from inkstruct.alignment import align_sample
from inkstruct.geometry import path_length
from inkstruct.samples import iter_index
from inkstruct.source_trajectory import source_trajectory
from inkstruct.structures import StructureRepository
from inkstruct.trajectory_experiment import SharedTransform, projected_tail_length

MAIN = "而相儒荡"
KEY = {"而": 3, "相": 5, "儒": 13, "荡": 6}
LABELS = {
    "A": "A 旧默认",
    "P": "P 旧 v6 字框",
    "U": "U 旧参考/统一框",
    "B": "B 修参考/固定来源",
    "F": "F 新 v6 完整轨迹",
    "M": "M 同来源压缩平滑",
}


def load(path):
    return json.loads(path.read_text())


def draw_grid(rows, labels, path, *, zoom=False):
    cell, left, top = 260, 130, 52
    image = Image.new("RGB", (left + cell * len(labels), top + len(rows) * 290), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype("/System/Library/Fonts/STHeiti Medium.ttc", 17)
    for j, label in enumerate(labels):
        draw.text((left + j * cell + 8, 10), label, font=font, fill="#172b4d")
    for i, row in enumerate(rows):
        y = top + i * 290
        draw.text((6, y + 40), row["title"], font=font, fill="#172b4d")
        x0, y0, x1, y1 = row.get("bounds", (0, 0, 1, 1))
        scale = 220 / max(x1 - x0, y1 - y0)
        for j, strokes in enumerate(row["curves"]):
            panel = Image.new("RGB", (cell, cell), "#f7f8fa")
            d = ImageDraw.Draw(panel)
            if strokes is None:
                d.text((30, 105), "无可用目标原稿", font=font, fill="#68758a")
            else:
                for k, stroke in enumerate(strokes):
                    xy = [(20 + (p[0] - x0) * scale, 20 + (p[1] - y0) * scale) for p in stroke]
                    selected = not zoom or k in row.get("indices", [])
                    color = "#1b5f98" if selected else "#d2d9df"
                    d.line(xy, fill=color, width=max(1, round(0.028 * scale)), joint="curve")
                    if zoom and selected:
                        d.line(xy, fill="#101e2c", width=1)
                        for px, py in xy:
                            d.ellipse((px - 1, py - 1, px + 1, py + 1), fill="#1b1b1b")
                        for (px, py), c in [(xy[0], "#df8138"), (xy[-1], "#148447")]:
                            d.ellipse((px - 3, py - 3, px + 3, py + 3), fill=c)
            image.paste(panel, (left + j * cell, y))
    image.save(path)


def svg_panel(strokes):
    if strokes is None:
        return '<div class="missing">无可用目标原稿</div>'
    paths = "".join(
        '<polyline points="' + " ".join(f"{x * 1000:.4f},{y * 1000:.4f}" for x, y in s) + '"/>'
        for s in strokes
    )
    return '<svg viewBox="0 0 1000 1000">' + paths + "</svg>"


def run(root):
    out = root / "report"
    out.mkdir(exist_ok=False)
    summary = load(root / "summary.json")
    prior = Path("artifacts/architecture_review_20261011/run_v1")
    old_protocol = load(prior / "protocol.json")
    repo = StructureRepository(Path("artifacts/full_library_20261010/inputs/characters.sqlite3"))
    # Supplementary target originals are used ONLY now, after outputs froze.
    originals, original_log, source_hashes = {}, [], {}
    for writer in WRITERS:
        p = (
            Path(f"artifacts/samples/{writer}/index.jsonl")
            if writer != "user_001"
            else Path("artifacts/component_aspect_20261007/user001_snapshot/index.jsonl")
        )
        source_hashes[str(p)] = sha(p)
        assert sha(p) == old_protocol["inputs"][str(p)]
        chars = {r["character"] for r in load(root / writer / "records.json")}
        for sample in iter_index(p):
            if sample.character not in chars:
                continue
            g = repo.get(sample.character)
            raw, reason = source_trajectory(sample, align_sample(sample, g), g)
            original_log.append(
                {
                    "writer": writer,
                    "character": sample.character,
                    "sample_id": sample.sample_id,
                    "source_sha256": sample.source_sha256,
                    "rejection": reason,
                }
            )
            if raw is not None:
                originals.setdefault((writer, sample.character), [s.points for s in raw.strokes])
    write(
        out / "original_evaluation_log.json",
        {
            "index_hashes": source_hashes,
            "samples": original_log,
            "role": "evaluation only; first valid repeat displayed",
        },
    )
    details, gallery, round_records = [], [], []
    for writer in WRITERS:
        records = load(root / writer / "records.json")
        bychar = {r["character"]: r for r in records}
        data = {c: load(root / writer / "glyphs" / f"{ord(c):04X}.json") for c in bychar}
        rows, locals_, hooks = [], [], []
        for c in MAIN:
            g = data[c]
            paths = [originals.get((writer, c))] + [curves(g[k]) for k in ("A", "P", "M", "F")]
            rows.append({"title": f"{writer}\n{c}", "curves": paths})
            k = KEY[c]
            xy = np.array(curves(g["F"])[k])
            # All panels use the identical crop, including originals and A.
            selected = [p[k] for p in paths if p is not None]
            points = np.vstack(selected)
            low, high = points.min(axis=0) - 0.04, points.max(axis=0) + 0.04
            locals_.append(
                {
                    "title": f"{c} 第{k + 1}笔",
                    "curves": paths,
                    "indices": [k],
                    "bounds": (*low, *high),
                }
            )
            centre = xy[-2] if c in "而荡" else xy[np.argmin(xy[:, 1]) + 1]
            hooks.append(
                {
                    "title": f"{c}\n折角/末端",
                    "curves": paths,
                    "indices": [k],
                    "bounds": (
                        centre[0] - 0.14,
                        centre[1] - 0.14,
                        centre[0] + 0.14,
                        centre[1] + 0.14,
                    ),
                }
            )
            metric = bychar[c]["representation_M_vs_F"][k]
            details.append(
                {
                    "writer": writer,
                    "character": c,
                    "stroke": k + 1,
                    "source": g["F"]["strokes"][k]["style_source"],
                    "A_points": len(g["A"]["strokes"][k]["points"]),
                    "F_points": len(xy),
                    "M_vs_F": metric,
                    "tail_F": path_length(xy[-2:]),
                    "tail_M_projected": projected_tail_length(curves(g["M"])[k], xy[-2]),
                }
            )
        labels = ["原稿（仅评估）"] + [LABELS[k] for k in ("A", "P", "M", "F")]
        draw_grid(rows, labels, out / f"{writer}_whole.png")
        draw_grid(locals_, labels, out / f"{writer}_stroke.png", zoom=True)
        draw_grid(hooks, labels, out / f"{writer}_corner_hook.png", zoom=True)
        # Predefined regression protection: benefits, unchanged cases and curves.
        protected = [c for c in "传砖桂生叵黧瀝" if c in data]
        draw_grid(
            [
                {
                    "title": writer + "\n" + c,
                    "curves": [curves(data[c][k]) for k in ("A", "U", "B", "F")],
                }
                for c in protected
            ],
            [LABELS[k] for k in ("A", "U", "B", "F")],
            out / f"{writer}_protection.png",
        )
        examples = load(root / writer / "round_examples.json")
        round_rows = []
        # A repeat-free source-based ranking; not a claimed naturalness classifier.
        seen = set()
        for r in examples:
            key = (r["sample_id"], r["source_stroke_id"])
            if key in seen:
                continue
            seen.add(key)
            c = r["character"]
            index = next(
                i
                for i, s in enumerate(data[c]["F"]["strokes"])
                if s["standard_stroke_id"] == r["stroke_id"]
            )
            g = data[c]
            expected = curves(g["F"])
            expected[index] = SharedTransform(**r["transform"]).apply(r["source_points"])
            xy = np.asarray(expected[index])
            low, high = xy.min(axis=0) - 0.06, xy.max(axis=0) + 0.06
            round_rows.append(
                {
                    "title": f"{writer} {c}\n第{index + 1}笔\n来自{r['source_character']}",
                    "curves": [expected, curves(g["A"]), curves(g["M"]), curves(g["F"])],
                    "indices": [index],
                    "bounds": (*low, *high),
                }
            )
            round_records.append({"writer": writer, **r, "target_order": index + 1})
            if len(round_rows) == 4:
                break
        if round_rows:
            draw_grid(
                round_rows,
                ["原轨迹同一变换", "A 旧默认", "M 同来源平滑", "F 完整轨迹"],
                out / f"{writer}_curved.png",
                zoom=True,
            )
        for c, g in data.items():
            gallery.append(
                f'<h3>{html.escape(writer)} · {c}</h3><div class="row">'
                + "".join(
                    '<div class="cell"><b>' + label + "</b>" + svg_panel(paths) + "</div>"
                    for label, paths in [("原稿（仅评估）", originals.get((writer, c)))]
                    + [(LABELS[k], curves(g[k])) for k in ("A", "P", "U", "B", "M", "F")]
                )
                + "</div>"
            )
    write(out / "key_stroke_metrics.json", details)
    write(out / "curved_examples.json", round_records)
    outcome_rows = []
    for writer, character, label in [
        ("wsq", "擂", "几何收益"),
        ("user_001", "田", "几何收益"),
        ("mjb", "似", "几何退步"),
        ("user_001", "饿", "几何退步"),
    ]:
        g = load(root / writer / "glyphs" / f"{ord(character):04X}.json")
        outcome_rows.append(
            {
                "title": f"{writer}\n{character} · {label}",
                "curves": [originals.get((writer, character))]
                + [curves(g[k]) for k in ("A", "P", "M", "F")],
            }
        )
    draw_grid(
        outcome_rows,
        ["原稿（仅评估）"] + [LABELS[k] for k in ("A", "P", "M", "F")],
        out / "outcomes.png",
    )
    local_table = "".join(
        f"<tr><td>{r['character']} 第{r['stroke']}笔</td><td>{r['F_points']}</td>"
        f"<td>{r['M_vs_F']['max_distance']:.4f}</td>"
        f"<td>{r['M_vs_F']['length_ratio']:.3f}</td>"
        f"<td>{r['M_vs_F']['terminal_angle_deg']:.1f}°</td></tr>"
        for r in details
        if r["writer"] == "user_001"
    )
    macros = {
        k: float(np.mean([v["macro"][k]["mean_distance"] for v in summary.values()]))
        for k in ("A", "P", "U", "B", "F", "M")
    }
    rows = "".join(
        f"<tr><td>{w}</td><td>{s['evaluated_characters']}</td>"
        + "".join(
            f"<td>{s['macro'][k]['mean_distance']:.5f}</td>" for k in ("A", "P", "U", "B", "F", "M")
        )
        + "</tr>"
        for w, s in summary.items()
    )
    images = "".join(
        f"<h2>{w}：整字、关键笔、折角/短钩、保护字和弯曲来源</h2>"
        + "".join(
            f'<h3>{title}</h3><a href="{w}_{name}.png"><img src="{w}_{name}.png"></a>'
            for name, title in [
                ("whole", "同尺度整字"),
                ("stroke", "关键整笔：黑色细线为中心线，黑点为原有顶点"),
                ("corner_hook", "同尺度局部放大：橙色起点、绿色末端"),
                ("protection", "保护字及明确参考缺陷"),
                ("curved", "作者弯曲来源：不把自然圆弯强行变成直角"),
            ]
        )
        for w in WRITERS
    )
    report = (
        """<!doctype html><html lang="zh"><meta charset="utf-8"><title>v6 exp 圆润化与参考贯通验收</title>
<style>body{font-family:system-ui;max-width:1600px;margin:35px auto;padding:0 20px;color:#223}p{line-height:1.7}img{max-width:100%}table{border-collapse:collapse}td,th{padding:9px;border:1px solid #ccd}.row{display:flex;gap:8px}.cell{flex:1;min-width:0;text-align:center}.cell svg,.missing{width:100%;background:#f7f8fa;aspect-ratio:1}.cell b{font-size:12px}polyline{stroke:#195c93;stroke-width:28;fill:none;stroke-linejoin:round;stroke-linecap:round}.centre polyline{stroke-width:3}.missing{display:grid;place-items:center;font-size:12px}button{padding:12px;position:sticky;top:0}</style>
<h1>v6 exp：优先消除人为圆润化</h1><p>2026-10-13 · 实验默认关闭 · 92 个档案—字组合 · 6 路对照。复用旧分组回归，不冒充新盲测。三位已命名作者和 user_001 批次，不能称四位独立作者。</p>
<p><b>已贯通：</b>版本锁定的修正参考 → 整字共同等比字框 → 完整作者部件；无供体保留完整参考折线。所有输出点保留，压力及笔内时间保留，笔间时间重新安排。不新增原型平均、8 点压缩或样条。</p>
<p><b>对照含义：</b>A 是旧默认，P 是旧 v6 后置字框，U 是旧参考放入共同字框，B 只改参考且固定 U 供体和变换，F 允许重新检索，M 与 F 同来源同布局但压缩平滑（未加原型平均）。A→F 同时涉及表示、布局与来源；只有 M→F 用于隔离表示影响，U→B 用于隔离参考影响。B 的安全拒绝若发生需单独说明。</p>
<p><b>质量边界：</b>折角/短钩保留是相对于选定作者轨迹或参考的保真；字体参考不是作者真值。完整复用不保证供体适合目标；较长弧长不自动更好。严格中心线交叉检查不覆盖笔宽粘连、自交和闭合意图。无原稿的格子明确留空，不能声称更像作者。</p>
<h2>真实原稿评价：逐笔、逐重复、逐字平均</h2><p>复用此前 38 个可评价档案—字组合、40 份原稿；下方附录中的额外保护字原稿仅作展示。评价使用统一弧长积分，不改变输出顶点。</p>
<table><tr><th>档案</th><th>字数</th><th>A</th><th>P</th><th>U</th><th>B</th><th>F</th><th>M</th></tr>"""
        + rows
        + f"""</table><p>四档案等权均差 A={macros["A"]:.6f}，F={macros["F"]:.6f}；相对差 {(macros["F"] / macros["A"] - 1) * 100:+.2f}%。这是几何均差变化，不是整体质量提升率。mjb 仍退步；末端方向未达到全面改善。</p>"""
        + """<h2>关键结果与限制</h2>
<p>四组档案的“而、相、儒、荡”均无可用同字原稿。本次只能确认相对于所选真实部件或字体参考的折钩保留，不能宣称这四字更像作者。下表是 user_001 的 M 相对 F；F 保留参考顶点，误差为零是表示忠实度，不是对原稿的准确度。</p>
<table><tr><th>关键笔</th><th>F 原有顶点</th><th>M 最大几何偏差</th><th>M/F 弧长比</th><th>M 末向偏差</th></tr>"""
        + local_table
        + """</table>
<p>“荡”第7笔末段：F 长度 0.11343，M 投影尾长 0.08340，压缩平滑损失约 26.5%；整笔弧长减少约 29.1%。这些数值说明这条参考的折钩被抹平，不表示一般情况下弧长越长越好。</p>
<p>旧 v6 已保留了四个关键参考折钩，新 F 并非第一次解决这些表示损失；这轮新增价值是把修正参考和前置统一字框接通。黧第1笔、瀝第6笔在四组档案中均由近空线恢复为非退化参考，字框内长度分别为 0.28021、0.17941。恢复的并非作者原稿。</p>
<p>U→B 固定供体及变换，无安全拒绝；47 个参考未改变的组合，其所有输出点、压力、时间完全不变。F 与 U 的供体身份均相同，但参考变化会改变部分重新拟合的部件变换，因此 B/F 分列，不能把重新放置算作修参考本身的收益。</p>
<p>F 的 92 份输出、994 笔通过标准 ID、笔数/笔顺、有限性、压力与单调时间检查；293 笔作者来源的 13,375 点逐点核对，另有 4,164 个完整参考点。F 无长度小于 0.01 的近退化笔画；相对 U 与修正参考均无新增严格笔间交叉。仍不证明无笔宽粘连、自交、闭合或拥挤问题。</p>
<p>自然圆弯保护覆盖所有被采用的真实来源：共同正等比变换保留曲率形状和转向，压力和笔内时间逐项核对。下方 16 个按来源弦长/弧长排序的弯曲示例同时含圆弯与折钩，只作图例，不冒充自动“自然度”判断。可见 user_001 的“码”第7笔仍保留原来的连续圆弯。</p>
<h2>有原稿的收益与退步案例</h2><p>按已记录几何结果展示收益与退步，不据此估计泛化比例；全体评价在上表和附录。mjb“似”、user_001“饿”的退步仍然存在，不能据几何折角更清楚就默认替换 v4。</p><a href="outcomes.png"><img src="outcomes.png"></a>
<p>图像固定笔宽为显示字框的 0.028，不模拟压力笔刷；局部黑色细线单独显示中心线，防止把显示笔刷的圆角误当成轨迹平滑。</p>"""
        + images
        + """<h2>完整 92 字审阅附录</h2><p>切换细中心线可区分轨迹本身圆弯与显示圆笔刷。每格使用相同 0–1 显示坐标，不独立放大字形。</p><button onclick="document.body.classList.toggle('centre')">切换笔刷 / 细中心线</button>"""
        + "".join(gallery)
        + "</html>"
    )
    (out / "报告.html").write_text(report)
    write(
        out / "report_manifest.json",
        {
            "renderer_sha256": sha(Path(__file__)),
            "run_protocol_sha256": sha(root / "protocol.json"),
            "summary_sha256": sha(root / "summary.json"),
            "images": {p.name: sha(p) for p in sorted(out.glob("*.png"))},
        },
    )
    write(
        out / "report_summary.json",
        {
            "macro_distance": macros,
            "original_available": len(originals),
            "key_strokes": details,
            "curved_examples": len(round_records),
        },
    )
    print(out / "报告.html")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    run(parser.parse_args().run)
