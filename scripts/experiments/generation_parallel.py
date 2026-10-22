"""Isolated v6.2 target-set/concurrency experiment. No application hooks.

The character body is compiled directly from the current production AST, not a
second implementation. All resources are worker local; the donor pool is whole.
"""
from __future__ import annotations

import os
for _key in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[_key] = '1'
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'

import argparse
import ast
import concurrent.futures as futures
import gzip
import hashlib
import inspect
import json
import multiprocessing as mp
from pathlib import Path
import statistics
import subprocess
import sys
import threading
import time
import traceback
import contextlib
import textwrap

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
# Reuse the existing isolated experiment's monitor dependency, never install it
# into or change the application environment.
sys.path.append(str(ROOT / '.venv-gpu-experiment/Lib/site-packages'))
OUT = Path(os.environ.get('INKSTRUCT_GENERATION_EXPERIMENT_OUT',str(ROOT/'artifacts/generation_sets_parallel_20261022'))).resolve()
OUT.relative_to((ROOT/'artifacts').resolve())
if OUT.is_dir():
    for key,name in [('TEMP','tmp'),('TMP','tmp'),('MPLCONFIGDIR','mpl-cache')]:
        cache=OUT/name;cache.mkdir(exist_ok=True);os.environ[key]=str(cache)
PROFILE = ROOT / 'artifacts/v61_collection_acceptance_20261013/run_v3_with_validation/source_archive.json'
DATABASE = ROOT / 'artifacts/structures/characters.sqlite3'
SMALL = '孔正址兄礼烧止怔歪羊群'
LOCAL = threading.local()


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), 'utf-8')


