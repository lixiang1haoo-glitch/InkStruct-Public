"""Private source-aware admission gallery with human acceptance and boundary cases."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from report_v61_exp import render
from run_v6_exp import sha, write
from run_v61_admission_exp import dict_curves
from run_v61_source_topology_exp import ACCEPTED, PRIOR, WRITERS

from inkstruct.geometry import bbox
from inkstruct.profile import load_profile
from inkstruct.trajectory_experiment import SharedTransform
from inkstruct.v61_contacts import segment_clearance


def load(p):
    return json.loads(p.read_text())


def run(root):
    out=root/'report';out.mkdir(exist_ok=False)
    summaries=load(root/'summary.json')
    records={w:{r['character']:r for r in load(root/w/'records.json')} for w in WRITERS}
    glyphs={w:{c:load(root/w/'glyphs'/f'{ord(c):04X}.json') for c in rs} for w,rs in records.items()}
    originals={w:{} for w in WRITERS}
    for w in WRITERS:
        for r in load(root/w/'evaluation.json'):originals[w].setdefault(r['character'],r['original'])
    labels=['原稿（仅评估）','A 已验收基线','B 源内部拓扑','C 参考差异诊断','D 扩展完整来源']

    def row(w,c,indices=None,bounds=None):
        r={'title':f'{w}\n{c}','curves':[originals[w].get(c)]+[dict_curves(glyphs[w][c][a]) for a in 'ABCD']}
        if indices is not None:r['indices']=indices
        if bounds is not None:r['bounds']=bounds
        return r

    render([row('user_001',c) for c in '震叵'],labels,out/'main.png')
    accepted=[]
    for c in '铜伯':
        old=load(ACCEPTED/'glyphs'/f'{ord(c):04X}.json')
        accepted.append({'title':c+'\n人工风格认可','curves':[originals['user_001'][c],dict_curves(old['A']),dict_curves(glyphs['user_001'][c]['A']),dict_curves(glyphs['user_001'][c]['D'])]})
    render(accepted,['原稿（仅评估）','上轮参考回退','上轮人工认可结果','本轮 D：保持不变'],out/'human_accepted.png')
    profile=load_profile(PRIOR/'source_archive.json')
    sources=[]
    for c in '震叵':
        rs=records['user_001'][c]
        oldids={p['component_id'] for p in rs['arms']['A']['provenance']}
        p=next(p for p in rs['arms']['D']['provenance'] if p['component_id'] not in oldids)
        q=p['candidate'];sample=profile.source_trajectories[q['sample_id']]
        mapping={s.standard_stroke_id:s for s in sample.strokes}
        raw=[mapping[k].points for k in q['stroke_ids']]
        transformed=[dict_curves(glyphs['user_001'][c]['D'])[i] for i in p['indices']]
        fallback=[dict_curves(glyphs['user_001'][c]['A'])[i] for i in p['indices']]
        sources.append({'title':q['character']+'部件 → '+c,'curves':[raw,fallback,transformed]})
    render(sources,['完整作者来源（原坐标）','原参考回退部件','共用等比变换后'],out/'sources.png')
    local=[]
    for c,ids,name in [('震',[8,9,11],'辰部原有交叉'),('震',[12,13,14],'辰部末端'),('叵',[1,2,3],'口部圆弯与交叉')]:
        r=row('user_001',c,ids);r['title']=c+'\n'+name
        points=[p for curves in r['curves'] if curves for i in ids for p in curves[i]]
        x0,y0,x1,y1=bbox(points);r['bounds']=(x0-.03,y0-.03,x1+.03,y1+.03)
        local.append(r)
    render(local,labels,out/'local.png')
    brush=[]
    for c in '震叵':
        for width in (.014,.028,.05):
            brush.append({'title':f'{c}\n笔宽 {width:.3f}','curves':[dict_curves(glyphs['user_001'][c][a]) for a in 'AD'],'brush_width':width})
    render(brush,['A 已验收基线','D 扩展来源'],out/'brush.png')
    # Reconstruct rejected proposals for diagnosis only; never substitute them
    # into delivered glyph JSON or count them as accepted coverage.
    bad=[]
    rejection_details=[]
    for c,arm in [('震','C'),('田','D'),('睡','D')]:
        rs=records['user_001'][c];base=glyphs['user_001'][c]['A']
        byid={s['standard_stroke_id']:i for i,s in enumerate(base['strokes'])}
        for d in rs['arms'][arm]['log']['placement']:
            if d['accepted']:continue
            q=d['candidate'];sample=profile.source_trajectories[q['sample_id']]
            mapping={s.standard_stroke_id:s for s in sample.strokes}
            t=SharedTransform(**d['transform']);trial=dict_curves(base)
            for sid,tid in zip(q['stroke_ids'],d['source_mapping_evidence']['target_ids'],strict=True):
                trial[byid[tid]]=t.apply(mapping[sid].points)
            bad.append({'title':c+'\n拒绝 '+q['character']+'候选','curves':[dict_curves(base),trial,dict_curves(glyphs['user_001'][c]['D'])]})
            rejection_details.append({'character':c,'source_character':q['character'],'reason':d['fallback_reason'],
                'external_contacts':d['new_cross_boundary_contacts'],'unexplained_crossings':d['topology']['unexplained_new_pairs']})
            break
    render(bad,['A 基线','未采用候选（诊断）','实际 D 输出'],out/'rejected.png')
    # Fixed-position protection gallery: every unchanged case, not just favorites.
    guard_files=[]
    for w in WRITERS:
        chars=[c for c,r in records[w].items() if r['arms']['D']['unchanged']]
        for k in range(0,len(chars),8):
            name=f'guards_{w}_{k//8+1}.png';guard_files.append(name)
            render([{'title':f'{w}\n{c} · 不变','curves':[dict_curves(glyphs[w][c][a]) for a in 'AD']} for c in chars[k:k+8]],['A 基线','D 本轮'],out/name)
        render([row(w,c) for c in '而相儒荡'],labels,out/f'focus_{w}.png')
    xy=dict_curves(glyphs['user_001']['震']['D']);gap=segment_clearance(xy[3],xy[8])
    human={'reviewer':'user feedback in this conversation','scope':'previous user_001 铜/伯 outputs only',
        'assessment':'style imitation substantially improved; inherited crossings/local differences acceptable; geometric mismatch not evidence of style damage',
        'variation_cause':'normal writing variation is plausible, not statistically proven',
        'blind_review':False,'approval_extended_to_new_cases':False,
        'previous_generation_files':{c:sha(ACCEPTED/'glyphs'/f'{ord(c):04X}.json') for c in '铜伯'},
        'current_baseline_and_D_unchanged':True}
    write(out/'human_acceptance.json',human)
    lines=['# v6.1 exp：以作者来源为依据的内部拓扑验收与完整部件扩展','',
        '本轮保持生产默认；旧档案和旧输出不覆盖。本报告包含实际生成、原供体、局部、未采用候选和全部保护案例。','',
        '## 人工验收结论已更新','',
        '用户人工审查认可上一轮“铜、伯”风格模仿显著提升，认为底部交叉及局部差异可接受。该反馈适用于具体已看过的输出，不是盲评统计，也不能自动扩展到本轮新例。两字本轮完全保持原有轨迹。此前所谓“局部退步”改为“几何差异、人工可接受”，不再用作否决风格的依据。','',
        '![人工认可结果保留](human_accepted.png)','',
        '## 四路固定因素','',
        '- A：上一轮已验收的实际结果；user_001 保留完整同与怕的白，其他档案重现冻结 v6 基线。',
        '- B：仅在原候选池和原等比拟合下，将源中已有且原样保留的内部交叉与新增外部交叉分开。',
        '- C：同一候选池，再将参考弧长比例、参考支持的接触丢失降为诊断；仍阻止新增跨部件严格交叉和 0.028 笔宽接触。',
        '- D：固定 C 的全部已接入来源，扩展通过既有有序结构映射验证的完整整字→部件来源。',
        '', '原先已接入的所有部件来源、变换保持不变，只填参考回退位置。不重建档案、不改排序、拟合、参考版本，不逐笔变形或混搭。根桥仍验证参考之间的身份/有序对应；作者笔形本身与参考或某次目标原稿的距离不作为本轮否决条件。',
        '', '100 个档案—目标组合都是已观察回归；46 组有 56 份原稿，仅在全部生成冻结后评价，同字重复整组排除训练。没有新的盲测或新作者泛化结论。','',
        '## 实际新增来源','', '| 档案 | A | B | C | D | 总笔数 |', '| --- | ---: | ---: | ---: | ---: | ---: |']
    for w,s in summaries.items():
        cv=s['coverage'];total=sum(cv['A'].values())
        lines.append(f"| {w} | "+' | '.join(str(cv[a]['source_strokes']) for a in 'ABCD')+f' | {total} |')
    lines.extend(['', 'user_001：“震”完整辰部来自“晨”，8/15 → 15/15 笔；“叵”内口来自完整“口”，2/5 → 5/5 笔。两项合计增加 10 笔。其他三个档案没有额外准入，不把完成扫描说成跨作者质量提升。',
        '', '![新例整字对照](main.png)', '', '“叵”没有目标原稿，空白评价格表示缺失，不声称它更接近作者对叵的实际写法。',
        '', '![来源与放置](sources.png)', '', '![同尺度局部](local.png)',
        '', '## 检测含义与安全边界','',
        '完整来源逐项验证：身份/哈希、可靠一对一标准映射、笔顺、部件完整所有权、角色（或显式根角色桥）；变换须正等比。保留全部来源点、压力及笔内时间差，输出统一重排为全局非递减时间。内部交叉集合在变换前后必须一致，不能因为来源已有交叉就放过变换损伤。',
        '', '100×4 输出的笔数、标准 ID/笔顺、有限坐标、压力、时间、越界和退化检查均通过；所有原已接入部件保真。98 个组合轨迹内容完全不变。相对 A，新增严格交叉只出现在新来源内部：震 4 对、叵 2 对，均逐对追溯到源；新增跨部件严格交叉为 0。',
        '', '0.014、0.028 下没有新增跨部件笔宽接触；0.05 下震有一处第 4/9 笔新接触，不能扩大宣称为所有笔宽均安全。它是不同部件放置后形成的接触信号，与源内部交叉性质不同。',
        '', f'震第 4/9 笔最小中心线间隙为 **{gap:.6f}**；在 0.028 笔宽仍分离、在 0.05 笔宽接触。粗笔宽场景应保留原结果或独立处理布局，本轮没有为消除此结果而事后调参。',
        '', '![三档笔宽](brush.png)', '', '## 真正需要保留的外部风险拦截','',
        '“震”按原评分排列的前两个晨部件均因跨部件接触被拒，第三个在当前笔宽下通过。田、睡的根部件候选仍因新外部交叉/接触回退，原的根桥因结构/笔数不相容不建候选。不是所有作者来源都无条件放行。接触报警表示需要复核的外部关系风险，不等于每处接触都已经被人工认定为错误。','',
        '![未采用候选与实际输出](rejected.png)','',
        '## 几何差异仅作诊断','', '| 字 | 平均几何距离 A→D | 末向角差 A→D | 结论边界 |','| --- | --- | --- | --- |'])
    z=summaries['user_001']['character_metrics']['震'];a=z['A'];d=z['D']
    lines.append(f"| 震 | {a['mean_distance']:.6f} → {d['mean_distance']:.6f} | {a['terminal_angle_deg']:.2f}° → {d['terminal_angle_deg']:.2f}° | 原稿距离下降约 {(1-d['mean_distance']/a['mean_distance'])*100:.2f}%，末向略变；不据此判定风格优劣 |")
    lines.extend(['| 叵 | 无目标原稿 | 无目标原稿 | 仅确认真实来源保真与当前结构安全 |','',
        '不同点数沿用弧长积分评价，不压缩交付轨迹。原有折点、短钩、自然圆弯通过整部件等比变换保留；相对某次原稿的钩长或末向偏差不单独作为损伤。新增两例仍待用户人工风格验收，不能承接铜/伯的人工好评。',
        '', 'B 已获得震的 7 笔；C 与 B 在全部 100 例完全一致，因此取消参考差异硬拒没有新增实测覆盖收益，只有规则语义更正和边界测试证据。D 再新增口部 3 笔，属于来源池角色扩展，不能算排序改进。','',
        '## 保护字与自然圆弯',''])
    for w in WRITERS:lines.extend([f'![{w} 重点四字](focus_{w}.png)',''])
    lines.extend(['以下包含全部 98 个不变组合的同尺度 A/D 对照：',''])
    for name in guard_files:lines.append(f'- [保护图：{name}]({name})')
    lines.extend(['','## 使用范围与尚未解决事项','',
        '实验入口默认不开扩展，须显式启用 existing_pool 或根部件角色列表。生产入口没有导入本模块。建议将来源拓扑分类及可追溯整字桥保留在 v6.1 exp；当前显示笔宽下可以继续有限试用。震的粗笔宽接触尚未解决，仍需显式标记；饿的已有拥挤、映射未准入和其他参考回退也未因本轮自动解决。',
        '', '输入/代码/来源与参数见 protocol.json、各档案 records.json；生成先冻结于 generation_freeze.json，后续目标原稿评价存 evaluation.json。人工反馈另存 human_acceptance.json。没有全库扫描、重新建档、新网络或风险模型。'])
    (out/'report.md').write_text('\n'.join(lines)+'\n')
    write(out/'rejected_diagnostics.json',rejection_details)
    write(out/'manifest.json',{'script_sha256':sha(Path(__file__)),
        'inputs':{str(p):sha(p) for p in [root/'summary.json',root/'protocol.json',*sorted(root.glob('*/records.json')),*sorted(root.glob('*/evaluation.json'))]},
        'images':{p.name:sha(p) for p in sorted(out.glob('*.png'))},'brush_risk_gap':gap})


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True)
    run(p.parse_args().run)
