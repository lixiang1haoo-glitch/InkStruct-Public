"""Persistent isolated layout worker, immutable resource catalog loaded once.

Private trusted experiment transport. Not a public document/pickle protocol.
"""
import common as b
import copy
import pickle
import time
import traceback
from pathlib import Path
from inkstruct.document.package import load_package
from inkstruct.editor.build_cache import MarkdownBuildCache
from inkstruct.editor.mixed import build_markdown

def worker(connection,cancel_event,input_path,directory,compact=False):
    started=time.perf_counter()
    loaded=load_package(Path(input_path))
    cache=MarkdownBuildCache()
    connection.send({'ready':True,'init_ms':(time.perf_counter()-started)*1000})
    trace=b.instrument()
    while True:
        request=connection.recv()
        if request is None:break
        token=request.pop('token')
        args=b.build_inputs(loaded)
        args.update(request,cancelled=cancel_event,cache=cache)
        start=time.perf_counter();index=len(trace.rows)
        try:
            result=build_markdown(**args)
            computed=time.perf_counter()
            loaded.resolver=result['resolver']
            payload={k:result[k] for k in ('document','snapshot')}
            payload['selections']=tuple(result['resolver'].selections.values())
            pack_start=time.perf_counter()
            if compact:
                from packed import pack_snapshot
                payload['snapshot']=pack_snapshot(payload['snapshot'])
            packed=time.perf_counter()
            raw=pickle.dumps(payload,protocol=5)
            encoded=time.perf_counter()
            path=Path(directory)/f'layout-{token}.pickle'
            path.write_bytes(raw)
            connection.send({'token':token,'path':str(path),'bytes':len(raw),
                             'compute_ms':(computed-start)*1000,'pack_ms':(packed-pack_start)*1000,
                             'pickle_ms':(encoded-packed)*1000,
                             'write_ms':(time.perf_counter()-encoded)*1000,'cache':cache.statistics(),
                             'phases':trace.aggregate(index)})
        except Exception:
            connection.send({'token':token,'error':traceback.format_exc(),
                             'cancelled':cancel_event.is_set()})

def restore_result(payload,resolver):
    resolved=copy.copy(resolver)
    resolved.selections={s.occurrence_id:s for s in payload.pop('selections')}
    from types import SimpleNamespace
    return dict(payload,resolver=resolved,asset_lookup={g.asset_id:g for pool in resolved.pools.values() for g in pool},
                provider=SimpleNamespace(assets={c:p[0] for c,p in resolved.pools.items()}))
