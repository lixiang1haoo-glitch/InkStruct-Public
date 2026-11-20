"""Freeze a plot page in the confirmed work coordinates used by the machine."""

import math
from dataclasses import dataclass

from .schema import PathPoints, PlotPage, Point

COORDINATE_DECIMALS = 4
TEST_CIRCLE_RADIUS_MM = .5


def machine_point(point: Point) -> Point:
    if len(point) != 2 or not all(math.isfinite(value) for value in point):
        raise ValueError("坐标必须是有限的毫米数值。")
    return tuple(round(value, COORDINATE_DECIMALS) or 0.0 for value in point)


@dataclass(frozen=True)
class WorkArea:
    left: float
    top: float
    right: float
    bottom: float

    def __post_init__(self):
        if (not all(math.isfinite(value) for value in (self.left, self.top, self.right, self.bottom))
                or self.left >= self.right or self.top >= self.bottom):
            raise ValueError("工作范围需要有效的 X、Y 最小值和最大值。")

    def contains(self, point: Point, *, inset=0.0):
        x, y = point
        return self.left + inset <= x <= self.right - inset and self.top + inset <= y <= self.bottom - inset

    def require(self, point: Point, label: str):
        x, y = point
        if not self.contains(point):
            raise ValueError(f"{label} ({x:g}, {y:g}) mm 超出已确认的工作范围。")


@dataclass(frozen=True)
class PaperRegistration:
    origin: Point
    anchor: Point = (0.0, 0.0)
    cosine: float = 1.0
    sine: float = 0.0
    scale: float = 1.0
    x_axis: Point = (1.0, 0.0)
    y_axis: Point = (0.0, 1.0)

    @classmethod
    def two_point(cls, paper: tuple[Point, Point], machine: tuple[Point, Point], *, scale=False):
        paper_start, paper_end = map(machine_point, paper)
        machine_start, machine_end = map(machine_point, machine)
        px, py = (b - a for a, b in zip(paper_start, paper_end, strict=True))
        mx, my = (b - a for a, b in zip(machine_start, machine_end, strict=True))
        paper_distance, machine_distance = math.hypot(px, py), math.hypot(mx, my)
        if min(paper_distance, machine_distance) < 1:
            raise ValueError("前两个对位点的距离需至少 1 mm。")
        px, py = px / paper_distance, py / paper_distance
        mx, my = mx / machine_distance, my / machine_distance
        return cls(machine_start, paper_start, px * mx + py * my, px * my - py * mx,
                   machine_distance / paper_distance if scale else 1.0)

    def vector(self, x, y):
        u = self.scale * (self.cosine * x - self.sine * y)
        v = self.scale * (self.sine * x + self.cosine * y)
        return (u * self.x_axis[0] + v * self.y_axis[0],
                u * self.x_axis[1] + v * self.y_axis[1])

    def place(self, point: Point) -> Point:
        x, y = point[0] - self.anchor[0], point[1] - self.anchor[1]
        u, v = self.vector(x, y)
        return machine_point((self.origin[0] + u, self.origin[1] + v))


@dataclass(frozen=True)
class MachineStroke:
    name: str
    points: PathPoints
    width_mm: float


@dataclass(frozen=True)
class MachinePage:
    index: int
    strokes: tuple[MachineStroke, ...]
    registration: PaperRegistration

    def clearance_box(self, start: Point, margin: float) -> WorkArea:
        """Propose an outward-rounded rectangle for the operator to inspect."""
        left = right = start[0]
        top = bottom = start[1]
        for stroke in self.strokes:
            for x, y in stroke.points:
                left, right = min(left, x), max(right, x)
                top, bottom = min(top, y), max(bottom, y)
        # Round relative extents out to whole mm, matching what the operator sees.
        x, y = start
        return WorkArea(x + math.floor(left - x - margin), y + math.floor(top - y - margin),
                        x + math.ceil(right - x + margin), y + math.ceil(bottom - y + margin))

    def check(self, area: WorkArea | None, start: Point, *, dry_run=False):
        machine_point(start)
        if area is not None:
            area.require(start, "当前笔尖位置")
        if not self.strokes:
            raise ValueError("当前页没有可发送的笔迹。")
        for number, stroke in enumerate(self.strokes, 1):
            if len(stroke.points) < 2:
                raise ValueError(f"第 {number} 笔没有完整的笔段。")
            for index, point in enumerate(stroke.points):
                machine_point(point)
                if area is not None:
                    kind = "空走终点" if not index else ("抬笔试走坐标" if dry_run else "落笔坐标")
                    area.require(point, f"第 {number} 笔的{kind}")


def position_page(page: PlotPage, registration: PaperRegistration) -> MachinePage:
    if not page.strokes:
        raise ValueError("当前页没有可发送的笔迹。")
    strokes = []
    for stroke in page.strokes:
        points = tuple(map(registration.place, stroke.points))
        if len(set(points)) < 2:
            raise ValueError(f"第 {len(strokes) + 1} 笔在设备坐标精度下没有长度。")
        strokes.append(MachineStroke(stroke.stroke_id, points, stroke.width_mm))
    return MachinePage(page.index, tuple(strokes), registration)


def axis_trial(registration):
    paths = (
        ((0, 0), (50, 0)), ((0, 0), (0, 50)),
        ((34, 5), (44, 15)), ((44, 5), (34, 15)),
        ((5, 34), (10, 39), (15, 34)), ((10, 39), (10, 45)),
    )
    return MachinePage(0, tuple(MachineStroke("试画 X/Y", tuple(map(registration.place, points)), .2)
                                for points in paths), registration)


def registration_marks(page: PlotPage, registration: PaperRegistration,
                       points: tuple[Point, Point, Point]) -> MachinePage:
    if len(set(points)) != 3:
        raise ValueError("需要三个不同的纸面测试点。")
    ax, ay = points[0]
    bx, by = points[1]
    cx, cy = points[2]
    length = math.dist(points[0], points[1])
    if length < 1 or abs((bx - ax) * (cy - ay) - (by - ay) * (cx - ax)) / length < 1:
        raise ValueError("第三点要离前两个点的连线至少 1 mm，才能独立核验。")
    strokes = []
    for count, paper in enumerate(points, 1):
        x, y = paper
        radius = TEST_CIRCLE_RADIUS_MM / registration.scale
        if not (radius <= x <= page.width_mm - radius and radius <= y <= page.height_mm - radius):
            raise ValueError(f"测试点 {count} 的圆超出了纸面。")
        x, y = registration.place(paper)
        path = tuple(machine_point((x + TEST_CIRCLE_RADIUS_MM * math.cos(angle),
                                    y + TEST_CIRCLE_RADIUS_MM * math.sin(angle)))
                     for angle in (i * math.tau / 24 for i in range(25)))
        strokes.append(MachineStroke(f"测试点 {count}", path, .2))
    return MachinePage(page.index, tuple(strokes), registration)
