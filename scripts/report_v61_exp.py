"""Render the bounded v6.1 iteration, including non-improvements and regressions."""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from report_v6_integrated_exp import svg_panel
from run_v6_exp import sha, write
from run_v61_exp import ARMS, WRITERS, dict_curves

LABELS = ["A 旧 v4", "B 冻结 v6", "C 只改候选", "D 只改布局", "E v6.1 exp"]


def load(path):
    return json.loads(path.read_text())


def closest_pair(left, right):
    result = None
    for a, b in ((np.asarray(left), np.asarray(right)), (np.asarray(right), np.asarray(left))):
        start = b[:-1]
        v = np.diff(b, axis=0)
        denom = np.maximum(np.sum(v * v, axis=1), 1e-24)
        t = np.clip(np.sum((a[:, None] - start) * v, axis=2) / denom, 0, 1)
        projected = start + t[:, :, None] * v
        lengths = np.linalg.norm(a[:, None] - projected, axis=2)
        i, j = np.unravel_index(lengths.argmin(), lengths.shape)
        if result is None or lengths[i, j] < result[0]:
            result = (float(lengths[i, j]), a[i], projected[i, j])
    return result


def render(rows, labels, path):
    size, left, top = 260, 140, 48
    im = Image.new("RGB", (left + size * len(labels), top + len(rows) * 285), "white")
    draw = ImageDraw.Draw(im)
    font = ImageFont.truetype("/System/Library/Fonts/STHeiti Medium.ttc", 16)
    for j, label in enumerate(labels):
        draw.text((left + j * size + 8, 10), label, font=font, fill="#22354b")
    for i, row in enumerate(rows):
        y = top + i * 285
        draw.text((5, y + 25), row["title"], font=font, fill="#22354b")
        x0, y0, x1, y1 = row.get("bounds", (0, 0, 1, 1))
        scale = 220 / max(x1 - x0, y1 - y0)
        for j, curves in enumerate(row["curves"]):
            panel = Image.new("RGB", (size * 2, size * 2), "#f7f8fa")
            d = ImageDraw.Draw(panel)
            if curves is not None:
                for k, c in enumerate(curves):
                    xy = [(2 * (20 + (x - x0) * scale), 2 * (20 + (y - y0) * scale)) for x, y in c]
                    chosen = "indices" not in row or k in row["indices"]
                    color = "#185c94" if chosen else "#d3dbe3"
                    width = max(1, round(row.get("brush_width", 0.028) * scale * 2))
                    d.line(xy, fill=color, width=width, joint="curve")
                    # Round caps match the constant circular-brush distance model.
                    for px, py in xy:
                        radius = width / 2
                        d.ellipse((px - radius, py - radius, px + radius, py + radius), fill=color)
                    if "indices" in row and chosen:
                        d.line(xy, fill="#19242b", width=2)
                        for px, py in xy:
                            d.ellipse((px - 1, py - 1, px + 1, py + 1), fill="#19242b")
                if "pair" in row:
                    _, a, b = closest_pair(curves[row["pair"][0]], curves[row["pair"][1]])
                    d.line(
                        [
                            (2 * (20 + (p[0] - x0) * scale), 2 * (20 + (p[1] - y0) * scale))
                            for p in (a, b)
                        ],
                        fill="#d35532",
                        width=3,
                    )
            panel = panel.resize((size, size), Image.Resampling.LANCZOS)
            im.paste(panel, (left + j * size, y))
    im.save(path)


