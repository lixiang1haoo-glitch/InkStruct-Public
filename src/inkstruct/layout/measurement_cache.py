"""Scoped, dependency-checked measurements; source identities are never rebased."""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, fields, is_dataclass
from functools import wraps
from inspect import signature
from sys import getsizeof

from ..assets.symbol_provider import ResolvedGlyph
from ..cache import BoundedCache
from ..document.cancellation import check_cancel

MEASUREMENT_VERSION = "source-exact-measurement-v2"
_active = ContextVar("inkstruct_measurement_cache", default=None)


class MeasurementCache(BoundedCache):
    def __init__(self, *, max_entries=4096, max_weight=64 * 1024**2):
        super().__init__(max_entries=max_entries, max_weight=max_weight)
        self.reused = self.recomputed = self.invalidated = 0
        self._resources = {}

    @staticmethod
    def resources(value):
        return {id(g): g for _, g, _ in value.dependencies}

    def _remove(self, primary):
        resources = self.resources(self._entries[primary].value)
        super()._remove(primary)
        for identity in resources:
            glyph, count, weight = self._resources[identity]
            if count == 1:
                self.weight -= weight
                del self._resources[identity]
            else:
                self._resources[identity] = (glyph, count - 1, weight)

    def put(self, keys, value, weight):
        keys = tuple(dict.fromkeys(keys))
        if not keys or weight < 0:
            raise ValueError("Cache entry needs keys and nonnegative weight")
        with self._lock:
            for key in keys:
                if key in self._aliases:
                    self._remove(self._aliases[key])
            resources = self.resources(value)
            weights = {
                identity: self._resources[identity][2]
                if identity in self._resources
                else _weight(glyph) + 256
                for identity, glyph in resources.items()
            }
            if weight + sum(weights.values()) > self.max_weight:
                self.skipped += 1
                return
            while self._entries and (
                len(self._entries) >= self.max_entries
                or self.weight
                + weight
                + sum(w for k, w in weights.items() if k not in self._resources)
                > self.max_weight
            ):
                self._remove(next(iter(self._entries)))
                self.evictions += 1
            for identity, glyph in resources.items():
                if identity in self._resources:
                    old, count, size = self._resources[identity]
                    self._resources[identity] = (old, count + 1, size)
                else:
                    self._resources[identity] = (glyph, 1, weights[identity])
                    self.weight += weights[identity]
            super().put(keys, value, weight)

    def clear(self):
        with self._lock:
            super().clear()
            self._resources.clear()

    def record(self, status):
        with self._lock:
            setattr(self, status, getattr(self, status) + 1)

    def statistics(self):
        with self._lock:
            result = super().statistics()
            result.update(hits=self.reused, misses=self.recomputed, invalidations=self.invalidated)
            result["shared_resources"] = len(self._resources)
            return result


@contextmanager
def measurement_scope(cache):
    """A worker-local scope inherited by nested footnote/template layout passes."""
    token = _active.set(cache)
    try:
        yield
    finally:
        _active.reset(token)


@dataclass(frozen=True)
class Container:
    kind: type
    items: tuple


def _freeze(value):
    if isinstance(value, (list, tuple, set)):
        return Container(type(value), tuple(_freeze(v) for v in value))
    return value  # Measurement records and their dataclass children are frozen.


def _thaw(value):
    if isinstance(value, Container):
        return value.kind(_thaw(v) for v in value.items)
    return value


def _weight(*values, exclude_glyphs=False, check=None):
    # Record-local sharing is counted once. ResolvedGlyph objects can be excluded
    # here because MeasurementCache accounts for their last retained reference.
    seen = set()

    def visit(value):
        if exclude_glyphs and isinstance(value, ResolvedGlyph):
            return 0
        if id(value) in seen:
            return 0
        seen.add(id(value))
        if isinstance(value, ResolvedGlyph):
            return value.retained_bytes
        if check and len(seen) % 256 == 0:
            check()
        size = getsizeof(value)
        if is_dataclass(value) and not isinstance(value, type):
            size += getsizeof(getattr(value, "__dict__", {}))
            size += sum(visit(getattr(value, f.name)) for f in fields(value))
        elif isinstance(value, (tuple, list, set)):
            size += sum(visit(v) for v in value)
        return size

    return sum(visit(value) for value in values)


@dataclass(frozen=True)
class Measurement:
    value: object
    dependencies: tuple


class RecordingResolver:
    def __init__(self, delegate):
        self.delegate = delegate
        self.dependencies = []
        self.failed = False

    def resolve(self, occurrence, **options):
        try:
            glyph = self.delegate.resolve(occurrence, **options)
        except ValueError:
            self.failed = True
            raise
        self.dependencies.append((occurrence, glyph, options))
        return glyph


def cached_measurement(function):
    """Cache known immutable measurement inputs, replaying all resolver effects.

    Only attach to measurement functions whose resolver use is through resolve().
    Keys retain exact source spans and identities. repr preserves numeric types
    and signed zero in these controlled dataclass/sequence/settings inputs.
    Mutable output containers are copied, while frozen geometry is shared.
    """
    parameters = signature(function)
    namespace = function.__module__ + "." + function.__name__

    @wraps(function)
    def measured(*args, **kwargs):
        cache = _active.get()
        if cache is None:
            return function(*args, **kwargs)
        from ..assets.resolver import SELECTION_VERSION
        from ..math.handwritten import MATH_LAYOUT_VERSION
        from .blocks import LAYOUT_VERSION

        bound = parameters.bind(*args, **kwargs)
        bound.apply_defaults()
        arguments = bound.arguments
        resolver = arguments["resolver"]

        def check():
            check_cancel(arguments.get("cancelled"))
            callback = arguments.get("cancel_check")
            if callback:
                callback()

        check()
        key = (
            MEASUREMENT_VERSION,
            LAYOUT_VERSION,
            MATH_LAYOUT_VERSION,
            SELECTION_VERSION,
            namespace,
            repr(
                tuple(
                    (k, v)
                    for k, v in arguments.items()
                    if k not in {"resolver", "cancelled", "cancel_check"}
                )
            ),
        )
        check()
        candidate = cache.get(key)
        if candidate is not None:
            valid = True
            for occurrence, old_glyph, options in candidate.dependencies:
                check()
                try:
                    glyph = resolver.resolve(occurrence, **options)
                except ValueError:
                    valid = False
                    break
                if glyph != old_glyph:
                    valid = False
                    break
            check()
            if valid:
                value = _thaw(candidate.value)
                check()
                cache.record("reused")
                return value
            cache.record("invalidated")
        cache.record("recomputed")
        recording = RecordingResolver(resolver)
        arguments["resolver"] = recording
        value = function(*bound.args, **bound.kwargs)
        check()
        # Missing/invalid resource resolutions must be retried next time.
        if not recording.failed:
            entry = Measurement(_freeze(value), tuple(recording.dependencies))
            weight = _weight(key, entry, exclude_glyphs=True, check=check)
            check()
            cache.put((key,), entry, weight)
        check()
        return value

    return measured
