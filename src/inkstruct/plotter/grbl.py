"""Blocking Grbl transactions for plotters with Z-axis pen control."""

import errno
import math
import re
from collections import deque
from dataclasses import dataclass, field
from threading import Event, Lock
from time import monotonic, sleep

from .physical import COORDINATE_DECIMALS, MachinePage, WorkArea, axis_trial, machine_point
from .schema import Point

PEN_UP = 0.0
PEN_DOWN = -1.6
Z_TOLERANCE_MM = .05
DEFAULT_WRITE_FEED = 2500
MAX_WRITE_FEED = 5000
XY_TOLERANCE_MM = .075
STATIONARY_TOLERANCE_MM = .01
PIN_INTERIOR_MM = 2.0
RAISED_SEGMENT_MM = .75
MAX_PACKET_LINES = 6
MAX_PENDING_MM = 15.0
STATUS_INTERVAL = .04
ENDPOINT_POLL = .008
WCO_WAIT_SECONDS = 3.


class MachineError(RuntimeError):
    pass


class StatusTimeout(MachineError):
    pass


class CommandRejected(MachineError):
    pass


class PageInterrupted(MachineError):
    """A page operation failed at a known XY, with no queued XY movement."""
    def __init__(self, message, anchor):
        super().__init__(message)
        self.anchor = anchor


def save_stroke_progress(journal, number, before_pen, state, control):
    backoff = (0, .04, .10, .20)
    for attempt, delay in enumerate(backoff, start=1):
        if control.stop_requested.wait(delay):
            raise Stopped("已停止作业。")
        try:
            journal.save(number - int(before_pen), before_pen)
            return
        except OSError as error:
            code = getattr(error, "winerror", None)
            transient = code in (5, 32, 33) if code else error.errno in (errno.EACCES, errno.EBUSY, errno.EAGAIN)
            if not transient or attempt == len(backoff):
                raise PageInterrupted(f"书写进度保存失败，请核对第 {number} 笔。{error}", state) from error


class ExternalHold(MachineError):
    pass


class Stopped(MachineError):
    pass


def validate_feed(value):
    if type(value) is not int or not 60 <= value <= MAX_WRITE_FEED:
        raise ValueError(f"运动速度应在 60–{MAX_WRITE_FEED} mm/min 内。")


@dataclass(frozen=True)
class Status:
    state: str
    position: tuple[float, float, float] | None
    offset: tuple[float, float, float] | None
    limits: str


def position_vector(value: str):
    entries = value.split(",")
    if len(entries) == 2:
        raise MachineError("此设备只报告 X/Y。写字机笔控需要支持 Z 轴升降并报告笔高。")
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
    elif "MPos" in data:
        machine = position_vector(data["MPos"])
        if offset is None:
            return Status(state, None, None, data.get("Pn", ""))
        position = tuple(a - b for a, b in zip(machine, offset, strict=True))
        if not all(math.isfinite(value) for value in position):
            raise MachineError("设备工作坐标不是有限数值。")
    else:
        position = None
    return Status(state, position, offset, data.get("Pn", ""))


@dataclass
class MotionControl:
    interrupted_cleanly: bool = False
    pause_requested: Event = field(default_factory=Event)
    stop_requested: Event = field(default_factory=Event)
    finish_stroke: Event = field(default_factory=Event)
    pause_at_idle: Event = field(default_factory=Event)
    manual_lock: Lock = field(default_factory=Lock)
    requested_height: float | None = None
    accepting_manual: bool = True

    def request_idle_pause(self, height=None):
        with self.manual_lock:
            if not self.accepting_manual or self.stop_requested.is_set():
                return False
            if height is not None:
                if not PEN_DOWN <= height <= PEN_UP or self.requested_height is not None:
                    return False
                self.requested_height = height
            self.pause_at_idle.set()
            return True

    def take_height(self):
        with self.manual_lock:
            height, self.requested_height = self.requested_height, None
            return height

    def resume_idle(self):
        with self.manual_lock:
            if self.requested_height is None:
                self.pause_at_idle.clear()

    def finish_unless_paused(self):
        with self.manual_lock:
            if self.pause_at_idle.is_set():
                return False
            self.accepting_manual = False
            return True


