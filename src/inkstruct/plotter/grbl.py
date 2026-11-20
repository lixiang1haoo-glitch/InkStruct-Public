"""Blocking Grbl transactions for the N1. The owning worker holds the serial port."""

import logging
import math
import re
from collections import deque
from dataclasses import dataclass, field
from threading import Event
from time import monotonic, sleep

from .physical import COORDINATE_DECIMALS, MachinePage, WorkArea, axis_trial, machine_point
from .schema import Point

PEN_UP = 0.0
PEN_DOWN = -1.6
Z_TOLERANCE_MM = .05
TRAVEL_FEED = 1500
DEFAULT_WRITE_FEED = 2500
MAX_WRITE_FEED = 5000
XY_TOLERANCE_MM = .075
PIN_INTERIOR_MM = 2.0
MAX_PACKET_LINES = 6
MAX_PENDING_MM = 15.0
STATUS_INTERVAL = .04
LOG = logging.getLogger(__name__)


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


@dataclass
class XYWindow:
    area: WorkArea
    z: float
    points: list[Point]
    distance: float = 0.0
    progress: float = 0.0
    last_progress: float = field(default_factory=monotonic)
    pin: str = ""
    seen_run: bool = False
    review_pins: bool = True

    def arm(self, targets):
        for point in targets:
            self.distance += math.dist(self.points[-1], point)
            self.points.append(point)

    def observe(self, status: Status, qualified: bool):
        if status.position is None:
            raise MachineError("运动期间未收到有效坐标。")
        x, y, z = status.position
        self.seen_run |= status.state == "Run"
        point = (x, y)
        if not self.area.contains(point, inset=-XY_TOLERANCE_MM) or abs(z - self.z) > Z_TOLERANCE_MM:
            raise MachineError("运动坐标偏离已确认的工作范围或笔高。")

        # Use the earliest valid projection, so a nearby later segment cannot
        # release send credit before the earlier segment has been traversed.
        length = 0.0
        candidates = []
        for a, b in zip(self.points, self.points[1:]):
            dx, dy = b[0] - a[0], b[1] - a[1]
            segment = math.hypot(dx, dy)
            if not segment:
                continue
            fraction = min(1.0, max(0.0, ((x - a[0]) * dx + (y - a[1]) * dy) / segment**2))
            along = length + fraction * segment
            if along >= self.progress - XY_TOLERANCE_MM:
                deviation = math.dist(point, (a[0] + fraction * dx, a[1] + fraction * dy))
                if deviation <= XY_TOLERANCE_MM:
                    moving_both = min(abs(dx), abs(dy)) > .001
                    candidates.append((along, moving_both))
            length += segment
        along, moving_both = min(candidates, default=(self.progress, False))
        if candidates:
            if along > self.progress + .015:
                self.progress = along
                self.last_progress = monotonic()
        elif math.dist(point, self.points[-1]) > XY_TOLERANCE_MM:
            raise MachineError("运动坐标偏离已发送的轨迹。")

        axes = set(status.limits) & set("XYZ")
        if axes:
            if (not qualified or not self.review_pins or status.limits not in {"X", "Y", "XY", "YX"}
                    or status.state not in {"Run", "Idle"} or (len(axes) == 2 and not moving_both)
                    or not self.area.contains(point, inset=PIN_INTERIOR_MM)
                    or not all(self.area.contains(p, inset=PIN_INTERIOR_MM) for p in self.points)):
                raise MachineError(f"作业中设备报告了轴限位（Pn:{status.limits}）。")
            if not self.pin:
                self.pin = status.limits
                self.last_progress = monotonic()
                LOG.warning("N1 reported Pn:%s at %s; verifying the queued path", self.pin, point)
            else:
                self.pin = "".join(sorted(set(self.pin) | axes))
        if self.pin and status.state == "Run" and monotonic() - self.last_progress > .45:
            raise MachineError(f"限位复核期间未检测到运动进展（Pn:{self.pin}）。")


