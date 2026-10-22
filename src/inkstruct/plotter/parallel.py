"""Bounded, spawn-safe page routing. Workers return decisions, never authority geometry."""
from __future__ import annotations

import math
import multiprocessing as mp
import os
import threading
import time
from dataclasses import replace

from .export import RoutedPage, RouteOrder, route_key, route_page
from .routing import travel_distance


class ExportCancelled(Exception):
    pass


class ExportControl:
    """Cancellation and atomic publication have one linearization point."""

    def __init__(self):
        self.cancelled = threading.Event()
        self.lock = threading.Lock()
        self.published = False

    def check(self):
        if self.cancelled.is_set():
            raise ExportCancelled("导出已取消；没有发布输出目录")

    def cancel(self):
        with self.lock:
            if self.published:
                return False
            self.cancelled.set()
            return True

    def publish(self, staging, output):
        with self.lock:
            self.check()
            if output.exists():
                raise FileExistsError(f"Output appeared during export: {output}")
            staging.rename(output)
            self.published = True


def _worker(connection):
    try:
        while True:
            request = connection.recv()
            if request is None:
                return
            position, page, start = request
            try:
                routed = route_page(page, optimize=True, start=start)
                connection.send((position, RouteOrder(routed.source_indices, routed.reversed_paths), None))
            except Exception as error:  # noqa: BLE001 -- parent repeats failures with the authoritative serial implementation.
                connection.send((position, None, f"{type(error).__name__}: {error}"))
    except (EOFError, BrokenPipeError):
        pass
    finally:
        connection.close()


def _exchange(item, request):
    # A pipe write can itself block if a child hangs before reading its input.
    # Keep both directions off the scheduler so cancellation/timeout can reap it.
    try:
        item['pipe'].send(request)
        item['response'] = item['pipe'].recv()
    except Exception as error:  # noqa: BLE001 -- relay transport failures to scheduler.
        # Do not retain a traceback holding PipeConnection's temporary memoryview.
        item['transport_error'] = f'{type(error).__name__}: {error}'
    finally:
        item['done'].set()


def available_memory():
    if os.name == 'nt':
        import ctypes
        class Status(ctypes.Structure):
            _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong),
                        *[(name, ctypes.c_ulonglong) for name in
                          ('total', 'available', 'page_total', 'page_available', 'virtual', 'virtual_available', 'extended')]]
        state = Status()
        state.length = ctypes.sizeof(state)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(state)):
            return state.available
    return None