def canonical(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


class Timer:
    """Inclusive attribution, one wrapper per process (not used for threads)."""
    def __init__(self):
        self.rows = {}
        self.restores = []

    def wrap(self, obj, name, label):
        old = getattr(obj, name)
        def call(*args, **kwargs):
            started = time.perf_counter()
            try:
                return old(*args, **kwargs)
            finally:
                row = self.rows.setdefault(label, {'seconds': 0., 'calls': 0})
                row['seconds'] += time.perf_counter() - started
                row['calls'] += 1
        setattr(obj, name, call)
        self.restores.append((obj, name, old))

    def install(self):
        import importlib
        specs = [
            ('inkstruct.profile', 'load_profile', 'profile_read_parse'),
            ('inkstruct.generation_v61_helpers', 'check_sources', 'source_integrity'),
            ('inkstruct.generation_v61_helpers', 'compact_sources', 'source_summary'),
            ('inkstruct.generation_v61_helpers', 'source_audit', 'source_audit'),
            ('inkstruct.trajectory_experiment', 'invariants', 'geometry_protocol'),
            ('inkstruct.v61_author_strokes_batch', 'crossing_pairs', 'collision_crossing'),
            ('inkstruct.v61_author_strokes_batch', 'contact_pairs', 'collision_contact'),
            ('inkstruct.v61_candidate_expansion', 'fit_bounded_axes', 'component_axis_fit'),
            ('inkstruct.v61_candidate_expansion', 'fit_shared_similarity', 'component_similarity_fit'),
            ('inkstruct.v61_candidate_expansion', 'correspondence', 'component_correspondence'),
            ('gzip', 'compress', 'compress'), ('json', 'dumps', 'json_encode')]
        for module, name, label in specs:
            self.wrap(importlib.import_module(module), name, label)
        from inkstruct.structures import StructureRepository
        self.wrap(StructureRepository, 'get', 'structure_sql_decode')
        self.wrap(StructureRepository, 'content_sha256', 'structure_logical_hash')
        from inkstruct.structure_corrections import CorrectedStructureRepository
        self.wrap(CorrectedStructureRepository, '__init__', 'corrected_resource_init')
        from inkstruct.v62_exp import SemanticBatchStrokeFallback, SemanticCandidateGenerator
        self.wrap(SemanticCandidateGenerator, '__init__', 'engine_init')
        self.wrap(SemanticBatchStrokeFallback, '__init__', 'stroke_pool_descriptors_init')
        for name in ('inventory', 'prepare', 'expand', 'extend'):
            self.wrap(SemanticCandidateGenerator, name, 'component_' + name)
        self.wrap(SemanticBatchStrokeFallback, 'select', 'semantic_select_fit_sort_collision')
        self.wrap(Path, 'write_bytes', 'write_binary')
        from inkstruct import generation_workflow
        self.wrap(generation_workflow,'sha256_file','output_and_profile_hash')
        # Time the exact production NumPy/filter/sort blocks separately. A with
        # scope adds only timing; early returns still run its finally clause.
        from inkstruct import v61_author_strokes_batch as batch
        original=batch.BatchAuthorStrokeFallback.select
        function=ast.parse(textwrap.dedent(inspect.getsource(original))).body[0]
        @contextlib.contextmanager
        def phase(label):
            tick=time.perf_counter()
            try:yield
            finally:
                row=self.rows.setdefault(label,{'seconds':0.,'calls':0})
                row['seconds']+=time.perf_counter()-tick;row['calls']+=1
        def scoped(nodes,label):
            return ast.With(items=[ast.withitem(context_expr=ast.Call(func=ast.Name(id='_experiment_phase',ctx=ast.Load()),args=[ast.Constant(label)],keywords=[]))],body=nodes)
        branch=next(n for n in function.body if isinstance(n,ast.If) and ast.unparse(n.test)=='d is not None')
        first_loop=next(i for i,n in enumerate(branch.body) if isinstance(n,ast.For))
        branch.body=[scoped(branch.body[:first_loop],'numpy_fit_arrays'),scoped(branch.body[first_loop:],'candidate_admission_filters')]
        function.body=[scoped([n],'candidate_sort') if isinstance(n,ast.Expr) and ast.unparse(n).startswith('ranked.sort')
                       else scoped([n],'candidate_final_geometry') if isinstance(n,ast.For) else n for n in function.body]
        namespace={**vars(batch),'_experiment_phase':phase}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[function],type_ignores=[])),str(batch.__file__),'exec'),namespace)
        batch.BatchAuthorStrokeFallback.select=namespace['select']
        self.restores.append((batch.BatchAuthorStrokeFallback,'select',original))


def initialize(profile_path=None, attribute=False):
    entry_ns=time.perf_counter_ns()
    from inkstruct import generation_workflow as module
    from inkstruct.structures import StructureRepository
    started = time.perf_counter()
    timer = Timer()
    if attribute:
        timer.install()
    source = inspect.getsource(module.generate_v61)
    tree = ast.parse(source).body[0]
    ns = dict(vars(module))
    profile = Path(profile_path or PROFILE)
    ns.update(semantic=True, base=StructureRepository(DATABASE),
              profile_record={'path': str(profile), 'sha256': digest(profile)}, writer='user_001')
    # Production imports/class selection and exact resource initialization.
    cut = next(i for i, node in enumerate(tree.body)
               if ast.unparse(node).startswith('output.mkdir'))
    setup = tree.body[:cut]
    setup += tree.body[cut + 1: next(i for i, node in enumerate(tree.body)
                 if ast.unparse(node).startswith('protocol ='))]
    exec(compile(ast.fix_missing_locations(ast.Module(body=setup, type_ignores=[])),
                 str(module.__file__), 'exec'), ns)
    initial_rules = list(ns['engine'].rule_log)
    ns['engine'].rule_log = []
    loop = next(node for node in tree.body if isinstance(node, ast.For))
    first = next(i for i, node in enumerate(loop.body) if ast.unparse(node).startswith('stem ='))
    last = next(i for i, node in enumerate(loop.body) if ast.unparse(node).startswith('engine.rule_log ='))
    body = ast.Module(body=loop.body[first:last + 1], type_ignores=[])
    LOCAL.state = {'namespace': ns, 'body': compile(ast.fix_missing_locations(body), str(module.__file__), 'exec'),
                   'initial_rules': initial_rules, 'timer': timer, 'initialization_s': time.perf_counter()-started,
                   'source_sha256': hashlib.sha256(source.encode()).hexdigest(), 'count': 0}
    LOCAL.state['initializer_entry_ns']=entry_ns
    LOCAL.state['resources_ready_ns']=time.perf_counter_ns()
    save(OUT/'worker-initializations'/f'{os.getpid()}-{threading.get_ident()}-{time.time_ns()}.json',
         {'pid':os.getpid(),'profile_sha256':ns['profile_record']['sha256'],
          'initial_rules':initial_rules,'inventory_rules_hash':canonical(initial_rules),
          'production_function_sha256':LOCAL.state['source_sha256'],
          'initialization_s':LOCAL.state['initialization_s']})
    return {'pid': os.getpid(), 'initialization_s': LOCAL.state['initialization_s'],
            'pool_sizes': {k: len(v) for k, v in ns['single'].pool.items()},
            'inventory_rules_hash': canonical(initial_rules), 'inventory_rules': initial_rules,
            'production_function_sha256': LOCAL.state['source_sha256']}


