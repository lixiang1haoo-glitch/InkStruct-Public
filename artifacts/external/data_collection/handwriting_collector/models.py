from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Iterable

import numpy as np


def is_cjk_character(value: str) -> bool:
    """Return whether value is one CJK unified ideograph."""
    if len(value) != 1:
        return False
    code = ord(value)
    return (
        0x3400 <= code <= 0x4DBF
        or 0x4E00 <= code <= 0x9FFF
        or 0x20000 <= code <= 0x2FA1F
        or 0x30000 <= code <= 0x323AF
    )


@dataclass(frozen=True)
class TrajectoryPoint:
    x: float
    y: float
    pressure: float
    t_ms: int

    def validate(self, width: float, height: float) -> None:
        if not all(math.isfinite(v) for v in (self.x, self.y, self.pressure)):
            raise ValueError("轨迹点包含非有限数值")
        if not (0.0 <= self.pressure <= 1.0):
            raise ValueError("压力值必须位于 [0, 1]")
        if self.t_ms < 0:
            raise ValueError("时间戳不能为负数")
        if not (0.0 <= self.x <= width and 0.0 <= self.y <= height):
            raise ValueError("轨迹点超出画布范围")

    def to_dict(self) -> dict:
        return {
            "x": round(float(self.x), 4),
            "y": round(float(self.y), 4),
            "pressure": round(float(self.pressure), 6),
            "t_ms": int(self.t_ms),
        }


@dataclass
class Stroke:
    points: list[TrajectoryPoint] = field(default_factory=list)

    def to_dict(self, index: int) -> dict:
        return {
            "stroke_index": index,
            "points": [point.to_dict() for point in self.points],
        }


@dataclass
class Trajectory:
    strokes: list[Stroke] = field(default_factory=list)

    def start_stroke(self, point: TrajectoryPoint) -> None:
        self.strokes.append(Stroke([point]))

    def append_point(self, point: TrajectoryPoint) -> None:
        if not self.strokes:
            self.start_stroke(point)
        else:
            self.strokes[-1].points.append(point)

    def undo_last_stroke(self) -> bool:
        if not self.strokes:
            return False
        self.strokes.pop()
        return True

    def clear(self) -> None:
        self.strokes.clear()

    @property
    def point_count(self) -> int:
        return sum(len(stroke.points) for stroke in self.strokes)

    @property
    def duration_ms(self) -> int:
        points = list(self.iter_points())
        return 0 if not points else max(0, points[-1].t_ms - points[0].t_ms)

    def iter_points(self) -> Iterable[TrajectoryPoint]:
        for stroke in self.strokes:
            yield from stroke.points

    def validate(self, width: float, height: float) -> None:
        if not self.strokes or self.point_count == 0:
            raise ValueError("请先书写有效轨迹")
        previous_global_t = -1
        for stroke in self.strokes:
            if not stroke.points:
                raise ValueError("存在空笔画")
            previous_t = -1
            for point in stroke.points:
                point.validate(width, height)
                if point.t_ms < previous_t:
                    raise ValueError("笔画内时间戳必须递增")
                if point.t_ms < previous_global_t:
                    raise ValueError("轨迹时间戳必须全局递增")
                previous_t = point.t_ms
                previous_global_t = point.t_ms

    def to_point_seq(self) -> tuple[np.ndarray, list[int]]:
        """Convert a single character to the legacy DiffInk (N, 5) protocol."""
        if self.point_count == 0:
            raise ValueError("没有轨迹数据")
        seq = np.zeros((self.point_count, 5), dtype=np.float32)
        row = 0
        for stroke in self.strokes:
            if not stroke.points:
                continue
            for point in stroke.points:
                seq[row, 0] = point.x
                seq[row, 1] = point.y
                seq[row, 2] = 1.0
                row += 1
            seq[row - 1, 2] = 0.0
            seq[row - 1, 3] = 1.0
        seq = seq[:row]
        seq[-1, 3] = 0.0
        seq[-1, 4] = 1.0
        return seq, [len(seq)]
