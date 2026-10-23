"""Same-scale full glyph and local figures for frozen multiwriter layout regression."""
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

from inkstruct.learned_component_layout import layout_summary
from inkstruct.profile import load_profile
from inkstruct.samples import sha256_file
from inkstruct.structures import StructureRepository
from inkstruct.trajectory_experiment import curve_error


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    protocol = read(args.input / 'run_protocol.json')
    for section in ('input_sha256', 'code_sha256'):
        for name, expected in protocol[section].items():
            assert sha256_file(Path(name)) == expected, name
    manifest = read(args.input / 'generation_manifest.json')
    for name, expected in manifest.items():
        assert sha256_file(Path(name)) == expected, name
    summary, coverage = read(args.input / 'summary.json'), read(args.input / 'coverage.json')
    repository = StructureRepository(DATABASE)
    sources = {w: load_profile(args.input / 'training' / (w+'.json')).source_trajectories for w in summary}
    rows = [read(p) for p in sorted((args.input / 'cases').glob('*.json'))]
    audit = Counter()
    for row in rows:
        audit.update(audit_generated(row, sources[row['writer']], repository))
        assert {k: row[k] for k in read(args.input / 'generated' / (row['task']['id']+'.json'))} == read(args.input / 'generated' / (row['task']['id']+'.json'))
    assert dict(audit) == read(args.input / 'integrity_audit.json')
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
    changed, gallery, diagnosis = [], [], []
    for row in rows:
        labels = ['reference', 'A', 'D', 'B', 'M']
        titles = ['原稿·仅评估', 'A · 固定 v4', 'D · 固定完整部件', 'B · 向学习中心', 'M · 冻结公共中心方案']
        xy = {'reference': row['reference'], **{k: curves(glyph_from_dict(v)) for k, v in row['outputs'].items()}}
        indices = [i for i, s in enumerate(row['outputs']['A']['strokes']) if s['standard_stroke_id'] in row['task']['target_stroke_ids']]
        # Show largest geometric change, or most discrepant D stroke if nothing changed.
        changes = {i: curve_error(xy['M'][i], xy['D'][i])[1] for i in indices}
        index = max(indices, key=lambda i: changes[i]) if max(changes.values()) > 1e-10 else max(indices, key=lambda i: curve_error(xy['D'][i], xy['reference'][i])[1])
        points = np.asarray([p for label in labels for p in xy[label][index]])
        center = (points.min(0)+points.max(0))/2
        span = max(float(np.ptp(points, axis=0).max())*1.3, .12)
        fig, axes = plt.subplots(2, 5, figsize=(16, 7.2))
        for col, label in enumerate(labels):
            color = ['#333333', '#2874a6', '#14806a', '#ad7734', '#985594'][col]
            for line in range(2):
                ax = axes[line, col]
                for i, stroke in enumerate(xy[label]):
                    a = np.asarray(stroke)
                    ax.plot(a[:, 0], a[:, 1], color=color if i in indices else '#c1cad2', lw=1.7 if i == index else 1.)
                    if i == index:
                        ax.scatter(*a[-1], color=color, s=12)
                ax.set_aspect('equal')
                ax.set_xlim((-.02, 1.02) if line == 0 else (center[0]-span/2, center[0]+span/2))
                ax.set_ylim((1.02, -.02) if line == 0 else (center[1]+span/2, center[1]-span/2))
                ax.grid(alpha=.15)
                ax.tick_params(labelsize=7)
            axes[0, col].set_title(titles[col], fontsize=11)
            if label != 'reference':
                m = row['metrics'][label]
                axes[1, col].set_xlabel(f"部件均差 {m['mean_distance']:.4f}\n末向 {m['terminal_angle_deg']:.2f}°", fontsize=10)
        writer, char = row['writer'], row['task']['character']
        fig.suptitle(f'{writer} · {char} · 已观察回归 · 局部 s{index+1}\n同一显示比例；整部件共享变换；A / D 与候选实例固定', fontsize=13)
        fig.tight_layout(rect=(0, 0, 1, .91))
        name = 'figures/'+row['task']['id']+'.png'
        fig.savefig(args.output / name, dpi=135)
        plt.close(fig)
        delta = 100*(row['metrics']['M']['mean_distance']/row['metrics']['D']['mean_distance']-1)
        changed_flag = row['outputs']['M'] != row['outputs']['D']
        caption = f'{writer} · {char}：M 相对 D 部件几何偏差 {delta:+.2f}%；'+('有调整' if changed_flag else '全部字段不变')
        block = f'<figure><img src="{name}" loading="lazy"><figcaption>{caption}</figcaption></figure>'
        gallery.append(block)
        if changed_flag:
            changed.append(block)
            pred = row['predictions']['learned']
            gold_center, gold_span, _ = layout_summary([row['reference'][i] for i in indices])
            z = np.r_[gold_center-np.asarray(pred['center']), np.log(gold_span/pred['span'])]/pred['response_dispersion']
            diagnosis.append({'writer': writer, 'character': char,
                'geometry_change_percent': delta, 'tier': pred['tier'],
                'gold_distance': float(np.linalg.norm(z)),
                'radius': row['metadata']['B']['layout_band']['radius'],
                'original_distance': row['metadata']['B']['layout_band']['distance_before'],
                'scope': 'post-hoc diagnosis only; not used by generation or parameter selection'})
        print('figure', writer, char, flush=True)
    table = []
    for writer, result in summary.items():
        for label in ('A', 'D', 'B', 'M'):
            m = result['component'][label]
            table.append(f'<tr><td>{writer} / {result["n"]}</td><td>{label}</td><td>{m["mean_distance"]:.6f}</td><td>{m["terminal_angle_deg"]:.3f}°</td><td>{m["maximum_character_geometry_ratio"]:.4f}</td><td>{m["maximum_stroke_local_error_increase"]:+.6f}</td><td>{len(m["changed_characters"])}</td><td>{"通过" if m["passes_prior_quality_gates"] else "未通过"}</td></tr>')
    cal = ''.join(f'<li>{w}：训练 {c["training_characters"]} 字 / {c["training_captures"]} 条，校准 {c["calibration_characters"]} 字，经验半径 {c["radius"]:.4f}；预测层次 {html.escape(str(c["prediction_tiers"]))}。</li>' for w, c in coverage.items())
    style = '<style>body{font:17px/1.7 system-ui;margin:35px auto;max-width:1450px;padding:0 22px;color:#203040}img{width:100%;height:auto}figure{margin:30px 0}table{border-collapse:collapse;width:100%;font-size:15px}td,th{border:1px solid #ccd5df;padding:7px}th{background:#eef3f7}code{word-break:break-all}</style>'
    intro = '''<h1>冻结布局规则：scx / mjb / wsq 回归报告</h1>
<p>本轮检验同作者不同字的部件布局经验能否支持保守修正，保持原来的 A、D、部件供体、目标布局来源和标称强度不变。M 是上轮开发已冻结的方案：训练经验决定移动幅度，同一完整部件朝公共布局移动；B 是同幅度朝学习布局的诊断对照，不在本轮重新选择胜者。</p>
<p><strong>这是已有样本回归，不是新的留出验证。</strong>每个字现有一次采样；任务名单沿用历史原稿映射合格的样本，不能声称全量目标盲选。旧文件包含原稿，但推理前用白名单去除原稿、指标和目标采样 ID，训练轨迹按字过滤；全部 144 字输出落盘后才加载原稿评分。没有调整参数或根据本轮失败添加排除名单。</p>
<p>每位作者分别用自己的训练字留一计算经验 90% 分位数，沿用相同算法与阈值，不复制 user_001 的具体数值半径。相同部件证据不足时回退到相同角色和父布局，故不能把所有预测都称为同部件比较，也不能把经验分位数称为自然性概率。</p>'''
    failed = [w for w, r in summary.items() if not r['component']['M']['passes_prior_quality_gates']]
    conclusion = '<p><strong>结论：冻结 M 在 '+ '、'.join(failed)+' 未通过原有质量门槛，不能接入正式默认。平均收益无法替代局部保护。</strong>144 字中仅 9 字发生调整，135 字与 D 全字段一致；这证明路径保守，但没有证明改动可靠。</p>'
    diagnosis_table = ''.join(f'<tr><td>{d["writer"]} / {d["character"]}</td><td>{d["geometry_change_percent"]:+.2f}%</td><td>{d["tier"]}</td><td>{d["gold_distance"]:.4f}</td><td>{d["radius"]:.4f}</td></tr>' for d in diagnosis)
    content = intro+conclusion+'<h2>逐作者结果</h2><table><tr><th>作者 / 字数</th><th>路径</th><th>部件几何均差</th><th>末向均差</th><th>最差字/D</th><th>最差笔局部增量</th><th>相对 D 改字数</th><th>原质量门槛</th></tr>'+''.join(table)+'</table>'
    content += '<p>门槛：均差严格改善、末向不超过 D +0.5°、每字几何不超过 1.05D、每笔最大局部偏差增量不超过 0.005、来源启用数不减少。D 作为基线不会“严格优于自身”；无改动也不能称为改善。几何单位为归一化字框坐标，角度以度计；单字内先平均部件笔画，再按字平均，不将采样点数当样本数。</p>'
    content += '<h2>训练证据与核验</h2><ul>'+cal+'</ul><p>'+html.escape(str(dict(audit)))+'</p>'
    content += '<p>逐点核对完整轨迹、压力和笔内相对时间；全局时间按笔顺重排。检查笔数、标准 ID、有限坐标、字框、退化和严格笔间交叉，关闭路径与 D 全字段一致。交叉检查不覆盖笔宽接触、自交；短钩采用既有操作性末端弯曲指标，并非人工语义标注。弧长差异不单独代表质量。</p>'
    content += '<h2>为何经验范围也会误伤</h2><p>下表只在生成和评分之后诊断。scx「涤」与 wsq「铜」的真实原稿也在经验范围之外，且两者都使用相同部件参考。将偏离群体参考中心视为错误，会压掉真实作者在特定字中的布局差异。不得利用这些原稿诊断结果回调本轮参数或添加字名单。</p><table><tr><th>作者 / 字</th><th>M 几何变化</th><th>参考层次</th><th>原稿到经验中心距离</th><th>经验半径</th></tr>'+diagnosis_table+'</table>'
    content += '<h2>M 实际改变的全部案例</h2>'+(''.join(changed) or '<p>所有输出与 D 相同。</p>')
    content += '<p><a href="gallery.html">全部 144 字同尺度整字与局部放大图</a>。生成记录、输入哈希、供体来源、变换、回退原因、逐笔误差与整字指标见旁边实验目录。生产默认及正式入口未修改。</p>'
    (args.output / 'InkStruct_三作者冻结布局回归报告.html').write_text('<!doctype html><meta charset="utf-8">'+style+content)
    (args.output / 'gallery.html').write_text('<!doctype html><meta charset="utf-8">'+style+'<h1>全部 144 字：固定比例对照</h1>'+''.join(gallery))
    save(args.output / 'integrity_audit.json', dict(audit))
    save(args.output / 'posthoc_diagnosis.json', diagnosis)
    save(args.output / 'report_manifest.json', {'input_summary_sha256': sha256_file(args.input / 'summary.json'),
         'report_code_sha256': sha256_file(Path(__file__)), 'figures': len(rows), 'changed_figures': len(changed)})
    print(args.output / 'InkStruct_三作者冻结布局回归报告.html', flush=True)


if __name__ == '__main__':
    main()
