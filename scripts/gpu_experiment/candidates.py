"""Real v6.2 pools, optimized NumPy baseline, synchronized FP64 GPU experiment."""
import bootstrap as b
import cProfile
import hashlib
import inspect
import json
import pstats
import sys
import textwrap
import time
from collections import defaultdict
import numpy as np
from monitor import Monitor
from fitting import GPUFit, cpu_fit, packed_cpu, pack_q
from inkstruct.profile import load_profile
from inkstruct.structures import StructureRepository
from inkstruct.v62_exp import SemanticBatchStrokeFallback
from inkstruct import v61_author_strokes_batch as module

PROFILE=b.ROOT/'artifacts/v61_collection_acceptance_20261013/run_v3_with_validation/source_archive.json'

def injected(calculator):
    """Retain exact original source after numeric stage, including all gates."""
    source=textwrap.dedent(inspect.getsource(module.BatchAuthorStrokeFallback.select))
    start=source.index('        y = anchors([target])')
    end=source.index('        for n, (sample, source, _) in enumerate(entries):',start)
    source=source[:start]+'        scale, offset, ratio, ends, low, high, scores = experiment_fit(d, target, start_anchor)\n'+source[end:]
    namespace={**vars(module),'experiment_fit':calculator};exec(source,namespace)
    return namespace['select']

def prepare():
    t=time.perf_counter();profile=load_profile(PROFILE);load=time.perf_counter()-t
    t=time.perf_counter();repo=StructureRepository();single=SemanticBatchStrokeFallback(profile,repo);init=time.perf_counter()-t
    return repo,single,{'profile_load_s':load,'source_pool_and_descriptors_s':init,'pool_sizes':{k:len(v) for k,v in single.pool.items()}}

def fit_benchmark():
    monitor=Monitor().start();repo,single,report=prepare();gpu=GPUFit();report['gpu_context_s']=gpu.init_seconds
    # Stratify over the whole repository in codepoint order; no candidate pruning.
    chars=repo.characters();chosen=list(dict.fromkeys(list('孔正址兄礼烧止怔歪羊群')+[chars[i] for i in np.linspace(0,len(chars)-1,512,dtype=int)]))
    report['repository_characters']=len(chars);report['characters']=chosen
    from inkstruct.structure_corrections import CorrectedStructureRepository
    from inkstruct.generation_workflow import corrections
    target_repo=CorrectedStructureRepository(repo,*corrections())
    groups={};identities={};prepared=[]
    # Let the actual v6.2 mixin perform semantic filtering. Stop BEFORE ranking/
    # collision only for this stage experiment; full-pipeline validation below.
    original=module.BatchAuthorStrokeFallback.select
    def capture(self,graph,index,current,reference,*,start_anchor=None):
        from inkstruct.v61_author_strokes import stroke_class
        kind=stroke_class(graph.strokes[index].median);d=self.descriptors.get(kind)
        if d is not None:
            entries=self.pool[kind];identity=tuple((s.sample_id,st.standard_stroke_id) for s,st,_ in entries)
            if identity not in identities:
                key=len(identities);identities[identity]=key;groups[key]={'d':d,'targets':[],'identities':identity,'kind':kind}
            group=groups[identities[identity]]
            group['targets'].append(reference[index]);prepared.append((graph.character,index,identities[identity]))
        return None,{}
    module.BatchAuthorStrokeFallback.select=capture
    start=time.perf_counter()
    try:
        for i,ch in enumerate(chosen):
            graph=target_repo.get(ch);ref=[s.median for s in graph.strokes]
            for n in range(len(ref)):single.select(graph,n,ref,ref)
            if i%64==0:print('prepared',i,len(chosen),flush=True)
    finally:module.BatchAuthorStrokeFallback.select=original
    report['semantic_query_prepare_s']=time.perf_counter()-start
    report['query_count']=len(prepared);report['groups']=[{'kind':g['kind'],'candidates':len(g['d']['length']),'queries':len(g['targets'])} for g in groups.values()]
    report['candidate_pairs']=sum(len(g['d']['length'])*len(g['targets']) for g in groups.values())
    b.save('candidate-inputs.json',{'report':report,'queries':prepared,'pool_identities':[g['identities'] for g in groups.values()]})
    records=[];max_error=0
    # Small correctness first, including every represented semantic pool.
    first_use=[]
    for g in groups.values():
        tar=g['targets'][0];out,t=gpu.batch(g['d'],pack_q(tar)[None,:]);expected=packed_cpu(cpu_fit(g['d'],tar))
        assert np.allclose(out[0],expected,rtol=1e-11,atol=1e-12)
        max_error=max(max_error,float(np.max(np.abs(out[0]-expected))))
        first_use.append(t)
    report['small_check_max_error']=max_error
    report['first_use_batches']=first_use
    b.save('candidate-stage-progress.json',report)
    # Compute on resident candidates, transfers and full conservative CPU
    # verification separately. Alternate CPU/GPU timing order each repeat.
    for rep in range(5):
        row={'repeat':rep,'batches':[]}
        def cpu_all():
            start=time.perf_counter()
            for g in groups.values():
                for tar in g['targets']:cpu_fit(g['d'],tar)
            row['cpu_s']=time.perf_counter()-start
        def gpu_all():
            start=time.perf_counter();verify=0;device=upload=download=0
            for g in groups.values():
                targets=g['targets']
                for pos in range(0,len(targets),256):
                    subset=targets[pos:pos+256]
                    t=time.perf_counter();queries=np.asarray([pack_q(t) for t in subset]);packing=time.perf_counter()-t
                    out,times=gpu.batch(g['d'],queries)
                    t=time.perf_counter()
                    for i,tar in enumerate(subset):
                        expected=packed_cpu(cpu_fit(g['d'],tar))
                        assert np.allclose(out[i],expected,rtol=1e-11,atol=1e-12)
                    verification=time.perf_counter()-t;verify+=verification
                    device+=times['device_event_s'];upload+=times['candidate_upload_s']+times['query_upload_alloc_s'];download+=times['download_s']
                    row['batches'].append({**times,'queries':len(subset),'candidates':len(g['d']['length']),'pack_s':packing,'cpu_verify_s':verification})
            row.update(gpu_including_verify_s=time.perf_counter()-start,cpu_verify_s=verify,device_s=device,upload_s=upload,download_s=download)
        for fn in ((cpu_all,gpu_all) if rep%2==0 else (gpu_all,cpu_all)):fn()
        records.append(row);print('paired',rep,{k:v for k,v in row.items() if k!='batches'},flush=True)
        b.save('candidate-stage.json',{**report,'repetitions':records})
    # Actual same-pool scale crossover: only distinct real targets, no tiling.
    largest=max(groups.values(),key=lambda g:len(g['targets']))
    scale=[]
    for count in (1,8,32,128,256):
        if len(largest['targets'])<count:continue
        targets=largest['targets'][:count];queries=np.asarray([pack_q(t) for t in targets])
        for rep in range(7):
            t=time.perf_counter();expected=[packed_cpu(cpu_fit(largest['d'],tar)) for tar in targets];cpu=time.perf_counter()-t
            out,times=gpu.batch(largest['d'],queries);assert np.allclose(out,expected,rtol=1e-11,atol=1e-12)
            scale.append({'queries':count,'candidates':len(largest['d']['length']),'repeat':rep,'cpu_s':cpu,**times})
    report['repetitions']=records;report['scale']=scale;report['monitor']=monitor.stop()
    report['correctness']='all candidate numeric outputs checked FP64; all downstream decisions require CPU authoritative recomputation'
    b.save('candidate-stage.json',report)

