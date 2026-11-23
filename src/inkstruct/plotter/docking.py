"""Evidence used to bind a physical docking point to a controller session."""

from dataclasses import asdict, dataclass, field
from math import dist

from ..document.schema import digest
from .grbl import PEN_UP, STATIONARY_TOLERANCE_MM, Z_TOLERANCE_MM
from .physical import machine_point


def idle_xy(status):
    if (status is None or status.state != "Idle" or status.blocking_pins or not status.position
            or abs(status.position[2] - PEN_UP) > Z_TOLERANCE_MM):
        raise ValueError("请抬笔、停稳并重新读取位置。")
    return machine_point(status.position[:2])


def at_zero(point):
    return dist(point, (0., 0.)) <= STATIONARY_TOLERANCE_MM


@dataclass
class DockTrial:
    device_id: str
    initial: tuple
    connection: str
    readings: list = field(default_factory=list)
    mode: str = ""
    origin: tuple | None = None
    trial_axes: object = None

    def record_restart(self, connection, status):
        if self.mode or not connection or connection == self.connection:
            raise ValueError("请保持笔尖不动，重启设备并手动重连。")
        point = idle_xy(status)
        self.connection = connection
        self.readings.append(point)
        if len(self.readings) == 3:
            if all(at_zero(p) for p in self.readings):
                self.mode = "zero"
            elif not at_zero(self.initial) and all(not at_zero(p) and dist(p, self.initial) <= STATIONARY_TOLERANCE_MM
                                                   for p in self.readings):
                self.mode = "retained"
            else:
                raise ValueError("三轮重启读数不一致。请重启软件，重新初始化；若仍失败，请联系交流群 1035966437。")
            self.origin = point


def reconnect_key(profile):
    return digest([profile.id, profile.serial, asdict(profile.axes), profile.datum.id])


def idle_checkpoint(profile, frame, status):
    if frame is None or not profile.serial or not profile.datum or not profile.datum.boot_mode:
        return None
    xy = idle_xy(status)
    if status.offset is None or at_zero(xy):
        return None
    return dict(schema="dock-idle-v1", identity=reconnect_key(profile), xy=xy,
                offset=status.offset, frame=machine_point(frame))


def restored_frame(profile, saved, status):
    xy = idle_xy(status)
    if (at_zero(xy) or status.offset is None or not profile.serial or not profile.datum
            or not profile.datum.boot_mode or not saved or saved.get("schema") != "dock-idle-v1"
            or saved.get("identity") != reconnect_key(profile)
            or tuple(saved["offset"]) != tuple(status.offset)
            or dist(xy, machine_point(saved["xy"])) > STATIONARY_TOLERANCE_MM):
        return None
    return machine_point(saved["frame"])


def dock_from_mark(axes, virtual, work):
    dx, dy = axes.map(*machine_point(virtual))
    x, y = machine_point(work)
    return machine_point((x - dx, y - dy))
