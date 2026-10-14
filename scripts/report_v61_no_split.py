"""Private same-scale review of the single reviewed no-split exception."""
from __future__ import annotations

import argparse
import html
from pathlib import Path

from generate_v61_library import CORRECTIONS, DB, WRITERS, digest, dump
from report_v61_exp import render
from run_v61_exp import dict_curves
from run_v61_no_split import CHARS
from run_v61_positional_variants import load

from inkstruct.glyph_frame_exp import reference_frame
from inkstruct.structure_corrections import CorrectedStructureRepository
from inkstruct.structures import StructureRepository
from inkstruct.trajectory_experiment import crossing_pairs
from inkstruct.v6_integrated_exp import framed_graph
from inkstruct.v61_contacts import segment_clearance


def run(root,out):
    freeze=load(root/'freeze.json')
    assert all(digest(p)==h for p,h in freeze['outputs'].items())
    out.mkdir(parents=True,exist_ok=False)
    records={(w,c):load(root/w/f'{ord(c):04X}.json.gz') for w in WRITERS for c in CHARS}
    base=StructureRepository(DB);target=CorrectedStructureRepository(base,*CORRECTIONS)
    g=target.get('群');g=framed_graph(g,reference_frame(g));ref=[s.median for s in g.strokes]
    r=records['user_001','群'];a,b=[dict_curves(r[k]['glyph']) for k in ('A','B')]
    render([{'title':'user_001 群\n整字','curves':[a,b,ref]},
            {'title':'尹部局部\n同尺度','curves':[a,b,ref],'indices':[0,1,2,3],
             'bounds':(.05,.05,.57,.70)}],['A 禁用前','B 禁用后＋作者单笔','当前参考（仅布局诊断）'],out/'qun.png')
    rows=[]
    for w in WRITERS:
        rr=records[w,'群']
        rows.append({'title':f'{w} 群','curves':[dict_curves(rr[k]['glyph']) for k in ('A','B')]})
    render(rows,['A 禁用前','B 禁用后'],out/'four_qun.png')
    for w in WRITERS:
        rows=[{'title':f'{w} {c}','curves':[dict_curves(records[w,c][k]['glyph']) for k in ('A','B')]}
              for c in CHARS if c!='群']
        render(rows,['A 禁用前','B 禁用后'],out/f'{w}_protection.png')
    changes=[{'writer':w,'character':c,**r['checks']} for (w,c),r in records.items() if r['checks']['changed_strokes']]
    protected=[]
    for w,c,donor in [('wsq','饿','馘'),('mjb','饿','戍'),('scx','儒','斋'),('wsq','儒','斋'),
                       ('scx','群','羸'),('wsq','群','羸')]:
        rr=records[w,c]
        before={i:p for i,p in rr['A']['provenance'].items() if p['character']==donor}
        assert before and all(rr['B']['provenance'][i]==p for i,p in before.items())
        assert dict_curves(rr['A']['glyph'])==dict_curves(rr['B']['glyph'])
        protected.append({'writer':w,'target':c,'source':donor,'orders':[int(i)+1 for i in before],
                          'source_and_transform_exact':True})
    head={k:{'stroke_2_4_strict_crossing':(1,3) in crossing_pairs(x),
             'stroke_3_4_strict_crossing':(2,3) in crossing_pairs(x),
             'obsolete_stroke_1_4_diagnostic':{'strict_crossing':(0,3) in crossing_pairs(x),
                                                'clearance':segment_clearance(x[0],x[3])}}
          for k,x in [('A',a),('B',b),('reference',ref)]}
    dump(out/'summary.json',{'changed':changes,'unchanged_cases':len(records)-len(changes),
                            'approved_paths':protected,'head_diagnostic':head,
                            'human_review':{'authority':'user clarification in this thread',
                                'scope':'user_001 群: two horizontal strokes pass through the long falling stroke',
                                'accepted':True,'criterion_orders':[[2,4],[3,4]],
                                'retracted':'requiring the long stroke to pass above the top horizontal; inferred reference-start defect',
                                'supersedes':'report_verified interpretation only; generation unchanged'},
                            'interpretation':'user confirms the intended crossing relation is correct; no reference-start repair warranted by the previous misinterpretation'})
    lines=['# v6.1 exp：禁止“尹→一＋尸”拆分复用', '',
        '**人工验收更正：这里的“穿头”指两横穿过长撇。用户确认新结果在这一关系上没有问题；撤回此前“未穿头”和参考起点异常的判断。**','',
        '本报告替代 report_verified 的相关解释，复用同一份冻结输出，不改生成代码、来源、变换或轨迹。第2/4、第3/4笔的真实线段交叉可作为辅助证据；验收依据为本次用户澄清，不把它扩大为全系统质量认证。','',
        '规则版本 `author_reuse_no_split_v1`；显式开关 `CandidateExpansionGenerator(..., split_rules=True)`。关闭时保持旧路径。原始数据库和作者档案未改。', '',
        '生产设计采用：整字 → 完整部件 → 关键笔替换 → 作者单笔 → 明确缺口。本轮验证排除所有同字供体，避免整字复用掩盖跨字错误；生产默认未切换。','',
        '## 本轮结果','',
        '固定四位作者、9 字，共36例。只改变 user_001“群”第1、3、4笔，其余35字的几何、压力、笔内时间与来源完全不变。',
        '没有找到可用完整“尹”或“君”候选：当前该作者档案在既有映射准入口径下的完整候选清单为空，并非本轮把它们禁止。旧“炉→尸”计划被撤销后，沿用原作者单笔回退，仍13/13笔为作者来源。','',
        '![整字和局部](qun.png)','',
        '## 逐笔来源和变换','',
        '所有新笔为同作者完整轨迹的正等比缩放和平移，没有拉长、弯折或补造撇。表中变换为 sx、sy、tx、ty，完整精度和原始哈希保存在运行 JSON 中。','',
        '|目标笔顺|修复前来源|修复后来源|新变换|变化|','|---:|---|---|---|---|']
    for i in range(13):
        p,q=(r[k]['provenance'][str(i)] for k in ('A','B'))
        source=lambda x:f"{x['character']} / {x['source_stroke_id']}"
        values=', '.join(f'{q["transform"][axis]:.8f}' for axis in ('sx','sy','tx','ty'))
        lines.append(f'|{i+1}|{source(p)}|{source(q)}|{values}|'+('替换' if i+1 in [1,3,4] else '原样保留')+'|')
    lines+=['','## 规则边界与追溯','',
        '只阻止尹节点下面“一＋尸”的拆分子单元及其后代参与作者部件检索/生成。完整尹、包含完整尹的君仍允许；户里的尸、其他位置的正常尸不受影响。作者单笔回退是独立的笔型检索，不伪称完整尸部件。',
        '来源库存和目标检索使用非破坏性的视图；原数据库子节点、动态展开、旧候选/计划均检查。最终输出还有旧计划拒绝门，不能直接绕过规则重放旧计划。',
        '各作者 source_audit.json 保存来源库存审核及规则日志，逐字记录保存被撤旧计划、版本、原因、完整候选清单与单笔来源。', '',
        '## 形态与安全验收','',
        '36例均通过笔数、标准ID/笔顺、有限坐标、压力、单调时间、退化/越界检查；来源逐点、压力、笔内时间核对通过。没有新增跨部件交叉或粘连，检查笔宽 .014/.028/.05。',
        'user_001“群”第1/3笔原有严格交叉消失；.014下第1/3、第1/4笔原有接触消失；.028和.05下接触集合不变。这些损失不自动计作收益。',
        '此前误把“穿头”解释为长撇穿过最上方横画，用第1/4笔关系判断验收，选错了检查对象。这里应关注两横（第2、3笔）穿过长撇（第4笔），用户已确认新结果没有问题。旧输出和参考也有这两对中心线交叉，不能把这个布尔指标单独当作新方案更好的证明，更不能据此推翻人工确认的拆分禁用规则。',
        '撤回此前“参考起点异常、需要穿头放置修复”的推断和建议。现有参考与作者轨迹均不因该误解改动；禁止尹→一＋尸的规则及正常复用保护结论保留。','',
        '## 已人工认可的保护路径','',
        '|作者|目标|来源|笔顺|结果|','|---|---|---|---|---|']
    for p in protected:
        lines.append(f"|{p['writer']}|{p['target']}|{p['source']}|{p['orders']}|来源、变换和输出完全不变|")
    lines+=['','![四位作者的群](four_qun.png)','',
            '## 其他保护字','', '已接受作者部件的内部交叉与自然圆弯没有因偏离参考而被重新拒绝；非命中案例未重跑候选排序。']
    for w in WRITERS:
        lines+=['',f'### {w}','',f'![保护字]({w}_protection.png)']
    (out/'report.md').write_text('\n'.join(lines))
    body=['<!doctype html><meta charset="utf-8"><title>尹拆分禁用复核</title><style>body{font:16px/1.7 system-ui;max-width:1200px;margin:auto;padding:24px}img{max-width:100%}table{border-collapse:collapse;width:100%;font-size:14px;margin:18px 0}td,th{border:1px solid #d8dee6;padding:8px;text-align:left}th{background:#eef3f7}p{margin:12px 0}</style>']
    table=False
    for line in lines:
        if line.startswith('|'):
            if not table:
                body.append('<table>');table=True;tag='th'
            else:
                tag='td'
            if not line.startswith('|---'):
                body.append('<tr>'+''.join(f'<{tag}>'+html.escape(v.strip())+f'</{tag}>' for v in line.strip('|').split('|'))+'</tr>')
            continue
        if table:
            body.append('</table>');table=False
        if line.startswith('!['):
            name=line.split('](')[1][:-1];body.append(f'<img src="{name}">')
        elif line.startswith('#'):
            level=len(line)-len(line.lstrip('#'))
            body.append(f'<h{level}>'+html.escape(line.lstrip('# '))+f'</h{level}>')
        else:
            body.append('<p>'+html.escape(line.replace('**',''))+'</p>')
    (out/'index.html').write_text('\n'.join(body))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args();run(a.root,a.output)
