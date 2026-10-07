"""Report the frozen terminal experiment, including its negative new-author result."""
from __future__ import annotations

import argparse
import html
import json
import os
from pathlib import Path

import numpy as np

from inkstruct.geometry import path_length
from inkstruct.terminal_selection import terminal_vector
from inkstruct.trajectory_experiment import stroke_metrics


def read(path):
    return json.loads(path.read_text())


def curves(glyph):
    return [[(p['x'], p['y']) for p in s['points']] for s in glyph['strokes']]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--development', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    out = args.output or args.input / 'report'
    out.mkdir(exist_ok=False)
    (out / 'figures').mkdir()
    os.environ.setdefault('MPLCONFIGDIR', str(out / '.mpl'))
    os.environ.setdefault('XDG_CACHE_HOME', str(out / '.cache'))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    font_manager.fontManager.addfont('/System/Library/Fonts/Supplemental/Arial Unicode.ttf')
    plt.rcParams.update({'font.family': 'Arial Unicode MS', 'axes.unicode_minus': False})
    records = [read(p) for p in sorted((args.input / 'cases').glob('*.json'))]
    development = [read(p) for p in sorted((args.development / 'cases').glob('*.json'))]
    choice = read(args.development / 'frozen_choice.json')['chosen']
    dev_summary = read(args.development / 'summary.json')
    summary = read(args.input / 'summary.json')
    selected_development = [r for r in development if (r['selected'][choice] or {}).get('candidate') != (r['selected']['D'] or {}).get('candidate')]

    def draw(case, prefix):
        lines = {'reference': case['reference'], **{k: curves(v) for k, v in case['variants'].items()}}
        labels = ['reference', 'A', 'D', 'E']
        indices = [i for i, s in enumerate(case['variants']['A']['strokes']) if s['standard_stroke_id'] in case['task']['target_stroke_ids']]
        def angle_delta(i):
            a = stroke_metrics(lines['A'][i], lines['reference'][i])['terminal_angle_deg']
            b = stroke_metrics(lines['E'][i], lines['reference'][i])['terminal_angle_deg']
            return abs((b or 0.) - (a or 0.))
        index = max(indices, key=angle_delta)
        cloud = np.asarray([p for label in labels for p in lines[label][index]])
        center = (cloud.min(0) + cloud.max(0)) / 2
        span = max(float(np.ptp(cloud, axis=0).max()) * 1.5, .10)
        fig, axes = plt.subplots(2, 4, figsize=(13, 7))
        colors = ['#222222', '#2070a8', '#14836c', '#9450a4']
        for col, (label, color) in enumerate(zip(labels, colors, strict=True)):
            for row in range(2):
                ax = axes[row, col]
                for i, points in enumerate(lines[label]):
                    a = np.asarray(points)
                    ax.plot(a[:, 0], a[:, 1], color=color if i in indices else '#bcc4cb', lw=1.7 if i == index else 1.)
                    if i == index:
                        ax.scatter(*a[-1], color=color, s=13)
                        if row == 1:
                            window = min(.02, .15 * path_length(lines['reference'][i]))
                            direction = terminal_vector(points, window)
                            if direction is not None:
                                end = a[-1] + direction * span * .10
                                ax.annotate('', xy=end, xytext=a[-1], arrowprops={'arrowstyle': '->', 'color': color, 'lw': 1.5})
                ax.set_aspect('equal')
                ax.set_xlim((-.02, 1.02) if row == 0 else (center[0]-span/2, center[0]+span/2))
                ax.set_ylim((1.02, -.02) if row == 0 else (center[1]+span/2, center[1]-span/2))
                ax.grid(alpha=.15)
                ax.tick_params(labelsize=7)
            axes[0, col].set_title({'reference': '作者原稿·仅评估', 'A': 'A · 固定 v4 adaptive',
                'D': 'D · 完整部件共同拟合', 'E': 'E · 冻结末向评分'}[label], fontsize=10)
            if label != 'reference':
                values = case['metrics'][label]
                axes[1, col].set_xlabel(f"部件几何均差 {values['mean_distance']:.4f}\n末向均差 {values['terminal_angle_deg']:.2f}°", fontsize=9)
        fig.suptitle(f"{prefix} · {case['task']['character']} · 局部为 s{index+1}\n圆点为末端，箭头为评估窗口弦方向；所有输出顶点直接绘制", fontsize=12)
        fig.tight_layout(rect=(0, 0, 1, .92))
        fig.subplots_adjust(hspace=.30)
        name = f"figures/{prefix}-{case['task']['id']}.png"
        fig.savefig(out / name, dpi=140)
        plt.close(fig)
        return name

    gallery = []
    figures = {}
    for number, case in enumerate(records, 1):
        name = draw(case, 'wsq')
        figures[case['task']['id']] = name
        selected = case['provenance_E']['selected']
        donor = selected['candidate']['character'] if selected else '回退 A'
        gallery.append(f'<details><summary>{html.escape(case["task"]["character"])} · 供体 {html.escape(donor)}</summary><img loading="lazy" src="{name}"><p><a href="../cases/{case["task"]["id"]}.json">全部轨迹与候选记录</a></p></details>')
        if number % 16 == 0:
            print('figures', number, '/', len(records), flush=True)
    dev_figures = []
    for record in selected_development:
        converted = {'task': record['task'], 'reference': record['reference'],
            'variants': {k: record['outputs'][v] for k, v in [('A', 'A'), ('D', 'D'), ('E', choice)]},
            'metrics': {k: record['metrics'][v] for k, v in [('A', 'A'), ('D', 'D'), ('E', choice)]}}
        dev_figures.append(draw(converted, 'scx开发'))
    style = '<style>body{max-width:1260px;margin:32px auto;padding:0 24px;font:16px/1.8 system-ui;color:#263b50;background:#f6f8fa}img{width:100%}table{border-collapse:collapse;width:100%;background:white}th,td{padding:9px;text-align:left;border-bottom:1px solid #dae1e7}h2{margin-top:32px}details{background:white;padding:16px;margin:14px 0;border:1px solid #d8e0e7}a{color:#12689c}.finding{padding:18px;background:#fff1e7}</style>'
    text = '<h1>末端方向候选优化：冻结验证与负结果</h1><p>2026-10-07 · E 只改变候选评分，轨迹表示和共同变换不变 · 生产默认与现有实验入口均不变</p>'
    text += '<p class="finding"><strong>结论：</strong>新增末向评分在 scx 开发集只改选 1 字，在新作者 wsq 的 64 字上没有改选任何供体，E 与 D 全字段完全一致。D/E 相对 A 的几何偏差增加约 1.4%、末向误差增加约 1.5°。本次改进没有通过独立作者验证，不接入正式生成器。</p>'
    text += '<h2>预先固定的实验设计</h2><p>沿用 scx 的 32 个开发目标、相同训练供体和前 16 个候选，整部件依旧采用一个正等比缩放和平移。方向提示分别来自生成 A 和公共标准中心线，权重预设为 0、0.0025、0.005、0.01、0.02、0.04。按字求平均，候选选择从不读取目标原稿；原稿仅在生成完成后用于评估。</p><p>选择规则预先要求几何均差不超过 D 的 1.01 倍、启用字数相同，再最小化末向均差。冻结得到标准方向提示、权重 0.005；不在 wsq 上调整。wsq 恢复并独立建档 791 个完整原始样本，A 仅用训练组的 456 个成功样本；156 个有效测试字中 92 个有相容供体，按上下文轮转取 64 个。结果只适用于这类可检索部件，不能代表全部 156 字。</p>'
    text += '<h2>开发集与新作者结果分开报告</h2><table><tr><th>集合</th><th>路径</th><th>几何均差</th><th>末向均差</th><th>弧长绝对相对差</th></tr>'
    for group, data, labels in [('scx 开发，32 字', dev_summary, [('A', 'A'), ('D', 'D'), ('E', choice)]), ('wsq 确认，64 字', summary, [('A', 'A'), ('D', 'D'), ('E', 'E')])]:
        for display, key in labels:
            values = data[key]
            text += f'<tr><td>{group}</td><td>{display}</td><td>{values["mean_distance"]:.6f}</td><td>{values["terminal_angle_deg"]:.2f}°</td><td>{values["absolute_length_error"]:.2%}</td></tr>'
    text += '</table><p>开发集 A 方向提示的全部非零权重均未改选。标准提示只在“妮”出现所选权重的改善，不能将这一例收益解释成普遍趋势。wsq 的 D/E 启用 62 字，2 字回退；几何优于 A 为 22/64，末向优于 A 为 27/64。更接近弧长不自动代表更好的书写风格。</p>'
    for name in dev_figures:
        text += f'<h2>唯一改变的开发案例</h2><img src="{name}">'
    text += '<h2>为何没有改选：确认后的分数核查</h2><p>64 字中，2 字无安全候选，12 字只有一个，50 字有多个。后者中 9 字的 D 已具有最低标准方向惩罚；其余 41 字至少需要 0.00811 的权重才可能改变排序，高于冻结的 0.005。这个核查只解释原分数，没有尝试用验证结果重选权重，也没有生成“调大后更好”的结论。问题并非都能归因于缺候选，目标方向提示和候选分数尺度仍需新的开发实验。</p>'
    text += '<h2>按末向变化自动选出的两端案例</h2>'
    ordered = sorted(records, key=lambda c: c['metrics']['D']['terminal_angle_deg'] - c['metrics']['A']['terminal_angle_deg'])
    for case, label in [(ordered[0], '改善最多'), (ordered[-1], '退化最多')]:
        text += f'<h3>{label}：{case["task"]["character"]}</h3><img src="{figures[case["task"]["id"]]}">'
    text += '<h2>完整性与边界</h2><p>192 个 A/D/E 输出全部通过有限坐标、范围、压力、笔数、标准 ID、笔顺和全局时间检查；D/E 没有新增相对 A 的严格笔间交叉。62 个接受部件的 12,403 个源点、压力及笔内相对时间逐项核验吻合。同字重复按字符分组，旧档案和输出未覆盖。</p><p>同字重建能保住源折钩，仍不意味着跨字供体能自动匹配目标作者形态。一次新作者验证也不是全面统计结论。当前保留已接入实验开关和原平滑默认，不把失败的权重方案推入生产；后续开发需要更可靠的目标方向提示及跨作者分数尺度，再使用新的未观察目标确认。这里不宣称所有已知问题已解决。</p>'
    text += '<p><a href="gallery.html">全部 64 字图集</a> · <a href="../summary.json">确认指标</a> · <a href="../frozen_plan.json">冻结计划与哈希</a> · <a href="../integrity_and_candidate_audit.json">完整性与候选核查</a></p>'
    prefix = '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>InkStruct 末端方向实验</title>' + style
    (out / 'InkStruct_末端方向实验报告.html').write_text(prefix + text)
    (out / 'gallery.html').write_text(prefix + '<h1>wsq 全部 64 个确认案例</h1><p>统一尺度的原稿、A、D、E；E 与 D 输出相同，负结果全部保留。</p>' + ''.join(gallery))
    print(out / 'InkStruct_末端方向实验报告.html')


if __name__ == '__main__':
    main()