def run(root, report_dir="report"):
    out = root / report_dir
    out.mkdir(exist_ok=False)
    summaries = load(root / "summary.json")
    dataset = {}
    records = {}
    originals = {}
    gallery = []
    for writer in WRITERS:
        records[writer] = {r["character"]: r for r in load(root / writer / "records.json")}
        dataset[writer] = {
            c: load(root / writer / "glyphs" / f"{ord(c):04X}.json") for c in records[writer]
        }
        originals.update(
            {
                (writer, r["character"]): r["original"]
                for r in load(root / writer / "evaluation.json")
            }
        )

        def row(c, title=None, indices=None, writer=writer):
            value = {
                "title": title or f"{writer}\n{c}",
                "curves": [dict_curves(dataset[writer][c][k]) for k in ARMS],
            }
            if indices is not None:
                value["indices"] = indices
            return value

        render([row(c) for c in "而相儒荡"], LABELS, out / f"{writer}_main.png")
        zoom = []
        for c, pair in [("相", (5, 8)), ("儒", (5, 10))]:
            r = row(c, indices=list(pair))
            xy = r["curves"][1]
            _, a, b = closest_pair(xy[pair[0]], xy[pair[1]])
            centre = (a + b) / 2
            r.update(
                pair=pair,
                bounds=(centre[0] - 0.16, centre[1] - 0.16, centre[0] + 0.16, centre[1] + 0.16),
            )
            zoom.append(r)
        for c, k in [("而", 3), ("荡", 6)]:
            r = row(c, indices=[k])
            p = r["curves"][1][k][-2]
            r["bounds"] = (p[0] - 0.15, p[1] - 0.15, p[0] + 0.15, p[1] + 0.15)
            zoom.append(r)
        render(zoom, LABELS, out / f"{writer}_local.png")
        chars = [c for c in ("传", "砖", "桂", "生", "叵", "黧", "瀝") if c in dataset[writer]]
        render([row(c) for c in chars], LABELS, out / f"{writer}_protect.png")
        for c, g in dataset[writer].items():
            gallery.append(
                f'<h3>{writer} · {c}</h3><div class="row">'
                + "".join(
                    f'<div class="cell"><b>{html.escape(label)}</b>{svg_panel(xy)}</div>'
                    for label, xy in [("原稿，仅评估", originals.get((writer, c)))]
                    + list(zip(LABELS, [dict_curves(g[k]) for k in ARMS], strict=True))
                )
                + "</div>"
            )
    example_rows = []
    for writer, c, meaning in [
        ("wsq", "宵", "C收益 / D退步"),
        ("scx", "擂", "减少接触\n无可用原稿"),
        ("user_001", "儒", "C与D分开改善\n无目标原稿"),
        ("mjb", "似", "仍失败"),
        ("user_001", "饿", "仍失败"),
        ("user_001", "叵", "个性化仍不足"),
    ]:
        g = dataset[writer][c]
        example_rows.append(
            {
                "title": f"{writer}\n{c}\n{meaning}",
                "curves": [originals.get((writer, c))] + [dict_curves(g[k]) for k in ARMS],
            }
        )
    render(example_rows, ["原稿，仅评估"] + LABELS, out / "outcomes.png")
    sensitivity = []
    for width in (0.014, 0.028, 0.05):
        for writer, items in records.items():
            for c, r in items.items():
                pairs = {
                    k: {tuple(p["orders"]) for p in v["pairs"] if p["centerline_gap"] <= width}
                    for k, v in r["contacts"].items()
                }
                for k in ("C", "D", "E"):
                    new = pairs[k] - pairs["B"]
                    if new:
                        sensitivity.append(
                            {
                                "writer": writer,
                                "character": c,
                                "width": width,
                                "arm": k,
                                "new_pairs": sorted(new),
                            }
                        )
    write(out / "brush_sensitivity.json", sensitivity)
    g = dataset["wsq"]["宵"]
    render(
        [
            {
                "title": f"wsq 宵\n笔宽 {width}",
                "brush_width": width,
                "curves": [originals[("wsq", "宵")]] + [dict_curves(g[k]) for k in ARMS],
            }
            for width in (0.028, 0.05)
        ],
        ["原稿，仅评估"] + LABELS,
        out / "brush_sensitivity.png",
    )
    curved = []
    for writer, c, k in [
        ("user_001", "码", 6),
        ("user_001", "认", 1),
        ("scx", "儒", 13),
        ("user_001", "瀝", 1),
    ]:
        g = dataset[writer][c]
        xy = np.asarray(dict_curves(g["B"])[k])
        lo = xy.min(axis=0) - 0.04
        hi = xy.max(axis=0) + 0.04
        curved.append(
            {
                "title": f"{writer}\n{c} 第{k + 1}笔",
                "indices": [k],
                "curves": [dict_curves(g[a]) for a in ARMS],
                "bounds": (*lo, *hi),
            }
        )
    render(curved, LABELS, out / "curved.png")
    macro = {
        k: {
            field: float(np.mean([v["macro"][k][field] for v in summaries.values()]))
            for field in ("mean_distance", "terminal_angle_deg", "absolute_length_error")
        }
        for k in ARMS
    }
    counts = {
        k: {
            "changed": sum(v["changed_glyphs"].get(k, 0) for v in summaries.values()),
            "extra_contacts": sum(
                v["extra_brush_contacts_vs_reference"][k] for v in summaries.values()
            ),
        }
        for k in ARMS
    }
    table = "".join(
        f"<tr><td>{label}</td><td>{macro[k]['mean_distance']:.8f}</td><td>{macro[k]['terminal_angle_deg']:.4f}°</td><td>{counts[k]['extra_contacts']}</td><td>{counts[k]['changed'] if k in 'CDE' else '—'}</td></tr>"
        for k, label in zip(ARMS, LABELS, strict=True)
    )
    gap_rows = []
    for writer, c, pair in [
        ("wsq", "儒", [6, 11]),
        ("user_001", "儒", [6, 11]),
        ("scx", "擂", [1, 5]),
        ("wsq", "宵", [3, 6]),
        ("scx", "相", [6, 9]),
    ]:
        r = records[writer][c]
        values = {
            k: next(x["centerline_gap"] for x in r["contacts"][k]["pairs"] if x["orders"] == pair)
            for k in ARMS
        }
        gap_rows.append({"writer": writer, "character": c, "orders": pair, "gaps": values})
    gap_table = "".join(
        f"<tr><td>{r['writer']} {r['character']} {r['orders']}</td>"
        + "".join(f"<td>{r['gaps'][k]:.5f}</td>" for k in ARMS)
        + "</tr>"
        for r in gap_rows
    )
    sections = "".join(
        f"<h2>{w}：重点字、间隙与保护字</h2>"
        + "".join(
            f'<h3>{label}</h3><a href="{w}_{name}.png"><img src="{w}_{name}.png"></a>'
            for name, label in [
                ("main", "而、相、儒、荡：同尺度整字"),
                ("local", "连接间隙、折角与短钩：同尺度局部"),
                ("protect", "保护字：包含收益与未解决项"),
            ]
        )
        for w in WRITERS
    )
    page = (
        """<!doctype html><html lang="zh"><meta charset="utf-8"><title>v6.1 exp 首轮验收</title><style>body{font-family:system-ui;max-width:1750px;margin:30px auto;padding:0 20px;color:#223}p{line-height:1.8}img{max-width:100%}td,th{padding:9px;border:1px solid #ccd}table{border-collapse:collapse}.row{display:flex;gap:7px}.cell{flex:1;min-width:0;text-align:center}.cell svg,.missing{width:100%;background:#f7f8fa;aspect-ratio:1}.cell b{font-size:12px}polyline{stroke:#185c94;stroke-width:28;fill:none;stroke-linejoin:round;stroke-linecap:round}.centre polyline{stroke-width:3}.missing{display:grid;place-items:center;font-size:12px}button{padding:12px}</style>
<h1>v6.1 exp：固定实例提案，分离候选与统一布局</h1><p>2026-10-13 · 基线 901b2f3 · 92 个档案—字组合，460份A/B/C/D/E输出 · 实验默认关闭。三位已命名作者和 user_001 批次，不称四位独立作者；全是已观察的开发/回归数据，无新盲测。</p>
<p><b>本轮新增：</b>固定候选提案接口、作者末向特征重排、真实笔段/端点/显示笔宽诊断、集中决定完整部件的有界平移，以及独立的协议/几何/风格回退记录。完整点通道与绕过8点、平均、样条是v6已有能力，不重复计功。</p>
<p><b>控制：</b>A冻结旧v4；B是逐项复现的v6；C固定B候选池与每候选原变换，只重排；D固定B供体，只改布局；E固定C供体，再运行同一个布局方法。原稿不参加排序、参数和建档，原有同字整组排除规则不变。没有非等比缩放、逐笔变形或新参考修复。</p>
<p>布局最大平移0.028、步长0.014；只移动完整作者部件，不修改部件内部连接。以参考中分离的跨部件笔段作软提示，不强制闭合。保持B已有且参考也支持的接触，拒绝新增笔宽接触和严格交叉。阈值是本次固定显示笔宽模型，不能解释为作者真值。</p>
<h2>汇总：结构收益有限，风格收益尚不充分</h2><table><tr><th>路径</th><th>原稿几何均差</th><th>末向均差</th><th>相对参考新增笔宽接触对</th><th>相对B改变字数</th></tr>"""
        + table
        + """</table>
<p>38个可评组合、40份原稿，逐笔/重复/字/档案分组等权。C/E几何均差仅比B低约0.053%，D反而高约0.024%；变化来自wsq“宵”这一有原稿案例，不能宣称总体风格改善。E相对参考的新增笔宽接触提示由43对降至38对，仍有38对需要解释；这也不是确认错误的数量。</p>
<p>C改变4个组合，D改变5个，E改变6个；86个组合E轨迹完全不变。293/994笔作者来源覆盖率约29.48%，701笔仍参考回退，覆盖率没有提高。所有新路径无协议失败、新增严格交叉或新退化；在用于门控的0.028笔宽下无新增接触对，但0.05笔宽出现新增粘连反例（见下节），不能称无新增损伤。</p>
<h2>连接间隙：实际笔段距离</h2><p>下表为中心线最小距离；固定圆笔刷宽0.028时，减去0.028即模型中的边缘间隙。负值代表显示覆盖，不是中心线严格相交。红线标出局部最近位置。</p><table><tr><th>作者 / 字 / 笔序对</th>"""
        + "".join(f"<th>{x}</th>" for x in LABELS)
        + "</tr>"
        + gap_table
        + """</table>
<h2>收益、无变化与退步并列</h2><p>wsq“宵”：C改供体后原稿均差0.015488→0.014426；D只平移降接触，却使均差增至0.015969。user_001“儒”：C将雨从“零”改为“雷”，间隙变得更大；D保留“零”只上移0.014，变化更小。两者都无目标原稿，不能认定间隙越大越好。user_001“瀝”的候选末向重排改变了氵来源，但没有新增可确认的接触收益，应标待复核。</p><a href="outcomes.png"><img src="outcomes.png"></a>
<h2>仍失败及诊断</h2><p>“相”三组目部仅有“泪”一个合格候选；user_001无合格目部。完整部件共用变换不能修其内部标准化开口和横线距离，本轮不强行逐笔封口。“叵”user_001的匚没有实例，口有同作者实例但不符合当前上下文池，仍明显参考字体化。mjb“似”的以仍参考回退；user_001“饿”的饣候选仍不能通过安全门槛，我仍无合格当前上下文实例。这些没有解决。</p>
<p>“而、荡”的折钩及 user_001“码、认”的原有圆弯保持不变。下面圆弯图同时展示“瀝”来源改变的待复核例；保留一个供体的圆弯不等于供体适合目标。</p><a href="curved.png"><img src="curved.png"></a>
"""
        + """<h2>新增风险：换显示笔宽后，候选收益不再安全</h2>
<p>追加检查0.014、0.028、0.05三种笔宽。前两档C/D/E未新增接触对；0.05时wsq“宵”的C/E新增第1、3笔粘连：原稿中心线间距0.07219，B为0.05119，C/E仅0.03027。当前候选排序只验收0.028，不能泛化成任何实际笔刷都安全。D没有此新增接触，但其原稿几何均差仍退步。这是本轮保留的负面结果，没有在看到原稿后继续调参。</p>
<a href="brush_sensitivity.png"><img src="brush_sensitivity.png"></a>"""
        + sections
        + """<h2>全部92组合与评估原稿</h2><p>每格相同0–1字框。重点四字没有目标原稿，不用参考冒充原稿。开关仅改变显示，不重新运行优化或验收。</p><button onclick="document.body.classList.toggle('centre')">切换细中心线 / 固定圆笔刷</button>"""
        + "".join(gallery)
        + """<h2>接入判断</h2><p>暂只适合显式实验预览；可以继续验证真实笔段诊断和固定供体的小幅布局调整，不能默认启用全部候选重排。下一步优先审计同作者完整整字实例进入目标部件的上下文适配（目、我、口等已有原始实例却未被当前池接纳），而不是继续放大重排权重或训练风险模型。仍缺独立人工复评、新留出、真实笔刷/输出设备接触一致性与失效边界。</p></html>"""
    )
    (out / "报告.html").write_text(page)
    write(out / "summary.json", {"macro": macro, "counts": counts, "gap_examples": gap_rows})
    write(
        out / "manifest.json",
        {
            "renderer_sha256": sha(Path(__file__)),
            "protocol_sha256": sha(root / "protocol.json"),
            "images": {p.name: sha(p) for p in out.glob("*.png")},
        },
    )
    print(out / "报告.html")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--report-dir", default="report")
    args = parser.parse_args()
    run(args.run, args.report_dir)