@dataclass
class XYWindow:
    area: WorkArea | None
    z: float
    points: list[Point]
    distance: float = 0.0
    progress: float = 0.0
    seen_run: bool = False

    def arm(self, targets):
        for point in targets:
            self.distance += math.dist(self.points[-1], point)
            self.points.append(point)

    def observe(self, status: Status):
        if status.position is None:
            raise MachineError("运动期间未收到有效坐标。")
        x, y, z = status.position
        self.seen_run |= status.state == "Run"
        point = (x, y)
        if ((self.area is not None and not self.area.contains(point, inset=-XY_TOLERANCE_MM))
                or abs(z - self.z) > Z_TOLERANCE_MM):
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
                    candidates.append(along)
            length += segment
        if candidates:
            self.progress = max(self.progress, min(candidates))
        elif math.dist(point, self.points[-1]) > XY_TOLERANCE_MM:
            raise MachineError("运动坐标偏离已发送的轨迹。")


class GrblLink:
    def __init__(self, serial, *, phase=lambda _phase: None, progress=lambda _done, _total: None, pen_state=lambda _state: None):
        self.paused_seconds = 0.0
        self.serial = serial
        self.phase = phase
        self.progress = progress
        self.pen_state = pen_state
        self.responses = deque()
        self.recent_reports = deque(maxlen=16)
        self.last_status = None
        self.status_count = 0
        self.status_at = 0.0
        self.saw_reset = False
        self.metric = False
        self.motion_active = False
        self.xy_window = None
        self.referenced_idle_xy = None
        self.firmware_report = ""
        self.segment_unbounded_travel = False
        self.packet_bytes = 120

    def send(self, text: str):
        self.serial.write(text.encode("ascii"))

    def motion_time(self):
        return monotonic() - self.paused_seconds

    def pump(self, timeout=.05, *, local_hold=False):
        line = self.serial.readline(timeout)
        if not line:
            return
        line = line.strip()
        if line.startswith("<") or line.lower().startswith(("alarm:", "error:")):
            self.recent_reports.append(line[:512])
        if line.startswith("<"):
            previous = self.last_status.offset if self.last_status else None
            self.last_status = decode_status(line, previous)
            self.status_count += 1
            self.status_at = monotonic()
            if self.metric and previous is not None and self.last_status.offset != previous:
                raise MachineError("设备工作坐标偏置已变化。")
            if self.motion_active:
                state = self.last_status.state
                if state.startswith("Hold") and not local_hold:
                    raise ExternalHold("设备在作业中被外部暂停。")
                if state.split(":")[0] not in {"Idle", "Run", "Hold"}:
                    raise MachineError(f"作业中设备进入 {state} 状态。")
                if self.xy_window is not None:
                    self.xy_window.observe(self.last_status)
        elif line.lower().startswith("error:"):
            raise CommandRejected(f"设备返回 {line}。")
        elif line.lower().startswith("alarm:"):
            raise MachineError(f"设备返回 {line}。")
        elif line.startswith("Grbl"):
            self.saw_reset = True
            if self.last_status is not None:
                raise MachineError("设备已复位，请重新核对工作坐标。")
        elif len(self.responses) < 1024:
            self.responses.append(line)
        else:
            raise MachineError("设备返回了过多的未确认响应。")

    def checkpoint(self, control: MotionControl | None):
        if control is None:
            return False
        if control.stop_requested.is_set():
            raise Stopped("已停止作业。")
        if not control.pause_requested.is_set():
            return False
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
            self.pump(local_hold=True)
            if held and monotonic() - self.status_at > 3:
                raise MachineError("暂停期间未收到设备状态。")
            if not held and self.status_count > generation and self.last_status.state in {"Idle", "Hold:0"}:
                held = True
                self.phase("paused")
        if control.stop_requested.is_set():
            raise Stopped("已停止作业。")
        self.send("~")
        # The N1 can still report Hold:0 after cycle-start. Keep acknowledgements
        # queued and wait for Run/Idle before sending another motion segment.
        generation = self.status_count
        deadline = monotonic() + 5
        next_query = 0.0
        while monotonic() < deadline:
            if control.stop_requested.is_set():
                raise Stopped("已停止作业。")
            if monotonic() >= next_query:
                self.send("?")
                next_query = monotonic() + .1
            self.pump(local_hold=True)
            if self.status_count > generation and self.last_status.state in {"Idle", "Run"}:
                self.paused_seconds += monotonic() - began
                self.phase("running")
                return True
        raise MachineError("继续指令发出后，设备未确认恢复运动。")

    def status(self, control=None, *, timeout=2.5):
        end = self.motion_time() + timeout
        generation = self.status_count
        next_query = 0.0
        while self.motion_time() < end:
            if self.checkpoint(control):
                generation = self.status_count
                next_query = 0.0
            if self.status_count > generation:
                return self.last_status
            if monotonic() >= next_query:
                self.send("?")
                next_query = monotonic() + .25
            self.pump()
        raise StatusTimeout("设备未返回状态。")

    def command(self, command: str, control=None):
        self.checkpoint(control)
        self.send(command + "\n")
        end = self.motion_time() + 15
        lines = []
        while self.motion_time() < end:
            self.checkpoint(control)
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
        try:
            state = self.status()
        except StatusTimeout as error:
            raise StatusTimeout("串口已打开，设备未返回 Grbl 状态。请核对所选串口和通信协议。") from error
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
        self.firmware_report = next((line for line in identity if line.startswith("[VER:")), "")
        hard_limits = [line for line in settings if re.match(r"^\$21\s*=", line)]
        self.segment_unbounded_travel = not (
            len(hard_limits) == 1 and re.fullmatch(r"\$21\s*=\s*1(?:\.0+)?\s*(?:\([^()]*\))?", hard_limits[0])
        )
        for line in identity:
            capacity = re.fullmatch(r"\[OPT:[^,]*,\d+,(\d+)\]", line)
            if capacity and int(capacity[1]) >= 64:
                self.packet_bytes = min(240, int(capacity[1]) - 1)
        status = self.require_idle()
        deadline = monotonic() + WCO_WAIT_SECONDS
        while status.offset is None and monotonic() < deadline:
            sleep(min(.05, max(0., deadline - monotonic())))
            remaining = deadline - monotonic()
            if remaining > 0:
                try:
                    status = self.require_idle(timeout=remaining)
                except StatusTimeout:
                    # This optional query cannot qualify a connection for automatic recovery.
                    break
        return status

    def require_idle(self, control=None, *, for_motion=False, timeout=2.5):
        status = self.status(control, timeout=timeout)
        if not self.metric or status.state != "Idle" or status.position is None:
            raise MachineError(f"需要设备处于 Idle 并返回有效的毫米工作坐标，当前状态为 {status.state}。")
        if (self.referenced_idle_xy is not None
                and math.dist(status.position[:2], self.referenced_idle_xy) > XY_TOLERANCE_MM):
            raise MachineError("设备待机期间的笔位读数已变化，请重新连接并对准机身基准。")
        if for_motion and not PEN_DOWN - Z_TOLERANCE_MM <= status.position[2] <= PEN_UP + Z_TOLERANCE_MM:
            raise MachineError("Z 工作坐标超出升降笔范围，请在设备侧核对笔尖位置。")
        return status

    def confirm_datum_position(self, control):
        first = self.require_idle(control)
        if abs(first.position[2] - PEN_UP) > Z_TOLERANCE_MM:
            raise ValueError("请先抬笔，再记录机身基准。")
        second = self.require_idle(control)
        if (abs(second.position[2] - PEN_UP) > Z_TOLERANCE_MM
                or math.dist(first.position[:2], second.position[:2]) > XY_TOLERANCE_MM):
            raise MachineError("设备读数尚未稳定，请重新连接并对准机身基准。")
        self.referenced_idle_xy = second.position[:2]
        return second

    def wait_idle(self, control, *, z: float, poll=.08, anchor=None):
        end = self.motion_time() + 120
        while self.motion_time() < end:
            self.checkpoint(control)
            status = self.status(control)
            if status.state == "Idle":
                if status.position is None:
                    raise MachineError("设备已空闲，但没有返回笔位。")
                if abs(status.position[2] - z) > Z_TOLERANCE_MM:
                    if anchor is not None and math.dist(anchor.position[:2], status.position[:2]) <= XY_TOLERANCE_MM:
                        raise PageInterrupted("设备已停稳，但笔尖未到达指定高度。", anchor)
                    raise MachineError("设备已空闲，但 Z 工作坐标未到达预期位置。")
                return status
            sleep(poll)
        raise MachineError("等待设备 Idle 超时。")

    def pen(self, height, control):
        try:
            self.command(f"G1 Z{height:g} F5000", control)
        except CommandRejected as error:
            raise MachineError(f"设备拒绝 Z 轴升降笔指令，请核对笔控方式。{error}") from error

    def xy(self, point: Point, feed: int, control):
        self.command(self.xy_command(point, feed), control)

    @staticmethod
    def xy_command(point, feed):
        x, y = point
        return f"G1 X{x:.{COORDINATE_DECIMALS}f} Y{y:.{COORDINATE_DECIMALS}f} F{feed}"

    def send_xy_packet(self, targets, lines, control, next_status):
        self.checkpoint(control)
        if monotonic() - self.status_at > .8:
            self.interrupt_xy(control, 0)
        self.xy_window.arm(targets)
        self.send("\n".join(lines) + "\n")
        remaining = len(lines)
        awaiting_status = 0
        end = self.motion_time() + 15
        while (remaining or awaiting_status > self.status_count) and self.motion_time() < end:
            self.checkpoint(control)
            now = monotonic()
            if now - self.status_at > .8:
                self.interrupt_xy(control, remaining)
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

    def interrupt_xy(self, control, remaining):
        # Stop adding segments. Account for every outstanding acknowledgement
        # before using the GRBL planner barrier, including on closed paths.
        deadline = monotonic() + 2.5
        while remaining and monotonic() < deadline:
            self.checkpoint(control)
            if self.responses:
                remaining -= int(self.responses.popleft() == "ok")
            else:
                self.pump(.025)
        if remaining:
            raise MachineError("运动回报超时，已发笔段仍有未确认的指令。")
        self.command("G4 P0", control)
        state = self.status(control)
        if (state.state != "Idle" or state.position is None or state.offset is None
                or math.dist(state.position[:2], self.xy_window.points[-1]) > XY_TOLERANCE_MM):
            raise MachineError("运动回报超时，未确认已发笔段的终点。")
        raise PageInterrupted("运动回报超时，本次运动已中断。", state)

    def xy_status(self, control):
        try:
            return self.status(control, timeout=.5)
        except StatusTimeout:
            self.interrupt_xy(control, 0)

    def finish_xy(self, window, feed, control):
        end = self.motion_time() + (window.distance - window.progress) * 60 / feed + 1.5
        while self.motion_time() < end:
            self.checkpoint(control)
            status = self.xy_status(control)
            if status.state == "Idle" and math.dist(status.position[:2], window.points[-1]) <= XY_TOLERANCE_MM:
                # A closed path may end at its initial coordinate before the
                # first Run report. GRBL's zero dwell is a planner barrier.
                ambiguous_endpoint = (not window.seen_run and window.distance > XY_TOLERANCE_MM and
                                      math.dist(window.points[0], window.points[-1]) <= XY_TOLERANCE_MM)
                if ambiguous_endpoint:
                    self.command("G4 P0", control)
                    sleep(.025)
                    status = self.status(control, timeout=.5)
                    if (status.state != "Idle" or
                            math.dist(status.position[:2], window.points[-1]) > XY_TOLERANCE_MM):
                        raise MachineError("设备到位复核未通过。")
                return status
            sleep(ENDPOINT_POLL)
        raise MachineError("设备没有到达已发送行程的终点。")

    def bounded_pen_up(self, state, points, feed, control):
        """Keep at most one short raised segment outstanding without a measured work area."""
        try:
            for end in points:
                start = state.position[:2]
                steps = math.ceil(math.dist(start, end) / RAISED_SEGMENT_MM)
                for index in range(1, steps + 1):
                    target = machine_point(tuple(a + (b - a) * index / steps
                                                 for a, b in zip(start, end, strict=True)))
                    window = XYWindow(None, PEN_UP, [state.position[:2]])
                    self.xy_window = window
                    self.send_xy_packet([target], [self.xy_command(target, feed)], control, monotonic())
                    state = self.finish_xy(window, feed, control)
                    self.xy_window = None
                    state = self.manual_at_rest(state, control)
            return state
        finally:
            self.xy_window = None

    def move_path(self, state, points, area, feed, z, control, *, segment_travel=True):
        state = self.manual_at_rest(state, control)
        if self.segment_unbounded_travel and segment_travel and area is None and z == PEN_UP:
            return self.bounded_pen_up(state, points, feed, control)
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
                window = self.xy_window = XYWindow(area, z, [state.position[:2]])
                no_progress_until = self.motion_time() + 1.5 + MAX_PENDING_MM * 60 / feed
                while pending:
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
                        if control.pause_at_idle.is_set():
                            break
                        no_progress_until = self.motion_time() + 1.5 + MAX_PENDING_MM * 60 / feed
                    else:
                        end = self.xy_status(control)
                        if end.state == "Idle":
                            if math.dist(end.position[:2], origin) > XY_TOLERANCE_MM:
                                raise MachineError("设备已空闲，但没有到达排队行程的终点。")
                            if not window.seen_run and math.dist(window.points[0], origin) <= XY_TOLERANCE_MM:
                                self.finish_xy(window, feed, control)
                            window.progress = window.distance
                        if self.motion_time() >= no_progress_until:
                            raise MachineError("设备未继续沿已发送的轨迹移动。")
                        sleep(.016)
                state = self.finish_xy(window, feed, control)
                self.xy_window = None
                state = self.manual_at_rest(state, control)
            return state
        finally:
            self.xy_window = None

    def verify_rest(self, control, expected):
        fresh = self.status(control)
        if (fresh.state != "Idle" or not fresh.position or
                fresh.offset != expected.offset or expected.state != "Idle" or
                math.dist(fresh.position, expected.position) > STATIONARY_TOLERANCE_MM):
            raise MachineError("笔尖未确认停稳，或设备坐标已变化。")
        return fresh

    def change_height(self, state, target, control):
        if not PEN_DOWN <= target <= PEN_UP:
            raise ValueError("笔尖高度超出设备支持的范围。")
        if not PEN_DOWN - Z_TOLERANCE_MM <= state.position[2] <= PEN_UP + Z_TOLERANCE_MM:
            raise MachineError("当前 Z 坐标超出升降笔范围。")
        self.pen(target, control)
        result = self.wait_idle(control, z=target)
        if math.dist(state.position[:2], result.position[:2]) > STATIONARY_TOLERANCE_MM:
            raise MachineError("升降笔过程中 XY 已变化，请重新核对位置。")
        return result

    def manual_at_rest(self, state, control):
        if not control.pause_at_idle.is_set():
            return state
        anchor = state.position[:2]
        original_z = min(PEN_UP, max(PEN_DOWN, state.position[2]))
        state = self.verify_rest(control, state)
        self.phase("paused")
        self.pen_state(state)
        while control.pause_at_idle.is_set():
            self.checkpoint(control)
            target = control.take_height()
            if target is not None:
                state = self.change_height(state, target, control)
                self.pen_state(state)
            if control.stop_requested.wait(.05):
                raise Stopped("已停止作业。")
            state = self.verify_rest(control, state)
            if math.dist(state.position[:2], anchor) > STATIONARY_TOLERANCE_MM:
                raise MachineError("暂停期间 XY 已变化，请重新核对位置。")
        self.checkpoint(control)
        # The user explicitly resumed. Restore the interrupted path's pen height
        # at the verified stationary XY before admitting further segments.
        if abs(state.position[2] - original_z) > Z_TOLERANCE_MM:
            state = self.change_height(state, original_z, control)
        self.phase("running")
        return state

    def park_interrupted_page(self, anchor, control, area, dock, feed):
        self.referenced_idle_xy = anchor.position[:2]
        state = self.set_pen(False, area, control)
        if dock is None or state.offset is None or (area is not None and not (
                area.contains(state.position[:2]) and area.contains(dock))):
            return state, False
        state = self.move_path(state, (machine_point(dock),), area, feed, PEN_UP, control)
        state = self.verify_rest(control, state)
        if math.dist(state.position[:2], dock) > XY_TOLERANCE_MM:
            raise MachineError("未确认到达停靠点。")
        return state, True

    def enter_motion(self, control, *, anchor=None):
        self.motion_active = True
        self.phase("running")
        self.command("G21 G90 G94", control)
        self.pen(PEN_UP, control)
        return self.wait_idle(control, z=PEN_UP, anchor=anchor)

    def run_page(self, page: MachinePage, area: WorkArea | None, control: MotionControl, *,
                 dry_run=False, feed=DEFAULT_WRITE_FEED, state=None,
                 segment_travel=True, commissioning=False, height=PEN_DOWN, start=0, journal=None):
        validate_feed(feed)
        if not PEN_DOWN <= height <= -.1 or not 0 <= start <= len(page.strokes):
            raise ValueError('笔高或续写笔序无效。')
        segment_travel = segment_travel and not commissioning
        if state is None:
            state = self.require_idle(control, for_motion=True)
        page.check(area, state.position[:2], dry_run=dry_run)
        state = self.enter_motion(control, anchor=state)
        total = len(page.strokes)
        for number, stroke in enumerate(page.strokes[start:], start + 1):
            state = self.move_path(state, stroke.points[:1], area, feed, PEN_UP, control,
                                   segment_travel=segment_travel)
            if not dry_run:
                if journal is not None:
                    save_stroke_progress(journal, number, True, state, control)
                self.pen(height, control)
                state = self.wait_idle(control, z=height, poll=ENDPOINT_POLL, anchor=state)
            state = self.move_path(state, stroke.points[1:], area, feed,
                                   PEN_UP if dry_run else height, control, segment_travel=segment_travel)
            if not dry_run:
                self.pen(PEN_UP, control)
                state = self.wait_idle(control, z=PEN_UP, poll=ENDPOINT_POLL, anchor=state)
                if journal is not None:
                    save_stroke_progress(journal, number, False, state, control)
            self.progress(number, total)
            if not dry_run and number < total and control.finish_stroke.is_set():
                self.motion_active = False
                control.interrupted_cleanly = True
                return state
        self.pen(PEN_UP, control)
        return self.wait_idle(control, z=PEN_UP, anchor=state)

    def trial_axes(self, axes, area, feed, control, *, confirmed_area=None):
        state = self.require_idle(control, for_motion=True)
        page = axis_trial(axes.register((0, 0), state.position[:2]))
        if confirmed_area is not None and area is not None and area != confirmed_area:
            page.check(area, state.position[:2])
        return self.run_page(page, confirmed_area or area, control, feed=feed,
                             state=state, segment_travel=False)

    def jog(self, offset: Point, area: WorkArea | None, control: MotionControl, *,
            feed=DEFAULT_WRITE_FEED, commissioning=False, require_bounds=False, range_disabled=False):
        state = self.require_idle(control, for_motion=True)
        start = state.position[:2]
        end = machine_point(tuple(a + b for a, b in zip(start, offset, strict=True)))
        if require_bounds and area is None:
            raise ValueError("此步长需要已确认的工作范围。")
        return self.move_from(start, end, area, control, feed=feed,
                              segment_travel=range_disabled or not commissioning)

    def move_to(self, target: Point, area: WorkArea | None, control: MotionControl, *, feed=DEFAULT_WRITE_FEED):
        state = self.require_idle(control, for_motion=True)
        return self.move_from(state.position[:2], machine_point(target), area, control, feed=feed)

    def move_from(self, start, end, area, control, *, feed=DEFAULT_WRITE_FEED, segment_travel=True):
        validate_feed(feed)
        if area is not None:
            area.require(start, "当前笔尖位置")
            area.require(end, "点动终点")
        state = self.enter_motion(control)
        if math.dist(start, state.position[:2]) > XY_TOLERANCE_MM:
            raise MachineError("抬笔后起点坐标变化，运动已停止。")
        return self.move_path(state, (end,), area, feed, PEN_UP, control, segment_travel=segment_travel)

    def set_pen(self, down: bool, area: WorkArea | None, control: MotionControl, *, height=PEN_DOWN):
        if not PEN_DOWN <= height <= 0:
            raise ValueError('笔尖高度超出设备支持的范围。')
        state = self.require_idle(control, for_motion=True)
        if down and area is not None:
            area.require(state.position[:2], "落笔位置")
        self.motion_active = True
        self.phase("running")
        height = height if down else PEN_UP
        self.command("G21 G90 G94", control)
        return self.change_height(state, height, control)

    def touch(self, area: WorkArea | None, control: MotionControl):
        state = self.require_idle(control, for_motion=True)
        if area is not None:
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
                        return status
                except MachineError:
                    pass
        finally:
            self.send("\x18")