class GrblLink:
    def __init__(self, serial, *, phase=lambda _phase: None, progress=lambda _done, _total: None):
        self.serial = serial
        self.phase = phase
        self.progress = progress
        self.responses = deque()
        self.last_status = None
        self.status_count = 0
        self.status_at = 0.0
        self.metric = False
        self.motion_active = False
        self.xy_window = None
        self.pin_review = False
        self.packet_bytes = 120

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
            self.status_at = monotonic()
            if self.metric and previous is not None and self.last_status.offset != previous:
                raise MachineError("设备工作坐标偏置已变化。")
            if self.motion_active:
                state = self.last_status.state
                if state.split(":")[0] not in {"Idle", "Run", "Hold"}:
                    raise MachineError(f"作业中设备进入 {state} 状态。")
                if self.xy_window is not None:
                    self.xy_window.observe(self.last_status, self.pin_review)
                elif set(self.last_status.limits) & set("XYZ"):
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
        # CX-Elite can send a startup acknowledgement before the first status.
        # No line command has been sent on this connection yet.
        self.responses.clear()
        settings = self.command("$$")
        # CX-Elite appends the setting description after the numeric value.
        unit_settings = [line for line in settings if re.match(r"^\$13\s*=", line)]
        if len(unit_settings) != 1 or not re.fullmatch(
            r"\$13\s*=\s*0(?:\.0+)?\s*(?:\([^()]*\))?", unit_settings[0]
        ):
            raise MachineError("无法确认设备状态使用毫米。请在设备侧核对 Grbl 的 $13 设置。")
        self.metric = True
        identity = self.command("$I")
        self.pin_review = ("[VER:1.1f / CX-Elite V2.1.003:]" in identity and
                           any(re.fullmatch(r"\$21\s*=\s*0(?:\.0+)?\s*(?:\([^()]*\))?", line)
                               for line in settings))
        for line in identity:
            capacity = re.fullmatch(r"\[OPT:[^,]*,\d+,(\d+)\]", line)
            if capacity and int(capacity[1]) >= 64:
                self.packet_bytes = min(240, int(capacity[1]) - 1)
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

    def wait_idle(self, control, *, z: float, poll=.08):
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
            sleep(poll)
        raise MachineError("等待设备 Idle 超时。")

    def pen(self, height, control):
        self.command(f"G1 Z{height:g} F5000", control)

    def xy(self, point: Point, feed: int, control):
        self.command(self.xy_command(point, feed), control)

    @staticmethod
    def xy_command(point, feed):
        x, y = point
        return f"G1 X{x:.{COORDINATE_DECIMALS}f} Y{y:.{COORDINATE_DECIMALS}f} F{feed}"

    def send_xy_packet(self, targets, lines, control, next_status):
        self.checkpoint(control)
        self.xy_window.arm(targets)
        self.send("\n".join(lines) + "\n")
        remaining = len(lines)
        awaiting_status = 0
        end = monotonic() + 15
        while (remaining or awaiting_status > self.status_count) and monotonic() < end:
            end += self.checkpoint(control)
            now = monotonic()
            if now - self.status_at > .8:
                raise MachineError("运动期间未收到设备状态。")
            if remaining and awaiting_status <= self.status_count and now >= next_status:
                awaiting_status = self.status_count + 1
                self.send("?")
                next_status = now + STATUS_INTERVAL
            if self.responses:
                if self.responses.popleft() == "ok":
                    remaining -= 1
            else:
                self.pump(.012)
        if remaining or awaiting_status > self.status_count:
            raise MachineError("设备未确认所有已发送的笔段。")
        return next_status

    def finish_xy(self, window, feed, control):
        end = monotonic() + (window.distance - window.progress) * 60 / feed + 1.5
        while monotonic() < end:
            end += self.checkpoint(control)
            status = self.status(control, timeout=.5)
            if status.state == "Idle" and math.dist(status.position[:2], window.points[-1]) <= XY_TOLERANCE_MM:
                # A closed path may end at its initial coordinate before the
                # first Run report. GRBL's zero dwell is a planner barrier.
                ambiguous_endpoint = (not window.seen_run and window.distance > XY_TOLERANCE_MM and
                                      math.dist(window.points[0], window.points[-1]) <= XY_TOLERANCE_MM)
                if ambiguous_endpoint:
                    self.command("G4 P0", control)
                if window.pin or ambiguous_endpoint:
                    sleep(.025)
                    status = self.status(control, timeout=.5)
                    if (status.state != "Idle" or status.limits or
                            math.dist(status.position[:2], window.points[-1]) > XY_TOLERANCE_MM):
                        raise MachineError("设备到位复核未通过" + (f"（Pn:{window.pin}）。" if window.pin else "。"))
                    if window.pin:
                        LOG.info("N1 Pn:%s cleared at the verified endpoint %s", window.pin, window.points[-1])
                return status
            if status.state.startswith("Hold"):
                raise MachineError("设备在作业中被外部暂停。")
            sleep(.016)
        raise MachineError("设备没有到达已发送行程的终点。")

    def move_path(self, state, points, area, feed, z, control, *, review_pins=True):
        start = state.position[:2]
        pending = deque()
        for point in points:
            steps = math.ceil(math.dist(start, point) / (MAX_PENDING_MM / 2))
            pending.extend(machine_point(tuple(a + (b - a) * i / steps for a, b in zip(start, point, strict=True)))
                           for i in range(1, steps + 1))
            start = point
        next_status = monotonic()
        try:
            while pending:
                window = self.xy_window = XYWindow(area, z, [state.position[:2]], review_pins=review_pins)
                no_progress_until = monotonic() + 1.5 + MAX_PENDING_MM * 60 / feed
                while pending and not window.pin:
                    origin = window.points[-1]
                    distance = window.distance - window.progress
                    targets, lines = [], []
                    size = 0
                    while pending and len(lines) < MAX_PACKET_LINES:
                        target = pending[0]
                        segment = math.dist(origin, target)
                        line = self.xy_command(target, feed)
                        if distance + segment > MAX_PENDING_MM or size + len(line) + 1 > self.packet_bytes:
                            break
                        targets.append(pending.popleft())
                        lines.append(line)
                        origin = target
                        distance += segment
                        size += len(line) + 1
                    if lines:
                        next_status = self.send_xy_packet(targets, lines, control, next_status)
                        no_progress_until = monotonic() + 1.5 + MAX_PENDING_MM * 60 / feed
                    else:
                        end = self.status(control, timeout=.5)
                        if end.state == "Idle":
                            if math.dist(end.position[:2], origin) > XY_TOLERANCE_MM:
                                raise MachineError("设备已空闲，但没有到达排队行程的终点。")
                            if not window.seen_run and math.dist(window.points[0], origin) <= XY_TOLERANCE_MM:
                                self.finish_xy(window, feed, control)
                            window.progress = window.distance
                        if monotonic() >= no_progress_until:
                            raise MachineError("设备未继续沿已发送的轨迹移动。")
                        sleep(.016)
                state = self.finish_xy(window, feed, control)
            return state
        finally:
            self.xy_window = None

    def enter_motion(self, control):
        self.motion_active = True
        self.phase("running")
        self.command("G21 G90 G94", control)
        self.pen(PEN_UP, control)
        return self.wait_idle(control, z=PEN_UP)

    def run_page(self, page: MachinePage, area: WorkArea, control: MotionControl, *,
                 dry_run=False, feed=DEFAULT_WRITE_FEED, state=None, review_pins=True):
        if type(feed) is not int or not 60 <= feed <= MAX_WRITE_FEED:
            raise ValueError(f"书写速度应在 60–{MAX_WRITE_FEED} mm/min 内。")
        if state is None:
            state = self.require_idle(control, for_motion=True)
        page.check(area, state.position[:2], dry_run=dry_run)
        state = self.enter_motion(control)
        total = len(page.strokes)
        for number, stroke in enumerate(page.strokes, 1):
            state = self.move_path(state, stroke.points[:1], area, TRAVEL_FEED, PEN_UP, control,
                                   review_pins=review_pins)
            if not dry_run:
                self.pen(PEN_DOWN, control)
                state = self.wait_idle(control, z=PEN_DOWN, poll=.02)
            state = self.move_path(state, stroke.points[1:], area, feed, PEN_UP if dry_run else PEN_DOWN, control,
                                   review_pins=review_pins)
            if not dry_run:
                self.pen(PEN_UP, control)
                state = self.wait_idle(control, z=PEN_UP, poll=.02)
            self.progress(number, total)
        self.pen(PEN_UP, control)
        return self.wait_idle(control, z=PEN_UP)

    def trial_axes(self, axes, area, feed, control):
        state = self.require_idle(control, for_motion=True)
        page = axis_trial(axes.register((0, 0), state.position[:2]))
        if area is None:
            x, y = zip(*(point for stroke in page.strokes for point in stroke.points), strict=True)
            area = WorkArea(min(x) - .1, min(y) - .1, max(x) + .1, max(y) + .1)
        return self.run_page(page, area, control, feed=feed, state=state, review_pins=False)

    def jog(self, offset: Point, area: WorkArea | None, control: MotionControl):
        state = self.require_idle(control, for_motion=True)
        start = state.position[:2]
        end = machine_point(tuple(a + b for a, b in zip(start, offset, strict=True)))
        if area is None:
            # Device-manager diagnostics use only the requested travel envelope.
            # Hardware limits and every moving-axis pin report still stop motion.
            x, y = zip(start, end, strict=True)
            area = WorkArea(min(x) - .1, min(y) - .1, max(x) + .1, max(y) + .1)
            return self.move_from(start, end, area, control, review_pins=False)
        return self.move_from(start, end, area, control)

    def move_to(self, target: Point, area: WorkArea, control: MotionControl):
        state = self.require_idle(control, for_motion=True)
        return self.move_from(state.position[:2], machine_point(target), area, control)

    def move_from(self, start, end, area, control, *, review_pins=True):
        area.require(start, "当前笔尖位置")
        area.require(end, "点动终点")
        state = self.enter_motion(control)
        return self.move_path(state, (end,), area, TRAVEL_FEED, PEN_UP, control, review_pins=review_pins)

    def set_pen(self, down: bool, area: WorkArea, control: MotionControl):
        state = self.require_idle(control, for_motion=True)
        if down:
            area.require(state.position[:2], "落笔位置")
        self.motion_active = True
        self.phase("running")
        height = PEN_DOWN if down else PEN_UP
        self.command("G21 G90 G94", control)
        self.pen(height, control)
        return self.wait_idle(control, z=height)

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
