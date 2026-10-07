"""Illustrated report for the frozen contextual placement confirmation set."""
from __future__ import annotations

import argparse
import base64
import html
import json
import os
from pathlib import Path

import numpy as np


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    args = parser.parse_args()
    root = args.input
    out = root / 'report'
    out.mkdir(exist_ok=False)
    (out / 'figures').mkdir()
    os.environ.setdefault('MPLCONFIGDIR', str(root / 'matplotlib'))
    os.environ.setdefault('XDG_CACHE_HOME', str(root / 'cache'))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    font = '/System/Library/Fonts/Supplemental/Arial Unicode.ttf'
    font_manager.fontManager.addfont(font)
    plt.rcParams.update({'font.family': font_manager.FontProperties(fname=font).get_name(),
                         'font.size': 10, 'axes.unicode_minus': False})
    records = [json.loads(p.read_text()) for p in sorted((root / 'cases').glob('*.json'))]
    summary = json.loads((root / 'summary.json').read_text())
    gallery = []
    for n, case in enumerate(records, 1):
        task = case['task']
        lines = {'原稿': case['reference'], **{k: [[(p['x'], p['y']) for p in s['points']] for s in v['strokes']]
                                              for k, v in case['variants'].items()}}
        labels = ['原稿', 'A', 'B', 'D']
        colors = ['#222222', '#0072b2', '#aa4499', '#009e73']
        index = case['indices'][0]
        cloud = np.asarray([p for label in labels for p in lines[label][index]])
        center = (cloud.min(axis=0) + cloud.max(axis=0)) / 2
        span = max(float(np.ptp(cloud, axis=0).max()) * 1.2, .1)
        fig, axes = plt.subplots(2, 4, figsize=(12, 6.6))
        for col, (label, color) in enumerate(zip(labels, colors, strict=True)):
            for row in range(2):
                ax = axes[row, col]
                for i, p in enumerate(lines[label]):
                    a = np.asarray(p)
                    ax.plot(a[:, 0], a[:, 1], color=color if i in case['indices'] else '#c8c8c8',
                            lw=2 if i == index else 1)
                    if i == index:
                        ax.scatter(*a[-1], marker='s', s=15, c=color)
                ax.set_aspect('equal')
                ax.set_xlim((-.02, 1.02) if row == 0 else (center[0] - span / 2, center[0] + span / 2))
                ax.set_ylim((-.02, 1.02) if row == 0 else (center[1] - span / 2, center[1] + span / 2))
                ax.invert_yaxis()
                ax.grid(alpha=.15)
                ax.tick_params(labelsize=7)
            axes[0, col].set_title({'原稿': '原稿·仅评估', 'A': 'A · v4 adaptive',
                                   'B': 'B · 包围盒等比变换', 'D': 'D · 共同拟合与候选重排'}[label])
            if label != '原稿':
                metric = case['metrics'][label]
                axes[1, col].set_xlabel(f"部件均差 {metric['mean_distance']:.4f}\n末向误差 {metric['terminal_angle_deg']:.1f}°")
        selected = case['provenance']['selected']
        donor = selected['candidate']['character'] if selected else '回退 A'
        fig.suptitle(f"{task['id'].split('-')[0]} · {task['character']} · D 供体 {donor}\n整字与局部共用显示比例；高亮为迁移部件，方块为末端", fontsize=13)
        fig.tight_layout(rect=(0, 0, 1, .91))
        fig.savefig(out / 'figures' / f"{task['id']}.png", dpi=140)
        plt.close(fig)
        gallery.append(f'<details><summary>{html.escape(task["id"])} · {task["character"]}</summary>'
                       f'<a href="figures/{task["id"]}.png"><img loading="lazy" src="figures/{task["id"]}.png"></a>'
                       f'<p><a href="../cases/{task["id"]}.json">轨迹与完整候选诊断</a></p></details>')
        if n % 20 == 0:
            print(f'figures {n}/{len(records)}', flush=True)
    style = '<style>body{max-width:1280px;margin:32px auto;padding:0 24px;font:16px/1.75 -apple-system,sans-serif;color:#24303d}h1{font-size:29px}h2{margin-top:34px}img{width:100%}table{border-collapse:collapse;width:100%}td,th{padding:8px;border-bottom:1px solid #ccd4de;text-align:left}th{background:#edf2f7}details{padding:9px;border-bottom:1px solid #ddd}.lead{padding:18px;background:#eaf4ed}a{color:#075aa6}</style>'
    body = '<h1>上下文完整轨迹优化：冻结验证报告</h1><p>2026-10-07 · 算法 D · 生产默认保持不变</p>'
    body += '<p class="lead">D 在两组新验证样本上把平均几何偏差降低约 3%，且没有新增相对 A 的严格笔间交叉；末向误差有所上升，耗时也增加。它是有效但仍有限的推进，不是已解决所有风格与布局问题。</p>'
    body += '<h2>算法与实验隔离</h2><p>保留完整源点，不做 16/8 点压缩输出。用每笔等权的匹配锚点求整个部件唯一的等比缩放和平移，再按放置后的形态重排最多 16 个真实供体；若新增严格交叉、越界或过度缩短，则尝试下一整部件候选。目标原稿只用于评分。</p><p>另试验了一个对所有笔画共用的平滑空间位移场，限制其导数以避免折叠；开发集没有收益，因此冻结为关闭。开发集是之前的 32 个 scx 跨字案例。确认集 scx 27 字不在上一轮 192 案例中，mjb 53 字未用于本算法调参；同字按相同哈希归组，两个作者均只用各自训练组建 A 档案和供体库。因数据有限，不报告统计显著性。</p>'
    for writer, result in summary.items():
        body += f'<h2>{writer}：{result["n"]} 个新验证字</h2><table><tr><th>路径</th><th>平均几何偏差</th><th>平均末向误差</th><th>弧长绝对相对差</th><th>优于/差于 A</th></tr>'
        for label in ('A', 'B', 'D'):
            r = result[label]
            body += f'<tr><td>{label}</td><td>{r["mean_distance"]:.5f}</td><td>{r["terminal_angle_deg"]:.2f}°</td><td>{r["absolute_length_error"]:.2%}</td><td>{r["better_than_A"]}/{r["worse_than_A"]}</td></tr>'
        improvement = 1 - result['D']['mean_distance'] / result['A']['mean_distance']
        speed = (result['median_seconds']['A'] + result['median_seconds']['D_additional']) / result['median_seconds']['A']
        body += f'</table><p>D 平均几何偏差减少 {improvement:.2%}；整部件回退 {result["fallbacks"]} 字。当前测得单部件算法总耗时约为 A 的 {speed:.1f} 倍（不含 PNG，仅探索性计时），尚需优化后才能考虑批量默认启用。每字是统计单位，指标仅计算所迁移部件。</p>'
        selected = [c for c in records if c['task']['id'].startswith(writer + '-')]
        selected.sort(key=lambda c: c['metrics']['D']['mean_distance'] - c['metrics']['A']['mean_distance'])
        for case, caption in [(selected[0], '改善最多'), (selected[-1], '退步最多')]:
            name = case['task']['id']
            encoded = base64.b64encode((out / 'figures' / f'{name}.png').read_bytes()).decode()
            body += f'<h3>{writer} {caption}：{case["task"]["character"]}（事后展示，不作选参）</h3><a href="figures/{name}.png"><img src="data:image/png;base64,{encoded}"></a>'
    body += '<h2>已确认收益与尚未解决的问题</h2><p>80 个字共 240 个 A/B/D 输出通过坐标、压力、笔数、ID、笔顺和全局时间检查；D 全部保留所选供体完整点列，并且没有新增相对 A 的严格笔间交叉。但回退 A 也无法修复 A 原有交叉，因此不把这个门槛等同于“无交叉错误”。同一供体的末向保存完好，也不能保证它符合目标字的真实末向。D 当前继承 A 的置信度字段，尚未重新校准，不能把它当作 D 的质量证据；另已逐点核验 80 个 D 部件共 4,275 个源点的坐标、压力和相对时间全部吻合。</p><p>本轮还在正式评估器加入局部审计：最低笔画置信度、低分笔画 ID、来源、相对标准中心线的额外交叉、极短源笔画和近点状输出。scx 的丢 s1/s2、侈 s6/s7、劓最低分 0.27929，以及 mjb 的黧 s1 短笔风险均重新检出。这些是风险证据，不应伪装为已经修复。原评估漏掉的笔间时间倒序现已能拒绝。</p><p>下一步仍需解决已有异常交叉、目标上下文中的末端方向、敫内攵的嵌套视图、真实整部件变体、源中心线异常及吞吐性能；保持生产默认不变。自然变化还缺作者同字重复采集，不能用随机噪声假装验证。</p>'
    body += '<p><a href="gallery.html">全部 80 案例</a> · <a href="../summary.json">机器可读指标</a> · <a href="../frozen_plan.json">冻结参数、分组与输入哈希</a></p>'
    prefix = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>上下文轨迹优化报告</title>' + style
    (out / 'InkStruct_上下文轨迹优化报告.html').write_text(prefix + '<body>' + body + '</body></html>')
    (out / 'gallery.html').write_text(prefix + '<body><h1>全部 80 个新验证案例</h1>' + ''.join(gallery) + '</body></html>')


if __name__ == '__main__':
    main()