def compute(job):
    task_entry_ns=time.perf_counter_ns()
    character, output, fault = job
    if fault == 'crash':
        os._exit(79)
    if fault == 'raise':
        raise RuntimeError('injected transient worker failure')
    state = LOCAL.state
    ns = dict(state['namespace'])
    output = Path(output)
    folder = output / 'user_001'
    folder.mkdir(parents=True, exist_ok=True)
    ns.update(character=character, output=output, folder=folder, complete=[], failed=[], warned=[])
    if fault == 'after-payload':
        # Inject a crash between the production compressed payload and its
        # commit row. Kept in staging and never advertised as completed.
        tree=ast.parse(inspect.getsource(__import__('inkstruct.generation_workflow',fromlist=['generate_v61']).generate_v61)).body[0]
        loop=next(node for node in tree.body if isinstance(node,ast.For))
        attempt=next(node for node in loop.body if isinstance(node,ast.Try))
        index=next(i for i,node in enumerate(attempt.body) if ast.unparse(node).startswith('path.write_bytes'))
        code=ast.Module(body=attempt.body[:index+1],type_ignores=[])
        ns['stem']=folder/f'{ord(character):04X}';ns['row']={'warnings':[]}
        exec(compile(ast.fix_missing_locations(code),'injected-staging-crash','exec'),ns)
        os._exit(80)
    state['namespace']['engine'].rule_log = []
    started = time.perf_counter()
    exec(state['body'], ns)
    elapsed = time.perf_counter() - started
    state['count'] += 1
    if state['count'] % 100 == 0:
        ns['target']._cache.clear()
        ns['engine']._rule_graphs = {k:v for k,v in ns['engine']._rule_graphs.items() if k[0]=='source'}
    row = ns['row']
    payload_path = folder / f'{ord(character):04X}.json.gz'
    payload = json.loads(gzip.decompress(payload_path.read_bytes())) if row['status'] != 'failed' else None
    record={'character': character, 'pid': os.getpid(), 'compute_publish_s': elapsed,
            'initialization_s': state['initialization_s'], 'worker_count': state['count'],
            'payload_hash': canonical(payload), 'row_without_files_hash': canonical({k:v for k,v in row.items() if k!='files'}),
            'status': row['status'], 'warnings': row['warnings'],
            'inventory_rules_hash': canonical(state['initial_rules']),
            'phases_inclusive': dict(state['timer'].rows)}
    record.update(worker_entry_ns=task_entry_ns,initializer_entry_ns=state['initializer_entry_ns'],
                  resources_ready_ns=state['resources_ready_ns'],worker_return_ready_ns=time.perf_counter_ns())
    return record


