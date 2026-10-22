"""Thread-safe bounded LRU for immutable derived values, with shared-key aliases."""

from collections import OrderedDict
from dataclasses import dataclass
from threading import RLock


@dataclass(frozen=True)
class Entry:
    keys: tuple
    value: object
    weight: int


class BoundedCache:
    """Weights are conservative estimates, not a guarantee about process RSS."""

    def __init__(self, *, max_entries, max_weight):
        if max_entries < 1 or max_weight < 1:
            raise ValueError("Cache limits must be positive")
        self.max_entries, self.max_weight = max_entries, max_weight
        self._entries, self._aliases = OrderedDict(), {}
        self._lock = RLock()
        self.weight = self.hits = self.misses = self.evictions = self.skipped = 0

    def get(self, key):
        with self._lock:
            if key not in self._aliases:
                self.misses += 1
                return None
            primary = self._aliases[key]
            self._entries.move_to_end(primary)
            self.hits += 1
            return self._entries[primary].value

    def _remove(self, primary):
        entry = self._entries.pop(primary)
        for key in entry.keys:
            del self._aliases[key]
        self.weight -= entry.weight

    def put(self, keys, value, weight):
        keys = tuple(dict.fromkeys(keys))
        if not keys or weight < 0:
            raise ValueError("Cache entry needs keys and nonnegative weight")
        with self._lock:
            for key in keys:
                if key in self._aliases:
                    self._remove(self._aliases[key])
            if weight > self.max_weight:
                self.skipped += 1
                return
            while self._entries and (
                len(self._entries) >= self.max_entries or self.weight + weight > self.max_weight
            ):
                self._remove(next(iter(self._entries)))
                self.evictions += 1
            primary = keys[0]
            self._entries[primary] = Entry(keys, value, weight)
            self._aliases.update((key, primary) for key in keys)
            self.weight += weight

    def clear(self):
        with self._lock:
            self._entries.clear()
            self._aliases.clear()
            self.weight = 0

    def statistics(self):
        with self._lock:
            return {
                "entries": len(self._entries),
                "estimated_bytes": self.weight,
                "hits": self.hits,
                "misses": self.misses,
                "evictions": self.evictions,
                "skipped": self.skipped,
            }
