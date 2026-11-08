"""Cold backend initialization/JIT/H2D measured independently of warm batches."""
import bootstrap as b
import os
import sys
import time
from fitting import GPUFit,pack_q,cpu_fit,packed_cpu
from candidates import prepare
from monitor import Monitor
import numpy as np

rep=int(sys.argv[1]);cache=b.OUT/f'cold-kernel-cache-{rep}'
assert not cache.exists();cache.mkdir();os.environ['CUPY_CACHE_DIR']=str(cache)
monitor=Monitor().start();repo,single,report=prepare()
graph=repo.get('正');target=graph.strokes[-1].median;d=single.descriptors['heng']
start=time.perf_counter();gpu=GPUFit();report['gpu_context_import_s']=time.perf_counter()-start
records=[]
for i in range(11):
    out,times=gpu.batch(d,pack_q(target)[None,:]);t=time.perf_counter();expected=packed_cpu(cpu_fit(d,target))
    assert np.allclose(out[0],expected,rtol=1e-11,atol=1e-12)
    times['cpu_verify_s']=time.perf_counter()-t;records.append(times)
report['batches']=records;report['candidates']=len(d['length']);report['queries']=1
report['cupy_memory_pool_used_bytes']=gpu.cp.get_default_memory_pool().used_bytes()
report['cupy_memory_pool_cached_bytes']=gpu.cp.get_default_memory_pool().total_bytes()
report['monitor']=monitor.stop();b.save(f'cold-fit-{rep}.json',report)
print('cold context',report['gpu_context_import_s'],'first',records[0],flush=True)
