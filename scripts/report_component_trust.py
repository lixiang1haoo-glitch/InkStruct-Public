"""Render the negative local-trust experiment and audit all retained source points."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import numpy as np
from experiment_component_trust import glyph_from_dict
from report_terminal_selection import curves
from run_raw_trajectory_experiment import DATABASE, save

from inkstruct.component_trust import correspondence_bound
from inkstruct.profile import load_profile
from inkstruct.samples import sha256_file
from inkstruct.structures import StructureRepository
from inkstruct.trajectory_experiment import crossing_pairs, invariants, stroke_metrics


def read(path):
    return json.loads(path.read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch', type=Path, required=True)
    parser.add_argument('--radius-development', type=Path, required=True)
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
    assert sha256_file(Path(batch['profile'])) == batch['profile_sha256']
    sources = load_profile(Path(batch['profile'])).source_trajectories
    repository = StructureRepository(DATABASE)
    for folder in [args.radius_development, args.development, args.regression]:
        protocol = read(folder / 'run_protocol.json')
        for group in ('input_sha256', 'code_sha256'):
            for path, expected in protocol[group].items():
                assert sha256_file(Path(path)) == expected, path
    choice = read(args.development / 'frozen_choice.json')
    assert choice['radius'] == 0., 'update narrative if development outcome differs'
    audit = {'outputs': 0, 'source_points': 0, 'bounded_strokes': 0, 'fixed_donor_translation_strokes': 0,
             'maximum_bound_excess': 0., 'scope': 'development plus previously observed regression only'}
    gallery, highlights, row_cache = [], [], {}

    def draw(row, folder, scope, variant='R_0.0'):
        labels = ['reference', 'A', 'D', 'H', 'P', variant]
        reference = min(row['references'], key=lambda r: r['sample_id'])['curves']
        lines = {'reference': reference, **{k: curves(v) for k, v in row['outputs'].items()}}
        indices = [i for i, s in enumerate(row['outputs']['A']['strokes']) if s['standard_stroke_id'] in row['task']['target_stroke_ids']]
        index = max(indices, key=lambda i: (stroke_metrics(lines['P'][i], reference[i])['max_distance']-
                                            stroke_metrics(lines['D'][i], reference[i])['max_distance']))
        cloud = np.asarray([p for k in labels for p in lines[k][index]])
        center = (cloud.min(0)+cloud.max(0))/2
        span = max(float(np.ptp(cloud, axis=0).max())*1.35, .12)
        fig, axes = plt.subplots(2, 6, figsize=(19, 7.4))
        for col, label in enumerate(labels):
            color = ['#333', '#2574a8', '#14816c', '#a05a92', '#b98032', '#525da3'][col]
            for r in range(2):
                ax = axes[r, col]
                for i, points in enumerate(lines[label]):
                    a = np.asarray(points)
                    ax.plot(a[:, 0], a[:, 1], color=color if i in indices else '#bcc5ce', lw=1.8 if i == index else 1.)
                    if i == index:
                        ax.scatter(*a[-1], color=color, s=13)
                ax.set_aspect('equal')
                ax.set_xlim((-.02, 1.02) if r == 0 else (center[0]-span/2, center[0]+span/2))
                ax.set_ylim((1.02, -.02) if r == 0 else (center[1]+span/2, center[1]-span/2))
                ax.grid(alpha=.15)
                ax.tick_params(labelsize=7)
            axes[0, col].set_title(['原稿·仅评估', 'A · v4', 'D · 原完整部件', 'H · 分层方向', 'P · H 同供体平移', variant+' · 受限选择'][col], fontsize=10)
            if label != 'reference':
                m = row['metrics'][label]
                axes[1, col].set_xlabel(f"几何 {m['mean_distance']:.4f}\n末向 {m['terminal_angle_deg']:.2f}°", fontsize=10)
        fig.suptitle(f"{scope} · {row['task']['character']} · 局部 s{index+1}\n相同整字/局部比例；源顶点直接绘制；原稿按最小样本 ID 展示，指标按全部有效采样平均", fontsize=12)
        fig.tight_layout(rect=(0, 0, 1, .92))
        name = f"figures/{row['task']['id']}-{variant}.png"
        fig.savefig(args.output / name, dpi=135)
        plt.close(fig)
        return name

    for scope, folder in [('开发', args.development), ('已观察回归', args.regression)]:
        for path in (folder / 'generated').glob('*.json'):
            row = read(path)
            graph = repository.get(row['task']['character'])
            ids = row['task']['target_stroke_ids']
            indices = [i for i, s in enumerate(graph.strokes) if s.stroke_id in ids]
            baseline_crossings = crossing_pairs(curves(row['outputs']['A']))
            assert row['outputs']['R_0.0'] == row['outputs']['D']
            for label, payload in row['outputs'].items():
                assert not invariants(glyph_from_dict(payload), graph)
                assert not crossing_pairs(curves(payload))-baseline_crossings
                audit['outputs'] += 1
                if label == 'A':
                    continue
                record = row['metadata'][label]['selected']
                if record is not None:
                    source = sources[record['candidate']['sample_id']]
                    assert source.character != graph.character and batch['split'][source.character] == 'train'
                    assert source.source_sha256 == record['candidate']['source_sha256']
                    mapping = {s.standard_stroke_id: s for s in source.strokes}
                    t = record['transform']
                    assert t['sx'] == t['sy'] and t['sx'] > 0
                    for i, sid in zip(indices, record['candidate']['stroke_ids'], strict=True):
                        points, original = payload['strokes'][i]['points'], mapping[sid]
                        np.testing.assert_allclose([(p['x'], p['y']) for p in points],
                            np.asarray(original.points)*t['sx']+[t['tx'], t['ty']], rtol=0, atol=1e-12)
                        np.testing.assert_array_equal([p['pressure'] for p in points], original.pressure)
                        np.testing.assert_allclose(np.diff([p['t_ms'] for p in points]), np.diff(original.t_ms), rtol=0, atol=1e-8)
                        audit['source_points'] += len(points)
                if label.startswith(('T_', 'R_')):
                    radius = float(label.split('_')[1])
                    for i in indices:
                        bound = correspondence_bound(curves(row['outputs']['D'])[i], curves(payload)[i])['maximum']
                        assert bound <= radius+1e-12
                        audit['bounded_strokes'] += 1
                        audit['maximum_bound_excess'] = max(audit['maximum_bound_excess'], bound-radius)
            h, p = row['metadata']['H']['selected'], row['metadata']['P']['selected']
            assert (h or {}).get('candidate') == (p or {}).get('candidate')
            if h is not None:
                delta = np.array([p['transform']['tx']-h['transform']['tx'], p['transform']['ty']-h['transform']['ty']])
                for i in indices:
                    a, b = np.asarray(curves(row['outputs']['H'])[i]), np.asarray(curves(row['outputs']['P'])[i])
                    np.testing.assert_allclose(b-a, np.broadcast_to(delta, b.shape), atol=1e-12, rtol=0)
                    audit['fixed_donor_translation_strokes'] += 1
        rows = [read(p) for p in sorted((folder / 'cases').glob('*.json'))]
        row_cache[scope] = rows
        worst = max(rows, key=lambda r: r['metrics']['P']['mean_distance']-r['metrics']['D']['mean_distance'])
        for row in rows:
            name = draw(row, folder, scope)
            gallery.append(f'<details><summary>{scope} · {row["task"]["character"]}</summary><img loading="lazy" src="{name}"></details>')
            if row['task']['id'] == worst['task']['id'] or (scope == '开发' and row['task']['character'] in '吗茶'):
                highlights.append(f'<h3>{scope} · {row["task"]["character"]}</h3><img src="{name}">')
                if scope == '开发':
                    name = draw(row, folder, scope+' · 未获准参数诊断', variant='R_0.05')
                    highlights.append(f'<p>下图 R_0.05 仅为失败参数诊断，不是冻结选择。</p><img src="{name}">')
        print(scope, 'figures', len(rows), flush=True)
    save(args.output / 'integrity_audit.json', audit)
    css = '<style>body{max-width:1450px;margin:30px auto;padding:0 24px;background:#f7f9fb;color:#263d50;font:16px/1.8 system-ui}img{width:100%}table{width:100%;border-collapse:collapse;background:white}th,td{padding:8px;border-bottom:1px solid #ddd;text-align:left}details{padding:16px;background:white;margin:12px 0}a{color:#126a99}.finding{padding:18px;background:#fff0df}</style>'
    prefix = '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>InkStruct 局部约束与共同平移实验</title>'+css
    text = '<h1>局部偏移约束与整部件共同平移</h1><p>2026-10-07 · 开发及已观察数据回归 · 无新增独立泛化声明 · 默认生成器不变</p>'
    text += '<p class="finding"><strong>两个方案均未通过开发门槛。</strong>简单半径约束能限制变化，却无法同时保住方向收益与所有逐笔质量门槛。再用共同平移最小化相对 D 的最大偏移，也未解决实际原稿偏差。两次冻结均为半径 0，即精确保留 D；不放宽门槛、不按已知失败字定特例。</p>'
    text += '<h2>连续几何边界，而非少数采样点</h2><p>将每笔新旧折线按归一化弧长对应，合并两条折线全部顶点所在的弧长比例。相邻比例之间的差向量是线性的，欧氏长度是凸函数，最大值位于边界；因此可在这些比例处算出整条笔画对应偏移的最大值，包含端点、短钩和稀疏折角。匹配点只用于审计，不写回输出。</p><p>该最大值同时给出两条笔画 Hausdorff 距离的上界；相对未知原稿的 Hausdorff 误差变化也不超过它。它<strong>不保证</strong>平均距离、末向、自然程度或压力更好，D 本身不是原稿。浮点核验容差为 1e-12。</p>'
    text += '<h2>控制组与开发选择</h2><p>A 固定 v4；D 原完整部件；H 为上一轮冻结 0.04 的分层方向评分；T 在原候选位置施加每笔半径；P 固定 H 供体，仅加一个共同平移；R 在共同平移后的完整候选池内按同一半径重选。H→P 区分放置贡献，T→R 包含放置和候选重选贡献。所有源顶点、压力和笔内时间保留，输出仍共享一个正等比变换，按输出笔顺重排时间。</p>'
    text += '<p>共同平移将所有笔画对应差向量作为点集，求最小覆盖圆的中心并反向平移整部件。用凸包上一至三点确定候选圆；凸包超过 64 点或新位置不通过越界/交叉检查则保留原位置。不旋转、不逐笔移动、不混搭。对 A 的匹配分数重新计算，方向评分不因平移改变。</p>'
    text += '<p>预设半径 0、0.005、0.01、0.02、0.03、0.05、0.08，单位为统一画布。开发选择要求总体几何至多 +1%、每字几何至多 +5%、每笔局部最大误差（先平均同字采样）增加不超过 0.005、启用数相同，并严格改善末向。T 的 0.03/0.05 保留“吗”，但局部最大误差 +0.00582 越限；较大半径放入“茶”的明显退化。R 的共同平移未改善这一取舍。</p>'
    text += '<h2>分层开发：全部参数</h2><table><tr><th>路径</th><th>几何均差</th><th>末向均差</th><th>最差字几何倍率</th><th>最差笔局部误差增加</th><th>改选数</th></tr>'
    for label, m in read(args.development / 'summary.json').items():
        text += f'<tr><td>{label}</td><td>{m["mean_distance"]:.6f}</td><td>{m["terminal_angle_deg"]:.2f}°</td><td>{m.get("maximum_character_geometry_ratio", 0):.4f}</td><td>{m.get("maximum_stroke_local_error_increase", 0):.6f}</td><td>{m.get("changed_from_D", "—")}</td></tr>'
    text += '</table><h2>已观察数据回归：不是新留出</h2><table><tr><th>路径</th><th>几何均差</th><th>末向均差</th><th>最差字几何倍率</th><th>最差笔局部误差增加</th></tr>'
    for label, m in read(args.regression / 'summary.json').items():
        text += f'<tr><td>{label}</td><td>{m["mean_distance"]:.6f}</td><td>{m["terminal_angle_deg"]:.2f}°</td><td>{m.get("maximum_character_geometry_ratio", 0):.4f}</td><td>{m.get("maximum_stroke_local_error_increase", 0):.6f}</td></tr>'
    text += '</table><p>R_0 与 D 全字段一致，是负结果的正确回退，不是算法质量提升。P 仅解释共同平移的效果，未获准部署。41 开发字 / 47 原稿、42 回归字 / 60 原稿沿用固定训练来源；目标原稿只在所有输出固定后读取评分。user_001 的物理作者身份仍未确认。</p>'
    text += '<h2>失败与回退案例</h2>'+''.join(highlights)
    text += f'<h2>完整性</h2><p>本报告核验 {audit["outputs"]} 个输出、{audit["source_points"]:,} 个重复使用的源点、{audit["bounded_strokes"]:,} 次逐笔连续边界及 {audit["fixed_donor_translation_strokes"]} 次固定供体共同平移。全部通过标准 ID、笔数/顺序、有限坐标、范围、压力、全局单调时间和相对 A 无新增严格笔间交叉检查。最大边界超限为 {audit["maximum_bound_excess"]}。这些不是独立样本数；交叉检查不涵盖笔宽接触和自交。</p>'
    text += '<p>原始轨迹保真、相对旧结果偏移小、贴近作者原稿是三个不同目标。本次已经实现可验证的连续偏移边界，但未证明质量约束与末向收益可兼得，因此保留实验代码和负结果，不接入正式路径。下一步需改善目标布局或候选适配证据，而不是持续靠拉回 D 或放宽门槛。</p><p><a href="gallery.html">全部 83 字同尺度图集</a> · <a href="integrity_audit.json">完整性核验</a></p>'
    (args.output / 'InkStruct_局部约束与共同平移实验报告.html').write_text(prefix+text)
    (args.output / 'gallery.html').write_text(prefix+'<h1>开发与已观察回归图集</h1>'+''.join(gallery))
    print(json.dumps(audit), flush=True)
    print(args.output / 'InkStruct_局部约束与共同平移实验报告.html')


if __name__ == '__main__':
    main()
