"""Render saved experimental outputs, with equal axes and a complete case gallery."""
from __future__ import annotations

import argparse
import base64
import html
import json
import os
from collections import Counter
from pathlib import Path

import numpy as np


def read(path):
    return json.loads(path.read_text())


def polylines(glyph):
    return [[(p['x'], p['y']) for p in s['points']] for s in glyph['strokes']]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output-name', default='report')
    args = parser.parse_args()
    root = args.input
    out = root / args.output_name
    out.mkdir(exist_ok=False)
    figures = out / 'figures'
    figures.mkdir()
    os.environ.setdefault('MPLCONFIGDIR', str(root / 'matplotlib'))
    os.environ.setdefault('XDG_CACHE_HOME', str(root / 'cache'))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib import font_manager

    font = Path('/System/Library/Fonts/Supplemental/Arial Unicode.ttf')
    if font.exists():
        font_manager.fontManager.addfont(str(font))
        plt.rcParams['font.family'] = font_manager.FontProperties(fname=str(font)).get_name()
    plt.rcParams.update({'font.size': 10, 'svg.fonttype': 'none', 'axes.unicode_minus': False})
    results = read(root / 'results.json')
    plan = read(root / 'plan.json')
    protocol = read(root / 'protocol.json')
    frozen = read(root / 'frozen_parameters.json')
    from inkstruct.profile import load_profile
    from inkstruct.samples import iter_index, sha256_file
    from inkstruct.trajectory_experiment import cumulative, curve_error, stroke_metrics

    sources = load_profile(Path('profiles/source_v1_20261007/scx/profile.json')).source_trajectories
    titles = {'R': '原稿 / Reference', 'A': 'A · v4 adaptive', 'B': 'B · 完整轨迹',
              'C': 'C · 保护性简化', 'M': 'M · 同源压缩对照',
              'B_xy': 'Bxy · 受限宽高比', 'C_xy': 'Cxy · 受限宽高比'}
    colors = {'R': '#222222', 'A': '#0072B2', 'B': '#009E73', 'C': '#D55E00',
              'M': '#8B61A8', 'B_xy': '#009E73', 'C_xy': '#D55E00'}
    cases = {}
    gallery = []

    def draw(ax, lines, label, indices, focus, limits, numbers=False):
        for i, line in enumerate(lines):
            points = np.asarray(line)
            selected = i in indices
            ax.plot(points[:, 0], points[:, 1], color=colors[label] if selected else '#c1c1c1',
                    lw=2 if i == focus else 1.15, alpha=1 if selected else .7,
                    solid_capstyle='round')
            if i == focus:
                ax.scatter(*points[0], marker='o', s=17, c='white', edgecolors=colors[label], zorder=4)
                ax.scatter(*points[-1], marker='s', s=17, c=colors[label], zorder=4)
            if numbers and selected:
                ax.annotate(str(i + 1), points[0], fontsize=7, xytext=(3, 3), textcoords='offset points')
        ax.set(xlim=limits[:2], ylim=limits[2:], aspect='equal')
        ax.invert_yaxis()
        ax.grid(alpha=.16)
        ax.tick_params(labelsize=7)

    def render(case, labels, name, focus=None, category=None, tail_zoom=False):
        task = case['task']
        indices = case['indices']
        if focus is None:
            special = {'岛': 3, '尴': 2}
            hooks = [i for i in indices if case['scores']['B']['strokes'][indices.index(i)]['hook']]
            focus = special.get(task['character'], hooks[0] if hooks else indices[0])
        lines = {'R': case['reference'], **{k: polylines(v) for k, v in case['variants'].items()}}
        zoom_lines = [lines[k][focus] for k in labels]
        if tail_zoom:
            zoom_lines = [line[max(0, int(np.searchsorted(cumulative(line),
                          cumulative(line)[-1] - .045)) - 1):] for line in zoom_lines]
        cloud = np.asarray([p for line in zoom_lines for p in line])
        lo, hi = cloud.min(axis=0), cloud.max(axis=0)
        center = (lo + hi) / 2
        span = max(float((hi - lo).max()) * 1.18, .10)
        zoom = (center[0] - span / 2, center[0] + span / 2,
                center[1] - span / 2, center[1] + span / 2)
        fig, axes = plt.subplots(2, len(labels), figsize=(3 * len(labels), 6.7))
        for col, label in enumerate(labels):
            draw(axes[0, col], lines[label], label, indices, focus, (-.02, 1.02, -.02, 1.02), True)
            draw(axes[1, col], lines[label], label, [focus], focus, zoom)
            axes[0, col].set_title(titles[label])
            if label == 'R':
                caption = '同字：原稿施加共同变换' if task['task'] == 'same' else '跨字：留出原稿仅用于评估'
            else:
                metric = next(s for s in case['scores'][label]['strokes'] if s['order'] == focus + 1)
                angle = metric['terminal_angle_deg']
                caption = f"s{focus + 1}  Δ均={metric['mean_distance']:.4f}\n弧长比={metric['length_ratio']:.3f}  末向={angle:.1f}°"
            axes[1, col].set_xlabel(caption)
        context = task.get('context', '')
        for symbol, readable in {'⿰': '左右', '⿱': '上下', '⿲': '左中右', '⿳': '上中下',
                                 '⿸': '左上包围', '⿺': '左下包围', '⺮': '竹头', '⺼': '月部'}.items():
            context = context.replace(symbol, readable)
        descriptor = ('同字重建' if task['task'] == 'same' else
                      f"整部件迁移 {task['candidate']['character']} → {task['character']} · {context}")
        zoom_label = '末端窗口' if tail_zoom else '局部坐标范围'
        fig.suptitle(f"{task['character']} · {descriptor} · {task['split']}" +
                     (f' · {category}' if category else '') +
                     f'\n上：整字同一字框；下：同一{zoom_label} s{focus + 1}；圆圈起点 / 方块终点', fontsize=13)
        fig.tight_layout(rect=(0, 0, 1, .90))
        for extension in ('png', 'svg'):
            fig.savefig(figures / f'{name}.{extension}', dpi=150, facecolor='white')
        plt.close(fig)
        return name

    for n, record in enumerate(results['records'], 1):
        task = record['task']
        case = read(root / 'cases' / f"{task['id']}.json")
        cases[task['id']] = case
        render(case, ['R', 'A', 'B', 'C', 'M'], task['id'])
        gallery.append(f'<details><summary>{html.escape(task["id"])} · {task["character"]}</summary>'
                       f'<img loading="lazy" src="figures/{task["id"]}.png">'
                       f'<p><a href="../cases/{task["id"]}.json">输出、变换、来源及逐笔指标 JSON</a> · '
                       f'<a href="figures/{task["id"]}.svg">SVG</a></p></details>')
        if n % 32 == 0:
            print(f'rendered {n}/192', flush=True)

    # Audit group isolation, output preservation, and independent evaluation resolution.
    training_chars = {s.character for s in iter_index(root / 'train_index.jsonl')}
    target_chars = {t['character'] for t in plan['tasks'] if t['task'] == 'cross'}
    donor_chars = {t['candidate']['character'] for t in plan['tasks'] if t['task'] == 'cross'}
    assert not training_chars & target_chars
    assert donor_chars <= training_chars
    duplicates = Counter(s.character for s in iter_index(Path('artifacts/samples/scx/index.jsonl')))
    audit = {'training_target_overlap': sorted(training_chars & target_chars),
             'nontraining_donors': sorted(donor_chars - training_chars),
             'repeated_character_groups': sum(v > 1 for v in duplicates.values()),
             'input_hashes': {k: v for k, v in protocol.items() if k.endswith('sha256')},
             'geometry_hash_matches_freeze': sha256_file(Path('src/inkstruct/trajectory_experiment.py')) == frozen['code_sha256'],
             'retention': {}, 'source_fidelity': {}, 'quadrature_sensitivity': {}, 'categories': {},
             'output_glyphs': sum(len(c['variants']) for c in cases.values())}
    for task_name in ('same', 'cross'):
        subset = [c for c in cases.values() if c['task']['task'] == task_name and c['task']['split'] == 'test']
        bpoints = sum(c['scores']['B']['aggregate']['selected_points'] for c in subset)
        cpoints = sum(c['scores']['C']['aggregate']['selected_points'] for c in subset)
        audit['retention'][task_name] = {'B_points': bpoints, 'C_points': cpoints, 'fraction': cpoints / bpoints}
        fidelity = {label: [] for label in ('C', 'M')}
        category_rows = {}
        for case in subset:
            b = polylines(case['variants']['B'])
            for label, fidelity_rows in fidelity.items():
                pred = polylines(case['variants'][label])
                fidelity_rows.extend(stroke_metrics(pred[i], b[i]) for i in case['indices'])
            for row in case['scores']['B']['strokes']:
                for category in row['categories']:
                    entry = category_rows.setdefault(category, {'characters': set(), 'strokes': 0})
                    entry['characters'].add(case['task']['character'])
                    entry['strokes'] += 1
        audit['categories'][task_name] = {k: {'characters': len(v['characters']), 'strokes': v['strokes']}
                                                 for k, v in category_rows.items()}
        audit['source_fidelity'][task_name] = {}
        for label, rows in fidelity.items():
            audit['source_fidelity'][task_name][label] = {
                k: {'mean': float(np.mean([r[k] for r in rows if r[k] is not None])),
                    'p95': float(np.percentile([r[k] for r in rows if r[k] is not None], 95)),
                    'max': float(max(r[k] for r in rows if r[k] is not None))}
                for k in ('max_distance', 'absolute_length_error', 'terminal_angle_deg')}
        # Predetermined first 16 cases, halved integration step. No output or parameter is changed.
        changes, paired_flips = [], 0
        for case in subset[:16]:
            fine = {}
            for label in ('A', 'B', 'C', 'M'):
                p = polylines(case['variants'][label])
                fine[label] = float(np.mean([curve_error(p[i], case['reference'][i], .0015)[0]
                                            for i in case['indices']]))
                changes.append(abs(fine[label] - case['scores'][label]['aggregate']['mean_distance']))
            coarse = case['scores']['B']['aggregate']['mean_distance'] - case['scores']['A']['aggregate']['mean_distance']
            paired_flips += ((fine['B'] - fine['A']) * coarse < 0)
        audit['quadrature_sensitivity'][task_name] = {'characters': 16, 'max_mean_error_change': max(changes),
                                                    'B_vs_A_ranking_flips': paired_flips}
    (out / 'audit.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2) + '\n')

    # Prespecified diagnostics plus transparently selected best/worst held-out transfers.
    exemplars = [('same-dev-U+5C9B', None, '已知长复合笔：岛 s4'),
                 ('same-dev-U+5C34', None, '已知弯折：尴 s3'),
                 ('same-test-U+6B89', 1, '末端微小回折：殉 s2（可能含采集抖动）'),
                 ('same-test-U+4F3C', 3, '短笔观察：似 s4'),
                 ('same-test-U+5549', 5, '直笔观察：啉 s6（按原稿直线度选择）'),
                 ('same-test-U+598D', 1, '圆弯观察：妍 s2（按原稿弧长/弦长选择）'),
                 ('same-test-U+598D', 5, '短钩观察：妍 s6')]
    selected_figures = []
    for case_id, focus, caption in exemplars:
        case = cases[case_id]
        name = 'detail-' + case_id + (f'-s{focus + 1}' if focus is not None else '')
        render(case, ['R', 'A', 'B', 'C', 'M'], name, focus, caption,
               tail_zoom=('钩' in caption or '末端' in caption))
        selected_figures.append((name, caption))
    cross = [c for c in cases.values() if c['task']['task'] == 'cross' and c['task']['split'] == 'test']
    cross.sort(key=lambda c: c['scores']['B']['aggregate']['mean_distance'] - c['scores']['A']['aggregate']['mean_distance'])
    for case, caption in [(cross[0], '留出集几何偏差改善最多'), (cross[-1], '留出集几何偏差退步最多'),
                          (cases['cross-test-U+5F55'], '严格交叉警报案例；不是所有新增交叉都属于错误')]:
        selected_figures.append((case['task']['id'], caption))
        name = 'xy-' + case['task']['id']
        render(case, ['R', 'A', 'B', 'B_xy', 'C_xy'], name)
        selected_figures.append((name, '宽高比敏感性单列：' + caption))

    # Matched donor panels expose the real instance, without replacing other target strokes.
    for case in (cross[0], cross[-1]):
        task = case['task']
        donor = sources[task['candidate']['sample_id']]
        donor_ids = set(task['candidate']['stroke_ids'])
        indices = [i for i, s in enumerate(donor.strokes) if s.standard_stroke_id in donor_ids]
        fig, axes = plt.subplots(1, 3, figsize=(10, 3.6))
        draw(axes[0], [s.points for s in donor.strokes], 'R', indices, indices[0], (0, 1, 0, 1), True)
        draw(axes[1], polylines(case['variants']['B']), 'B', case['indices'], case['indices'][0], (0, 1, 0, 1), True)
        draw(axes[2], case['reference'], 'R', case['indices'], case['indices'][0], (0, 1, 0, 1), True)
        for ax, title in zip(axes, [f'训练原稿 {donor.character}', f"B 目标 {task['character']}", '留出原稿（仅评估）'], strict=True):
            ax.set_title(title)
        fig.tight_layout()
        name = 'donor-' + task['id']
        fig.savefig(figures / f'{name}.png', dpi=160)
        plt.close(fig)
        selected_figures.append((name, '供体与目标：整部件采用同一个平移、等比缩放'))

    fig, axes = plt.subplots(1, 3, figsize=(13, 4.5))
    keys = ['mean_distance', 'terminal_angle_deg', 'donor_fidelity_mean_distance']
    for ax, key_name, ylabel in zip(axes, keys, ['对目标原稿的距离 / 字框单位', '对目标原稿的末向误差 / °', '对同一源部件的距离 / 字框单位'], strict=True):
        values = [[c['scores'][label]['aggregate'][key_name] for c in cross] for label in ('A', 'B', 'C', 'M')]
        for i, (label, vals) in enumerate(zip(('A', 'B', 'C', 'M'), values, strict=True)):
            ax.scatter(i + np.linspace(-.13, .13, len(vals)), vals, s=10, c=colors[label], alpha=.5)
            ax.plot([i - .2, i + .2], [np.median(vals)] * 2, color='black', lw=2)
        ax.set_xticks(range(4), ['A', 'B', 'C', 'M'])
        ax.set_ylabel(ylabel)
        ax.grid(axis='y', alpha=.2)
        ax.set_ylim(bottom=0)
    fig.suptitle('跨字留出集：64 个目标字，每点为一个字的所迁移部件；黑线为中位数')
    fig.tight_layout(rect=(0, 0, 1, .92))
    fig.savefig(figures / 'heldout-summary.png', dpi=160)
    fig.savefig(figures / 'heldout-summary.svg')
    plt.close(fig)

    def table(task, labels):
        rows = []
        for label in labels:
            row = results['summaries'][task][label]
            m = row['metrics']
            rows.append(f"<tr><td>{label}</td><td>{m['mean_distance']['mean']:.5f}</td>"
                        f"<td>{m['absolute_length_error']['mean']:.2%}</td><td>{m['terminal_angle_deg']['mean']:.2f}°</td>"
                        f"<td>{m['hook_length_error']['mean']:.5f} (n={m['hook_length_error']['n']})</td>"
                        f"<td>{m['selected_points']['mean']:.1f}</td><td>{row['characters_with_new_crossings_vs_A']}</td></tr>")
        return '<div class="table-scroll"><table><tr><th>路径</th><th>平均几何偏差</th><th>平均绝对弧长相对差</th><th>平均末向误差</th><th>钩尾长度差</th><th>所评估笔画点数/字</th><th>比 A 新增交叉的字数</th></tr>' + ''.join(rows) + '</table></div>'

    def embedded(name, caption):
        encoded = base64.b64encode((figures / f'{name}.png').read_bytes()).decode()
        return f'<figure><a href="figures/{name}.png"><img src="data:image/png;base64,{encoded}" alt="{html.escape(caption)}"></a><figcaption>{html.escape(caption)}</figcaption></figure>'

    style = '''<style>body{font:16px/1.7 -apple-system,BlinkMacSystemFont,"Arial Unicode MS",sans-serif;max-width:1450px;margin:32px auto;padding:0 24px;color:#202630}h1{font-size:30px}h2{margin-top:42px}img{width:100%;height:auto}.table-scroll{overflow-x:auto}table{min-width:780px;border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}td,th{padding:9px;border-bottom:1px solid #ccd4de;text-align:left}th{background:#edf2f7}figure{margin:30px 0}figcaption{font-size:14px;color:#46505b}details{border-bottom:1px solid #ddd;padding:10px}a{color:#075aa6}.lead{padding:18px;background:#eaf1f7;border-left:5px solid #0072b2}.warning{padding:18px;background:#fff4e6}code{background:#eee;padding:2px 5px}</style>'''
    body = '''<h1>InkStruct 完整轨迹直接变换：实际实验与效果对比</h1><p>2026-10-07 · scx · Mac CPU · 独立实验路径 · 生产默认保持不变</p>
    <p class="lead"><b>结论：值得接入高保真表示，但不宜整体替代当前跨字生成器。</b>直接变换能保住供体的折角、短钩与末端方向；本次跨字留出集的目标适配仍弱于 A。需要先解决候选实例和布局，而不是继续把源轨迹压成 8 点。</p>
    <h2>实验范围与防泄漏</h2><p>793 个字符按字符哈希分为训练 458、开发 179、留出 156；同字重复样本整组分配。高保真档案可用 778 个样本。实际同字/跨字各 32 个开发案例、64 个留出案例，总计 192 案例。岛、尴已知问题强制归入开发集。156 个留出字中有 154 个高保真有效样本，其中 62 个没有兼容训练供体；从其余 92 个按上下文轮转选 64 个，本结论仅针对该受限子集。跨字仅替换一个真实叶部件；其他笔画沿用 A，指标只聚合被替换笔画。候选必须同作者、同部件变体/位置/父布局/笔数；所有笔画共用一个变换。</p>
    <p>同字 A 固定原有完整档案和 adaptive 参数。原档案含有跨字目标样本，直接沿用会泄漏，因此跨字 A 仅用训练组重建一次并冻结（454 个成功入档样本），生成算法和参数仍固定。B/C 与 A 的候选、原型平均和内部布局无法严格相同；增设 M：同一真实供体、同一布局，16→8→B-Spline，不做原型平均，用于隔离轨迹表示损失。M 不是生产 A。</p>
    <p>B 保留完整原始归一化轨迹；C 保护端点、末段、稳定折点后做有界简化。开发集选定 ε=0.004，不再用留出数据调参。C 若改变源部件的严格笔间交叉集合，则整部件退回 B。等比缩放和平移为主实验；宽高比最多 1.15 的横纵缩放另表。</p>
    <h2>同字重建：64 字留出描述结果</h2><p>参考原稿与 B 使用同一个全字等比变换，便于隔离形状损伤。因此 B 接近零误差是恒等复用的预期结果，不能作为跨字泛化证据。同字“留出”仅指简化参数未在这些字上确定，A 原有完整档案仍可能包含这些字。</p>'''
    body += table('same_test', ['A', 'B', 'C', 'M'])
    body += '''<p>C 总点数由 18,790 减到 8,605（减少 54.2%），而 M 总体仍损失短弯与端部形状。圆弯经 C 简化后可能更显折线化，低误差不自动等于更自然。点数更多不代表信息更完整：M 在压缩后插值增加的点不能恢复丢失的角点。弧长保持仅反映保真，原稿抖动也可能被保留。</p>
    <h2>跨字迁移：64 个留出目标字</h2><p>B 平均几何偏差比 A 增大 14.2%，21/64 改善、43/64 退步；C 为 20/64 改善。B 的平均末端方向误差从 20.00° 降到 18.29°，但这不抵消布局和部件比例偏差。B 与同供体 M 比较，平均几何偏差仅降低约 1.08%，说明本轮主要瓶颈不是压缩本身。供体保真也不等于目标适配或主观风格更好。</p>'''
    body += table('cross_test', ['A', 'B', 'C', 'M'])
    body += embedded('heldout-summary', '所有留出目标字的分布，未剔除失败案例；不将笔画或采样点当作独立作者样本。')
    body += '''<h2>受限宽高比：独立敏感性实验</h2><p>不与等比结果混算。Bxy 几何偏差比 B 低约 2.84%，仍比 A 高 10.95%；末向误差略回升，新增交叉警报增至 7 字。不能据此全面放开非等比缩放。</p>'''
    body += table('cross_test', ['B_xy', 'C_xy', 'M_xy'])
    body += '''<h2>图像对比与来源</h2><p>整字均使用相同归一化坐标及显示比例；每组局部放大共用范围。未重采样输出用于绘图。圆圈为起点、方块为终点；跨字生成图的灰色笔画沿用 A；参考图的灰色笔画来自目标原稿。点击图片可查看原尺寸。除岛/尴外，细节案例按原稿形态事后选取，仅作解释；短钩另放大末端，殉的微小回折可能含抖动。下列案例包括预先指定的岛/尴，以及明确标记的留出集最好、最差和交叉警报；完整 192 案例另见图集。</p>'''
    for name, caption in selected_figures:
        body += embedded(name, caption)
    body += '''<h2>评估口径与局限</h2><p>统一使用弧长积分的双向点到线段距离，而不是逐点配对；最大距离包括全部原始顶点和间隔≤0.003 的积分点，是离散近似而非精确 Hausdorff，最大值可能低估至多约 0.0015。末向使用相同物理弧长窗口。短钩使用两尺度转角的操作性检测与最近点尾段投影，不是人工语义标注；跨字留出仅 3 个字命中，不能据此宣称短钩泛化改善。</p>
    <p>本实验记录的是严格笔间横穿交叉，排除端点接触、相切和共线重叠；不覆盖自交或所有视觉粘连。比原稿多交叉不自动等于错误，原作者跨字实例可能本来就有连接习惯。B/C 跨字各有 6 字比 A 新增交叉警报；其中啖、绵恢复了原稿已有交叉，羸、襁、桩出现原稿未有的内部交叉，录还出现部件与外部笔画的新交叉。全部 1056 个输出通过笔数、标准 ID、顺序、有限坐标、字框边界、压力范围及全局单调时间检查；未出现评估笔画退化或缩到原长 10% 以下。C 的拓扑回退：同字开发 3、同字留出 2、跨字开发等比 2 / 非等比 2、跨字留出 0。</p>
    <p>另已逐点核验 576 个 B/C 输出中的 68,815 个源点索引：坐标变换、压力及重排后的笔内相对时间均吻合。完整高保真档案虽然包含留出记录，但跨字候选池、训练 A 和布局构造仅使用训练字/标准结构；目标轨迹只在生成完成后进入评分。额外测试把目标轨迹完全移除仍可完成跨字生成。单作者、单次采集、有限部件，没有盲评、识别器评估或多作者统计；本报告提供几何证据，不声称书写风格识别质量得到统计证明。</p>
    <h2>接入建议</h2><ol><li>先接入可选的原始部件表示与 C 编码，保存变长点列、压力和源索引；优先同字回放、已验证的同形同位置部件。保留现有默认路径。</li><li>为候选选择与目标布局建立独立开发/留出验证。使用部件内比例、邻笔间距及上下文兼容性筛选；低置信度、退化、越界或新增冲突回退 A。</li><li>只在通过固定回归和人工盲评的部件上灰度启用；宽高比调整单独开关。扩展多作者和独立重复采集后，再讨论默认替换。</li></ol>
    <p><a href="gallery.html">完整 192 案例图集</a> · <a href="../per_character.csv">逐字指标 CSV</a> · <a href="../results.json">完整结果 JSON</a> · <a href="../plan.json">候选来源与冻结计划</a> · <a href="audit.json">隔离与评估审计</a> · <a href="../frozen_parameters.json">开发集参数选择</a> · <a href="../integrity_verification.json">逐点来源核查</a></p>'''
    document = '<!doctype html><html lang="zh-CN"><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>完整轨迹变换效果报告</title>' + style
    (out / 'InkStruct_原始轨迹变换实验报告.html').write_text(document + '<body>' + body + '</body></html>', encoding='utf-8')
    (out / 'gallery.html').write_text(document + '<body><h1>完整案例图集 · 192 案例</h1><p>固定顺序，所有结果均保留。</p>' + ''.join(gallery) + '</body></html>', encoding='utf-8')
    print(json.dumps(audit, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
