"""Audit fixed training trials and report grouped risk decisions with controls."""
from __future__ import annotations

import argparse
import html
import os
from collections import Counter
from pathlib import Path

import numpy as np
from experiment_component_trust import glyph_from_dict, read
from regress_calibrated_layout_writers import audit_generated
from run_raw_trajectory_experiment import DATABASE, curves, save

from inkstruct.counterfactual_layout_risk import CounterfactualLayoutRiskGate
from inkstruct.layout_risk import training_fold
from inkstruct.profile import load_profile
from inkstruct.samples import sha256_file
from inkstruct.structures import StructureRepository
from inkstruct.trajectory_experiment import curve_error


def verify_run(folder):
    protocol = read(folder / 'run_protocol.json')
    for group in ('input_sha256', 'code_sha256'):
        for name, expected in protocol[group].items():
            assert sha256_file(Path(name)) == expected, name
    for name, expected in read(folder / 'generation_manifest.json').items():
        assert sha256_file(Path(name)) == expected, name
    return protocol


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('training', 'development', 'regression', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    protocols = {k: verify_run(getattr(args, k)) for k in ('training', 'development', 'regression')}
    all_root = Path(protocols['training']['prior'])
    all_protocol = verify_run(all_root)
    single_root = Path(all_protocol['prior'])
    prior_replay = read(all_root / 'prior_replay.json')
    assert prior_replay['matched_complete_prior_outputs'] == prior_replay['expected'] == 914
    all_examples = read(all_root / 'examples.json')
    old_examples = read(single_root / 'examples.json')
    for e in all_examples:
        old = next(o for o in old_examples if o['writer'] == e['writer'] and o['character'] == e['character'])
        assert all(e[k] == old[k] for k in ('features', 'geometry_ratio', 'local_increase', 'angle_increase', 'safe_benefit'))
    assert len(all_examples) == len(old_examples) == 33
    choice = read(args.development / 'frozen_choice.json')
    for key in ('summary', 'run_protocol'):
        assert choice[key+'_sha256'] == sha256_file(args.development / (key+'.json'))
    assert protocols['regression']['choice'] == choice
    repo = StructureRepository(DATABASE)
    audit = Counter()
    source_cache, current_fold = None, None
    # Visit a whole fold together so its large source profile is loaded once.
    trial_paths = sorted(args.training.glob('*/generated/*.json'), key=lambda p: (
        p.parent.parent.name, read(p)['task']['fold'], p.name))
    for path in trial_paths:
        trial = read(path)
        old_path = Path(trial['frozen_input'])
        assert sha256_file(old_path) == trial['frozen_input_sha256']
        old = read(old_path)
        fold = read(old_path.parent.parent / 'fold_manifest.json')
        identity = (trial['writer'], fold['fold'])
        if current_fold != identity:
            assert sha256_file(Path(fold['profile'])) == fold['profile_sha256']
            source_cache = load_profile(Path(fold['profile'])).source_trajectories
            assert all(training_fold(s.character) != fold['fold'] for s in source_cache.values())
            current_fold = identity
        assert training_fold(trial['task']['character']) == fold['fold']
        check = {'task': old['task'], 'outputs': {'A': old['outputs']['A'], 'D': old['outputs']['D'], 'P': trial['output'], 'off': old['outputs']['D']},
            'metadata': {'D': old['metadata']['D'], 'P': trial['metadata'], 'off': old['metadata']['D']}, 'predictions': old['predictions']}
        audit.update(audit_generated(check, source_cache, repo))
    assert dict(audit) == read(args.training / 'integrity_audit.json')
    full_audit = {'counterfactual_training': dict(audit), 'all_component_training': read(all_root / 'integrity_audit.json'), 'prior_replay': prior_replay}
    print('training source audit', dict(audit), flush=True)
    examples = read(args.training / 'examples.json')
    gates = {'trial': CounterfactualLayoutRiskGate(examples), 'observed': CounterfactualLayoutRiskGate([{**e, 'proposal_id': 'observed'} for e in all_examples])}
    cases = []
    for stage in ('development', 'regression'):
        folder, protocol = getattr(args, stage), protocols[stage]
        sources = {w: load_profile(Path(p)).source_trajectories for w, p in protocol['profiles'].items()}
        audit = Counter()
        for path in (folder / 'generated').glob('*.json'):
            row = read(path)
            audit.update(audit_generated(row, sources[row['writer']], repo))
            for label, source in row['selected_labels'].items():
                assert row['outputs'][label] == row['outputs'][source]
            if row['features'] is not None:
                for label, decision in row['decisions'].items():
                    pool, scope, threshold = label.split('_')
                    restored = gates[pool].predict(row['writer'], row['task']['character'], row['features'], scope=scope, threshold=float(threshold))
                    assert decision == restored
                    assert len({(r['writer'], r['character']) for r in decision.get('neighbors', [])}) == len(decision.get('neighbors', []))
                    assert all(r['character'] != row['task']['character'] for r in decision.get('neighbors', []))
        assert dict(audit) == read(folder / 'integrity_audit.json')
        full_audit[stage] = dict(audit)
        for path in sorted((folder / 'cases').glob('*.json')):
            row = read(path)
            generated = read(folder / 'generated' / path.name)
            assert all(row[k] == v for k, v in generated.items())
            cases.append((stage, row))
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
    gallery, highlights = [], []
    selected_label = choice['label']
    for stage, row in cases:
        ids = row['task']['target_stroke_ids']
        indices = [i for i, s in enumerate(row['outputs']['D']['strokes']) if s['standard_stroke_id'] in ids]
        gold = row['references'][0]['curves']
        values = {'reference': gold, **{k: curves(glyph_from_dict(v)) for k, v in row['outputs'].items()}}
        labels = ['reference', 'A', 'D', 'M', selected_label]
        titles = ['原稿·仅评估', 'A · 固定 v4', 'D · 完整部件基线', 'M · 原经验范围修正', 'G · 开发冻结 '+selected_label]
        differences = {i: curve_error(values['D'][i], values['M'][i])[1] for i in indices}
        index = max(indices, key=lambda i: differences[i]) if max(differences.values()) > 1e-10 else max(indices, key=lambda i: curve_error(values['D'][i], gold[i])[1])
        cloud = np.asarray([p for label in labels for p in values[label][index]])
        center = (cloud.min(0)+cloud.max(0))/2
        span = max(float(np.ptp(cloud, axis=0).max())*1.3, .12)
        fig, axes = plt.subplots(2, 5, figsize=(16, 7.2))
        for col, label in enumerate(labels):
            color = ['#333', '#2874a6', '#14806a', '#b17637', '#91579f'][col]
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
            axes[0, col].set_title(titles[col], fontsize=10)
            if label != 'reference':
                scores = row['metrics'][label]
                axes[1, col].set_xlabel(f"部件均差 {scores['mean_distance']:.4f}\n末向 {scores['terminal_angle_deg']:.2f}°", fontsize=10)
        char = row['task']['character']
        fig.suptitle(f'{row["writer"]} · {char} · {"开发" if stage == "development" else "已观察回归"} · 局部 s{index+1}\n相同比例，候选与轨迹点固定；G 与 D 重合不代表取得改进', fontsize=13)
        fig.tight_layout(rect=(0, 0, 1, .91))
        name = 'figures/'+row['task']['id']+'.png'
        fig.savefig(args.output / name, dpi=135)
        plt.close(fig)
        block = f'<figure><img loading="lazy" src="{name}"><figcaption>{row["writer"]} / {char}</figcaption></figure>'
        gallery.append(block)
        if row['outputs']['M'] != row['outputs']['D']:
            highlights.append(block)
        print('figure', row['writer'], char, flush=True)
    training_coverage = read(args.training / 'coverage.json')
    coverage_rows = ''.join(f'<tr><td>{w}</td><td>{c["eligible_components"]}</td><td>{c["trials"]}</td><td>{c["labeled"]}</td><td>{c["labeled_characters"]}</td><td>{c["safe_benefit"]}</td><td>{c.get("changed_without_valid_gold",0)}</td></tr>' for w,c in training_coverage.items())
    control = 'observed_'+choice['scope']+'_'+str(choice['threshold']) if selected_label != 'D' else 'D'
    table = []
    for stage in ('development', 'regression'):
        for writer, result in read(getattr(args, stage) / 'summary.json').items():
            for label in dict.fromkeys(['D', 'M', control, selected_label]):
                s = result['component'][label]
                table.append(f'<tr><td>{stage}/{writer}</td><td>{result["n"]}</td><td>{label}</td><td>{s["mean_distance"]:.6f}</td><td>{s["terminal_angle_deg"]:.3f}°</td><td>{s["maximum_character_geometry_ratio"]:.4f}</td><td>{s["maximum_stroke_local_error_increase"]:+.6f}</td><td>{len(s["changed_characters"])}</td><td>{"通过" if s["passes_gates"] else "未通过"}</td></tr>')
    decision_rows = []
    for stage, row in cases:
        if row['outputs']['M'] == row['outputs']['D'] or selected_label == 'D':
            continue
        decision = row['decisions'][selected_label]
        ratio = row['metrics']['M']['mean_distance']/row['metrics']['D']['mean_distance']-1
        support = decision.get('safe_fraction')
        support = '不足' if support is None else f'{support:.3f}'
        decision_rows.append(f'<tr><td>{stage}/{row["writer"]}</td><td>{row["task"]["character"]}</td><td>{100*ratio:+.2f}%</td><td>{"接受 M" if decision["accepted"] else "保留 D"}</td><td>{support}</td></tr>')
    style = '<style>body{font:17px/1.7 system-ui;margin:35px auto;max-width:1500px;padding:0 22px;color:#203040}img{width:100%;height:auto}figure{margin:30px 0}table{border-collapse:collapse;width:100%;font-size:14px}td,th{border:1px solid #ccd5df;padding:7px}th{background:#eef3f7}code{word-break:break-all}</style>'
    assert choice['label'] == 'trial_pooled_0.6', 'revise narrative for another frozen choice'
    content = '<h1>训练内试移对照：布局风险学习扩展实验</h1>'
    content += '<p><strong>结论：获得部分风险区分能力，但仍不能接入正式默认。</strong>冻结的跨作者 0.6 门槛拦住了 wsq「铜」的退化，保留况、淹、绫、附的收益；scx「涤」仍被错误放行。当前不是完整解决方案，也不是新的留出泛化验证。</p>'
    content += '<h2>第一步：覆盖全部相容部件仍没有新增风险标签</h2><p>复用 12 份三折隔离档案，对照从每字一个部件的 914 个扩大到全部 946 个相容部件，原 914 个 A/D/M 输出、来源及诊断按 JSON 表示精确重放。新增部件都未触发原 M，标签仍为 33 个；同字分组后的开发仍回退 D。失败运行 training_v1 保留，最终 all-component 训练为 training_v2。</p>'
    content += '<h2>第二步：只在训练折内增加固定幅度试移</h2><p>对具备来源和布局证据的训练部件，独立尝试 0.05、0.1、0.25、0.5 四档共同等比移动，目的地为公共部件布局。保留同一完整供体及既有安全回退，不逐笔缩放、不混搭。试移允许出现在原经验范围内部，但只用于建立训练监督；实际查询仍只接受或拒绝原 M_D_1.0，不会输出额外试移路径。</p>'
    content += '<table><tr><th>作者/批次</th><th>可试移部件</th><th>试移次数</th><th>有效标签</th><th>作者—字数</th><th>安全收益标签</th><th>改动但缺原稿</th></tr>'+coverage_rows+'</table>'
    content += f'<p>共 {len(examples)} 个有效标签，覆盖 {len({(e["writer"],e["character"]) for e in examples})} 个作者—字、{len({e["character"] for e in examples})} 个不同汉字。多个幅度、部件和重复采样是相关的对照，不是新的自然书写样本。目标折始终排除在自身 v4、来源、布局模型和校准之外，所有试移固定后才读取训练原稿评分。</p>'
    content += '<p>每个作者—字只让距离查询最近的一个部件/试移投票；IQR 特征尺度也先按作者—字取中位数，避免部件多或试移多的字取得更多票。查询同字跨所有作者排除。其余 22 个特征、距离 2、最低 5 票、最多 8 票、标签和质量门槛不变。试移幅度在本轮评分前固定，未按回归结果调节。</p>'
    content += '<h2>开发选择与范围</h2><p>开发还是已有 41 字，其中原 M 仅改动「冗」。同作者风险判断拒绝该改动，合并作者的 8 个近邻中 5 个满足安全收益标签，只有 0.6 门槛通过开发。因此冻结 trial_pooled_0.6；仅凭一个有效改动字选择门槛，证据很弱。跨作者只提供风险监督，输出轨迹的供体仍是目标作者。比例不是自然性概率。</p>'
    content += '<h2>逐作者冻结回归</h2><table><tr><th>阶段/作者</th><th>字数</th><th>路径</th><th>部件均差</th><th>末向均差</th><th>最差字/D</th><th>最差笔局部增量</th><th>改字数</th><th>原门槛</th></tr>'+''.join(table)+'</table>'
    content += '<p>observed_pooled_0.6 是在相同门槛下只用原 33 个实际改动标签的对照；trial_pooled_0.6 使用试移标签。候选、原 D/M、目标名单和生成参数固定，比较的是风险监督资料。各作者分别报告，D 不需严格优于自身。所有回归数据已观察，未据此改门槛、重选模型或新增排除名单。</p>'
    content += '<p>wsq 的冻结 G 虽优于 D，几何均差仍比原 v4 A 高 0.61%，末向也更差；这不是替代当前平滑路径的证据。</p>'
    content += '<h2>全部原 M 改动的接受与拒绝</h2><table><tr><th>阶段/作者</th><th>字</th><th>M 相对 D 几何变化</th><th>冻结决定</th><th>邻近安全票比例</th></tr>'+''.join(decision_rows)+'</table>'
    content += '<p>回归中原 M 提出 12 个改动，冻结模型接受 7 个，其中 6 个几何改善、1 个退化；拒绝的 5 个包含「铜」及禾、四、镐、镩四个原本改善的字。这里是有限实例计数，不能作为总体精度估计。wsq 通过原局部质量门槛，scx 涤仍有 +8.49% 几何退化和 +0.012022 局部增量，因此不批准整体接入。</p>'
    content += '<h2>证据限制和下一步</h2><p>训练对照覆盖不足已显著缓解，但涤在 8 个近邻中有 7 个安全票仍会失败，说明增加标签不能代替合适的判别信息。当前特征主要描述布局和相邻部件关系，没有直接刻画每笔相对 v4 的几何、末向及端点变化。后续应在隔离训练中检验这些特征是否能区分收益与损伤，不能仅提高门槛来躲开已观察反例。交叉拟合/全训练档案分布差异、原稿噪声、作者身份和人工自然性评价限制仍在。</p>'
    content += '<h2>核验</h2><pre>'+html.escape(str(full_audit))+'</pre><p>逐点核对共同正等比变换、源轨迹点数、压力、笔内相对时间、标准 ID/笔顺、有限坐标与字框；跨笔时间重新排成单调序列，无相对 A 新增严格笔间交叉。模型决定可从冻结训练标签精确重放，每字最多一票。未覆盖自交和笔宽接触。G 输出全字段等于对应 D/M，指标逐字段核对后复用既有统一评估；弧长接近不单独等于质量更好。</p>'
    content += '<h2>原稿与实际冻结输出</h2><p>所有列使用相同比例，局部窗口也一致；多次采样按既有记录第一个有效原稿选图，指标按全部有效采样平均。</p>'+''.join(highlights)+'<p><a href="gallery.html">全部 227 字对照图集</a></p>'
    name = args.output / 'InkStruct_训练试移风险对比报告.html'
    name.write_text('<!doctype html><meta charset="utf-8">'+style+content)
    (args.output / 'gallery.html').write_text('<!doctype html><meta charset="utf-8">'+style+'<h1>实际冻结输出：227 字同尺度对照</h1>'+''.join(gallery))
    save(args.output / 'integrity_audit.json', full_audit)
    save(args.output / 'report_manifest.json', {'figures': len(cases), 'highlight_figures': len(highlights),
        'report_code_sha256': sha256_file(Path(__file__)), 'choice': choice})
    print(name, flush=True)


if __name__ == '__main__':
    main()
