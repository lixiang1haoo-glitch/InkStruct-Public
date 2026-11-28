"""Local plotter profiles and physical placement records."""

import json
import math
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from uuid import uuid4

from ..resource_catalog import atomic_json, catalog_write
from .grbl import DEFAULT_WRITE_FEED, MAX_WRITE_FEED, PEN_DOWN
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
class DeviceDatum:
    """A physical reference on one device with one axis calibration.

    Its work-coordinate origin is observed afresh in each connection and is
    deliberately not part of the saved profile.
    """

    id: str
    device_id: str
    axes: DeviceAxes
    label: str
    area: WorkArea | None = None
    checkpoint: tuple[float, float] | None = None

    boot_mode: str = ""  # Empty on legacy paper-corner datums.
    restart_positions: tuple = ()

    @classmethod
    def create(cls, profile, label):
        return cls(uuid4().hex, profile.id, profile.axes, label.strip())

    def __post_init__(self):
        if self.boot_mode not in ("", "zero", "retained") or len(self.restart_positions) not in (0, 4):
            raise ValueError("停靠点初始化记录无效。")
        object.__setattr__(self, "restart_positions", tuple(machine_point(p) for p in self.restart_positions))
        if not self.id or not self.device_id or not self.label.strip():
            raise ValueError("请填写纸张限位及基准点名称。")
        if isinstance(self.axes, dict):
            object.__setattr__(self, "axes", DeviceAxes(**self.axes))
        if isinstance(self.area, dict):
            object.__setattr__(self, "area", WorkArea(**self.area))
        if self.checkpoint is not None:
            object.__setattr__(self, "checkpoint", machine_point(self.checkpoint))

    def to_body(self, work_point, origin):
        x, y = machine_point(work_point)
        ox, oy = machine_point(origin)
        return machine_point(self.axes.unmap(x - ox, y - oy))

    def to_work(self, body_point, origin):
        x, y = self.axes.map(*machine_point(body_point))
        ox, oy = machine_point(origin)
        return machine_point((ox + x, oy + y))

    def origin_from_checkpoint(self, work_point):
        if self.checkpoint is None:
            raise ValueError("请先登记备用基准点。")
        x, y = machine_point(work_point)
        dx, dy = self.axes.map(*self.checkpoint)
        return machine_point((x - dx, y - dy))

    @staticmethod
    def _area_between(a, b):
        return WorkArea(min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1]))

    def to_body_area(self, work_area, origin):
        # Axis swapping and mirroring keep the rectangle axis-aligned.
        ox, oy = machine_point(origin)
        return self._area_between(self.axes.unmap(work_area.left - ox, work_area.top - oy),
                                  self.axes.unmap(work_area.right - ox, work_area.bottom - oy))

    def to_work_area(self, body_area, origin):
        ox, oy = machine_point(origin)
        ax, ay = self.axes.map(body_area.left, body_area.top)
        bx, by = self.axes.map(body_area.right, body_area.bottom)
        return self._area_between((ox + ax, oy + ay), (ox + bx, oy + by))


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
    datum: DeviceDatum | None = None
    limit_area_enabled: bool = False
    active_pen: str = ""
    pen_heights: tuple = ()
    stop_generation: str = ""

    def accepts_sheet(self, record):
        return bool(self.datum and self.datum.boot_mode and record and record.get("generation") == self.datum.id
                    and record.get("stops", "") == self.stop_generation and record.get("virtual") is not None)

    @property
    def writing_height(self):
        return dict(self.pen_heights).get(self.active_pen, PEN_DOWN)

    @classmethod
    def create(cls, name, port, serial=""):
        return cls(uuid4().hex, name.strip(), port, serial)

    @classmethod
    def from_storage(cls, data):
        profile = cls(**{key: value for key, value in data.items()
                         if key not in {"paper_calibration", "return_after_page"}})
        if "limit_area_enabled" not in data and (profile.area or (profile.datum and profile.datum.area)):
            return replace(profile, limit_area_enabled=True)
        return profile

    def __post_init__(self):
        if not self.id or not self.name.strip() or not self.port:
            raise ValueError("请填写设备名称并选择串口。")
        if isinstance(self.axes, dict):
            object.__setattr__(self, "axes", DeviceAxes(**self.axes))
        if isinstance(self.area, dict):
            object.__setattr__(self, "area", WorkArea(**self.area))
        if isinstance(self.datum, dict):
            object.__setattr__(self, "datum", DeviceDatum(**self.datum))
        if self.datum and (self.datum.device_id != self.id or self.datum.axes != self.axes):
            object.__setattr__(self, "datum", None)
        if self.offset is not None:
            object.__setattr__(self, "offset", machine_point(self.offset))
        if type(self.feed) is not int or not 60 <= self.feed <= MAX_WRITE_FEED:
            raise ValueError(f"XY 运动速度应在 60–{MAX_WRITE_FEED} mm/min 内。")
        heights = tuple((name, float(value)) for name, value in self.pen_heights)
        if (any(not isinstance(name, str) or not name.strip() or not PEN_DOWN <= value <= -.1
                for name, value in heights) or len(dict(heights)) != len(heights)
                or (self.active_pen and self.active_pen not in dict(heights))):
            raise ValueError("笔具名称或标定高度无效。")
        object.__setattr__(self, "pen_heights", heights)
        if type(self.limit_area_enabled) is not bool:
            raise ValueError("工作范围开关无效。")


