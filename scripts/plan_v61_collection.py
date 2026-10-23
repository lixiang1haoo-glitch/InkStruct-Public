"""Audit real sources and produce a bounded, leakage-safe user_001 collection plan."""
from __future__ import annotations

import argparse
import csv
import html
import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from run_v6_exp import archive, sha, write

from inkstruct.profile import load_profile
from inkstruct.recommend import DEFAULT_COMMON_CHARACTERS, _load_common_characters
from inkstruct.structure_corrections import CorrectedStructureRepository
from inkstruct.structures import StructureRepository
from inkstruct.v61_collection import (
    audit_targets,
    coverage_summary,
    freeze_validation,
    projected_candidates,
    select_budget,
)
from inkstruct.v61_exp import V61ExpGenerator

INDEX = Path('artifacts/component_aspect_20261007/user001_snapshot/index.jsonl')
PRIOR = Path('artifacts/architecture_review_20261011/run_v1/user_001/source_archive.json')


def export_csv(path, rows):
    with path.open('x',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=['character','repeats','purpose','components','reason'])
        w.writeheader();w.writerows(rows)


def reason(slot):
    if slot['status']=='only_one_safe_donor_character':
        return f"已有可替换供体字仅{'、'.join(slot['safe_donor_characters'])}；补第二种真实实例，不计新增覆盖"
    detail=(f"同名其他上下文供体{len(slot['other_context_donor_characters'])}字、完整单字采样{slot['whole_character_captures']}份")
    return f"当前同身份/变体/角色/父布局/笔数的索引实例为空；{detail}，不能直接当作该位置可靠供体"


