"""Render source admission evidence, unchanged guards, and two-repeat evaluation."""
from __future__ import annotations

import argparse
import html
import json
from collections import defaultdict
from pathlib import Path

from report_v61_exp import render
from run_v6_exp import sha, write
from run_v61_exp import dict_curves

from inkstruct.geometry import bbox
from inkstruct.profile import load_profile


def load(path):
    return json.loads(path.read_text())


def run(root, report_dir='report'):
    out=root/report_dir;out.mkdir(exist_ok=False)
    rows=load(root/'records.json');records={r['character']:r for r in rows}
    summary=load(root/'summary.json');protocol=load(root/'protocol.json')
    data={c:load(root/'glyphs'/f'{ord(c):04X}.json') for c in records}
    originals=defaultdict(list)
    for r in load(root/'evaluation.json'):originals[r['character']].append(r['original'])
    labels=['原稿 1（仅评估）','原稿 2（仅评估）','A 当前','B 整字→部件','C 原有交叉复核','D 两项结合']

    def panel(c, title=None, indices=None, bounds=None):
        r={'title':title or c,'curves':(originals[c]+[None,None])[:2]+[dict_curves(data[c][a]) for a in 'ABCD']}
        if indices is not None:r['indices']=indices
        if bounds is not None:r['bounds']=bounds
        return r

    render([panel(c) for c in '铜伯'],labels,out/'main.png')
    # Use one shared crop per row from all displayed curves, never crop
    # each arm independently to disguise scale or placement differences.
    locals=[]
    for c,indices,name in [('铜',[6],'铜·外框钩'),('铜',[8,9,10],'铜·内口'),('伯',[4,6],'伯·白底交叉')]:
        displays=[dict_curves(data[c][a]) for a in ('A','D')]+originals[c]
        xy=[p for display in displays for i in indices for p in display[i]]
        x0,y0,x1,y1=bbox(xy)
        if c=='伯':y0=max(y0,y1-.30)
        if c=='铜' and indices==[6]:y0=max(y0,y1-.28)
        locals.append(panel(c,name,indices,(x0-.04,y0-.04,x1+.04,y1+.04)))
    render(locals,labels,out/'local.png')
    widths=[]
    for c in '铜伯':
        for w in (.014,.028,.05):
            r={'title':f'{c}\n笔宽 {w:.3f}','curves':[dict_curves(data[c][a]) for a in 'AD'],'brush_width':w}
            widths.append(r)
    render(widths,['A 当前','D 两项结合'],out/'brush.png')
    guards=[c for c in records if c not in '铜伯']
    for i in range(0,len(guards),8):
        render([{'title':f'{c}\n轨迹不变','curves':[dict_curves(data[c][a]) for a in 'AD']} for c in guards[i:i+8]],
               ['A 当前','D 两项结合'],out/f'guards_{i//8+1}.png')
    render([panel(c) for c in '懂使枝便慢悦'],labels,out/'other_validation.png')
    archive=load_profile(Path('artifacts/v61_collection_acceptance_20261013/run_v3_with_validation/source_archive.json'))
    source_rows=[]
    for c,sourcechar in [('铜','同'),('伯','怕')]:
        p=next(p for p in records[c]['arms']['D']['provenance'] if p['candidate']['character']==sourcechar)
        sample=archive.source_trajectories[p['candidate']['sample_id']]
        ss={s.standard_stroke_id:s for s in sample.strokes}
        raw=[ss[k].points for k in p['candidate']['stroke_ids']]
        placed=[dict_curves(data[c]['D'])[i] for i in p['indices']]
        reference=[dict_curves(data[c]['A'])[i] for i in p['indices']]
        source_rows.append({'title':f'{sourcechar} → {c}\n整部件共用变换','curves':[raw,reference,placed]})
    render(source_rows,['原始完整来源（原坐标）','A 对应参考部件','D 等比放置部件'],out/'sources.png')
    lines=['# v6.1 exp：完整同复用于铜、白部原有交叉复核',
        '', '生产默认不变。本次只验证两条明确的来源准入缺口，不改候选排序、布局拟合或档案。',
        '', '## 对照与边界',
        '', '- A：当前冻结结果；B：只新增完整“同”到右部“同”的有序映射桥；C：只准入已逐源复核的“怕”白部内部交叉；D：二者结合。',
        '- 338 份训练档案、修正参考版本、原有拟合与映射门槛不变。所有目标字及重复样本均不进入训练。',
        '- 31 字均为已观察的回归字；此前 8 字验证结果已公开，本次不能再称新盲测。18 字共 28 份原稿用于评估；每个字的重复样本先归组。',
        '- B 改的是来源角色准入与覆盖，C 改的是误拒判断；不是候选排序或布局优化。',
        '- 生成文件和哈希先冻结，再读取目标原稿；源内部交叉的复核只看训练原稿。',
        '- 不新增平滑、轨迹平均、逐笔缩放或自由形变。完整原始点、压力和笔内时间差逐项核对，最终时间按输出笔顺重排。',
        '', '## 整字与局部', '', '![同尺度整字](main.png)', '', '![同尺度局部](local.png)',
        '', '![完整来源与等比放置](sources.png)',
        '', '## 来源与准入证据',
        '', '| 字 | A 作者笔数 | D 作者笔数 | 变化 |', '| --- | ---: | ---: | --- |']
    for c in '铜伯':
        r=records[c];n=len(data[c]['A']['strokes'])
        lines.append(f"| {c} | {r['arms']['A']['integrity']['source_strokes']}/{n} | {r['arms']['D']['integrity']['source_strokes']}/{n} | "+('银的钅不变；完整同六笔共用一个变换' if c=='铜' else '什的亻不变；怕的白五笔共用原候选变换')+' |')
        for p in r['arms']['D']['log']['placement']:
            lines.extend(['',f"{c}：等比变换与准入结果：`{json.dumps({'transform':p['transform'],'accepted':p['accepted'],'new_pairs':p['topology']['new_pairs'],'reviewed_inherited_pairs':p['topology']['reviewed_inherited_pairs'],'new_external_brush_contacts':p['new_cross_boundary_contacts']},ensure_ascii=False)}`。数组索引从 0 开始；面向人的笔序从 1 开始。"])
    lines.extend(['', '铜：源“同”的 s1–s6 顺序对应目标 s6–s11。根节点完整性、部件身份/字形变体、笔数、笔顺、原档案可靠映射和参考版本桥均需成立；有序参考对应平均/最大误差约 0.0331/0.0967，低于沿用的 0.08/0.22 界限。没有把所有整字无条件放进部件池。',
        '', '伯：旧拒绝对是目标第 5/7 笔，即白部第 3/5 笔；供体“怕”原稿第 6/8 笔已经在底部收笔处相交。这里将其标为“已观察并复核的来源内部交叉”，不是凭交叉位于内部就一律认定自然。复核记录绑定具体样本哈希、源部件、笔画 ID、目标角色及交叉对；放置后的内部交叉对须与源完全一致，新增外部交叉继续拒绝。',
        '', '原拟合没有改变：伯仍采用原候选记录的变换。新增跨部件笔宽接触也会拒绝；不通过放宽全局交叉阈值实现。',
        '', '## 原稿几何评价（只作辅助）', '', '| 字 | 平均几何距离 A→D | 末向角差 A→D | 端点距离 A→D |', '| --- | --- | --- | --- |'])
    for c in '铜伯':
        a,d=(summary['character_metrics'][c][k] for k in 'AD')
        lines.append(f"| {c} | {a['mean_distance']:.6f} → {d['mean_distance']:.6f} | {a['terminal_angle_deg']:.2f}° → {d['terminal_angle_deg']:.2f}° | {a['endpoint_error']:.5f} → {d['endpoint_error']:.5f} |")
    lines.extend(['', '按弧长积分比较不同点数折线，评估间距 0.003；交付轨迹未重采样。逐笔距离、末向、末端转折、弧长误差在 evaluation.json。弧长更近不能单独证明质量，自动末端转折指标也不是语义短钩真值。',
        '', '## 图像复核：收益与局部退步同时存在', '',
        '**铜：** 内口恢复供体原有的圆弯、开口与倾斜，外框钩由参考的横向折尾变为作者来源的斜上收钩，末向更接近两份目标原稿。但供体的外钩明显偏长：第 7 笔平均距离由 0.02351 升至 0.04139，端点距离由 0.05636 升至 0.10322。右部总体仍较两份目标原稿偏小，完整整字可用并不等于等比缩入任意位置都适配。', '',
        '**伯：** 顶撇、白部圆弯和右下钩恢复了作者来源特征，整字字体化减轻。但怕的白部底横与收钩相连，而两份伯原稿底部均留有开口；直接复用也把这处不适配的连接带过来了。第 5 笔距离由 0.03602 升至 0.04486，自动末端转折长度误差由 0.00410 升至 0.01141；第 6 笔末向角差由 62.41° 升至 80.01°。不能据整字均差下降就称全部更好。', '',
        '**判定：** 原规则确实把“相对字体新增交叉”混同于“放置引入的新碰撞”，应拆分；但一个交叉来自真实源，只证明来源保真，不能证明适合目标。保留本来源特定的实验许可，不自动推广到所有内部交叉，不逐笔剪钩或强行开口。下一步需要更多同角色完整供体与独立未观察目标，验证开口/钩长适配；当前目标原稿不能倒流到选供体规则。',
        '', '## 安全与保护字', '', f"{summary['cases']} 字 × 4 路：笔数、标准 ID、笔顺、有限坐标、压力范围、全局非递减时间、越界和退化检查通过。其余 29 字的笔画坐标、压力、时间及 ID/笔顺/置信度完全不变；v61 输出器来源说明标签的词汇会改变，不能把标签变化算成字形变化。", '',
        '伯新增 1 对严格中心线交叉，恰为经复核继承的源内部对；不能报告为“零新增交叉”。铜无新增严格交叉。显示笔宽接触单独列出：',
        '', '| 字 | 笔宽 | 新增接触（1 起笔序） | 新增跨来源接触 |', '| --- | --- | --- | --- |'])
    for c in '铜伯':
        for width,result in records[c]['arms']['D']['contacts'].items():
            fmt=lambda ps:'、'.join(f'{a+1}/{b+1}' for a,b in ps) or '无'
            lines.append(f"| {c} | {width} | {fmt(result['new'])} | {fmt(result['new_between_sources_or_reference'])} |")
    lines.extend(['', '![三档显示笔宽](brush.png)', '', '下列保护字全部保留现有轨迹，包括而、相、儒、荡、叵和饿；相的既有接触、饿的既有间距风险没有因本次试验而解决。', ''])
    for i in range(0,len(guards),8):lines.extend([f'![保护字 {i//8+1}](guards_{i//8+1}.png)',''])
    lines.extend(['## 其余原验证字','', '![其余六字与原稿](other_validation.png)', '',
        '懂、使、枝、便、慢、悦完全不变，其右部仍为参考回退、个性化不足。本轮不扩大到这些部件。', '',
        '## 能力边界与复现', '',
        '原生产入口没有导入本实验模块。`AdmissionProbeGenerator.probe(ctx)` 默认关闭两个准入探针；只有显式给定根部件角色白名单或来源复核清单才开启。源复核不是可复制到所有作者/部件的通行证。', '',
        '输入/代码哈希在 protocol.json，生成冻结在 generation_freeze.json；records.json 保留实际来源、标准对应、变换、交叉及拒绝原因。旧样本/数据库/档案/输出均未覆盖。此前报告流程试运行目录保留，不计入正式结果。', '',
        '本报告图像使用相同字框和固定圆形笔刷，非设备实写结果；源码的折线关节没有经过几何平滑。以上图像判断为本轮逐图检查，尚无独立人工盲评。'])
    (out/'report.md').write_text('\n'.join(lines)+'\n')
    # HTML keeps the local gallery easy to inspect without external assets.
    body=[]
    for line in lines:
        if line.startswith('!['):
            alt,url=line[2:].split('](',1);body.append(f'<figure><img src="{html.escape(url[:-1])}"><figcaption>{html.escape(alt)}</figcaption></figure>')
        else:body.append(f'<p>{html.escape(line)}</p>')
    (out/'report.html').write_text('<!doctype html><meta charset="utf-8"><title>v6.1 完整部件准入对照</title><style>body{font:16px system-ui;max-width:1800px;margin:32px auto;padding:0 20px;color:#22354b}img{max-width:100%}p{white-space:pre-wrap}figure{margin:24px 0}</style>'+''.join(body))
    write(out/'manifest.json',{'code':{str(Path(__file__)):sha(Path(__file__))},
        'inputs':{str(root/f):sha(root/f) for f in ('records.json','summary.json','evaluation.json','protocol.json')},
        'images':{p.name:sha(p) for p in sorted(out.glob('*.png'))},'protocol':protocol['name']})


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True)
    p.add_argument('--report-dir',default='report')
    args=p.parse_args()
    run(args.run,args.report_dir)
