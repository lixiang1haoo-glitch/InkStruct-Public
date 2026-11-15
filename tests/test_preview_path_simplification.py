import os
import subprocess
import sys
from threading import Event
import textwrap
from xml.etree import ElementTree as ET

import pytest

from inkstruct.document.cancellation import LayoutCancelled
from inkstruct.document.schema import PageProfile
from inkstruct.renderers.pages import page_svg, screen_page_svg
from inkstruct.renderers.preview_paths import simplify_stroke, tolerance_squared
from inkstruct.scene.schema import LayoutSnapshot, Page, PaintOp


def sample_snapshot(deviation=.015):
    near = ((1, 1), (1.5, 1 + deviation), (2, 1))
    return LayoutSnapshot(
        'snapshot', 'job', 'document', 1, PageProfile(20, 30, 1),
        (Page(0, (), (PaintOp('ink', near, .3), PaintOp('ink', ((3, 1), (4, 1)), .3),
                      PaintOp('dot', ((5, 1),), .3)),
              preview_ops=(PaintOp('guide', near, .2),)),),
        (), 'resources', 'markdown-test',
    )


@pytest.mark.parametrize(('spec', 'scale', 'point_count'), [
    ((60, 90, 1), 3, 2),
    ((120, 180, 1), 6, 2),
    ((60, 90, 2.5), 7.5, 3),
    ((120, 180, 2), 12, 3),
    ((120, 211, 1), 211 / 30, 3),
])
def test_screen_svg_applies_physical_tolerance_per_stroke(spec, scale, point_count):
    snapshot = sample_snapshot()
    assert tolerance_squared(snapshot.page_profile, spec) == pytest.approx((.1 / scale) ** 2)
    raw = page_svg(snapshot, 0)
    assert screen_page_svg(snapshot, 0, spec, accelerate=False) == raw
    root = ET.fromstring(screen_page_svg(snapshot, 0, spec, accelerate=True))
    ns = '{http://www.w3.org/2000/svg}'
    ink = [node for node in root if 'data-occurrence' in node.attrib]
    assert [node.get('data-occurrence') for node in ink] == ['guide', 'ink', 'ink', 'dot']
    for stroke in ink[:2]:
        points = stroke.get('points').split()
        assert len(points) == point_count
        assert points[0] == '1.000000,1.000000' and points[-1] == '2.000000,1.000000'
    assert len(ink[2].get('points').split()) == 2
    assert ink[3].tag == ns + 'circle' and ink[3].get('cx') == '5.000000'
    assert page_svg(snapshot, 0) == raw


def test_rdp_preserves_reversals_and_handles_cancellation():
    for points in (((0, 0), (2, 0), (1, 0)), ((0, 0), (2, 0), (0, 0))):
        assert simplify_stroke(points, .01) == points
    assert simplify_stroke(((0, 0), (0, 0), (0, 0)), .01) == ((0, 0), (0, 0))
    cancelled = Event()
    cancelled.set()
    with pytest.raises(LayoutCancelled):
        simplify_stroke(((0, 0), (1, 0), (2, 0)), .01, cancelled=cancelled)


def test_raster_workers_use_same_full_page_transform_for_tiles(tmp_path):
    from inkstruct.editor.continuous_preview import FULL, RasterWorker

    snapshot = sample_snapshot(.0015)
    render_key = ((2520, 3564, 1.5), 12, True)
    outputs = []
    for token, tiles in enumerate(((FULL,), ((0, 0), (1, 1))), 1):
        path = tmp_path / f'{token}.svg'
        job = RasterWorker(snapshot, 1, 0, render_key, tiles, token, path)
        results = []
        job.signals.finished.connect(results.append)
        job.run()
        assert 'error' not in results[0]
        outputs.append(path.read_bytes())
    assert outputs[0] == outputs[1]
    assert outputs[0] == screen_page_svg(snapshot, 0, render_key[0], accelerate=True).encode()
    assert b'1.500000,1.001500' in outputs[1]
    assert '1.500000,1.001500' not in screen_page_svg(snapshot, 0, (512, 512, 1.5), accelerate=True)


