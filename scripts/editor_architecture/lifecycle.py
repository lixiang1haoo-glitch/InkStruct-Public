import common as b
import multiprocessing as mp
from multiprocessing import shared_memory
from pathlib import Path
import pickle
import time
from PySide6 import QtGui
from ipc import worker as raster_worker
from process_layout import worker as layout_worker,restore_result
from inkstruct.document.package import load_package
from inkstruct.editor.mixed import build_markdown

def run():
    app=QtGui.QGuiApplication([]);ctx=mp.get_context('spawn');conn,child=ctx.Pipe()
    p=ctx.Process(target=raster_worker,args=(child,str(b.OUT/'ipc'),'gpu'));p.start();conn.recv()
    conn.send({'token':99901,'generation':1,'mode':'shm_lease','size':(630,891)})
    r=conn.recv();memory=shared_memory.SharedMemory(name=r['location'])
    image=QtGui.QImage(memory.buf,r['width'],r['height'],r['stride'],QtGui.QImage.Format.Format_ARGB32_Premultiplied)
    before=b.sha_bytes(image.constBits())
    conn.send({'crash':True});p.join(timeout=5);assert p.exitcode==23
    assert b.sha_bytes(image.constBits())==before
    del image;memory.close()
    try:unexpected=shared_memory.SharedMemory(name=r['location'])
    except FileNotFoundError:released=True
    else:unexpected.close();released=False
    assert released,'Mapped image owner not released after final reader closed'
    conn.close();conn,child=ctx.Pipe();event=ctx.Event()
    p=ctx.Process(target=layout_worker,args=(child,event,str(b.INPUT),str(b.OUT/'tmp'),True));p.start();conn.recv()
    loaded=load_package(b.INPUT);args=b.build_inputs(loaded)
    request={k:args[k] for k in ('session','revision','page','style','flow')}
    conn.send(dict(request,token=99902));time.sleep(.02);start=time.perf_counter();event.set()
    cancelled=conn.recv();cancel_ms=(time.perf_counter()-start)*1000
    assert cancelled.get('cancelled') is True,cancelled
    event.clear();conn.send(dict(request,token=99903));r=conn.recv();assert 'error' not in r,r
    path=Path(r['path']);result=restore_result(pickle.loads(path.read_bytes()),loaded.resolver);path.unlink()
    control=build_markdown(**args)
    assert result['snapshot']==control['snapshot']
    conn.send(None);p.join(timeout=5);assert p.exitcode==0
    b.save('lifecycle.json',{'gpu_worker_crash_mapped_image_stays_valid':True,
        'last_reader_close_releases_windows_mapping':released,'layout_mid_compute_cancel_ms':cancel_ms,
        'layout_after_cancel_exact_full_control':True,
        'expired_revision_policy':'Reject request token/generation before making QImage; native layout revision/key guards remain active'})
    print('Crash while mapped, final owner release and cancellation recovery verified')

if __name__=='__main__':mp.freeze_support();run()
