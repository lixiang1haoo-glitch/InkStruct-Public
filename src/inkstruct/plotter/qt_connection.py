"""Exclusive plotter serial access, isolated from the GUI thread."""

from datetime import datetime, timezone
from math import dist
from queue import Queue
from time import monotonic

from PySide6 import QtCore, QtSerialPort

from .grbl import DEFAULT_WRITE_FEED, PEN_DOWN, STATIONARY_TOLERANCE_MM, ExternalHold, GrblLink, MachineError, MotionControl, PageInterrupted, Stopped


def serial_ports():
    return QtSerialPort.QSerialPortInfo.availablePorts()


def port_category(info):
    """Classify passive enumeration data; opening the selected port is a separate action."""
    ids = (getattr(info, "vendorIdentifier", lambda: 0)(),
           getattr(info, "productIdentifier", lambda: 0)())
    if ids == (0x28E9, 0x018A):
        return "已识别的写字机"
    description = info.description().strip().casefold()
    if not any(ids) and (description in {"通信端口", "通讯端口", "communications port"}
                         or "bluetooth" in description or "蓝牙" in description):
        return "其他串口"
    return "待识别设备"


class N1Serial:
    def __init__(self, name):
        info = next((port for port in serial_ports() if port.portName() == name), None)
        if info is None:
            raise OSError(f"找不到所选串口 {name}。请刷新串口列表。")
        self.usb_serial = info.serialNumber()
        self.port = QtSerialPort.QSerialPort(info)
        self.buffer = bytearray()
        port = self.port
        configured = (
            port.setBaudRate(115200), port.setDataBits(port.DataBits.Data8),
            port.setParity(port.Parity.NoParity), port.setStopBits(port.StopBits.OneStop),
            port.setFlowControl(port.FlowControl.NoFlowControl),
        )
        if not all(configured):
            raise OSError(f"无法配置串口 {name}。{port.errorString()}")
        if not port.open(QtCore.QIODevice.OpenModeFlag.ReadWrite):
            if port.error() == port.SerialPortError.PermissionError:
                raise OSError(f"串口 {name} 被占用或无访问权限。{port.errorString()}")
            raise OSError(f"无法打开串口 {name}。{port.errorString()}")

    def write(self, data):
        if self.port.write(data) != len(data):
            raise OSError(self.port.errorString())
        while self.port.bytesToWrite():
            if not self.port.waitForBytesWritten(200):
                raise OSError("串口发送超时或设备已断开。")

    def readline(self, timeout):
        deadline = monotonic() + timeout
        while b"\n" not in self.buffer:
            if not self.port.bytesAvailable():
                remaining = deadline - monotonic()
                if remaining <= 0:
                    return None
                if not self.port.waitForReadyRead(max(1, int(remaining * 1000))):
                    if self.port.error() not in (self.port.SerialPortError.NoError,
                                                self.port.SerialPortError.TimeoutError):
                        raise OSError(self.port.errorString())
                    return None
            self.buffer.extend(bytes(self.port.readAll()))
            if len(self.buffer) > 65536:
                raise OSError("设备响应超过串口缓冲上限。")
        line, _, rest = self.buffer.partition(b"\n")
        self.buffer = rest
        return line.decode("ascii", errors="replace").strip()

    def close(self):
        self.port.close()

    @property
    def unavailable(self):
        errors = QtSerialPort.QSerialPort.SerialPortError
        return not self.port.isOpen() or self.port.error() in (errors.ResourceError, errors.DeviceNotFoundError)


