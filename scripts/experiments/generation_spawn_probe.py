"""Minimal frozen Windows spawn probe; NOT a self-contained InkStruct build.

Loads the explicitly supplied, unchanged project source/runtime. This tests
freeze_support and worker isolation, not production bundle resource discovery.
"""
import concurrent.futures
import hashlib
import importlib
import json
import multiprocessing
import os
from pathlib import Path
import sys


def setup(root):
    root=Path(root)
    for key in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS'):os.environ[key]='1'
    sys.path[:0]=[str(root/'scripts/experiments'),str(root/'src'),str(root/'.venv/Lib/site-packages')]
    generation=importlib.import_module('inkstruct.generation_workflow')
    generation.resources=lambda:root
    experiment=importlib.import_module('generation_parallel')
    experiment.initialize()


def calculate(job):
    experiment=importlib.import_module('generation_parallel')
    return {**experiment.compute(job),'sys_frozen':bool(getattr(sys,'frozen',False)),
            'executable':sys.executable}


def main():
    root=Path(sys.argv[1]).resolve()
    output=Path(sys.argv[2]).resolve()
    output.mkdir(exist_ok=False)
    with concurrent.futures.ProcessPoolExecutor(2,mp_context=multiprocessing.get_context('spawn'),
            initializer=setup,initargs=(str(root),)) as pool:
        results=list(pool.map(calculate,[(c,str(output),None) for c in '孔正']))
    experiments=Path(os.environ.get('INKSTRUCT_GENERATION_EXPERIMENT_OUT',str(root/'artifacts/generation_sets_parallel_20261022')))
    baseline=json.loads((experiments/'small-serial-1/round-0/summary.json').read_text('utf-8'))['results']
    expected={row['character']:row for row in baseline}
    assert all(r['sys_frozen'] and r['payload_hash']==expected[r['character']]['payload_hash'] for r in results)
    (output/'verification.json').write_text(json.dumps({'passed':True,'results':results,
        'scope':'frozen console harness, explicit external project source and app site-packages; NOT production bundle acceptance'},ensure_ascii=False,indent=2),'utf-8')
    print('Frozen harness spawn and exact payloads passed',flush=True)


if __name__=='__main__':
    multiprocessing.freeze_support();main()
