"""Completed CPU/GPU pixels: file vs shared memory copy vs retained mapped lease.

Worker completion precedes notification. Token/generation rejection, release,
crash and CPU retry are exercised. This is transport-stage evidence, not native
scroll performance, and mapping lifetime must remain attached to every image.
"""
import common as b
import inspect
import multiprocessing as mp
from multiprocessing import shared_memory
import os
from pathlib import Path
import pickle
import sys
import time
from PySide6 import QtGui

def worker(conn,directory,backend):
    app=QtGui.QGuiApplication([])
    from inkstruct.editor.preview_backend import CpuRaster,GpuRaster
    readbacks=[]
    old=GpuRaster.image
    # Timing the actual completed toImage + format conversion separately.
    source=inspect.getsource(old)
    import textwrap
    source=textwrap.dedent(source).replace('image = fbo.toImage().convertToFormat(QtGui.QImage.Format.Format_ARGB32_Premultiplied)',
                                          'image = completed_readback(fbo)')
    def completed_readback(fbo):
        ts=time.perf_counter();image=fbo.toImage().convertToFormat(QtGui.QImage.Format.Format_ARGB32_Premultiplied)
        readbacks.append((time.perf_counter()-ts)*1000);return image
    ns=dict(old.__globals__,completed_readback=completed_readback);exec(source,ns);GpuRaster.image=ns['image']
    start=time.perf_counter();raster=GpuRaster() if backend=='gpu' else CpuRaster()
    conn.send({'ready':True,'init_ms':(time.perf_counter()-start)*1000,'backend':backend})
    leases={}
    try:
        while True:
            request=conn.recv()
            if request is None:break
            if 'release' in request:
                memory=leases.pop(request['release']);memory.close();memory.unlink();conn.send({'released':request['release']});continue
            if request.get('crash'):os._exit(23)
            token=request['token'];readbacks.clear();start=time.perf_counter()
            raw=(Path(directory)/'ipc-input.svg').read_bytes();read=time.perf_counter()
            renderer=raster.svg(raw);parsed=time.perf_counter()
            w,h=request['size'];image=raster.image(renderer,w,h,1.5,0,0,round(w*1.5),round(h*1.5));done=time.perf_counter()
            size=image.sizeInBytes()
            if request['mode']=='file':
                path=Path(directory)/f'pixels-{token}.argb'
                with path.open('wb') as file:file.write(image.constBits())
                location=str(path)
            else:
                memory=shared_memory.SharedMemory(create=True,size=size)
                memory.buf[:size]=image.constBits();leases[token]=memory;location=memory.name
            written=time.perf_counter()
            conn.send({'token':token,'generation':request['generation'],'mode':request['mode'],'location':location,
                'width':image.width(),'height':image.height(),'stride':image.bytesPerLine(),'bytes':size,
                'read_svg_ms':(read-start)*1000,'parse_ms':(parsed-read)*1000,'completed_draw_readback_ms':(done-parsed)*1000,
                'gpu_readback_ms':sum(readbacks),'write_or_shm_copy_ms':(written-done)*1000})
    finally:
        for memory in leases.values():memory.close();memory.unlink()
        raster.close()

