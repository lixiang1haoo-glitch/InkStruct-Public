"""Private same-scale gallery for candidate expansion, with source provenance."""
from __future__ import annotations

import argparse
import gzip
import html
import json
from collections import Counter
from pathlib import Path

import numpy as np
from generate_v61_library import digest
from report_v61_exp import render
from run_v61_exp import dict_curves

from inkstruct.trajectory_experiment import stroke_metrics

LABELS = {'A': '原 v6.1', 'B_context': '只放宽上下文', 'C_hierarchy': '只扩层级',
          'D_nested': '只扩嵌套', 'E_whole': '只增整字目标', 'F_combined': '组合·等比', 'G_axes': '组合后·有界非等比'}


def load(path):
    return json.loads(gzip.decompress(path.read_bytes()) if path.suffix == '.gz' else path.read_bytes())


def svg(glyph):
    paths = []
    for s in glyph['strokes']:
        color = '#185c94' if 'author' in s['style_source'] else '#a05b43'
        d = 'M' + ' L'.join(f'{p["x"]:.8f},{p["y"]:.8f}' for p in s['points'])
        paths.append(f'<path d="{d}" stroke="{color}"/>')
    return '<svg viewBox="-.04 -.04 1.08 1.08"><g fill="none" stroke-width=".028" stroke-linecap="round" stroke-linejoin="round">'+''.join(paths)+'</g></svg>'


