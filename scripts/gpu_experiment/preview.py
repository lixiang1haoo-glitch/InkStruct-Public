"""Visible native CPU vs GL composition, unmodified layout/cache/raster path.

No production monkeypatch survives this process. DwmFlush is a compositor fence,
not an optical display latency measurement. Qt paint and fence timings are separate.
"""
import bootstrap as b
import ctypes
import hashlib
import inspect
import json
import statistics
import sys
import textwrap
import time
from dataclasses import asdict

from PySide6 import QtCore, QtGui, QtWidgets, QtOpenGLWidgets
from inkstruct.document.package import load_package
from inkstruct.editor.mixed import build_markdown
from inkstruct.editor.build_cache import MarkdownBuildCache
from inkstruct.editor import continuous_preview as module
from inkstruct.renderers.pages import page_svg
from monitor import Monitor

backend=sys.argv[1]; repeat=int(sys.argv[2])
label=f'{backend}-{repeat}'
open_only='--open-only' in sys.argv
if open_only:label=f'{backend}-open-{repeat}'
edit_only='--edit-only' in sys.argv
if edit_only:label=f'{backend}-edit-{repeat}'
gl_comp=backend=='gpu'
if backend=='gpu-raster':
    import os
    from inkstruct.editor import preview_process
    os.environ['INKSTRUCT_GPU_EXPERIMENT_LABEL']=label
    preview_process.worker_command=lambda directory:[sys.executable,str(b.ROOT/'scripts/gpu_experiment/raster_worker.py'),str(directory)]
    original=module.PreviewProcess
    class GPUProcess(original):
        def __init__(self,parent=None):
            super().__init__(parent)
            env=self.process.processEnvironment();env.insert('QT_QPA_PLATFORM','windows')
            self.process.setProcessEnvironment(env)
    module.PreviewProcess=GPUProcess
app=QtWidgets.QApplication([]);app.setStyle('Fusion')
from inkstruct.theme import use_light_theme
use_light_theme(app)
monitor=Monitor().start()
report={'backend':backend,'repeat':repeat,'scenarios':[], 'dpr':app.devicePixelRatio(),
        'endpoint':'visible native Qt paint completion + DwmFlush; not optical presentation',
        'os_disk_cache':'not flushed; cold means new application/canvas/page cache',
        'window_size':[1400,900],'theme':'production forced light','scroll_input_target_hz':60}
fence=ctypes.WinDLL('dwmapi').DwmFlush
foreground=ctypes.WinDLL('user32').GetForegroundWindow
foreground.restype=ctypes.c_void_p

# Execute precisely the existing draw body on an external GL painter. Layout,
# raster bytes, geometry, diagnostics, selection, tile budgets are untouched.
source=textwrap.dedent(inspect.getsource(module.ContinuousPageCanvas.paintEvent))
source=source.replace('painter = QtGui.QPainter(self)','painter = self._external_painter')
ns=dict(vars(module));exec(source,ns);external_paint=ns['paintEvent']

class Canvas(module.ContinuousPageCanvas):
    def __init__(self):
        super().__init__();self.frames=[];self.overlay=None;self.epoch=0;self.drawn_epoch=-1
    def update(self,*args):
        super().update(*args)
        if self.overlay is not None:self.overlay.update()
    def paintEvent(self,event):
        if gl_comp:return
        start=time.perf_counter();super().paintEvent(event)
        self.frames.append({'start':start,'ms':(time.perf_counter()-start)*1000,'epoch':self.epoch})
        self.drawn_epoch=self.epoch

class Overlay(QtOpenGLWidgets.QOpenGLWidget):
    def __init__(self,canvas,parent):
        super().__init__(parent);self.canvas=canvas
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.swapped_epoch=-1;self.frameSwapped.connect(self.swapped)
    def initializeGL(self):
        ctx=self.context();report['gl']={'valid':ctx.isValid(),'format':str(ctx.format()),
            'paint_engine':None,'renderer':str(ctx.functions().glGetString(0x1F01)),
            'vendor':str(ctx.functions().glGetString(0x1F00))}
    def swapped(self):self.swapped_epoch=self.canvas.drawn_epoch
    def paintGL(self):
        c=self.canvas;start=time.perf_counter()
        painter=QtGui.QPainter(self);engine=str(painter.paintEngine().type())
        if not report.get('capturing',False):
            counts=report['gl'].setdefault('measured_paint_engines',{})
            counts[engine]=counts.get(engine,0)+1
        painter.fillRect(self.rect(),self.palette().window())
        painter.translate(c.pos())
        painter.setClipRect(c.rect())
        c._external_painter=painter
        external_paint(c,QtGui.QPaintEvent(c.viewport_rect().toAlignedRect().intersected(c.rect())))
        painter.end();self.context().functions().glFinish()
        c.frames.append({'start':start,'ms':(time.perf_counter()-start)*1000,'epoch':c.epoch,'paint_engine':engine})
        c.drawn_epoch=c.epoch

