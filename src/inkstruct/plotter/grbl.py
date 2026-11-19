"""Blocking Grbl transactions for the N1. The owning worker holds the serial port."""

import math
import re
from collections import deque
from dataclasses import dataclass, field
from threading import Event
from time import monotonic, sleep

from .physical import COORDINATE_DECIMALS, MachinePage, WorkArea, machine_point
from .schema import Point

PEN_UP = 0.0
PEN_DOWN = -1.6
Z_TOLERANCE_MM = .05
TRAVEL_FEED = 1500


class MachineError(RuntimeError):
    pass


class Stopped(MachineError):
    pass


@dataclass(frozen=True)
class Status:
    state: str
    position: tuple[float, float, float] | None
    offset: tuple[float, float, float] | None
    limits: str


def position_vector(value: str):
    entries = value.split(",")
    if len(entries) not in (3, 4):
        raise MachineError("设备返回了无法识别的坐标。")
    try:
        values = tuple(map(float, entries))
    except ValueError as error:
        raise MachineError("设备返回了无效的坐标。") from error
    if not all(math.isfinite(value) for value in values):
        raise MachineError("设备坐标不是有限数值。")
    return values[:3]


def decode_status(line: str, previous_offset=None):
    if not line.startswith("<") or not line.endswith(">"):
        raise MachineError("设备状态响应不完整。")
    state, *fields = line[1:-1].split("|")
    data = dict(item.split(":", 1) for item in fields if ":" in item)
    offset = position_vector(data["WCO"]) if "WCO" in data else previous_offset
    if "WPos" in data:
        position = position_vector(data["WPos"])
    elif "MPos" in data and offset is not None:
        position = tuple(a - b for a, b in zip(position_vector(data["MPos"]), offset, strict=True))
    else:
        position = None
    return Status(state, position, offset, data.get("Pn", ""))


@dataclass
class MotionControl:
    pause_requested: Event = field(default_factory=Event)
    stop_requested: Event = field(default_factory=Event)