def worker_budget(pages, limit=4):
    cpus = getattr(os, 'process_cpu_count', os.cpu_count)() or 1
    count = min(limit, len(pages), max(1, cpus - 2))
    memory = available_memory()
    if memory is not None and pages:
        # Includes interpreter, the immutable page and serialization temporaries.
        largest = max(sum(len(s.points) for s in p.strokes) for p in pages)
        per_worker = 96 * 1024**2 + largest * 192
        count = min(count, max(1, (memory - 512 * 1024**2) // per_worker))
    return max(1, count)


def apply_order(page, order, start):
    """Validate compact worker decisions against the original immutable page."""
    n = len(page.strokes)
    if (not isinstance(order, RouteOrder) or len(order.indices) != n or
            len(order.reversed_paths) != n or any(type(i) is not int for i in order.indices) or
            sorted(order.indices) != list(range(n)) or
            any(type(value) is not bool for value in order.reversed_paths)):
        raise ValueError('Invalid routing worker permutation')
    domains = []
    prior = object()
    group = -1
    for stroke in page.strokes:
        if stroke.execution_domain != prior:
            group += 1
            prior = stroke.execution_domain
        domains.append(group)
    if [domains[i] for i in order.indices] != domains:
        raise ValueError('Routing worker crossed execution domains')
    strokes = tuple(replace(page.strokes[i], points=page.strokes[i].points[::-1]) if reverse
                    else page.strokes[i] for i, reverse in zip(order.indices, order.reversed_paths, strict=True))
    before = travel_distance(tuple(s.points for s in page.strokes), start)
    after = travel_distance(tuple(s.points for s in strokes), start)
    if after > before:
        raise ValueError('Routing worker exceeded baseline travel')
    return RoutedPage(replace(page, strokes=strokes), order.indices, order.reversed_paths, before, after, start)


class PageRouter:
    def __init__(self, *, max_workers=4, timeout=120, context=None):
        self.max_workers = max_workers
        self.timeout = timeout
        self.context = context
        self.statistics = {'workers': 0, 'cache_hits': 0, 'fallback': None, 'worker_pids': []}

    def routes(self, pages, *, optimize, start, cache=None, control=None, progress=None):
        control = control or ExportControl()
        if len(start) != 2 or not all(math.isfinite(v) for v in start):
            raise ValueError('Plot start must have two finite coordinates')
        orders, missing = {}, []
        keys = {}
        for i, page in enumerate(pages):
            control.check()
            key = route_key(page, optimize, start) if cache is not None else None
            keys[i] = key
            order = cache.get(key) if cache is not None else None
            if order is None:
                missing.append(i)
            else:
                # Cache stores decisions only, including original execution domains.
                apply_order(page, order, start)
                orders[i] = order
                self.statistics['cache_hits'] += 1
        count = worker_budget([pages[i] for i in missing], self.max_workers)
        if optimize and len(missing) > 1 and count > 1 and sum(len(pages[i].strokes) for i in missing) >= 512:
            try:
                self._parallel(pages, missing, orders, start, count, control, progress)
            except ExportCancelled:
                raise
            except Exception as error:  # noqa: BLE001 -- includes spawn failures, broken pipes, worker crashes/timeouts/invalid decisions.
                self.statistics['fallback'] = f'{type(error).__name__}: {error}'
                if progress:
                    progress('fallback', len(orders), len(pages))
        for i in missing:
            control.check()
            if i not in orders:
                result = route_page(pages[i], optimize=optimize, start=start)
                orders[i] = RouteOrder(result.source_indices, result.reversed_paths)
            if cache is not None:
                cache.put((keys[i],), orders[i], 256 + len(pages[i].strokes) * 512)
            if progress:
                progress('route', len(orders), len(pages))
        for i, page in enumerate(pages):
            control.check()
            yield apply_order(page, orders[i], start)

    def _parallel(self, pages, missing, orders, start, count, control, progress):
        ctx = self.context or mp.get_context('spawn')
        workers = []
        pending = iter(missing)
        try:
            for _ in range(count):
                control.check()
                parent, child = ctx.Pipe()
                process = ctx.Process(target=_worker, args=(child,), daemon=True)
                item = {'process': process, 'pipe': parent, 'child': child, 'index': None}
                workers.append(item)
                process.start()
                child.close()
                self.statistics['worker_pids'].append(process.pid)
                self.statistics['workers'] += 1
            while True:
                control.check()
                active = False
                for item in workers:
                    process = item['process']
                    if item['index'] is None:
                        index = next(pending, None)
                        if index is not None:
                            item.update(index=index, started=time.monotonic(), done=threading.Event(),
                                        transport_error=None, response=None)
                            item['io'] = threading.Thread(target=_exchange, args=(item, (index, pages[index], start)), daemon=True)
                            item['io'].start()
                    if item['index'] is None:
                        continue
                    active = True
                    if item['done'].is_set():
                        item['io'].join()
                        if item['transport_error'] is not None:
                            raise RuntimeError(item['transport_error'])
                        index, order, error = item['response']
                        if index != item['index'] or error:
                            raise RuntimeError(error or 'Routing response identity mismatch')
                        apply_order(pages[index], order, start)
                        orders[index] = order
                        item['index'] = None
                        if progress:
                            progress('route', len(orders), len(pages))
                    elif not process.is_alive():
                        raise RuntimeError(f'Routing worker exited: {process.exitcode}')
                    elif time.monotonic() - item['started'] > self.timeout:
                        raise TimeoutError('Routing worker timed out')
                if not active:
                    break
                control.cancelled.wait(0.02)
        finally:
            # These processes belong exclusively to this export, never another job.
            for item in workers:
                item['child'].close()
                process = item['process']
                if process.pid is not None:
                    if process.is_alive():
                        process.terminate()
                    process.join(timeout=2)
                    if process.is_alive():
                        process.kill()
                        process.join(timeout=2)
                    process.close()
                item['pipe'].close()
                if item.get('io') is not None:
                    item['io'].join(timeout=2)
