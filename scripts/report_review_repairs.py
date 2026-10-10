"""Render auditable whole-glyph, local and failure examples for review repairs."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from inkstruct.alignment import align_sample
from inkstruct.control_repair import ControlRepairGenerator
from inkstruct.generate import DeterministicGenerator
from inkstruct.geometry import signature_key
from inkstruct.profile import load_profile
from inkstruct.samples import iter_index
from inkstruct.structures import StructureRepository


def write(path, value):
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
    )


def render_grid(rows, labels, path, *, local=False):
    """Common coordinates per row; pressure-independent brush matches review app."""
    cell, margin, left, top = 250, 32, 150, 52
    im = Image.new("RGB", (left + len(labels) * cell, top + len(rows) * (cell + 30)), "white")
    draw = ImageDraw.Draw(im)
    font = ImageFont.truetype("/System/Library/Fonts/STHeiti Medium.ttc", 19)
    for j, label in enumerate(labels):
        draw.text((left + j * cell + 20, 10), label, font=font, fill="#172b4d")
    for i, row in enumerate(rows):
        y = top + i * (cell + 30)
        draw.text((8, y + 70), row["title"], font=font, fill="#172b4d")
        bounds = row.get("bounds", (0, 0, 1, 1))
        x0, y0, x1, y1 = bounds
        scale = (cell - 2 * margin) / max(x1 - x0, y1 - y0)
        for j, curves in enumerate(row["curves"]):
            x = left + j * cell
            panel = Image.new("RGB", (cell, cell), "#f7f8fa")
            d = ImageDraw.Draw(panel)
            for k, curve in enumerate(curves):
                xy = [(margin + (p[0] - x0) * scale, margin + (p[1] - y0) * scale) for p in curve]
                selected = not local or k in row.get("indices", [])
                d.line(
                    xy,
                    fill="#145da0" if selected else "#cbd2dc",
                    width=max(1, round(0.05 * scale)),
                    joint="curve",
                )
                if local and selected:
                    for point, color in ((xy[0], "#dd7532"), (xy[-1], "#166534")):
                        d.ellipse(
                            (point[0] - 3, point[1] - 3, point[0] + 3, point[1] + 3), fill=color
                        )
            im.paste(panel, (x, y))
    im.save(path)


def curves(glyph):
    return [[(p["x"], p["y"]) for p in s["points"]] for s in glyph["strokes"]]


def run(args):
    from dataclasses import asdict

    root = args.validation
    out = root / args.report_dir
    out.mkdir(exist_ok=False)
    summary = json.loads((root / "summary.json").read_text())
    original = json.loads((root / "original_reviews.json").read_text())
    if {r["character"] for r in original["reviews"]} != set("传后子生团砖儒七桂而相荡已叵"):
        raise ValueError("This narrative report is specific to the 2026-10-10 reviewed cohort")
    metrics = json.loads((root / "metrics.json").read_text())
    repo = StructureRepository(args.db)
    profile = load_profile(args.profile)
    rows = []
    compared = {}
    for review in original["reviews"]:
        c = review["character"]
        data = json.loads((root / f"comparisons/{ord(c):04X}.json").read_text())
        compared[c] = data
        rows.append(
            {
                "title": c + ("\n原评：好" if review["rating"] == "good" else "\n原评：不好"),
                "curves": [curves(data["A"]), curves(data["B"])],
            }
        )
    for page in range(2):
        render_grid(
            rows[page * 7 : (page + 1) * 7], ["原输出 A", "修复候选 B"], out / f"whole_{page}.png"
        )
    targets = {
        "传": [2, 3],
        "砖": [5, 6],
        "桂": [4, 6, 7],
        "生": [2],
        "而": [3],
        "相": [5],
        "儒": [11, 13],
    }
    local_rows = []
    for c, indices in targets.items():
        data = compared[c]
        pair = [curves(data["A"]), curves(data["B"])]
        xy = np.array([p for cs in pair for k in indices for p in cs[k]])
        lo, hi = xy.min(axis=0) - 0.08, xy.max(axis=0) + 0.08
        extent = max(hi - lo)
        mid = (lo + hi) / 2
        local_rows.append(
            {
                "title": c + "\n关键笔画",
                "curves": pair,
                "indices": indices,
                "bounds": (*list(mid - extent / 2), *list(mid + extent / 2)),
            }
        )
    render_grid(local_rows, ["原输出 A", "修复候选 B"], out / "local.png", local=True)
    # Frozen ablations use identical profiles/layout and only toggle the two mechanisms.
    ablations = []
    for c in "传桂生而相":
        value = json.loads((args.development / f"{ord(c):04X}.json").read_text())
        assert value["outputs"]["G"] == compared[c]["B"], "ablation output changed after freezing"
        ablations.append(
            {"title": c, "curves": [curves(value["outputs"][k]) for k in ["A", "E", "S", "G"]]}
        )
    render_grid(ablations, ["原版", "仅端点修复", "仅稀疏残差", "联合修复"], out / "ablations.png")
    # Explicit rejected candidates: do not conceal new damage behind final fallbacks.
    bad_rows = [
        r for r in metrics if r["writer"] == profile.writer_id and r["diagnostics"]["fallback"]
    ]
    rejection_rows = []
    unsafe = ControlRepairGenerator(profile, repo.metadata()["source_version"], guard=False)
    baseline = DeterministicGenerator(profile, repo.metadata()["source_version"])
    for r in bad_rows:
        c = r["character"]
        graph = repo.get(c)
        a = asdict(baseline.generate(graph))
        b = asdict(unsafe.generate(graph))
        rejection_rows.append(
            {"title": c + "\n新增交叉", "curves": [curves(a), curves(b), curves(a)]}
        )
        write(
            out / f"rejected_{ord(c):04X}.json",
            {"A": a, "rejected": b, "diagnostics": r["diagnostics"]},
        )
    render_grid(rejection_rows, ["原输出", "被拒候选", "回退后输出"], out / "rejected.png")
    protection = []
    for c in summary["control_characters"][:10]:
        data = json.loads((root / f"comparisons/{ord(c):04X}.json").read_text())
        protection.append({"title": c, "curves": [curves(data["A"]), curves(data["B"])]})
    render_grid(protection, ["原输出", "全局启用试验"], out / "protection.png")
    # Reconstruct membership in sparse prototype aggregates from the matched raw index.
    index_sha = hashlib.sha256(args.source_index.read_bytes()).hexdigest()
    if index_sha != profile.source_index_sha256:
        raise ValueError("raw source index does not match frozen profile")
    keys = {
        event["key"]
        for d in compared.values()
        for event in d["diagnostics"]["events"]
        if event["kind"] == "sparse_residual"
    }
    donors = {key: [] for key in sorted(keys)}
    accepted, raw_chars = 0, set()
    for sample in iter_index(args.source_index):
        raw_chars.add(sample.character)
        try:
            graph = repo.get(sample.character)
            aligned = align_sample(sample, graph)
        except (ValueError, KeyError):
            continue
        if aligned.stroke_order_status == "ambiguous" or sample.writer_id != profile.writer_id:
            continue
        accepted += 1
        for mapping in aligned.mappings:
            if mapping.mapping_type != "one_to_one" or mapping.confidence < 0.30:
                continue
            standard = graph.strokes[mapping.standard_orders[0] - 1]
            key = f"{signature_key(standard.signature)}@{standard.component_path}"
            if key in donors:
                user_index = mapping.user_orders[0] - 1
                donors[key].append(
                    {
                        "character": sample.character,
                        "sample_id": sample.sample_id,
                        "source_sha256": sample.source_sha256,
                        "standard_stroke_id": standard.stroke_id,
                        "user_order": user_index + 1,
                        "confidence": mapping.confidence,
                        "raw_full_glyph": [
                            [
                                (p.x / sample.canvas_width, p.y / sample.canvas_height)
                                for p in s.points
                            ]
                            for s in sample.strokes
                        ],
                    }
                )
    assert accepted == profile.sample_count
    for key, ds in donors.items():
        assert len(ds) == profile.prototypes[key].sample_count, (key, len(ds))
    write(
        out / "donors.json",
        {
            "index_sha256": index_sha,
            "accepted_samples": accepted,
            "target_originals": sorted(raw_chars & set(compared)),
            "donors": donors,
        },
    )
    donor_rows = []
    for key, ds in donors.items():
        for donor in ds:
            donor_rows.append(
                {
                    "title": donor["character"] + "\n第" + str(donor["user_order"]) + "笔",
                    "curves": [donor["raw_full_glyph"]],
                    "indices": [donor["user_order"] - 1],
                }
            )
    render_grid(donor_rows, ["原始完整轨迹（非目标原稿）"], out / "donors.png", local=True)
    table = "".join(
        f"<tr><td>{s['writer']}</td><td>{s['n']}</td><td>{s['changed']}</td><td>{s['fallback']}</td><td>{s['output_invariant_failure']}</td></tr>"
        for s in summary["cohorts"]
    )
    bow_rows = []
    for c, stroke_index in [("传", 2), ("砖", 5), ("桂", 4), ("生", 2)]:
        item = next(r for r in metrics if r["writer"] == profile.writer_id and r["character"] == c)
        a, b = item["A"][stroke_index], item["B"][stroke_index]
        bow_rows.append(
            f"<tr><td>{c} 第{stroke_index + 1}笔</td><td>{a['max_chord_distance']:.4f}</td><td>{b['max_chord_distance']:.4f}</td></tr>"
        )
    bow_table = "".join(bow_rows)
    doc = f"""<!doctype html><meta charset="utf-8"><title>已知字形问题修复对比</title>
