"""Render all reviewed local-repair cases, including failures, at common scales."""
from __future__ import annotations

import argparse
import html
import json
import os
from itertools import pairwise
from pathlib import Path

import numpy as np

LABELS = {'translation': '已复核交叉：有界平移', 'exemplar': '真实整部件：共同等比变换',
          'outline_override_raw': '轮廓推导：未加交叉保护', 'outline_override': '轮廓推导：加入交叉保护'}


def curves(glyph):
    return [np.array([(p['x'], p['y']) for p in s['points']]) for s in glyph['strokes']]


def pairs(values):
    return '、'.join(f's{a + 1}/s{b + 1}' for a, b in values) or '无'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--benchmark', type=Path)
    args = parser.parse_args()
    output = args.output or args.input / 'report'
    output.mkdir(exist_ok=False)
    (output / 'figures').mkdir()
    os.environ.setdefault('MPLCONFIGDIR', str(output / '.mpl'))
    os.environ.setdefault('XDG_CACHE_HOME', str(output / '.cache'))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    from matplotlib.path import Path as Polygon
    font = Path('/System/Library/Fonts/Supplemental/Arial Unicode.ttf')
    if font.exists():
        font_manager.fontManager.addfont(str(font))
        plt.rcParams['font.family'] = 'Arial Unicode MS'
    plt.rcParams['axes.unicode_minus'] = False
    records = [json.loads(p.read_text()) for p in sorted((args.input / 'cases').glob('*.json'))]
    cards = []
    for record in records:
        before, after = curves(record['before']), curves(record['after'])
        standard = [np.array(s['median']) for s in record['standard']['strokes']]
        changed = {int(s[1:]) - 1 for s in record['changed_geometry_ids']}
        focus = changed | {i for pair in record['removed_crossings'] + record['new_crossings'] for i in pair}
        if not focus:
            focus = {5, 6, 7} if record['character'] == '侈' else set(range(max(0, len(before) - 4), len(before)))
        if record['character'] == '丢':
            focus |= {0, 1}
        if record['character'] == '黧':
            focus |= {0, 2}
        local = np.concatenate([s for group in (before, after, standard) for i, s in enumerate(group) if i in focus])
        center = (local.min(0) + local.max(0)) / 2
        width = max(float(np.ptp(local, axis=0).max()) * 1.15, .10)
        limits = (center[0] - width/2, center[0] + width/2, center[1] + width/2, center[1] - width/2)
        fig, axes = plt.subplots(2, 3, figsize=(11, 7.4))
        titles = ['原标准中心线（非作者原稿）', 'A：固定 v4 adaptive', LABELS[record['method']]]
        for col, group in enumerate((standard, before, after)):
            for row in range(2):
                ax = axes[row, col]
                for i, s in enumerate(group):
                    color = '#bb3b32' if i in focus else '#aab4bf'
                    ax.plot(s[:, 0], s[:, 1], color=color, lw=1.8, solid_capstyle='round')
                    if i in focus:
                        ax.plot(s[-1, 0], s[-1, 1], 'o', color=color, ms=2.5)
                        ax.text(s[0, 0], s[0, 1], f's{i + 1}', fontsize=7, color='#293c54')
                ax.set_aspect('equal')
                ax.axis((0, 1, 1, 0) if row == 0 else limits)
                ax.grid(alpha=.15)
                ax.tick_params(labelsize=7)
                if row == 0:
                    ax.set_title(titles[col], fontsize=10)
                if col == 0:
                    ax.set_ylabel('整字：统一 0–1 画布' if row == 0 else '局部：三图同一范围')
        fig.suptitle(f"{record['writer']} · {record['character']}｜已知问题复核；无该字作者原稿，不作风格优劣评分", fontsize=12)
        fig.text(.5, .013, f"改变几何：{', '.join(record['changed_geometry_ids']) or '无（保留 A）'}    "
                 f"消除严格交叉：{pairs(record['removed_crossings'])}    新增：{pairs(record['new_crossings'])}", ha='center', fontsize=10)
        fig.tight_layout(rect=(0, .035, 1, .955))
        filename = f"figures/{record['id']}.png"
        fig.savefig(output / filename, dpi=160)
        plt.close(fig)
        selected = record['provenance'].get('selected') or {}
        candidate = selected.get('candidate', {})
        if candidate:
            detail = f"供体：{candidate['character']}；源笔画 {candidate['stroke_ids']}；共同变换 {selected['transform']}。"
        else:
            detail = record['provenance'].get('fallback_reason') or record['provenance'].get('reason') or '见来源记录。'
        cards.append(f'<article><h2>{html.escape(record["writer"] + " · " + record["character"] + " · " + LABELS[record["method"]])}</h2>'
                     f'<img loading="lazy" src="{filename}"><p>{html.escape(detail)}</p>'
                     f'<p>消除交叉：{pairs(record["removed_crossings"])}；新增：{pairs(record["new_crossings"])}。'
                     f'<a href="../cases/{record["id"]}.json">完整输入、输出与来源</a></p></article>')
    source = json.loads((args.input / 'outline_source.json').read_text())
    outline = np.asarray(source['outline']) / 1024
    outline[:, 1] = 1 - outline[:, 1]
    old = np.asarray(source['original_median']) / 1024
    old[:, 1] = 1 - old[:, 1]
    proposed = np.asarray(source['proposed_normalized_median'])
    dense = np.concatenate([np.linspace(a, b, 30) for a, b in pairwise(proposed)])
    inside = Polygon(outline).contains_points(dense)
    assert inside.all(), 'estimated centerline leaves the flattened source outline'
    containment = {'sampled_segment_points': len(dense), 'all_inside_flattened_outline': bool(inside.all()),
                   'boundary_subdivisions': 24, 'interpretation': 'sampled check, not an analytic containment proof'}
    (output / 'outline_containment.json').write_text(json.dumps(containment, indent=2))
    fig, ax = plt.subplots(figsize=(9, 4))
    ax.fill(outline[:, 0], outline[:, 1], color='#dce3eb', label='原始公开字形轮廓')
    ax.plot(proposed[:, 0], proposed[:, 1], color='#287c73', lw=2, label='40 截面推导中心线（估计）')
    ax.plot(old[:, 0], old[:, 1], color='#bb3b32', lw=4, marker='o', ms=3, label='原始近点状中心线')
    ax.set_aspect('equal')
    ax.invert_yaxis()
    ax.legend(fontsize=9)
    ax.set_title('黧 s1：公开轮廓与中心线不一致；推导值不是作者原稿')
    fig.tight_layout()
    fig.savefig(output / 'figures/source-outline.png', dpi=170)
    plt.close(fig)
    intro = '''<h1>局部几何与真实部件检索：效果对比</h1>
<p>2026-10-07 · 独立可关闭实验 · 默认生成器未变。</p>
<p><strong>范围：</strong>两位作者、六个已知问题字、16 条诊断路径。这里是已知案例的工程复核，参数及规则已接触这些案例，不能称作新的留出集。没有这些目标字的作者原稿，标准中心线只作结构参考。之前的同字 A/B/C 和跨字留出实验独立保存，不能合并统计。</p>
<p><strong>有效结果：</strong>scx 丢的 s1 平移 0.014 消除 s1/s2；scx 侈的单笔平移失败，但拶的完整下部夕共同等比变换后消除 s6/s7；mjb 侈的 s7 平移 0.050 消除 s6/s7 和 s7/s8。平移不改变笔内形状、弧长、末向、压力和时间。整部件迁移保持供体各笔之间的比例，用一个共同变换，不逐笔缩放。</p>
<p><strong>边界：</strong>上述“消除交叉”仅表示已复核的几何约束改善，不证明作者风格或整字视觉质量变好。scx 侈迁移后的个别笔明显缩短；scx 徼可取缴的真实攵，但徹、徽没有通过约束的实例，mjb 未找到相容攵，均保留 A。缺乏实例时不制造轨迹。</p>
<p><strong>源异常：</strong>黧 s1 的原中心线长 0.00403，轮廓覆盖明显较长的区域。由公开轮廓推导中心线后，输出首笔由 scx 0.00423→0.27575、mjb 0.00079→0.10058。它是结构估计，不是作者轨迹。scx 初稿新增 s1/s3 交叉；上移首笔 0.008 后才通过保护。下文保留初稿对照，不把它算成功结果。</p>
<img src="figures/source-outline.png"><p>推导中心线的 1,170 个沿段采样位置均处在离散轮廓内。这是采样检验，不是连续包含的数学证明。</p>
<p><strong>性能：</strong>在上一轮已冻结的 80 个确认案例上，加速前后所有输出字段完全一致；scx 选择阶段中位数 33.87→5.16 ms，mjb 13.64→3.87 ms。这是一次成对的探索性计时，未做硬件隔离，不能解释成整体系统加速 6.6/3.5 倍。加上原 A 生成耗时，仍约为 A 的 3.0/2.6 倍，尚未达到此前 1.5 倍预算。</p>
<p><strong>不变量与来源：</strong>所有 16 输出检查笔数、标准 ID、笔顺、有限坐标、压力、全局单调时间和画布范围；除显式展示的未保护初稿外，均无新增相对 A 的严格笔间交叉。回退保留 A，可能保留 A 已有问题。来源样本及哈希、共同变换、修正参数和回退原因均在每例 JSON 中。源码和汇总结论进 Git；个人档案与图文留在忽略目录。</p>
<p><strong>下一步：</strong>优先作为显式实验开关接入真实部件生成，显示来源及回退；将“结构源修正”“整部件迁移”“已复核单笔平移”分开开关和评估。新作者或新组用于独立确认，进一步评估末端方向及盲评，不能把本报告当泛化验证。</p>'''
    if args.benchmark:
        benchmark = json.loads(args.benchmark.read_text())
        result = benchmark['results']
        performance = []
        for writer in ('scx', 'mjb'):
            row = result[writer]
            old, fast = (row['median_seconds'][key] * 1000 for key in ('old', 'fast'))
            ratio = 1 + row['median_seconds']['fast'] / row['median_base_seconds']
            performance.append(f"{writer} {old:.2f}→{fast:.2f} ms（选择阶段 {old/fast:.2f} 倍；加上 A 约为原 A 的 {ratio:.2f} 倍）")
        begin = intro.index('<p><strong>性能：')
        end = intro.index('</p>', begin) + 4
        intro = intro[:begin] + '<p><strong>性能：</strong>80 个已冻结确认案例的输出全部字段逐项相同。交替执行旧/新选择器顺序的一次成对计时：' + '；'.join(performance) + '。缓存仅用于源匹配锚点，不压缩输出。结果为探索性计时，未做硬件隔离；仍未达到整体 1.5 倍预算。</p>' + intro[end:]
    page = '<!doctype html><meta charset="utf-8"><title>InkStruct 局部几何改进报告</title><style>body{max-width:1120px;margin:40px auto;padding:0 24px;font:16px/1.8 system-ui;color:#203047;background:#f6f8fa}h1{font-size:30px}h2{font-size:22px}article{background:white;padding:24px;margin:30px 0;border:1px solid #d9e1e9;border-radius:12px}img{width:100%;height:auto}a{color:#186b9a}strong{color:#154d65}</style>' + intro + ''.join(cards)
    path = output / 'InkStruct_局部几何改进报告.html'
    path.write_text(page)
    print(path)


if __name__ == '__main__':
    main()