class Monitor:
    def __init__(self):
        self.rows=[]; self.stop=threading.Event()
    def start(self):
        import psutil
        self.process=psutil.Process()
        self.started=time.perf_counter()
        self.thread=threading.Thread(target=self.run, daemon=True);self.thread.start()
        return self
    def run(self):
        import psutil
        while not self.stop.is_set():
            group=[self.process]+self.process.children(recursive=True)
            rss=private=cpu=read=write=0;errors=0
            for p in group:
                try:
                    memory=p.memory_info();rss+=memory.rss;private+=getattr(memory,'private',0)
                    c=p.cpu_times();cpu+=c.user+c.system
                    io=p.io_counters();read+=io.read_bytes;write+=io.write_bytes
                except (psutil.NoSuchProcess,psutil.AccessDenied):errors+=1
            self.rows.append({'t':time.perf_counter()-self.started,'rss':rss,'private':private,'cpu_s':cpu,'read_bytes':read,'write_bytes':write,'access_or_exit_errors':errors})
            self.stop.wait(.1)
    def close(self):
        self.stop.set();self.thread.join();return self.rows


def trial(mode, workers, characters, label, rounds=2, attribute=False):
    if not characters:
        raise ValueError('No supported output targets; no resources or workers started')
    destination=OUT/label
    destination.mkdir(parents=True,exist_ok=False)
    monitor=Monitor().start(); start=time.perf_counter()
    executor=None
    if mode=='serial':
        init=initialize(attribute=attribute)
    else:
        cls=futures.ProcessPoolExecutor if mode=='process' else futures.ThreadPoolExecutor
        options={'mp_context':mp.get_context('spawn')} if mode=='process' else {}
        executor=cls(max_workers=workers, initializer=initialize, initargs=(None,attribute),**options)
        init=None
    results=[]
    shutdown_s=0.
    try:
        for repeat in range(rounds):
            output=destination/f'round-{repeat}'
            output.mkdir()
            tick=time.perf_counter()
            jobs=[(c,str(output),None) for c in characters]
            if executor:
                future_rows={};submitted={};received={}
                for job in jobs:
                    submitted[job[0]]=time.perf_counter_ns()
                    future_rows[executor.submit(compute,job)]=job[0]
                for future in futures.as_completed(future_rows):
                    record=future.result();record['parent_receive_ns']=time.perf_counter_ns()
                    record['parent_submit_ns']=submitted[record['character']]
                    received[record['character']]=record
                records=[received[c] for c in characters]
            else:
                records=[compute(j) for j in jobs]
            rows={'round':repeat,'wall_s':time.perf_counter()-tick,'characters':list(characters),'results':records}
            results.append(rows)
            publish_tick=time.perf_counter()
            save(output/'protocol.json',{'writers':['user_001'],'characters':[r['character'] for r in records if r['status']!='failed'],
                 'requested_characters':list(characters),'method':'v6.2 exp','version':__import__('inkstruct.generation_workflow',fromlist=['V62_VERSION']).V62_VERSION,
                 'generation_mode':'cross_character_generation','same_character_sources_excluded':True,
                 'profile':{'path':str(PROFILE),'sha256':digest(PROFILE)},'experiment':True})
            save(output/'summary.json',rows)
            rows['summary_publish_s']=time.perf_counter()-publish_tick
            print(label,'round',repeat,'wall',round(rows['wall_s'],3),'pids',sorted({r['pid'] for r in records}),flush=True)
    finally:
        if executor:
            shutdown_tick=time.perf_counter();executor.shutdown(wait=True,cancel_futures=True)
            shutdown_s=time.perf_counter()-shutdown_tick
        samples=monitor.close()
        save(destination/'measurement.json',{'mode':mode,'workers':workers,'initialization':init,'total_including_shutdown_s':time.perf_counter()-start,
             'rounds':results,'monitor':samples,'peak_group_rss':max(r['rss'] for r in samples),'attribution_enabled':attribute})
        if executor:
            save(destination/'transport.json',{'shutdown_s':shutdown_s,'summary_publish_s':[r.get('summary_publish_s') for r in results],
                'samples':[{'character':r['character'],'round':batch['round'],'pid':r['pid'],
                   'submit_to_worker_start_ms':(r['worker_entry_ns']-r['parent_submit_ns'])/1e6,
                   'return_ready_to_parent_ms':(r['parent_receive_ns']-r['worker_return_ready_ns'])/1e6,
                   'resource_init_ms':(r['resources_ready_ns']-r['initializer_entry_ns'])/1e6,
                   'result_pickle_bytes':len(__import__('pickle').dumps({k:v for k,v in r.items() if not k.startswith('parent_')},protocol=5))}
                   for batch in results for r in batch['results']],
                'caveat':'return-ready to parent includes serialization, pipe, futures dispatch and parent wake-up; not pure wire time. Submit delay includes queue and cold resource initialization.'})