class Scroll(QtWidgets.QScrollArea):
    def resizeEvent(self,event):
        super().resizeEvent(event)
        if getattr(self,'overlay',None):self.overlay.setGeometry(self.viewport().rect())

window=QtWidgets.QWidget();window.setWindowTitle(f'InkStruct GPU experiment {label}')
window.resize(1400,900)
layout=QtWidgets.QHBoxLayout(window)
editor=QtWidgets.QPlainTextEdit();editor.setReadOnly(True);editor.setMaximumWidth(550)
layout.addWidget(editor)
scroll=Scroll();scroll.setWidgetResizable(False);layout.addWidget(scroll,1)
canvas=Canvas();scroll.setWidget(canvas);scroll.setAlignment(QtCore.Qt.AlignmentFlag.AlignHCenter)
if gl_comp:
    overlay=Overlay(canvas,scroll.viewport());canvas.overlay=overlay;scroll.overlay=overlay
    overlay.setGeometry(scroll.viewport().rect());overlay.show();overlay.raise_()
for bar in (scroll.verticalScrollBar(),scroll.horizontalScrollBar()):
    bar.valueChanged.connect(canvas.viewport_changed)
    if gl_comp:bar.valueChanged.connect(lambda *_:overlay.update())
window.show()

def pump(condition,timeout=90):
    loop=QtCore.QEventLoop();timer=QtCore.QTimer();timer.setInterval(2)
    start=time.perf_counter();state={'timeout':False}
    def tick():
        if condition():loop.quit()
        elif time.perf_counter()-start>timeout:state['timeout']=True;loop.quit()
    timer.timeout.connect(tick);timer.start();loop.exec();timer.stop()
    if state['timeout']:raise TimeoutError('visible preview timeout '+str(canvas.statistics())+str(canvas._errors))

def update_action(name,action,ready=False):
    canvas.epoch+=1;epoch=canvas.epoch;start=time.perf_counter();action()
    ready_at_action=canvas.viewport_ready()
    canvas.update()
    pump(lambda:canvas.drawn_epoch>=epoch and (not ready or canvas.viewport_ready()) and
         (not gl_comp or overlay.swapped_epoch>=epoch))
    # Cache readiness may become true before its newly painted image: force an
    # additional actual frame so first-ready never times a loading placeholder.
    if ready:
        canvas.epoch+=1;epoch=canvas.epoch;canvas.update()
        pump(lambda:canvas.drawn_epoch>=epoch and (not gl_comp or overlay.swapped_epoch>=epoch))
    paint_done=time.perf_counter();hr=fence();end=time.perf_counter()
    fg=foreground()==int(window.winId())
    row={'name':name,'action_to_paint_ms':(paint_done-start)*1000,
         'action_to_dwm_fence_ms':(end-start)*1000,'dwm_hresult':hr,'foreground':fg,
         'cache_ready':canvas.viewport_ready(),'cache_ready_at_action':ready_at_action,'time':start}
    report['scenarios'].append(row)
    return row

