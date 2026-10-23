"""Actual Qt SVG cache lifetimes, current hit maps and review overlays."""

import importlib.util
import os
import subprocess
import sys

import pytest


@pytest.mark.skipif(importlib.util.find_spec("PySide6") is None, reason="desktop extra missing")
def test_preview_cache_pixels_overlay_invalidation_and_eviction(tmp_path):
    program = r"""
import gc,time,weakref
from dataclasses import replace
from types import SimpleNamespace
from PySide6 import QtWidgets,QtTest
from inkstruct.assets.resolver import AssetResolver
from inkstruct.cache import BoundedCache
from inkstruct.document.editing import SourceSession
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.schema import PageProfile,Diagnostic,SourceSpan
from inkstruct.layout.blocks import layout_markdown
from inkstruct.editor import app as ui
from inkstruct.renderers import pages
app=QtWidgets.QApplication([])
s=layout_markdown(parse_markdown(SourceSession('12.50\n\n'*20)),AssetResolver(builtin_numbers=True),page=PageProfile(80,100,10))
assert len(s.pages)>2 and s.exportable
canvas=ui.PageCanvas();canvas.show()
canvas.load_page(s,0);app.processEvents()
first_renderer=canvas.renderer
first=canvas.grab().toImage()
canvas.load_page(s,1);canvas.load_page(replace(s,revision=50),0);app.processEvents()
assert canvas.renderer is first_renderer and canvas.snapshot.revision==50
assert canvas.grab().toImage()==first and canvas.preview_cache.statistics()['hits']==1
# Overlay marks are not baked into the cached SVG. Current fragments drive hit testing.
f=s.pages[0].fragments[0]
canvas.reviews={f.asset_id:SimpleNamespace(rating='bad')}
canvas.update();app.processEvents();marked=canvas.grab().toImage()
assert marked!=first
canvas.show_marks=False;canvas.update();app.processEvents()
assert canvas.grab().toImage()==first
selected=[];canvas.selected.connect(selected.append)
QtTest.QTest.mouseClick(canvas,ui.QtCore.Qt.MouseButton.LeftButton,pos=canvas.rect_for(f).center().toPoint())
assert selected and selected[-1]==f
canvas.selected_id=f.occurrence_id;canvas.update();app.processEvents()
assert canvas.grab().toImage()!=first
canvas.selected_id=None;canvas.reviews={}
# The same snapshot ID with new page content cannot reuse old graphics.
p=s.pages[0]
changed=replace(p,paint_ops=(replace(p.paint_ops[0],width_mm=.8),*p.paint_ops[1:]))
s2=replace(s,pages=(changed,*s.pages[1:]))
canvas.load_page(s2,0);assert canvas.renderer is not first_renderer
# Exportability/debug and page dimensions are independent invalidation inputs.
invalid=replace(s,diagnostics=(Diagnostic('test','test',SourceSpan(0,1)),))
try:pages.preview_key(invalid,0,debug=False)
except ValueError:pass
else:raise AssertionError('cache key bypassed finished export gate')
canvas.load_page(invalid,0);debug_renderer=canvas.renderer
assert debug_renderer is not first_renderer
canvas.load_page(s,0);assert canvas.renderer is first_renderer
canvas.load_page(replace(s,page_profile=PageProfile(90,100,10)),0)
assert canvas.renderer is not first_renderer
# A zoom uses vectors at the new size, retaining the same renderer.
r=canvas.renderer;canvas.scale=4;canvas.resize_page();assert canvas.renderer is r
# No QObject parent retains evicted native SVG objects.
canvas.preview_cache=BoundedCache(max_entries=1,max_weight=64*1024**2)
canvas.load_page(s,0);ref=weakref.ref(canvas.renderer)
canvas.load_page(s,1);gc.collect();assert ref() is None
assert canvas.preview_cache.statistics()['entries']==1
# Cache hit bypasses SVG serialization and updates the current snapshot pointer.
def forbidden(*a,**kw):raise AssertionError('unexpected SVG regeneration')
ui.page_svg=forbidden
canvas.load_page(replace(s,revision=77),1)
assert canvas.snapshot.revision==77
canvas.close()
print('Qt page-cache pixels, current overlays, hit tests and native eviction passed')
"""
    result = subprocess.run(
        [sys.executable, "-c", program, str(tmp_path)],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        capture_output=True,
        text=True,
        timeout=35,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(importlib.util.find_spec("PySide6") is None, reason="desktop extra missing")
def test_editor_exports_share_route_decisions_without_routing_on_input(tmp_path):
    program = r"""
import json,sys,time
from pathlib import Path
from PySide6 import QtWidgets,QtTest
from inkstruct.editor.mixed import MixedWindow
from inkstruct.plotter.options import ExportOptions
MixedWindow.configure_svg_export=lambda self,snapshot:(ExportOptions(tuple(range(len(snapshot.pages)))),self.optimize.isChecked())
from inkstruct.plotter import export
app=QtWidgets.QApplication([])
root=Path(sys.argv[1])
w=MixedWindow(source='|12|34|\n|---|---|\n|5.6|7.8|\n');w.show()
errors=[];w.message_error=lambda e:errors.append(str(e))
def ready():
 end=time.monotonic()+10
 while time.monotonic()<end:
  app.processEvents()
  if w.snapshot and w.canvas.isEnabled() and not w.timer.isActive() and not w.worker:
   w.recovery_timer.stop();return
  QtTest.QTest.qWait(10)
 raise AssertionError(w.status.text())
ready();w.optimize.setChecked(True)
assert w.build_cache.routes.statistics()['entries']==0
def save(name,callback):
 target=root/name
 QtWidgets.QFileDialog.getSaveFileName=staticmethod(lambda *a,**k:(str(target),''))
 callback()
 assert not errors,errors
 return {p.name:p.read_bytes() for p in target.iterdir()}
a=save('whole-a',w.export_machine)
assert w.build_cache.routes.statistics()['entries']>0
real=export.optimize_paths
def forbidden(*a,**kw):raise AssertionError('unexpected route search')
export.optimize_paths=forbidden
assert save('whole-b',w.export_machine)==a
export.optimize_paths=real
before=w.build_cache.routes.statistics().copy()
w.editor.insertPlainText('9');ready()
assert w.build_cache.routes.statistics()==before
w.dirty=False;w.close()
print('Qt document exports share route decisions; input does not route')
"""
    result = subprocess.run(
        [sys.executable, "-c", program, str(tmp_path)],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        capture_output=True,
        text=True,
        timeout=35,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