def report(root, out, extra_roots=()):
    out.mkdir(parents=True, exist_ok=False)
    roots = [root, *extra_roots]
    rows = [r for folder in roots for r in load(folder/'summary.json')]
    assert len({(r['writer'], r['character']) for r in rows}) == len(rows)
    totals = {'total_strokes': sum(r['strokes'] for r in rows), 'arms': {}}
    for arm in LABELS:
        totals['arms'][arm] = {
            'source_strokes': sum(r['arms'][arm]['integrity']['source_strokes'] for r in rows),
            'changed_cases': sum(not r['arms'][arm]['unchanged'] for r in rows),
            'new_external_crossing_cases': sum(bool(r['arms'][arm]['new_cross_component_crossings']) for r in rows),
            'new_contact_cases': {w: sum(bool(r['arms'][arm]['new_cross_component_contacts'][w]) for r in rows) for w in ('0.014','0.028','0.05')}}
    files = [p for folder in roots for p in folder.glob('*/*.json.gz')]
    frozen = {str(p): digest(p) for p in files}
    truth_files = list(Path('artifacts/v61_source_topology_20261013/run_v1').glob('*/evaluation.json'))
    truth = {}
    for file in truth_files:
        for item in load(file):
            truth.setdefault((file.parent.name, item['character']), []).append(item)
    evaluations = []
    lines = ['# v6.1 exp 候选限制扩展实测', '',
             '仅开发/回归案例；生产默认未变。所有旧全库基线逐点一致。蓝色为作者轨迹，棕色为参考回退。', '',
             '参数在本批生成前冻结，未用目标原稿选择来源或调整参数；没有新留出结论。', '',
             '| 路径 | 作者笔画 | 覆盖率 | 改变字数 | 新增跨部件交叉字数 |', '|---|---:|---:|---:|---:|']
    for arm, data in totals['arms'].items():
        lines.append(f'| {LABELS[arm]} | {data["source_strokes"]} / {totals["total_strokes"]} | {data["source_strokes"]/totals["total_strokes"]:.1%} | {data["changed_cases"]} | {data["new_external_crossing_cases"]} |')
    lines += ['', '各单项均从 A 独立出发；组合结果不能用单项相加。非等比 G 从 F 出发，只处理仍未覆盖的部分，整部件横纵比例差上限 1.35。', '',
              '上下文实验保留身份、字形变体、笔数及可靠映射。嵌套实验同时验证目标与来源视图；所有新增跨上下文/层级对应均增加有序参考核验，因此不是简单取消一条过滤。', '',
              '组合实验优先尝试较大的完整部件，仅当作者笔画覆盖严格增加时才可能替换已接受的小部件，并重新检查相对旧输出的跨边界碰撞。布局仍为参考锚点拟合，尚未解决参考布局支配问题。', '',
              '有界非等比保留所有点、压力与笔内时间，但会改变折角角度、末向、宽高比例和圆弯；不应称为与等比相同的几何保真。', '',
              '## 逐字结果', '', '| 作者 | 字 | A | 上下文 | 层级 | 嵌套 | 整字目标 | F | G |', '|---|---|---:|---:|---:|---:|---:|---:|---:|']
    gallery = []
    rejected = Counter()
    case_records = {}
    for row in rows:
        writer, char = row['writer'], row['character']
        path = next(folder/writer/f'{ord(char):04X}.json.gz' for folder in roots if (folder/writer/f'{ord(char):04X}.json.gz').exists())
        record = load(path)
        originals = {s['sample_id']: s for s in record['evaluation_originals']}
        for item in truth.get((writer,char), []):
            originals[item['sample_id']] = {'sample_id':item['sample_id'], 'curves':item['original']}
        record['evaluation_originals'] = list(originals.values())
        for original in originals.values():
            metrics = {}
            for arm in LABELS:
                xy = dict_curves(record['arms'][arm]['glyph'])
                if len(xy) != len(original['curves']):
                    continue
                metrics[arm] = [stroke_metrics(a,b) for a,b in zip(xy,original['curves'],strict=True)]
            evaluations.append({'writer':writer,'character':char,'sample_id':original['sample_id'],'metrics':metrics})
        case_records[(writer,char)] = record
        counts = [record['arms'][a]['checks']['integrity']['source_strokes'] for a in LABELS]
        lines.append('| '+writer+' | '+char+' | '+' | '.join(str(n) for n in counts)+' |')
        panels = []
        for arm, label in LABELS.items():
            r = record['arms'][arm]
            sources = '; '.join(p['candidate']['character']+' / '+p['candidate']['component_id']+
                               f' → {p["component_id"]} [{p["transform"]["sx"]:.3f}, {p["transform"]["sy"]:.3f}]' for p in r['provenance'])
            panels.append(f'<div><b>{label} · {r["checks"]["integrity"]["source_strokes"]}/{row["strokes"]}</b>{svg(r["glyph"])}<small>{html.escape(sources) or "参考回退、个性化不足"}</small></div>')
        for r in record['arms']['G_axes']['log']:
            if r.get('rejected'):
                rejected[str(r['rejected'])] += 1
            if r.get('fallback_reason'):
                rejected[r['fallback_reason']] += 1
        gallery.append(f'<section><h2>{writer} · {char}</h2><div class="grid">'+''.join(panels)+'</div></section>')
    selected = [('user_001','想'),('user_001','田'),('user_001','睡'),('user_001','而'),
                ('user_001','铜'),('user_001','伯'),('mjb','把'),('wsq','闻'),('scx','媷'),
                ('mjb','涸'),('wsq','羝'),('scx','谣')]
    # Always include every additional axis success, including negative-looking ones.
    selected += [k for k,r in case_records.items() if r['arms']['G_axes']['checks']['integrity']['source_strokes'] > r['arms']['F_combined']['checks']['integrity']['source_strokes'] and k not in selected]
    details = []
    for key in selected:
        if key not in case_records:
            continue
        r = case_records[key]
        writer,char = key
        variants = [dict_curves(r['arms'][a]['glyph']) for a in ('A','F_combined','G_axes')]
        originals = r['evaluation_originals']
        variants.append(originals[0]['curves'] if originals else None)
        # Common viewport for every arm. Region comes from affected output strokes,
        # never from the target original or any tuning operation.
        affected = sorted({i for p in r['arms']['F_combined']['provenance'] for i in p['indices']
                           if any(variants[0][i] != v[i] for v in variants[1:3])})
        if not affected:
            affected = list(range(len(variants[0])))
        coords = np.asarray([p for v in variants[:3] for i in affected for p in v[i]])
        lo, hi = coords.min(axis=0)-.04, coords.max(axis=0)+.04
        # A second panel zooms the lower area to expose hooks, endpoints and contacts.
        lo[1] = max(lo[1], hi[1] - .45)
        name = f'{writer}-{ord(char):04X}.png'
        render([{'title': f'{writer}\n{char} 整字', 'curves': variants},
                {'title': '下部局部\n共用窗口', 'curves': variants, 'bounds': (*lo,*hi), 'indices': affected}],
               ['A 当前', 'F 组合等比', 'G 有界非等比', '原稿（若有，仅评估）'], out/name)
        details.append(f'<h3>{writer} · {char}</h3><img src="{name}" style="max-width:100%">')
        lines += ['', f'### {writer} · {char}', '', f'![整字及局部]({name})']
    lines += ['', '## 负面与边界', '', '新增来源覆盖不是人工风格验收。无原稿时只判断来源保真与结构；原稿可能有自然书写波动。', '',
              '笔宽 0.014、0.028、0.05 的新增跨部件接触统计：', '', '```json', json.dumps({a:d['new_contact_cases'] for a,d in totals['arms'].items()}, ensure_ascii=False, indent=2), '```', '',
              '非等比尝试拒绝原因（尝试次数，非独立字数）：', '', '```json',json.dumps(rejected,ensure_ascii=False,indent=2),'```', '',
              '完整逐点轨迹、来源、替换关系、变换和拒绝证据保存在相邻 run_v3 和 protection_v1 下各作者的 JSON.gz 文件；原稿评价在本目录 evaluation.json。所有个人轨迹及图文均被 Git 忽略。']
    grouped = {}
    for entry in evaluations:
        key = entry['writer'], entry['character']
        values = grouped.setdefault(key, {a: [] for a in LABELS})
        for arm, strokes in entry['metrics'].items():
            values[arm].append(float(np.mean([s['mean_distance'] for s in strokes])))
    distance_counts = {}
    for arm in ('F_combined','G_axes'):
        deltas = [float(np.mean(v[arm])-np.mean(v['A'])) for v in grouped.values() if v[arm] and v['A']]
        distance_counts[arm] = {'lower':sum(d < -1e-8 for d in deltas), 'higher':sum(d > 1e-8 for d in deltas), 'unchanged':sum(abs(d) <= 1e-8 for d in deltas)}
    notes = [
        f'本报告共 {len(rows)} 个作者—目标字；有原稿评价 {len(grouped)} 组、{len(evaluations)} 份样本，重复样本先按同字分组。距离变小/变大/不变：F {distance_counts["F_combined"]}，G {distance_counts["G_axes"]}。这不是风格评分。',
        '视觉核查：user_001 的田保留了完整来源的圆弯、开口和底钩，与该次原稿仍有差别；mjb 的涸及 scx 的谣仍有内部比例/开口适配问题。',
        '负面案例：羝的羊部来源为羸，供体末笔是竖，原稿是撇式写法。非等比保住了来源几何的连续性，却没有解决笔形语境不适配。不能断言总优于参考回退。',
        '默认笔宽 0.028 下未新增跨部件接触，不代表其他笔宽安全。细笔宽下的新增接触还揭示：只比较固定笔宽接触集合，会漏掉原先已近邻笔段继续靠近。',
        '睡恢复的是可验证子部件组合，不能当成旧完整目部的碰撞被解除。整部件复用和子部件组合的来源都在下方逐路列出。',
        '仅建议将有映射证明的上下文、嵌套和整字目标通道继续作为可关闭试用；非等比保留独立开关，尚不作为默认回退。']
    lines += ['', '## 复核结论', '', *notes]
    assert frozen == {str(p):digest(p) for p in files}, 'generation output changed during evaluation'
    (out/'evaluation.json').write_text(json.dumps({'generation_hashes':frozen,
        'truth_hashes':{str(p):digest(p) for p in truth_files}, 'report_code_sha256':digest(Path(__file__)),
        'records':evaluations},ensure_ascii=False),encoding='utf-8')
    (out/'totals.json').write_text(json.dumps(totals,ensure_ascii=False),encoding='utf-8')
    (out/'report.md').write_text('\n'.join(lines), encoding='utf-8')
    table = '<table><tr><th>路径</th><th>作者笔画</th><th>覆盖率</th><th>改变字数</th></tr>'+''.join(
        f'<tr><td>{LABELS[a]}</td><td>{d["source_strokes"]}/{totals["total_strokes"]}</td><td>{d["source_strokes"]/totals["total_strokes"]:.1%}</td><td>{d["changed_cases"]}</td></tr>' for a,d in totals['arms'].items())+'</table>'
    intro = '<p>蓝色：完整作者来源；棕色：参考回退。全部共用字框和笔宽，所有轨迹点保留。</p><p>本轮均为开发/回归，覆盖率不代表观感评分；G 为独立非等比实验。原稿只在生成冻结后评价。</p>'+table+''.join('<p>'+html.escape(n)+'</p>' for n in notes)
    (out/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>v6.1 候选扩展实测</title><style>body{font:15px system-ui;margin:24px;color:#203040}.grid{display:grid;grid-template-columns:repeat(7,minmax(140px,1fr));gap:12px}svg{width:100%;background:#fafafa}small{display:block;font-size:11px;overflow-wrap:anywhere}section{border-top:1px solid #ccc;margin-top:24px}img{display:block}</style><h1>v6.1 exp 候选扩展实测</h1>'+intro+''.join(details)+''.join(gallery), encoding='utf-8')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('root', type=Path)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--extra-root', type=Path, action='append', default=[])
    args = p.parse_args()
    report(args.root, args.output, args.extra_root)
