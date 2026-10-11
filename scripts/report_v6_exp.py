"""Evidence report for v6 exp; figures are real curves, not generated illustrations."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
from report_review_repairs import curves, render_grid

from inkstruct.alignment import align_sample
from inkstruct.contextual_trajectory import fit_shared_similarity
from inkstruct.samples import iter_index
from inkstruct.source_trajectory import source_trajectory
from inkstruct.structures import StructureRepository
from inkstruct.trajectory_experiment import curve_error, path_length, projected_tail_length


def run(root):
    out = root / "report"
    out.mkdir(exist_ok=False)
    records = json.loads((root / "records.json").read_text())
    summary = json.loads((root / "summary.json").read_text())
    bychar = {r["character"]: r for r in records}
    values = {c: json.loads((root / f"comparisons/{ord(c):04X}.json").read_text()) for c in bychar}
    zoom = []
    for c, indices in {
        "而": [3, 4, 5],
        "相": [4, 5, 8],
        "儒": [10, 11, 12, 13, 14, 15],
        "荡": [6, 7, 8],
    }.items():
        cs = [curves(values[c][k]) for k in ["A", "V6", "M"]]
        xy = np.array([p for s in cs for i in indices for p in s[i]])
        lo, hi = xy.min(axis=0) - 0.04, xy.max(axis=0) + 0.04
        mid = (lo + hi) / 2
        span = max(hi - lo)
        zoom.append(
            {
                "title": c,
                "curves": cs,
                "indices": indices,
                "bounds": (*list(mid - span / 2), *list(mid + span / 2)),
            }
        )
    render_grid(zoom, ["v4 原输出", "v6 exp", "同来源压缩 M"], out / "local.png", local=True)
    nested = [
        {"title": c, "curves": [curves(values[c][k]) for k in ["V6_flat", "V6"]]} for c in "儒荡"
    ]
    render_grid(nested, ["原部件层级", "验证展开需/汤"], out / "nested.png")
    eval_rows = json.loads((root / "evaluation_only.json").read_text())
    evaluation_ids = {r["sample_id"] for r in eval_rows}
    repo = StructureRepository(Path("artifacts/full_library_20261010/inputs/characters.sqlite3"))
    aligned_metrics = defaultdict(lambda: defaultdict(list))
    examples = {}
    for sample in iter_index(
        Path("artifacts/component_aspect_20261007/user001_snapshot/index.jsonl")
    ):
        if sample.sample_id not in evaluation_ids:
            continue
        graph = repo.get(sample.character)
        source, _ = source_trajectory(sample, align_sample(sample, graph), graph)
        raw = [s.points for s in source.strokes]
        for label in ["A_train", "V6", "M"]:
            generated = curves(values[sample.character][label])
            t = fit_shared_similarity(generated, raw)
            aligned_metrics[sample.character][label].append(
                float(
                    np.mean(
                        [curve_error(t.apply(g), r)[0] for g, r in zip(generated, raw, strict=True)]
                    )
                )
            )
        if sample.character in "木被雪名" and sample.character not in examples:
            examples[sample.character] = {
                "title": sample.character,
                "curves": [
                    raw,
                    *[curves(values[sample.character][label]) for label in ["A_train", "V6", "M"]],
                ],
            }
    render_grid(
        list(examples.values()),
        ["留出原稿", "同训练样本 v4", "v6 exp", "同来源压缩 M"],
        out / "originals.png",
    )
    grouped = {}
    for c in sorted({r["character"] for r in eval_rows}):
        group = [r for r in eval_rows if r["character"] == c]
        grouped[c] = {
            label: float(
                np.mean(
                    [np.mean([s["mean_distance"] for s in row["metrics"][label]]) for row in group]
                )
            )
            for label in ["A", "A_train", "V6", "M"]
        }
    aggregate = {
        k: float(np.mean([v[k] for v in grouped.values()])) for k in ["A", "A_train", "V6", "M"]
    }
    aligned = {
        label: float(np.mean([np.mean(item[label]) for item in aligned_metrics.values()]))
        for label in ["A_train", "V6", "M"]
    }
    improved = sum(row["V6"] < row["A_train"] for row in grouped.values())
    m = next(r for r in records if r["character"] == "荡")["representation_metrics"][6]
    raw = curves(values["荡"]["V6"])[6]
    compressed = curves(values["荡"]["M"])[6]
    hook = {
        "definition": "declared diagnostic tail: original reference vertex index 19 through end; not automatic semantic truth",
        "v6_tail_length": path_length(raw[19:]),
        "M_projected_tail_length": projected_tail_length(compressed, raw[19]),
    }
    result = {
        "per_character_original_distance": grouped,
        "macro_original_distance": aggregate,
        "macro_after_one_glyph_similarity_evaluation_only": aligned,
        "v6_better_than_A_train_characters": improved,
        "n_characters": len(grouped),
        "hook_diagnostic": hook,
        "limitations": "descriptive regression; global raw-coordinate error includes layout; alignment removes only shared scale/translation, not author-specific slant/aspect; no significance claim",
    }
    (out / "evaluation_summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    table = "".join(
        f"<tr><td>{label}</td><td>{aggregate[label]:.5f}</td><td>{aligned[label]:.5f}</td></tr>"
        for label in ["A_train", "V6", "M"]
    )
    provenance = []
    for c in "而相儒荡":
        d = bychar[c]["diagnostics"]
        parts = []
        for p in d["components"]:
            selected = p.get("selection", {}).get("selected")
            parts.append(
                p["canonical"]
                + " ← "
                + (selected["candidate"]["character"] if selected else "完整参考线")
            )
        provenance.append(
            f"<tr><td>{c}</td><td>{'；'.join(parts) if parts else '整字完整参考线（root 无可迁移叶部件）'}</td><td>{bychar[c]['integrity']['source_strokes']}/{len(values[c]['V6']['strokes'])}</td></tr>"
        )
    pt = "".join(provenance)
    doc = f"""<!doctype html><meta charset="utf-8"><title>v6 exp 实验报告</title>
