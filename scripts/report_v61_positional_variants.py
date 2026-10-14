"""Same-scale variant repair report; originals opened only after generation freeze."""
from __future__ import annotations

import argparse
import gzip
import html
import json
from collections import Counter
from pathlib import Path

from generate_v61_library import CORRECTIONS, DB, SOURCES, digest, dump
from report_v61_candidate_expansion import svg
from report_v61_exp import render
from run_v61_admission_exp import stroke_payload
from run_v61_exp import dict_curves

from inkstruct.glyph_frame_exp import reference_frame
from inkstruct.profile import load_profile
from inkstruct.structure_corrections import CorrectedStructureRepository
from inkstruct.structures import StructureRepository
from inkstruct.v61_contacts import contact_pairs

ARMS=['old_F','old_G','new_F','new_G']
LABELS=['旧等比 F','旧非等比 G','修复等比 F','修复非等比 G','原稿（仅评估）']


def load(p):
    return json.loads(gzip.decompress(p.read_bytes()) if p.suffix=='.gz' else p.read_bytes())


def report(root,out):
    out.mkdir(parents=True,exist_ok=False)
    frozen=load(root/'freeze.json')['outputs']
    assert all(digest(p)==h for p,h in frozen.items())
    records={(p.parent.name,load(p)['character']):load(p) for p in root.glob('*/*.json.gz')}
    originals={}
    truth_files=list(Path('artifacts/v61_source_topology_20261013/run_v1').glob('*/evaluation.json'))
    for file in truth_files:
        for r in load(file):
            originals.setdefault((file.parent.name,r['character']),r['original'])
    for writer,path in SOURCES.items():
        for s in load_profile(path).source_trajectories.values():
            originals.setdefault((writer,s.character),[st.points for st in s.strokes])
    stats={'cases':len(records),'old_regressions':sum(r['existing_regression'] for r in records.values()),
           'old_bad_candidates':0,'old_bad_cases':0,'families':Counter(),'changed_G':0,'changed_F':0,
           'new_external_crossing_cases':0,'new_brush_contact_cases':0,'sources':Counter()}
    changed=[];cells=[];rows=[]
    geometry = []
    repository = CorrectedStructureRepository(StructureRepository(DB), *CORRECTIONS)
    for key,r in records.items():
        w,c=key
        bad=[p for p in r['old_selected_audit'] if not p['evidence']['accepted']]
        stats['old_bad_candidates']+=len(bad);stats['old_bad_cases']+=bool(bad)
        for p in bad:
            for fam in {t['family'] for t in p['evidence']['checks'] if t['status']=='incompatible'}:
                stats['families'][fam]+=1
        changes={s:stroke_payload(r['arms']['new_'+s]['glyph'])!=stroke_payload(r['arms']['old_'+s]['glyph']) for s in ['F','G']}
        for s in ['F','G']:stats['changed_'+s]+=changes[s]
        if any(changes.values()):changed.append(key)
        new=r['arms']['new_G']['checks']
        stats['new_external_crossing_cases']+=bool(new['new_cross_component_crossings'])
        # Repaired reference strokes still belong to the repaired component;
        # the older generic evaluator treated every fallback stroke as an owner.
        groups = [set(p['indices']) for p in r['arms']['old_G']['provenance']
                  if any(p['component_id'] == b['target_component'] for b in bad)]
        old_xy,new_xy = (dict_curves(r['arms'][a]['glyph']) for a in ['old_G','new_G'])
        changed_indices = {i for i,(a,b) in enumerate(zip(old_xy,new_xy,strict=True)) if a != b}
        assert changed_indices <= set().union(*groups), 'unrelated geometry changed'
        contacts = {}
        if groups:
            graph=repository.get(c);transform=reference_frame(graph)
            ref=[transform.apply(s.median) for s in graph.strokes]
            for width in (.014,.028,.05):
                added=contact_pairs(new_xy,width)-contact_pairs(old_xy,width)
                boundary={pair for pair in added if any((pair[0] in g)!=(pair[1] in g) for g in groups)}
                contacts[str(width)]={'new_boundary':sorted(boundary),
                    'already_present_in_reference':sorted(boundary & contact_pairs(ref,width)),
                    'new_internal':sorted(added-boundary)}
            stats['new_brush_contact_cases']+=bool(contacts['0.028']['new_boundary'])
        geometry.append({'writer':w,'character':c,'changed_indices':sorted(changed_indices),'contacts':contacts})
        for arm in ARMS:stats['sources'][arm]+=r['arms'][arm]['checks']['integrity']['source_strokes']
        counts=[r['arms'][a]['checks']['integrity']['source_strokes'] for a in ARMS]
        rows.append('| '+w+' | '+c+' | '+' | '.join(map(str,counts))+' | '+str(len(bad))+' |')
        panels=[]
        for arm,label in zip(ARMS,LABELS,strict=False):
            a=r['arms'][arm]
            provenance='；'.join(p['candidate']['character']+' → '+p['component_id'] for p in a['provenance'])
            panels.append('<div><b>'+label+'</b>'+svg(a['glyph'])+'<small>'+html.escape(provenance or '参考回退、个性化不足')+'</small></div>')
        cells.append(f'<section><h3>{w} · {c}</h3><div class="grid">'+''.join(panels)+'</div></section>')
    dump(out/'summary.json',stats)
    dump(out/'repair_geometry.json',geometry)
    selected=[('wsq','羝'),('scx','羝'),*changed,('user_001','铜'),('user_001','伯'),('wsq','闻'),
              ('user_001','想'),('wsq','叵'),('mjb','涸')]
    selected=list(dict.fromkeys(k for k in selected if k in records))
    figures=[];figure_notes=[]
    for key in selected:
        r=records[key];writer,char=key
        curves=[dict_curves(r['arms'][a]['glyph']) for a in ARMS]+[originals.get(key)]
        indices=sorted({i for i,(a,b) in enumerate(zip(curves[1],curves[3],strict=True)) if a!=b})
        if char in '羝羚翔':indices=list(range(6))
        if not indices:indices=list(range(len(curves[0])))
        bounds=(0.,.28,.5,1.) if char in '羝羚翔' else (0.,.45,1.,1.)
        name=f'{writer}-{ord(char):04X}.png'
        render([{'title':f'{writer}\n{char} 整字','curves':curves},
                {'title':'关键笔画局部','curves':curves,'indices':indices,'bounds':bounds}],LABELS,out/name)
        figures.append(f'<h3>{writer} · {char}</h3><img src="{name}">')
        figure_notes.extend(['',f'### {writer} · {char}','',f'![整字与局部]({name})'])
    intro=[f'验证 {stats["cases"]} 个作者—目标字，其中 {stats["old_regressions"]} 个旧输出按保存的来源和变换逐点恢复；其余为同类问题开发案例。没有新留出结论。',
           f'旧 G 中识别到 {stats["old_bad_cases"]} 字、{stats["old_bad_candidates"]} 个已选部件不兼容。按部件家族：{dict(stats["families"])}。修复后 G 改变 {stats["changed_G"]} 字，F 改变 {stats["changed_F"]} 字。',
           '修复只撤销不兼容来源，并在其笔画范围内寻找完整适配来源；其他已接受部件及变换锁定。未强行将竖掰成撇，未平滑或重采样输出。',
           '参考仅用于识别粗粒度内容变体，并结合供体真实轨迹核查；不要求作者曲线贴合字体。羊、土、王、子、车之外的形态尚未获得硬判据，模糊情况标记复核。',
           '羊部适配来源存在，不代表完整放置可用；候选仍须通过完整映射、有序对应、变换范围和跨部件安全检查。未通过时明确保留参考回退、个性化不足。',
           f'相对旧 G 新增跨部件严格交叉 {stats["new_external_crossing_cases"]} 字、默认笔宽新增跨修复部件接触 {stats["new_brush_contact_cases"]} 字。本批为三位作者的羚，第5/7笔接触，参考本来已有，但相对旧输出确实新增；保留间距风险，不宣称没有损伤。两例羝的新增第3/6笔接触位于羊部内部，不算跨部件碰撞。完整协议及源点、压力、笔内时间校验逐字留档。',
           '旧嗓的独立搜索重放曾出现差异；本轮改用已保存来源计划恢复基线，并限定修复范围，未将重放/搜索变化算入修复贡献。原运行及旧输出未覆盖。']
    md=['# v6.1 exp 位置变体修复报告','',*intro,'','## 逐字覆盖与旧误用','',
        '| 作者 | 字 | 旧 F | 旧 G | 修复 F | 修复 G | 旧 G 不兼容部件 |','|---|---|---:|---:|---:|---:|---:|',*rows,*figure_notes]
    (out/'report.md').write_text('\n'.join(md),encoding='utf-8')
    (out/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>v6.1 位置变体修复</title><style>body{font:15px system-ui;margin:24px;color:#24384a}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:15px}svg{width:100%;background:#fafafa}img{max-width:100%}small{display:block}section{border-top:1px solid #ddd}</style><h1>v6.1 exp 位置变体修复</h1>'+''.join('<p>'+html.escape(p)+'</p>' for p in intro)+''.join(figures)+''.join(cells),encoding='utf-8')
    dump(out/'evaluation_provenance.json',{'generation':frozen,'truth':{str(p):digest(p) for p in truth_files},
        'archives':{str(p):digest(p) for p in SOURCES.values()},'report_code_sha256':digest(Path(__file__))})
    assert all(digest(p)==h for p,h in frozen.items())


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('root',type=Path);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();report(args.root,args.output)