def run(root, split_path, index_path):
    root.mkdir(parents=True,exist_ok=False)
    split=json.loads(split_path.read_text())
    write(root/'split.json',split)
    development=split['development_regression']; validation=split['prospective_validation']
    assert not set(development)&set(validation)
    forbidden=set(development)|set(validation)
    raw=[json.loads(line) for line in index_path.read_text().splitlines()]
    sampled={x['character'] for x in raw}
    base=StructureRepository(Path('artifacts/full_library_20261010/inputs/characters.sqlite3'))
    common=_load_common_characters()
    if sha(index_path)==split['raw_index_sha256']:
        assert freeze_validation(base,sampled,development,common)==validation
    inputs=[index_path,split_path,PRIOR,base.path,DEFAULT_COMMON_CHARACTERS,
            Path('third_party/makemeahanzi/graphics.txt'),Path('third_party/makemeahanzi/dictionary.txt'),
            Path('configs/structure_overrides/unclipped_reference_v1.json')]
    code=[Path(__file__),Path('scripts/run_v6_exp.py'),*Path('src/inkstruct').glob('*.py')]
    frozen={'inputs':{str(p):sha(p) for p in inputs},'code':{str(p):sha(p) for p in code}}
    write(root/'protocol.json',{'name':'v6.1 exp user_001 actual-admission collection planning',
        'baseline_commit':'51a27bc',**frozen,'budget':split['budget'],'repeats':2,
        'heldout_usage':'prospective validation is excluded from candidates, training, and ranking targets; '
                        'coverage probed only after acquisition list frozen; no validation original exists yet',
        'coverage_semantics':'current accepted output / alternatives passing frozen-context guards / '
                             'future public-compatible projections are three different quantities',
        'projection_assumptions':'new whole-character capture passes complete one-to-one mapping, confidence, '
             'source geometry, top16 retrieval and real placement; no author trajectory simulated',
        'candidate_policy':'uncollected GB2312 level-1 or curated-common characters, 3..16 strokes, no component warnings; '
             'current exact context and reference compatibility gates, existing reliable nested views',
        'production_default_changed':False})
    sources,excluded=archive(index_path,base,forbidden)
    prior=load_profile(PRIOR)
    if sha(index_path)==split['raw_index_sha256']:
        assert json.loads(json.dumps({k:asdict(v) for k,v in sources.source_trajectories.items()}))==json.loads(json.dumps({
            k:asdict(v) for k,v in prior.source_trajectories.items()}))
    write(root/'audit_source_archive.json',asdict(sources))
    write(root/'source_exclusions.json',excluded)
    write(root/'inventory.json',{'raw_samples':len(raw),'raw_character_count':len(sampled),
        'retained_samples':sources.sample_count,'retained_characters':sources.character_count,
        'excluded_reasons':dict(Counter(x['reason'] for x in excluded)),
        'raw_characters':sorted(sampled),'source_frozen_equal_prior':sha(index_path)==split['raw_index_sha256'],
        'no_validation_originals_used':True})
    target=CorrectedStructureRepository(base,inputs[5],inputs[6],inputs[7])
    engine=V61ExpGenerator(sources,base,target)
    slots,glyphs=audit_targets(engine,development)
    write(root/'development_audit.json',{'slots':slots,'glyphs':glyphs,'summary':coverage_summary(slots,glyphs)})
    candidates=projected_candidates(engine,slots,sampled,forbidden,set(common))
    plan=select_budget(candidates,slots,split['budget'])
    chosen={r['character'] for r in plan['recommendations']}
    assert not chosen&(sampled|forbidden)
    write(root/'candidate_projections.json',candidates)
    write(root/'plan.json',plan)  # List frozen BEFORE prospective validation is examined.
    validation_slots,validation_glyphs=audit_targets(engine,validation)
    validation_candidates=projected_candidates(engine,validation_slots,sampled,forbidden,set(common),only_gaps=False)
    validation_links={c:validation_candidates[c]['opportunities'] for c in chosen if c in validation_candidates}
    write(root/'validation_audit.json',{'slots':validation_slots,'glyphs':validation_glyphs,
        'summary':coverage_summary(validation_slots,validation_glyphs),'selected_collection_links':validation_links,
        'used_to_rank_collection':False,'target_originals_read':False})
    # Existing v6 reference baseline is unchanged by shared-helper extraction.
    original_root=Path('artifacts/v6_integrated_20261013/run_v2/user_001/glyphs')
    if sha(index_path)==split['raw_index_sha256']:
        for c,g in glyphs.items():
            old=json.loads((original_root/f'{ord(c):04X}.json').read_text())['F']
            assert json.loads(json.dumps(g['baseline']['strokes']))==old['strokes']
    trainrows=[]
    for item in plan['recommendations']:
        ss=[slots[k] for k in item['marginal_slots']]
        desc='；'.join(f"{s['character']}的{s['canonical']}（{s['context_key']}）：{reason(s)}" for s in ss)
        trainrows.append({'character':item['character'],'repeats':2,'purpose':'v61_training_acquisition',
            'components':' '.join(sorted({s['canonical'] for s in ss})), 'reason':desc})
    export_csv(root/'补采任务.csv',trainrows)
    export_csv(root/'验证任务_禁止建档.csv',[{'character':c,'repeats':2,'purpose':'v61_validation_do_not_train',
        'components':'','reason':'冻结的跨字验证；全部重复采样仅评价，不进入作者库，不参与调参'} for c in validation])
    notes=[]
    for item,csvrow in zip(plan['recommendations'],trainrows,strict=True):
        serves=sorted({slots[k]['character'] for k in item['opportunities']})
        supports=sorted({validation_slots[k]['character'] for k in validation_links.get(item['character'],{})})
        notes.append({**csvrow,'sequence':item['sequence'],'stroke_count':item['stroke_count'],
            'in_common_list':item['common_list'],'development_targets':serves,'validation_targets_posthoc':supports,
            'expected_slots':item['marginal_slots'],'actual_usable_after_capture':None})
    write(root/'recommendations_explained.json',notes)
    make_report(root,split,slots,glyphs,plan,notes,validation_slots,validation_glyphs,validation_links)
    assert all(sha(Path(p))==h for group in frozen.values() for p,h in group.items())
    write(root/'verification.json',{'input_code_unchanged':True,'split_disjoint':True,
        'no_existing_or_evaluation_characters_recommended':True,'validation_not_used_for_ranking':True,
        'original_user001_23_stroke_payloads_unchanged':sha(index_path)==split['raw_index_sha256'],
        'actual_new_usable_sources':0,'note':'Collection not yet performed; no claimed actual coverage gain.'})
    print(json.dumps({'characters':[x['character'] for x in notes],
        'development':coverage_summary(slots,glyphs),'validation':coverage_summary(validation_slots,validation_glyphs),
        'projected_new_strokes':sum(slots[k]['stroke_count'] for k in plan['projected_first_source_slots']),
        'prospective_validation':validation},ensure_ascii=False,indent=2))


