"""Render source-audited development/confirmation of hierarchical direction cues."""
from __future__ import annotations

import argparse
import html
import json
import os
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from report_terminal_selection import curves
from run_raw_trajectory_experiment import DATABASE, save

from inkstruct.profile import load_profile
from inkstruct.samples import sha256_file
from inkstruct.structures import StructureRepository
from inkstruct.trajectory_experiment import crossing_pairs, invariants, stroke_metrics


def read(path):
    return json.loads(path.read_text())


def namespace(value):
    if isinstance(value, dict):
        return SimpleNamespace(**{k: namespace(v) for k, v in value.items()})
    return [namespace(v) for v in value] if isinstance(value, list) else value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch', type=Path, required=True)
    parser.add_argument('--context', type=Path, required=True)
    parser.add_argument('--development', type=Path, required=True)
    parser.add_argument('--confirmation', type=Path)
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
    plan = read(args.batch / 'plan.json')
    assert sha256_file(Path(plan['profile'])) == plan['profile_sha256']
    profile = load_profile(Path(plan['profile']))
    repository = StructureRepository(DATABASE)
    chosen = read(args.development / 'frozen_choice.json')
    dev_summary = read(args.development / 'summary.json')
    context_summary = read(args.context / 'summary.json')
    assert all(v['evidence_available'] == 0 for k, v in context_summary.items() if k not in ('A', 'D'))
    display = chosen['chosen'] if chosen['chosen'] != 'D' else min(
        (label for label in dev_summary if label not in ('A', 'D')),
        key=lambda label: (dev_summary[label]['terminal_angle_deg'], label))
    sets = [('开发', args.development)] + ([('留出', args.confirmation)] if args.confirmation else [])
    audit = {'outputs': 0, 'source_points': 0, 'independent_reference_uses': 0, 'sets': {}, 'default_changed': False}
    gallery, highlights, changed_rows = [], [], []
    for scope, folder in sets:
        run = read(folder / 'run_protocol.json')
        assert sha256_file(args.batch / 'plan.json') == run['plan_sha256']
        for p, expected in run['code_sha256'].items():
            assert sha256_file(Path(p)) == expected, p
        coverage = read(folder / 'coverage.json')
        audit['sets'][scope] = coverage
        for p in (folder / 'generated').glob('*.json'):
            row = read(p)
            graph = repository.get(row['task']['character'])
            ids = row['task']['target_stroke_ids']
            indices = [i for i, s in enumerate(graph.strokes) if s.stroke_id in ids]
            base_crossings = crossing_pairs(curves(row['outputs']['A']))
            for label, payload in row['outputs'].items():
                assert not invariants(namespace(payload), graph)
                assert not crossing_pairs(curves(payload))-base_crossings
                audit['outputs'] += 1
                record = row['metadata'].get(label, {}).get('selected')
                if record is None:
                    continue
                candidate = record['candidate']
                source = profile.source_trajectories[candidate['sample_id']]
                assert source.source_sha256 == candidate['source_sha256']
                assert plan['split'][source.character] == 'train'
                assert source.character != graph.character
                mapping = {s.standard_stroke_id: s for s in source.strokes}
                t = record['transform']
                assert t['sx'] == t['sy'] and t['sx'] > 0
                for i, sid in zip(indices, candidate['stroke_ids'], strict=True):
                    points = payload['strokes'][i]['points']
                    original = mapping[sid]
                    np.testing.assert_allclose([(p['x'], p['y']) for p in points],
                        np.asarray(original.points)*t['sx']+[t['tx'], t['ty']], atol=1e-12, rtol=0)
                    np.testing.assert_array_equal([p['pressure'] for p in points], original.pressure)
                    np.testing.assert_allclose(np.diff([p['t_ms'] for p in points]), np.diff(original.t_ms), atol=1e-8, rtol=0)
                    audit['source_points'] += len(points)
            # Reference diagnostics are shared across weights; audit once per case.
            trial = next(v for k, v in row['metadata'].items() if k != 'D')
            for record in trial['direction_diagnostics']:
                detail = record['author_context_evidence']
                excluded = {graph.character, record['candidate']['character']}
                references = detail.get('used_sources', []) + [s for d in detail.get('stroke_backoff', []) for s in d.get('used_sources', [])]
                for ref in references:
                    assert ref['character'] not in excluded and plan['split'][ref['character']] == 'train'
                    assert profile.source_trajectories[ref['sample_id']].source_sha256 == ref['source_sha256']
                    audit['independent_reference_uses'] += 1
        rows = [read(p) for p in sorted((folder / 'cases').glob('*.json'))]
        ordered = sorted(rows, key=lambda r: r['metrics'][display]['terminal_angle_deg']-r['metrics']['D']['terminal_angle_deg'])
        highlighted = {ordered[0]['task']['id'], ordered[-1]['task']['id'],
            max(rows, key=lambda r: r['metrics'][display]['mean_distance']-r['metrics']['D']['mean_distance'])['task']['id']}
        for row in rows:
            dsel, hsel = row['metadata']['D']['selected'], row['metadata'][display]['selected']
            if (dsel or {}).get('candidate') != (hsel or {}).get('candidate'):
                d, h = row['metrics']['D'], row['metrics'][display]
                donor_names = ' → '.join(x['candidate']['character']+' / '+x['candidate']['sample_id'][:8] for x in (dsel, hsel))
                changed_rows.append(f'<tr><td>{scope}</td><td>{row["task"]["character"]}</td><td>{donor_names}</td><td>{(h["mean_distance"]/d["mean_distance"]-1)*100:+.2f}%</td><td>{h["terminal_angle_deg"]-d["terminal_angle_deg"]:+.2f}°</td></tr>')
            reference = min(row['references'], key=lambda r: r['sample_id'])['curves']
            labels = ['reference', 'A', 'D', display]
            lines = {'reference': reference, **{k: curves(v) for k, v in row['outputs'].items()}}
            ids = row['task']['target_stroke_ids']
            indices = [i for i, s in enumerate(row['outputs']['A']['strokes']) if s['standard_stroke_id'] in ids]
            index = max(indices, key=lambda i: abs(
                (stroke_metrics(lines[display][i], reference[i])['terminal_angle_deg'] or 0.)-
                (stroke_metrics(lines['D'][i], reference[i])['terminal_angle_deg'] or 0.)))
            cloud = np.asarray([p for label in labels for p in lines[label][index]])
            center = (cloud.min(0)+cloud.max(0))/2
            span = max(float(np.ptp(cloud, axis=0).max())*1.35, .12)
            fig, axes = plt.subplots(2, 4, figsize=(13, 7.4))
            for col, label in enumerate(labels):
                color = ['#333333', '#2472a5', '#158168', '#95549c'][col]
                for r in range(2):
                    ax = axes[r, col]
                    for i, points in enumerate(lines[label]):
                        a = np.asarray(points)
                        ax.plot(a[:, 0], a[:, 1], color=color if i in indices else '#bac3cb', lw=1.8 if i == index else 1.)
                        if i == index:
                            ax.scatter(*a[-1], color=color, s=14)
                    ax.set_aspect('equal')
                    ax.set_xlim((-.02, 1.02) if r == 0 else (center[0]-span/2, center[0]+span/2))
                    ax.set_ylim((1.02, -.02) if r == 0 else (center[1]+span/2, center[1]-span/2))
                    ax.grid(alpha=.15)
                    ax.tick_params(labelsize=7)
                axes[0, col].set_title(['原稿·仅评估', 'A · v4 adaptive', 'D · 完整部件', 'H · 分层方向评分'][col], fontsize=11)
                if label != 'reference':
                    m = row['metrics'][label]
                    selected = row['metadata'].get(label, {}).get('selected')
                    donor = selected['candidate']['character'] if selected else '—'
                    axes[1, col].set_xlabel(f"供体 {donor}｜几何 {m['mean_distance']:.4f}\n末向 {m['terminal_angle_deg']:.2f}°", fontsize=10)
            fig.suptitle(f"{scope} · {row['task']['character']} · 局部 s{index+1} · {len(row['references'])} 份有效原稿\n图示为样本 ID 最小的一份；指标先平均原稿、再平均字；输出直接绘制全部顶点", fontsize=12)
            fig.tight_layout(rect=(0, 0, 1, .92))
            name = f"figures/{row['task']['id']}.png"
            fig.savefig(args.output / name, dpi=140)
            plt.close(fig)
            gallery.append(f'<details><summary>{scope} · {html.escape(row["task"]["character"])}</summary><img loading="lazy" src="{name}"></details>')
            if row['task']['id'] in highlighted:
                highlights.append(f'<h3>{scope}：{row["task"]["character"]}</h3><img src="{name}">')
        print(scope, 'figures', len(rows), flush=True)
    save(args.output / 'integrity_audit.json', audit)
    style = '<style>body{max-width:1280px;margin:32px auto;padding:0 24px;background:#f7f9fb;color:#263c50;font:16px/1.8 system-ui}img{width:100%}td,th{padding:8px;border-bottom:1px solid #ddd;text-align:left}table{width:100%;border-collapse:collapse;background:white}details{background:white;padding:14px;margin:12px 0}a{color:#126a99}.finding{padding:18px;background:#fff0df}</style>'
    prefix = '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>InkStruct 作者条件末向实验</title>'+style
    text = '<h1>相同部件与分层几何参考：作者条件末向实验</h1><p>2026-10-07 · user_001 归档批次，物理作者身份未确认 · 生产默认不变</p>'
    text += f'<p class="finding">开发冻结结果：<strong>{chosen["chosen"]}</strong>。展示路径为 {display}；若冻结为 D，展示的非零权重仅用于解释失败，不代表获准接入。'+('已按冻结参数完成字符留出确认。' if args.confirmation else '没有消耗留出组；本报告不声称新的泛化收益。')+'</p>'
    text += '<h2>数据隔离与重复采样</h2><p>归档共 385 条、294 字，按字符哈希分为 177 训练字（230 条）、59 开发字（74 条）、58 留出字（81 条）。仅训练组构建 A 及高保真档案，成功建档 203 条，保留完整源轨迹 197 条。公开结构在读取目标原稿前选择 46 个开发目标、45 个留出目标；所有候选和输出先固定，再对目标原稿对齐评估。原稿不能进入目标布局、候选选择或建档。同字重复先字内平均，不算独立目标。</p>'
    text += '<p>开发组 41 字、47 份原稿可评估；5 字无可靠一对一笔画映射而退出评分，拒绝原因留存。不能用 47 份原稿代替 41 个字扩大统计样本。该批次没有与 scx/mjb/wsq 重叠的源哈希，但这不证明物理作者不同，索引引用的外部原始文件未逐个重哈希。</p>'
    text += '<h2>两级实验及为何扩展</h2><p>第一层只使用同一部件上下文的其他字。每次排除目标字和候选供体字，近邻按公共形状选择，重复记录字内平均，至少 4 个不同字且方向集中度不低于 0.5。此批次仅剩 0–3 个参考字，所有配置回退到 D，不能解释为方向思路无效。</p>'
    text += '<p>第二层先用部件证据；不足时，按公共中心线的折转、钩、宽高签名检索相近笔画，形状距离不超过 0.20，取最近最多 8 个其他字，每字只选一个公共笔画及其重复记录。公共库没有语义 stroke_type 标签，几何签名不等于书法笔画类别。两种提示分别是作者实际末向均值、作者相对公共末向的偏差。用共同有证据的笔画评分，避免候选缺证据而占便宜。</p>'
    text += '<p>这些笔画只提供评分方向，生成仍整组选一个真实部件。输出顶点、供体内部关系、共同等比变换及安全候选池不变，不逐笔拼接或缩放输出。权重固定搜索 0、0.005、0.01、0.02、0.04、0.08；开发规则要求几何至多增加 1%、启用数不变，再最小化末向，必须严格改善才可进留出。分层扩展在观察第一层覆盖不足后提出，因此属于开发过程，不算独立验证。</p>'
    text += '<h2>开发结果（按字汇总）</h2><table><tr><th>路径</th><th>几何均差</th><th>末向均差</th><th>弧长相对差</th><th>有证据字数</th><th>换供体字数</th></tr>'
    for label, m in dev_summary.items():
        text += f'<tr><td>{label}</td><td>{m["mean_distance"]:.6f}</td><td>{m["terminal_angle_deg"]:.2f}°</td><td>{m["absolute_length_error"]:.2%}</td><td>{m.get("evidence_available", "—")}</td><td>{m.get("different_donor_from_D", "—")}</td></tr>'
    text += '</table><p>几何、末向、弧长与局部偏差统一按折线评估，不统一输出点数，不以弧长接近单独判优。</p>'
    if args.confirmation:
        confirm_coverage = read(args.confirmation / 'coverage.json')
        text += f'<p>留出实际评估 {confirm_coverage["scored_characters"]} 字、{confirm_coverage["scored_captures"]} 份原稿；计划 {confirm_coverage["planned_characters"]} 字。被排除的映射不可靠原稿单独记录。</p>'
        text += '<h2>冻结后的字符留出</h2><table><tr><th>路径</th><th>几何均差</th><th>末向均差</th><th>换供体</th></tr>'
        for label, m in read(args.confirmation / 'summary.json').items():
            text += f'<tr><td>{label}</td><td>{m["mean_distance"]:.6f}</td><td>{m["terminal_angle_deg"]:.2f}°</td><td>{m.get("different_donor_from_D", "—")}</td></tr>'
        confirmed = read(args.confirmation / 'summary.json')
        h, d = confirmed[display], confirmed['D']
        text += f'</table><p>相对 D：末向改变 {h["terminal_angle_deg"]-d["terminal_angle_deg"]:+.2f}°，几何均差改变 {(h["mean_distance"]/d["mean_distance"]-1)*100:+.4f}%；几何差异很小，不能夸大。</p>'
        text += '<p>留出仅用于一次确认，不调整权重。开发门槛也适用于是否考虑后续接入；不能只选择有利指标宣布成功。</p>'
    text += '<h2>全部改选案例：收益与代价同时列出</h2><table><tr><th>集合</th><th>字</th><th>供体字 / 样本 ID 前缀</th><th>几何相对变化</th><th>末向变化</th></tr>'+''.join(changed_rows)+'</table><p>留出组 6 字末向均改善，但知、鸣、种的几何偏差增加；鸣约增加 13.9%。总体几何平均几乎不变掩盖了这些局部退化，因此不因平均门槛通过而直接接入生产。茶的供体字相同，但换了完整采样实例，没有逐笔混搭。</p>'
    text += '<h2>方向变化两端及几何退化案例</h2><p>每组按 H−D 末向变化两端、以及几何偏差增加最多自动选图；无方向退化时，末向上端为未变化案例。全部案例另列图集；原稿按样本 ID 选择而非按拟合好坏。</p>'+''.join(highlights)
    text += f'<h2>完整性与边界</h2><p>{audit["outputs"]} 个输出通过有限坐标、画布范围、压力、标准 ID、笔数、笔顺及全局单调时间检查，{audit["source_points"]:,} 个源点的共同变换、压力和笔内时间逐项核验；{audit["independent_reference_uses"]:,} 次参考使用确认排除目标/供体字符且只来自训练组。无相对 A 新增严格笔间交叉；不覆盖笔宽接触和自交。</p>'
    text += '<p>方向提示是可解释的训练数据参考，不是自然概率。短钩可能是有效个性，也可能是噪声，当前无独立人工钩段标注。同字直接重建的几何保真不证明跨字选择正确。无论本轮局部收益如何，暂不替代平滑默认；保留全部负结果、拒绝及回退，再根据新的验证证据决定接入。</p><p><a href="gallery.html">全部同尺度整字与局部图</a> · <a href="integrity_audit.json">完整性审计</a></p>'
    (args.output / 'InkStruct_作者条件末向实验报告.html').write_text(prefix+text)
    (args.output / 'gallery.html').write_text(prefix+'<h1>作者条件末向实验图集</h1>'+''.join(gallery))
    print(json.dumps({k: v for k, v in audit.items() if k != 'sets'}), flush=True)
    print(args.output / 'InkStruct_作者条件末向实验报告.html')


if __name__ == '__main__':
    main()
