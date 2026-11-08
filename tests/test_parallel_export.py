"""Exact output and failure boundaries for page-only parallel export."""
import json
import multiprocessing as mp
import os
import threading
import time
from dataclasses import replace

import pytest

from inkstruct.cache import BoundedCache
from inkstruct.plotter.export import RouteOrder, export_plan, route_page
from inkstruct.plotter.parallel import (
    ExportCancelled,
    ExportControl,
    PageRouter,
    apply_order,
    worker_budget,
)
from inkstruct.plotter.schema import PlotPage, PlotPlan, PlotStroke


def fixture_plan():
    pages = []
    for page in range(3):
        strokes = tuple(PlotStroke(f'p{page}-s{i}',
                         ((2 + i % 26 * 3, 2 + i // 26 * 3), (3 + i % 26 * 3, 3 + i // 26 * 3)),
                         occurrence_id=f'o{page}:{i}', source_stroke_id=f'asset:{i}',
                         execution_domain='a' if i < 100 or i >= 200 else 'b') for i in range(260))
        pages.append(PlotPage(page, 100, 100, strokes))
    return PlotPlan('doc', 'snapshot', tuple(pages))


def crash_worker(connection):
    os._exit(17)


def sleeping_worker(connection):
    time.sleep(20)


def corrupt_worker(connection):
    index, page, _start = connection.recv()
    connection.send((index, RouteOrder((0,) * len(page.strokes), (False,) * len(page.strokes)), None))


class FaultContext:
    def __init__(self, target):
        self.ctx = mp.get_context('spawn')
        self.target = target

    def Pipe(self):
        return self.ctx.Pipe()

    def Process(self, **kwargs):
        return self.ctx.Process(**{**kwargs, 'target': self.target})


def contents(path):
    return {p.name: p.read_bytes() for p in path.iterdir()}


def test_parallel_output_exact_and_original_unchanged(tmp_path):
    plan = fixture_plan()
    before = repr(plan)
    serial = export_plan(plan, tmp_path/'serial', optimize=True, export_scope={'frozen': 'unchanged'})
    router = PageRouter(max_workers=2)
    parallel = export_plan(plan, tmp_path/'parallel', optimize=True, routing=router,
                           export_scope={'frozen': 'unchanged'})
    assert contents(serial) == contents(parallel)
    assert router.statistics['workers'] == 2 and router.statistics['fallback'] is None
    assert repr(plan) == before
    assert not any(p.pid in router.statistics['worker_pids'] for p in mp.active_children())


@pytest.mark.parametrize('target', [crash_worker, sleeping_worker, corrupt_worker])
def test_failure_falls_back_to_exact_serial_and_reaps_children(tmp_path, target):
    plan = fixture_plan()
    control = ExportControl()
    router = PageRouter(max_workers=2, timeout=.25, context=FaultContext(target))
    export_plan(plan, tmp_path/'actual', optimize=True, routing=router, control=control)
    export_plan(plan, tmp_path/'expected', optimize=True)
    assert router.statistics['fallback'] and contents(tmp_path/'actual') == contents(tmp_path/'expected')
    assert not mp.active_children()


def test_spawn_failure_falls_back(tmp_path):
    class Unavailable:
        def Pipe(self):
            raise OSError('spawn unavailable')
    router = PageRouter(context=Unavailable())
    export_plan(fixture_plan(), tmp_path/'out', optimize=True, routing=router)
    assert 'spawn unavailable' in router.statistics['fallback']


def test_cancel_active_workers_leaves_no_output(tmp_path):
    control = ExportControl()
    router = PageRouter(context=FaultContext(sleeping_worker))
    timer = threading.Timer(.4, control.cancel)
    timer.start()
    try:
        with pytest.raises(ExportCancelled):
            export_plan(fixture_plan(), tmp_path/'out', optimize=True, routing=router, control=control)
    finally:
        timer.join()
    assert not list(tmp_path.iterdir()) and not mp.active_children()


def test_cancel_while_large_payload_send_is_blocked(tmp_path):
    plan = fixture_plan()
    # Large enough to exceed pipe capacity while the child deliberately never reads.
    points = tuple((2 + i % 90, 2 + i % 80) for i in range(30000))
    plan = replace(plan, pages=tuple(replace(p, strokes=(replace(p.strokes[0], points=points), *p.strokes[1:]))
                                    for p in plan.pages))
    control = ExportControl()
    router = PageRouter(context=FaultContext(sleeping_worker))
    timer = threading.Timer(.4, control.cancel)
    timer.start()
    started = time.monotonic()
    try:
        with pytest.raises(ExportCancelled):
            export_plan(plan, tmp_path/'out', optimize=True, routing=router, control=control)
    finally:
        timer.join()
    assert time.monotonic()-started < 5
    assert not list(tmp_path.iterdir()) and not mp.active_children()


@pytest.mark.parametrize('stage', ['route', 'write'])
def test_cancel_before_publication_cleans_staging(tmp_path, stage):
    control = ExportControl()
    def progress(current, done, total):
        if current == stage:
            control.cancel()
    with pytest.raises(ExportCancelled):
        export_plan(fixture_plan(), tmp_path/'out', routing=PageRouter(max_workers=1),
                    control=control, progress=progress)
    assert not list(tmp_path.iterdir())


def test_publication_wins_late_cancel(tmp_path):
    control = ExportControl()
    export_plan(fixture_plan(), tmp_path/'out', control=control, routing=PageRouter())
    assert control.published and control.cancel() is False
    assert (tmp_path/'out/plotter.json').is_file()


def test_existing_destination_untouched(tmp_path):
    output = tmp_path/'out'
    output.mkdir()
    (output/'keep').write_text('user')
    with pytest.raises(FileExistsError):
        export_plan(fixture_plan(), output, routing=PageRouter())
    assert contents(output) == {'keep': b'user'}


def test_destination_appears_during_export(tmp_path):
    output = tmp_path/'out'
    def progress(*args):
        output.mkdir(exist_ok=True)
        (output/'keep').write_text('user')
    with pytest.raises(FileExistsError):
        export_plan(fixture_plan(), output, routing=PageRouter(), control=ExportControl(), progress=progress)
    assert contents(output) == {'keep': b'user'}
    assert list(tmp_path.iterdir()) == [output]


def test_cache_hit_never_starts_workers_and_uses_current_geometry(tmp_path):
    plan = fixture_plan()
    cache = BoundedCache(max_entries=10, max_weight=10**7)
    export_plan(plan, tmp_path/'first', optimize=True, route_cache=cache, routing=PageRouter())
    changed = replace(plan, snapshot_id='new', pages=tuple(replace(p, strokes=tuple(
        replace(s, points=(s.points[0], (5, 5), s.points[-1]), source_stroke_id='new:'+s.source_stroke_id)
        for s in p.strokes)) for p in plan.pages))
    router = PageRouter()
    export_plan(changed, tmp_path/'hit', optimize=True, routing=router, route_cache=cache)
    export_plan(changed, tmp_path/'uncached', optimize=True)
    assert router.statistics['cache_hits'] == 3 and router.statistics['workers'] == 0
    assert contents(tmp_path/'hit') == contents(tmp_path/'uncached')


@pytest.mark.parametrize('optimize,pages', [(False, (0, 2)), (True, (1,)), (True, (0, 2))])
def test_selection_order_and_optimization_setting(tmp_path, optimize, pages):
    plan = fixture_plan()
    export_plan(plan, tmp_path/'a', page_indices=pages, optimize=optimize)
    export_plan(plan, tmp_path/'b', page_indices=pages, optimize=optimize, routing=PageRouter())
    assert contents(tmp_path/'a') == contents(tmp_path/'b')
    manifest = json.loads((tmp_path/'b/plotter.json').read_text())
    assert [p['page_index'] for p in manifest['pages']] == list(pages)


@pytest.mark.parametrize('indices,reverse', [((0, 0), (False, False)), ((1, 0), (False, False)),
                                           ((0, 1), (False, 1))])
def test_invalid_or_cross_domain_decision_rejected(indices, reverse):
    p = fixture_plan().pages[0]
    p = replace(p, strokes=(p.strokes[0], replace(p.strokes[1], execution_domain='b')))
    with pytest.raises(ValueError):
        apply_order(p, RouteOrder(indices, reverse), (0, 0))


def test_empty_page_and_non_origin_match():
    p = PlotPage(0, 100, 100, ())
    assert next(PageRouter().routes((p,), optimize=True, start=(20, 30))) == route_page(p, optimize=True, start=(20, 30))


def test_memory_and_cpu_budget(monkeypatch):
    from inkstruct.plotter import parallel
    monkeypatch.setattr(parallel, 'available_memory', lambda: 600*1024**2)
    assert worker_budget(fixture_plan().pages) == 1
    monkeypatch.setattr(parallel, 'available_memory', lambda: 10*1024**3)
    assert 1 <= worker_budget(fixture_plan().pages) <= 3
