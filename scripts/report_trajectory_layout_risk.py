"""Audit inference feature ablation and show every frozen M change at equal scale."""
from __future__ import annotations

import argparse
import html
import os
from collections import Counter
from pathlib import Path

import numpy as np
from experiment_component_trust import glyph_from_dict, read
from regress_calibrated_layout_writers import audit_generated
from report_counterfactual_layout_risk import verify_run
from run_raw_trajectory_experiment import DATABASE, curves, save

from inkstruct.profile import load_profile
from inkstruct.samples import sha256_file
from inkstruct.structures import StructureRepository
from inkstruct.trajectory_experiment import curve_error
from inkstruct.trajectory_layout_risk import TrajectoryLayoutRiskGate, stroke_geometry_features

CONTROL = 'g0.0_pooled_0.6'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('training', 'development', 'regression', 'output'):
        parser.add_argument('--'+key, type=Path, required=True)
    args = parser.parse_args()
    protocol = read(args.training / 'run_protocol.json')
    for group in ('input_sha256', 'code_sha256'):
        for path, expected in protocol[group].items():
            assert sha256_file(Path(path)) == expected, path
    prior = Path(protocol['prior'])
    verify_run(prior)
    old_examples, examples = read(prior / 'examples.json'), read(args.training / 'examples.json')
    assert len(old_examples) == len(examples)
    cache = {}
    for i, (old, new) in enumerate(zip(old_examples, examples, strict=True)):
        assert all(new[k] == v for k, v in old.items() if k != 'features')
        assert new['features'][:22] == new['layout_features'] == old['features']
        trial_path = Path(old['generated_file'])
        assert sha256_file(trial_path) == old['generated_sha256']
        trial = read(trial_path)
        frozen = Path(trial['frozen_input'])
        if frozen not in cache:
            assert sha256_file(frozen) == trial['frozen_input_sha256']
            row = read(frozen)
            cache[frozen] = [glyph_from_dict(row['outputs'][k]) for k in ('A', 'D')]
        feature, evidence = stroke_geometry_features(*cache[frozen], glyph_from_dict(trial['output']), trial['task']['target_stroke_ids'])
        assert feature == new['geometry_features'] == new['features'][22:]
        assert evidence == new['geometry_evidence']
        if (i+1) % 500 == 0:
            print('replayed features', i+1, flush=True)
    del cache
    choice = read(args.development / 'frozen_choice.json')
    for key in ('summary', 'run_protocol'):
        assert choice[key+'_sha256'] == sha256_file(args.development / (key+'.json'))
    # Narrative is deliberately limited to this negative experiment.
    assert choice['label'] == 'D', 'Rewrite interpretation for a positive result'
    gate = TrajectoryLayoutRiskGate(examples)
    repository = StructureRepository(DATABASE)
    audits, cases, decision_replays = {}, [], 0
    for stage in ('development', 'regression'):
        folder = getattr(args, stage)
        p = verify_run(folder)
        assert p['training_examples_sha256'] == sha256_file(args.training / 'examples.json')
        if stage == 'regression':
            assert p['choice'] == choice
        archives = {w: load_profile(Path(path)).source_trajectories for w, path in p['profiles'].items()}
        audit = Counter()
        for path in sorted((folder / 'generated').glob('*.json')):
            row = read(path)
            audit.update(audit_generated(row, archives[row['writer']], repository))
            for label, source in row['selected_labels'].items():
                assert row['outputs'][label] == row['outputs'][source]
            if row['features'] is not None:
                f, e = stroke_geometry_features(*(glyph_from_dict(row['outputs'][k]) for k in ('A', 'D', 'M')), row['task']['target_stroke_ids'])
                assert f == row['geometry_features'] and e == row['geometry_evidence']
                assert row['features'] == row['layout_features']+f
                for label, decision in row['decisions'].items():
                    weight, scope, threshold = label.split('_')
                    restored = gate.predict(row['writer'], row['task']['character'], row['features'],
                        scope=scope, threshold=float(threshold), geometry_weight=float(weight[1:]))
                    assert restored == decision
                    votes = decision.get('neighbors', [])
                    assert len({(e['writer'], e['character']) for e in votes}) == len(votes)
                    assert all(e['character'] != row['task']['character'] for e in votes)
                    decision_replays += 1
            case_path = folder / 'cases' / path.name
            if case_path.exists():
                case = read(case_path)
                assert all(case[k] == v for k, v in row.items())
                cases.append((stage, case))
        assert dict(audit) == read(folder / 'integrity_audit.json')
        audits[stage] = dict(audit)
    audits['feature_replays'] = len(examples)
    audits['decision_replays'] = decision_replays
    audits['zero_weight_control_replays'] = {s: read(getattr(args, s) / 'zero_weight_replay.json') for s in ('development', 'regression')}
    audits['training_scope'] = 'Replayed all geometry features and preserved labels; existing raw trials verified by hashes. Full source audit is in prior counterfactual report.'
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
    blocks, decisions, support = [], [], []
    for stage, row in cases:
        if row['outputs']['M'] == row['outputs']['D']:
            continue
        ids = row['task']['target_stroke_ids']
        indices = [i for i, s in enumerate(row['outputs']['D']['strokes']) if s['standard_stroke_id'] in ids]
        values = {'reference': row['references'][0]['curves'], **{k: curves(glyph_from_dict(v)) for k, v in row['outputs'].items()}}
        labels = ['reference', 'A', 'M', CONTROL, 'D']
        titles = ['原稿 · 仅评估', 'A · 固定 v4', 'M · 原布局调整', '旧风险门控 · 权重 0', '本轮冻结 G = D']
        index = max(indices, key=lambda i: curve_error(values['D'][i], values['M'][i])[1])
        cloud = np.asarray([p for label in labels for p in values[label][index]])
        center = (cloud.min(0)+cloud.max(0))/2
        span = max(float(np.ptp(cloud, axis=0).max())*1.3, .12)
        fig, axes = plt.subplots(2, 5, figsize=(16, 7.2))
        for col, label in enumerate(labels):
            color = ['#333', '#2874a6', '#b17637', '#91579f', '#14806a'][col]
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
        char, writer = row['task']['character'], row['writer']
        fig.suptitle(f'{writer} · {char} · {"开发" if stage == "development" else "已观察回归"} · 局部 s{index+1}\n同一显示比例、固定候选；G 全部保留 D，不能据此宣称学会区分风险', fontsize=13)
        fig.tight_layout(rect=(0, 0, 1, .91))
        filename = 'figures/'+row['task']['id']+'.png'
        fig.savefig(args.output / filename, dpi=135, bbox_inches='tight')
        plt.close(fig)
        blocks.append(f'<figure><img src="{filename}" loading="lazy"><figcaption>{stage}/{writer}：{char}</figcaption></figure>')
        m = row['metrics']['M']['mean_distance']/row['metrics']['D']['mean_distance']-1
        decisions.append(f'<tr><td>{stage}/{writer}</td><td>{char}</td><td>{100*m:+.2f}%</td><td>{row["selected_labels"][CONTROL]}</td><td>D（开发未选出新门控）</td></tr>')
        if stage == 'development':
            for label, d in row['decisions'].items():
                if label.endswith('_0.6'):
                    support.append(f'<tr><td>{label}</td><td>{len(d.get("neighbors", []))}</td><td>{d.get("safe_fraction", "不足")}</td><td>{d["accepted"]}</td></tr>')
    table = []
    for stage in ('development', 'regression'):
        for writer, s in read(getattr(args, stage) / 'summary.json').items():
            for label in ('A', 'D', 'M', CONTROL):
                r = s['component'][label]
                table.append(f'<tr><td>{stage}/{writer}</td><td>{s["n"]}</td><td>{"G=D" if label == "D" else label}</td><td>{r["mean_distance"]:.6f}</td><td>{r["terminal_angle_deg"]:.3f}°</td><td>{r["maximum_character_geometry_ratio"]:.4f}</td><td>{r["maximum_stroke_local_error_increase"]:+.6f}</td></tr>')
    content = '''<h1>笔画几何风险特征：固定输出对照实验</h1>
<p><strong>结果：没有取得新的质量收益，保留完整部件基线 D。</strong>加入每笔几何信息的 24 种配置均未通过开发选择，因此没有将任何正权重门控投入回归。回归中的 G 是预先约定的 D 回退，绝不是新模型成功识别了「涤」。生产默认、正式 CLI 与 Mac 入口保持原样。</p>
<h2>跨字相同部件如何作为自然变化参照</h2>
<p>同作者在不同字中的同部件实例可提供真实变化范围，但位置、形态、结构角色和邻接笔画也会导致变化。本项目按这些上下文筛选完整部件，不逐笔拼凑。同字重复采样分组，目标原稿仅用于评估。没有 scx/mjb/wsq 同字重复采样；user_001 存在重复记录，但物理作者身份未独立确认。跨字经验范围不是同字自然变异的完整分布。</p>
<p>本轮不是新增自然变化样本：沿用 3,088 个隔离训练试移标签，覆盖 753 个作者—字和 358 个不同汉字；四档试移高度相关。跨作者风险监督不能作为目标作者的自然性概率。</p>
<h2>唯一变量：风险判断的输入特征</h2>
<p>原 22 维布局特征之外，增加 24 维逐笔汇总：D/A 的均差、最大偏差、起终点、末向和弧长误差，以及 M/A 相对 D/A 的变化。统一折线评估，不重采样输出。A 是固定 v4 基线，绝不是真值；与 A 更接近也可能保留 A 的失真。</p>
<p>布局、几何分别按作者—字中位数估计 IQR，再将两个特征块的平均平方距离加权；几何权重取 0、0.25、0.5、0.75、1。权重 0 精确恢复原布局距离，防止添加维度稀释原距离。每个作者—字最多一票，查询同字跨作者先排除，最低 5 票、最多 8 票、距离不超过 2。候选、原 A/D/M、目标布局、标签和质量门槛全部固定。</p>
<h2>开发失败与支持不足</h2>
<p>同作者/跨作者、三个安全票门槛、五个权重共 30 组，其中 24 组有新特征。已有开发集 41 个有效字中，仅「冗」有 M 改动。权重 0 的 pooled/0.6 接受该收益；所有正权重配置拒绝。除纯几何的同作者配置外，正权重配置都不足 5 个近邻；纯几何同作者有 6 票，仅 1 票支持收益。结果更符合“在现有尺度与距离限制下证据稀疏”，不能说明几何信息无用，更不能说明它有效。</p>
<table><tr><th>冗：门槛 0.6</th><th>近邻数</th><th>安全票比例</th><th>接受</th></tr>'''+''.join(support)+'''</table>
<p>未放宽距离、改尺度或降低门槛来挽救此次结果，也未用已观察回归重新选参数。development_v1 保留初次运行；v2 只整理导入顺序后重跑，冻结结果相同。</p>
<h2>开发冻结后的回归对照</h2>
<table><tr><th>阶段/作者</th><th>字数</th><th>路径</th><th>部件均差</th><th>末向均差</th><th>最差字/D</th><th>最差笔局部增量</th></tr>'''+''.join(table)+'''</table>
<p>回归 186 个有效字，G 与 D 全字段相同。旧风险门控接受 7 个改动，包含「涤」退化；本轮全退回 D 会同时失去其余 6 个均差收益。因此“涤不再被改坏”来自关闭调整，不能计为风险判断能力提升。D 自身仍有跨字误差，尤其 wsq D 比 v4 A 更差。本轮没有支持替代当前平滑默认的新证据。</p>
<table><tr><th>阶段/作者</th><th>字</th><th>M 相对 D 均差</th><th>旧门控</th><th>本轮 G</th></tr>'''+''.join(decisions)+'''</table>
<h2>范围、审计与后续方向</h2>
<p>全程复用既有开发/回归数据，不能称为新留出验证；有效开发改动只有一字，参数选择覆盖很弱。报告重新计算全部 3,088 个几何特征并核对原标签不变，重放全部改动查询的门控决定，重新核验开发/回归的完整原始点、共享正等比变换、压力、笔顺、标准 ID、有限坐标、边界、非退化和单调时间。没有相对 A 新增严格笔间交叉；不覆盖自交、共线重合与笔宽接触。训练原轨迹不重生成，本轮校验原文件哈希，其逐点源审计见上一轮报告。</p>
<p>G 输出逐字段等于 D，旧门控等于对应 D/M，随后复用既有统一折线指标。图中采用第一个有效原稿，指标按该字全部有效采样平均。弧长更接近不单独等于质量更高。本轮固定的等比变换未加入横纵独立缩放。</p>
<p>下一步应先在隔离训练折评估特征支持范围与预测增益，区分真实几何风险与跨字布局差异；参数校准完成后再冻结评估。自然性仍需同作者同部件的上下文对照和人工评价。保留完整轨迹的可选路径，但不把本轮全回退视为生产升级。</p>
<pre>'''+html.escape(str(audits))+'''</pre><h2>全部 13 个原 M 改动案例：整字与局部同尺度图</h2>'''+''.join(blocks)
    style = '<style>body{font:17px/1.7 system-ui;margin:35px auto;max-width:1500px;padding:0 22px;color:#203040}img{width:100%;height:auto}figure{margin:30px 0}table{border-collapse:collapse;width:100%;font-size:14px}td,th{border:1px solid #ccd5df;padding:7px}th{background:#eef3f7}pre{white-space:pre-wrap}</style>'
    name = args.output / 'InkStruct_笔画几何风险对比报告.html'
    name.write_text('<!doctype html><meta charset="utf-8">'+style+content)
    save(args.output / 'integrity_audit.json', audits)
    save(args.output / 'report_manifest.json', {'figures': len(blocks), 'scored_cases': len(cases), 'frozen_choice': choice,
        'report_code_sha256': sha256_file(Path(__file__)), 'report_sha256': sha256_file(name)})
    print(name, flush=True)


if __name__ == '__main__':
    main()
