"""Actual editor interaction harness: visible paints, completed pixels, DWM fence.

Exercises Qt text transactions in the real MixedWindow. No application defaults,
user projects or release files are written. The isolated mode changes only layout
worker placement (persistent process) or tiles per scheduling batch.
"""
import common as b
import ctypes
import json
import multiprocessing as mp
import os
import pickle
import sys
import threading
import time
from dataclasses import replace
from PySide6 import QtCore,QtGui,QtWidgets
from inkstruct.editor import mixed,continuous_preview as cp
from inkstruct.editor.build_cache import MarkdownBuildCache
from inkstruct.theme import use_light_theme
from process_layout import worker,restore_result

def main():
    mode=sys.argv[1];run=int(sys.argv[2]);name=f'native-{mode}-{run}'
    if (b.OUT/'stop-native.flag').exists():raise SystemExit('Stopped before next native run; trial logs retained')
    if (b.OUT/(name+'.json')).exists():raise SystemExit('Existing run; choose new number')
    app=QtWidgets.QApplication([]);use_light_theme(app)
    requested=os.environ.get('INKSTRUCT_EDITOR_PREVIEW_BACKEND')
    if requested:
        if requested not in ('cpu','gpu'):raise ValueError('Unknown experimental backend')
        old_init=cp.PreviewProcess.__init__
        def init(process,parent=None):
            old_init(process,parent);process.backend=requested
            env=process.process.processEnvironment()
            env.insert('INKSTRUCT_PREVIEW_BACKEND',requested)
            env.insert('QT_QPA_PLATFORM','windows' if requested=='gpu' else 'offscreen')
            process.process.setProcessEnvironment(env)
        cp.PreviewProcess.__init__=init
    if mode=='warnings':
        from publication import warning_membership
        mixed.MixedWindow.current_font_warnings=warning_membership
    os.environ['INKSTRUCT_GPU_EXPERIMENT_OUT']=str(b.OUT)
    sys.path.append(str(b.ROOT/'scripts/gpu_raster_followup'))
    from outside_monitor import Monitor
    monitor=Monitor().start()
    trace=b.instrument();worker_rows=[];frames=[];heartbeats=[];pubs=[];inputs=[]
    from inkstruct.editor.app import ReviewWindow
    for klass,method in [(cp.ContinuousPageCanvas,'load_page'),(ReviewWindow,'refresh_list'),
                         (mixed.MixedWindow,'current_font_warnings')]:
        trace.wrap(klass,method,klass.__name__+'.'+method)
    fence=ctypes.WinDLL('dwmapi').DwmFlush
    foreground=ctypes.WinDLL('user32').GetForegroundWindow;foreground.restype=ctypes.c_void_p
    if mode in ('batch8','visible4'):
        import inspect,textwrap
        source=textwrap.dedent(inspect.getsource(cp.ContinuousPageCanvas._launch)).replace('tiles[:32]','tiles[:4]' if mode=='visible4' else 'tiles[:8]')
        ns=dict(vars(cp));exec(source,ns);cp.ContinuousPageCanvas._launch=ns['_launch']
        if mode=='visible4':cp.MAX_PAGE_IMAGE=0
    if mode=='idle':
        import inspect,textwrap
        source=textwrap.dedent(inspect.getsource(cp.ContinuousPageCanvas._launch))
        source=source.replace('if indices:',"if indices and time.perf_counter()-getattr(self,'_experiment_scroll_time',0)>.12:")
        ns=dict(vars(cp));exec(source,ns);cp.ContinuousPageCanvas._launch=ns['_launch']
        old_changed=cp.ContinuousPageCanvas.viewport_changed
        def changed(canvas,*args):
            canvas._experiment_scroll_time=time.perf_counter()
            if not hasattr(canvas,'_experiment_idle_timer'):
                canvas._experiment_idle_timer=QtCore.QTimer(canvas)
                canvas._experiment_idle_timer.setSingleShot(True)
                canvas._experiment_idle_timer.timeout.connect(canvas._queue)
            canvas._experiment_idle_timer.start(130)
            return old_changed(canvas,*args)
        cp.ContinuousPageCanvas.viewport_changed=changed
    original_paint=cp.ContinuousPageCanvas.paintEvent
    def paint(canvas,event):
        start=time.perf_counter();original_paint(canvas,event)
        frames.append({'start':start,'end':time.perf_counter(),'ms':(time.perf_counter()-start)*1000,
                       'ready':canvas.viewport_ready(),'snapshot':getattr(canvas.snapshot,'snapshot_id',None),
                       'foreground':foreground()==int(window.winId())})
    cp.ContinuousPageCanvas.paintEvent=paint
    original_render=cp.PreviewProcess.render
    original_receive=cp.PreviewProcess.read_result
    def submit(process,result,tiles):
        result['_experiment_submit']=time.perf_counter();return original_render(process,result,tiles)
    def receive(process):
        pending=process.pending;start=time.perf_counter();original_receive(process)
        if pending and process.pending is None:
            worker_rows.append({'receive_start':start,'receive_ms':(time.perf_counter()-start)*1000,
                'request_wall_ms':(time.perf_counter()-pending.get('_experiment_submit',start))*1000,
                'svg_ms':pending['svg_seconds']*1000,'raster_and_file_write_ms':pending['raster_seconds']*1000,
                'cancelled':pending['cancel_event'].is_set(),'error':pending.get('error')})
    cp.PreviewProcess.render=submit;cp.PreviewProcess.read_result=receive

    class Window(mixed.MixedWindow):
        def __init__(self):
            self.process_mode=mode in ('process','compact');self.proc=None;self.layout_transports=[]
            super().__init__()
            self.setWindowTitle(f'InkStruct architecture experiment {mode} {run}')
            if self.process_mode:
                ctx=mp.get_context('spawn');self.conn,child=ctx.Pipe()
                self.proc_cancel=ctx.Event()
                self.proc=ctx.Process(target=worker,args=(child,self.proc_cancel,str(b.INPUT),str(b.OUT/'tmp'),mode=='compact'))
                self.proc.start();self.proc_ready=False;self.proc_request=None;self.proc_serial=run*1000
                self.poll=QtCore.QTimer(self);self.poll.setInterval(3);self.poll.timeout.connect(self.receive_layout);self.poll.start()
        def start_recovery(self):self.recovery_timer.stop()
        def publish(self,result):
            start=time.perf_counter();super().publish(result)
            pubs.append({'start':start,'end':time.perf_counter(),'ms':(time.perf_counter()-start)*1000,
                         'accepted':result.get('revision')==self.revision,'error':result.get('error')})
        def build_arguments(self):
            start=time.perf_counter();args=super().build_arguments()
            inputs.append({'name':'build_arguments_source_clone','ms':(time.perf_counter()-start)*1000})
            return args
        def source_contents_changed(self,*args):
            start=time.perf_counter();super().source_contents_changed(*args)
            inputs.append({'name':'source_contents_changed','ms':(time.perf_counter()-start)*1000})
        def launch_layout(self):
            if not self.process_mode:return super().launch_layout()
            if self.closed or self.worker or self.source_error or not self.proc_ready:
                if not self.closed and not self.proc_ready:self.timer.start(30)
                return
            args=self.build_arguments();self.cancelled=args['cancelled'];self.proc_cancel.clear()
            self.proc_serial+=1;token=self.proc_serial
            from inkstruct.document.schema import digest
            self.current_key=digest([self.revision,self.mode,self.source_session.document_id])
            self.proc_request={'key':self.current_key,'revision':self.revision,'token':token,'start':time.perf_counter()}
            # Persistent immutable font catalog; do not transmit all glyphs on every keystroke.
            request={k:args[k] for k in ('session','revision','page','style','flow')}
            self.conn.send(dict(request,token=token));self.worker=True
        def receive_layout(self):
            if not self.conn.poll():return
            response=self.conn.recv()
            if response.get('ready'):
                self.proc_ready=True;self.layout_transports.append(response);return
            request=self.proc_request
            if request is None or response['token']!=request['token']:raise ValueError('Stale process token')
            start=time.perf_counter()
            result={'key':request['key'],'revision':request['revision']}
            if 'error' in response:result['error']=response['error']
            else:
                path=b.OUT/'tmp'/f"layout-{response['token']}.pickle"
                raw=path.read_bytes();read_end=time.perf_counter()
                payload=pickle.loads(raw);decode_end=time.perf_counter();path.unlink()
                result.update(restore_result(payload,self.resolver))
                response.update(read_ms=(read_end-start)*1000,decode_ms=(decode_end-read_end)*1000,
                                restore_ms=(time.perf_counter()-decode_end)*1000,
                                submit_to_receive_ms=(time.perf_counter()-request['start'])*1000)
            self.layout_transports.append(response);self.proc_request=None;self.publish(result)
        def schedule_layout(self):
            if self.process_mode and self.proc is not None and self.worker:self.proc_cancel.set()
            super().schedule_layout()

    window=Window();window.resize(1400,900);window.show()
    report={'mode':mode,'run':run,'harness_version':3,'window':[1400,900],'dpr':window.devicePixelRatioF(),
            'preview_backend_start':window.canvas._process.backend,
            'endpoint':'Qt actual paint with viewport_ready, followed by DwmFlush; not optical scanout',
            'scenarios':[],'frames':frames,'heartbeats':heartbeats,'input_phases':inputs,'publish':pubs,'raster_jobs':worker_rows}
    last=[time.perf_counter()]
    timer=QtCore.QTimer();timer.setInterval(16)
    def heartbeat():
        now=time.perf_counter();heartbeats.append({'time':now,'gap_ms':(now-last[0])*1000});last[0]=now
    timer.timeout.connect(heartbeat);timer.start()
    def pump(predicate,timeout=90):
        start=time.perf_counter();loop=QtCore.QEventLoop();poll=QtCore.QTimer();poll.setInterval(2)
        def tick():
            if predicate() or time.perf_counter()-start>timeout:loop.quit()
        poll.timeout.connect(tick);poll.start();loop.exec();poll.stop()
        if not predicate():raise TimeoutError(window.status.text()+str(window.canvas._errors))
    def ready():
        return window.snapshot is not None and window.worker is None and not window.timer.isActive() and window.canvas.viewport_ready()
    def settle():
        pump(ready)
        start=time.perf_counter();window.canvas.update()
        pump(lambda:frames and frames[-1]['end']>start and frames[-1]['ready'])
        fence()
    def navigate(page):
        window.page_picker.setValue(page);window.change_page()
    def edit_source(edit):
        from inkstruct.document.source import scalar_to_utf16
        old=window.source_session.source
        cursor=window.editor.textCursor()
        cursor.setPosition(scalar_to_utf16(window.buffer.display,window.buffer.raw_to_display(edit['start'])))
        cursor.setPosition(scalar_to_utf16(window.buffer.display,window.buffer.raw_to_display(edit['end'])),QtGui.QTextCursor.MoveMode.KeepAnchor)
        window.editor.setTextCursor(cursor);cursor.insertText(edit['text'])
        assert window.source_session.source==old[:edit['start']]+edit['text']+old[edit['end']:], 'UI edit scalar/UTF16 mismatch'
    def mark():return {'time':time.perf_counter(),'frames':len(frames),'heartbeats':len(heartbeats),'input':len(inputs),'publish':len(pubs),'raster':len(worker_rows),'trace':len(trace.rows),'cache':window.canvas.statistics()}
    def finish(kind,start,**extra):
        now=time.perf_counter()
        row={'name':kind,'wall_ms':(now-start['time'])*1000,'foreground':foreground()==int(window.winId()),
             'foreground_fraction_frames':sum(v.get('foreground',False) for v in frames[start['frames']:])/max(1,len(frames)-start['frames']),
             'frame_ms':b.summary([v['ms'] for v in frames[start['frames']:]]),
             'heartbeat_gap_ms':b.summary([v['gap_ms'] for v in heartbeats[start['heartbeats']:]]),
             'frames':len(frames)-start['frames'],'cache_before':start['cache'],'cache_after':window.canvas.statistics(),
             'phases':trace.aggregate(start['trace']),'input_rows':inputs[start['input']:],
             'publish_rows':pubs[start['publish']:],'raster_rows':worker_rows[start['raster']:],**extra}
        report['scenarios'].append(row);print(mode,run,kind,round(row['wall_ms'],1),flush=True)
    def scroll_sequence(kind,cold=False,background=False):
        start=mark();actions=[];bar=window.scroll.verticalScrollBar();base=bar.value()
        schedule=time.perf_counter()
        for i in range(60):
            deadline=schedule+i/60
            if time.perf_counter()<deadline:pump(lambda d=deadline:time.perf_counter()>=d)
            if cold:position=round(window.canvas.page_rect((i//5)%len(window.snapshot.pages)).top())
            else:position=base+round((i%20 if i%40<20 else 39-i%40)*8)
            act=time.perf_counter();bar.setValue(position);window.canvas.update()
            pump(lambda:frames and frames[-1]['end']>=act)
            before_fence=time.perf_counter();fence()
            actions.append({'input_lateness_ms':(act-deadline)*1000,
                            'visible_update_proxy_ms':(time.perf_counter()-act)*1000,
                            'paint_to_fence_ms':(time.perf_counter()-before_fence)*1000,
                            'complete_at_frame':frames[-1]['ready'],'time':act,
                            'foreground':foreground()==int(window.winId())})
        endscroll=time.perf_counter();settle()
        finish(kind,start,actions=actions,after_scroll_content_settle_ms=(time.perf_counter()-endscroll)*1000)
    try:
        pump(lambda:window.isVisible() and app.applicationState()==QtCore.Qt.ApplicationState.ApplicationActive and foreground()==int(window.winId()),60)
        report['screen']={'logical_dpi':window.screen().logicalDotsPerInch(),'refresh_hz':window.screen().refreshRate(),'name':window.screen().name()}
        start=mark();window.load_project_path(b.INPUT);settle();finish('cold_open',start)
        if mode=='admission':
            from admission import configure,install_weight_shortcut
            report['catalog_weight']=configure(window.build_cache,window.resolver)
            install_weight_shortcut(window.resolver)
        report['viewport']=[window.scroll.viewport().width(),window.scroll.viewport().height()]
        report['pages']=len(window.snapshot.pages);report['instances']=len(window.snapshot.fragments);report['diagnostics']=len(window.snapshot.diagnostics)
        edits=json.loads((b.OUT/'scenario-edits-v3.json').read_text(encoding='utf-8'))
        for edit in edits:
            navigate(6);settle();original=window.source_session.source
            start=mark();edit_source(edit)
            input_return=time.perf_counter();settle()
            finish('edit_'+edit['name'],start,input_return_ms=(input_return-start['time'])*1000,
                   snapshot_id=window.snapshot.snapshot_id,pages=len(window.snapshot.pages))
            window.source_history('undo');settle();assert window.source_session.source==original
        navigate(6);settle();scroll_sequence('warm_scroll')
        # Keep old snapshot visibly scrollable but selection/export disabled by original editor.
        edit=edits[1];edit_source(edit)
        report['stale_click_disabled_at_submit']=not window.canvas.isEnabled()
        assert report['stale_click_disabled_at_submit']
        window.timer.stop();window.launch_layout();scroll_sequence('scroll_during_relayout',background=True)
        report['stale_click_disabled']=not window.canvas.isEnabled() if window.worker else True
        window.source_history('undo');settle()
        window.canvas.preview_cache.clear();scroll_sequence('uncached_page_jumps',cold=True)
        start=mark();zooms=[]
        for i in range(12):
            old=len(frames);ts=time.perf_counter()
            window.canvas.scale=3*(1.0+(i%3)*.25);window.canvas.resize_page();window.canvas.viewport_changed()
            settle();zooms.append({'ms':(time.perf_counter()-ts)*1000,'frames':len(frames)-old})
        finish('continuous_zoom',start,actions=zooms)
        start=mark();zooms=[]
        for i in range(12):
            ts=time.perf_counter();window.canvas.scale=3*(1+(i%3)*.25)
            window.canvas.resize_page();window.canvas.viewport_changed();window.canvas.update()
            pump(lambda:frames and frames[-1]['end']>=ts)
            fence();zooms.append({'feedback_ms':(time.perf_counter()-ts)*1000,'ready':window.canvas.viewport_ready()})
        final=time.perf_counter();settle()
        finish('rapid_zoom',start,actions=zooms,final_complete_ms=(time.perf_counter()-final)*1000)
        navigate(6);settle()
        target=next((f,r) for f,r in window.canvas._geometry(5)
                    if f.text.isascii() and f.text.isdigit() and window.source_session.source[f.span.start:f.span.end]==f.text)
        selected=[];window.canvas.selected.connect(lambda f:selected.append(f.occurrence_id))
        point=target[1].center()
        event=QtGui.QMouseEvent(QtCore.QEvent.Type.MouseButtonPress,point,point,
             QtCore.Qt.MouseButton.LeftButton,QtCore.Qt.MouseButton.LeftButton,QtCore.Qt.KeyboardModifier.NoModifier)
        window.canvas.mousePressEvent(event);assert selected==[target[0].occurrence_id]
        report['selection_probe']={'occurrence_id':target[0].occurrence_id,'source_range':[target[0].span.start,target[0].span.end],
                                   'text':target[0].text,'page':6,'actual_qt_canvas_handler':True}
        if run>=20:
            window.canvas.scale=3;window.canvas.resize_page()
            for page in (5,6,7,6):
                navigate(page);settle()
                pump(lambda:window.canvas._job is None and not window.canvas._timer.isActive())
            scroll_sequence('warm_idle_scroll')
        report['layout_transports']=window.layout_transports
        report['preview_backend_final']=window.canvas._process.backend
        report['gpu_fallback_reason']=window.canvas._process.fallback_reason
        report['cache']=window.build_cache.statistics();report['foreground_all']=all(a.get('foreground',True) for s in report['scenarios'] for a in s.get('actions',[]))
        window.grab().save(str(b.OUT/(name+'.png')))
    except Exception:
        import traceback;report['error']=traceback.format_exc();print(report['error'],flush=True)
    finally:
        timer.stop();window.dirty=False;window.recovery_timer.stop();window.canvas.stop_rendering()
        report['monitor']=monitor.stop()
        if window.proc:
            if window.proc.is_alive():window.conn.send(None);window.proc.join(timeout=5)
            if window.proc.is_alive():window.proc.terminate();window.proc.join()
        b.save(name+'.json',report);window.close();app.quit()
    return 1 if 'error' in report else 0

if __name__=='__main__':mp.freeze_support();raise SystemExit(main())