def make_report(root,split,slots,glyphs,plan,notes,vs,vg,vl):
    d=coverage_summary(slots,glyphs); v=coverage_summary(vs,vg)
    first=plan['projected_first_source_slots']; extra=sum(slots[k]['stroke_count'] for k in first)
    new_v={k for links in vl.values() for k in links if not vs[k]['safe_donor_characters']}
    touched_v={vs[k]['character'] for links in vl.values() for k in links}
    lines=['# user_001 · v6.1 exp 首批补采清单','',
        '**先采训练清单，单独保存验证清单。不要把验证字及其任何重复采样加入作者档案。**','',
        f"训练补采：{'、'.join(n['character'] for n in notes)}。每字2次，共{len(notes)*2}份。",
        f"前瞻验证：{'、'.join(split['prospective_validation'])}。每字2次，共{len(split['prospective_validation'])*2}份；尚未采集，不称新盲测成绩。",'',
        '## 当前实际覆盖与未来预计覆盖','',
        f"23字回归目标：{d['actual_source_strokes']}/{d['total_strokes']}笔实际采用作者轨迹；{d['actual_reference_strokes']}笔回退。",
        f"若全部新增实例成功映射并通过真实生成准入，公开结构筛选预计可为{len(first)}个原无安全供体槽、{extra}笔提供来源机会；这是条件性机会，不是实际新增{extra}笔。",
        f"另外{len(plan['projected_second_source_slots'])}个槽预计达到至少两个不同供体字；重复写同一字不算不同供体字。",
        f"8字前瞻验证当前实际采用{v['actual_source_strokes']}/{v['total_strokes']}笔；清单冻结后检查到{len(new_v)}个无来源槽可望获得新候选，另有{len(touched_v)}个字存在新增供体适配机会；其余为保护对照，未据此重选。本验证组主要检验新供体适配与不退步，不能证明52笔机会在新字上的覆盖外推。",
        '**本轮实际新增可用样本为0：尚未发生补采。没有模拟作者轨迹，也没有生成虚假的采后结果。**','',
        '## 逐字补什么、服务谁、为何不直接复用','',
        '| 顺序 | 补采字 | 内容/次数 | 服务回归字 | 冻结后核对的验证字 | 理由 |',
        '| --- | --- | --- | --- | --- | --- |']
    for n in notes:
        lines.append(f"| {n['sequence']} | {n['character']} | {n['stroke_count']}笔，2次 | {'、'.join(n['development_targets'])} | {'、'.join(n['validation_targets_posthoc']) or '—'} | {n['reason'].replace('|','／')} |")
    lines+=['','## 暂不通过盲目补采处理的缺口','',
            '| 目标部件 | 当前状态 | 已有证据/处置 |','| --- | --- | --- |']
    for s in slots.values():
        if s['status'] in ('existing_pool_rejected_by_placement_review_first','reference_shape_filter_review_first'):
            lines.append(f"| {s['character']}／{s['canonical']} | {s['status']} | 有{ s['eligible_pool_size']}个拟合提案；先复核映射和真实碰撞，不把新增同名样本当解决方案 |")
        elif s['status']=='missing_eligible_context' and s['slot_id'] not in first:
            lines.append(f"| {s['character']}／{s['canonical']} | 本批未覆盖 | 精确角色/变体/笔数及形态门槛不放宽；同名来源{len(s['other_context_donor_characters'])}字，需另查准入或下一批 |")
    lines+=['','## 采集与验收约定','',
        '- 按本人自然写法书写，不临摹屏幕参考笔形，不为了过关刻意拉直或闭合；设备、画布与握笔习惯保持一致。',
        '- 完整字采集，保留原始所有点、压力、时间和原始笔序。遇合笔、漏笔、拆笔或错序，保留并标记；无法可靠一对一映射时不强行入库。',
        '- 同一字写两次，分两轮完成；用于检查稳定性，不平均轨迹，不当作两个独立供体字。',
        '- 补采成功不等于准入成功。依次检查原始有效性→完整无歧义映射→部件身份/角色/笔数→来源索引→目标实际生成；逐阶段报告数量及拒绝原因。',
        '- 先在23个已知回归字检查新实例的实际采用和不变量，再冻结参数；随后才对8个验证字原稿评价。验证原稿不参与排序、建档和调参。',
        '- 评价包含原有圆弯、折钩、末向、整体间距、真实笔段接触和实际显示笔宽；不能用参考拟合距离或覆盖率代替风格。',
        '- 所有采后建档必须使用本目录split.json中两组目标字符的并集作整组排除；旧档案和旧输出不覆盖。',
        '- `补采任务.csv` 与 `验证任务_禁止建档.csv` 分开导入采集器。CSV用途标签只是提示，真正隔离由建档排除清单执行。','',
        '## 范围与复用','',
        '复用recommend.py的贪心边际覆盖选择、现有可靠嵌套视图、完整档案提取、v6.1候选与生成验收。预计层只检查公开结构，不构造假作者轨迹；无全局最优或90%风格质量保证。生产默认不变。',
        '本清单仅针对冻结的user_001本地快照与有限目标集；不是其他作者的通用字表。候选限GB2312一级汉字或项目常用清单、3–16笔，常用字优先；字表外或较复杂的缺口本批可能无法覆盖。']
    (root/'补采说明.md').write_text('\n'.join(lines)+'\n')
    rows=''.join('<tr>'+''.join(f'<td>{html.escape(str(value))}</td>' for value in
        [n['sequence'],n['character'],n['stroke_count'],'、'.join(n['development_targets']),
         '、'.join(n['validation_targets_posthoc']) or '—',n['reason']])+'</tr>' for n in notes)
    text='''<!doctype html><meta charset="utf-8"><title>user_001 v6.1 补采清单</title><style>body{font:16px system-ui;max-width:1200px;margin:32px auto;padding:20px;color:#203245}td,th{padding:10px;border:1px solid #ccd5df}table{border-collapse:collapse}p{line-height:1.7}.note{padding:16px;background:#fff1cf}</style><h1>user_001 · v6.1 exp 首批补采</h1>'''
    text+=f'<p class="note">训练：<b>{"　".join(n["character"] for n in notes)}</b>，每字2次。<br>验证：<b>{"　".join(split["prospective_validation"])}</b>，每字2次；不得建档或调参。</p>'
    text+=f'<p>当前23字实际采用作者轨迹 {d["actual_source_strokes"]}/{d["total_strokes"]} 笔。补采后预计为 {extra} 笔提供新来源机会，但仍需映射和生成验收；实际新增可用来源目前为0。8个验证字的原稿尚未采集，未参与选字评分。</p>'
    text+='<p><a href="补采任务.csv">下载训练补采CSV</a> · <a href="验证任务_禁止建档.csv">下载独立验证CSV</a> · <a href="补采说明.md">完整说明、未解决项与验收约定</a></p>'
    text+='<table><tr><th>顺序</th><th>补采字</th><th>笔数</th><th>服务回归字</th><th>验证字（事后核对）</th><th>为何需要</th></tr>'+rows+'</table>'
    text+='<p>写自然手写，不临摹字体、不强制闭合；保留完整几何、压力、时间。两次采样分两轮完成，不平均。当前没有可靠供体的部分不能用参考加噪声冒充作者风格。详见补采说明及可追溯JSON。</p>'
    (root/'报告.html').write_text(text)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--split',type=Path,required=True)
    p.add_argument('--index',type=Path,default=INDEX)
    a=p.parse_args();run(a.output,a.split,a.index)
