"""Local plotter profiles and physical placement records."""

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import uuid4

from ..document.schema import digest
from ..resource_catalog import atomic_json, catalog_write
from .grbl import DEFAULT_WRITE_FEED, MAX_WRITE_FEED
from .physical import PaperRegistration, WorkArea, machine_point


@dataclass(frozen=True)
class DeviceAxes:
    x_scale: float = 1.
    y_scale: float = 1.
    mirror_x: bool = False
    mirror_y: bool = False
    swap: bool = False

    def __post_init__(self):
        if not all(math.isfinite(v) and .0001 <= v <= 10 for v in (self.x_scale, self.y_scale)):
            raise ValueError("X/Y 比例必须在 0.01% 至 1000% 内。")
        if any(type(v) is not bool for v in (self.mirror_x, self.mirror_y, self.swap)):
            raise ValueError("轴向选项无效。")

    def map(self, x, y):
        x *= -self.x_scale if self.mirror_x else self.x_scale
        y *= -self.y_scale if self.mirror_y else self.y_scale
        return (y, x) if self.swap else (x, y)

    def unmap(self, x, y):
        if self.swap:
            x, y = y, x
        return (x / (-self.x_scale if self.mirror_x else self.x_scale),
                y / (-self.y_scale if self.mirror_y else self.y_scale))

    def register(self, paper, measured, *, angle=0., scale=1.):
        return PaperRegistration(machine_point(measured), machine_point(paper), math.cos(angle),
                                 math.sin(angle), scale, self.map(1, 0), self.map(0, 1))

    def measure(self, paper, a, b):
        delta = self.unmap(b[0] - a[0], b[1] - a[1])
        result = PaperRegistration.two_point(paper, ((0., 0.), delta), scale=True)
        return math.atan2(result.sine, result.cosine), result.scale


@dataclass(frozen=True)
class PageAlignment:
    a: tuple[float, float]
    b: tuple[float, float] | None = None
    angle: float = 0.
    scale: float = 1.

    def __post_init__(self):
        object.__setattr__(self, "a", machine_point(self.a))
        if self.b is not None:
            object.__setattr__(self, "b", machine_point(self.b))
            if math.dist(self.a, self.b) < 1.:
                raise ValueError("A、B 两点至少相距 1 mm。")
        if not math.isfinite(self.angle) or not math.isfinite(self.scale) or not .1 <= self.scale <= 10:
            raise ValueError("页面修正数值无效。")

    def validate_size(self, width, height):
        for x, y in (self.a, *((self.b,) if self.b is not None else ())):
            if not (0 <= x <= width and 0 <= y <= height):
                raise ValueError("对位点须位于页面内。")


@dataclass(frozen=True)
class DeviceProfile:
    id: str
    name: str
    port: str
    serial: str = ""
    axes: DeviceAxes = DeviceAxes()
    area: WorkArea | None = None
    offset: tuple[float, float] | None = None
    feed: int = DEFAULT_WRITE_FEED

    @classmethod
    def create(cls, name, port, serial=""):
        return cls(uuid4().hex, name.strip(), port, serial)

    def __post_init__(self):
        if not self.id or not self.name.strip() or not self.port:
            raise ValueError("请填写设备名称并选择串口。")
        if isinstance(self.axes, dict):
            object.__setattr__(self, "axes", DeviceAxes(**self.axes))
        if isinstance(self.area, dict):
            object.__setattr__(self, "area", WorkArea(**self.area))
        if self.offset is not None:
            object.__setattr__(self, "offset", machine_point(self.offset))
        if type(self.feed) is not int or not 60 <= self.feed <= MAX_WRITE_FEED:
            raise ValueError("书写速度无效。")


class PlotterProfiles:
    def __init__(self, workspace):
        self.path = Path(workspace) / "plotter-profiles.json"
        self.lock_path = self.path.with_suffix(".lock")

    def read(self):
        if not self.path.exists():
            return {"devices": {}, "placements": {}, "selected": ""}
        return json.loads(self.path.read_text("utf-8"))

    def devices(self):
        return [DeviceProfile(**profile) for profile in self.read()["devices"].values()]

    @catalog_write
    def save(self, profile):
        data = self.read()
        data["devices"][profile.id] = asdict(profile)
        data["selected"] = profile.id
        atomic_json(self.path, data)

    def place(self, profile, page, setup, alignment, position=None, offset=None, correction=None, *, connection=None):
        scope = digest([profile.id, page])
        key = digest([scope, setup, asdict(profile.axes), asdict(alignment) if alignment else None])
        if position is not None:
            self.record(key, {"point": machine_point(position), "offset": offset, "scope": scope,
                              "connection": connection,
                              "setup": setup, "correction": asdict(correction or alignment)})
        return self.read()["placements"].get(key)

    @catalog_write
    def record(self, key, value):
        data = self.read()
        data["placements"][key] = value
        atomic_json(self.path, data)

    def setups(self, profile, page):
        scope = digest([profile.id, page])
        return sorted({entry["setup"] for entry in self.read()["placements"].values()
                       if entry.get("scope") == scope})
