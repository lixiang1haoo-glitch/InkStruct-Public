"""Render source-acquisition gains, unchanged controls and brush-contact regressions."""
from __future__ import annotations

import argparse
import html
import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from report_v6_integrated_exp import svg_panel
from report_v61_exp import render
from run_v6_exp import sha, write
from run_v61_exp import dict_curves

from inkstruct.alignment import _minimum_cost_assignment, _resolve_equal_count_order, align_sample
from inkstruct.glyph_frame_exp import reference_frame
from inkstruct.profile import load_profile
from inkstruct.samples import iter_index
from inkstruct.structures import StructureRepository
from inkstruct.v6_integrated_exp import framed_graph
from inkstruct.v61_contacts import segment_clearance
from inkstruct.v61_exp import V61ExpGenerator


def load(path):
    return json.loads(path.read_text())


def run(root, report_dir='report'):
    out = root/report_dir
    out.mkdir(exist_ok=False)
    summary = load(root/'summary.json')
    split = load(Path('artifacts/v61_collection_20261013/plan_v4/split.json'))
    rows = {s:load(root/s/'records.json') for s in ('regression','prospective')}
    glyphs = {r['character']:load(root/s/'glyphs'/f"{ord(r['character']):04X}.json")
              for s,rr in rows.items() for r in rr}
    originals = defaultdict(list)
    for s in rows:
        for r in load(root/s/'evaluation.json'):
            if 'means' not in r:
                r['means']={arm:{key:float(np.mean([m[key] for m in mm])) for key in
                    ('mean_distance','max_distance','terminal_angle_deg','absolute_length_error')}
                    for arm,mm in r['metrics'].items()}
            originals[r['character']].append(r)
    has_validation=summary['prospective_original_samples']>0

    def row(c, **kwargs):
        return {'title':c, 'curves':[originals[c][0]['original'] if originals[c] else None,
            *[dict_curves(glyphs[c][a]) for a in ('before','after')]],**kwargs}

    labels = ['原稿（有则显示）','补采前（冻结）','补采后（同参数）']
    render([row(c) for c in '而相儒荡'],labels,out/'main.png')
    render([row(c) for c in '叵生针饿'],labels,out/'source_gains.png')
    render([row(c) for c in '雪震瀝传'],labels,out/'changed_controls.png')
    render([row(c) for c in '情睡桂码砖认'],labels,out/'unchanged_controls.png')
    render([row(c) for c in split['prospective_validation']],labels,out/'prospective.png')
    if has_validation:
        repeat_rows=[{'title':c,'curves':[*(r['original'] for r in originals[c][:2]),
            *[dict_curves(glyphs[c][a]) for a in ('before','after')]]}
            for c in split['prospective_validation'] if len(originals[c])==2]
        render(repeat_rows,['验证原稿 1','验证原稿 2','补采前（冻结）','补采后（冻结）'],out/'validation_repeats.png')
    zooms = []
    for c,index,title in [('而',3,'而·原有折钩'),('相',8,'相·目部底部接触'),('儒',13,'儒·而部末钩'),
                         ('荡',6,'荡·右部短钩'),('叵',4,'叵·匚圆弯'),('饿',5,'饿·部件间隙')]:
        xy = dict_curves(glyphs[c]['after'])[index]
        center = np.asarray(xy[-1]) if c not in '相饿' else np.asarray(xy).mean(axis=0)
        if c=='叵':
            center = np.asarray(xy).mean(axis=0)
        radius = .22
        zooms.append(row(c,title=title,indices=[index],bounds=(*list(center-radius),*list(center+radius))))
    render(zooms,labels,out/'details.png')
    width_rows = [row(c,title=f'{c} · 笔宽 {w}',brush_width=w) for c in '相饿雪' for w in (.014,.028,.05)]
    render(width_rows,labels,out/'brush_width.png')

    # Inspect capture mapping in original pen order, without admitting rejected data.
    repo = StructureRepository(Path('artifacts/full_library_20261010/inputs/characters.sqlite3'))
    samples = list(iter_index(root/'training.jsonl'))
    grouped = defaultdict(list)
    for s in samples:
        grouped[s.character].append(s)
    mapping_review=[]
    for sample in samples:
        g=repo.get(sample.character)
        aligned=align_sample(sample,g)
        if aligned.stroke_order_status!='ambiguous':continue
        result,costs=_resolve_equal_count_order([s.median for s in g.strokes],aligned.source_normalized_strokes)
        n=len(g.strokes)
        regularized=costs+np.asarray([[.025*abs(i-j)/max(1,n-1) for j in range(n)] for i in range(n)])
        best,_=_minimum_cost_assignment(regularized)
        mapping_review.append({'character':sample.character,'sample_id':sample.sample_id,
            'identity_improvement':result.identity_improvement,'alternative_margin':result.alternative_margin,
            'best_standard_to_raw_DIAGNOSTIC_ONLY':[i+1 for i in best],
            'admitted':False,'note':'No override; permutation requires reviewed mapping evidence.'})
    write(out/'mapping_review.json',mapping_review)
    font = ImageFont.truetype('/System/Library/Fonts/STHeiti Medium.ttc',15)
    for number, chars in enumerate(('当睛请锤','什俄匝坐','扬泪硅需'),1):
        im = Image.new('RGB',(1000,1230),'white');d=ImageDraw.Draw(im)
        for j,t in enumerate(['结构参考（非书写真值）','补录 1·原始笔序','补录 2·原始笔序']):
            d.text((120+j*290,10),t,font=font,fill='#22354b')
        for i,c in enumerate(chars):
            g=repo.get(c); ss=grouped[c]
            paths=[[s.median for s in framed_graph(g,reference_frame(g)).strokes]]
            paths += [align_sample(s,g).source_normalized_strokes for s in ss]
            d.text((10,70+i*290),c,font=font,fill='#22354b')
            for j,strokes in enumerate(paths):
                ox,oy=110+j*290,45+i*290
                d.rectangle((ox,oy,ox+270,oy+270),fill='#f7f8fa')
                for k,stroke in enumerate(strokes):
                    xy=[(ox+15+x*240,oy+15+y*240) for x,y in stroke]
                    color=('#256294','#a1472e','#477747','#8858a1')[k%4]
                    d.line(xy,fill=color,width=3)
                    d.text(xy[0],str(k+1),font=font,fill=color)
        im.save(out/f'capture_mapping_{number}.png')

    profile = load_profile(root/'source_archive.json')
    # Index construction reuses the actual generator; no new selection or refitting.
    engine = V61ExpGenerator(profile,repo,repo)
    indexed = {e['sample_id'] for entries in engine.v6.index.by_key.values() for e in entries}
    new_ids = {s.sample_id for s in samples}
    mapping = load(root/'new_mapping_audit.json')
    uses = defaultdict(set); proposed = defaultdict(set)
    used_ids=set(); proposed_ids=set()
    for s,rr in rows.items():
        audit = load(root/s/'after_audit.json')
        for r in rr:
            for p in r['provenance']['after']:
                q=p['candidate']
                if q['sample_id'] in new_ids:
                    uses[q['character']].add(r['character']);used_ids.add(q['sample_id'])
        for slot in audit['slots'].values():
            for trial in slot['trials']:
                q=trial['candidate']
                if q['sample_id'] in new_ids:
                    proposed[q['character']].add(slot['character']);proposed_ids.add(q['sample_id'])
    character_rows=[]
    for c in '请锤需俄睛泪坐当扬硅什匝':
        ss=[s for s in samples if s.character==c]
        mm=[r for r in mapping if r['character']==c]
        character_rows.append({'character':c,'raw':len(ss),'admitted':sum(r['admitted'] for r in mm),
            'indexed':sum(s.sample_id in indexed for s in ss),
            'proposed_for':sorted(proposed[c]),'actually_used_for':sorted(uses[c]),
            'mapping_status':dict(Counter(r['stroke_order_status'] for r in mm))})
    write(out/'per_capture_character.json',character_rows)

    # Report exact polyline gaps for signals; do not call every contact a defect.
    contact_details=[]
    for r in rows['regression']:
        c=r['character'];before=dict_curves(glyphs[c]['before']);after=dict_curves(glyphs[c]['after'])
        owners={i:p['component_id'] for p in r['provenance']['after'] for i in p['indices']}
        for a,b in r['new_brush_contacts']['0.028']:
            contact_details.append({'character':c,'orders':[a+1,b+1],
                'kind':'同一作者部件内部' if a in owners and owners.get(a)==owners.get(b) else '跨部件或参考边界',
                'gap_before':segment_clearance(before[a],before[b]),
                'gap_after':segment_clearance(after[a],after[b])})
    write(out/'new_contact_details.json',contact_details)
    metrics=[]
    for c,items in originals.items():
        if not items or 'means' not in items[0]:continue
        metric={a:{key:float(np.mean([r['means'][a][key] for r in items]))
                   for key in items[0]['means'][a]} for a in ('before','after')}
        metrics.append({'character':c,'samples':len(items),'means':metric,
                        'cohort':'prospective' if c in split['prospective_validation'] else 'regression'})
    write(out/'metrics_by_character.json',metrics)
    conversion=load(root/'forecast_conversion.json')
    accepted=[r for r in conversion if r['now_selected']]
    new_strokes=sum(r['stroke_count'] for r in accepted)
    reg=summary['splits']['regression']
    lines=['# user_001 补采验收：实际来源增加，但不能直接扩大默认使用','',
        '本轮只增加通过原门槛的训练来源；生成参数、参考修正、布局与排序算法均未调节。','',
        f"收到{summary['intake']['raw_json_files']}份采样，其中24份训练采样原始有效、笔数全部匹配；{summary['new_complete_samples']}份训练采样通过完整映射建档，档案322→338份。",
        '当、睛、请、锤各两份被映射器标为 ambiguous，未强行入库。这是映射不确定性，不直接等于书写错误。',
        f'新增来源中：{len(new_ids&indexed)}份有索引部件、{len(proposed_ids)}份进入本次31字候选提案、{len(used_ids)}份被实际选中。',
        (f"收到8个预留验证字的16份原稿，{summary['prospective_original_samples']}份可作逐笔评价。两路31字输出均与验证原稿到达前的冻结输出完全一致；验证字全组不进入来源库。"
         if has_validation else '8个预留验证字未随包提供；保留其冻结身份，只生成无原稿的结构对照，不报告新留出风格成绩。'),'',
        '## 预计覆盖转为实际覆盖','',
        f"23字回归：作者来源90/219→118/219（41.1%→53.9%，增加28笔）；参考回退129→101笔。此前11槽/52笔机会中，{len(accepted)}槽/{new_strokes}笔实际采用；4槽/24笔因映射未准入而未兑现。",
        '8字预留对照：24/82笔不变；使、伯、便更换亻供体。此组检验供体适配和保护性变化，不验证全部首次覆盖收益的跨字外推。',
        '硅已通过建档和索引，但固定排序仍选择原有供体；“采到了”“可检索”“被选中”不能混算。','',
        '## 每个补采字的去向','',
        '| 补采字 | 原始有效 | 完整建档 | 有索引部件 | 进入候选的目标 | 实际采用的目标 |',
        '| --- | --- | --- | --- | --- | --- |']
    for r in character_rows:
        lines.append(f"| {r['character']} | {r['raw']} | {r['admitted']} | {r['indexed']} | {'、'.join(r['proposed_for']) or '—'} | {'、'.join(r['actually_used_for']) or '—'} |")
    lines+=['','## 不变量与观感风险','',
        '31字两路均保持笔数、标准ID、笔顺、有限坐标、压力范围和单调时间；完整部件共用等比变换，原始几何、压力和笔内时间差精确保留。无新增严格中心线交叉。',
        f"回归集中{len(reg['changed_characters'])}字变化、{23-len(reg['changed_characters'])}字不变。0.028笔宽下，相、雪、震、饿出现新增接触对；较粗0.05下还有儒、叵、荡、针等信号。它们需视觉复核，接触对既可能是原有笔形内部连接，也可能是部件粘连，不能一律视为错误。",
        '现有放置门槛主要防越界、严格交叉及长度退化；新增源池并不保证相对补采前没有笔宽粘连。此次保留这些负面结果，不回调参数掩盖。','',
        '| 字 | 新接触笔序 | 关系 | 原间隙 | 补采后间隙 |', '| --- | --- | --- | --- | --- |']
    for r in contact_details:
        lines.append(f"| {r['character']} | {r['orders']} | {r['kind']} | {r['gap_before']:.5f} | {r['gap_after']:.5f} |")
    lines+=['','相的目部底部、雪和震的雨部接触均在同一完整作者部件内部，不能称为新增跨部件碰撞；饿的两对接触跨越食部与我部，应优先复核。',
        '图上能看到相、儒、荡和叵带入了供体原有弯曲与钩形；这不是再次启用平滑。没有这些目标原稿时，不能判断它们一定更像作者对目标字的写法。',
        '映射复核图显示：当的前两笔、锤的相邻笔，以及请/睛青部的书写次序与参考有差异。自动最佳对应存在改排证据，但未同时达到当前两项纠序阈值；保持未准入，具体分数和建议对应仅作诊断，见 mapping_review.json。']
    lines+=['','## 有原稿的既有回归评价','',
        '使用原有12份、10字原稿，仅评价；认的3份按同字汇总。输出不重采样，几何评价使用原有统一弧长积分。','',
        '| 字 | 原稿份数 | 平均距离：前→后 | 末向角差：前→后 |',
        '| --- | --- | --- | --- |']
    for r in metrics:
        if r['cohort']!='regression':continue
        a,b=r['means']['before'],r['means']['after']
        lines.append(f"| {r['character']} | {r['samples']} | {a['mean_distance']:.5f}→{b['mean_distance']:.5f} | {a['terminal_angle_deg']:.2f}°→{b['terminal_angle_deg']:.2f}° |")
    lines+=['','针、震、饿的平均几何距离下降，雪上升；其余6字不变。不能据此把震、饿的新接触风险判为通过，也不能将距离下降直接解释为作者风格更好。无原稿的相、儒、荡、叵等只评价来源保真与结构。','']
    if has_validation:
        lines+=['## 冻结跨字验证：8字、16份原稿','',
            '全部同字重复按一组评价，以下为两份原稿的字内平均；没有使用这些原稿选字、建档、改候选或调参。',
            '| 字 | 原稿份数 | 平均距离：前→后 | 末向角差：前→后 |',
            '| --- | --- | --- | --- |']
        for r in metrics:
            if r['cohort']!='prospective':continue
            a,b=r['means']['before'],r['means']['after']
            lines.append(f"| {r['character']} | {r['samples']} | {a['mean_distance']:.6f}→{b['mean_distance']:.6f} | {a['terminal_angle_deg']:.2f}°→{b['terminal_angle_deg']:.2f}° |")
        lines+=['','使的平均几何距离小幅下降；伯、便小幅上升，其他5字不变。使的末向角差未改善，伯、便变差；不同方面的变化不一致，不能声称跨字风格整体提升。',
            '8字无新增严格交叉；0.028和0.05笔宽未增加接触对，0.014下使、伯、便出现内部亻接触变化。仅8字且主要测试备选供体，不能推广为大字库统计结论。',
            '![两份验证原稿与冻结输出](validation_repeats.png)','']
    lines+=[
        '## 图文对照','',
        '所有列使用相同字框比例和笔宽；局部各列使用同一裁剪窗口。原稿为空表示没有可用目标原稿，不是生成失败。',
        '![而相儒荡](main.png)','![新增来源](source_gains.png)','![变化保护字](changed_controls.png)',
        '![不变保护字](unchanged_controls.png)','![折钩、圆弯与间隙局部](details.png)',
        '![笔宽敏感性](brush_width.png)','![预留验证字](prospective.png)',
        '![映射待复核：当睛请锤](capture_mapping_1.png)',
        '![已准入样本：什俄匝坐](capture_mapping_2.png)',
        '![已准入样本：扬泪硅需](capture_mapping_3.png)','',
        '## 下一步','',
        '先复核当、睛、请、锤的笔序对应证据，再决定是否需要补写；不要要求作者为迁就字体参考改变自然笔形。',
        '把饿的跨部件接触、相的目部内部接触和雪、震的供体更换列为重点验收；已通过原始/映射准入的16份可以留在实验档案，但不等于各目标放置都通过观感验收。',
        ('继续保留旧档案及旧默认。验证原稿现已齐全并保持整组隔离；本组评价结果已经打开，后续若据此开发，应转为回归集，并另行预留新验证字。'
         if has_validation else '继续保留旧档案及旧默认。铜、懂、使、伯、枝、便、慢、悦仍待补充评价原稿，每字两次，任何重复都不得进入来源库。')]
    (out/'验收报告.md').write_text('\n'.join(lines)+'\n')
    gallery=[]
    for c,g in glyphs.items():
        gallery.append(f'<h3>{c}</h3><div class="row">'+''.join(
            f'<div><b>{html.escape(label)}</b>{svg_panel(xy)}</div>'
            for label,xy in zip(labels,row(c)['curves'],strict=True))+'</div>')
    body='<html><meta charset="utf-8"><title>补采验收</title><style>body{font:16px system-ui;max-width:1100px;margin:30px auto}.row{display:flex}.row>div{width:32%}svg{width:100%}img{max-width:100%}p{line-height:1.7}</style>'
    body+='<h1>user_001 补采验收</h1><p>24份训练收到，16份建档；回归作者轨迹90→118/219笔。新增接触风险仍在，保持默认。</p>'
    body+=('<p>16份验证原稿齐全，全部仅用于评价；使小幅改善，伯、便小幅退步，其他5字不变。</p>' if has_validation else '<p>8个预留字未提供原稿。</p>')
    body+='<p><a href="验收报告.md">完整结论、逐字去向和指标</a></p>'
    body+=''.join(f'<h2>{name}</h2><img src="{file}">' for name,file in
                  [('重点四字','main.png'),('来源增加','source_gains.png'),('退步与变化','changed_controls.png'),('局部细节','details.png'),('映射待复核','capture_mapping_1.png')])
    body+='<h2>全部31字同尺度矢量对照</h2>'+''.join(gallery)+'</html>'
    (out/'index.html').write_text(body)
    write(out/'report_verification.json',{'images_and_report':{p.name:sha(p) for p in out.iterdir() if p.is_file()},
        'heldout_originals_missing':summary['prospective_original_samples']==0,
        'no_generation_or_parameter_changes':True})
    print(out)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--report-dir',default='report')
    args=parser.parse_args()
    run(args.run,args.report_dir)
