"""Evidence-bounded private report for the four-writer fallback census."""
from __future__ import annotations

import argparse
import csv
import gzip
import json
from collections import Counter
from pathlib import Path

from generate_v61_library import SOURCES, WRITERS, digest, dump
from report_v61_exp import render
from run_v61_exp import dict_curves

from inkstruct.profile import load_profile
from inkstruct.trajectory_experiment import SharedTransform

LABELS = {
    'no_declared_identity_count_source': '当前登记视图中无同名完整部件',
    'identity_variant_or_stroke_count_mismatch': '有同名部件，但变体或笔数不符',
    'context_or_index_scope_restriction': '已有可靠完整部件，被角色/父结构范围挡住',
    'actual_placement_rejected': '进入候选后，实际放置检查拒绝',
    'only_same_character_source_excluded': '只有目标同字来源，被跨字实验排除',
    'target_structure_mapping_unresolved': '目标结构归属不完整或置信度不足',
    'root_bridge_mapping_or_reference_gate': '完整单字桥接的对应/参考门槛未过',
    'target_not_scheduled_with_source': '有可靠来源，但该目标组未进入调度',
    'reference_shape_or_fit_gate': '同上下文来源被参考形状/拟合门槛挡住',
    'source_mapping_unreliable': '现有同身份来源未达到映射阈值',
    'target_not_scheduled_no_reliable_declared_source': '未调度，且未发现可靠登记来源',
}


def load(path):
    return json.loads(gzip.decompress(path.read_bytes()) if str(path).endswith('.gz') else path.read_bytes())