class GrblLink:
    def __init__(self, serial, *, phase=lambda _phase: None, progress=lambda _done, _total: None):
        self.serial = serial
        self.phase = phase
        self.progress = progress
        self.responses = deque()
        self.last_status = None
        self.status_count = 0
        self.metric = False
        self.motion_active = False

    def send(self, text: str):
        self.serial.write(text.encode("ascii"))

    def pump(self, timeout=.05):
        line = self.serial.readline(timeout)
        if not line:
            return
        line = line.strip()
        if line.startswith("<"):
            previous = self.last_status.offset if self.last_status else None
            self.last_status = decode_status(line, previous)
            self.status_count += 1
            if self.metric and previous is not None and self.last_status.offset != previous:
                raise MachineError("设备工作坐标偏置已变化。")
            if self.motion_active:
                state = self.last_status.state
                if state.split(":")[0] not in {"Idle", "Run", "Hold"}:
                    raise MachineError(f"作业中设备进入 {state} 状态。")
                if self.last_status.limits and set(self.last_status.limits) & set("XYZ"):
                    raise MachineError(f"作业中设备报告了轴限位（Pn:{self.last_status.limits}）。")
        elif line.lower().startswith(("error:", "alarm:")):
            raise MachineError(f"设备返回 {line}。")
        elif line.startswith("Grbl"):
            if self.last_status is not None:
                raise MachineError("设备已复位，请重新核对工作坐标。")
        elif len(self.responses) < 1024:
            self.responses.append(line)
        else:
            raise MachineError("设备返回了过多的未确认响应。")

    def checkpoint(self, control: MotionControl | None):
        if control is None:
            return 0.0
        if control.stop_requested.is_set():
            raise Stopped("已停止作业。")
        if not control.pause_requested.is_set():
            return 0.0
        began = monotonic()
        self.send("!")
        self.phase("pausing")
        # Consume reports without losing the outstanding G-code acknowledgement.
        next_query = 0.0
        generation = self.status_count
        held = False
        while control.pause_requested.is_set() or not held:
            if control.stop_requested.is_set():
                raise Stopped("已停止作业。")
            now = monotonic()
            if not held and now - began > 5:
                raise MachineError("未收到设备已暂停的确认。")
            if now >= next_query:
                self.send("?")
                next_query = now + .2
            self.pump()
            if not held and self.status_count > generation and self.last_status.state in {"Idle", "Hold:0"}:
                held = True
                self.phase("paused")
        self.send("~")
        self.phase("running")
        return monotonic() - began

    def status(self, control=None, *, timeout=2.5):
        end = monotonic() + timeout
        generation = self.status_count
        next_query = 0.0
        while monotonic() < end:
            paused_for = self.checkpoint(control)
            if paused_for:
                end += paused_for
                generation = self.status_count
                next_query = 0.0
            if self.status_count > generation:
                return self.last_status
            if monotonic() >= next_query:
                self.send("?")
                next_query = monotonic() + .25
            self.pump()
        raise MachineError("设备未返回状态。")

    def command(self, command: str, control=None):
        self.checkpoint(control)
        self.send(command + "\n")
        end = monotonic() + 15
        lines = []
        while monotonic() < end:
            end += self.checkpoint(control)
            if self.responses:
                line = self.responses.popleft()
                if line == "ok":
                    return lines
                lines.append(line)
            else:
                self.pump()
        raise MachineError(f"设备未确认 {command}。")

    def connect(self):
        # Read status before any command. Settings are queried, never rewritten.
        state = self.status()
        if state.state != "Idle":
            raise MachineError(f"设备报告 {state.state}，请在设备侧检查并恢复到 Idle 后重新连接。")
        if state.position is None:
            deadline = monotonic() + 5
            while state.position is None and monotonic() < deadline:
                sleep(.1)
                state = self.status()
        if state.position is None:
            raise MachineError("设备没有返回可核对的工作坐标。")
        settings = self.command("$$")
        # CX-Elite appends the setting description after the numeric value.
        unit_settings = [line for line in settings if re.match(r"^\$13\s*=", line)]
        if len(unit_settings) != 1 or not re.fullmatch(
            r"\$13\s*=\s*0(?:\.0+)?\s*(?:\([^()]*\))?", unit_settings[0]
        ):
            raise MachineError("无法确认设备状态使用毫米。请在设备侧核对 Grbl 的 $13 设置。")
        self.metric = True
        return self.require_idle()

    def require_idle(self, control=None, *, for_motion=False):
        status = self.status(control)
        if not self.metric or status.state != "Idle" or status.position is None:
            raise MachineError(f"需要设备处于 Idle 并返回有效的毫米工作坐标，当前状态为 {status.state}。")
        if set(status.limits) & set("XYZ"):
            raise MachineError(f"设备报告了轴限位（Pn:{status.limits}），无法移动。")
        if for_motion and not PEN_DOWN - Z_TOLERANCE_MM <= status.position[2] <= PEN_UP + Z_TOLERANCE_MM:
            raise MachineError("Z 工作坐标超出升降笔范围，请在设备侧核对笔尖位置。")
        return status

    def wait_idle(self, control, *, z: float):
        end = monotonic() + 120
        while monotonic() < end:
            end += self.checkpoint(control)
            began = monotonic()
            status = self.status(control)
            end += max(0.0, monotonic() - began - 2.5)
            if status.state == "Idle":
                if status.position is None or abs(status.position[2] - z) > Z_TOLERANCE_MM:
                    raise MachineError("设备已空闲，但 Z 工作坐标未到达预期位置。")
                return status
            if status.state.startswith("Hold") and not control.pause_requested.is_set():
                raise MachineError("设备在作业中被外部暂停。")
            sleep(.08)
        raise MachineError("等待设备 Idle 超时。")

    def pen(self, height, control):
        self.command(f"G1 Z{height:g} F5000", control)

    def xy(self, point: Point, feed: int, control):
        x, y = point
        self.command(f"G1 X{x:.{COORDINATE_DECIMALS}f} Y{y:.{COORDINATE_DECIMALS}f} F{feed}", control)

    def enter_motion(self, control):
        self.motion_active = True
        self.phase("running")
        self.command("G21 G90 G94", control)
        self.pen(PEN_UP, control)
        return self.wait_idle(control, z=PEN_UP)

    def run_page(self, page: MachinePage, area: WorkArea, control: MotionControl, *, dry_run=False, feed=900):
        if type(feed) is not int or not 60 <= feed <= 3000:
            raise ValueError("书写速度应在 60–3000 mm/min 内。")
        state = self.require_idle(control, for_motion=True)
        page.check(area, state.position[:2], dry_run=dry_run)
        self.enter_motion(control)
        total = len(page.strokes)
        for number, stroke in enumerate(page.strokes, 1):
            self.xy(stroke.points[0], TRAVEL_FEED, control)
            if not dry_run:
                self.pen(PEN_DOWN, control)
            for point in stroke.points[1:]:
                self.xy(point, feed, control)
            if not dry_run:
                self.pen(PEN_UP, control)
            self.progress(number, total)
        self.pen(PEN_UP, control)
        return self.wait_idle(control, z=PEN_UP)

    def jog(self, offset: Point, area: WorkArea, control: MotionControl):
        state = self.require_idle(control, for_motion=True)
        start = state.position[:2]
        end = machine_point(tuple(a + b for a, b in zip(start, offset, strict=True)))
        area.require(start, "当前笔尖位置")
        area.require(end, "点动终点")
        self.enter_motion(control)
        self.xy(end, TRAVEL_FEED, control)
        return self.wait_idle(control, z=PEN_UP)

    def touch(self, area: WorkArea, control: MotionControl):
        state = self.require_idle(control, for_motion=True)
        area.require(state.position[:2], "试触纸位置")
        self.enter_motion(control)
        self.pen(PEN_DOWN, control)
        self.command("G4 P0.3", control)
        self.pen(PEN_UP, control)
        return self.wait_idle(control, z=PEN_UP)

    def abort(self):
        # Try a controlled halt before clearing queued moves. Position is
        # considered untrusted after reset, even if the controller reports Idle.
        self.motion_active = False
        try:
            self.send("!")
            deadline = monotonic() + 1.2
            while monotonic() < deadline:
                try:
                    status = self.status(timeout=.25)
                    if status.state in {"Idle", "Hold:0", "Alarm"}:
                        break
                except MachineError:
                    pass
        finally:
            self.send("\x18")
