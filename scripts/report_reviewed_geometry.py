"""Render source-defect evidence and all reviewed repair outcomes, including refusals."""
from __future__ import annotations

import argparse
import os
from pathlib import Path

import numpy as np
from validate_reviewed_geometry import curves, read

from inkstruct.samples import sha256_file


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    args = parser.parse_args()
    out = args.input/'report'
    out.mkdir(exist_ok=False)
    (out/'figures').mkdir()
    os.environ['MPLCONFIGDIR'], os.environ['XDG_CACHE_HOME'] = str(out/'.mpl'), str(out/'.cache')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    font_manager.fontManager.addfont('/System/Library/Fonts/Supplemental/Arial Unicode.ttf')
    plt.rcParams.update({'font.family': 'Arial Unicode MS', 'axes.unicode_minus': False})
    plan, summary = read(args.input/'frozen_plan.json'), read(args.input/'summary.json')
    for section in ('code_sha256', 'input_sha256'):
        for path, expected in plan[section].items():
            assert sha256_file(Path(path)) == expected, path
    source_figures = []
    for row in read(args.input/'public_source_audit.json'):
        if 'rejection' in row:
            continue
        outline = np.asarray(row['outline'])
        center = (outline.min(0)+outline.max(0))/2
        span = float(np.ptp(outline, axis=0).max())*1.18
        fig, axes = plt.subplots(1, 2, figsize=(10, 4.5))
        for ax, points, title in zip(axes, [row['original_median'], row['proposed']], ['原中心线', '轮廓推导估计'], strict=True):
            a = np.asarray(points)
            ax.fill(outline[:, 0], outline[:, 1], color='#dfe6ec')
            ax.plot(a[:, 0], a[:, 1], color='#b94749', lw=2)
            ax.scatter(a[[0, -1], 0], a[[0, -1], 1], color='#b94749', s=16)
            ax.set_aspect('equal')
            ax.set_xlim(center[0]-span/2, center[0]+span/2)
            ax.set_ylim(center[1]-span/2, center[1]+span/2)
            ax.set_title(title)
        fig.suptitle(f"公开源轮廓 · {row['character']} {row['stroke_id']} · 原弧长 {row['report']['old_length']:.2f} → 估计 {row['report']['proposed_length']:.2f}\n原始源坐标，两图同尺度；非作者原稿")
        fig.tight_layout(rect=(0, 0, 1, .86))
        name = f"figures/source-U+{ord(row['character']):04X}.png"
        fig.savefig(out/name, dpi=130)
        plt.close(fig)
        source_figures.append(name)
    rows = [read(p) for p in sorted((args.input/'cases').glob('*.json'))]
    gallery, table = [], []
    for row in rows:
        lines = {'S': [s['median'] for s in row['standard']['strokes']], 'A': curves(row['before']), 'R': curves(row['after'])}
        selected = {'黧': 0, '瀝': 5, '丢': 0, '侈': 6}[row['character']]
        cloud = np.asarray([p for k in ('S', 'A', 'R') for p in lines[k][selected]])
        center = (cloud.min(0)+cloud.max(0))/2
        span = max(float(np.ptp(cloud, axis=0).max())*1.5, .14)
        fig, axes = plt.subplots(2, 3, figsize=(11, 7.5))
        for col, label in enumerate(('S', 'A', 'R')):
            for r in range(2):
                ax = axes[r, col]
                for i, stroke in enumerate(lines[label]):
                    a = np.asarray(stroke)
                    ax.plot(a[:, 0], a[:, 1], color='#2e789b' if i == selected else '#aebbc5', lw=1.9 if i == selected else 1.)
                    if i == selected:
                        ax.scatter(a[[0, -1], 0], a[[0, -1], 1], color='#2e789b', s=12)
                ax.set_aspect('equal')
                ax.set_xlim((-.02, 1.02) if r == 0 else (center[0]-span/2, center[0]+span/2))
                ax.set_ylim((1.02, -.02) if r == 0 else (center[1]+span/2, center[1]-span/2))
                ax.grid(alpha=.13)
                ax.tick_params(labelsize=7)
            axes[0, col].set_title({'S': '公开原中心线·非作者原稿', 'A': 'A · 现有生成', 'R': 'R · 复核修正'}[label], fontsize=10)
        changed = '、'.join(row['repair']['changed_geometry_ids']) or '无操作'
        fig.suptitle(f"{row['writer']} · {row['character']} · 改变几何：{changed}\n整字同尺度，下排共享局部范围 s{selected+1}；所有输出顶点直接绘制", fontsize=12)
        fig.tight_layout(rect=(0, .02, 1, .91))
        fig.subplots_adjust(hspace=.22)
        name = f"figures/{row['writer']}-U+{ord(row['character']):04X}.png"
        fig.savefig(out/name, dpi=130)
        plt.close(fig)
        removed = '、'.join(f's{i+1}/s{j+1}' for i, j in row['removed_crossings']) or '无'
        table.append(f'<tr><td>{row["writer"]}</td><td>{row["character"]}</td><td>{changed}</td><td>{removed}</td><td>{row["before_lengths"][selected]:.5f} → {row["after_lengths"][selected]:.5f}</td></tr>')
        gallery.append(f'<h3>{row["writer"]} · {row["character"]}</h3><img loading="lazy" src="{name}"><p><a href="../cases/{row["writer"]}-U+{ord(row["character"]):04X}.json">全部轨迹、修正与拒绝原因</a></p>')
    style = '<style>body{max-width:1250px;margin:32px auto;padding:0 24px;font:16px/1.8 system-ui;color:#263b50;background:#f5f7fa}img{width:100%}table{border-collapse:collapse;width:100%;background:white}td,th{padding:10px;border-bottom:1px solid #ddd;text-align:left}.finding{background:#e9f2e9;padding:20px}a{color:#12689c}</style>'
    prefix = '<!doctype html><meta charset="utf-8"><title>InkStruct 已复核局部几何修正</title>'+style
    text = '<h1>已复核局部几何修正：源退化与异常交叉</h1><p>2026-10-07 · 独立开关 reviewed-geometry · 默认关闭 · 不改上游文件和结构数据库</p><p class="finding"><strong>结果：</strong>公开源中的黧 s1、瀝 s6 均存在长轮廓配近零中心线的问题。三位作者的输出都接受了只改该笔的结构估计修正，并通过新增交叉与不变量检查。scx 丢、mjb 侈的已复核交叉消除；scx 侈没有有界安全平移，继续保留。每位作者 64 个非目标保护字的原有字形字段不变。</p>'
    text += '<h2>源数据证据</h2><p>扫描公开 graphics 全部记录，以原坐标中心线弧长小于 10 筛查近点候选，只有瀝 s6 和黧 s1；它们均通过已有细长单轮廓、中心线/轮廓跨度不足 5%、各截面单区间的检查。40 个截面中点构造源估计，起止方向依据原末端区域。仅适用于这两条版本和哈希锁定的记录；这不是全面源数据正确性证明，其他类型缺陷仍可能存在。</p>'
    for name in source_figures:
        text += f'<img src="{name}">'
    text += '<h2>全部 12 个诊断结果</h2><table><tr><th>作者</th><th>字</th><th>改变笔画</th><th>消除严格交叉</th><th>局部笔画弧长</th></tr>'+''.join(table)+'</table><p>弧长只是验证近点退化消失，不能据此宣称风格更好。这里缺少目标字作者原稿；公开标准图也不能冒充作者原稿。scx/mjb 的已有案例属于已观察回归；瀝是这轮新识别的源问题，wsq 为第三份作者档案上的几何约束核验，均非笔迹泛化精度或盲评结论。</p>'
    text += '<h2>如何限制改动</h2><p>源轮廓修正只在生成笔画相对修正候选严重缩短时尝试，且只取修正图产生的指定单笔；其余笔画位置、形状和压力保留。若引入交叉，只允许该笔在既有 0.06 位移预算内作刚性平移；不能消除则整体放弃此次修正。已采集整字/真实部件笔画始终受保护。</p><p>丢/侈平移必须匹配已复核作者、结构版本和完整输出几何哈希。即使字符相同，只要输出不同就不自动修正；哈希相同但笔画已被标为真实采集来源也拒绝移动。步长 0.002、16 个方向、中心线间隙 0.002 沿用原诊断参数，当前不重新调参。没有把所有偏离标准的相交都判成错误。</p>'
    text += '<h2>保护、写出与实际入口</h2><p>三位作者各 68 个 A/R 输出，共 408 个主回归轨迹；每人 64 个非目标字的原有字形字段不变（仅增加独立修正诊断）。204 个 R 文件续跑哈希一致，切换开关复用旧 run-id 被拒绝。另做 24 个原始源路径组合输出，scx/mjb 共 59 笔真实来源几何及压力不变。全程未改原档案、上游轮廓和 SQLite。</p><p>CLI 增加 --reviewed-geometry；Mac 新增“使用已复核的局部几何修正（实验）”，默认不选。必须使用确定性 adaptive/1，来源估计、改动笔画、拒绝原因和运行身份写入独立 geometry_repairs 元数据。原始源生成的局部风险显示会同步更新。</p>'
    text += '<h2>性能边界</h2><table><tr><th>作者</th><th>A 68 字秒数</th><th>R 68 字秒数</th></tr>'
    for writer, data in summary.items():
        text += f'<tr><td>{writer}</td><td>{data["batch_seconds"]["A"]:.3f}</td><td>{data["batch_seconds"]["R"]:.3f}</td></tr>'
    text += '</table><p>同机单次、固定 A 后 R，含 SVG 写出，未隔离缓存和系统负载。失败的有界平移搜索仍较慢；未配置字符采用快速无操作返回。这里没有证明达到全库 1.5 倍预算，不默认开启。</p><h2>剩余问题</h2><p>scx 侈仍缺安全平移；此前完整夕迁移方案也有明显形态变化，不能仅凭交叉消失推广。徹/徽供体不足、未见字末向、自然变化、人类盲评及真实设备边缘事件仍未完成。严格笔间交叉检查不涵盖墨迹笔宽粘连和所有自交。</p><p><a href="../summary.json">完整指标</a> · <a href="../frozen_plan.json">输入、参数与代码哈希</a> · <a href="../public_source_audit.json">公开源筛查记录</a></p>'+''.join(gallery)
    (out/'InkStruct_已复核几何修正报告.html').write_text(prefix+text)
    print(out/'InkStruct_已复核几何修正报告.html')


if __name__ == '__main__':
    main()