def run_qt(program, root):
    result = subprocess.run(
        [sys.executable, '-B', '-c', textwrap.dedent(program), str(root)],
        env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen', 'QT_SCALE_FACTOR': '1',
             'INKSTRUCT_LAYOUT_PREVIEW_HOME': str(root)},
        capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=65, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_acceleration_settings_redraw_live_and_preserve_export(tmp_path):
    run_qt(r'''
        import sys
        from pathlib import Path
        from time import monotonic, sleep
        from PySide6 import QtCore, QtGui, QtWidgets
        from inkstruct.editor.continuous_preview import FULL
        from inkstruct.editor.mixed import MixedWindow
        from inkstruct.global_defaults import GlobalDefaultsStore
        from inkstruct.plotter.adapters import plan_from_snapshot
        from inkstruct.plotter.export import export_plan
        from inkstruct.settings_dialog import SettingsDialog

        app = QtWidgets.QApplication([])
        qt = QtCore.QSettings
        qt.setDefaultFormat(qt.Format.IniFormat)
        qt.setPath(qt.Format.IniFormat, qt.Scope.UserScope, sys.argv[1])
        config = GlobalDefaultsStore.make_settings()
        key = GlobalDefaultsStore.PREVIEW_ACCELERATION_KEY
        config.setValue('preview_backend_v1', 'cpu')
        config.sync()
        assert not config.contains(key)

        w = MixedWindow(source='1234567890\n\n|1|2|\n|---|---|\n|3|4|')
        w.show()
        canvas = w.canvas

        def wait(condition):
            deadline = monotonic() + 15
            while not condition():
                app.processEvents()
                sleep(.005)
                assert monotonic() < deadline, (w.status.text(), canvas._errors)

        wait(lambda: w.snapshot is not None and w.worker is None and canvas.viewport_ready())
        assert canvas.render_acceleration
        snapshot, revision = w.snapshot, w.revision
        assert snapshot.exportable, snapshot.diagnostics
        root = Path(sys.argv[1])
        before = export_plan(plan_from_snapshot(snapshot), root / 'accelerated')
        on_key = canvas._key(0, FULL)

        dialog = SettingsDialog(w, category='preview')
        dialog.show()
        page = dialog.pages['preview']
        assert page.acceleration.text() == '渲染加速' and page.acceleration.isChecked()
        assert not dialog.apply_document.isVisible()
        page.acceleration.click()
        assert not canvas.render_acceleration and not config.contains(key)
        assert on_key != canvas._key(0, FULL)
        wait(lambda: canvas.preview_cache.get(canvas._key(0, FULL)) is not None)
        assert w.snapshot is canvas.snapshot is snapshot and w.revision == revision
        after = export_plan(plan_from_snapshot(w.snapshot), root / 'original')
        assert [(p.name, p.read_bytes()) for p in sorted(before.glob('*.svg'))] == [
            (p.name, p.read_bytes()) for p in sorted(after.glob('*.svg'))
        ]
        dialog.save_button.click()
        config.sync()
        assert config.value(key, True, bool) is False
        assert w.snapshot is snapshot and w.revision == revision and not w.timer.isActive()

        # Deliver an old completion after off -> on -> off -> on. The old
        # request's render key matches the current one, but it was cancelled.
        wait(lambda: canvas._job is None)
        canvas.preview_cache.clear()
        dialog = SettingsDialog(w, category='preview')
        dialog.show()
        page = dialog.pages['preview']
        deferred = []
        render = canvas._process.render
        canvas._process.render = lambda result, tiles: deferred.append(result)
        page.acceleration.click()
        wait(lambda: bool(deferred))
        old = deferred[0]
        page.acceleration.click()
        page.acceleration.click()
        assert old['render_key'] == canvas._render_key() and old['cancel_event'].is_set()
        stale = QtGui.QImage(1, 1, QtGui.QImage.Format.Format_ARGB32_Premultiplied)
        old['images'] = [(FULL, stale)]
        canvas._process.render = render
        canvas._process._finish(old)
        assert canvas.preview_cache.get(canvas._key(0, FULL)) is None
        wait(lambda: canvas.preview_cache.get(canvas._key(0, FULL)) is not None)
        assert canvas.preview_cache.get(canvas._key(0, FULL)).width() > 1
        dialog.reject()
        assert not canvas.render_acceleration and w.snapshot is canvas.snapshot is snapshot

        wait(lambda: canvas._job is None)
        old_key = canvas._key(0, FULL)
        dpr = canvas.devicePixelRatioF()
        canvas.devicePixelRatioF = lambda: 1.5 * dpr
        app.sendEvent(canvas, QtCore.QEvent(QtCore.QEvent.Type.DevicePixelRatioChange))
        assert canvas._key(0, FULL) != old_key
        wait(lambda: canvas.preview_cache.get(canvas._key(0, FULL)) is not None)
        zoom_key = canvas._key(0, FULL)
        w.zoom.setCurrentIndex((w.zoom.currentIndex() + 1) % w.zoom.count())
        assert canvas._key(0, FULL) != zoom_key
        assert w.snapshot is canvas.snapshot is snapshot and w.revision == revision
        w.dirty = False
        assert w.close()
    ''', tmp_path)
    run_qt(r'''
        import sys
        from PySide6 import QtCore, QtWidgets
        from inkstruct.editor.continuous_preview import ContinuousPageCanvas
        from inkstruct.editor.preview_settings import PreviewSettingsPage
        app = QtWidgets.QApplication([])
        qt = QtCore.QSettings
        qt.setDefaultFormat(qt.Format.IniFormat)
        qt.setPath(qt.Format.IniFormat, qt.Scope.UserScope, sys.argv[1])
        widget = ContinuousPageCanvas()
        page = PreviewSettingsPage()
        assert not widget.render_acceleration and not page.acceleration.isChecked()
        widget.stop_rendering()
    ''', tmp_path)