class N1Worker(QtCore.QThread):
    succeeded = QtCore.Signal(str, object)
    failed = QtCore.Signal(str, str, bool)
    pen_state = QtCore.Signal(object, object)
    phase = QtCore.Signal(str)
    progress = QtCore.Signal(int, int)

    def __init__(self, parent=None, *, serial_factory=N1Serial):
        super().__init__(parent)
        self.serial_factory = serial_factory
        self.requests = Queue()
        self.jog_fault_path = None
        self.stopped_at = self.closed_idle = None
        self.control = None
        self.closing = False
        self.retained_port = None

    def submit(self, kind, *arguments):
        if self.closing:
            return False
        self.control = MotionControl()
        self.requests.put((kind, arguments, self.control))
        return True

    def restore_idle_reference(self, xy):
        # Ordered ahead of any subsequent motion submitted by the GUI.
        self.requests.put(("restore-idle-reference", (xy,), None))

    def shutdown(self):
        if not self.closing:
            self.closing = True
            if self.control is not None:
                self.control.stop_requested.set()
            self.requests.put(None)

    def run(self):
        link = None
        try:
            while (request := self.requests.get()) is not None:
                kind, args, control = request
                if kind == "restore-idle-reference":
                    if link is not None and not self.retained_port:
                        link.referenced_idle_xy = args[0]
                    continue
                self.page_failure = None
                self.stopped_at = None
                try:
                    if kind == "connect":
                        if link is not None and self.retained_port != args[0]:
                            raise ValueError("请先断开当前串口。")
                        recovering = link is not None
                        port_name = args[0]
                        serial = link.serial if recovering else self.serial_factory(port_name)
                        expected_serial = args[1] if len(args) > 1 else ""
                        link = GrblLink(serial, phase=self.phase.emit,
                                        progress=self.progress.emit,
                                        pen_state=lambda state: self.pen_state.emit(control, state))
                        if len(args) > 1 and getattr(serial, "usb_serial", expected_serial) != expected_serial:
                            raise MachineError("USB 设备与档案不符，请断开串口后重新选择写字机。")
                        result = link.connect()
                        fresh = link.require_idle()
                        self.stable_on_connect = (result.offset is not None and fresh.offset == result.offset
                                                  and dist(result.position, fresh.position) <= STATIONARY_TOLERANCE_MM)
                        result = fresh
                        self.reset_on_connect = recovering or link.saw_reset
                        self.retained_port = None
                    elif link is None:
                        raise MachineError("设备尚未连接。")
                    elif kind == "disconnect":
                        if not self.retained_port:
                            self.stopped_at = link.verify_rest(control, link.require_idle(control))
                        link.serial.close()
                        link = result = None
                        self.retained_port = None
                    elif self.retained_port:
                        raise ValueError("请先重新读取设备状态。")
                    elif kind == "position-datum":
                        result = link.confirm_datum_position(control)
                    elif kind.startswith("position"):
                        result = link.require_idle(control)
                        if result.offset is None and kind == "position-read":
                            raise ValueError("设备尚未报告工作坐标偏置，请稍后再记录原点。")
                    elif kind in {"jog", "device-jog"}:
                        offset, area = args[:2]
                        option = args[2] if len(args) >= 3 else DEFAULT_WRITE_FEED
                        # Older callers used the third argument to require a confirmed rectangle.
                        feed = DEFAULT_WRITE_FEED if type(option) is bool else option
                        result = link.jog(offset, area, control, commissioning=kind == "device-jog",
                                          require_bounds=option is True, feed=feed,
                                          range_disabled=len(args) == 4 and args[3] is True)
                    elif kind in {"return", "page-return"}:
                        target, area = args[:2]
                        feed = args[2] if len(args) == 3 else DEFAULT_WRITE_FEED
                        result = link.move_to(target, area, control, feed=feed)
                    elif kind == "calibrate-height":
                        height, area = args
                        result = link.set_pen(True, area, control, height=height)
                    elif kind == "calibrate-line":
                        page, area, feed, height = args
                        result = link.run_page(page, area, control, feed=feed, height=height)
                    elif kind == "pen":
                        down, area = args[:2]
                        height = args[2] if len(args) == 3 else PEN_DOWN
                        result = link.set_pen(down, area, control, height=height)
                    elif kind == "touch":
                        result = link.touch(*args, control)
                    elif kind == "axis-trial":
                        axes, area, feed, confirmed_area = args
                        result = link.trial_axes(axes, area, feed, control, confirmed_area=confirmed_area)
                    elif kind in {"dry", "write"}:
                        page, area, feed, *settings = args
                        options = dict(settings[0]) if settings else {}
                        dock = options.pop("failure_dock", None)
                        try:
                            result = link.run_page(page, area, control, dry_run=kind == "dry", feed=feed, **options)
                        except PageInterrupted as error:
                            self.page_failure = str(error)
                            result, parked = link.park_interrupted_page(error.anchor, control, area, dock, feed)
                            self.page_failure += (" 已确认抬笔回停靠点。" if parked else
                                                  " 已原地抬笔。请核对停靠点和工作范围。")
                    else:
                        raise ValueError(f"无法识别的设备操作：{kind}")
                    if link is not None:
                        while not control.finish_unless_paused():
                            result = link.manual_at_rest(result, control)
                        link.motion_active = False
                        if link.referenced_idle_xy is not None and result.state == "Idle":
                            link.referenced_idle_xy = result.position[:2]
                    self.succeeded.emit(kind, result)
                # A failed request must not unwind the serial owner's event loop.
                except Exception as error:
                    motion = bool(link and link.motion_active)
                    session_lost = motion or not isinstance(error, ValueError)
                    fault = None
                    fault_path = self.jog_fault_path
                    manual = kind in {"jog", "device-jog"}
                    if (link and (manual or motion) and session_lost
                            and fault_path and not isinstance(error, Stopped)):
                        fault = {"time_utc": datetime.now(timezone.utc).isoformat(), "operation": kind,
                                 "firmware_report": link.firmware_report, "error": str(error),
                                 "reports_before_stop": list(link.recent_reports)}
                        if manual:
                            fault.update(delta_mm=args[0], range_confirmed=args[1] is not None)
                        else:
                            fault_path = fault_path.with_name("plotter-last-motion-fault.json")
                    if link is not None and session_lost:
                        unavailable = getattr(link.serial, "unavailable", False)
                        if motion and not unavailable:
                            try:
                                link.abort()
                                if fault is not None:
                                    fault["reports_at_stop"] = list(link.recent_reports)
                            except Exception as stop_error:
                                if fault is not None:
                                    fault["stop_error"] = str(stop_error)
                        self.retained_port = port_name
                    detail = (self.page_failure + " " if self.page_failure else "") + str(error)
                    if self.retained_port and getattr(link.serial, "unavailable", False):
                        detail += " 当前串口不可用，请检查 USB，手动断开串口后重新连接。"
                    elif self.retained_port:
                        detail += " 串口已保留。请检查笔尖与设备，然后重新读取状态。"
                    elif motion or isinstance(error, Stopped):
                        detail += " 请检查笔尖、当前位置和纸面对位，再重新连接。"
                    if fault is not None:
                        from ..resource_catalog import atomic_json
                        try:
                            atomic_json(fault_path, fault)
                            detail += f" 本次回包已保存至 {fault_path.name}。"
                        except Exception as log_error:
                            detail += f" 本次故障记录未保存：{log_error}"
                    self.failed.emit(kind, detail, session_lost)
        finally:
            if link is not None:
                try:
                    if not self.retained_port:
                        self.closed_idle = link.verify_rest(None, link.require_idle())
                except (ValueError, MachineError, OSError):
                    self.closed_idle = None
                finally:
                    link.serial.close()