def main():
    app=QtGui.QGuiApplication([])
    tag='-'+sys.argv[1] if len(sys.argv)>1 else ''
    os.environ['INKSTRUCT_GPU_EXPERIMENT_OUT']=str(b.OUT)
    sys.path.append(str(b.ROOT/'scripts/gpu_raster_followup'))
    from outside_monitor import Monitor
    monitor=Monitor().start()
    from inkstruct.renderers.pages import page_svg
    with (b.OUT/'baseline-result-v2.pickle').open('rb') as file:result=pickle.load(file)
    raw=page_svg(result['snapshot'],5,debug=True).encode()
    directory=b.OUT/('ipc'+tag);directory.mkdir(exist_ok=False);(directory/'ipc-input.svg').write_bytes(raw)
    rows=[];tests={};initial=[];token=0;cpu_small_hash=None
    for backend in ('cpu','gpu'):
        ctx=mp.get_context('spawn');conn,child=ctx.Pipe();process=ctx.Process(target=worker,args=(child,str(directory),backend));process.start()
        initial.append(conn.recv());hashes={}
        for repeat in range(5):
            for size in ((630,891),(945,1337)):
                for mode in ('file','shm_copy','shm_lease'):
                    token+=1;start=time.perf_counter();conn.send({'token':token,'generation':1,'mode':mode,'size':size})
                    response=conn.recv();received=time.perf_counter()
                    assert response['token']==token and response['generation']==1
                    w,h,stride=response['width'],response['height'],response['stride']
                    assert w*h*4==response['bytes'] and stride==w*4
                    if mode=='file':
                        raw_pixels=Path(response['location']).read_bytes();read=time.perf_counter()
                        image=QtGui.QImage(raw_pixels,w,h,stride,QtGui.QImage.Format.Format_ARGB32_Premultiplied).copy()
                        Path(response['location']).unlink()
                    else:
                        memory=shared_memory.SharedMemory(name=response['location']);read=time.perf_counter()
                        image=QtGui.QImage(memory.buf,w,h,stride,QtGui.QImage.Format.Format_ARGB32_Premultiplied)
                        if mode=='shm_copy':image=image.copy()
                    ready=time.perf_counter()
                    digest=b.sha_bytes(image.constBits())
                    key=tuple(size)
                    if key in hashes:assert hashes[key]==digest
                    hashes[key]=digest
                    if mode!='file':
                        # Every QImage reference is destroyed before mapping close / owner release.
                        del image;memory.close();conn.send({'release':token});assert conn.recv()=={'released':token}
                    rows.append(dict(response,backend=backend,repeat=repeat,size=size,time=start,ready_time=ready,
                        submit_to_notification_ms=(received-start)*1000,map_or_read_ms=(read-received)*1000,
                        construct_copy_ms=(ready-read)*1000,end_to_ready_ms=(ready-start)*1000,
                        release_inclusive_ms=(time.perf_counter()-start)*1000,pixel_sha256=digest))
        # Stale/cancelled generation: inspect identity before any image construction.
        token+=1;conn.send({'token':token,'generation':0,'mode':'shm_copy','size':(630,891)})
        rejected=conn.recv();assert rejected['generation']!=1
        conn.send({'release':token});assert conn.recv()['released']==token
        tests[backend+'_stale_generation_rejected_without_mapping']=True
        token+=1;conn.send({'token':token,'generation':1,'mode':'shm_copy','size':(630,891)})
        cancelled=conn.recv();conn.send({'release':token});assert conn.recv()['released']==token
        tests[backend+'_cancelled_result_released_without_mapping']=True
        if backend=='gpu':
            assert cpu_small_hash is not None
            start=time.perf_counter();conn.send({'crash':True});process.join(timeout=5);assert process.exitcode==23
            conn.close();conn,child=ctx.Pipe();process=ctx.Process(target=worker,args=(child,str(directory),'cpu'));process.start();conn.recv()
            token+=1;conn.send({'token':token,'generation':1,'mode':'file','size':(630,891)})
            retry=conn.recv();assert b.sha(Path(retry['location']))==cpu_small_hash
            tests['gpu_crash_to_complete_cpu_retry_ms']=(time.perf_counter()-start)*1000
            Path(retry['location']).unlink()
        else:cpu_small_hash=hashes[(630,891)]
        conn.send(None);process.join(timeout=5);assert process.exitcode==0
    b.save('ipc'+tag+'-samples.json',{'samples':rows,'tests':tests,'initialization':initial,'monitor':monitor.stop(),
           'same_backend_all_transports_pixels_exact':True,'scope':'Transport-stage only; not foreground interaction'})
    print('IPC completed synchronization, exact pixels and lifetime/rejection/crash retry verified',flush=True)

if __name__=='__main__':mp.freeze_support();main()