<style>body{{font:17px/1.75 system-ui;color:#152239;max-width:1180px;margin:40px auto;padding:20px}}img{{max-width:100%;height:auto}}table{{border-collapse:collapse}}td,th{{border:1px solid #ccd;padding:9px 16px}}.lead{{background:#f0f5fa;padding:22px}}a{{color:#145da0}}</style>
<h1>v6 exp：完整作者轨迹＋完整参考回退</h1><p>2026-10-11 · 独立实验入口 · 生产默认不变</p>
<p class="lead">实验路径已经运行。完整点序列确实保住折角、末钩和末端方向，尤其“荡”第 7 笔。但当前标准字框布局和大量参考回退，使保护字更接近字体；有原稿的 15 字中，仅 {improved} 字的原坐标几何误差优于同训练样本 v4。评估时仅做一次整字等比对齐后，两者误差接近，说明原坐标差异很大一部分来自布局尺度与位置。结论是：值得保留这条无损表示路径，尚不值得整体替换现有生成器。</p>
<p><a href="../v6_exp.inkreview">独立 78 字复评项目</a> · <a href="../protocol.json">冻结协议与哈希</a> · <a href="../records.json">逐字来源、变换、拒绝与指标</a> · <a href="evaluation_summary.json">原稿评估</a></p>
<h2>路径确实绕过了什么</h2><p>V6 只读取完整原始轨迹档案和参考中心线。没有调用旧 v4 生成器，没有 8 点输出控制网，没有平均多个作者实例，也没有 B-Spline。每个接受的部件全部笔画来自同一次真实采样，共用一个正的等比缩放和平移；不逐笔拉伸、不混搭。缺少合格来源时逐点保留完整参考线；不回退到旧平滑字形。</p>
<p>检索和对齐仍使用 16 个描述锚点来比较形态和估计变换，这些锚点不替换交付轨迹。原始源档案先做一次整字等比归一化；源点数、点序、压力不丢失。时间按最终笔顺重排，保留源笔画内部时间差，笔间隔 60 ms。参考笔画用固定压力 0.5 和按弧长分配的时间，其压力并非作者真值。</p>
<h2>来源和四字结果</h2><table><tr><th>字</th><th>实际来源</th><th>作者来源笔数/总数</th></tr>{pt}</table>
<p>而：避免借“万”的残差拉宽框形，但当前整个字是参考字形，不能声称模仿了作者。而型底部本就不闭合。相：目部缺口回到参考笔形的范围，收益来自避开不相容端点残差及保留参考路径，不是来自找到了作者目部。儒：亻、雨是实写实例，下部而仍是参考；荡：草头、三点水是实写实例，下部复杂折笔完整保留参考折线。</p>
<img src="../development.png"><p>所有整字均用同一 0–1 坐标和 0.3/6 笔宽比例显示，没有逐字自动铺满。R=完整参考；V6=作者完整部件＋参考回退；M=锁定 V6 候选和变换后，仅施加旧式压缩与样条的诊断对照。M 不参与候选选择，不是交付路径。</p>
<h2>局部折角与末向</h2><img src="local.png">
<p>“荡”第 7 笔 V6 保留全部 21 个参考顶点。固定来源 M 相对 V6 最大局部偏差 {m["max_distance"]:.4f} 个字框单位，末端方向差 {m["terminal_angle_deg"]:.1f}°，弧长比 {m["length_ratio"]:.3f}。指定末钩起点为参考第 20 点时，V6 末段长度 {hook["v6_tail_length"]:.4f}，M 投影对应末段长度 {hook["M_projected_tail_length"]:.4f}。这是相对输入参考的表示保真，不能当作作者风格评分；弧长更长也不自动更好，原始轨迹可能含噪声。</p>
<h2>结构细分贡献单列</h2><img src="nested.png"><p>只对需/汤启用现有顺序形态校验通过的嵌套视图，不改原数据库。不开视图时，儒只有亻、荡只有艹来自作者；展开后另获得雨、氵。原参考路径不变。因此这两处新增来源属于候选覆盖变化，不能算成去平滑的收益。</p>
<h2>数据隔离、固定参数与保护检查</h2><p>4 个已观察字为开发/回归，另 74 个为保护回归（含明确好字叵、其他旧标记字和既有哈希选出的 64 字）。这些不是新盲测质量标签。78 个字及其所有同字重复样本在建源档案前整体排除，剩余 {summary["archive_samples"]} 个完整有效样本、{summary["archive_characters"]} 个字。所有选择阈值沿用既有检索器，运行保护集后未调整。</p>
<p>78 字共 {summary["source_component_count"]} 个作者部件被接受，覆盖 {summary["glyphs_with_source"]} 字；{summary["source_strokes"]} 笔来自作者、{summary["reference_strokes"]} 笔来自参考。逐点验证 {summary["source_points"]} 个作者点均等于记录变换后的原点、压力相同，{summary["reference_points"]} 个参考点与输入逐点相同。笔数、标准 ID、笔顺、有限坐标、压力、全局单调时间、字框检查均通过；无零长度退化；相对完整参考无新增严格中心线交叉。</p>
<p>相对旧 A，“要”多出一对中心线交叉（第 8/9 笔），但它已存在于原参考女部；该部件候选未通过后保留参考，故不能称为新引入的异常交叉，也不能因此自动宣布视觉合格。共记录 29 个经过完整检查后被拒的候选；严格交叉检查不覆盖粗笔接触、闭合间隙和所有拥挤。</p>
<img src="../protection_0.png"><details><summary>更多保护字</summary><img src="../protection_1.png"></details>
<p>明确风险：原来好评的叵在 V6 中更方、更像参考字形，风格被改变；没有沿用其旧好评。原项目、旧档案、旧输出不修改，V6 项目全部待复评。</p>
<h2>留出原稿：实际存在的负面结果</h2><p>生成和选择全部冻结后，才读取 20 份留出原稿（15 个字）评估；四个重点字均无作者原稿。先按笔等权、再按同字样本平均、最后按字等权，避免重复样本多的字占优势。指标为统一折线距离评估，不压缩交付点。A_train 用与 V6 源档案相同的 314 个训练样本重新建一个仅用于比较的 v4 档案；V6 从不读取它。</p>
<table><tr><th>路径</th><th>原坐标平均几何偏差</th><th>评估时仅整字等比对齐后的偏差</th></tr>{table}</table>
<p>旧冻结 A 为 {aggregate["A"]:.5f}，但它可能用过这些目标原稿，所以只能作为历史展示，不能当公平留出基线。A_train 才是相同训练集合对照。V6 与 M 的几何均值几乎一致：关闭压缩/平滑保住局部形状，并未自动解决候选写法、字框比例和参考回退造成的总体差异。此小样本描述不能推断全库统计显著性。</p>
<img src="originals.png"><p>原稿也按同一整字坐标显示。上表第二列包含位置和比例差异；第三列仅在评估阶段对整字做一次等比缩放和平移，绝不逐笔对齐，也不把原稿用于生成。</p>
<h2>接入判断</h2><p>建议保留 v6 exp 作为独立候选路径。可以优先考虑让无可靠作者原型的复杂笔画采用保折点参考回退；有相容作者部件时采用完整点序列。正式替换仍需补上不改笔形的作者整字布局、扩大部件覆盖及人工保护验证。当前证据支持表示更忠实，不能支持整体风格更像作者，更不能默认替换所有字。</p>
"""
    (out / "报告.html").write_text(doc, encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run", type=Path, required=True)
    run(p.parse_args().run)
