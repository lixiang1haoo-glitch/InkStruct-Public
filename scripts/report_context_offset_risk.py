"""Audit contextual risk offsets and their unchanged trajectory decisions."""
from __future__ import annotations

import argparse
import html
import json
import os
from collections import Counter
from itertools import pairwise
from pathlib import Path

import numpy as np
from experiment_component_trust import glyph_from_dict, read
from regress_calibrated_layout_writers import audit_generated
from report_counterfactual_layout_risk import verify_run
from run_raw_trajectory_experiment import DATABASE, curves, save
from train_grouped_logistic_risk import identity, summarize

from inkstruct.context_offset_risk import ContextRiskGate, base_logits, fit_offset
from inkstruct.exemplar_index import component_key
from inkstruct.grouped_logistic_risk import (
    fit_grouped,
    group_weights,
    sigmoid,
    validation_cells,
)
from inkstruct.layout_risk import training_fold
from inkstruct.profile import load_profile
from inkstruct.samples import sha256_file
from inkstruct.structures import StructureRepository
from inkstruct.trajectory_experiment import curve_error

CONTROL = 'g0.0_pooled_0.6'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('training', 'development', 'regression', 'output'):
        parser.add_argument('--'+key, type=Path, required=True)
    args = parser.parse_args()
    protocol = read(args.training / 'run_protocol.json')
    for group in ('input_sha256', 'code_sha256'):
        for name, expected in protocol[group].items():
            assert sha256_file(Path(name)) == expected, name
    choice = read(args.training / 'frozen_choice.json')
    for key in ('summary', 'run_protocol'):
        assert choice[key+'_sha256'] == sha256_file(args.training / (key+'.json'))
    training_path = args.training / 'examples.json'
    prior_root = Path(protocol['prior'])
    assert sha256_file(training_path) == choice['training_examples_sha256']
    rows = read(training_path)
    predictions = {tuple(p['identity']): p for p in read(args.training / 'predictions.json')}
    training_summary = read(args.training / 'summary.json')
    manifest_checks = []
    for record in read(prior_root / 'source_audit.json'):
        manifest = read(Path(record['fold_manifest']))
        frozen_path = Path(manifest['frozen_manifest'])
        assert sha256_file(frozen_path) == manifest['frozen_manifest_sha256']
        original = read(frozen_path)
        index_path = frozen_path.parent / 'index.jsonl'
        assert sha256_file(index_path) == manifest['index_sha256'] == original['index_sha256']
        samples = [json.loads(line) for line in index_path.read_text().splitlines() if line]
        assert {r['character'] for r in samples} == set(manifest['training_characters'])
        assert all(training_fold(s['character']) != manifest['fold'] for s in samples)
        assert set(manifest['training_characters']).isdisjoint(manifest['target_characters'])
        assert sha256_file(Path(manifest['profile'])) == manifest['profile_sha256'] == original['profile_sha256']
        manifest_checks.append({'index': str(index_path), 'sha256': sha256_file(index_path), 'records': len(samples), 'excluded_target_fold': True})
    repository = StructureRepository(DATABASE)
    for r in rows:
        graph = repository.get(r['character'])
        component = next(c for c in graph.components if c.component_id == r['component_id'])
        assert r['context'] == component_key(graph, component)
    model_count = 0
    for generation, heldout, train, valid in validation_cells(rows):
        assert not {r['character'] for r in train} & {r['character'] for r in valid}
        assert {r['fold'] for r in train+valid} == {generation}
        model = fit_grouped(train, view='combined', regularization=.1)
        assert model.payload() == read(prior_root / 'models' / f'{generation}-{heldout}-combined_0.1.json')
        x = [r['features'] for r in valid]
        np.testing.assert_allclose(model.predict(x), [predictions[identity(r)]['scores']['base'] for r in valid], atol=1e-12, rtol=0)
        for mode in protocol['config']['modes']:
            for reg in protocol['config']['regularization']:
                label = f'{mode}_{reg}'
                correction = fit_offset(train, base_logits(model, [r['features'] for r in train]), mode=mode, regularization=reg)
                saved = read(args.training / 'models' / f'{generation}-{heldout}-{label}.json')
                assert correction.payload() == saved
                scores = sigmoid(base_logits(model, x)+correction.offset(valid))
                np.testing.assert_allclose(scores, [predictions[identity(r)]['scores'][label] for r in valid], atol=1e-12, rtol=0)
                model_count += 1
    for label, summary in training_summary.items():
        assert summarize(rows, [predictions[identity(r)]['scores'][label] for r in rows]) == summary['all']
    grid = [('base', None)]+[(v, r) for v in protocol['config']['modes'] for r in protocol['config']['regularization']]
    name = lambda pair: 'base' if pair[0] == 'base' else f'{pair[0]}_{pair[1]}'
    best = min(grid, key=lambda pair: (training_summary[name(pair)]['all']['brier'], training_summary[name(pair)]['all']['log_loss'],
        ['base', 'author', 'component', 'hierarchical'].index(pair[0]), -(pair[1] or 0)))
    assert (choice['mode'], choice['regularization']) == best
    print('training audit', model_count, 'offset models,', len(manifest_checks), 'source indexes', flush=True)
    gate = ContextRiskGate(rows, mode=choice['mode'], regularization=choice['regularization'])
    repository = StructureRepository(DATABASE)
    audits, cases, decision_count = {}, [], 0
    for stage in ('development', 'regression'):
        folder = getattr(args, stage)
        p = verify_run(folder)
        assert p['choice'] == choice
        archives = {w: load_profile(Path(path)).source_trajectories for w, path in p['profiles'].items()}
        audit = Counter()
        for path in sorted((folder / 'generated').glob('*.json')):
            row = read(path)
            old_path = Path(row['frozen_input'])
            assert sha256_file(old_path) == row['frozen_input_sha256']
            old = read(old_path)
            for label, source in row['selected_labels'].items():
                assert row['outputs'][label] == old['outputs'][source]
            assert row['outputs']['G'] == row['outputs']['N']
            audit.update(audit_generated(row, archives[row['writer']], repository))
            if row['features'] is not None:
                character = row['task']['character']
                restored = gate.predict(row['writer'], character, row['context'], row['features'], threshold=choice['threshold'])
                assert restored == row['decision']
                model = read(folder / 'models' / (row['task']['id']+'.json'))
                assert model['model'] == gate.cache[character][0].payload()
                assert model['correction'] == gate.cache[character][1].payload()
                expected = [[r['writer'], r['character'], r['component_id'], r['proposal_id']] for r in gate.examples if r['character'] != character]
                assert model['training_identities'] == expected
                decision_count += 1
            case_path = folder / 'cases' / path.name
            if case_path.exists():
                case = read(case_path)
                assert all(case[k] == v for k, v in row.items())
                cases.append((stage, case))
        assert dict(audit) == read(folder / 'integrity_audit.json')
        audits[stage] = dict(audit)
    audits.update(training_models_replayed=model_count, source_indexes=manifest_checks, query_models_replayed=decision_count)
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
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.4))
    labels = list(training_summary)
    axes[0].barh(labels, [training_summary[k]['all']['brier'] for k in labels], color=['#14806a' if k == choice['label'] else '#8eacbf' for k in labels])
    axes[0].set_xlim(0, .3)
    axes[0].set_xlabel('按作者—字等权 Brier，低为优；选择集上的诊断')
    axes[0].set_title('九个隔离组的折外预测')
    bins, reliability = np.linspace(0, 1, 6), {}
    for label, color in [('base', '#2874a6'), ('component_0.1', '#14806a')]:
        scores = np.asarray([predictions[identity(r)]['scores'][label] for r in rows])
        y = np.asarray([r['safe_benefit'] for r in rows])
        w = group_weights(rows)
        points = []
        for lo, hi in pairwise(bins):
            mask = (scores >= lo) & ((scores < hi) if hi < 1 else (scores <= hi))
            if mask.any():
                mean_score = float((w*mask)@scores/(w@mask))
                fraction = float((w*mask)@y/(w@mask))
                points.append({'lo': float(lo), 'hi': float(hi), 'score': mean_score, 'safe_fraction': fraction, 'rows': int(mask.sum())})
        reliability[label] = points
        axes[1].plot([p['score'] for p in points], [p['safe_fraction'] for p in points], 'o-', label=label, color=color)
    axes[1].plot([0, 1], [0, 1], '--', color='#aaa')
    axes[1].set(xlim=(0, 1), ylim=(0, 1), xlabel='平均模型分数', ylabel='实际安全收益标签比例', title='高分不能当作安全保证')
    axes[1].legend()
    fig.tight_layout()
    fig.savefig(args.output / 'figures/training.png', dpi=140, bbox_inches='tight')
    plt.close(fig)
    blocks, decision_table = [], []
    for stage, row in cases:
        if row['features'] is None:
            continue
        ids = row['task']['target_stroke_ids']
        indices = [i for i, s in enumerate(row['outputs']['D']['strokes']) if s['standard_stroke_id'] in ids]
        values = {'reference': row['references'][0]['curves'], **{k: curves(glyph_from_dict(v)) for k, v in row['outputs'].items()}}
        labels = ['reference', 'A', 'D', 'N', 'G']
        titles = ['原稿 · 仅评估', 'A · 固定 v4', 'D · 完整部件', 'N · 原数值风险模型', 'G · 部件上下文校正']
        index = max(indices, key=lambda i: curve_error(values['D'][i], values['M'][i])[1])
        cloud = np.asarray([p for label in labels for p in values[label][index]])
        center = (cloud.min(0)+cloud.max(0))/2
        span = max(float(np.ptp(cloud, axis=0).max())*1.3, .12)
        fig, axes = plt.subplots(2, 5, figsize=(16, 7.2))
        for col, label in enumerate(labels):
            color = ['#333', '#2874a6', '#14806a', '#91579f', '#b17637'][col]
            for level in range(2):
                ax = axes[level, col]
                for i, stroke in enumerate(values[label]):
                    a = np.asarray(stroke)
                    ax.plot(a[:, 0], a[:, 1], color=color if i in indices else '#c2cad1', lw=1.7 if i == index else 1.)
                    if i == index:
                        ax.scatter(*a[-1], color=color, s=12)
                ax.set_aspect('equal')
                ax.set_xlim((-.02, 1.02) if level == 0 else (center[0]-span/2, center[0]+span/2))
                ax.set_ylim((1.02, -.02) if level == 0 else (center[1]+span/2, center[1]-span/2))
                ax.grid(alpha=.15)
                ax.tick_params(labelsize=7)
            axes[0, col].set_title(titles[col], fontsize=11)
            if label != 'reference':
                s = row['metrics'][label]
                axes[1, col].set_xlabel(f"部件均差 {s['mean_distance']:.4f}\n末向 {s['terminal_angle_deg']:.2f}°", fontsize=10)
        char, writer, score = row['task']['character'], row['writer'], row['decision']['score']
        fig.suptitle(f'{writer} · {char} · {"开发" if stage == "development" else "已观察回归"} · 局部 s{index+1}\n相同比例、固定供体与原 D/M；上下文分数 {score:.3f} → {row["selected_labels"]["G"]}', fontsize=13)
        fig.tight_layout(rect=(0, 0, 1, .91))
        filename = 'figures/'+row['task']['id']+'.png'
        fig.savefig(args.output / filename, dpi=135, bbox_inches='tight')
        plt.close(fig)
        blocks.append(f'<figure><img src="{filename}" loading="lazy"><figcaption>{stage}/{writer}：{char}</figcaption></figure>')
        ratio = row['metrics']['M']['mean_distance']/row['metrics']['D']['mean_distance']-1
        decision_table.append(f'<tr><td>{stage}/{writer}</td><td>{char}</td><td>{ratio*100:+.2f}%</td><td>{row["decision"]["base_score"]:.4f}</td><td>{score:.4f}</td><td>{row["selected_labels"]["G"]}</td></tr>')
    rows_html, writer_html, result_html = [], [], []
    for label, d in training_summary.items():
        s = d['all']
        frac = '—' if s['safe_fraction_among_accepted'] is None else f'{s["safe_fraction_among_accepted"]:.3f}'
        rows_html.append(f'<tr><td>{label}</td><td>{s["brier"]:.6f}</td><td>{s["log_loss"]:.6f}</td><td>{s["accepted_writer_characters"]}</td><td>{frac}</td></tr>')
    for writer in training_summary['base']['writer']:
        writer_html.append('<tr><td>'+writer+'</td>'+''.join(f'<td>{training_summary[label]["writer"][writer]["brier"]:.6f}</td>' for label in ('base', 'author_0.1', 'component_0.1', 'hierarchical_0.1'))+'</tr>')
    for stage in ('development', 'regression'):
        for writer, result in read(getattr(args, stage) / 'summary.json').items():
            for label in ('A', 'D', 'N', 'G'):
                s = result['component'][label]
                result_html.append(f'<tr><td>{stage}/{writer}</td><td>{result["n"]}</td><td>{label}</td><td>{s["mean_distance"]:.6f}</td><td>{s["terminal_angle_deg"]:.3f}°</td><td>{s["maximum_character_geometry_ratio"]:.4f}</td><td>{s["maximum_stroke_local_error_increase"]:+.6f}</td><td>{"通过" if s["passes_gates"] else "未通过"}</td></tr>')
    assert choice['label'] == 'component_0.1', 'Revise narrative for another frozen choice'
    assert all(r['outputs']['G'] == r['outputs']['N'] for _, r in cases), 'Revise unchanged-output narrative'
    errors = read(args.training / 'numeric_false_accepts.json')
    error_table = []
    for e in sorted(errors, key=lambda r: -r['geometry_ratio']):
        writer, char, _, proposal = e['identity']
        error_table.append(f'<tr><td>{writer}/{char}</td><td>{e["context"]}</td><td>{proposal}</td><td>{e["geometry_ratio"]:.4f}</td><td>{e["local_increase"]:+.6f}</td><td>{e["angle_increase"]:+.3f}°</td><td>{len(e["same_context_training_characters"])}</td></tr>')
    content = """<h1>作者与部件上下文校准：错误审计及对照实验</h1>
<p><strong>结论：部件上下文只带来极小训练预测改善，实际输出与原数值模型完全相同，仍不接入生产。</strong>冻结选择 component_0.1；开发 41 字、回归 186 字均未改变原数值门控的选择。「涤」仍被误放，「淹、附」仍有收益。没有将近似不变的预测指标写成生成质量提升。</p>
<h2>先回查错误，不预设都是噪声</h2>
<p>原数值模型的折外 128 次接受中有 33 次不满足原安全收益条件，涉及 19 个作者—字。21 次仅平均几何退化；5 次同时平均/局部退化；5 次平均改善但局部退化；2 次平均/局部/末向均退化。部分偏差很小，但最大为 mjb「协」平均退化 40.03%、局部增量 0.027583。因此不能通过放宽“微小变化”的标签定义抹去全部错误。</p>
<p>这 19 个错误接受的作者—字中，6 个在对应训练单元没有同作者、同精确部件上下文对照。有些失败案例有相当高的同上下文训练安全比例，因此缺少参照不是唯一原因。没有删除零支持或难例，也没有调整原安全标签。</p>
<table><tr><th>作者/字</th><th>公共部件上下文</th><th>试移</th><th>几何倍率</th><th>局部增量</th><th>末向增量</th><th>训练同作者同上下文字数</th></tr>"""+''.join(error_table)+"""</table>
<h2>校正方法与冻结条件</h2>
<p>保留原 46 维数值模型及正则化 0.1，在其 logit 上加入惩罚约束的分类偏移。三种模型为作者、部件、作者+部件+作者部件三层；各尝试 0.001、0.01、0.1 惩罚。部件键完全沿用公共结构的 canonical、变体、位置角色、父布局、笔数，不读取目标原稿。训练集有 69 个部件上下文、138 个作者部件组合。</p>
<p>每个作者—字总权重相同。词表和数值模型都只在当前训练单元拟合；没有训练过的分类项偏移为零。较强惩罚将稀少分类偏移压向零，不生成未经约束的组独立模型。九个验证单元沿用上一轮的“同一原生成折内部再分字组”，目标字在训练标签和共用源档案中双重隔离。</p>
<p>原数值模型作为第十个对照纳入选择，只按训练折外 Brier、对数损失及预定平局规则冻结。查询同字跨作者在拟合与词表构建之前排除。接受分数保持 0.8，候选、A/D/M、轨迹、共享等比变换及目标名单都不变。重复使用既有训练折选模型仍是探索性实验，不是独立泛化验证。</p>
<h2>训练内结果</h2>
<table><tr><th>配置</th><th>Brier</th><th>对数损失</th><th>有接受试移的作者—字</th><th>接受试移安全比例</th></tr>"""+''.join(rows_html)+"""</table><img src="figures/training.png">
<p>部件 0.1 的 Brier 为 0.234349，原数值模型 0.234575，仅改善约 0.097%；接受试移实际安全比例反而由 73.71% 到 73.11%。作者校正均更差；低惩罚的复杂分组明显恶化。这不是安全性校准保证，模型分数也不是书写自然性概率。</p>
<table><tr><th>作者/批次</th><th>原数值 Brier</th><th>作者 0.1</th><th>部件 0.1</th><th>三层 0.1</th></tr>"""+''.join(writer_html)+"""</table>
<h2>冻结后的实际输出</h2>
<table><tr><th>阶段/作者</th><th>有效字数</th><th>路径</th><th>部件均差</th><th>末向均差</th><th>最差字/D</th><th>最差笔局部增量</th><th>原质量门槛</th></tr>"""+''.join(result_html)+"""</table>
<p>N 为原数值模型，G 为部件校正模型。所有 235 个生成字的 G 与 N 轨迹全字段相同（其中 227 字有有效评分）；分数变化未跨越任何实际决策门槛。回归仍改涤、淹、附：涤平均退化 8.49%、局部增量 0.012022；wsq 均差改善约 0.52%，仍比 v4 A 差约 0.90%。没有抬门槛来专门排除涤。</p>
<table><tr><th>阶段/作者</th><th>字</th><th>M 相对 D 均差</th><th>原数值分数</th><th>上下文分数</th><th>输出</th></tr>"""+''.join(decision_table)+"""</table>
<h2>限制及后续方向</h2>
<p>同作者不同字的相同部件有参考价值，但粗粒度上下文先验仍不足以决定某个具体布局调整。较弱收缩导致过拟合，强收缩几乎不改变决策。这里既有微小退化，也有真实的大幅损伤和平均/局部目标冲突，不能全归因于标签噪声。没有进行新的自然性人工评分，user_001 的物理作者身份仍未独立确认。</p>
<p>连续的风险门控实验未修复关键误伤，后续应回到候选及布局提议本身：在隔离训练中先测量“选择另一完整同作者部件”能提供多少可实现收益，再设计候选排序或共同放置改进。应单列候选选择贡献，继续保留整部件共享变换及原始折钩，不继续只围绕已知反例堆叠门槛。</p>
<h2>核验</h2><p>重拟合 81 个分类偏移模型，精确重放九个原数值模型、全部折外预测和冻结选择；检查 12 份建档索引目标折排除；重放 13 个查询模型的词表、参数和训练身份。轨迹继续核验完整源点、压力、共同正等比变换、标准 ID/笔顺、有限坐标、边界、非退化和单调时间；没有相对 A 新增严格笔间交叉，不覆盖自交和笔宽接触。弧长接近不单独等于质量更高。</p><pre>"""+html.escape(str(audits))+"""</pre>
<h2>全部 13 个原 M 改动案例：同尺度整字与局部图</h2><p>G/N 重合是实测结果，不是绘图遗漏。原稿只用于评估，图片取首个有效采样，指标按该字有效采样平均。</p>"""+''.join(blocks)
    style = '<style>body{font:17px/1.7 system-ui;margin:35px auto;max-width:1500px;padding:0 22px;color:#203040}img{width:100%;height:auto}figure{margin:30px 0}table{border-collapse:collapse;width:100%;font-size:14px}td,th{border:1px solid #ccd5df;padding:7px}th{background:#eef3f7}pre{white-space:pre-wrap}</style>'
    report = args.output / 'InkStruct_部件上下文风险对比报告.html'
    report.write_text('<!doctype html><meta charset="utf-8">'+style+content)
    save(args.output / 'integrity_audit.json', audits)
    save(args.output / 'reliability.json', reliability)
    save(args.output / 'report_manifest.json', {'case_figures': len(blocks), 'scored_cases': len(cases), 'choice': choice,
        'report_code_sha256': sha256_file(Path(__file__)), 'report_sha256': sha256_file(report)})
    print(report, flush=True)


if __name__ == '__main__':
    main()
