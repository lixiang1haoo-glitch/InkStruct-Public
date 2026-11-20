"""Physical page routing, elapsed-time estimates and durable stroke checkpoints."""

from dataclasses import asdict, dataclass, replace
from hashlib import sha256
import json
from math import dist, isfinite
from pathlib import Path

from ..resource_catalog import atomic_json


def lengths(strokes, start=None):
    travel = ink = 0.
    for stroke in strokes:
        if start is not None:
            travel += dist(start, stroke.points[0])
        ink += sum(dist(a, b) for a, b in zip(stroke.points, stroke.points[1:]))
        start = stroke.points[-1]
    return travel, ink


def route_page(page):
    """Only reorder adjacent runs of explicitly identified geometric strokes."""
    strokes = list(page.strokes)
    i = 0
    while i < len(strokes):
        first = strokes[i]
        if not first.independent:
            i += 1
            continue
        end = i + 1
        while (end < len(strokes) and end - i < 64 and strokes[end].independent
               and strokes[end].execution_domain == first.execution_domain):
            end += 1
        original = strokes[i:end]
        previous = strokes[i - 1].points[-1] if i else first.points[0]
        position = previous
        pending = original.copy()
        ordered = []
        while pending:
            _, index, reverse = min((dist(position, stroke.points[side]), k, side == -1)
                                    for k, stroke in enumerate(pending) for side in (0, -1))
            stroke = pending.pop(index)
            if reverse:
                stroke = replace(stroke, points=stroke.points[::-1])
            ordered.append(stroke)
            position = stroke.points[-1]
        following = strokes[end:end + 1]
        if lengths(ordered + following, previous)[0] < lengths(original + following, previous)[0] - .001:
            strokes[i:end] = ordered
        i = end
    return replace(page, strokes=tuple(strokes))


def motion_seconds(distance, count, feed):
    return distance * 60 / feed + count * .35


def estimate_seconds(strokes, feed, start=None):
    travel, ink = lengths(strokes, start)
    return motion_seconds(travel + ink, len(strokes), feed)


@dataclass(frozen=True)
class ProgressFile:
    path: Path
    total: int
    optimized: bool = True
    placement: dict | None = None

    @classmethod
    def for_page(cls, folder, document, page, background, device):
        encoded = json.dumps([document, asdict(page), background, device],
                             ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
        return cls(Path(folder) / "plotter-progress" / (sha256(encoded).hexdigest() + ".json"),
                   len(page.strokes))

    def read(self):
        if not self.path.exists():
            return 0, False
        data = json.loads(self.path.read_bytes())
        if not isinstance(data, dict):
            raise ValueError("续写记录格式无效。")
        placement = data.get("placement")
        if placement is not None and (not isinstance(placement, dict) or
                                      not isinstance(placement.get("setup"), str) or
                                      not isinstance(placement.get("anchor"), list)):
            raise ValueError("续写记录中的纸面对位信息无效。")
        done, pending = data.get("completed"), data.get("check_stroke")
        if (data.get("total") != self.total or type(done) is not int or not 0 <= done <= self.total
                or type(pending) is not bool or (pending and done == self.total)):
            raise ValueError("本页续写记录无效，请核对纸面。")
        return done, pending

    def save(self, done, pending):
        atomic_json(self.path, {"total": self.total, "completed": done, "check_stroke": pending,
                                "optimized": self.optimized, "placement": self.placement})


def timing_factor(path):
    try:
        value = float(json.loads(path.read_bytes())["factor"])
        if isfinite(value) and value > 0:
            return value
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return 1.


def record_time(path, seconds, estimate):
    if seconds > 0 and estimate > 0:
        measured = seconds / estimate
        factor = (timing_factor(path) + measured) / 2 if path.exists() else measured
        atomic_json(path, {"factor": factor, "last_seconds": seconds})
