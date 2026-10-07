"""Report training-derived layout and calibrated placement with fixed donors."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import numpy as np
from experiment_component_trust import glyph_from_dict, read
from report_terminal_selection import curves
from run_raw_trajectory_experiment import DATABASE, save

from inkstruct.profile import load_profile
from inkstruct.samples import sha256_file
from inkstruct.structures import StructureRepository
from inkstruct.trajectory_experiment import crossing_pairs, curve_error, invariants


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch', type=Path, required=True)
    parser.add_argument('--direct', type=Path, required=True)
    parser.add_argument('--development', type=Path, required=True)
    parser.add_argument('--regression', type=Path, required=True)
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
    batch = read(args.batch / 'plan.json')
    sources = load_profile(Path(batch['profile'])).source_trajectories
    repository = StructureRepository(DATABASE)
    choice = read(args.development / 'frozen_choice.json')
    assert choice['label'] == 'M_D_1.0', 'revise narrative for a different development choice'
    calibration = read(args.development / 'training_calibration.json')
    assert sha256_file(args.development / 'training_calibration.json') == sha256_file(args.regression / 'training_calibration.json')
    assert all(batch['split'][c] == 'train' for c in calibration['character_scores'])
    assert calibration['radius'] == float(np.quantile(list(calibration['character_scores'].values()), .9, method='higher'))
    audit = {'outputs': 0, 'source_points': 0, 'reference_uses': 0, 'unchanged_selected': {},
             'scope': 'development and observed regression; not fresh validation'}
    for folder in (args.direct, args.development, args.regression):
        protocol = read(folder / 'run_protocol.json')
        for group in ('input_sha256', 'code_sha256'):
            for p, expected in protocol[group].items():
                assert sha256_file(Path(p)) == expected, p
        for path in (folder / 'generated').glob('*.json'):
            row = read(path)
            graph = repository.get(row['task']['character'])
            ids = row['task']['target_stroke_ids']
            indices = [i for i, s in enumerate(graph.strokes) if s.stroke_id in ids]
            cross = crossing_pairs(curves(row['outputs']['A']))
            prediction = row['predictions']['learned']
            for ref in prediction.get('reference_sources', []):
                assert batch['split'][ref['character']] == 'train' and ref['character'] != graph.character
                assert sources[ref['sample_id']].source_sha256 == ref['source_sha256']
                audit['reference_uses'] += 1
            for label, payload in row['outputs'].items():
                assert not invariants(glyph_from_dict(payload), graph)
                assert not crossing_pairs(curves(payload))-cross
                audit['outputs'] += 1
                if label == 'A':
                    continue
                meta = row['metadata'][label]
                original_label = label if label in ('D', 'H') else label.split('_')[1]
                assert (meta['selected'] or {}).get('candidate') == (row['metadata'][original_label]['selected'] or {}).get('candidate')
                if label.endswith('_0.0'):
                    assert payload == row['outputs'][original_label]
                selected = meta['selected']
                if selected is None:
                    continue
                candidate = selected['candidate']
                source = sources[candidate['sample_id']]
                assert source.character != graph.character and batch['split'][source.character] == 'train'
                assert source.source_sha256 == candidate['source_sha256']
                mapping = {s.standard_stroke_id: s for s in source.strokes}
                t = selected['transform']
                assert t['sx'] == t['sy'] and t['sx'] > 0
                for i, sid in zip(indices, candidate['stroke_ids'], strict=True):
                    points, raw = payload['strokes'][i]['points'], mapping[sid]
                    np.testing.assert_allclose([(p['x'], p['y']) for p in points],
                        np.asarray(raw.points)*t['sx']+[t['tx'], t['ty']], atol=1e-12, rtol=0)
                    np.testing.assert_array_equal([p['pressure'] for p in points], raw.pressure)
                    np.testing.assert_allclose(np.diff([p['t_ms'] for p in points]), np.diff(raw.t_ms), atol=1e-8, rtol=0)
                    audit['source_points'] += len(points)
                for i, stroke in enumerate(curves(payload)):
                    if i not in indices:
                        assert stroke == curves(row['outputs'][original_label])[i]
    print('audit', audit['outputs'], flush=True)
    gallery, highlights, changed_table = [], [], []

    def draw(row, scope, direct=False):
        labels = ['reference', 'A', 'D', 'L_D_0.5', 'P_D_0.5'] if direct else ['reference', 'A', 'D', 'B_D_1.0', 'M_D_1.0']
        titles = ['原稿·仅评估', 'A · v4', 'D · 原完整部件'] + (['L · 直接学习布局 0.5', 'P · 公共布局 0.5'] if direct else ['B · 经验范围后学习布局', 'M · 同强度公共布局'])
        reference = min(row['references'], key=lambda r: r['sample_id'])['curves']
        lines = {'reference': reference, **{k: curves(v) for k, v in row['outputs'].items()}}
        ids = row['task']['target_stroke_ids']
        indices = [i for i, s in enumerate(row['outputs']['A']['strokes']) if s['standard_stroke_id'] in ids]
        tested = labels[3] if direct else labels[4]
        index = max(indices, key=lambda i: curve_error(lines[tested][i], lines['D'][i])[1])
        cloud = np.asarray([p for k in labels for p in lines[k][index]])
        center = (cloud.min(0)+cloud.max(0))/2
        span = max(float(np.ptp(cloud, axis=0).max())*1.35, .12)
        fig, axes = plt.subplots(2, 5, figsize=(16, 7.4))
        for col, label in enumerate(labels):
            color = ['#333', '#2874a6', '#14806a', '#ad7734', '#985594'][col]
            for r in range(2):
                ax = axes[r, col]
                for i, points in enumerate(lines[label]):
                    a = np.asarray(points)
                    ax.plot(a[:, 0], a[:, 1], color=color if i in indices else '#bac4ce', lw=1.7 if i == index else 1.)
                    if i == index:
                        ax.scatter(*a[-1], color=color, s=13)
                ax.set_aspect('equal')
                ax.set_xlim((-.02, 1.02) if r == 0 else (center[0]-span/2, center[0]+span/2))
                ax.set_ylim((1.02, -.02) if r == 0 else (center[1]+span/2, center[1]-span/2))
                ax.grid(alpha=.15)
                ax.tick_params(labelsize=7)
            axes[0, col].set_title(titles[col], fontsize=10)
            if label != 'reference':
                m = row['metrics'][label]
                axes[1, col].set_xlabel(f"几何 {m['mean_distance']:.4f}\n末向 {m['terminal_angle_deg']:.2f}°", fontsize=10)
        fig.suptitle(f"{scope} · {row['task']['character']} · 局部 s{index+1}\n相同整字和局部比例；所有输出源点直接绘制；原稿按最小样本 ID 选图，指标按字内原稿平均", fontsize=12)
        fig.tight_layout(rect=(0, 0, 1, .92))
        name = f"figures/{row['task']['id']}-{'direct' if direct else 'calibrated'}.png"
        fig.savefig(args.output / name, dpi=140)
        plt.close(fig)
        return name

    direct_rows = [read(p) for p in (args.direct / 'cases').glob('*.json')]
    ordered = sorted(direct_rows, key=lambda r: r['metrics']['L_D_0.5']['mean_distance']-r['metrics']['D']['mean_distance'])
    for row, name in [(ordered[0], '直接布局：改善最多'), (ordered[-1], '直接布局：退化最多')]:
        figure = draw(row, name, direct=True)
        highlights.append(f'<h3>{name} · {row["task"]["character"]}</h3><img src="{figure}">')
    for scope, folder in [('开发', args.development), ('已观察回归', args.regression)]:
        rows = [read(p) for p in sorted((folder / 'cases').glob('*.json'))]
        audit['unchanged_selected'][scope] = sum(r['outputs']['D'] == r['outputs']['M_D_1.0'] for r in rows)
        for row in rows:
            figure = draw(row, scope)
            gallery.append(f'<details><summary>{scope} · {row["task"]["character"]}</summary><img loading="lazy" src="{figure}"></details>')
            if row['outputs']['D'] != row['outputs']['M_D_1.0']:
                highlights.append(f'<h3>{scope} · {row["task"]["character"]}</h3><img src="{figure}">')
                d, m = row['metrics']['D'], row['metrics']['M_D_1.0']
                strength = row['metadata']['B_D_1.0']['layout_band']['effective_strength']
                changed_table.append(f'<tr><td>{scope}</td><td>{row["task"]["character"]}</td><td>{strength:.4f}</td><td>{(m["mean_distance"]/d["mean_distance"]-1)*100:+.2f}%</td><td>{m["terminal_angle_deg"]-d["terminal_angle_deg"]:+.3f}°</td></tr>')
        print(scope, 'figures', len(rows), flush=True)
    save(args.output / 'integrity_audit.json', audit)
    style = '<style>body{max-width:1370px;margin:32px auto;padding:0 24px;background:#f7f9fb;color:#263c50;font:16px/1.8 system-ui}img{width:100%}table{width:100%;border-collapse:collapse;background:white}th,td{padding:8px;border-bottom:1px solid #ddd;text-align:left}details{padding:14px;margin:12px 0;background:white}a{color:#126a99}.finding{padding:18px;background:#e9f2ee}</style>'
    prefix = '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>InkStruct 训练布局与经验范围实验</title>'+style
    text = '<h1>训练原稿布局与经验范围控制</h1><p>2026-10-07 · 固定完整供体、共同等比变换 · 已观察数据回归，不宣称新泛化 · 默认不变</p>'
    text += '<p class="finding"><strong>小范围有效。</strong>冻结方案为 M_D_1.0：训练原稿判断原布局是否明显偏离经验范围，若偏离，再按相应小强度向公共布局调整。开发仅移动“冗”，几何均差下降 1.77%；42 字已观察回归仅移动“禾、火、四”，几何均差下降 1.08%，其余 39 字全字段保持 D。效果集中于 4 字，不能外推为普遍布局改善。</p>'
    text += '<h2>先观察无条件布局的收益与代价</h2><p>从训练原稿学习部件中心相对公共中心的偏移、最大边长比例。公共完整字与原稿均在 0.85 最大跨度框架中比较，保留全部源点。相同部件参考不足时，按相同角色和父布局检索，公共位置、宽高及笔数决定最近 8 个不同字；至少 4 字，先重复采样字内中位数、再跨字中位数。目标字全组排除。</p><p>36 个有预测的开发字中，学习布局的中心误差比公共布局低约 6.15%，对数尺度误差低约 21.68%。半强度直接应用 L_D_0.5，平均轨迹偏差下降约 11.79%，但最差字“恨”几何偏差增加 40.26%，未通过局部门槛。不能只报告平均改善。</p>'
    text += '<h2>训练字留一估计变化范围</h2><p>在训练组内部逐字留出，预测时排除该字全部重复记录。以中心/对数尺度残差的中位绝对偏差衡量分散程度，保留最低尺度 0.01、0.01、0.05。重复先按部件平均秩位置（中位数），再用字内最大部件分数代表该字；129 字的经验 90% 上分位给出半径 5.730659。这是训练经验范围，不是新字的 90% 覆盖保证或自然概率。</p><p>原位置在范围内就不动；范围外只朝边界移动一部分。B 朝学习中心移动；M 在同样有效强度下朝公共布局移动。M 仍用训练资料决定是否移动和移动幅度，因此不是完全无学习的对照，也不保证最终位置落入该经验范围。每组所有笔画共享一个正等比缩放和平移；压力及笔内时间保留，跨笔时间重新安排。候选字、实例和笔顺均固定。</p>'
    text += '<h2>冻结选择与结果</h2><p>开发比较标称强度 0、0.1、0.25、0.5、1，要求整体几何改善、平均末向至多 +0.5°、每字几何至多 +5%、每笔局部最大偏差至多 +0.005、来源启用数不减少。最佳为 M_D_1.0；标称 1 不代表全量移动，4 个改动字的实际强度约 0.19–0.32。</p><table><tr><th>集合</th><th>路径</th><th>几何均差</th><th>末向均差</th><th>最差字几何倍率</th><th>最差笔局部误差增加</th><th>移动字数</th></tr>'
    for scope, folder in [('开发 41 字', args.development), ('已观察回归 42 字', args.regression)]:
        summary = read(folder / 'summary.json')
        for label in ('A', 'D', 'H', 'B_D_1.0', 'M_D_1.0'):
            m = summary[label]
            ratio = f'{m["maximum_character_geometry_ratio"]:.4f}' if 'maximum_character_geometry_ratio' in m else '—'
            increase = f'{m["maximum_stroke_local_error_increase"]:.6f}' if 'maximum_stroke_local_error_increase' in m else '—'
            text += f'<tr><td>{scope}</td><td>{label}</td><td>{m["mean_distance"]:.6f}</td><td>{m["terminal_angle_deg"]:.3f}°</td><td>{ratio}</td><td>{increase}</td><td>{m.get("layout_applied", "—")}</td></tr>'
    text += '</table><p>冻结 M 在回归的平均末向增加约 0.026°，逐笔最坏局部误差增加 0.002145；没有字内平均几何退化。B 的最坏逐笔增量 0.00665 超出门槛，不能把所有学习中心方案一起称为通过。H 的原有局部退化仍存在，未与 M 组合进入正式路径。</p><table><tr><th>集合</th><th>字</th><th>实际强度</th><th>几何变化</th><th>末向变化</th></tr>'+''.join(changed_table)+'</table>'
    text += '<h2>同尺度图文：收益与退化都保留</h2>'+''.join(highlights)
    text += '<h2>数据、完整性与结论范围</h2><p>仍是 user_001 归档批次，物理作者身份未确认。训练仅使用原训练组；开发 41 字 / 47 原稿、回归 42 字 / 60 原稿按字内采样平均，不把重复算独立目标。所有输出先固定，再读取目标原稿评分；两阶段校准文件逐字节一致。数据已观察，不是新留出。公共布局和供体也可能来自相同训练库，预测不是独立自然性证据。</p>'
    text += f'<p>{audit["outputs"]} 个输出和 {audit["source_points"]:,} 个重复使用源点通过标准 ID、笔数/顺序、有限坐标、范围、压力、全局单调时间以及共同变换逐点核验；{audit["reference_uses"]:,} 次布局参考使用均来自训练组且排除目标字。无相对 A 新增严格笔间交叉。零强度全字段不变，部件外坐标不变。检查不覆盖笔宽接触和自交；弧长接近不单独代表好，未新增人工短钩标注。</p>'
    text += '<p><strong>决策：</strong>保留此可关闭实验路径，暂不替换平滑默认或加入正式 CLI/Mac 入口。下一步应跨已有作者做明确标为回归的适用范围检查，并寻求未观察资料及人工比较；目前只能支持少数极端布局的保守修正，不能宣称学习布局全面优于公共结构。</p><p><a href="gallery.html">全部 83 字同尺度对照</a> · <a href="integrity_audit.json">源点与来源审计</a></p>'
    (args.output / 'InkStruct_训练布局与经验范围实验报告.html').write_text(prefix+text)
    (args.output / 'gallery.html').write_text(prefix+'<h1>开发与已观察回归图集</h1>'+''.join(gallery))
    print(json.dumps(audit), flush=True)
    print(args.output / 'InkStruct_训练布局与经验范围实验报告.html')


if __name__ == '__main__':
    main()