def report(root):
    out = root / 'report_v2'
    out.mkdir(exist_ok=False)
    audit, probes, nested = root / 'run_v2', root / 'probes_v2', root / 'nested_v1'
    totals = Counter()
    summaries = load(audit / 'summary.json')
    for s in summaries:
        totals.update(s['stroke_partition'])
    total = totals['all_strokes']
    fallback = total - totals['source_strokes']
    assert fallback == 295898 and total == 450468
    rows = [r for w in WRITERS for r in load(audit / f'{w}.json')]
    with (out / 'fallback_slots.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        columns = ['writer', 'character', 'canonical', 'context', 'strokes', 'reason', 'reliable_identity_samples',
                   'same_context_indexed', 'eligible_before_top16', 'donor_characters', 'rejection_reasons']
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for r in rows:
            writer.writerow({**{k: r[k] for k in columns if k in r},
                'reason': LABELS[r['reason']], 'donor_characters': ''.join(sorted({s['character'] for s in r['reliable_sources']})),
                'rejection_reasons': json.dumps(r['actual_rejection_reasons'], ensure_ascii=False)})
    evidence = load(probes / 'summary.json')
    successful = [r for r in evidence if r['accepted']]
    cases, gallery = [], []
    selected = [('user_001', '想', '心'), ('user_001', '加', '力'), ('user_001', '田', '田'),
                ('scx', '媷', '女'), ('mjb', '把', '巴'), ('wsq', '闻', '耳')]
    for w, c, part in selected:
        row = next(r for r in evidence if r['writer'] == w and r['character'] == c and r['canonical'] == part)
        file = probes / f'{w}-{ord(c):04X}-{row["component_id"]}.json.gz'
        data = load(file)
        donor = data['accepted']['proposal']['candidate']['character']
        name = f'{w}-{ord(c):04X}.png'
        render([{'title': f'{w}\n{c} ← {donor} 的 {part}',
                 'curves': [dict_curves(data['current_glyph']), data['source_curves'], dict_curves(data['trial_glyph'])]}],
               ['当前全库结果', '完整来源部件（原坐标）', '诊断试摆：通过原有检查'], out / name)
        case = {'writer': w, 'character': c, 'part': part, 'source': donor, 'mode': row['mode'],
                'before_source_strokes': row['current_source_strokes'],
                'after_source_strokes': row['accepted']['integrity']['source_strokes'],
                'stroke_count': len(data['trial_glyph']['strokes']), 'proof': row['accepted']['proof'],
                'image': name, 'record': str(file.relative_to(root))}
        cases.append(case)
        gallery.append(f'<h3>{w} · {c} ← {donor} 的 {part}</h3><img src="{name}"><p>作者笔画 {case["before_source_strokes"]} → {case["after_source_strokes"]} / {case["stroke_count"]}。通过现有几何与协议检查，不等于人工认定更像作者。<a href="../{case["record"]}">完整证据</a></p>')
    ndata = load(root / 'nested_probes_v1/user_001-60F3.json.gz')
    render([{'title': 'user_001\n想：只展开相部', 'curves': [dict_curves(ndata['current_glyph']), dict_curves(ndata['trial_glyph'])]}],
           ['当前：0 / 13 笔作者来源', '单独展开相部：9 / 13 笔作者来源'], out / 'nested-xiang.png')
    gallery.append('<h3>“想”的另一层遗漏：相部没有展开</h3><img src="nested-xiang.png"><p>只调用现有有序结构验证展开“相”，木和目可分别找到完整作者来源，独立试验达到 9/13。与上面心部 4/13 是分开的诊断实验，未把两者直接相加声称 13/13。</p>')
    # Reconstruct a recorded rejected placement for a negative illustration only.
    lib = Path('artifacts/v61_full_library_20261014/run_v1')
    data = load(lib / 'user_001/7761.json.gz')
    trial = next(t for t in data['expansion']['whole_root']['placement'] if not t['accepted'])
    profile = load_profile(SOURCES['user_001'])
    source = profile.source_trajectories[trial['candidate']['sample_id']]
    mapping = {s.standard_stroke_id: s for s in source.strokes}
    original = dict_curves(data['glyph'])
    after = [list(s) for s in original]
    positions = {s['standard_stroke_id']: i for i, s in enumerate(data['glyph']['strokes'])}
    transform = SharedTransform(**trial['transform'])
    for sid, tid in zip(trial['candidate']['stroke_ids'], trial['source_mapping_evidence']['target_ids'], strict=True):
        after[positions[tid]] = transform.apply(mapping[sid].points)
    render([{'title': 'user_001\n睡：拒绝示例', 'curves': [original, after]}],
           ['当前结果：参考回退', '被拒绝试摆（未交付）：完整目'], out / 'rejected-shui.png')
    gallery.append('<h3>有来源仍不能直接复用：“睡”的目部</h3><img src="rejected-shui.png"><p>完整“目”的源映射通过，但按当前整部件拟合后产生新的跨部件交叉/笔宽接触。不能将其与作者原有内部交叉混为一谈。右侧“垂”则未在当前档案登记视图中找到完整来源。</p>')
    dump(out / 'negative-shui.json', trial)
    nested_stats = load(nested / 'summary.json')
    lines = ['# 为什么四作者全库只有 34.3% 笔画来自作者轨迹', '',
        '已完成全部 38,296 个生成结果的回退审查：450,468 笔中，作者来源 154,570 笔（34.313%），参考回退 295,898 笔。档案分别有 338、767、431、779 份完整来源样本。生产与旧结果未修改。', '',
        '**结论：既有真实来源缺口，也有检索/调度遗漏；不能把全部回退都当作需要补采，更不能把所有拒绝都叫误拒。**', '',
        '## 一、按回退笔画统计首个主要障碍', '',
        '这是互斥、按最终回退笔画加权的分类，不是候选拒绝次数。一个槽位可能同时存在多个限制，表中只记录当前路径最先暴露的障碍。', '',
        '| 原因 | 回退笔画数 | 占回退笔画 |', '|---|---:|---:|']
    for key in sorted(LABELS, key=lambda k: -totals[k]):
        lines.append(f'| {LABELS[key]} | {totals[key]:,} | {totals[key]/fallback:.2%} |')
    lines += ['', '“无同名完整部件”只限当前档案的原有和已验证嵌套登记视图（包含根、父节点和叶节点），不是凭字图证明采集数据里没有任何潜在小部件。', '',
        f'进一步调用已有嵌套结构验证发现，其中 **{sum(s["within_no_declared_source_strokes"] for s in nested_stats):,} 笔**可在拆出的子部件层找到符合原有身份、位置、映射及参考形状条件的候选；含“仅同字来源”类共 **{sum(s["candidate_covered_strokes_not_admitted"] for s in nested_stats):,} 笔**。这是预计候选覆盖，还未逐一做真实放置验收，不能加进 34.3%。', '',
        f'另外有 {sum(s["whole_target_source_components_with_reliable_target"] for s in summaries):,} 个仍有回退的作者—目标字，其完整根节点能在其他字中找到满足映射阈值的完整部件（目标结构也达阈值）。这是未启用“部件到整字”通道的候选机会，尚未全量试摆；与上表重叠，不能相加。', '', '## 二、已有完整作者部件却未复用的具体字', '',
        '| 作者 | 目标 | 已有完整来源 | 未采用的具体原因 | 诊断后作者笔画数 |', '|---|---|---|---|---|']
    notes = {'context_bridge': '角色或父结构标签不同，被精确上下文检索排除',
             'whole_root_target': '缺少“已有部件 → 整个目标字”的候选通道',
             'top16_tail': '仅检查前16个候选；可通过的“奶”排在第18位'}
    for c in cases:
        lines.append(f'| {c["writer"]} | {c["character"]} | {c["source"]} 的 {c["part"]} | {notes[c["mode"]]} | {c["before_source_strokes"]} → {c["after_source_strokes"]} / {c["stroke_count"]} |')
    lines += ['', '- user_001“想”：心部来自“总”，二者均在底部，但父结构分别为上下 `⿱` 和上中下 `⿳`，精确键把来源排除。只改变候选范围、通过原有有序对应验证后，4笔完整心部能通过准入。',
        '- user_001“想”：相部的完整9笔实例未登记，但子部件木、目都有可靠来源。当前嵌套白名单只有“需、汤”。单独用已有展开器验证“相”，不改坐标和笔顺，可使9笔改用作者来源；与心部实验保持分离。',
        '- user_001“田”：已有“苗”中的完整田，旧路径却先按冂、土拆开找，未提出整田的候选。保持可靠身份/映射和整部件等比变换后，5笔整体可通过检查。',
        '- scx“媷”：同角色、同父结构、同身份的女部候选共有19个。“奶”的女部原排名18，不是映射或碰撞不合格，只是未进入前16个；纳入后原有全部准入条件通过。', '',
        f'本轮有意选择常用问题字及全部3个“超过16个候选仍回退”槽位，共诊断 {len(evidence)} 个作者—目标—部件任务，{len(successful)} 个找到可通过现有检查的候选（51个上下文桥接、6个完整部件到整字、1个候选尾部）。这不是随机抽样，不可外推全库改善率；同字多个任务也不能直接相加。', '',
        '全部尾部候选检查中，scx“娠”另外2个、wsq“鴈”另外41个均未找到通过者，因此“提高候选上限”不是覆盖率的主要解法。', '',
        '## 三、不能称为误拒的案例', '',
        '- user_001“睡”的目：已有完整“目”，映射可靠；当前等比放置后新增跨部件碰撞，被拒绝有直接几何证据。需要改进布局或换来源，不能只取消碰撞检查。',
        '- user_001“印”的卩：档案里有“服”的第5–6笔，但平均映射置信度为0.5411，低于0.55；不能在本轮绕过映射约束。低分表示证据不足，不等于已确认轨迹错误。',
        '- scx“凝”的疑：已有“疑”整字，逐笔均值约0.698，但源组件结构置信度不足。属于结构/组件映射证据问题，不能说档案没采过“疑”。',
        '- user_001“而、白、雨”：分别能找到“需”的而、“怕/泉”的白和若干雨部，但目标根结构置信度为0.7。现有记录将缺少可解释拆分也归入结构低置信，不能据此断言笔序一定错误；本次保留复核，没有放宽到0.7。',
        '- 同一作者只写过目标字自身时，当前跨字评估主动排除同字来源。10,236笔属于这一类；若另做“已有字直接复用”产品模式可重新评估，不能悄悄混进本轮跨字覆盖率。', '',
        '## 四、建议顺序', '',
        '1. 先处理明确接口遗漏：有限上下文桥接、完整部件到整字、经过验证的目标嵌套展开。保留ID、笔顺、映射、正等比及真实笔段碰撞检查。',
        '2. 候选上限改为“先找过审候选”的有限预算策略值得小试，但全库只有3个回退槽位受到超过16候选的直接影响，本轮仅1个恢复，不应优先于层级/上下文问题。',
        '3. 对真正出现跨部件碰撞的候选单独研究布局，不继续把已有源内部交叉误判为损伤。',
        '4. 修复有证据的结构映射问题，再对仍缺少可靠完整来源的部件规划补采。不能用降低映射门槛换覆盖率。', '',
        '## 五、证据边界与文件', '',
        '所有试摆为独立诊断输出，未覆盖全库字图、档案或生产入口。没有读目标原稿，没有使用8点压缩、轨迹平均或样条。试摆保留来源完整点、压力和笔内时间；通过安全检查只说明存在可用候选通道，不代表自然程度已获人工认可。', '',
        '[打开全部图文对照](index.html) · [全部回退槽位清单](fallback_slots.csv)', '',
        '原统计 run_v2；上下文/整字/候选尾部试摆 probes_v2；目标嵌套候选审查 nested_v1；独立“想”展开试摆 nested_probes_v1。早期run_v1为变体/笔数未拆分的审计草稿，结论以run_v2为准。']
    for c in cases:
        lines += ['', f'### {c["writer"]} · {c["character"]}', '', f'![同尺度对照]({c["image"]})']
    lines += ['', '### 嵌套展开与负例', '', '![想：只展开相部](nested-xiang.png)', '', '![睡：有来源但当前放置不安全](rejected-shui.png)']
    (out / 'report.md').write_text('\n'.join(lines) + '\n')
    table = '<table><tr><th>主要障碍</th><th>回退笔画</th><th>占回退</th></tr>' + ''.join(
        f'<tr><td>{LABELS[k]}</td><td>{totals[k]:,}</td><td>{totals[k]/fallback:.2%}</td></tr>' for k in sorted(LABELS, key=lambda k: -totals[k])) + '</table>'
    (out / 'index.html').write_text('<!doctype html><meta charset="utf-8"><title>v6.1 参考回退原因审查</title><style>body{font:16px system-ui;max-width:1250px;margin:30px auto;padding:20px;line-height:1.7;color:#243348}img{max-width:100%}td,th{padding:7px 16px;border-bottom:1px solid #ddd;text-align:left}h3{margin-top:45px}a{color:#176799}</style><h1>34.3% 背后：来源缺口与漏用分开看</h1><p>全部38,296份结果，295,898笔参考回退。以下试摆未写回生成器，保留当前结果对照。</p><p><a href="report.md">完整分析与边界</a> · <a href="fallback_slots.csv">逐字回退原因</a></p>'+table+'<h2>真实来源诊断试摆</h2><p>同尺度、同笔宽0.028。源部件在原坐标显示，未将它平均或重画。成功只表示通过映射、协议和几何检查；作者风格仍待人工审查。</p>'+''.join(gallery))
    dump(out / 'summary.json', {'stroke_partition': dict(totals), 'probe_tasks': len(evidence),
        'probe_passes': len(successful), 'cases': cases, 'nested_candidate_coverage': nested_stats,
        'report_code_sha256': digest(Path(__file__)), 'production_changed': False})
    print(out / 'index.html')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('root', type=Path)
    report(p.parse_args().root)
