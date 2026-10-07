"""Private illustrated audit and A/B/C generation report; never edits old artifacts."""
from __future__ import annotations

import argparse
import html
from pathlib import Path

import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from experiment_component_trust import glyph_from_dict
from matplotlib.font_manager import FontProperties
from run_raw_trajectory_experiment import curves, save
from validate_structure_corrections import read, repositories

from inkstruct.geometry import path_length
from inkstruct.outline_median import flatten_outline
from inkstruct.samples import sha256_file
from inkstruct.trajectory_experiment import crossing_pairs

FONT = FontProperties(fname='/System/Library/Fonts/Supplemental/Arial Unicode.ttf')
COLORS = {'原稿': '#222222', 'A': '#c44937', 'B': '#008b99', 'C': '#7054a1'}


def draw_case(row, path, reason, corrected):
    c, w = row['task']['character'], row['task']['writer']
    outputs = {k: curves(glyph_from_dict(v)) for k, v in row['outputs'].items()}
    ids = [s['standard_stroke_id'] for s in row['outputs']['A']['strokes']]
    if c in '黧瀝盼':
        sid = {'黧':'s1', '瀝':'s6', '盼':'s7'}[c]
    elif row['deltas']['C']['new_crossings'] and not row['events']['changes']:
        sid = ids[row['deltas']['C']['new_crossings'][0][0]]
    elif row['events']['changes']:
        sid = row['events']['changes'][0]['stroke_id']
    elif row['reference'] is not None:
        sid = max(ids, key=lambda s: abs(row['stroke_metrics']['B'][s]['max_distance']-row['stroke_metrics']['A'][s]['max_distance']))
    else:
        sid = ids[0]
    index = ids.index(sid)
    highlighted = {index}
    if row['deltas']['C']['new_crossings'] and not row['events']['changes']:
        highlighted.update(row['deltas']['C']['new_crossings'][0])
    curves_by_label = {'原稿':row['reference'], **outputs}
    fig, axes = plt.subplots(2,4,figsize=(14,8.5),layout='constrained')
    focused = [np.asarray(v[i]) for v in curves_by_label.values() if v is not None for i in highlighted]
    points = np.vstack(focused); center = (points.min(axis=0)+points.max(axis=0))/2
    width = max(float(np.ptp(points,axis=0).max())*1.15, .06)
    for col, (label, paths) in enumerate(curves_by_label.items()):
        ax, zoom = axes[:,col]
        if paths is None:
            ax.text(.5,.5,'无目标原稿\n仅可评价结构',ha='center',va='center',fontproperties=FONT,transform=ax.transAxes)
            zoom.text(.5,.5,'无目标原稿',ha='center',va='center',fontproperties=FONT,transform=zoom.transAxes)
        else:
            for i, stroke in enumerate(paths):
                p = np.asarray(stroke)
                ax.plot(*p.T,color=COLORS[label] if i in highlighted else '#888888',lw=1.7 if i in highlighted else 1.1)
            p = np.asarray(paths[index])
            zoom.plot(*p.T,color=COLORS[label],lw=2)
            zoom.scatter(*p[[0,-1]].T,s=23,color=COLORS[label])
            for other in highlighted-{index}:
                zoom.plot(*np.asarray(paths[other]).T,color='#c79221',lw=2, label=ids[other])
                zoom.legend(fontsize=9)
            title = f'{sid}: 弧长 {path_length(paths[index]):.4f}'
            if label != '原稿':
                title += f" / 新交叉 {len(row.get('deltas',{}).get(label,{}).get('new_crossings',[]))}"
            zoom.set_title(title,fontproperties=FONT,fontsize=10)
        ax.set_title({'原稿':'目标原稿（仅评估）','A':'A 原结构 + 原档案','B':'B 修结构 + 原档案','C':'C 修结构 + 重建档案'}[label],fontproperties=FONT,fontsize=12)
        ax.set_xlim(0,1);ax.set_ylim(1,0);ax.set_aspect('equal');ax.grid(alpha=.15)
        zoom.set_xlim(center[0]-width/2,center[0]+width/2);zoom.set_ylim(center[1]+width/2,center[1]-width/2);zoom.set_aspect('equal');zoom.grid(alpha=.15)
        ax.tick_params(labelsize=8);zoom.tick_params(labelsize=8)
    fig.suptitle(f'{w} · {c} · {reason}\n整字统一 0–1，局部四列使用相同坐标窗口；端点为圆点',fontproperties=FONT,fontsize=15)
    fig.savefig(path,dpi=150);plt.close(fig)
    return {'writer':w,'character':c,'reason':reason,'stroke_id':sid,'figure':path.name,
        'gold':row['reference'] is not None, 'task':row['task'], 'deltas':row['deltas'],
        'lengths':{k:path_length(v[index]) for k,v in outputs.items()},'metrics':row.get('metrics')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--validation',type=Path,required=True)
    parser.add_argument('--review',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    rows=[read(p) for p in sorted((args.validation/'evaluated').glob('*.json'))]
    summary=read(args.validation/'summary.json'); reference=read(args.validation/'reference_validation.json')
    _, corrected=repositories()
    # Display selection occurs only after sealed inference and scoring.
    selected=[(r,'确认源缺陷修复') for r in rows if r['task']['character'] in '黧瀝盼']
    for w in summary:
        scored=[r for r in rows if r['task']['writer']==w and r['reference'] is not None and r['events']['changes'] and r['task']['cohort']=='observed_regression']
        for func, name in [(min,'B 几何收益最大案例'),(max,'B 几何退化最大案例')]:
            if scored:
                r=func(scored,key=lambda r:r['metrics']['B']['mean_distance']-r['metrics']['A']['mean_distance'])
                selected.append((r,name))
    unchanged=next(r for r in rows if r['reference'] is not None and not r['deltas']['B']['geometry_changed'])
    selected.append((unchanged,'B 无变化保护案例'))
    selected.extend((r,'C 未改结构保护字的新增交叉') for r in rows if not r['events']['changes'] and r['deltas']['C']['new_crossings'])
    examples=[]
    for i,(r,reason) in enumerate(selected):
        examples.append(draw_case(r,args.output/f'case_{i+1:02}.png',reason,corrected))
    save(args.output/'display_selection.json',examples)
    # Compact source-layer proof figure: the three reviewed repairs, same axes per row.
    fig,axes=plt.subplots(3,2,figsize=(10,11))
    base=corrected.base
    for row,c in enumerate('黧瀝盼'):
        idx={'黧':0,'瀝':5,'盼':6}[c]; raw=corrected.graphics[c]
        poly=flatten_outline(raw['strokes'][idx],subdivisions=48)
        for col,repo in enumerate([base,corrected]):
            ax=axes[row,col];points=np.asarray(repo.get(c).strokes[idx].median)*[1024,-1024]+[0,1024]
            ax.fill(*poly.T,color='#eeeeee',edgecolor='#999999',lw=.8)
            ax.plot(*points.T,color=COLORS['A' if col==0 else 'B'],lw=2);ax.scatter(*points[[0,-1]].T,s=20)
            center=(poly.min(axis=0)+poly.max(axis=0))/2; width=np.ptp(poly,axis=0).max()*1.12
            ax.set_xlim(center[0]-width/2,center[0]+width/2);ax.set_ylim(center[1]-width/2,center[1]+width/2);ax.set_aspect('equal')
            ax.set_title(f'{c} s{idx+1} · '+('原中心线' if col==0 else '修复中心线'),fontproperties=FONT,fontsize=14)
    fig.suptitle('源轮廓修复：参考字体路径，不是作者原稿',fontproperties=FONT,fontsize=17)
    fig.tight_layout();fig.savefig(args.output/'source_repairs.png',dpi=160);plt.close(fig)
    diagnostics={}
    for label in ('B','C'):
        scored=[r for r in rows if r['reference'] is not None and r['task']['cohort']=='observed_regression']
        delta=[r['metrics'][label]['mean_distance']-r['metrics']['A']['mean_distance'] for r in scored]
        diagnostics[label]={'regression_scored':len(scored),'better':sum(v < -1e-9 for v in delta),'equal':sum(abs(v)<=1e-9 for v in delta),'worse':sum(v>1e-9 for v in delta),
            'new_crossing_characters':sum(bool(r['deltas'][label]['new_crossings']) for r in rows),
            'new_crossing_pairs':sum(len(r['deltas'][label]['new_crossings']) for r in rows),
            'unchanged_source_changed_output':sum(not r['events']['changes'] and r['deltas'][label]['geometry_changed'] for r in rows)}
    save(args.output/'diagnostics.json',diagnostics)
    crossing_review=[]
    for r in rows:
        c=r['task']['character']
        if any(v['new_crossings'] for v in r['deltas'].values()):
            reference_pairs=crossing_pairs([s.median for s in corrected.get(c).strokes])
            crossing_review.append({'task':r['task'],'gold_available':r['reference'] is not None,
                'corrected_reference_pairs':sorted(reference_pairs),
                'generated_new_pairs':{k:[{'stroke_ids':[f's{i+1}' for i in pair], 'in_corrected_reference':tuple(pair) in reference_pairs,
                    'disposition':'potential damage; no automatic acceptance from length restoration'} for pair in d['new_crossings']] for k,d in r['deltas'].items()}})
    save(args.output/'crossing_review.json',crossing_review)
    sections=['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>结构数据审计与修复实验</title><style>body{font:17px/1.75 -apple-system,BlinkMacSystemFont,sans-serif;max-width:1150px;margin:40px auto;padding:0 24px;color:#17252d}h1,h2{line-height:1.3}img{max-width:100%;border:1px solid #ddd;margin:12px 0}table{border-collapse:collapse;width:100%;font-size:15px}td,th{border:1px solid #ddd;padding:8px;text-align:left}.note{background:#eef5f6;padding:16px}details{margin:18px 0}code{font-size:13px}a{color:#007c89}</style>',
        '<h1>第一批扩展结构审计与修复实验</h1><p>2026-10-07 · 私有图文报告 · scx / mjb / wsq · 生产默认保持不变</p>',
        '<p class="note">已确认并在独立参考修正层处理 6,015 条缺陷中心线，涉及 4,465 字。这里的“修复”指恢复源几何或重建经过复核的参考路径，不代表全库质量已验证，更不代表作者风格改善。生成结果中的收益、无变化与损伤均在下方展示。</p>',
        '<h2>1. 审计结论与证据边界</h2><table><tr><th>类别</th><th>数量</th><th>处理</th></tr><tr><td>导入时裁剪负 y，丢失端部/钩部几何</td><td>6,012 笔 / 4,464 字</td><td>按上游源坐标精确恢复；保留原坐标原点</td></tr><tr><td>原中心线近空</td><td>2 笔：黧 s1、瀝 s6</td><td>复用已验证细长单条截面修复</td></tr><tr><td>稀疏弦线穿出弯曲轮廓</td><td>1 笔：盼 s7</td><td>保留两端，38 个单区间截面重建内部</td></tr><tr><td>额外筛查疑似</td><td>19 笔（含上述 3 笔）</td><td>3 确认、10 字体宽折角差异、6 待复核</td></tr><tr><td>映射一致性</td><td>0 条已证实矛盾；485 字未决</td><td>缺失/未知分解、非叶部件匹配等，不自动改写</td></tr><tr><td>修正层执行失败</td><td>'+str(len(reference['failed']))+'</td><td>只覆盖上述确定规则，复杂钩/分支未尝试强修复</td></tr></table>',
        '<p>扫描了 9,574 字、112,617 笔，包含轮廓内含、端点、折返、轮廓覆盖和笔画/部件映射；这些是保守筛查，不是经过盲标注验证的全缺陷分类器。字体轮廓没有唯一中心线，字体路径也不是作者笔迹真值。没有独立笔顺权威数据，因此只验证数据库与已有顺序/ID/映射的一致性，不能证明语言学笔顺正确。</p>',
        '<p>关键根因来自本地上游 README 116–125 行：坐标框为 (0,900) 到 (1024,-124)。现导入器对 1−y/1024 做逐点裁剪，使合法负 y 丢失。修正层只去除裁剪，保持旧坐标原点；部分参考 y 因而大于 1，生成输出仍经过原有整字画布适配。没有将旧档案偷偷迁到另一坐标原点。</p>',
        '<img src="source_repairs.png" alt="三条源中心线的修复前后">',
        '<p>已逐图检查全部 19 个疑似候选、24 个未报警对照（短笔、长笔、多点弯折各 8 个），另展示 12 个裁剪量分位案例。24 个对照未观察到明确缺陷；这不等于估计漏检率。视觉判断由助手完成，仍需独立人工复核。</p>',
        '<h2>2. 固定条件的 A/B/C 实验</h2><p>A：原结构 + 原档案；B：只替换参考结构，同一档案、adaptive=1.0；C：同一训练索引，在修正结构上重新对齐和建档。确定性生成器无随机抽样，记录 seed=0。三位作者的训练索引哈希与旧档案匹配；1,148 份共同保留的作者轨迹点、压力、时间、弧长参数完全一致，标准对应也无变化。C 的全局风格/原型估计可以变化，因此不能把其贡献算到 B。</p>',
        '<p>共 246 个作者—字组合、738 份输出；包含旧回归样本、确认修复字和每位作者最多 32 个未修改保护字（与旧回归重叠 3 例，独立新增 93 例）。旧字集全部标为已观察回归集，“盼”是修复开发案例，没有冒充新留出。19 个候选的阈值用于初步筛查；修复规则在生成前冻结，未根据目标质量调参。</p>',
        '<p>所有输出先封存哈希，再读取目标原稿评分。原稿来自保留完整点列的档案；不同点数用折线距离及统一弧长积分比较，不再降采样输出。几何误差单位为归一化字格，表中为按字平均后作者内平均。弧长误差不等于质量，原稿也可能含噪声；短钩与末向只是独立诊断。</p>',
        '<h2>3. 真实原稿回归结果</h2><table><tr><th>作者 / 有原稿回归数</th><th>A 几何 / 末向°</th><th>B 几何 / 末向°</th><th>C 几何 / 末向°</th><th>B 几何变化</th></tr>']
    for w,s in summary.items():
        g=s['regression_gold'];a,b,c=[g[k] for k in ('A','B','C')]
        sections.append(f"<tr><td>{w} / {g['scored']}</td><td>{a['mean_distance']:.5f} / {a['terminal_angle_deg']:.2f}</td><td>{b['mean_distance']:.5f} / {b['terminal_angle_deg']:.2f}</td><td>{c['mean_distance']:.5f} / {c['terminal_angle_deg']:.2f}</td><td>{100*(b['mean_distance']/a['mean_distance']-1):+.2f}%</td></tr>")
    sections += ['</table><p>负值表示几何误差下降；C 相对 A 的平均几何误差变化分别为 scx −3.73%、mjb −1.61%、wsq −1.85%；这是重新建档的独立贡献，且会改变未修正字。平均值不能掩盖个例退化。样本不是独立随机抽样，没有显著性或总体泛化结论。</p>',
        '<table><tr><th>路径</th><th>回归字改善 / 相同 / 变差</th><th>新增严格交叉：字 / 笔对</th><th>未改参考却改变输出</th></tr>']
    for k,d in diagnostics.items():
        sections.append(f"<tr><td>{k}</td><td>{d['better']} / {d['equal']} / {d['worse']}</td><td>{d['new_crossing_characters']} / {d['new_crossing_pairs']}</td><td>{d['unchanged_source_changed_output']}</td></tr>")
    sections += ['</table><p>新增交叉是相对 A 新出现的严格线段交叉，不能全部自动判为异常；它不覆盖自交、共线接触或笔宽。B 的 6 对新交叉均不在修正参考的严格交叉集合中；C 为 9 对，其中还涉及未改结构的保护字。它们应作为潜在生成损伤复核，不能以‘恢复了缺笔’为由忽略。全部 738 份输出未发现协议不变量失败或零长笔；这不代表 A 没有近空缺笔（黧/瀝 6 个组合的关键笔弧长仅 0.0008–0.0078，B 恢复至 0.177–0.292）。全部案例的具体笔对、笔画退化、笔数、ID、笔顺、有限坐标、压力和单调时间检查保存在 evaluated JSON。结构正确并不能保证当前旧档案的全部输出更好。</p>',
        '<h2>4. 整字与局部验收：包括收益、无变化和退化</h2><p>每张图上排都是同一 0–1 字格，下排四列共享关键笔画的同一局部窗口；无原稿处明确留空。蓝色/红色高亮同一个标准笔画 ID。展示案例由封存后的评分选出，未参与修复规则或生成选择。</p>']
    for e in examples:
        sections.append(f"<h3>{html.escape(e['writer']+' '+e['character']+' · '+e['reason'])}</h3><img src=\"{e['figure']}\" alt=\"整字与局部对比\">")
    sections += ['<h2>5. 可接入范围与尚缺证据</h2><p>保留独立版本和默认关闭。明确的黧/瀝近空中心线、盼曲线缺失已消除参考数据的明显缺失，但当前直接生成仍出现未获参考拓扑支持的新交叉，只可作为按源哈希白名单的离线/实验参考修正候选，但生成端必须继续做整字与局部验收。全库去裁剪应与档案版本配套迁移；此次 B/C 的个例损伤说明不能直接全量替换生产数据库，也不能认为重新建档必然消除问题。</p>',
        '<p>尚缺：复杂钩/多分支的可靠有向路径重建；6 条疑似的独立复核；485 字未决映射的权威结构证据；独立笔顺依据；更大盲标注正常/异常集以估计漏检；未观察留出字、多作者与重复采样；全库生成保护回归。短路径筛查、全库程序执行、有限图审均不等于全面修复。</p>',
        '<p>短钩统计覆盖有限：各字报告只在原稿被既有诊断器识别出钩时计算，其余为空；不把无指标当作短钩已经正确。盼虽修复了参考弯曲，三位作者均无目标原稿，不能声称更像作者。</p><p>生产代码默认、原上游、旧数据库、作者档案和旧输出没有改变。中止的 validation_v1 保留：比较内存列表/元组类型导致校验器误报，修正为序列值比较后在新目录 validation_v2 完整重跑，未覆盖旧结果。</p>',
        '<h2>6. 完整审计图册与可追溯数据</h2>']
    for p in sorted(args.review.glob('*.png')):
        rel=Path(__import__('os').path.relpath(p,args.output))
        sections.append(f'<details><summary>{html.escape(p.name)}</summary><img src="{rel}" alt="审计同尺度叠加图"></details>')
    for name,path in [('完整数值汇总',args.validation/'summary.json'),('新增交叉与修正参考的逐对核对',args.output/'crossing_review.json'),('逐字逐笔修正证据',args.validation/'correction_events.json'),('输入/代码哈希与冻结协议',args.validation/'protocol.json'),('19 候选判断及拒绝原因',args.review/'candidate_ledger.json'),('24 对照逐图复核',args.review/'control_visual_review.json'),('未决映射清单',args.review.parent/'scan_v1'/'mapping.json')]:
        rel=__import__('os').path.relpath(path,args.output); sections.append(f'<p><a href="{rel}">{name}</a></p>')
    sections.append('</html>');(args.output/'report.html').write_text('\n'.join(sections))
    save(args.output/'manifest.json', {'validation':str(args.validation),'review':str(args.review),'input_sha256':{str(p):sha256_file(p) for p in [args.validation/'summary.json',args.validation/'generation_manifest.json',args.review/'candidate_ledger.json']},'script_sha256':sha256_file(Path(__file__))})
    print('report saved',args.output,flush=True)


if __name__ == '__main__':
    main()