def prepare():
    OUT.mkdir(exist_ok=False)
    for name,args in [('git-status-before.txt',['status','--short','--untracked-files=all']),('git-head-before.txt',['rev-parse','HEAD'])]:
        (OUT/name).write_bytes(subprocess.check_output(['git',*args],cwd=ROOT))
    sources={p.relative_to(ROOT).as_posix():digest(p) for folder in ('src','tests','configs','packaging')
             for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts}
    save(OUT/'source-before.json',sources)
    previous=json.loads((ROOT/'artifacts/export_parallel_0.1.38_20261022/user-data-before.json').read_text('utf-8'))
    data={}
    for name in previous:
        p=Path(name)
        if p.is_file():
            s=p.stat();data[name]={'size':s.st_size,'mtime_ns':s.st_mtime_ns}
    save(OUT/'user-data-before-metadata.json',data)
    from inkstruct.generation_workflow import corrections,code_hashes
    from inkstruct.fonts import APP_VERSION
    from inkstruct.structures import StructureRepository
    import platform,psutil
    all_chars=StructureRepository(DATABASE).characters()
    representative=list(dict.fromkeys(list(SMALL)+[all_chars[round(i*(len(all_chars)-1)/20)] for i in range(21)]))
    save(OUT/'inputs.json',{'app_version':APP_VERSION,'head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
         'platform':platform.platform(),'processor':platform.processor(),'logical_cpus':psutil.cpu_count(),'physical_cpus':psutil.cpu_count(logical=False),
         'memory_bytes':psutil.virtual_memory().total,'disk_free':__import__('shutil').disk_usage(ROOT).free,
         'power':subprocess.check_output(['powercfg','/getactivescheme'],text=True,errors='replace'),
         'profile':str(PROFILE),'resources':{str(p):digest(p) for p in [PROFILE,DATABASE,*corrections()]},
         'code':code_hashes(),'small':list(SMALL),'representative':representative,'all_supported':all_chars,
         'numpy_threads':{k:os.environ[k] for k in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS')},
         'baseline_system_cpu_percent':psutil.cpu_percent(interval=1),'cold_definition':'new interpreter/worker; OS disk cache not flushed'})


def compare():
    paths=sorted(OUT.glob('*/round-*/summary.json'))
    reference={};mismatch=[];count=0
    for path in paths:
        for record in json.loads(path.read_text('utf-8'))['results']:
            key=record['character'];identity=(record['payload_hash'],record['row_without_files_hash'])
            if key in reference and reference[key][0]!=identity:
                mismatch.append({'character':key,'first':reference[key][1],'other':str(path),'identity':identity})
            else:reference[key]=(identity,str(path))
            count+=1
    save(OUT/'comparison.json',{'comparisons':count,'unique_characters':len(reference),'mismatches':mismatch})
    print('Compared',count,'records; mismatches',len(mismatch),flush=True)
    if mismatch:raise AssertionError(mismatch[:2])


def production():
    from inkstruct.generation_workflow import generate_v61
    from inkstruct.structures import StructureRepository
    started=time.perf_counter()
    result=generate_v61(OUT/'production-reference','user_001',list(SMALL),StructureRepository(DATABASE),
                       {'path':str(PROFILE),'sha256':digest(PROFILE)},None,lambda:False,semantic=True)
    save(OUT/'production-reference-measurement.json',{'wall_s':time.perf_counter()-started,'result':result})
    differences=[]
    inventory=[]
    for char in SMALL:
        name=f'{ord(char):04X}.json.gz'
        a=json.loads(gzip.decompress((OUT/'production-reference/user_001'/name).read_bytes()))
        b=json.loads(gzip.decompress((OUT/'small-serial-1/round-0/user_001'/name).read_bytes()))
        if char==SMALL[0]:
            # Global inventory evidence emitted by production in its first glyph
            # is retained separately by the prototype, not silently dropped.
            n=len(a['rule_log'])-len(b['rule_log'])
            inventory=a['rule_log'][:n]
            a['rule_log']=a['rule_log'][n:]
        if a!=b:
            differences.append({'character':char,'different_fields':[k for k in a if a[k]!=b.get(k)]})
    save(OUT/'production-equivalence.json',{'differences':differences,'initial_inventory_evidence':inventory,
         'inventory_hash':canonical(inventory),'comparison':'all decoded fields exact after separately retaining one global inventory prefix'})
    assert not differences,differences


def suite():
    tasks=[('production',[])]
    for rep in range(1,4):
        for mode,workers in [('serial',1),('process',2),('process',4),('thread',2)]:
            label=f'small-{mode}{workers if mode!="serial" else ""}-{rep}'
            if (OUT/label/'measurement.json').is_file():continue
            tasks.append(('trial',['--mode',mode,'--workers',str(workers),'--label',label,'--rounds','2']))
    for mode,workers in [('serial',1),('process',2),('process',4)]:
        tasks.append(('trial',['--mode',mode,'--workers',str(workers),'--set','representative','--label',f'representative-{mode}{workers}','--rounds','3']))
    tasks.append(('trial',['--label','attribution','--rounds','1','--attribute']))
    for action,options in tasks:
        label=options[options.index('--label')+1] if '--label' in options else action
        command=[sys.executable,'-B','-X','utf8',str(Path(__file__).resolve()),action,*options]
        tick=time.perf_counter()
        with (OUT/(label+'.native.log')).open('x',encoding='utf-8') as stream:
            process=subprocess.run(command,stdout=stream,stderr=subprocess.STDOUT,cwd=ROOT)
        save(OUT/(label+'.command.json'),{'command':command,'returncode':process.returncode,'wall_s':time.perf_counter()-tick})
        print(label,process.returncode,flush=True)
        if process.returncode:raise RuntimeError(label)
    compare()


def faults():
    destination=OUT/'faults';destination.mkdir(exist_ok=False)
    events=[]
    context=mp.get_context('spawn')
    def verified(root):
        valid=[]
        for path in (root/'user_001').glob('*.json'):
            row=json.loads(path.read_text('utf-8'))
            if row.get('status') not in ('complete','warning'):continue
            if row.get('files') and all(digest(root/name)==h for name,h in row['files'].items()):
                valid.append(row['character'])
        return valid
    # Cooperatively stop admission while one character is running; completion
    # remains valid, unsubmitted work is explicitly pending, not silently lost.
    root=destination/'cancel';tick=time.perf_counter()
    with futures.ProcessPoolExecutor(1,mp_context=context,initializer=initialize) as pool:
        running=pool.submit(compute,('正',str(root),None))
        queued=pool.submit(compute,('孔',str(root),None))
        cancelled=queued.cancel()
        result=running.result()
    events.append({'case':'cancel','queued_cancelled':cancelled,'complete':verified(root),'pending':['孔'],
                   'cancel_to_quiescence_s':time.perf_counter()-tick,'boundary':'current character finishes; no new admission'})
    assert cancelled and verified(root)==['正']
    # A transient exception retries once on the SAME persistent worker state.
    root=destination/'retry'
    with futures.ProcessPoolExecutor(1,mp_context=context,initializer=initialize) as pool:
        try:pool.submit(compute,('孔',str(root),'raise')).result()
        except RuntimeError as error:events.append({'case':'transient','error':str(error)})
        result=pool.submit(compute,('孔',str(root),None)).result()
    assert verified(root)==['孔']
    # Abrupt failure leaves an actual payload without the commit row; reject it.
    root=destination/'crash-staging'
    with futures.ProcessPoolExecutor(1,mp_context=context,initializer=initialize) as pool:
        retained=pool.submit(compute,('孔',str(root),None)).result()
        try:pool.submit(compute,('正',str(root),'after-payload')).result()
        except futures.process.BrokenProcessPool as error:events.append({'case':'crash','error':str(error)})
    assert (root/'user_001/6B63.json.gz').is_file() and verified(root)==['孔']
    # Parent retries into a NEW attempt, then exposes only checked artifacts.
    import shutil
    staging=root;root=destination/'serial-fallback';(root/'user_001').mkdir(parents=True)
    for suffix in ('.json','.json.gz'):
        shutil.copyfile(staging/'user_001'/('5B54'+suffix),root/'user_001'/('5B54'+suffix))
    initialize()
    results=[retained,compute(('正',str(root),None))]
    expected=json.loads((OUT/'small-serial-1/round-0/summary.json').read_text('utf-8'))['results']
    by={r['character']:r for r in expected}
    assert all(r['payload_hash']==by[r['character']]['payload_hash'] for r in results)
    events.append({'case':'serial-fallback','complete':verified(root),'identity_exact':True,'retained_complete_without_regeneration':['孔']})
    # Unsupported character isolates failure and never creates publishable ink.
    root=destination/'unsupported';result=compute(('A',str(root),None))
    assert result['status']=='failed' and not verified(root)
    events.append({'case':'unsupported','result':result,'complete':verified(root)})
    save(destination/'verification.json',{'passed':True,'events':events,'cancel_semantics':'between characters; hard mid-character crash is not publication',
         'frozen_executable':'not yet tested; source interpreter Windows spawn verified'})
    print('Faults passed',flush=True)


if __name__=='__main__':
    mp.freeze_support()
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['prepare','trial','compare','production','suite','faults'])
    parser.add_argument('--mode',default='serial',choices=['serial','thread','process']);parser.add_argument('--workers',type=int,default=1)
    parser.add_argument('--set',default='small',choices=['small','representative','mainland','traditional','markdown','custom']);parser.add_argument('--label');parser.add_argument('--rounds',type=int,default=2)
    parser.add_argument('--reverse',action='store_true')
    parser.add_argument('--attribute',action='store_true');args=parser.parse_args()
    if args.action=='prepare':prepare()
    elif args.action=='compare':compare()
    elif args.action=='production':production()
    elif args.action=='suite':suite()
    elif args.action=='faults':faults()
    else:
        while (OUT/'foreground-session.flag').exists():
            save(OUT/'foreground-hold-reached.json',{'pid':os.getpid(),'action':args.action,'label':args.label,'time':time.time()})
            time.sleep(2)
        manifest='inputs.json' if args.set in ('small','representative') else 'scope-inputs.json'
        chars=json.loads((OUT/manifest).read_text('utf-8'))[args.set]
        if args.reverse:chars=list(reversed(chars))
        trial(args.mode,args.workers,chars,args.label,args.rounds,args.attribute)
