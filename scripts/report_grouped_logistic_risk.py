"""Audit training-isolated risk calibration and render frozen cohort comparisons."""
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

from inkstruct.grouped_logistic_risk import (
    GroupedLogisticRiskGate,
    fit_grouped,
    group_weights,
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
    training_path = Path(protocol['training']) / 'examples.json'
    assert sha256_file(training_path) == choice['training_examples_sha256']
    rows = read(training_path)
    predictions = {tuple(p['identity']): p for p in read(args.training / 'predictions.json')}
    training_summary = read(args.training / 'summary.json')
    manifest_checks = []
    for record in read(args.training / 'source_audit.json'):
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
    model_count = 0
    for generation, heldout, train, valid in validation_cells(rows):
        assert not {r['character'] for r in train} & {r['character'] for r in valid}
        assert {r['fold'] for r in train+valid} == {generation}
        prior = float(group_weights(train)@np.asarray([r['safe_benefit'] for r in train]))
        for row in valid:
            assert predictions[identity(row)]['scores']['constant'] == prior
        for view in protocol['config']['feature_views']:
            for reg in protocol['config']['regularization']:
                label = f'{view}_{reg}'
                model = fit_grouped(train, view=view, regularization=reg)
                saved = read(args.training / 'models' / f'{generation}-{heldout}-{label}.json')
                assert model.payload() == saved
                scores = model.predict([r['features'] for r in valid])
                np.testing.assert_allclose(scores, [predictions[identity(r)]['scores'][label] for r in valid], atol=1e-12, rtol=0)
                model_count += 1
    for label, summary in training_summary.items():
        assert summarize(rows, [predictions[identity(r)]['scores'][label] for r in rows]) == summary['all']
    grid = [(v, r) for v in protocol['config']['feature_views'] for r in protocol['config']['regularization']]
    best = min(grid, key=lambda p: (training_summary[f'{p[0]}_{p[1]}']['all']['brier'],
        training_summary[f'{p[0]}_{p[1]}']['all']['log_loss'], {'layout': 22, 'geometry': 24, 'combined': 46}[p[0]], -p[1]))
    assert (choice['view'], choice['regularization']) == best
    print('training audit', model_count, 'models,', len(manifest_checks), 'source indexes', flush=True)
    gate = GroupedLogisticRiskGate(rows, view=choice['view'], regularization=choice['regularization'])
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
            audit.update(audit_generated(row, archives[row['writer']], repository))
            if row['features'] is not None:
                character = row['task']['character']
                restored = gate.predict(character, row['features'], threshold=choice['threshold'])
                assert restored == row['decision']
                model = read(folder / 'models' / (row['task']['id']+'.json'))
                assert model['model'] == gate.cache[character][0].payload()
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
    for label, color in [('layout_0.1', '#2874a6'), ('combined_0.1', '#14806a')]:
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
        labels = ['reference', 'A', 'D', CONTROL, 'G']
        titles = ['原稿 · 仅评估', 'A · 固定 v4', 'D · 完整部件', '旧近邻门控', 'G · 训练冻结逻辑模型']
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
        fig.suptitle(f'{writer} · {char} · {"开发" if stage == "development" else "已观察回归"} · 局部 s{index+1}\n相同比例、固定供体与原 D/M；G 分数 {score:.3f} → {row["selected_labels"]["G"]}', fontsize=13)
        fig.tight_layout(rect=(0, 0, 1, .91))
        filename = 'figures/'+row['task']['id']+'.png'
        fig.savefig(args.output / filename, dpi=135, bbox_inches='tight')
        plt.close(fig)
        blocks.append(f'<figure><img src="{filename}" loading="lazy"><figcaption>{stage}/{writer}：{char}</figcaption></figure>')
        ratio = row['metrics']['M']['mean_distance']/row['metrics']['D']['mean_distance']-1
        decision_table.append(f'<tr><td>{stage}/{writer}</td><td>{char}</td><td>{ratio*100:+.2f}%</td><td>{row["selected_labels"][CONTROL]}</td><td>{score:.4f}</td><td>{row["selected_labels"]["G"]}</td></tr>')
    rows_html, writer_html, result_html = [], [], []
    for label, d in training_summary.items():
        s = d['all']
        frac = '—' if s['safe_fraction_among_accepted'] is None else f'{s["safe_fraction_among_accepted"]:.3f}'
        rows_html.append(f'<tr><td>{label}</td><td>{s["brier"]:.6f}</td><td>{s["log_loss"]:.6f}</td><td>{s["accepted_writer_characters"]}</td><td>{frac}</td></tr>')
    for writer in training_summary['constant']['writer']:
        writer_html.append('<tr><td>'+writer+'</td>'+''.join(f'<td>{training_summary[label]["writer"][writer]["brier"]:.6f}</td>' for label in ('constant', 'layout_0.1', 'geometry_0.1', 'combined_0.1'))+'</tr>')
    for stage in ('development', 'regression'):
        for writer, result in read(getattr(args, stage) / 'summary.json').items():
            for label in ('A', 'D', CONTROL, 'G'):
                s = result['component'][label]
                result_html.append(f'<tr><td>{stage}/{writer}</td><td>{result["n"]}</td><td>{label}</td><td>{s["mean_distance"]:.6f}</td><td>{s["terminal_angle_deg"]:.3f}°</td><td>{s["maximum_character_geometry_ratio"]:.4f}</td><td>{s["maximum_stroke_local_error_increase"]:+.6f}</td><td>{"通过" if s["passes_gates"] else "未通过"}</td></tr>')
    assert choice['label'] == 'combined_0.1', 'Revise narrative for changed choice'
    content = '''<h1>训练内隔离校准：布局改动风险模型</h1>
<p><strong>结论：存在有限预测信息，但没有解决实际误伤，不接入生产。</strong>只用隔离训练折选择组合特征、正则化 0.1 的逻辑回归，固定接受分数 0.8。回归仍错误放行 scx「涤」，只保留 wsq「淹、附」的收益；比旧门控丢失更多收益，没有修复其关键反例。生产默认、CLI/Mac 入口不变。</p>
<h2>验证设计：原稿不能从供体档案绕回训练</h2>
<p>沿用 3,088 个相关试移标签、753 个作者—字、358 个不同汉字、12 份三折源档案。对每个原生成折，所有目标字都已排除在建档索引中；只在该折目标内部，再按字符哈希划三组，两个组训练风险模型，另一个组验证。不同作者、部件和幅度的同一个字始终同组。三折各三组，共九个验证单元；每个标签恰好得到一次折外预测。验证字也不可能经其他训练实例的供体档案进入模型。报告核查了 12 份建档索引、源档案及哈希。</p>
<p>原 22 维布局特征、24 维几何特征与 46 维组合分别尝试 0.001、0.01、0.1 三档 L2 正则化。各作者—字总权重相等，训练均值/标准差只由本单元训练组计算，标准差下限 0.1，标准化值截在 ±5。截距不惩罚，不做类别平衡；常数控制只预测训练组安全比例。原稿仅用于已有训练标签，原输出不重生成。</p>
<h2>训练内结果：少量增益，不是安全保证</h2>
<p>按 Brier 最低冻结 combined_0.1：0.234575，相比常数 0.253417 下降约 7.43%；布局单独为 0.235140，加入几何仅下降约 0.24%，且对数损失从布局的 0.663246 升至 0.664099。几何单独更差，不能宣称新增几何特征带来明确质量突破。</p>
<table><tr><th>配置</th><th>Brier</th><th>对数损失</th><th>有接受试移的作者—字</th><th>接受试移安全比例</th></tr>'''+''.join(rows_html)+'''</table><img src="figures/training.png">
<p>选中配置分数 ≥0.8 的折外试移只有 128 行，覆盖 58 个作者—字；按作者—字原权重条件统计的安全收益比例为 73.71%，并没有达到 80% 的安全保证。多次试移是相关的，不能把行数当作独立自然样本。这些结果用于模型选择，有选择乐观性，不能作为独立性能证明。</p>
<table><tr><th>作者/批次</th><th>常数 Brier</th><th>布局 0.1</th><th>几何 0.1</th><th>组合 0.1</th></tr>'''+''.join(writer_html)+'''</table>
<p>user_001 的组合模型甚至弱于常数；该批次物理作者身份也未独立确认。跨作者风险监督不是目标作者的自然书写概率。各单元训练标签约占全部数据的 2/9，完整训练模型的数据规模和档案分布不同，不能将这里的条件比例直接搬到实际生成。</p>
<h2>冻结后实际生成：未在开发或回归上调参</h2>
<p>先保存训练选择与哈希，再对既有开发和回归生成输出。每次查询在训练标签与尺度估计之前排除所有作者的同字记录；使用冻结的特征/正则化和 0.8 门槛。只接受或拒绝旧 M，A/D/M、供体、点数及共同等比变换固定，目标原稿在输出固定后才读取评分。没有根据「涤」的 0.8037 分数临时抬高门槛。</p>
<table><tr><th>阶段/作者</th><th>有效字数</th><th>路径</th><th>部件均差</th><th>末向均差</th><th>最差字/D</th><th>最差笔局部增量</th><th>原质量门槛</th></tr>'''+''.join(result_html)+'''</table>
<p>开发 41 字中，模型拒绝原 M 对「冗」的收益，G=D。已观察回归 186 字中仅涤、淹、附采用 M：涤退化 8.49%、局部误差增加 0.012022；wsq 均差改善约 0.52%，但仍弱于旧门控的 0.81%，且几何仍比 v4 A 差约 0.90%。原稿噪声可能影响短末段角度；弧长接近不单独等于质量更好。所有回归都是既有数据，不称新留出。</p>
<table><tr><th>阶段/作者</th><th>字</th><th>M 相对 D 均差</th><th>旧门控</th><th>新模型分数</th><th>新模型输出</th></tr>'''+''.join(decision_table)+'''</table>
<h2>自然性、限制与后续</h2>
<p>同作者不同字的同部件仍可作为真实变化参照，但必须结合位置、形态、角色及邻件分析。保留供体原始形状不等于适合目标布局；人工试移不是新采集的自然变化。当前特征没有解决好作者与部件上下文差异，线性模型也可能不足。该解释是待检验假设，不是本轮已证明的原因。</p>
<p>下一步应检查训练中错误接受的部件/作者分布与原始几何差异，判断是监督标签、上下文表达还是模型能力的限制；不可仅移动门槛来躲开已知涤。完整源轨迹仍适合原稿重建及相容部件保真，但本实验不能支持全面替代平滑默认。</p>
<h2>核验</h2><p>重拟合 81 个验证模型、重放全部折外分数与选择、核查 12 份建档索引排除目标折、重放 13 个实际查询模型。开发/回归再核对源点、共享正等比变换、压力、相对时间、标准 ID/笔数/笔顺、有限坐标、边界、非退化及单调时间；没有相对 A 新增严格笔间交叉，不覆盖自交、共线重合和笔宽接触。输出等于旧 D/M 后复用既有统一折线指标。旧数据不覆盖，私有产物不进入 Git。</p><pre>'''+html.escape(str(audits))+'''</pre>
<h2>全部 13 个原 M 改动案例</h2><p>整字及局部所有列尺度一致。图片为该字首个有效原稿，指标按有效采样平均。未画出的 214 个有效字没有 M 改动，输出和指标均完整保存在独立目录。</p>'''+''.join(blocks)
    style = '<style>body{font:17px/1.7 system-ui;margin:35px auto;max-width:1500px;padding:0 22px;color:#203040}img{width:100%;height:auto}figure{margin:30px 0}table{border-collapse:collapse;width:100%;font-size:14px}td,th{border:1px solid #ccd5df;padding:7px}th{background:#eef3f7}pre{white-space:pre-wrap}</style>'
    report = args.output / 'InkStruct_训练内风险校准对比报告.html'
    report.write_text('<!doctype html><meta charset="utf-8">'+style+content)
    save(args.output / 'integrity_audit.json', audits)
    save(args.output / 'reliability.json', reliability)
    save(args.output / 'report_manifest.json', {'case_figures': len(blocks), 'scored_cases': len(cases), 'choice': choice,
        'report_code_sha256': sha256_file(Path(__file__)), 'report_sha256': sha256_file(report)})
    print(report, flush=True)


if __name__ == '__main__':
    main()