<style>body{{font:17px/1.75 system-ui;max-width:1140px;margin:45px auto;color:#182c46;padding:20px}}img{{max-width:100%;height:auto}}table{{border-collapse:collapse}}td,th{{padding:8px 20px;border:1px solid #ccd}}a{{color:#145da0}}.note{{background:#f2f5fa;padding:20px}}</style>
<h1>已知字形问题：第一批修复与复评</h1><p>2026-10-10 · 固定原档案、标准结构和 adaptive 参数；生产默认不变。</p>
<p class="note">确认并修复了端点位移重复叠加及不连续施加的问题。传、砖、桂、生的碗形短横明显减轻；而、相、儒的部分圆拱收敛。12 个坏字生成了不同候选，但这不代表 12 个坏字已经全部修好。荡无变化；后、子、七、团、已仍有未解决或需偏好确认的问题。</p>
<p><a href="../修复候选.inkreview">打开独立复评项目</a> · <a href="../summary.json">统计</a> · <a href="../protocol.json">冻结协议与输入哈希</a> · <a href="../metrics.json">逐字逐笔数据</a> · <a href="donors.json">原型真实来源</a></p>
<h2>修复机制及贡献</h2><p>端点统计已经记录相对原笔画的总位移，旧生成器在包围盒变换后再次叠加，仅移动首尾控制点。新路径只施加一次总位移：近直笔以端点间的等比旋转变换保留细微弧度；折笔把剩余端点修正沿弧长连续分配。未把所有横画拉成直线。第二项独立实验仅收缩不足 4 个样本的折笔原型中非仿射残差，保留端点残差；它是需复评的保守正则化，不是少样本等于错误。</p>
<img src="ablations.png"><p>单独改端点可消除短横主要失真；单独收缩稀疏残差影响框形圆拱。候选来源、档案、布局参数相同，未重新建档。</p>
<h2>全部标记字：统一坐标与笔宽</h2><p>坐标均为原来的 0–1 字框；笔宽/字高 = 0.3/6。各字未分别拉伸。右列是算法候选，包括保护字叵的试验变化；交付项目中的叵仍是原文件。</p><img src="whole_0.png"><img src="whole_1.png">
<h2>关键笔画局部放大</h2><p>每行两幅图使用共同裁切框、缩放和笔宽；蓝色为指定笔画、灰色为邻笔；橙色起点，绿色终点。该图比较生成结果，不是与作者真值比较。</p><img src="local.png">
<h2>收益边界</h2><ul><li>明确可见：传、砖、桂、生的短横异常弯曲减轻，涉及正文 19 次出现。</li><li>局部改善：而、相、儒的圆拱收敛；相的闭合缺口、儒的拥挤仍存在，不能记为完整成功。</li><li>仍未完成：后上部连接和口的比例，子/七/已的作者偏好，团内部连接，荡的复杂折笔。荡保持原样。</li></ul>
<table><tr><th>目标短横</th><th>原弦线最大偏离</th><th>候选弦线最大偏离</th></tr>{bow_table}</table><p>单位为字框边长；分别约减少 88%、87%、86%、74%。这里只刻画已定位的碗形缺陷，不代表风格总质量。未以弧长越接近参考骨架作为成功判据。</p>
<h2>回归检查与保护</h2><table><tr><th>作者</th><th>字数</th><th>算法改变</th><th>新增交叉回退</th><th>最终协议失败</th></tr>{table}</table>
<p>共 866 个作者–字组合。632 个基线完整对象与原输出一致。候选新增交叉 10 个，全部回退；候选未发现新增零长度笔画或协议失败。检查笔数、标准 ID、笔顺、有限坐标、压力范围、单调时间和字框。交叉仅指中心线严格相交，不涵盖粗笔接触、闭合缺口或视觉不自然；通过不代表质量合格。</p>
<p>参数仅在 14 个已看过的标记字确定，它们是开发/回归集。618 个未标记字是固定参数保护检查，不是逐字质量好标签；另外三位作者各 78 字仅作机械回归，不能推断更像其本人，也不是已验证的统计泛化。</p>
<p>独立复评项目仅替换 12 个原 bad 字；其余 620 个文件逐字节保留。原项目和 14 条旧评价保存在原地及审计副本；发生变化的 12 个候选不继承旧 bad，也不自动变为 good。</p>
<h3>主动展示损伤：未经保护的候选新增交叉</h3><img src="rejected.png"><p>这两个案例说明不宜全库直接启用。交付项目未改动这些未标记字。</p>
<details><summary>查看 10 个按哈希预选的保护对照</summary><img src="protection.png"></details>
<h2>作者原始轨迹核对</h2><p>本地原始索引哈希与冻结档案完全一致；复现了 {accepted} 个有效样本及这些稀疏原型的全部成员数。14 个标记字均无目标原稿。以下是相关原型的完整真实来源轨迹：它们只能帮助辨别曲度确有作者来源，不能证明迁移到目标字后比例与连接正确。原型样本数并非独立字种数，例如某条含 3 次“茶”的重复采样，不能当作 3 个独立字形证据。未改写原轨迹或档案。</p><details><summary>查看实际原型来源笔画（完整点序列）</summary><img src="donors.png"></details>
<h2>接入建议</h2><p>先在这份独立项目复评，优先接受端点修复明确改善的短横；框形正则化保持独立开关。之后按部件扩大人工保护集，检查闭合、钩长及粗笔接触，再决定默认接入。当前可用于可关闭的候选生成，尚不适合整体替换生产默认。</p>
"""
    (out / "报告.html").write_text(doc, encoding="utf-8")
    print(out / "报告.html")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", default="report")
    for arg in ["validation", "development", "profile", "db", "source-index"]:
        parser.add_argument("--" + arg, required=True, type=Path)
    run(parser.parse_args())
