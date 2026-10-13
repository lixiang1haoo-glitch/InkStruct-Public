"""Visual report for the reference-dependence ablation; uses shared v6.1 renderer."""
from __future__ import annotations

import argparse
import html
import json
from collections import Counter
from pathlib import Path

import numpy as np
from report_v6_integrated_exp import svg_panel
from report_v61_exp import closest_pair, render
from run_v6_exp import sha, write
from run_v61_exp import WRITERS, dict_curves
from run_v61_reference_exp import ARMS

from inkstruct.v61_contacts import segment_clearance

LABELS = ['A 当前参考方式', 'R 旧重排控制', 'B 降低参考权重', 'C 固定供体改布局', 'D 排序＋布局']


def load(p):
    return json.loads(p.read_text())


def run(root, report_dir="report"):
    out = root / report_dir
    out.mkdir(exist_ok=False)
    summaries = load(root / 'summary.json')
    data, records, originals, gallery = {}, {}, {}, []
    for writer in WRITERS:
        records[writer] = {r['character']:r for r in load(root / writer / 'records.json')}
        data[writer] = {c:load(root / writer / 'glyphs' / f'{ord(c):04X}.json') for c in records[writer]}
        originals.update({(writer,i['character']):i['original'] for i in load(root/writer/'evaluation.json')})

    contact_review = []
    for writer, rs in records.items():
        truth = load(root / writer / 'evaluation.json')
        for c, rec in rs.items():
            samples = [v for v in truth if v['character'] == c]
            for arm in 'RBCD':
                for i, j in rec['brush_sensitivity_new_pairs_vs_A']['0.05'][arm]:
                    gaps = [segment_clearance(v['original'][i], v['original'][j]) for v in samples]
                    status = ('no_target_original' if not gaps else
                              'contact_in_all_originals' if max(gaps) <= .05 else
                              'no_contact_in_all_originals' if min(gaps) > .05 else 'mixed_originals')
                    contact_review.append({'writer':writer, 'character':c, 'arm':arm,
                                           'orders':[i+1,j+1], 'original_gaps':gaps, 'status':status})
    write(out / 'contact_original_review.json', contact_review)

    def row(w,c,title=None,truth=False):
        xy = [dict_curves(data[w][c][k]) for k in ARMS]
        return {'title':title or f'{w}\n{c}', 'curves':([originals.get((w,c))] if truth else []) + xy}

    for w in WRITERS:
        render([row(w,c) for c in '而相儒荡'],LABELS,out/f'{w}_main.png')
        zoom = []
        for c,pair in [('相',(5,8)),('儒',(5,10))]:
            r = row(w,c)
            _,a,b = closest_pair(r['curves'][0][pair[0]],r['curves'][0][pair[1]])
            z = (a+b)/2
            r.update(indices=list(pair),pair=pair,bounds=(z[0]-.18,z[1]-.18,z[0]+.18,z[1]+.18))
            zoom.append(r)
        for c,i in [('而',3),('荡',6)]:
            r = row(w,c)
            z = r['curves'][0][i][-2]
            r.update(indices=[i],bounds=(z[0]-.16,z[1]-.16,z[0]+.16,z[1]+.16))
            zoom.append(r)
        render(zoom,LABELS,out/f'{w}_local.png')
        render([row(w,c) for c in ('叵','生','砖','桂','黧','瀝')],LABELS,out/f'{w}_protect.png')
        for c,g in data[w].items():
            r = records[w][c]
            count = r['integrity']['A']
            gallery.append(f'<h3>{w} · {c}：作者 {count["source_strokes"]} 笔 / 参考 {count["reference_strokes"]} 笔</h3>'
                '<div class="row">'+''.join(f'<div><b>{html.escape(label)}</b>{svg_panel(xy)}</div>'
                for label,xy in [('原稿（仅评价）',originals.get((w,c)))]+
                list(zip(LABELS,[dict_curves(g[k]) for k in ARMS],strict=True)))+'</div>')
    # Show the actual best and worst available target-original cases, never cherry-pick gains.
    comparisons = []
    examples = []
    for arm,base in [('B','R'),('C','A'),('D','A')]:
        values = [(v[arm]['mean_distance']-v[base]['mean_distance'],w,c)
                  for w,s in summaries.items() for c,v in s['per_character'].items()
                  if abs(v[arm]['mean_distance']-v[base]['mean_distance'])>1e-12]
        if values:
            for delta,w,c in [min(values),max(values)]:
                examples.append(row(w,c,f'{w} {c}\n{arm}−{base}: {delta:+.5f}',True))
            comparisons.append({'arm':arm,'base':base,'best':min(values),'worst':max(values)})
    for w,c in [('mjb','似'),('user_001','饿'),('user_001','叵')]:
        examples.append(row(w,c,truth=True))
    render(examples,['原稿，仅评价']+LABELS,out/'outcomes.png')
    natural=[]
    for w,c,i in [('user_001','码',4),('user_001','认',1),('scx','儒',12)]:
        r=row(w,c,truth=True)
        xy=np.array(r['curves'][1][i]);a=xy.min(axis=0)-.05;b=xy.max(axis=0)+.05
        r.update(indices=[i],bounds=(*a,*b));natural.append(r)
    render(natural,['原稿，仅评价']+LABELS,out/'natural_curves.png')
    sensitive=[]
    for w,rs in records.items():
        for c,r in rs.items():
            if (w,c) not in {('wsq','噗'),('scx','相'),('user_001','坡'),('user_001','儒')}:
                continue
            if any(r['brush_sensitivity_new_pairs_vs_A'][str(width)][k]
                   for width in (.014,.05) for k in 'BCD'):
                for width in (.028,.05):
                    item=row(w,c,f'{w} {c}\n笔宽 {width}',True)
                    item['brush_width']=width;sensitive.append(item)
    if sensitive:
        render(sensitive,['原稿，仅评价']+LABELS,out/'brush_sensitivity.png')
    macro={k:{f:float(np.mean([s['macro'][k][f] for s in summaries.values()]))
              for f in ('mean_distance','terminal_angle_deg','absolute_length_error')} for k in ARMS}
    changes={k:sum(s['changed_vs_A'][k] for s in summaries.values()) for k in ARMS}
    coverage={k:{f:sum(s[f][k] for s in summaries.values())
                 for f in ('source_strokes','reference_strokes')} for k in ARMS}
    brush={str(width):{k:sum(len(r['brush_sensitivity_new_pairs_vs_A'][str(width)][k])
                 for rs in records.values() for r in rs.values()) for k in ARMS}
           for width in (.014,.028,.05)}
    aggregate={'macro':macro,'changes':changes,'coverage':coverage,'extra_brush_pairs':brush,
               'contact_review':{k:dict(Counter(x['status'] for x in contact_review if x['arm']==k))
                                 for k in 'RBCD'},
               'comparisons':comparisons}
    write(out/'aggregate.json',aggregate)
    table=''.join(f'<tr><td>{LABELS[j]}</td><td>{macro[k]["mean_distance"]:.8f}</td>'
        f'<td>{macro[k]["terminal_angle_deg"]:.4f}°</td><td>{macro[k]["absolute_length_error"]:.6f}</td>'
        f'<td>{changes[k]}</td><td>{coverage[k]["source_strokes"]}/{coverage[k]["reference_strokes"]}</td></tr>'
        for j,k in enumerate(ARMS))
    group=''.join(f'<tr><td>{w}</td><td>{len(s["per_character"])}</td>'+''.join(
        f'<td>{s["macro"][k]["mean_distance"]:.6f}</td>' for k in ARMS)+'</tr>' for w,s in summaries.items())
    pics=''.join(f'<h3>{w}：整字、局部、保护字</h3>'+''.join(
        f'<a href="{w}_{part}.png"><img src="{w}_{part}.png"></a>' for part in ('main','local','protect')) for w in WRITERS)
    report='''<!doctype html><meta charset="utf-8"><title>v6.1 exp：参考影响有限对照</title>
<style>body{font:16px system-ui;max-width:1500px;margin:28px auto;padding:20px;color:#203245}p{line-height:1.7}img{width:100%;height:auto}.row{display:grid;grid-template-columns:repeat(6,1fr);gap:8px}.row svg{width:100%}table{border-collapse:collapse}th,td{padding:8px;border:1px solid #ccd6df}h2{margin-top:40px}.note{background:#fff0ce;padding:16px}</style>
<h1>v6.1 exp：减轻参考中心线影响</h1>
<p>基于 d782a54；复用现有档案、嵌套视图、候选池、统一字框与完整轨迹。生产默认不变。本轮没有扩池、重新建档、逐笔形变、平均轨迹或平滑。</p>
<p class="note">A 是上一轮 B（冻结的 v6 完整轨迹参考方式）；R 是上一轮 C（旧 v6.1 候选重排）。B 对 R 只把参考几何评分权重从1降为0.25；B 对 A还含已有末向/间隙评分，不能全部归因于降权。C 固定 A 供体，以整体范围代替中心线锚点拟合；D 固定 B 供体使用同一布局。上一轮 E不是本轮A，避免将它的平移收益重复混入。</p>
<h2>本轮结论</h2><p>B对R的纯排序降权使几何均差下降0.148%，但仅3个可评原稿组合改变；wsq‘噗’末向略退步，粗笔刷新增相对A的接触，但其原稿也接触，不能判为损伤。C对A均差增加1.54%，D增加1.86%。mjb‘似’左部位置有改善，user_001‘坡’整体放置明显退步。不能将‘减少参考拟合’直接视为收益。</p>
<p>三档额外新增笔宽接触对：0.014与0.028均为0；0.05下R/B/C/D分别为1/2/14/17。B比R多出wsq‘噗’，其原稿第1/3笔间距0.01881，确有接触；B仍继承R的‘宵’异常接触。C的14对中有6对对应原稿不接触、1对原稿也接触、7对无原稿；D的17对对应7/2/8。新增提示不自动等于错误。本轮未根据这些结果继续调参。</p>
<h2>参考影响入口与取舍</h2><table><tr><th>阶段</th><th>参考如何进入</th><th>本轮处理</th></tr>
<tr><td>建档映射</td><td>形状、位置、端点、弧长、方向共同决定对应关系和置信度，会排斥差异大的写法</td><td>保留一对一、标准ID、笔顺、版本与置信度门槛；不重建档案</td></tr>
<tr><td>候选筛选</td><td>同身份/角色/笔数后，源字与目标字的字体部件形状和宽高比筛选，再取前16</td><td>原池冻结；放宽过滤或跨角色准入不混入排序实验</td></tr>
<tr><td>候选排序</td><td>作者轨迹对目标参考锚点残差主导，附加旧检索分数</td><td>B只降低几何参考项权重；置信度、作者末向特征、邻件间隙项不变</td></tr>
<tr><td>变换与布局</td><td>逐笔锚点最小二乘决定共同尺度/位置；参考还提供分离及接触提示</td><td>C以整体边界替代内部锚点，但字体边界不是作者真值；已出现负面结果</td></tr>
<tr><td>回退</td><td>没有可靠供体时，直接输出完整参考</td><td>明确标记个性化不足；不添加伪弯曲或噪声</td></tr></table>
<p>182个目标部件槽中：85采用作者实例、89没有当前同上下文索引实例、2被参考形状/比例过滤清空、6有候选但放置门槛拒绝。701笔回退分别对应607笔上下文来源不足、6笔参考过滤、21笔放置拒绝、67笔未进入多笔叶部件替换。此范围内主要覆盖瓶颈不是单一的中心线形状过滤。</p>
<h2>实验边界</h2><p>92个既有回归组合，38个可评组合/40份原稿；无新盲测。所有目标同字采样整组从建档剔除，原稿在全部生成冻结后才读入。主要问题字没有可用原稿；空白原稿栏表示缺失，不代表复制。参数只做预先冻结的一档敏感性测试，未根据本次误差调参。</p>
<p>完整源表示与版本保持一致。所有作者部件共用一个正等比变换。范围布局仍读取参考部件边界和粗位置，不能称为已经学会作者布局。实际笔段用于接触判断；不强闭合。0.028笔宽安全门槛保持不变；0.014和0.05为额外敏感性检查。</p>
<h2>数值对照（不是风格质量分）</h2><table><tr><th>路径</th><th>几何均差</th><th>末向均差</th><th>弧长相对误差</th><th>变化组合</th><th>作者/参考笔数</th></tr>'''+table+'''</table>
<p>按笔、重复样本、字、档案分层等权；统一0.003弧长积分，不改交付点列。距离下降、弧长接近和交叉检查都不等于风格更好。</p><table><tr><th>档案</th><th>可评字数</th><th>A</th><th>R</th><th>B</th><th>C</th><th>D</th></tr>'''+group+'''</table>
<h2>收益、退步与未解决例</h2><p>前六行按可评原稿几何变化展示各消融变化的两端；B对R的三例均差都下降，其第二行是改善最小者，不称退步。随后固定展示 mjb“似”、user_001“饿”“叵”。观感仍需人工评判。</p><img src="outcomes.png">
<h2>作者原有圆弯</h2><p>共同等比变换保留来源内部角度、圆弯和相对关系，但更换供体或缩放会改变绝对尺度与邻件关系。</p><img src="natural_curves.png">
'''+('<h2>笔宽敏感性：风险与原稿已有接触分开</h2><p>噗的新增接触有原稿支持；坡的新增接触没有原稿支持。相、儒缺原稿，仅作结构风险提示。</p><img src="brush_sensitivity.png">' if sensitive else '')+pics+'''
<h2>全部92组，统一0–1字框和笔宽</h2>'''+''.join(gallery)+'''
<h2>溯源与能力边界</h2><p>每字 records.json 记录冻结池、每笔来源、完整供体身份、最终共同变换、评分、拒绝原因、笔段/端点间隙和三档笔宽检查。reference_fallback_style_insufficient 明确表示参考回退、个性化不足。完整作者点列、压力和笔内时间逐点核验，最终时间按标准笔顺重排。</p><p>未扩池，因此覆盖不足不能算作排序/布局解决；来源映射与参考接触安全门槛仍有历史偏向。本轮不证明字体接触是真值，也不以远离字体为目标。详细结论见仓库 docs/V61_REFERENCE_INFLUENCE_20261013.md。</p>'''
    (out/'报告.html').write_text(report)
    write(out/'manifest.json',{'renderer_sha256':sha(Path(__file__)),
        'shared_renderer_sha256':sha(Path('scripts/report_v61_exp.py')),
        'protocol_sha256':sha(root/'protocol.json'),
        'images':{p.name:sha(p) for p in out.glob('*.png')}})
    print(json.dumps(aggregate,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run',type=Path,required=True)
    p.add_argument('--report-dir',default='report')
    args=p.parse_args()
    run(args.run,args.report_dir)
