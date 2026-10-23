"""Private figures and negative/positive evidence for source-correction transport."""
from __future__ import annotations

import argparse
import html
from collections import Counter
from pathlib import Path

import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from experiment_component_trust import glyph_from_dict
from matplotlib.font_manager import FontProperties
from run_raw_trajectory_experiment import curves, save
from validate_structure_corrections import read

from inkstruct.geometry import path_length
from inkstruct.samples import sha256_file

FONT=FontProperties(fname='/System/Library/Fonts/Supplemental/Arial Unicode.ttf')


def figure(row,scoped,path,reason):
    c=row['task']['character'];w=row['task']['writer']
    groups={k:curves(glyph_from_dict(row['outputs'][k])) for k in ('A','B','R','G')}
    groups['SC']=curves(glyph_from_dict(scoped['outputs']['SC']))
    groups={'原稿':row['reference'],**groups}
    sid={'黧':'s1','瀝':'s6','盼':'s7'}.get(c)
    if sid is None:sid=row['events']['changes'][0]['stroke_id'] if row['events']['changes'] else 's1'
    index=int(sid[1:])-1
    focus=np.vstack([v[index] for v in groups.values() if v is not None]);center=(focus.min(axis=0)+focus.max(axis=0))/2
    width=max(.05,float(np.ptp(focus,axis=0).max())*1.15)
    fig,axes=plt.subplots(2,6,figsize=(19,8),layout='constrained')
    colors=['#222222','#ba4b37','#e2922e','#88989b','#00899b','#76539d']
    for col,((name,paths),color) in enumerate(zip(groups.items(),colors,strict=True)):
        ax,zoom=axes[:,col]
        ax.set_title(name,fontproperties=FONT,fontsize=14)
        ax.set(xlim=(0,1),ylim=(1,0),aspect='equal');ax.grid(alpha=.15)
        zoom.set(xlim=(center[0]-width/2,center[0]+width/2),ylim=(center[1]+width/2,center[1]-width/2),aspect='equal');zoom.grid(alpha=.15)
        if paths is None:
            for a in (ax,zoom):a.text(.5,.5,'无目标原稿',ha='center',va='center',transform=a.transAxes,fontproperties=FONT)
            continue
        for i,p in enumerate(paths):ax.plot(*np.asarray(p).T,color=color if i==index else '#999999',lw=1.8 if i==index else 1)
        p=np.asarray(paths[index]);zoom.plot(*p.T,color=color,lw=2);zoom.scatter(*p[[0,-1]].T,color=color,s=18)
        zoom.set_title(f'{sid} · L={path_length(p):.4f}',fontsize=10)
    fig.suptitle(f'{w} · {c} · {reason}\nA 原结构；B 全图重生成；R 既有修复；G 固定风格变化量＋保护；SC 新档案仅替换修正笔',fontproperties=FONT,fontsize=15)
    fig.savefig(path,dpi=130);plt.close(fig)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--experiment',type=Path,required=True);p.add_argument('--scope',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    rows=[read(p) for p in sorted((args.experiment/'evaluated').glob('*.json'))]
    scoped={(r['task']['writer'],r['task']['character']):r for r in [read(p) for p in (args.scope/'evaluated').glob('*.json')]}
    summary=read(args.experiment/'summary.json');scope=read(args.scope/'summary.json')
    selected=[(r,'近空源缺陷恢复') for r in rows if r['task']['character'] in '黧瀝']
    selected += [(r,'弯曲源缺陷；无作者原稿') for r in rows if r['task']['character']=='盼']
    scores=[r for r in rows if r['reference'] is not None and r['events']['changes']]
    selected += [(min(scores,key=lambda r:r['metrics']['G']['mean_distance']-r['metrics']['A']['mean_distance']),'G 收益案例'),
                 (max(scores,key=lambda r:r['metrics']['G']['mean_distance']-r['metrics']['A']['mean_distance']),'G 退化案例')]
    selected += [(r,'越界拒绝；G 完整回退') for r in rows if r['events']['changes'] and not r['diagnostics']['G']['applied']]
    records=[]
    for i,(row,reason) in enumerate(selected):
        image=args.output/f'case_{i+1:02}.png';figure(row,scoped[(row['task']['writer'],row['task']['character'])],image,reason)
        records.append({'task':row['task'],'reason':reason,'figure':image.name,'G_diagnostics':row['diagnostics']['G']})
    save(args.output/'figure_selection.json',records)
    sections=['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>结构修复传播方式对照</title><style>body{font:17px/1.75 -apple-system,sans-serif;max-width:1300px;margin:40px auto;padding:0 24px;color:#173039}table{width:100%;border-collapse:collapse;font-size:15px}td,th{border:1px solid #ccc;padding:7px;text-align:left}img{width:100%;margin:14px 0}.note{background:#eef5f5;padding:20px}code{font-size:13px}</style>',
    '<h1>结构修复如何进入生成器：固定风格传递与影响范围消融</h1><p>2026-10-07 · 私有后续实验 · 沿用前轮 246 个作者—字组合 · 默认关闭</p>',
    '<p class="note">本轮减少了修复传播引起的附带改动，且保留六个近空笔恢复收益；但没有改善原稿回归集的平均几何误差。因此保留为实验路径，不能作为全库默认策略。</p>',
    '<h2>已核实的原因与控制条件</h2><p>前轮 A/B/C 封存输出及固定档案不变。B 改动 625 笔参考中心线未变的生成笔；4 个组合的整字画布变换发生变化。追踪 64 个受影响组合发现 32 笔签名变化、30 笔旧原型键变化；599 笔残差前跨度发生数值变化，其中 317 笔差异大于 1e-6。黧 s1 的跨度约从 0.0038 变为 0.25，瀝 s6 从约 0.0066 变为 0.15。这些变化会改变原型选择、残差幅度及邻笔布局，无法将 B 的结果简单归因于中心线本身。</p>',
    '<p>新 T 路径以固定 A 为底，只把已验证的新旧参考路径差向量通过原全局/画布线性变换加入输出。裁剪恢复采用源顶点索引对应；两条重建路径点数改变时采用归一化弧长对应，后者是近似。输出保留基线及修正场的所有折线节点，不再原型平均、B-Spline 或统一点数压缩。未修正笔的几何和压力保持一致，时间按笔顺重排；原稿来源笔拒绝改写。</p>',
    '<p>G 为 T 加既有位移预算保护（0.06/步长0.002/间距0.002）。若不能消除相对 A 的新严格交叉，或输出越界，则整个提案回退 A，不用整字缩放隐藏越界。R 是项目已有的两笔近空修复入口，作为避免重复工作的对照。另有 SB/SC：仅将 B/C 的修正参考笔画替入 A，使用相同保护；它们是看到 T/G 结果后的机制消融，不冒充独立留出验证。</p>',
    '<h2>实际生成与协议检查</h2><table><tr><th>路径</th><th>改变组合</th><th>未变参考笔被改动</th><th>协议失败</th><th>新交叉（组合/笔对）</th></tr>']
    for k in ('A','B','C','R','T','G'):
        d=summary['all']['all'][k];sections.append(f"<tr><td>{k}</td><td>{d['changed_cases']}</td><td>{d['changed_unchanged_reference_strokes']}</td><td>{d['invariant_failures']}</td><td>{d['new_crossing_cases']} / {d['new_pairs']}</td></tr>")
    sections += ['</table><p>G 接受 64 个受影响组合中的 61 个，完整回退 3 个越界组合；182 个未改参考的保护/回归组合原样返回。T 唯一新交叉来自一个弯曲修复案例，G 用 0.01 字格平移消除。六个黧/瀝缺笔在 T 中均已恢复且没有新交叉，无需平移；G 关键笔长为 0.173–0.275。R 也能恢复这六笔且无新交叉，所以这是传播机制的替代证据，不是首次解决这些案例。</p>',
    '<p>检查覆盖笔数、标准 ID、顺序、有限坐标、压力、时间、边界和严格笔间交叉。无新严格交叉不等于完整拓扑或视觉质量无损；没有覆盖自交、笔宽粘连等。无原稿的黧/瀝/盼只评价结构恢复，不评价作者相似度。</p>',
    '<h2>144 个有原稿旧回归案例：不能只看安全指标</h2><table><tr><th>路径</th><th>平均几何</th><th>平均局部最大误差</th><th>末向误差°</th><th>改善/相同/变差</th></tr>']
    for k in ('A','B','C','R','T','G','SB','SC'):
        d=summary['all']['regression_gold'][k] if k not in ('SB','SC') else scope['all'][k]
        sections.append(f"<tr><td>{k}</td><td>{d['mean_distance']:.6f}</td><td>{d['max_distance']:.6f}</td><td>{d['terminal_angle_deg']:.3f}</td><td>{d['better']} / {d['equal']} / {d['worse']}</td></tr>")
    sections += ['</table><p>G 几何误差相对 A 约 +0.027%，SC 约 +0.017%；均不能宣称改善。C 的全图重建均值下降约 2.12%，但把 C 限制为只改源修正笔后，均值收益消失，说明其收益大量来自其他风格/布局变化，不能全部归功于源修复。该对照同时改变了作用范围，不能进一步归因为唯一原因。</p>',
    '<p>参数来自已存在预算或预先固定的对应规则，没有依据本轮原稿误差选阈值；所有新输出在评分前封存。字集均已观察，盼为开发字，无新的泛化结论。弧长和短钩只作独立诊断，未把“更长/更接近原稿弧长”当质量目标。所有原输入哈希保持不变。</p>',
    '<h2>图文验收：整字与共享窗口局部图</h2><p>整字固定 0–1，局部各列使用相同坐标窗口。图例：R 既有修复、G 新变化量保护、SC 重建档案局部替换。例子在全部评分封存后选择，包含收益、退化与拒绝。</p>']
    for r in records:sections.append(f"<h3>{html.escape(r['task']['writer']+' '+r['task']['character']+' · '+r['reason'])}</h3><img src=\"{r['figure']}\" alt=\"整字与局部图\">")
    sections += ['<h2>接入判断与下一步</h2><p>不替换生产默认，不开启全库去裁剪传播。明确近空/缺弯曲的源修正仍是正确的数据处理，但进入生成器需要与档案几何语义配套。新的固定风格传递适合继续用于经过源哈希确认的局部修复研究；其全库作者风格收益尚未成立。下一步应检查训练档案在被裁剪参考下学到的残差偏差，以及新旧参考的部件对齐关系，不能靠降低交叉数量替代作者质量验收。</p>',
    '<p>本轮未扩展布局风险分类模型，未改写作者轨迹、旧数据库或旧输出。代码与脱敏结论可提交，逐例数据及图文报告保持 Git 忽略。</p>']
    for name,pth in [('主实验协议',args.experiment/'protocol.json'),('全组指标',args.experiment/'summary.json'),('原型/尺度逐笔追踪',args.experiment/'regeneration_trace.json'),('局部作用范围消融',args.scope/'summary.json')]:
        import os
        sections.append(f'<p><a href="{os.path.relpath(pth,args.output)}">{name}</a></p>')
    sections.append('</html>');(args.output/'report.html').write_text('\n'.join(sections))
    save(args.output/'manifest.json',{'script_sha256':sha256_file(Path(__file__)),'inputs':{str(p):sha256_file(p) for p in [args.experiment/'summary.json',args.scope/'summary.json',args.experiment/'generation_manifest.json',args.scope/'generation_manifest.json']},
        'fallbacks':dict(Counter(r['diagnostics']['G'].get('reason') or 'accepted' for r in rows if r['events']['changes']))})
    print('report',args.output,flush=True)


if __name__=='__main__':main()