def full_pipeline(backend,rep):
    from inkstruct.generation_workflow import generate_v61
    from inkstruct.samples import sha256_file
    monitor=Monitor().start();gpu=GPUFit() if backend=='gpu' else None
    numeric=[]
    def measured(d,target,start_anchor=None):
        start=time.perf_counter();out=(gpu.verified if gpu else cpu_fit)(d,target,start_anchor)
        numeric.append(time.perf_counter()-start);return out
    original=module.BatchAuthorStrokeFallback.select
    output=b.OUT/f'pipeline-{backend}-{rep}'
    from attribution import Attribution
    attribution=Attribution().generation() if rep>0 else None
    module.BatchAuthorStrokeFallback.select=injected(measured)
    profiler=cProfile.Profile() if rep==0 and backend=='cpu' else None
    start=time.perf_counter()
    try:
        if profiler:profiler.enable()
        result=generate_v61(output,'user_001',list('孔正址兄礼烧止怔歪羊群'),StructureRepository(),
            {'path':str(PROFILE),'sha256':sha256_file(PROFILE)},lambda r:print(r,flush=True),lambda:False,semantic=True)
    finally:
        module.BatchAuthorStrokeFallback.select=original
        phases=attribution.close() if attribution else None
        if profiler:
            profiler.disable();profiler.dump_stats(str(b.OUT/'candidate-pipeline.prof'))
            with (b.OUT/'candidate-pipeline-profile.txt').open('w',encoding='utf-8') as f:
                pstats.Stats(profiler,stream=f).sort_stats('cumulative').print_stats(100)
    seconds=time.perf_counter()-start
    b.save(f'pipeline-{backend}-{rep}.json',{'seconds':seconds,'profiled':bool(profiler),'phases_inclusive_not_additive':phases,'numeric_seconds':numeric,'result':result,
        'gpu':{'init_s':gpu.init_seconds,'max_error':gpu.max_error,'verified_pairs':gpu.verified_pairs,'records':gpu.records} if gpu else None,'monitor':monitor.stop()})
    print('pipeline',backend,rep,seconds,flush=True)

if __name__=='__main__':
    if sys.argv[1]=='stage':fit_benchmark()
    else:full_pipeline(sys.argv[1],int(sys.argv[2]))