def main():
    try:
        pump(lambda:window.isVisible() and app.applicationState()==QtCore.Qt.ApplicationState.ApplicationActive,60)
        report['screen']={'name':window.screen().name(),'refresh':window.screen().refreshRate(),
                          'logical_dpi':window.screen().logicalDotsPerInch(),
                          'physical_dpi':window.screen().physicalDotsPerInch()}
        open_start=start=time.perf_counter();loaded=load_package(b.ROOT/'artifacts/preview_performance_0.1.12_20261018/input.inkdoc')
        report['package_load_ms']=(time.perf_counter()-start)*1000
        editor.setPlainText(loaded.session.source)
        cache=MarkdownBuildCache()
        def build(revision):
            return build_markdown(loaded.session,revision,loaded.resolver,'','',loaded.page,loaded.style,loaded.flow,None,cache)
        start=time.perf_counter();result=build(0);report['parse_layout_ms']=(time.perf_counter()-start)*1000
        snapshot=result['snapshot'];report['pages']=len(snapshot.pages);report['diagnostics']=len(snapshot.diagnostics)
        def load():
            canvas.load_page(snapshot,5);scroll.verticalScrollBar().setValue(round(canvas.page_rect(5).top()))
        row=update_action('first_visible_cold',load,True)
        report['open_to_visible_ms']=(time.perf_counter()-open_start)*1000
        report['page_svg_sha256']=[hashlib.sha256(page_svg(snapshot,i,debug=not snapshot.exportable).encode()).hexdigest() for i in range(len(snapshot.pages))]
        report['selection_hash']=hashlib.sha256(repr(sorted((k,repr(v)) for k,v in result['resolver'].selections.items())).encode()).hexdigest()
        report['geometry_hash']=hashlib.sha256(repr([(f.occurrence_id,f.selection_bounds) for p in snapshot.pages for f in p.fragments]).encode()).hexdigest()
        if open_only:
            report['foreground_fraction']=int(foreground()==int(window.winId()))
            report['cache']=canvas.statistics();return
        # Both a cached local scroll and crossing into uncached neighbouring pages.
        for mode in (() if edit_only else ('cold_traverse','warm_local')):
            base=scroll.verticalScrollBar().value()
            if mode=='warm_local':
                for offset in (0,228,0):
                    update_action('warmup_not_timed',lambda p=base+offset:scroll.verticalScrollBar().setValue(p),True)
                pump(lambda:canvas._job is None and canvas.viewport_ready())
            canvas.frames.clear()
            start_stats=canvas.statistics()
            schedule_start=time.perf_counter()
            for i in range(80):
                deadline=schedule_start+i/60
                if time.perf_counter()<deadline:pump(lambda d=deadline:time.perf_counter()>=d)
                lateness=(time.perf_counter()-deadline)*1000
                if mode=='cold_traverse':position=round(canvas.page_rect(5).top())+i*18
                else:position=base+(i%20 if i%40<20 else 39-i%40)*12
                row=update_action(mode,lambda p=position:scroll.verticalScrollBar().setValue(p))
                row['input_lateness_ms']=lateness;row['scheduled_time']=deadline
            report[mode]={'paint_ms':b.summary([f['ms'] for f in canvas.frames]),
                          'frames':list(canvas.frames),'cache_before':start_stats,'cache_after':canvas.statistics()}
            if mode=='cold_traverse':
                update_action('cold_traverse_content_settle',lambda:None,True)
        for scale in (() if edit_only else (4.5,3.,4.5,3.)):
            def zoom():
                canvas.scale=scale;canvas.resize_page()
                scroll.verticalScrollBar().setValue(round(canvas.page_rect(5).top()))
            update_action(f'zoom_{scale/3:.1f}',zoom,True)
        # Real stable-identity edit API, retaining prior resolver selections.
        start=time.perf_counter()
        if edit_only:
            import inkstruct.document.editing as editing
            fragment=next(f for f in snapshot.pages[5].fragments if f.text=='0' and loaded.session.source[f.span.start:f.span.end]=='0')
            pos=fragment.span.start
            old_new_id=editing.new_id;editing.new_id=lambda:hashlib.sha256(b'gpu-perf-visible-edit-0-to-1-v1').hexdigest()[:32]
            try:loaded.session.apply(pos,pos+1,'1')
            finally:editing.new_id=old_new_id
            report['edit']={'source_start':pos,'old':'0','new':'1','page':6,'deterministic_new_anchor':True}
        else:
            pos=loaded.session.source.find('\n');loaded.session.apply(pos,pos,' ')
        loaded.resolver=result['resolver'];result=build(1)
        report['edit_parse_layout_ms']=(time.perf_counter()-start)*1000
        update_action('edit_visible',lambda:canvas.load_page(result['snapshot'],5),True)
        report['edit_to_visible_ms']=(time.perf_counter()-start)*1000
        report['edit_geometry_hash']=hashlib.sha256(repr([(f.text,f.selection_bounds,f.asset_id) for p in result['snapshot'].pages for f in p.fragments]).encode()).hexdigest()
        before=loaded.resolver.selections;after=result['resolver'].selections
        assert all(after[k]==v for k,v in before.items() if k in after)
        report['unchanged_frozen_selections_equal']=True
        # Exercise actual selection path at a known selectable character centre.
        target=next((f,r) for f,r in canvas._geometry(5) if f.status not in ('space','line-break'))
        selected=[];canvas.selected.connect(lambda f:selected.append(f.occurrence_id))
        point=target[1].center()
        event=QtGui.QMouseEvent(QtCore.QEvent.Type.MouseButtonPress,point,point,
             QtCore.Qt.MouseButton.LeftButton,QtCore.Qt.MouseButton.LeftButton,QtCore.Qt.KeyboardModifier.NoModifier)
        canvas.mousePressEvent(event);assert selected==[target[0].occurrence_id]
        report['selection_probe']=selected
        report['capturing']=True;window.grab().save(str(b.OUT/f'preview-{label}.png'))
        report['cache']=canvas.statistics();report['viewport']=[scroll.viewport().width(),scroll.viewport().height()]
        report['foreground_fraction']=statistics.mean(r['foreground'] for r in report['scenarios'])
    except Exception:
        import traceback
        report['error']=traceback.format_exc();print(report['error'],flush=True)
    finally:
        canvas.stop_rendering();report['monitor']=monitor.stop();b.save(f'preview-{label}.json',report)
        print(label,{k:v for k,v in report.items() if k in ('error','parse_layout_ms','open_to_visible_ms','foreground_fraction')},flush=True)
        window.close();app.quit()
QtCore.QTimer.singleShot(1500,main)
app.exec()
