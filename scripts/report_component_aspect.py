"""Private, reproducible figures and point audit for bounded aspect development."""
from __future__ import annotations

import argparse
import html
import json
import os
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from report_terminal_selection import curves
from run_raw_trajectory_experiment import Experiment, save

from inkstruct.samples import sha256_file
from inkstruct.trajectory_experiment import crossing_pairs, invariants, stroke_metrics


def read(path):
    return json.loads(path.read_text())


def namespace(value):
    if isinstance(value, dict):
        return SimpleNamespace(**{k: namespace(v) for k, v in value.items()})
    return [namespace(v) for v in value] if isinstance(value, list) else value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / 'figures').mkdir()
    os.environ['MPLCONFIGDIR'] = str(args.output / '.mpl')
    os.environ['XDG_CACHE_HOME'] = str(args.output / '.cache')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    font_manager.fontManager.addfont('/System/Library/Fonts/Supplemental/Arial Unicode.ttf')
    plt.rcParams.update({'font.family': 'Arial Unicode MS', 'axes.unicode_minus': False})
    protocol = read(args.input / 'protocol.json')
    for path, expected in protocol['input_hashes'].items():
        assert sha256_file(Path(path)) == expected, path
    choice = read(args.input / 'frozen_choice.json')
    assert sha256_file(args.input / 'summary.json') == choice['summary_sha256']
    assert sha256_file(args.input / 'protocol.json') == choice['protocol_sha256']
    experiment = Experiment(Path('artifacts/raw_trajectory_20261007'))
    summary = read(args.input / 'summary.json')
    rows = [read(p) for p in sorted((args.input / 'cases').glob('*.json'))]
    audit = {'outputs': 0, 'source_points': 0, 'cases': len(rows),
             'unit_cap_exact_D': True, 'unmodified_outside_component': True,
             'scope': 'development; strict interstroke crossings only; no pen-width or self-crossing claim'}
    labels = ['reference', 'A', 'D', 'E_1.1', 'F_1.1']
    titles = ['原稿·仅评估', 'A · v4 adaptive', 'D · 共同等比', 'E · 固定供体 1.1', 'F · 可换供体 1.1']
    figures, gallery = {}, []
    for row in rows:
        graph = experiment.repository.get(row['task']['character'])
        ids = row['task']['target_stroke_ids']
        indices = [i for i, s in enumerate(graph.strokes) if s.stroke_id in ids]
        baseline = curves(row['outputs']['A'])
        base_crossings = crossing_pairs(baseline)
        assert row['outputs']['D'] == row['outputs']['E_1.0'] == row['outputs']['F_1.0']
        for label, payload in row['outputs'].items():
            assert not invariants(namespace(payload), graph)
            assert not crossing_pairs(curves(payload))-base_crossings
            for i, stroke in enumerate(curves(payload)):
                if i not in indices:
                    assert stroke == baseline[i]
            audit['outputs'] += 1
            record = row['provenance'].get(label, {}).get('selected')
            if record is None:
                continue
            donor = record['candidate']
            source = experiment.sources[donor['sample_id']]
            assert source.character != row['task']['character']
            assert source.source_sha256 == donor['source_sha256']
            mapping = {s.standard_stroke_id: s for s in source.strokes}
            t = record['transform']
            cap = 1. if label == 'D' else float(label.split('_')[1])
            assert t['sx'] > 0 and t['sy'] > 0 and 1/cap-1e-12 <= t['sx']/t['sy'] <= cap+1e-12
            for i, sid in zip(indices, donor['stroke_ids'], strict=True):
                points = payload['strokes'][i]['points']
                src = mapping[sid]
                np.testing.assert_allclose([(p['x'], p['y']) for p in points],
                    np.asarray(src.points)*[t['sx'], t['sy']]+[t['tx'], t['ty']], atol=1e-12, rtol=0)
                np.testing.assert_array_equal([p['pressure'] for p in points], src.pressure)
                np.testing.assert_allclose(np.diff([p['t_ms'] for p in points]), np.diff(src.t_ms), atol=1e-8, rtol=0)
                audit['source_points'] += len(points)
        lines = {'reference': row['reference'], **{k: curves(v) for k, v in row['outputs'].items()}}
        # Diagnostic-only selection after generation, never used by candidate selection.
        chosen = max(indices, key=lambda i: abs(
            (stroke_metrics(lines['F_1.1'][i], lines['reference'][i])['terminal_angle_deg'] or 0.)-
            (stroke_metrics(lines['D'][i], lines['reference'][i])['terminal_angle_deg'] or 0.)))
        cloud = np.asarray([p for label in labels for p in lines[label][chosen]])
        center = (cloud.min(0)+cloud.max(0))/2
        span = max(float(np.ptp(cloud, axis=0).max())*1.35, .12)
        fig, axes = plt.subplots(2, 5, figsize=(16, 7.5))
        for col, label in enumerate(labels):
            color = ['#333333', '#2676a8', '#15806c', '#bb7530', '#944f9c'][col]
            for r in range(2):
                ax = axes[r, col]
                for i, points in enumerate(lines[label]):
                    a = np.asarray(points)
                    ax.plot(a[:, 0], a[:, 1], color=color if i in indices else '#bcc4cc', lw=1.7 if i == chosen else 1.)
                    if i == chosen:
                        ax.scatter(*a[-1], color=color, s=12)
                ax.set_aspect('equal')
                ax.set_xlim((-.02, 1.02) if r == 0 else (center[0]-span/2, center[0]+span/2))
                ax.set_ylim((1.02, -.02) if r == 0 else (center[1]+span/2, center[1]-span/2))
                ax.grid(alpha=.15)
                ax.tick_params(labelsize=7)
            axes[0, col].set_title(titles[col], fontsize=11)
            if label != 'reference':
                m = row['metrics'][label]
                selected = row['provenance'].get(label, {}).get('selected')
                donor = selected['candidate']['character'] if selected else '—'
                axes[1, col].set_xlabel(f"供体 {donor}｜几何 {m['mean_distance']:.4f}\n末向 {m['terminal_angle_deg']:.2f}°", fontsize=10)
        fig.suptitle(f"开发集 · {row['task']['character']} · 局部 s{chosen+1}\n相同整字及局部比例；全部输出顶点直接绘制；圆点标记末端", fontsize=13)
        fig.tight_layout(rect=(0, 0, 1, .93))
        name = f"figures/{row['task']['id']}.png"
        fig.savefig(args.output / name, dpi=140)
        plt.close(fig)
        figures[row['task']['id']] = name
        gallery.append(f'<details><summary>{html.escape(row["task"]["character"])}</summary><img loading="lazy" src="{name}"><a href="../cases/{row["task"]["id"]}.json">全部参数档、来源与轨迹</a></details>')
        if len(gallery) % 8 == 0:
            print('figures', len(gallery), flush=True)
    save(args.output / 'integrity_audit.json', audit)
    css = '<style>body{max-width:1350px;margin:32px auto;padding:0 24px;background:#f7f9fb;color:#263a4b;font:16px/1.8 system-ui}img{width:100%}table{border-collapse:collapse;width:100%;background:white}td,th{padding:8px;text-align:left;border-bottom:1px solid #ddd}details{padding:14px;margin:12px 0;background:white}a{color:#126a99}.finding{padding:20px;background:#fff0df}</style>'
    prefix = '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>InkStruct 整部件受限宽高实验</title>'+css
    text = '<h1>完整轨迹：整部件受限宽高实验</h1><p>2026-10-07 · scx 开发集 32 字 · 参数冻结为等比缩放 · 生产默认不变</p>'
    text += '<p class="finding"><strong>未通过开发门槛。</strong>三个宽高上限均未同时改善几何和末端方向。固定供体 E 的结果略变差；可换供体 F 虽多启用 1 字，却增加末向误差。保留负结果，不将该变换推广到正式生成器，也不消耗新的留出数据。</p>'
    text += '<h2>可比较的三条完整部件路径</h2><p>D 使用已有共同等比拟合；E 固定 D 的供体，只允许其等比方案与受限横纵方案竞争；F 在相同前 16 个候选中竞争。所有笔画使用同一正缩放和平移，保留源顶点、压力及笔内时间。A、候选池、目标布局和安全阈值固定。E−D 主要反映放置变化，F−E 包含供体重选贡献。A 与 D 同时改变表示和来源，不能归因为纯表示差异。</p>'
    text += '<p>预设宽高上限为 1、1.1、1.25、1.5；只有 F 的几何均差严格改善、末向不变差且启用数不减少才可选用，否则回到 1。原稿在所有选择完成后才读取评分。16 个锚点仅用于求变换，输出未重新降采样。非等比拟合采用最多 8 次重新匹配，仅接受变换后锚点平方误差下降；不声称全局最优，也不等同于真实作者形状最优。</p>'
    text += '<h2>逐档开发结果</h2><table><tr><th>路径</th><th>几何均差</th><th>最大局部差均值</th><th>末向均差</th><th>弧长相对差</th><th>端点差</th><th>启用/横纵/换供体</th></tr>'
    for label, values in summary.items():
        counts = '/'.join(str(values.get(k, '—')) for k in ('activated', 'bounded_xy', 'different_donor_from_D'))
        text += f'<tr><td>{label}</td><td>{values["mean_distance"]:.6f}</td><td>{values["max_distance"]:.6f}</td><td>{values["terminal_angle_deg"]:.2f}°</td><td>{values["absolute_length_error"]:.2%}</td><td>{values["endpoint_error"]:.6f}</td><td>{counts}</td></tr>'
    text += '</table><p>各字先对所迁移部件的笔画求均值，再对 32 字平均；坐标单位为统一画布。表中 E/F 包括明确保留的等比回退，横纵启用数单列，不与 D 混算。点数不同仍用相同的线段距离积分及末向窗口评估。弧长接近原稿不自动意味着质量更好，原稿也可能有采集噪声。</p>'
    text += '<h2>局部改善与退化都展示</h2><p>图例固定为最小非零上限 1.1，不根据好看程度挑参数；下面按 F−D 的几何变化自动取最好与最差各一例。完整图集含全部 32 字。</p>'
    ordered = sorted(rows, key=lambda r: r['metrics']['F_1.1']['mean_distance']-r['metrics']['D']['mean_distance'])
    for row, label in [(ordered[0], '几何改善最多'), (ordered[-1], '几何退化最多')]:
        text += f'<h3>{label}：{row["task"]["character"]}</h3><img src="{figures[row["task"]["id"]]}">'
    text += '<h2>同部件自然变化的含义</h2><p>不同字中的相同部件可以提供作者形状范围的参考，但上下文、邻笔和位置会影响自然形态。此前独立的 wsq 28 字实验有 26 个真实部件落在经验范围内，完整实例随机变化却使几何偏差增加 2.16%、末向增加 2.89°。这些数值属于此前实验，不能与本轮 32 字合并，也不能当作自然概率。当前结果进一步说明：能贴近 A 的布局锚点，不保证贴近作者目标原稿。</p>'
    text += '<h2>完整性与适用边界</h2>'
    text += f'<p>{audit["outputs"]} 个输出通过笔数、标准 ID、顺序、有限坐标、压力范围、画布范围和全局单调时间检查；{audit["source_points"]:,} 个源点的共同变换、压力与笔内相对时间逐项核对。部件外坐标不变，cap=1 与 D 全字段一致。无相对 A 新增严格笔间交叉；检测不涵盖笔宽接触和自交，亦不承诺清除 A 已有交叉。</p>'
    text += '<p>同字重建中保留折钩是预期效果，不能证明跨字泛化。本轮没有新增同字重建结论，也没有建立短钩语义标注：末向、端点和局部几何仅作代理。完整轨迹适用于来源完整、形态和布局相容的部件；不适用于缺少供体、源稿退化或需逐笔变形才能适配的场景。横纵缩放虽不丢点，却改变转角、方向和宽高关系，因此不能视作无损风格迁移。</p>'
    text += '<p>发现另一个归档数据批次 user_001：385 条记录、294 字，其中 48 字有 2–3 次记录；文件和原始几何未发现精确重复。这里只检查了数据清单与重复关系，物理作者身份尚未确认，不能称为独立新作者。没有用它建目标档案、选参数或计算本轮目标效果。未来如需使用，必须按字符分组后仅用训练组建档，重复样本按字汇总。</p>'
    text += '<p><strong>接入建议：</strong>继续保留默认平滑和可关闭的确定性完整源路径；同字原稿复用单独标识。先改进供体与目标上下文的相容判断，在新的开发数据上定规则，再用未观察字符确认。当前不接入随机实例变化，也不接入本轮横纵缩放。</p>'
    text += '<p><a href="gallery.html">全部 32 字同尺度图集</a> · <a href="../summary.json">全部指标</a> · <a href="../protocol.json">冻结协议和哈希</a> · <a href="../frozen_choice.json">冻结选择</a> · <a href="integrity_audit.json">逐点审计</a></p>'
    (args.output / 'InkStruct_整部件受限宽高实验报告.html').write_text(prefix+text)
    (args.output / 'gallery.html').write_text(prefix+'<h1>32 字开发图集</h1><p>原稿、A、D、E 1.1、F 1.1；所有参数档详见逐例 JSON。</p>'+''.join(gallery))
    print(json.dumps(audit), flush=True)
    print(args.output / 'InkStruct_整部件受限宽高实验报告.html')


if __name__ == '__main__':
    main()
