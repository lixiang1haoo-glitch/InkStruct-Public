"""Continuous page geometry, lazy pixels and stable source/export semantics."""
import os
import subprocess
import sys

import pytest

PROGRAM = r'''
import sys,time
from dataclasses import replace
from PySide6 import QtCore,QtGui,QtSvg,QtTest,QtWidgets
from inkstruct.editor.mixed import MixedWindow
from inkstruct.editor import continuous_preview as preview
from inkstruct.cache import BoundedCache
from inkstruct.assets.resolver import AssetResolver
from inkstruct.document.editing import SourceSession
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.schema import PageProfile
from inkstruct.layout.blocks import layout_markdown
from inkstruct.plotter.adapters import plan_from_snapshot
from inkstruct.plotter.svg import page_svg
from inkstruct.renderers.pages import page_svg as screen_svg

app=QtWidgets.QApplication([]);app.setStyle('Fusion')
def wait(predicate):
    if predicate():return
    loop=QtCore.QEventLoop();poll=QtCore.QTimer();poll.setInterval(5)
    expired=[];deadline=QtCore.QTimer();deadline.setSingleShot(True)
    deadline.timeout.connect(lambda:(expired.append(1),loop.quit()))
    poll.timeout.connect(lambda:loop.quit() if predicate() else None)
    poll.start();deadline.start(15000);loop.exec();poll.stop();deadline.stop()
    assert not expired,'preview did not finish'
def settle(canvas):
    wait(lambda:canvas.viewport_ready() and not canvas._job and not canvas._timer.isActive())
def pause(ms):
    loop=QtCore.QEventLoop();QtCore.QTimer.singleShot(ms,loop.quit);loop.exec()

case=sys.argv[1]
if case=='navigation':
    w=MixedWindow(source='12.34\n\n'*160);w.resize(1100,720);w.show()
    wait(lambda:w.snapshot and not w.worker and not w.timer.isActive())
    w.recovery_timer.stop();settle(w.canvas)
    s=w.snapshot;raw=w.buffer.raw;revision=w.revision;choices=w.resolver.selection_records()
    svg=[page_svg(p) for p in plan_from_snapshot(s).pages]
    c=w.canvas
    assert len(s.pages)>5 and c.height()>c.page_size()[1]*len(s.pages)
    assert c.render_jobs<=3,'offscreen pages were eagerly rendered'
    boundary=c.page_rect(1).top()-w.scroll.viewport().height()/2
    w.scroll.verticalScrollBar().setValue(round(boundary));app.processEvents();settle(c)
    visible=c.viewport_rect()
    assert visible.intersects(c.page_rect(0)) and visible.intersects(c.page_rect(1))
    assert w.page_picker.value()==c.page_at(visible.center().y())+1
    w.page_picker.setValue(5);app.processEvents();settle(c)
    assert c.viewport_rect().intersects(c.page_rect(4))
    f=next(f for f in s.pages[4].fragments if f.asset_id and f.text)
    point=c.rect_for(f).center().toPoint()
    w.scroll.ensureVisible(point.x(),point.y());app.processEvents()
    QtTest.QTest.mouseClick(c,QtCore.Qt.MouseButton.LeftButton,pos=point)
    assert w.editor.textCursor().selectedText()==f.text
    assert w.scroll.viewport().rect().contains(c.mapTo(w.scroll.viewport(),point))
    settle(c)
    # Revision-only snapshots with identical immutable pages keep their pixels;
    # an edit elsewhere must not flash a loading sheet here.
    jobs=c.render_jobs
    c.load_page(replace(s,revision=s.revision+1),4);app.processEvents();settle(c)
    assert c.render_jobs==jobs
    c.load_page(s,4);app.processEvents();settle(c)
    # Marks and selections are a separate layer, so toggling them doesn't
    # reserialize SVG or invalidate pixels, hit maps or frozen resources.
    c.selected_id=None;c.reviews={};c.update();app.processEvents()
    clean=w.scroll.viewport().grab().toImage();jobs=c.render_jobs
    from types import SimpleNamespace
    c.reviews={f.asset_id:SimpleNamespace(rating='bad')};c.update();app.processEvents()
    assert w.scroll.viewport().grab().toImage()!=clean
    c.show_marks=False;c.update();app.processEvents()
    assert w.scroll.viewport().grab().toImage()==clean and c.render_jobs==jobs
    top=c.page_rect(2).top()+100
    w.scroll.verticalScrollBar().setValue(round(top));app.processEvents()
    old=c.viewport_rect();i=c.page_at(old.top());fraction=(old.top()-c.page_rect(i).top())/c.page_rect(i).height()
    w.zoom.setCurrentIndex(2);app.processEvents();settle(c)
    assert abs(c.viewport_rect().top()-(c.page_rect(i).top()+fraction*c.page_rect(i).height()))<=2
    vp=w.scroll.viewport();pos=QtCore.QPointF(180,200)
    def wheel(delta, ctrl=True, widget=vp):
        event=QtGui.QWheelEvent(pos,QtCore.QPointF(widget.mapToGlobal(pos.toPoint())),
            QtCore.QPoint(),QtCore.QPoint(0,delta),QtCore.Qt.NoButton,
            QtCore.Qt.ControlModifier if ctrl else QtCore.Qt.NoModifier,
            QtCore.Qt.NoScrollPhase,False)
        app.sendEvent(widget,event);app.processEvents()
    def anchor():
        at=c.viewport_rect().topLeft()+pos;index=c.page_at(at.y());page=c.page_rect(index)
        return index,(at.x()-page.left())/page.width(),(at.y()-page.top())/page.height()
    before=anchor()
    wheel(60);assert w.zoom.currentText()=='150%'
    wheel(60);assert w.zoom.currentText()=='200%'
    after=anchor();assert before[0]==after[0] and max(abs(a-b) for a,b in zip(before[1:],after[1:]))<.004
    wheel(120);assert w.zoom.currentText()=='200%' and anchor()==after
    wheel(-120,False);assert w.zoom.currentText()=='200%' and anchor()!=after
    wheel(-480);assert w.zoom.currentText()=='75%'
    wheel(-120);assert w.zoom.currentText()=='75%'
    wheel(120,widget=w.editor.viewport());assert w.zoom.currentText()=='75%'
    assert w.snapshot is s and w.revision==revision and w.buffer.raw==raw
    assert w.resolver.selection_records()==choices
    assert [page_svg(p) for p in plan_from_snapshot(s).pages]==svg
    assert c.preview_cache.weight<=c.preview_cache.max_weight
    w.dirty=False;w.close()
elif case=='stale':
    s=layout_markdown(parse_markdown(SourceSession('12.34\n\n'*60)),AssetResolver(builtin_numbers=True))
    c=preview.ContinuousPageCanvas();scroll=QtWidgets.QScrollArea();scroll.resize(650,600)
    scroll.setWidget(c);scroll.show()
    real=c._process.render;held=[]
    c._process.render=lambda result,tiles:held.append(result)
    c.load_page(s,0);wait(lambda:bool(held))
    old=held[0];generation=c._generation
    c.load_page(replace(s,revision=99),0)
    assert c._generation==generation+1
    red=QtGui.QImage(8,8,QtGui.QImage.Format.Format_ARGB32_Premultiplied);red.fill(QtCore.Qt.GlobalColor.red)
    old['images']=[(preview.FULL,red)]
    c._completed(old)
    assert c.preview_cache.statistics()['entries']==0
    c._process.render=real;settle(c)
    assert not c._errors and c.snapshot.revision==99
    # A stopped process is replaceable, and an unavailable companion reports
    # a display error without changing source or enabling an invalid export.
    c.stop_rendering();scroll.close()
elif case=='tiling':
    s=layout_markdown(parse_markdown(SourceSession('12.34\n\n'*100)),AssetResolver(builtin_numbers=True),page=PageProfile(80,100,10))
    c=preview.ContinuousPageCanvas();scroll=QtWidgets.QScrollArea();scroll.resize(500,280)
    scroll.setWidget(c);scroll.show()
    c.preview_cache=BoundedCache(max_entries=2,max_weight=20*1024**2)
    c.load_page(s,0);settle(c)
    scroll.verticalScrollBar().setValue(round(c.page_rect(1).top()-100));app.processEvents();settle(c)
    jobs=c.render_jobs;pause(120)
    assert c.render_jobs==jobs,'neighbour prefetch evicted visible pages in a loop'
    # Force bounded physical pixel tiles and compare a complete page against
    # the same QSvgRenderer's reference pixels, including a 512px seam.
    c.preview_cache=BoundedCache(max_entries=64,max_weight=32*1024**2)
    preview.MAX_PAGE_IMAGE=1000
    scroll.resize(500,500);scroll.verticalScrollBar().setValue(0)
    c.load_page(replace(s,revision=2),0);app.processEvents();settle(c)
    width,height,dpr=c._spec();pw,ph=__import__('math').ceil(width*dpr),__import__('math').ceil(height*dpr)
    reference=QtGui.QImage(pw,ph,QtGui.QImage.Format.Format_ARGB32_Premultiplied)
    reference.setDevicePixelRatio(dpr);reference.fill(QtCore.Qt.GlobalColor.white)
    painter=QtGui.QPainter(reference)
    QtSvg.QSvgRenderer(screen_svg(s,0,debug=not s.exportable).encode()).render(painter,QtCore.QRectF(0,0,width,height));painter.end()
    actual=QtGui.QImage(pw,ph,QtGui.QImage.Format.Format_ARGB32_Premultiplied)
    actual.setDevicePixelRatio(dpr);actual.fill(QtCore.Qt.GlobalColor.white)
    painter=QtGui.QPainter(actual)
    for tile in c._tiles(0,c.page_rect(0)):
        image=c.preview_cache.get(c._key(0,tile));assert image is not None
        painter.drawImage(QtCore.QPointF(tile[0]*preview.TILE/dpr,tile[1]*preview.TILE/dpr),image)
    painter.end();assert actual==reference
    assert c.preview_cache.weight<=c.preview_cache.max_weight
    directory=c._process.directory;c.stop_rendering();scroll.close()
    assert not directory.exists(),'private raster files survived close'
elif case=='failure':
    from inkstruct.editor import preview_process
    def missing(directory):raise ValueError('fixture missing preview companion')
    preview_process.worker_command=missing
    s=layout_markdown(parse_markdown(SourceSession('缺字')),AssetResolver(builtin_numbers=True))
    assert not s.exportable
    c=preview.ContinuousPageCanvas();scroll=QtWidgets.QScrollArea();scroll.resize(600,500)
    scroll.setWidget(c);scroll.show();c.load_page(s,0)
    wait(lambda:bool(c._errors))
    assert c.snapshot is s and not c.snapshot.plotter_exportable
    assert 'fixture missing' in str(c._errors) and c._process.pending is None
    c.stop_rendering();scroll.close()
else:raise AssertionError(case)
print(case,'passed')
'''


@pytest.mark.parametrize('scale', ['1', '1.5', '2'])
@pytest.mark.parametrize('case', ['navigation', 'stale', 'tiling', 'failure'])
def test_continuous_preview(case, scale):
    result = subprocess.run([sys.executable, '-c', PROGRAM, case],
                            env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen',
                                 'QT_SCALE_FACTOR': scale},
                            capture_output=True, text=True, timeout=40, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
