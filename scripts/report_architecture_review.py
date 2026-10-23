"""Build same-scale figures and a local evidence report from frozen experiment output."""
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path

import numpy as np
from report_review_repairs import curves, render_grid

LABELS = {'A':'v4 基线','no_global':'去整字变换','no_layout':'去部件布局',
          'no_relation':'去关系位移','no_geometry':'去单笔几何','no_legacy':'去通用残差',
          'no_component_residual':'去部件残差','no_whole':'去整部件原型',
          'no_spline':'去 B-Spline','repair':'端点一致修复','R':'完整参考',
          'V6':'v6 原字框','V6_frame':'v6 统一字框','V6_learned':'v6 训练布局',
          'M_frame':'同源压缩＋统一字框'}


def read(path):
    return json.loads(path.read_text())


def table(headers, rows):
    return '<table><tr>'+''.join(f'<th>{html.escape(str(c))}</th>' for c in headers)+'</tr>'+''.join(
        '<tr>'+''.join(f'<td>{html.escape(str(c))}</td>' for c in row)+'</tr>' for row in rows)+'</table>'


def run(root, report_name='report'):
    out = root/report_name
    out.mkdir(exist_ok=False)
    summary = read(root/'summary.json')
    writers = list(summary)
    arms = list(LABELS)
    aggregate = {k:{'distance':float(np.mean([s['macro_distance'][k] for s in summary.values()])),
        'angle':float(np.mean([s['macro_terminal_angle'][k] for s in summary.values()])),
        'wins_vs_A':sum(s['improved_vs_A'][k] for s in summary.values()),
        'extra_cross_glyphs':sum(s['checks'][k]['glyphs_with_extra_crossings_vs_reference'] for s in summary.values()),
        'invariant_failed_glyphs':sum(s['checks'][k]['invariant_failed_glyphs'] for s in summary.values())} for k in arms}
    selected, example_rows = [], []
    for w,s in summary.items():
        ranked = sorted(s['per_character'],key=lambda c:s['per_character'][c]['V6_learned']['mean_distance']-s['per_character'][c]['A']['mean_distance'])
        evaluation = read(root/w/'evaluation.json')
        for c,role in [(ranked[0],'误差改善最大'),(ranked[-1],'误差退步最大')]:
            glyphs = read(root/w/'glyphs'/f'{ord(c):04X}.json')
            original = next(e['original'] for e in evaluation if e['character']==c)
            example_rows.append({'title':w+'\n'+c+'\n'+role,
                'curves':[original,*[curves(glyphs[k]) for k in ('A','V6','V6_frame','V6_learned')]]})
            selected.append({'writer':w,'character':c,'selection':role,'metrics':s['per_character'][c]})
    for i in range(2):
        render_grid(example_rows[i*4:(i+1)*4],['留出原稿','v4','v6 原字框','v6 统一字框','v6 训练布局'],out/f'originals_{i}.png')
    dev, local = [], []
    for c,indices in {'而':[3,4,5],'相':[4,5,8],'儒':[10,11,12,13,14,15],'荡':[6,7,8]}.items():
        glyphs = read(root/'user_001'/'glyphs'/f'{ord(c):04X}.json')
        cs = [curves(glyphs[k]) for k in ('A','no_spline','V6_frame','V6_learned','M_frame')]
        dev.append({'title':c,'curves':cs})
        xy = np.asarray([p for ss in cs for i in indices for p in ss[i]])
        lo,hi = xy.min(axis=0)-.04,xy.max(axis=0)+.04
        mid, span = (lo+hi)/2,max(hi-lo)
        local.append({'title':c,'curves':cs,'indices':indices,'bounds':(*list(mid-span/2),*list(mid+span/2))})
    labels = ['v4','只去样条','v6 统一字框','v6 训练布局','同源压缩 M']
    render_grid(dev,labels,out/'development.png')
    render_grid(local,labels,out/'local.png',local=True)
    protection = []
    for w in writers:
        glyphs = read(root/w/'glyphs'/f'{ord("叵"):04X}.json')
        protection.append({'title':w+'\n叵','curves':[curves(glyphs[k]) for k in ('A','repair','V6_frame','V6_learned')]})
    render_grid(protection,['v4','端点修复','v6 统一字框','v6 训练布局'],out/'protection.png')
    rows = [[LABELS[k],f'{v["distance"]:.5f}',f'{(v["distance"]/aggregate["A"]["distance"]-1)*100:+.2f}%',
             f'{v["angle"]:.2f}°',v['wins_vs_A'],v['extra_cross_glyphs']] for k,v in aggregate.items()]
    perwriter = [[w,s['n_characters'],s['n_samples'],*[f'{s["macro_distance"][k]:.5f}' for k in ('A','V6','V6_frame','V6_learned')]] for w,s in summary.items()]
    evidence = {'aggregate_equal_writer':aggregate,'examples':selected,
                'evaluated_writer_character_groups':sum(s['n_characters'] for s in summary.values()),
                'evaluated_samples':sum(s['n_samples'] for s in summary.values()),
                'generated_writer_characters':sum(s['total_glyphs'] for s in summary.values())}
    (out/'evidence_summary.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2))
    doc = f'''<!doctype html><html lang="zh"><meta charset="utf-8"><title>生成架构复核</title>
<style>body{{font:17px/1.75 system-ui;max-width:1450px;margin:30px auto;padding:24px;color:#182c40}}img{{max-width:100%}}table{{border-collapse:collapse}}td,th{{border:1px solid #ccd5dd;padding:8px 12px;text-align:left}}.lead{{background:#edf4f9;padding:20px}}details{{margin:20px 0}}a{{color:#165d93}}</style>
<h1>生成架构复核与拆层实验</h1><p>2026-10-11 · 独立分支 codex/architecture-review · 生产默认未改</p>
<p class="lead">结论：保留结构身份、原始轨迹、可靠映射和输出检查；布局仍然必要；8 点与无条件 B-Spline 不应作为唯一表示。完整轨迹加统一字框比上一版 v6 明显改善，但作者间有正反结果，末端方向也未全面改善，尚不能替换全部 v4。</p>
<p><a href="../protocol.json">预先固定的实验协议、分组与哈希</a> · <a href="../summary.json">所有作者全部路径结果</a> · <a href="evidence_summary.json">汇总与图例选择记录</a> · <a href="../../../../docs/ARCHITECTURE_REVIEW_20261011.md">完整架构复核及论文依据</a></p>
<h2>范围与公平比较</h2><p>4 位作者各预选 12 个目标字，按固定字符哈希选择，笔数限 3–20；所有同字重复样本一起排除，另排除 11 个已观察保护字。A 与 v6 使用完全相同的合格训练样本；旧全量档案不作为公平评估基线。生成后才读取目标几何。48 个作者—字组合中 10 个无法可靠逐笔映射，最终评估 38 个组合、40 份原稿；mjb 只剩 5 字，不能代表其整体笔迹。</p>
<p>这些真实样本过去有被观察的可能，称固定分组验证，不冒充新盲测。92 个作者—字组合全部生成，共 15 路、1380 个输出。源数据、数据库、旧档案均未覆盖。没有根据本轮结果调参数。比较按笔、同字样本、字、作者依次等权，4 位作者等权的均值不是统计显著性结论。</p>
<h2>总体结果：原坐标几何误差越小越好</h2>{table(['路径','几何误差','较 A 变化','末向误差','较 A 改善组合/38','较参考多交叉的字/92'],rows)}
<p>交叉列是严格中心线交叉提示，不是已确认视觉损伤；“叵”等正常手写也可能不同于字体。所有路径均无输出协议失败、无严格零长度笔画，但已有近空参考仍在：黧第 1 笔原 v6 弧长仅 0.00403、瀝第 6 笔仅 0.00840 字框单位，新的字框层并不修复这些源缺陷。v6 的两种整字变换逐点保留原输出的点数、动态值及交叉集合，未增加交叉。共同字框有 2 次越界提案（scx 生、user_001 瀝）被拒，精确回退到原 v6；训练布局本次没有越界回退。检查不覆盖所有粗笔碰撞、闭合和拥挤。</p>
<h2>作者间差异必须保留</h2>{table(['作者','有效字','原稿数','A','v6 原字框','v6 统一字框','v6 训练布局'],perwriter)}
<p>统一字框只依据公开参考线，将整字最长边归一到 0.85、居中，与原稿归一化约定一致；不是目标原稿对齐。训练布局再从该作者训练字中估计一个全字共用的正等比比例和平移，同字重复只投一票。仅 3 个参数，没有旋转、斜切、横纵独立缩放和逐笔调整。候选实例与部件布局在后处理前冻结。</p>
<p>与旧 v6 比，大部分几何收益来自坐标尺度约定一致。训练布局相对统一字框仅再改善约 0.55% 的作者等权均值，scx、user_001 改善，mjb、wsq 退步，证据不足以增加一个默认学习层。M 使用完全相同候选和变换，只恢复压缩与样条，不做原型平均；其总体误差接近完整轨迹，末向反而更接近本组原稿。不能说平滑只有负作用，也不能凭几何均值证明它保住了短钩。</p>
<h2>真实原稿：收益与退化一起展示</h2><p>以下按本轮 v6 训练布局相对 A 的几何误差，分别选每位作者改善最大和退步最大的字用于诊断。是结果后挑选的说明图，不是独立质量证据；汇总使用全部有效字。同字有重复时展示索引中的首份原稿，指标仍按全部重复平均。</p><img src="originals_0.png"><img src="originals_1.png">
<h2>四个历史问题字：整字与局部</h2><p>user_001 的而、相、儒、荡无用于本次评价的目标原稿。这些图只支持结构和表示判断，不能宣称更像作者。只去样条保留旧 8 点瓶颈，无法还原已经丢失的折点。v6 新路径仍有参考回退，并非所有笔画都来自作者。</p><img src="development.png"><img src="local.png">
<p>“相”的连接、闭合间隙需要明确接触约束；“而、儒”的而形下部本就开口，不能强行封底。“荡”的复杂折笔应优先保护原始顶点；改画布比例不会改变这些折点的角度。各行统一坐标比例，局部各列共用同一裁切范围，蓝色为选中笔，橙色起点、绿色终点。</p>
<h2>保护例：叵</h2><img src="protection.png"><p>旧人工好评仅属于当时 user_001 的原资产，不转移到本次重新建档输出；其他作者没有该好评。新路径会改变写法，特别是来源不足的参考回退。显示采用统一固定笔宽，不据此评价压力还原。</p>
<h2>工程与接入判断</h2><p>本轮新代码仅增加可关闭的整字坐标层、15 路实验和验证报告。没有改默认生成器、旧模型、原型或生产命令。各作者目录保留训练哈希、样本排除、原始源档案、全部输出、候选来源、变换、回退原因与评估原稿。</p>
<p>建议先统一坐标契约，再让完整轨迹与保折点参考成为独立表示选项。保留 v4 作为回归基线，逐部件接入可靠实例；不要全局删除布局、残差或部件整笔形，也不要把旧置信度当成审美分数。神经分支需先修正置信度目标和回退校准契约，再讨论扩大模型。详见完整 Markdown 复核。</p>
</html>'''
    (out/'报告.html').write_text(doc)
    print(json.dumps(evidence['aggregate_equal_writer'],ensure_ascii=False))


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--report-name',default='report')
    args=parser.parse_args()
    run(args.run,args.report_name)
