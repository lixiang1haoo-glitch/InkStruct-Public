"""Reuse the offline library gallery with explicit per-stroke sources and gaps."""
import json
from collections import Counter

from generate_v61_library import dump
from report_v61_library import report as base_report


def report(root, chars):
    base_report(root,chars)
    js=(root/'catalog.js').read_text()
    catalog=json.loads(js[len('const DATA='):-1])
    kinds=Counter();gaps=Counter();quality=Counter();writers={}
    for writer,rows in catalog['rows'].items():
        counts=Counter()
        for c,row in rows.items():
            full=json.loads((root/writer/f'{ord(c):04X}.json').read_text())
            if full['status']=='failed':continue
            counts.update(full['source_kinds']);counts['missing']+=full['reference_strokes']
            counts['axis_strokes']+=full['axis_strokes']
            kinds.update(full['source_kinds'])
            gaps.update(p.get('content_bucket','unknown') for p in full['missing'])
            quality['degenerate_cases']+=bool(full['checks']['degenerate'])
            geom=full['checks']['geometry']
            quality['new_external_crossing_cases']+=bool(geom['new_external_crossings'])
            for width,checks in geom['contacts'].items():
                quality['new_external_contact_cases_'+width]+=bool(checks['new_external'])
            row['missing_orders']=[p['order'] for p in full['missing']]
        writers[writer]=dict(counts)
    catalog['summary'].update(source_kinds=dict(kinds),missing_buckets=dict(gaps),geometry_review=dict(quality),source_breakdown=writers)
    dump(root/'summary.json',catalog['summary'])
    js=json.dumps(catalog,ensure_ascii=False,separators=(',',':')).replace('<','\\u003c').replace('\u2028','\\u2028').replace('\u2029','\\u2029')
    (root/'catalog.js').write_text('const DATA='+js+';')
    page=(root/'index.html').read_text()
    page=page.replace('全参考字只是结构回退，不能视作已模仿作者。','橙色虚线是作者来源缺口的诊断参考，不能视作作者轨迹或可交付的全作者字体。')
    page=page.replace('作者＋参考','作者＋缺口').replace('全参考回退','全缺口').replace('参考 ${r.reference_strokes} 笔','缺口 ${r.reference_strokes} 笔')
    page=page.replace('`${d.character} → 第 ${d.orders.join(\'、\')} 笔`',
        '`${d.label||"完整部件"}：${d.character} ${d.source_stroke_id||""} → 第 ${d.orders.join(\'、\')} 笔`')
    page=page.replace("${esc(donors||'无可用作者部件；参考回退')}",
        "${r.missing_orders?.length?'<b>剩余缺口：第 '+esc(r.missing_orders.join('、'))+' 笔</b><br>':'作者来源完整（仍需人工验收）<br>'}<details><summary>逐笔来源</summary>${esc(donors||'无可靠作者来源')}</details>")
    start=page.index('<footer>');end=page.index('</footer>',start)+len('</footer>')
    page=page[:start]+('<footer>禁止拆分规则 author_reuse_no_split_v1 与作者单笔回退已启用。'
        '排除同字原稿；完整部件优先，已有关键笔替换优先于单笔。无可靠来源时保留橙色虚线诊断位置并明确报缺口。'
        '完整轨迹下载包含诊断参考，不代表全作者输出可直接验收。内部自然交叉不自动判错；'
        '相对旧全库新增的跨部件接触只作人工审查提示。等比优先，继承的受限非等比部件在记录中单独标明。'
        '当前覆盖率不是风格合格率。生产默认未变。</footer>')+page[end:]
    (root/'index.html').write_text(page)
    summary=catalog['summary'];lines=['# 修正后的 v6.1 exp 四作者全库浏览','',
        '[打开图册](index.html)','',f'本次 {len(chars)} 字 × 4 位作者。禁止拆分规则、位置变体检查、作者单笔回退均开启。',
        '沿用已人工审查的来源与变换并从档案重新重建轨迹，其他字执行当前完整部件扩展。所有同字来源排除；不是原稿重放。','',
        '| 作者 | 全作者字 | 有缺口字 | 失败 | 作者笔画 | 缺口笔画 |','|---|---:|---:|---:|---:|---:|']
    for w,tot in summary['writers'].items():
        lines.append(f'| {w} | {tot.get("all_source",0)} | {tot.get("mixed",0)+tot.get("all_reference",0)} | {tot.get("failed",0)} | {tot.get("source_strokes",0)} | {tot.get("reference_strokes",0)} |')
    lines+=['','## 来源层级与范围','',
        '- '+ '；'.join(f'{k}: {v}' for k,v in kinds.items()),
        '- 关键笔替换沿用现有已核查位置变体计划，没有在本轮推广为通用替换器。',
        '- 等比优先；完整部件保留现有最高 1.35 轴比的独立回退。每笔变换均可查，不将非等比混称为等比。',
        '- 未重新建档，未新增同字验证原稿，未更改参数或生产默认。','',
        '## 明确缺口','',
        '橙色虚线仅用于显示尚无可靠作者来源的位置；完整诊断 JSON 中保留这些参考点并显式标记 `explicit_gap`。不得称这些笔画已模仿作者。',
        '每张卡片显示缺口笔序，展开逐笔来源可看供体字及标准笔画 ID；检查记录中包含样本 ID、变换和逐条拒绝原因。',
        '复杂方向签名是现有检索桶，不等于完整的语义笔画分类。来源覆盖仍受映射、端点/形态和新关系检查限制。','',
        '## 验收边界','',
        f'旧人工审查字完整源几何重建一致：{summary["regression_exact"]}/{summary["regression_checked"]}。',
        '“群”的穿头含义按用户澄清：两横穿过长撇；不再以长撇是否伸过顶横判错。',
        '逐字检查标准 ID、笔顺、有限坐标、压力、时间和作者源点/压力/笔内时间保真。',
        '相对旧全库的跨部件几何变化只作复核提示，不把作者原有内部交叉判成缺陷：',
        '```json',json.dumps(dict(quality),ensure_ascii=False,indent=2),'```',
        '检查通过或全作者覆盖不能证明字形、连接关系和风格正确。这是人工浏览批次，不是新留出集。','',
        '## 可追溯文件','',
        '`protocol.json` 记录输入、代码、旧计划/对照哈希及开关；`summary.json` 汇总；每字 `.json` 含逐笔来源和缺口；`.json.gz` 保留全部点和候选/规则拒绝日志；`.svg` 不压缩输出轨迹。旧结果均保留。']
    (root/'report.md').write_text('\n'.join(lines)+'\n')
