"""CPU/GPU full selector decisions on real corrected graphs and real source ink.

Reference context is explicit: this isolates selection/collision correctness and
does not claim a newly generated 64-character font or independent quality test.
"""
import bootstrap as b
import hashlib
import json
import time
import numpy as np
from candidates import prepare,injected
from fitting import GPUFit
from inkstruct import v61_author_strokes_batch as module
from inkstruct.structure_corrections import CorrectedStructureRepository
from inkstruct.generation_workflow import corrections
from monitor import Monitor

monitor=Monitor().start();repo,single,report=prepare();target_repo=CorrectedStructureRepository(repo,*corrections())
all_chars=repo.characters();chars=list(dict.fromkeys(list('孔正址兄礼烧止怔歪羊群')+[all_chars[i] for i in np.linspace(0,len(all_chars)-1,48,dtype=int)]))
gpu=GPUFit();original=module.BatchAuthorStrokeFallback.select;experimental=injected(gpu.verified)
rows=[];start=time.perf_counter();output=b.OUT/'decision-payloads.jsonl'
assert not output.exists()
with output.open('w',encoding='utf-8') as f:
    try:
        for ch in chars:
            graph=target_repo.get(ch);reference=[s.median for s in graph.strokes]
            for index in range(len(reference)):
                results={};times={}
                order=('cpu','gpu') if len(rows)%2 else ('gpu','cpu')
                for backend in order:
                    module.BatchAuthorStrokeFallback.select=original if backend=='cpu' else experimental
                    t=time.perf_counter();results[backend]=single.select(graph,index,reference,reference);times[backend]=time.perf_counter()-t
                assert results['cpu']==results['gpu'],(ch,index)
                piece,evidence=results['cpu'];raw=json.dumps(results['cpu'],ensure_ascii=False,sort_keys=True)
                row={'character':ch,'stroke':graph.strokes[index].stroke_id,'accepted':piece is not None,
                     'donor':evidence.get('sample_id'),'source_stroke':evidence.get('source_stroke_id'),
                     'times':times,'payload_sha256':hashlib.sha256(raw.encode()).hexdigest(),
                     'rejections':evidence.get('rejections',{})}
                rows.append(row);f.write(json.dumps({'case':row,'cpu':results['cpu'],'gpu':results['gpu']},ensure_ascii=False)+'\n')
            print('decisions',ch,len(rows),flush=True)
    finally:module.BatchAuthorStrokeFallback.select=original
report.update(characters=chars,rows=rows,accepted=sum(r['accepted'] for r in rows),
    total_s=time.perf_counter()-start,gpu_context_s=gpu.init_seconds,max_abs_error=gpu.max_error,
    verified_candidate_pairs=gpu.verified_pairs,gpu_records=gpu.records,monitor=monitor.stop(),
    context='corrected reference strokes; no generated-font quality claim',all_payloads_exact=True)
b.save('decisions.json',report)
print('accepted',report['accepted'],'/',len(rows),'seconds',report['total_s'],flush=True)
