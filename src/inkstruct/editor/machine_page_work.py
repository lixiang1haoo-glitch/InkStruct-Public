"""Bounded, latest-request-only calculations for the plotter sidebar."""

from collections import OrderedDict
from dataclasses import dataclass
from math import dist

from PySide6 import QtCore

from ..plotter.export import route_page as svg_route_page
from ..plotter.physical import PaperRegistration, position_page
from ..plotter.write_session import ProgressFile, route_page as legacy_route_page


class PageWork:
    """Only the GUI timer reads results. Workers receive immutable page data."""

    def __init__(self, parent, executor):
        self.executor = executor
        self.cache = OrderedDict()
        self.timer = QtCore.QTimer(parent)
        self.timer.setInterval(20)
        self.timer.timeout.connect(self.poll)
        self.pending = self.future = None
        self.key = None

    def cancel(self):
        self.timer.stop()
        if self.future is not None:
            self.future.cancel()
        self.pending = self.future = None
        self.key = None

    def request(self, key, function, args, ready, failed, *, immediate=False):
        if key == self.key and (self.pending is not None or self.future is not None):
            return
        self.cancel()
        if key in self.cache:
            self.cache.move_to_end(key)
            ready(self.cache[key])
            return
        self.key, self.ready, self.failed = key, ready, failed
        if immediate:
            try:
                value = function(*args)
            except Exception as error:
                failed(error)
            else:
                self.store(value)
        else:
            self.pending = function, args
            self.timer.start()

    def store(self, value):
        self.cache[self.key] = value
        if len(self.cache) > 8:
            self.cache.popitem(last=False)
        self.ready(value)

    def poll(self):
        if self.pending is not None:
            function, args = self.pending
            self.pending = None
            self.future = self.executor.submit(function, *args)
        if self.future is None or not self.future.done():
            return
        self.timer.stop()
        future, self.future = self.future, None
        try:
            result = future.result()
        except Exception as error:
            self.failed(error)
        else:
            self.store(result)


def prepare_page(folder, document_id, page, background_id, device_id):
    journal = (ProgressFile.for_page(folder, document_id, page, background_id, device_id)
               if device_id and page.strokes else None)
    routed = svg_route_page(page, optimize=True).page if page.strokes else page
    legacy = legacy_route_page(page) if any(s.independent for s in page.strokes) else page
    return journal, routed, legacy


def travel_distance(endpoints, start):
    distance = 0.
    for first, last in endpoints:
        if start is not None:
            distance += dist(start, first)
        start = last
    return distance


@dataclass(frozen=True)
class PageTiming:
    # From each stroke's first point to the final endpoint, excluding its approach.
    remaining: tuple[float, ...]
    before: float
    after: float
    original_start: tuple[float, float]
    routed_start: tuple[float, float]


def measure_page(raw, routed, job):
    page = job or position_page(routed, PaperRegistration((0, 0)))
    remaining = [0.] * (len(page.strokes) + 1)
    after = 0.
    for i in reversed(range(len(page.strokes))):
        points = page.strokes[i].points
        gap = dist(points[-1], page.strokes[i + 1].points[0]) if i + 1 < len(page.strokes) else 0.
        ink = sum(dist(a, b) for a, b in zip(points, points[1:]))
        remaining[i] = ink + gap + remaining[i + 1]
        after += gap
    before = after
    original_start = routed_start = page.strokes[0].points[0]
    if routed is not raw:
        place = page.registration.place
        original_start = place(raw.strokes[0].points[0])
        before = travel_distance(((place(s.points[0]), place(s.points[-1])) for s in raw.strokes), None)
    return PageTiming(tuple(remaining), before, after, original_start, routed_start)
