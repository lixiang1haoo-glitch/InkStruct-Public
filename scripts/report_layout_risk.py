"""Audit crossfit isolation and report the frozen risk-gate experiment."""
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

from inkstruct.layout_risk import training_fold
from inkstruct.profile import load_profile
from inkstruct.samples import iter_index, sha256_file
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
    choice = read(args.development / 'frozen_choice.json')
    assert choice['label'] == 'D', 'rewrite the negative-result narrative for a different frozen choice'
    for key in ('summary', 'run_protocol'):
        assert choice[key+'_sha256'] == sha256_file(args.development / (key+'.json'))
    assert protocols['regression']['choice'] == choice
    repo = StructureRepository(DATABASE)
    audit, fold_counts = Counter(), []
    for manifest in sorted(args.training.glob('*/fold_*/fold_manifest.json')):
        m = read(manifest)
        root = manifest.parent
        assert sha256_file(Path(m['profile'])) == m['profile_sha256']
        assert sha256_file(root / 'index.jsonl') == m['index_sha256']
        train, target = set(m['training_characters']), set(m['target_characters'])
        assert not train & target
        assert {s.character for s in iter_index(root / 'index.jsonl')} == train
        assert all(training_fold(c) != m['fold'] for c in train)
        assert all(training_fold(c) == m['fold'] for c in target)
        sources = load_profile(Path(m['profile'])).source_trajectories
        assert all(s.character in train for s in sources.values())
        for path in (root / 'generated').glob('*.json'):
            row = read(path)
            assert row['task']['character'] in target
            assert all(ref['character'] in train for ref in row['predictions']['learned'].get('reference_sources', []))
            audit.update(audit_generated(row, sources, repo))
        fold_counts.append({'writer': root.parent.name, 'fold': m['fold'], 'train_characters': len(train), 'target_characters': len(target)})
    assert dict(audit) == read(args.training / 'integrity_audit.json')
    print('training isolation verified', len(fold_counts), dict(audit), flush=True)
    full_audit = {'training': dict(audit), 'folds': fold_counts}
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
    training_table = ''.join(f'<tr><td>{w}</td><td>{c["generated"]}</td><td>{c["changed"]}</td><td>{c["labeled"]}</td><td>{c["safe_benefit"]}</td><td>{c.get("changed_without_valid_gold",0)}</td></tr>' for w, c in training_coverage.items())
    score_rows = []
    for stage in ('development', 'regression'):
        for writer, s in read(getattr(args, stage) / 'summary.json').items():
            for label in ('D', 'M', selected_label):
                v = s['component'][label]
                title = 'G（冻结 D）' if label == selected_label == 'D' and any(r.startswith(f'<tr><td>{stage}/{writer}') for r in score_rows) else label
                score_rows.append(f'<tr><td>{stage}/{writer}</td><td>{s["n"]}</td><td>{title}</td><td>{v["mean_distance"]:.6f}</td><td>{v["terminal_angle_deg"]:.3f}°</td><td>{len(v["changed_characters"])}</td></tr>')
    examples = read(args.training / 'examples.json')
    style = '<style>body{font:17px/1.7 system-ui;margin:35px auto;max-width:1450px;padding:0 22px;color:#203040}img{width:100%;height:auto}figure{margin:30px 0}table{border-collapse:collapse;width:100%;font-size:15px}td,th{border:1px solid #ccd5df;padding:7px}th{background:#eef3f7}code{word-break:break-all}</style>'
    content = '<h1>按字交叉拟合：布局改动风险实验</h1>'
    content += '<p><strong>结论：开发未支持启用风险门控，冻结回退 D。没有证明新算法能保留收益并可靠拦截误伤。</strong>生产默认及正式生成入口不变。</p>'
    content += f'<p>实际构建 12 份隔离 v4/完整轨迹档案，生成 914 字训练对照；只有 {len(examples)} 个作者—字有效改动对照，涉及 {len({e["character"] for e in examples})} 个不同字，其中 {sum(e["safe_benefit"] for e in examples)} 个满足训练安全收益条件。未把每个点或重复采样当独立样本。</p>'
    content += '<h2>训练证据</h2><table><tr><th>作者/批次</th><th>生成字数</th><th>M 改动</th><th>有效对照</th><th>安全收益</th><th>缺有效原稿</th></tr>'+training_table+'</table>'
    content += '<p>原训练字按字符哈希分三折，同字各作者及全部重复进入同一折。每折从其他两折重建 v4 与源档案，布局模型、校准和候选均排除目标折。全体输出固定后才加载训练原稿评分；同字重复先平均。有效训练条件为几何改善、各笔最大局部增量 ≤0.005、该字末向均差增量 ≤0.5°。</p>'
    content += '<p>22 个特征只描述公共部件位置/大小、已有 D、提议 M、经验范围以及最近不相交叶部件的中心和间隙关系。决策采用训练特征 IQR 标准化的最近邻，至多 8 个、距离不超过 2、至少 5 个有效作者—字对照；门槛 0.6/0.8/1.0 和同作者/合并作者共六种配置只在开发比较。安全票比例不是自然性概率。未单独验证邻接特征贡献。</p>'
    content += '<h2>为何开发退回原路径</h2><p>41 个有效开发字中，原 M 仅改动「冗」。user_001 自身训练只有 2 个有效改动对照；合并 33 个对照后，距「冗」足够近的也仅有 wsq「恐」1 个，低于预设最少 5 个。六种配置均放弃，因此与 D 完全一致。没有为保留冗的收益而降低样本数或扩大距离。</p>'
    content += '<h2>固定输出对比</h2><table><tr><th>阶段/作者</th><th>字数</th><th>路径</th><th>部件均差</th><th>末向均差</th><th>相对 D 改字数</th></tr>'+''.join(score_rows)+'</table>'
    content += '<p>回归为 user_001 42 字及 scx/mjb/wsq 144 字已有观察资料。冻结 D 的 186 字全字段未变，属于回退完整性核验；不能据此声称模型成功识别了涤/铜。未在回归上重新挑选门槛或更换模型。M 的已知收益和退化仍完整展示。图示使用既有记录中的第一个有效原稿，指标仍先按字内全部有效采样平均。</p>'
    content += '<h2>限制与下一步</h2><p>缺陷主要是有标签的改动对照过少：训练只对每字候选最多的一个部件提出改动，覆盖偏向常见侧旁；mjb 9 个改动中 7 个缺有效原稿。交叉拟合仅用三分之二资料，而正式查询使用原完整训练档案，存在分布差异。下一步应在不改变字分组的前提下覆盖训练字中的全部相容部件，并控制同字多部件的权重；不能把当前无改动写成质量突破。user_001 仍为作者身份未独立确认的归档批次。</p>'
    content += '<h2>来源与不变量核验</h2><pre>'+html.escape(str({k:v for k,v in full_audit.items() if k!='folds'}))+'</pre>'
    content += '<p>保留笔数、标准 ID、顺序、全量源点、压力、笔内相对时间；按输出笔顺重排全局时间，共同正等比变换，无新增严格笔间交叉。交叉检查不覆盖自交/笔宽接触。G 只是从已核验 D/M 选择，没有二次采样或几何修改；评分按对应固定输出逐字段核对后复用既有统一评估，不把弧长接近当质量结论。</p>'
    content += '<h2>所有 M 曾提出改动的字</h2>'+''.join(highlights)+'<p><a href="gallery.html">全部 227 个开发/回归字图集</a></p>'
    name = args.output / 'InkStruct_交叉拟合布局风险实验报告.html'
    name.write_text('<!doctype html><meta charset="utf-8">'+style+content)
    (args.output / 'gallery.html').write_text('<!doctype html><meta charset="utf-8">'+style+'<h1>相同比例的整字与局部对照</h1>'+''.join(gallery))
    save(args.output / 'integrity_audit.json', full_audit)
    save(args.output / 'report_manifest.json', {'figures': len(cases), 'highlight_figures': len(highlights),
        'report_code_sha256': sha256_file(Path(__file__)), 'choice': choice})
    print(name, flush=True)


if __name__ == '__main__':
    main()
