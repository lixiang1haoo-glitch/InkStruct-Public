"""Build a local, paginated four-writer review gallery from completed records."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

WRITERS = ('user_001', 'scx', 'mjb', 'wsq')
PAGE = r'''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>v6.1 exp · 四作者全库审查</title>
<style>
body{margin:0;background:#f4f5f7;color:#202934;font:15px system-ui}header{padding:20px 28px;background:#fff;border-bottom:1px solid #ddd}h1{font-size:23px;margin:0 0 10px}p{line-height:1.6;margin:6px 0}.muted{color:#606c7b}a{color:#245b9e}button,select,input{font:inherit;padding:7px;border:1px solid #bcc4d0;border-radius:5px;background:white}button{cursor:pointer}.tools{position:sticky;top:0;background:#f8f9fc;z-index:2;padding:12px 28px;display:flex;flex-wrap:wrap;gap:8px;border-bottom:1px solid #ddd}input{width:240px}.grid{display:grid;grid-template-columns:repeat(4,minmax(180px,1fr));gap:12px;padding:20px 28px;max-width:1500px;margin:auto}.card{background:white;border-radius:8px;padding:12px;min-width:0;border:1px solid #e1e5ea}.card img{width:100%;aspect-ratio:1;display:block}.title{display:flex;justify-content:space-between;align-items:center;font-size:18px}.detail{font-size:12px;line-height:1.6;overflow-wrap:anywhere}.tag{font-size:12px;border-radius:4px;padding:2px 5px;background:#edf2f8}.warning{background:#fff1d9}.failed{background:#ffdddd}.flagged{border:2px solid #bc4838}.placeholder{aspect-ratio:1;display:grid;place-items:center;background:#faf1f0;padding:10px}.nav{text-align:center;padding:18px}.card button{font-size:12px;margin-top:5px}details{margin-top:5px}.empty{padding:50px}footer{padding:25px;max-width:1200px;margin:auto}@media(max-width:850px){.grid{grid-template-columns:repeat(2,minmax(130px,1fr));padding:10px}.tools{padding:10px}.detail{font-size:11px}}
</style>
<header><h1>v6.1 exp · 四作者全库审查</h1>
<p id="summary"></p><p class="muted">相同字框、相同笔宽 0.028；保留所有轨迹点。全参考字只是结构回退，不能视作已模仿作者。作者原有内部交叉不是自动缺陷。放大后线帽呈圆形属于显示笔宽，未对轨迹重新平滑。</p>
<p><a href="report.md">运行说明与统计</a> · <a href="summary.json">验收统计</a> · <a href="protocol.json">版本与输入哈希</a>。点“标记问题”可写备注，最后导出清单交回。离线浏览器可能限制本地保存，请及时导出。</p></header>
<div class="tools"><input id="query" placeholder="输入汉字，如：铜伯震叵；或 U+94DC">
<select id="author"><option value="all">四作者并排</option></select>
<select id="filter"><option value="all">全部结果</option><option value="source">有作者轨迹</option><option value="full">全作者轨迹</option><option value="partial">作者＋参考</option><option value="reference">全参考回退</option><option value="warning">自动检查提示</option><option value="failed">生成失败</option><option value="flagged">我标记的问题</option></select>
<button id="prev">上一页</button><span id="position"></span><button id="next">下一页</button><button id="export">导出问题清单</button></div>
<form id="noteForm" hidden style="margin:16px 28px;padding:16px;background:#fff;border:1px solid #b9c6d8;border-radius:8px"><b id="noteTitle"></b><p><textarea id="noteText" aria-label="问题描述" placeholder="描述你看到的问题" rows="3" style="width:95%;font:inherit;padding:8px"></textarea></p><button type="submit">保存备注</button> <button id="noteCancel" type="button">取消</button> <button id="noteDelete" type="button">删除此标记</button></form><section id="exportPanel" hidden style="margin:16px 28px"><p>已尝试下载问题清单；也可复制下方内容交回。</p><textarea id="exportText" aria-label="导出的问题清单" readonly rows="8" style="width:95%"></textarea></section><main id="grid" class="grid"></main><div class="nav"><button id="prevBottom">上一页</button> <button id="nextBottom">下一页</button></div>
<footer>这批结果供人工发现问题，不是“全库质量合格”的结论。没有用目标原稿调参，也没有将目标原稿重新并入档案。严格检查的是笔画协议、来源保真，以及相对旧 v6 新增的跨部件交叉/接触；原有布局问题、异常自交及更粗笔宽仍需人工审查。已知：user_001“震”在 0.05 笔宽下有额外接触。生产默认未变。</footer>
<script src="catalog.js"></script><script>
const $=id=>document.getElementById(id), esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const writers=['user_001','scx','mjb','wsq'];let page=0,flags={},chosen=[],editingId=null;
const key='inkstruct-v61-review-'+DATA.run;
try{flags=JSON.parse(localStorage.getItem(key)||'{}')}catch(e){}
writers.forEach(w=>{$('author').add(new Option(w,w))});
$('summary').textContent=`${DATA.characters.length.toLocaleString()} 字 × 4 位作者；${DATA.summary.complete} 份通过本轮自动检查，${DATA.summary.warning} 份提示，${DATA.summary.failed} 份生成失败。`;
function match(r){let f=$('filter').value;if(!r)return false;return f==='all'||f==='source'&&r.source_strokes>0||f==='full'&&r.source_strokes>0&&r.reference_strokes===0||f==='partial'&&r.source_strokes>0&&r.reference_strokes>0||f==='reference'&&r.source_strokes===0&&r.status!=='failed'||f===r.status||f==='flagged'&&flags[r.writer+':'+r.character]!==undefined}
function render(){let ws=$('author').value==='all'?writers:[$('author').value];let q=$('query').value.trim();chosen=DATA.characters.filter(c=>(!q||q.includes(c)||('U+'+c.codePointAt(0).toString(16).toUpperCase()).includes(q.toUpperCase()))&&ws.some(w=>match(DATA.rows[w][c])));let size=ws.length===4?12:48;let pages=Math.max(1,Math.ceil(chosen.length/size));page=Math.min(page,pages-1);$('position').textContent=`${page+1} / ${pages} 页 · ${chosen.length} 字`;$('grid').style.gridTemplateColumns=ws.length===4?'':'repeat(auto-fill,minmax(230px,1fr))';let cards=[];
chosen.slice(page*size,(page+1)*size).forEach(c=>ws.forEach(w=>{let r=DATA.rows[w][c],cp=c.codePointAt(0).toString(16).toUpperCase(),id=w+':'+c;let flag=flags[id];let donors=(r.donors||[]).map(d=>`${d.character} → 第 ${d.orders.join('、')} 笔`).join('；');let ratio=r.status==='failed'?'失败':`作者 ${r.source_strokes}/${r.strokes} 笔 · 参考 ${r.reference_strokes} 笔`;
cards.push(`<article class="card ${flag!==undefined?'flagged':''}"><div class="title"><b>${esc(c)}</b><span>${w}</span><span class="tag ${r.status}">${esc(ratio)}</span></div>${r.status==='failed'?`<div class="placeholder">${esc(r.error)}</div>`:`<a href="${w}/${cp}.svg" target="_blank"><img loading="lazy" src="${w}/${cp}.svg" alt="${esc(c)} ${w}"></a>`}<div class="detail">${r.warnings.length?'<b>提示：'+esc(r.warnings.join('；'))+'</b><br>':''}${esc(donors||'无可用作者部件；参考回退')}<br><a href="${w}/${cp}.json" target="_blank">检查记录</a>${r.status==='failed'?'':` · <a href="${w}/${cp}.json.gz" download>完整轨迹与来源</a>`}</div><button data-id="${esc(id)}">${flag!==undefined?'修改标记':'标记问题'}</button>${flag!==undefined?`<div class="detail">备注：${esc(flag)}</div>`:''}</article>`)}));$('grid').innerHTML=cards.join('')||'<div class="empty">没有匹配的结果</div>';$('prev').disabled=page===0;$('next').disabled=page===pages-1;$('grid').querySelectorAll('button').forEach(b=>b.onclick=()=>{editingId=b.dataset.id;$('noteTitle').textContent='记录问题：'+editingId;$('noteText').value=flags[editingId]||'';$('noteForm').hidden=false;$('noteForm').scrollIntoView({block:'center'});$('noteText').focus()})}
function storeNote(value){if(value.trim())flags[editingId]=value.trim();else delete flags[editingId];try{localStorage.setItem(key,JSON.stringify(flags))}catch(e){}$('noteForm').hidden=true;editingId=null;render()}
$('noteForm').onsubmit=e=>{e.preventDefault();storeNote($('noteText').value)};$('noteCancel').onclick=()=>{$('noteForm').hidden=true;editingId=null};$('noteDelete').onclick=()=>storeNote('');
['query','author','filter'].forEach(id=>$(id).addEventListener(id==='query'?'input':'change',()=>{page=0;render()}));
function move(delta){page=Math.max(0,page+delta);render();window.scrollTo(0,0)}$('prev').onclick=$('prevBottom').onclick=()=>move(-1);$('next').onclick=$('nextBottom').onclick=()=>move(1);
$('export').onclick=()=>{let value={run:DATA.run,version:DATA.version,brush_width:.028,issues:Object.entries(flags).map(([id,note])=>{let [writer,character]=id.split(':');return {writer,character,note}})};$('exportText').value=JSON.stringify(value,null,2);$('exportPanel').hidden=false;$('exportPanel').scrollIntoView({block:'center'});let a=document.createElement('a');a.href=URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:'application/json'}));a.download='v61-人工审查问题.json';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)};
const params=new URLSearchParams(location.search);if(params.get('q'))$('query').value=params.get('q');if(writers.includes(params.get('author')))$('author').value=params.get('author');render();
</script></html>'''


def report(root, chars):
    rows, totals, summaries = {}, Counter(), {}
    for writer in WRITERS:
        rows[writer] = {}
        counts = Counter()
        for char in chars:
            path = root / writer / f'{ord(char):04X}.json'
            if not path.exists():
                raise RuntimeError(f'missing completed record: {path}')
            r = json.loads(path.read_text())
            counts[r['status']] += 1
            counts['source_strokes'] += r.get('source_strokes', 0)
            counts['reference_strokes'] += r.get('reference_strokes', 0)
            if r['status'] != 'failed':
                counts['all_source' if r['reference_strokes'] == 0 else 'all_reference' if r['source_strokes'] == 0 else 'mixed'] += 1
            if 'regression_exact' in r.get('checks', {}):
                counts['regression_checked'] += 1
                counts['regression_exact'] += int(r['checks']['regression_exact'])
            keep = ('writer', 'character', 'status', 'strokes', 'source_strokes', 'reference_strokes', 'donors', 'warnings', 'error')
            rows[writer][char] = {k: r[k] for k in keep if k in r}
        summaries[writer] = dict(counts)
        totals.update(counts)
    manifest = json.loads((root / 'protocol.json').read_text())
    result = {'expected_outputs': len(chars) * len(WRITERS), 'writers': summaries,
              **{k: totals[k] for k in ('complete', 'warning', 'failed', 'source_strokes', 'reference_strokes', 'regression_checked', 'regression_exact')}}
    (root / 'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    catalog = {'run': root.name, 'version': manifest['baseline_commit'], 'characters': chars, 'rows': rows, 'summary': result}
    # Script-safe JSON allows offline file browsing without fetch/CORS or a server.
    js = json.dumps(catalog, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c').replace('\u2028', '\\u2028').replace('\u2029', '\\u2029')
    (root / 'catalog.js').write_text('const DATA=' + js + ';', encoding='utf-8')
    (root / 'index.html').write_text(PAGE, encoding='utf-8')
    lines = ['# v6.1 exp 四作者全库人工审查', '', f'范围：结构库 {len(chars)} 字，四作者 {len(chars)*4} 份结果。基线代码 `{manifest["baseline_commit"]}`。', '',
             '[打开交互图册](index.html)', '',
             '| 作者 | 完成检查 | 提示 | 失败 | 全作者轨迹字 | 混合字 | 全参考字 | 作者笔画 / 总笔画 |',
             '|---|---:|---:|---:|---:|---:|---:|---:|']
    for w, c in summaries.items():
        lines.append(f'| {w} | {c.get("complete",0)} | {c.get("warning",0)} | {c.get("failed",0)} | {c.get("all_source",0)} | {c.get("mixed",0)} | {c.get("all_reference",0)} | {c.get("source_strokes",0)} / {c.get("source_strokes",0)+c.get("reference_strokes",0)} |')
    lines += ['', f'已冻结回归字逐笔输出核对：{totals["regression_exact"]}/{totals["regression_checked"]} 完全一致。', '',
              '## 阅读边界', '',
              '- 四作者使用现有冻结档案，未重新建档、未添加验证原稿；同字自身来源仍排除。整部件等比变换，不平均或重新平滑。',
              '- 默认显示笔宽 0.028，所有字使用统一 0–1 字框；SVG 外围留白相同。点击字图放大，完整点、压力、时间及候选拒绝原因在同名 JSON.gz。',
              '- 每字检查标准 ID、笔顺、坐标、压力、时间、来源逐点保真、退化及相对旧 v6 新增的跨部件交叉/笔宽接触。通过检查不等于观感合格。',
              '- 作者原有内部交叉保留；未审定所有自交、原有碰撞或更粗笔宽。已知 user_001“震”在 0.05 笔宽下出现额外接触，当前仍待人工判断。',
              '- 全参考回退没有作者笔形，不能据此评价该作者的风格迁移；本轮也不把全库当成未见留出集。',
              '- 失败不会暗中改用另一生成器，记录异常原因；自动提示不隐藏，供人工复核。生产默认和旧数据未改动。',
              '- 图册可输入多个汉字，按作者和覆盖类型筛选；四作者并排时，同字其他作者即使不满足筛选也保留，便于对照。问题备注可导出 JSON。', '',
              '## 文件', '',
              '`protocol.json` 冻结输入/代码哈希；`summary.json` 汇总；`作者/码位.json` 检查及文件哈希；同名 `.json.gz` 完整输出与来源；`.svg` 同尺度图。']
    (root / 'report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('output', type=Path)
    args = p.parse_args()
    report(args.output, json.loads((args.output / 'protocol.json').read_text())['characters'])
