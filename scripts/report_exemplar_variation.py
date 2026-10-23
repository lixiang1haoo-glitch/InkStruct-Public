"""Private figure report and source-point audit for frozen exemplar variation."""
from __future__ import annotations

import argparse
import html
import json
import os
from pathlib import Path

import numpy as np
from experiment_exemplar_variation import read, verify
from run_raw_trajectory_experiment import save

from inkstruct.component_variation_evidence import normalized_component
from inkstruct.geometry import path_length
from inkstruct.profile import load_profile
from inkstruct.terminal_selection import terminal_vector
from inkstruct.trajectory_experiment import stroke_metrics


def curves(glyph):
    return [[(p['x'], p['y']) for p in s['points']] for s in glyph['strokes']]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--development', type=Path, required=True)
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
    plan = read(args.input / 'frozen_plan.json')
    verify(plan)
    summary = read(args.input / 'summary.json')
    development = read(args.development / 'summary.json')
    sources = load_profile(Path(plan['sources'])).source_trajectories
    rows = [read(p) for p in sorted((args.input / 'cases').glob('*.json'))]
    audit = {'cases': len(rows), 'outputs': 0, 'verified_full_source_points': 0,
             'generated_evidence_in_range': 0, 'distinct_shapes_per_character': {}, 'family_counts': {}}
    labels = ['reference', 'A', 'D', 'V1', 'V2', 'V3', 'V4', 'V5']
    titles = {'reference': '原稿·仅评估', 'A': 'A · v4 adaptive', 'D': 'D · 确定性完整轨迹',
              **{f'V{i+1}': f'V{i+1} · 实例变化' for i in range(5)}}
    gallery, figures = [], {}
    for row in rows:
        ids = row['task']['target_stroke_ids']
        indices = [i for i, s in enumerate(row['variants']['A']['strokes']) if s['standard_stroke_id'] in ids]
        family = row['task']['context']
        family_display = family.replace('⿰', '左右')
        audit['family_counts'][family] = audit['family_counts'].get(family, 0)+1
        for label, meta in row['provenance'].items():
            record = meta['selected']
            if record is None:
                continue
            sample = sources[record['candidate']['sample_id']]
            assert sample.character != row['task']['character']
            assert sample.source_sha256 == record['candidate']['source_sha256']
            mapping = {s.standard_stroke_id: s for s in sample.strokes}
            matrix = record['transform']
            assert matrix['sx'] == matrix['sy'] and matrix['sx'] > 0
            for i, sid in zip(indices, record['candidate']['stroke_ids'], strict=True):
                output = row['variants'][label]['strokes'][i]['points']
                source = mapping[sid]
                expected = np.asarray(source.points)*matrix['sx'] + [matrix['tx'], matrix['ty']]
                np.testing.assert_allclose([(p['x'], p['y']) for p in output], expected, atol=1e-12, rtol=0.)
                np.testing.assert_allclose([p['pressure'] for p in output], source.pressure, atol=0, rtol=0)
                np.testing.assert_allclose(np.diff([p['t_ms'] for p in output]), np.diff(source.t_ms), atol=1e-8, rtol=0)
                audit['verified_full_source_points'] += len(output)
            if label.startswith('V'):
                audit['generated_evidence_in_range'] += bool(record['component_evidence'].get('within_empirical_range'))
        for check in row['checks'].values():
            assert not check['invariants'] and not check['new_crossings_vs_A']
            audit['outputs'] += 1
        audit['distinct_shapes_per_character'][row['task']['character']] = len({
            row['provenance'][f'V{i+1}']['variation'].get('selected_geometry_id') for i in range(5)})
        lines = {'reference': row['reference'], **{k: curves(v) for k, v in row['variants'].items()}}
        # Diagnostic only: choose the stroke with the largest terminal mismatch change.
        chosen = max(indices, key=lambda i: max(abs((stroke_metrics(lines[k][i], lines['reference'][i])['terminal_angle_deg'] or 0.)
                    -(stroke_metrics(lines['D'][i], lines['reference'][i])['terminal_angle_deg'] or 0.)) for k in labels[3:]))
        cloud = np.asarray([p for label in labels for p in lines[label][chosen]])
        center = (cloud.min(0)+cloud.max(0))/2
        span = max(float(np.ptp(cloud, axis=0).max())*1.4, .12)
        fig, axes = plt.subplots(2, 8, figsize=(22, 8.2))
        for col, label in enumerate(labels):
            color = '#333333' if label == 'reference' else '#286f9e' if label == 'A' else '#157862' if label == 'D' else '#a24f84'
            for r in range(2):
                ax = axes[r, col]
                for i, stroke in enumerate(lines[label]):
                    a = np.asarray(stroke)
                    ax.plot(a[:, 0], a[:, 1], color=color if i in indices else '#bac3cc', lw=1.6 if i == chosen else 1.)
                    if i == chosen:
                        ax.scatter(*a[-1], color=color, s=12)
                        if r == 1:
                            vector = terminal_vector(stroke, min(.02, .15*path_length(lines['reference'][i])))
                            if vector is not None:
                                ax.annotate('', xy=a[-1]+vector*span*.12, xytext=a[-1], arrowprops={'arrowstyle': '->', 'color': color})
                ax.set_aspect('equal')
                ax.set_xlim((-.02, 1.02) if r == 0 else (center[0]-span/2, center[0]+span/2))
                ax.set_ylim((1.02, -.02) if r == 0 else (center[1]+span/2, center[1]-span/2))
                ax.grid(alpha=.12)
                ax.tick_params(labelsize=6)
            donor = '' if label in ('reference', 'A') else '\n供体：'+row['provenance'][label]['selected']['candidate']['character']
            axes[0, col].set_title(titles[label]+donor, fontsize=10)
            if label != 'reference':
                metrics = row['metrics'][label]
                axes[1, col].set_xlabel(f"几何 {metrics['mean_distance']:.4f}\n末向 {metrics['terminal_angle_deg']:.1f}°", fontsize=9)
        fig.suptitle(f"wsq · {row['task']['character']} · {family_display} · 下排统一放大 s{chosen+1}\n完整顶点直接绘制；圆点为末端，箭头为统一评估窗口方向", fontsize=12)
        fig.tight_layout(rect=(0, .035, 1, .9))
        fig.subplots_adjust(hspace=.30)
        filename = f"figures/{row['task']['id']}.png"
        fig.savefig(args.output / filename, dpi=135)
        plt.close(fig)
        figures[row['task']['character']] = filename
        gallery.append(f'<details><summary>{row["task"]["character"]} · {html.escape(family)} · 5 次输出有 {audit["distinct_shapes_per_character"][row["task"]["character"]]} 种形状</summary><img src="{filename}" loading="lazy"><a href="../cases/{row["task"]["id"]}.json">全部坐标、供体、变换及哈希</a></details>')
    # One panel per family: source exemplars, held-out actual, A/D and five draws.
    cohorts = []
    for family in sorted(audit['family_counts']):
        row = next(r for r in rows if r['task']['context'] == family)
        ids = row['task']['target_stroke_ids']
        indices = [i for i, s in enumerate(row['variants']['A']['strokes']) if s['standard_stroke_id'] in ids]
        seen, entries = set(), []
        for record in row['pool']:
            donor = record['candidate']
            if donor['character'] in seen:
                continue
            seen.add(donor['character'])
            mapping = {s.standard_stroke_id: s.points for s in sources[donor['sample_id']].strokes}
            entries.append((f"训练原稿 · {donor['character']}", [mapping[sid] for sid in donor['stroke_ids']], '#667782'))
            if len(entries) == 8:
                break
        entries += [('留出原稿 · '+row['task']['character'], [row['reference'][i] for i in indices], '#242b36')]
        entries += [(label+' · '+row['task']['character'], [curves(row['variants'][label])[i] for i in indices],
                    '#287392' if label in ('A', 'D') else '#a24f84') for label in labels[1:]]
        fig, axes = plt.subplots(4, 4, figsize=(11, 10))
        for ax in axes.flat:
            ax.axis('off')
        for ax, (title, strokes, color) in zip(axes.flat, entries):
            for stroke in normalized_component(strokes):
                a = np.asarray(stroke)
                ax.plot(a[:, 0], a[:, 1], color=color, lw=1.5)
                ax.scatter(*a[-1], color=color, s=8)
            ax.set_xlim(-.58, .58)
            ax.set_ylim(.58, -.58)
            ax.set_aspect('equal')
            ax.set_title(title, fontsize=10)
        fig.suptitle(f'{family.replace(chr(0x2ff0), "左右")}\n各部件仅整体平移、等比归一化；训练示例按候选排序取前 8 个不同字，非全部参考分布', fontsize=12)
        fig.tight_layout(rect=(0, 0, 1, .94))
        filename = f'figures/cohort-{len(cohorts)+1}.png'
        fig.savefig(args.output / filename, dpi=135)
        plt.close(fig)
        cohorts.append((family, filename, row['task']['character']))
    save(args.output / 'integrity_audit.json', audit)
    styles = '<style>body{max-width:1450px;margin:32px auto;padding:0 28px;font:16px/1.8 system-ui;color:#263b50;background:#f5f7fa}img{width:100%;background:white}table{border-collapse:collapse;width:100%;background:white}td,th{padding:10px;border-bottom:1px solid #ddd;text-align:left}details{background:white;margin:12px 0;padding:16px}.finding{background:#fff0df;padding:20px}a{color:#096ba0}</style>'
    prefix = '<!doctype html><meta charset="utf-8"><title>InkStruct 跨字同部件变化验证</title>'+styles
    text = '<h1>用不同字的相同部件，检验变化是否自然</h1><p>2026-10-07 · 同作者、同部件形态和位置 · 保留完整源点 · 参数先冻结再验证</p>'
    text += '<p class="finding"><strong>结论：</strong>跨字原稿足以建立部件形状的经验参考范围；但落在该范围内，不等于适合目标字。本轮 28 个 wsq 留出字全部产生了可复现变化，26/28 的真实留出部件也落在参考范围内。尽管如此，随机实例路径相对确定性完整轨迹的期望几何偏差增加 2.16%、末向误差增加 2.89°，没有通过开发时设定的质量门槛。因此只保留可关闭的实验实现，不接入生产默认。</p>'
    text += '<h2>如何排除“复制自己的分数最好”</h2><p>按作者、部件、变体、位置、父结构和笔数分组，整部件共同平移与等比归一化，不逐笔拉伸。形状描述由等弧长匹配锚点、相对弧长和两档末向构成；锚点仅供比较，输出始终保留全部源点。参考组只用训练字；目标字在计数、去重、阈值拟合之前排除；生成实例评分进一步排除整个供体字和相同轨迹副本。</p><p>至少 8 个不同来源字才建立参考范围。每个训练字留出后计算到其余字的最近形状距离，多次采样先按字汇总，再取 95% 经验分位数。这是几何相容性代理，不是“95% 自然概率”。原稿噪声、左右邻接、上下文压缩和视觉审美仍可能未被模型覆盖。</p>'
    text += '<h2>开发与确认严格分开</h2><p>scx 32 字开发，只有 10 字拥有足够参考；范围预设为 0、0.0025、0.005、0.01。选择规则：相对 D，期望几何均差不增加超过 1%，末向不增加超过 0.5°，取最大的通过范围。冻结为 0.01。确认使用 wsq 前轮 64 字之外剩余的 28 个相容留出字；同字全部采样同组，候选和原 A 档案仅来自训练组。wsq 已在之前实验中出现，不能称作全新作者验证。</p><p>D 是完整原始部件以一个共同等比变换拟合固定 A 布局的确定性结果；V 保持相同表示、布局目标、前 16 个候选及安全约束，只改变近优候选的选择。每个候选都重新拟合自己的共同变换，因此候选形状和放置参数一起改变；这里不能把收益归因于轨迹表示。A 与 D 的表示、供体策略均不同，早先 A/B/C 匹配实验另见原报告。</p>'
    text += '<table><tr><th>集合</th><th>路径</th><th>几何均差</th><th>末向均差</th><th>弧长绝对相对差</th></tr>'
    for group, data in [('scx 开发，32 字', development), ('wsq 确认，28 字', summary)]:
        for label, values in [('A', data['metrics']['A']), ('D', data['metrics']['D']), ('V 精确期望', data['expected']['0.01']), ('V 五次实测均值', data['metrics']['V_mean'])]:
            text += f'<tr><td>{group}</td><td>{label}</td><td>{values["mean_distance"]:.6f}</td><td>{values["terminal_angle_deg"]:.2f}°</td><td>{values["absolute_length_error"]:.2%}</td></tr>'
    text += '</table><p>期望按每个候选的实际抽样概率精确求和；5 个种子不是 5 倍独立样本，按字聚合。弧长接近不自动代表质量更高，原稿也可能有噪声。确认的 V 五次均值几何优于 A 约 2.24%，但末向比 A 差约 5.01°，不能只凭几何平均宣布改进。</p>'
    text += '<h2>同部件原稿对齐证据</h2><p>以下各格使用相同归一化尺度，笔画间比例保持。每族展示少量训练原稿与一个留出字的原稿和生成版本；参考阈值使用全部合格训练字，图中 8 例不是参考全集。所有生成实例在范围内属于筛选条件，不能再拿 100% 通过率充当独立验证。</p>'
    for family, filename, character in cohorts:
        text += f'<h3>{html.escape(family)} · 示例 {character}</h3><img src="{filename}" loading="lazy">'
    outside = [r['task']['character'] for r in rows if not r['reference_evidence'].get('within_empirical_range')]
    text += f'<p>真实留出部件落在参考范围内：26/28；超出范围的字为 {"、".join(outside)}。这提示真实书写也有上下文例外，经验范围不能作为硬性“好字/坏字”标签。</p>'
    text += '<h2>整字和局部：变化最大的不利案例与有利案例</h2>'
    ordered = sorted(rows, key=lambda r: np.mean([r['metrics'][f'V{i+1}']['terminal_angle_deg'] for i in range(5)])-r['metrics']['D']['terminal_angle_deg'])
    for title, row in [('末向改善最多', ordered[0]), ('末向退化最多', ordered[-1])]:
        text += f'<h3>{title}：{row["task"]["character"]}</h3><img src="{figures[row["task"]["character"]]}">'
    text += '<p>局部观察：“噢”的 V2/V4 使用“哕”的口旁，保留了其末横回钩；供体原稿中确实存在这个动作，但目标“噢”的该笔末端更接近向右。这说明真实部件本身的自然变化，仍需目标上下文约束。</p>'
    text += f'<h2>完整性与使用边界</h2><p>{audit["outputs"]} 个输出全部通过笔数、标准笔画 ID、笔顺、有限坐标、压力范围、全局单调时间和边界检查。D/V 的 {audit["verified_full_source_points"]:,} 个源点逐项核验，坐标严格来自同一部件共同变换，压力及笔内相对时间保留；输出笔顺重新计时。无相对 A 新增严格笔间交叉。该交叉检查不覆盖笔宽接触与自交，A 原有交叉也不会被自动修复。</p>'
    text += '<p>没有同字重复采样，因此本报告支持“跨字同部件几何相容性”的判断，不支持同字自然重复分布、用户偏好或文字阅读质量的统计结论。28 字集中于高频部件组，不能外推到所有汉字。未观察的目标原稿只进入评分与报告，未进入候选库或阈值拟合。</p><p>直接变换适合形态、位置和笔数相容、可共同放置的完整部件，可保留真实折钩和笔画关系；不适合结构差异大、短笔退化、噪声源稿或必须逐笔扭曲才能匹配的场景。暂不替代现有平滑默认。接入顺序应为：先保留确定性完整轨迹开关及受限简化，记录来源和回退；再用独立开发数据加强上下文与末向条件；新的留出验证通过后，才考虑开放随机变化。不要用这 28 字重新调参数后继续称为留出验证。</p>'
    text += '<p><a href="gallery.html">全部 28 字整字及局部对照图</a> · <a href="../summary.json">汇总指标</a> · <a href="../frozen_plan.json">冻结协议、输入与代码哈希</a> · <a href="integrity_audit.json">逐点完整性核验</a></p>'
    (args.output / 'InkStruct_跨字同部件变化报告.html').write_text(prefix+text)
    (args.output / 'gallery.html').write_text(prefix+'<h1>全部 28 字 · 原稿 / A / D / 五个可复现实例</h1>'+''.join(gallery))
    print(json.dumps(audit, ensure_ascii=False, indent=2), flush=True)
    print(args.output / 'InkStruct_跨字同部件变化报告.html')


if __name__ == '__main__':
    main()
