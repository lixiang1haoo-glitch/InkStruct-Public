"""Post-freeze private visual and geometry review; originals never tune generation."""
from __future__ import annotations

import argparse
import html
import json
from collections import Counter
from pathlib import Path

from generate_v61_library import SOURCES, WRITERS, digest, dump
from report_v61_exp import render
from run_v61_author_strokes import COHORT, PRIOR
from run_v61_exp import dict_curves
from run_v61_positional_variants import load

from inkstruct.trajectory_experiment import path_length, stroke_metrics
from inkstruct.v61_contacts import contact_pairs


def run(root,out):
    frozen=load(root/'freeze.json')
    assert all(digest(p)==h for p,h in frozen['outputs'].items())
    out.mkdir(parents=True,exist_ok=False)
    records={(w,c):load(root/w/f'{ord(c):04X}.json.gz') for w in WRITERS for c in COHORT}
    originals={}; evaluation_inputs={}
    for w in WRITERS:
        for folder in ['v61_exp_20261013/run_v2','v61_source_topology_20261013/run_v1']:
            p=Path('artifacts')/folder/w/'evaluation.json'
            evaluation_inputs[str(p)]=digest(p)
            for r in load(p):
                if r.get('original'):
                    originals[w,r['character']]=r['original']
        # For newly inspected characters in archives, originals enter evaluation
        # only now. Retrieval already excludes every same-character sample.
        for r in load(SOURCES[w])['source_trajectories'].values():
            originals.setdefault((w,r['character']),[s['points'] for s in r['strokes']])
    totals={}; metrics=[]; missing=[]; sensitivity=[]; preserved=0
    for arm in 'ABCD':
        checks=[r['arms'][arm]['checks'] for r in records.values()]
        totals[arm]={'author_strokes':sum(r['author_strokes'] for r in checks),
                     'total_strokes':sum(r['total_strokes'] for r in checks),
                     'author_only_glyphs':sum(r['author_only_ready'] for r in checks)}
    for (w,c),r in records.items():
        a,d=(dict_curves(r['arms'][k]['glyph']) for k in ('A','D'))
        if a==d:
            preserved+=1
        for width in [.014,.028,.05]:
            before,after=contact_pairs(a,width),contact_pairs(d,width)
            sensitivity.append({'writer':w,'character':c,'width':width,
                                'new':sorted(after-before),'lost':sorted(before-after)})
        for arm,v in r['arms'].items():
            curves=dict_curves(v['glyph'])
            original=originals.get((w,c))
            if original and len(original)==len(curves):
                metrics.append({'writer':w,'character':c,'arm':arm,
                                'strokes':[stroke_metrics(p,q) for p,q in zip(curves,original,strict=True)]})
            assert all(path_length(s)>1e-6 for s in curves)
        for trial in r['arms']['D']['log']['trials']:
            if 'reason' in trial:
                missing.append({'writer':w,'character':c,**trial})
    dump(out/'evaluation.json',metrics)
    dump(out/'contact_sensitivity.json',sensitivity)
    dump(out/'missing.json',missing)
    contact_counts={str(width):{'new_glyphs':sum(bool(r['new']) for r in sensitivity if r['width']==width),
                                'lost_glyphs':sum(bool(r['lost']) for r in sensitivity if r['width']==width)}
                    for width in [.014,.028,.05]}
    inherited=[{'writer':w,'character':c,'pairs':log['checks'].get('inherited_source_contacts',[])}
               for (w,c),r in records.items() for log in r['hybrid_log']
               if log.get('accepted') and log['checks'].get('inherited_source_contacts')]
    dump(out/'summary.json',{'totals':totals,'unchanged_glyphs':preserved,
                            'original_cases':len({(r['writer'],r['character']) for r in metrics}),
                            'contacts':contact_counts,'inherited_source_contacts':inherited})
    dump(out/'evaluation_provenance.json',{'inputs':evaluation_inputs,'generation_freeze':digest(root/'freeze.json'),
        'originals_read_after_freeze':True,'source_archives':{str(p):digest(p) for p in SOURCES.values()}})
    main=records['wsq','羝']
    wrong=load(PRIOR/'wsq/7F9D.json.gz')['arms']['old_G']['glyph']
    comparisons=[dict_curves(wrong),*[dict_curves(main['arms'][k]['glyph']) for k in 'ABCD']]
    render([{'title':'wsq 羝\n整字','curves':comparisons},
            {'title':'第6笔局部\n同尺度放大','curves':comparisons,'indices':[5],'bounds':(0,.28,.5,1)}],
           ['旧：误用竖式羊','A：位置修复后','B：只换关键笔','C：只做单笔回退','D：组合'],out/'wsq_di.png')
    for w in WRITERS:
        rows=[]
        for c in COHORT:
            r=records[w,c]
            rows.append({'title':f'{w} {c}\n作者笔画 '+str(r['arms']['D']['checks']['author_strokes'])+
                         '/'+str(r['arms']['D']['checks']['total_strokes']),
                'curves':[originals.get((w,c)),*[dict_curves(r['arms'][k]['glyph']) for k in 'ABCD']]})
        render(rows,['原稿（空白=无）','A 上轮结果','B 只换关键笔','C 单笔回退','D 组合'],out/f'{w}.png')
    local=[]
    for w,c,indices in [('wsq','羚',[1,2]),('scx','羝',[5]),('mjb','羚',[5]),
                        ('user_001','而',[3]),('wsq','叵',[0]),('scx','荡',[6,7,8])]:
        r=records[w,c]
        local.append({'title':f'{w} {c}\n关键笔画','indices':indices,
                      'curves':[dict_curves(r['arms'][k]['glyph']) for k in 'ABCD']})
    render(local,['A 上轮结果','B 只换关键笔','C 单笔回退','D 组合'],out/'locals.png')
    counts=Counter(p['kind'] for r in records.values() for p in r['arms']['D']['provenance'].values())
    text='''# v6.1 exp 作者单笔回退与关键笔替换

48 个作者×字案例，共 480 笔；全部为开发/回归数据，不是新留出集。
生产默认不变。每笔均保存来源、哈希、变换、拒绝原因。整字原稿在生成冻结后才用于评价。

|路径|作者笔画|全作者轨迹字|
|---|---:|---:|
'''
    for arm,t in totals.items():
        text+=f"|{arm}|{t['author_strokes']}/480|{t['author_only_glyphs']}/48|\n"
    text+=f'''
A 为上轮位置变体检查后结果，B 仅替换羊部关键笔，C 仅给参考空缺补作者单笔，D 先 B 后 C。
D 来源分类：{dict(counts)}。完整部件、保留的混合部件笔画和独立作者单笔不可混称。

wsq 羝：保留羸的羊部前五笔，末笔改用熨第3笔的完整撇（34点），等比缩放和平移。
前五笔沿用上轮已存在的受限非等比变换；本轮没有再改形。新增撇为等比变换，因此不能把整个羊部称为同一变换的完整实例。
scx 羝：末笔来源皙第6笔。mjb 羚：末笔来源览第3笔。
wsq 羚：第2/3笔笔宽接触原本就在同一供体的前五笔中，属于保留的作者内部关系，最终允许该混合方案。早期 run_v1 / run_final / run_verified 曾误拒，已被本轮最终 run_source_aware 取代；不把这个误拒算作真实退步。

![羝整字及局部](wsq_di.png)

## 验收与边界

全部输出通过笔数、标准ID、笔顺、有限坐标、压力范围、时间单调、非退化检查；全部已用作者笔画通过逐点、压力和笔内时间保真复核。
本轮 D 与 A 相比 {preserved}/48 整字几何完全不变，所有已有完整部件几何均冻结。
没有新增严格交叉。笔宽 .028 的新增接触为 {contact_counts['0.028']['new_glyphs']} 字，记录见 summary.json；其中供体原有内部关系单独标注，不算拼接新增损伤。
细笔 .014 下 {contact_counts['0.014']['new_glyphs']} 字新增接触，粗笔 .05 下 {contact_counts['0.05']['new_glyphs']} 字新增接触；.028 下还有 {contact_counts['0.028']['lost_glyphs']} 字失去了旧接触。失去接触不一定是改善，可能扩大开口，需要人工验收。全部敏感性见 contact_sensitivity.json。
协议通过与覆盖增加不等于观感更好。逐笔拼接会损失真实部件内部协调；参考仍然控制单笔位置和大小，尚未消除字体布局影响。
原稿局部几何、弧长、末向和短钩评价在 evaluation.json；不把接近某次原稿当作作者风格的真值。
有原稿的 10 个案例中，D 的平均几何距离比 A 降低 5 个、升高 3 个、不变 2 个。wsq 羝由 .03175 升至 .03413，scx 羝由 .04298 降至 .04009；这仅是单次原稿几何对照，不是风格优劣排名。

人工图像核查记录（本轮助手查看，尚待用户验收）：wsq 羝的错误竖已消除，B 保住羊部前五笔的作者弧度，D 右侧也改用作者轨迹；整字大小和摆放仍偏向既有参考布局。wsq 叵的自然圆弯及相、儒等原有完整部件保持原样。user_001 而的横折钩仍无准入来源，不能声称已全作者化。scx 荡新增两撇但复合折钩仍是参考，混合来源的协调性尚未解决。扩大笔宽会暴露前述新增粘连，因此全作者来源导出只是来源验收，不是正式可用性认证。

D 仍有 {len(missing)} 笔无安全来源，详见 missing.json。诊断图保留这些参考笔画便于定位，但不会生成对应的 .author_only.json。
独立全作者输出只有覆盖完整时可导出；无法满足时显式报告缺口，不用不适配的作者笔画凑覆盖。
当前笔型桶只是保守方向描述，并非完备的汉字笔型语义；复杂折钩、长复合笔仍需审查。
候选排序仍含参考放置误差，是本轮固定的放置先验，不能当作风格分数。未使用均值原型、8点压缩或样条。

## 全部对照

'''
    for w in WRITERS:
        text+=f'### {w}\n\n![全部对照]({w}.png)\n\n'
    text+='![保护字与关键笔画](locals.png)\n'
    (out/'report.md').write_text(text)
    parts=['<!doctype html><meta charset="utf-8"><title>作者单笔回退实验</title><style>body{font:16px/1.7 system-ui;max-width:1500px;margin:auto;padding:24px}img{max-width:100%}pre{white-space:pre-wrap}details{margin:12px 0}</style>',
           '<h1>v6.1 exp：关键笔替换与作者单笔回退</h1>', '<pre>'+html.escape(text.split('## 全部对照')[0].replace('![羝整字及局部](wsq_di.png)',''))+'</pre>',
           '<img src="wsq_di.png">']
    for w in WRITERS:
        parts.append(f'<h2>{w}：原稿 / A / B / C / D</h2><img src="{w}.png">')
    parts.append('<h2>关键笔画</h2><img src="locals.png"><h2>逐字逐笔来源（D）</h2>')
    for (w,c),r in records.items():
        parts.append(f'<details><summary>{w} {c}</summary><pre>'+html.escape(json.dumps({
            'source':r['arms']['D']['provenance'],'missing':r['arms']['D']['log']['missing'],
            'hybrid':r['hybrid_log']},ensure_ascii=False,indent=2))+'</pre></details>')
    (out/'index.html').write_text('\n'.join(parts))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();run(a.root,a.output)
