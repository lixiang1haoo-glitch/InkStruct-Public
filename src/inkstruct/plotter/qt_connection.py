"""Exclusive Windows serial access for the N1, isolated from the GUI thread."""

from datetime import datetime, timezone
from queue import Queue
from time import monotonic

from PySide6 import QtCore, QtSerialPort

from .grbl import DEFAULT_WRITE_FEED, PEN_DOWN, GrblLink, MachineError, MotionControl, Stopped

N1_USB_ID = (0x28e9, 0x018a)


def n1_ports():
    return [port for port in QtSerialPort.QSerialPortInfo.availablePorts()
            if (port.vendorIdentifier(), port.productIdentifier()) == N1_USB_ID]


class N1Serial:
    def __init__(self, name):
        info = next((port for port in n1_ports() if port.portName() == name), None)
        if info is None:
            raise OSError("找不到所选的炽写 N1 USB 串口。")
        self.port = QtSerialPort.QSerialPort(info)
        self.buffer = bytearray()
        port = self.port
        configured = (
            port.setBaudRate(115200), port.setDataBits(port.DataBits.Data8),
            port.setParity(port.Parity.NoParity), port.setStopBits(port.StopBits.OneStop),
            port.setFlowControl(port.FlowControl.NoFlowControl),
        )
        if not all(configured) or not port.open(QtCore.QIODevice.OpenModeFlag.ReadWrite):
            raise OSError(f"无法独占打开 {name}。{port.errorString()}")

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


class N1Worker(QtCore.QThread):
    succeeded = QtCore.Signal(str, object)
    failed = QtCore.Signal(str, str, bool)
    phase = QtCore.Signal(str)
    progress = QtCore.Signal(int, int)

    def __init__(self, parent=None, *, serial_factory=N1Serial):
        super().__init__(parent)
        self.serial_factory = serial_factory
        self.requests = Queue()
        self.jog_fault_path = None
        self.control = None
        self.closing = False

    def submit(self, kind, *arguments):
        if self.closing:
            return False
        self.control = MotionControl()
        self.requests.put((kind, arguments, self.control))
        return True

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
                try:
                    if kind == "connect":
                        if link is not None:
                            link.serial.close()
                            link = None
                        link = GrblLink(self.serial_factory(*args), phase=self.phase.emit,
                                        progress=self.progress.emit)
                        result = link.connect()
                    elif link is None:
                        raise MachineError("设备尚未连接。")
                    elif kind == "disconnect":
                        link.serial.close()
                        link = result = None
                    elif kind == "position-datum":
                        result = link.confirm_datum_position(control)
                    elif kind.startswith("position"):
                        result = link.require_idle(control)
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
                        options = settings[0] if settings else {}
                        result = link.run_page(page, area, control, dry_run=kind == "dry", feed=feed, **options)
                    else:
                        raise ValueError(f"无法识别的设备操作：{kind}")
                    if link is not None:
                        link.motion_active = False
                        if link.referenced_idle_xy is not None and result.state == "Idle":
                            link.referenced_idle_xy = result.position[:2]
                    self.succeeded.emit(kind, result)
                except (MachineError, OSError, ValueError) as error:
                    motion = bool(link and link.motion_active)
                    disconnected = motion or not isinstance(error, ValueError)
                    fault = None
                    fault_path = self.jog_fault_path
                    manual = kind in {"jog", "device-jog"}
                    if (link and (manual or motion) and disconnected
                            and fault_path and not isinstance(error, Stopped)):
                        fault = {"time_utc": datetime.now(timezone.utc).isoformat(), "operation": kind,
                                 "pin_review_firmware": link.pin_review, "error": str(error),
                                 "reports_before_stop": list(link.recent_reports)}
                        if manual:
                            fault.update(delta_mm=args[0], range_confirmed=args[1] is not None)
                        else:
                            fault_path = fault_path.with_name("plotter-last-motion-fault.json")
                    if link is not None and disconnected:
                        if motion:
                            try:
                                link.abort()
                                if fault is not None:
                                    fault["reports_at_stop"] = list(link.recent_reports)
                            except (MachineError, OSError):
                                pass
                        link.serial.close()
                        link = None
                    detail = str(error)
                    if motion or isinstance(error, Stopped):
                        detail += " 请检查笔尖、当前位置和纸面对位，再重新连接。"
                    if fault is not None:
                        from ..resource_catalog import atomic_json
                        try:
                            atomic_json(fault_path, fault)
                            detail += f" 本次回包已保存至 {fault_path.name}。"
                        except OSError:
                            pass
                    self.failed.emit(kind, detail, disconnected)
        finally:
            if link is not None:
                link.serial.close()
