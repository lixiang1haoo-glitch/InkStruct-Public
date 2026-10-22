"""Reuse sealed scene/input harness with isolated worker and diagnostic hooks."""
import bootstrap as b
import sys

variant=sys.argv[1];backend=sys.argv[2];repeat=sys.argv[3]
worker_variant=variant.split('-')[0]
flags=sys.argv[4:]
sys.argv=[str(b.ROOT/'scripts/gpu_experiment/preview.py'),backend,repeat,*flags]
source=(b.ROOT/'scripts/gpu_experiment/preview.py').read_text(encoding='utf-8')
if 'steady' in variant:
    # An adjacent prefetch is intentionally outside the visible pages. Keep it
    # while visible tiles are ready; distant/urgent obsolete work still cancels.
    original_viewport=__import__('inkstruct.editor.continuous_preview',fromlist=['ContinuousPageCanvas']).ContinuousPageCanvas.viewport_changed
    from patches import stable_viewport_changed
    original_viewport.__globals__['ContinuousPageCanvas'].viewport_changed=stable_viewport_changed(original_viewport)
source=source.replace("label=f'{backend}-{repeat}'",f"label=f'{variant}-{{backend}}-{{repeat}}'")
source=source.replace("label=f'{backend}-open-{repeat}'",f"label=f'{variant}-{{backend}}-open-{{repeat}}'")
source=source.replace("label=f'{backend}-edit-{repeat}'",f"label=f'{variant}-{{backend}}-edit-{{repeat}}'")
if worker_variant!='old':
    source=source.replace("scripts/gpu_experiment/raster_worker.py","scripts/gpu_raster_followup/worker.py")
if worker_variant in ('cpu','cpu4'):
    source=source.replace("env.insert('QT_QPA_PLATFORM','windows')","env.insert('QT_QPA_PLATFORM','offscreen')")
import os
os.environ['INKSTRUCT_RASTER_VARIANT']=worker_variant
if 'external' in variant:
    source=source.replace('from monitor import Monitor','from outside_monitor import Monitor')
else:
    # Time the monitor itself: Windows process enumeration can hold the GIL.
    import monitor as monitor_module
    old_sample=monitor_module.Monitor.sample
    def audited_sample(self):
        import time
        start=time.perf_counter();old_sample(self)
        self.rows[-1]['sample_start']=start;self.rows[-1]['sample_end']=time.perf_counter()
    monitor_module.Monitor.sample=audited_sample
hooks="""
import gc
gc_events=[];gc_starts={}
def gc_trace(phase,info):
    now=time.perf_counter();generation=info['generation']
    if phase=='start':gc_starts[generation]=now
    else:
        gc_events.append({'start':gc_starts.pop(generation,now),'end':now,
                          'generation':generation,'collected':info.get('collected',0)})
gc.callbacks.append(gc_trace)
report['gc_events']=gc_events
report['variant']=FOLLOWUP_VARIANT
report['python_gc_threshold']=gc.get_threshold()
""".replace('FOLLOWUP_VARIANT',repr(variant))
source=source.replace("fence=ctypes.WinDLL('dwmapi').DwmFlush",hooks+"\nfence=ctypes.WinDLL('dwmapi').DwmFlush")
if 'prewarm' in variant:
    source=source.replace("open_start=start=time.perf_counter();loaded=load_package(",
        """open_start=start=time.perf_counter()
        warm_start=time.perf_counter()
        from inkstruct.editor.preview_process import worker_command
        command=worker_command(canvas._process.directory)
        canvas._process.process.start(command[0],command[1:])
        assert canvas._process.process.waitForStarted(2000)
        report['worker_prewarm_submit_ms']=(time.perf_counter()-warm_start)*1000
        start=time.perf_counter()
        loaded=load_package(""")
if 'gcpaused' in variant:
    source=source.replace("canvas.frames.clear()\n            start_stats", "gc.collect();gc.disable()\n            canvas.frames.clear()\n            start_stats")
    source=source.replace("if mode=='cold_traverse':\n                update_action", "gc.enable()\n            if mode=='cold_traverse':\n                update_action")
source=source.replace("report['capturing']=True;window.grab()", "gc.enable()\n        report['capturing']=True;window.grab()")
source=source.replace("canvas.stop_rendering();report['monitor']", "gc.enable();gc.callbacks.remove(gc_trace)\n        canvas.stop_rendering();report['monitor']")
source=source.replace("window.isVisible() and app.applicationState()==QtCore.Qt.ApplicationState.ApplicationActive,60",
    "window.isVisible() and app.applicationState()==QtCore.Qt.ApplicationState.ApplicationActive and foreground()==int(window.winId()),60")
exec(compile(source,str(b.ROOT/'scripts/gpu_experiment/preview.py'),'exec'),globals())
if 'error' in globals()['report']:raise SystemExit(2)