class PlotterProfiles:
    def __init__(self, workspace):
        self.path = Path(workspace) / "plotter-docking.json"
        self.legacy_path = Path(workspace) / "plotter-profiles.json"
        self.lock_path = self.path.with_suffix(".lock")

    def read(self):
        if self.path.exists():
            return json.loads(self.path.read_text("utf-8"))
        data = {"devices": {}, "selected": ""}
        if self.legacy_path.exists():
            previous = json.loads(self.legacy_path.read_text("utf-8"))
            data["selected"] = previous.get("selected", "")
            for key, item in previous["devices"].items():
                # Preserve motor calibration and pen settings. A legacy datum
                # was a user-named paper corner, never a verified parking spot.
                profile = DeviceProfile.from_storage(item)
                device = asdict(replace(profile, datum=None))
                data["devices"][key] = device
        return data

    def devices(self):
        return [DeviceProfile.from_storage(profile) for profile in self.read()["devices"].values()]

    @catalog_write
    def save(self, profile):
        data = self.read()
        device = asdict(profile)
        data["devices"][profile.id] = device
        data["selected"] = profile.id
        atomic_json(self.path, data)

    @catalog_write
    def rename_device(self, identifier, name):
        data = self.read()
        if identifier not in data["devices"] or not name.strip():
            raise ValueError("请选择已有设备并填写名称。")
        data["devices"][identifier]["name"] = name.strip()
        atomic_json(self.path, data)

    @catalog_write
    def remove_device(self, identifier):
        data = self.read()
        if identifier not in data["devices"]:
            raise ValueError("该写字机档案已移除。")
        del data["devices"][identifier]
        for section in ("paper_marks", "reconnect_positions"):
            data.get(section, {}).pop(identifier, None)
        if data["selected"] == identifier:
            data["selected"] = next(iter(data["devices"]), "")
        atomic_json(self.path, data)

    @catalog_write
    def import_marks(self, profile, marks):
        data = self.read()
        records = data.setdefault("paper_marks", {}).setdefault(profile.id, {})
        additions = {key: {"mark": machine_point(point)} for key, point in marks.items() if key not in records}
        if additions:
            records.update(additions)
            atomic_json(self.path, data)

    def sheets(self, profile):
        return self.read().get('paper_marks', {}).get(profile.id, {})

    def sheet(self, profile, key):
        return self.sheets(profile).get(key)

    @catalog_write
    def save_sheet(self, profile, key, mark, virtual, source, *, layout=None):
        data = self.read()
        records = data.setdefault("paper_marks", {}).setdefault(profile.id, {})
        entry = {"mark": machine_point(mark)}
        if virtual is not None:
            if not profile.datum or not profile.datum.boot_mode:
                raise ValueError("请先完成停靠点初始化。")
            entry.update(generation=profile.datum.id, stops=profile.stop_generation, virtual=machine_point(virtual), source=source)
        if layout:
            entry["layout"] = layout
        if records.get(key) != entry:
            records[key] = entry
            atomic_json(self.path, data)

    @catalog_write
    def exchange_checkpoint(self, profile, checkpoint=None):
        data = self.read()
        checkpoints = data.setdefault("reconnect_positions", {})
        previous = checkpoints.pop(profile.id, None)
        if checkpoint:
            checkpoints[profile.id] = checkpoint
        if previous or checkpoint:
            atomic_json(self.path, data)
        return previous
