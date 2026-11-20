"""Control a USB-connected N1 from the layout sidebar."""

import base64

from PySide6 import QtCore, QtGui, QtWidgets

from ..plotter.adapters import plan_from_snapshot, reference_image_export_scope
from ..plotter.grbl import DEFAULT_WRITE_FEED, PEN_UP, Z_TOLERANCE_MM
from ..plotter.physical import PaperRegistration, position_page
from ..plotter.profiles import PlotterProfiles
from ..plotter.qt_connection import N1Worker, n1_ports
from ..plotter.schema import PlotPage
from ..renderers.pages import page_draw
from ..resource_catalog import workspace_for
from ..settings_pages import label, scroll_page
from ..theme import set_tone
from .position_nudge import PositionNudge


def field(value=0, *, low=-2000, high=2000):
    control = QtWidgets.QDoubleSpinBox()
    control.setRange(low, high)
    control.setDecimals(3)
    control.setSingleStep(.5)
    control.setSuffix(" mm")
    control.setValue(value)
    return control


def pair_widget(controls):
    widget = QtWidgets.QWidget()
    row = QtWidgets.QHBoxLayout(widget)
    row.setContentsMargins(0, 0, 0, 0)
    for control in controls:
        row.addWidget(control)
    return widget


class MachinePreview(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumSize(300, 300)
        self.area = None
        self.coords = None
        self.job = None
        self.point = None
        self.mark_points = ()
        self.paths = {}
        self.paper = None

    def set_paper(self, snapshot, index):
        draw = page_draw(snapshot, index, not snapshot.exportable)
        self.paper = QtCore.QRectF(0, 0, draw.width_mm, draw.height_mm)
        self.backdrop = self.raster(draw.background)
        self.images = [(QtCore.QRectF(x, y, right - x, bottom - y), self.raster(data))
                       for (x, y, right, bottom), data in draw.images]
        self.guides = []
        for op in snapshot.pages[index].preview_ops:
            if not op.points:
                continue
            path = QtGui.QPainterPath()
            path.moveTo(*op.points[0])
            for point in op.points[1:]:
                path.lineTo(*point)
            self.guides.append((QtGui.QColor(op.color), op.width_mm, path))
        self.update()

    @staticmethod
    def raster(data):
        return QtGui.QImage.fromData(base64.b64decode(data)) if data else QtGui.QImage()

    def set_paths(self, job, coords, area, mark_points):
        if job is not self.job:
            self.paths = {}
            if job:
                for stroke in job.strokes:
                    path = self.paths.setdefault(stroke.width_mm, QtGui.QPainterPath())
                    path.moveTo(*stroke.points[0])
                    for point in stroke.points[1:]:
                        path.lineTo(*point)
        self.job, self.coords, self.area, self.mark_points = job, coords, area, mark_points
        self.update()

    def paintEvent(self, _event):
        painter = QtGui.QPainter(self)
        painter.fillRect(self.rect(), self.palette().window())
        if self.paper is None:
            return
        coords = self.coords or PaperRegistration((0, 0))
        a, b = coords.vector(1, 0)
        c, d = coords.vector(0, 1)
        tx, ty = coords.place((0, 0))
        paper_transform = QtGui.QTransform(a, b, c, d, tx, ty)
        scene = paper_transform.mapRect(self.paper)
        boundary = None
        if self.area:
            boundary = QtCore.QRectF(self.area.left, self.area.top,
                                     self.area.right - self.area.left, self.area.bottom - self.area.top)
            scene = scene.united(boundary)
        target = QtCore.QRectF(self.rect()).adjusted(16, 16, -16, -16)
        scale = min(target.width() / scene.width(), target.height() / scene.height())
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.translate(target.center())
        painter.scale(scale, scale)
        painter.translate(-scene.center())

        painter.save()
        painter.setWorldTransform(paper_transform, True)
        painter.fillRect(self.paper, QtGui.QColor("#ffffff"))
        if not self.backdrop.isNull():
            painter.drawImage(self.paper, self.backdrop)
        for rect, image in self.images:
            if not image.isNull():
                painter.drawImage(rect, image)
        for color, width, path in self.guides:
            painter.setPen(QtGui.QPen(color, width))
            painter.drawPath(path)
        painter.restore()

        for width, path in self.paths.items():
            pen = QtGui.QPen(QtGui.QColor("#075a9c"), max(width, 1 / scale))
            pen.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(QtCore.Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.drawPath(path)
        if boundary:
            painter.setPen(QtGui.QPen(QtGui.QColor("#34946a"), 1 / scale, QtCore.Qt.PenStyle.DashLine))
            painter.drawRect(boundary)
        painter.setPen(QtGui.QPen(QtGui.QColor("#9a5c12"), 1 / scale))
        for x, y in self.mark_points:
            painter.drawLine(QtCore.QPointF(x - 1.8, y), QtCore.QPointF(x + 1.8, y))
            painter.drawLine(QtCore.QPointF(x, y - 1.8), QtCore.QPointF(x, y + 1.8))
        if self.point is not None:
            painter.setPen(QtGui.QPen(QtGui.QColor("#b91d47"), 1 / scale))
            painter.drawEllipse(QtCore.QPointF(*self.point), 1.3, 1.3)


class MachinePanel(QtWidgets.QWidget):
    page_selected = QtCore.Signal(int)
    status_changed = QtCore.Signal(str)
    machine_state = QtCore.Signal()

    def __init__(self, parent, *, worker_factory=N1Worker, ports=n1_ports):
        super().__init__(parent)
        self.setObjectName("machine_control_panel")
        self.ports = ports
        self.port_records = ()
        self.snapshot = None
        self.candidate = None
        self.plan = self.paper_page = self.unplaced_preview = None
        self.plan_error = ""
        self.device = self.busy = None
        self.registration = self.confirmed_area = None
        self.job = None
        self.pending_pages = []
        self.completed_pages = set()
        self.batch_active = self.waiting_for_paper = False
        self.closing = False
        self.profiles = []
        self.profile = None
        self.position_callback = None
        self.template = None
        self.setup = "默认摆放"
        self.preview_enabled = False

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        body = QtWidgets.QWidget()
        controls = QtWidgets.QVBoxLayout(body)
        self.scroll = scroll_page(body)
        root.addWidget(self.scroll)

        self.connection = QtWidgets.QGroupBox("设备")
        connect_layout = QtWidgets.QVBoxLayout(self.connection)
        self.device_picker = QtWidgets.QComboBox()
        self.device_picker.setAccessibleName("当前写字机")
        self.device_picker.currentIndexChanged.connect(
            lambda: self.select_profile(self.device_picker.currentData())
        )
        self.link_button = self.button("连接", self.toggle_connection)
        self.manage_devices = self.button("设备管理…", self.open_devices)
        connect_layout.addWidget(pair_widget((self.device_picker, self.link_button)))
        connect_layout.addWidget(self.manage_devices)
        self.position_label = label("未连接")
        connect_layout.addWidget(self.position_label)
        self.confirm_range_button = self.button("确认工作范围…", self.open_devices)
        connect_layout.addWidget(self.confirm_range_button)
        controls.addWidget(self.connection)

        writing = QtWidgets.QGroupBox("书写")
        write_layout = QtWidgets.QVBoxLayout(writing)
        self.scope = QtWidgets.QComboBox()
        self.scope.setAccessibleName("书写范围")
        self.scope.addItem("所选页", "single")
        self.scope.addItem("全部页", "all")
        write_layout.addWidget(self.scope)
        self.page_list = QtWidgets.QListWidget()
        self.page_list.setAccessibleName("书写页面")
        self.page_list.setMaximumHeight(112)
        write_layout.addWidget(self.page_list)
        self.progress = QtWidgets.QProgressBar()
        self.progress.hide()
        write_layout.addWidget(self.progress)
        self.report = label("连接设备后可定位。")
        write_layout.addWidget(self.report)
        self.align_button = self.button("当前页对位…", self.open_alignment)
        self.nudge = PositionNudge("抬笔点动", unit="mm", minimum=.1, maximum=20)
        self.nudge.moved.connect(self.jog)
        write_layout.addWidget(self.nudge)
        self.return_button = self.button("抬笔回到 A 点", self.return_to_origin)
        self.pen_button = self.button("抬笔", self.raise_pen)
        write_layout.addWidget(pair_widget((self.return_button, self.pen_button)))
        self.alignment_status = label("当前页未对位")
        write_layout.addWidget(self.alignment_status)
        write_layout.addWidget(self.align_button)
        self.preview_button = self.button("预览落笔区域", self.toggle_preview)
        self.preview_button.setCheckable(True)
        self.dry_button = self.button("抬笔试走", lambda: self.run_job("dry"))
        self.write_button = self.button("开始书写…", self.handle_primary)
        self.write_button.setProperty("inkRole", "primary")
        self.stop_button = self.button("停止", self.stop)
        self.stop_button.setProperty("inkRole", "danger")
        write_layout.addWidget(pair_widget((self.preview_button, self.dry_button)))
        write_layout.addWidget(self.write_button)
        controls.addWidget(writing)
        root.addWidget(self.stop_button)

        self.preview = MachinePreview()
        self.preview.setMinimumSize(0, 180)
        controls.addWidget(self.preview)
        controls.addStretch()
        self.preview.hide()
        self.worker = worker_factory(self)
        self.worker.succeeded.connect(self.succeeded)
        self.worker.failed.connect(self.failed)
        self.worker.phase.connect(self.on_phase)
        self.worker.progress.connect(self.on_progress)

        self.page_list.currentRowChanged.connect(self.select_page)
        self.scope.currentIndexChanged.connect(self.change_scope)
        self.scanned = False
        self.set_workspace(workspace_for(self))

    def button(self, text, callback):
        button = QtWidgets.QPushButton(text)
        button.setAutoDefault(False)
        button.clicked.connect(lambda _checked=False: callback())
        return button

    @property
    def offset(self):
        return self.device.offset[:2] if self.device and self.device.offset is not None else None

    def set_workspace(self, workspace):
        self.store = PlotterProfiles(workspace)
        try:
            self.profiles = self.store.devices()
            selected = self.store.read()["selected"]
        except (OSError, ValueError, TypeError, KeyError) as error:
            self.profiles, selected = [], ""
            self.message(f"无法读取写字机设备设置。{error}", error=True)
        self.profile = next((p for p in self.profiles if p.id == selected), None)
        self.reload_profiles()
        self.apply_profile()

    def reload_profiles(self):
        with QtCore.QSignalBlocker(self.device_picker):
            self.device_picker.clear()
            if not self.profiles:
                self.device_picker.addItem("请选择或添加设备", None)
            for item in self.profiles:
                self.device_picker.addItem(item.name, item.id)
            if self.profile:
                self.device_picker.setCurrentIndex(self.device_picker.findData(self.profile.id))

    def save_profile(self, profile):
        if self.device is not None and (not self.profile or self.profile.id != profile.id):
            raise ValueError("请先断开当前设备。")
        self.store.save(profile)
        self.profile = profile
        self.profiles = self.store.devices()
        self.reload_profiles()
        self.apply_profile(activate=self.device is not None)

    def select_profile(self, identifier):
        if self.device is not None or self.busy is not None or self.batch_active:
            return False
        item = next((p for p in self.profiles if p.id == identifier), None)
        if item is None:
            return False
        try:
            self.save_profile(item)
        except (OSError, ValueError, KeyError, TypeError) as error:
            self.reload_profiles()
            self.message(str(error), error=True)
            return False
        return True

    def apply_profile(self, *, activate=False):
        self.confirmed_area = self.profile.area if activate and self.profile else None
        self.invalidate_registration()

    def open_devices(self, parent=None):
        from .machine_devices import DeviceDialog

        if self.busy is not None or self.batch_active:
            return
        self.refresh_ports()
        dialog = DeviceDialog(self, parent)
        try:
            dialog.exec()
        finally:
            dialog.deleteLater()

    def capture_position(self, callback):
        if self.device is None:
            return
        if self.submit("position-read"):
            self.position_callback = callback

    def toggle_preview(self):
        self.preview_enabled = self.preview_button.isChecked()
        self.preview.setVisible(self.preview_enabled)
        if self.preview_enabled:
            self.update_preview()
            self.scroll.ensureWidgetVisible(self.preview)

    def use_alignment(self, alignment, position):
        if self.profile is None or self.paper_page is None:
            return
        self.registration = self.profile.axes.register(alignment.a, position,
                                                        angle=alignment.angle, scale=alignment.scale)
        try:
            self.job = position_page(self.paper_page, self.registration)
        except ValueError as error:
            self.job = None
            self.message(str(error), error=True)
        self.update_preview()
        self.refresh_buttons()

    def open_alignment(self):
        from .machine_alignment import AlignmentDialog, page_context

        if self.candidate is None or self.busy is not None or self.waiting_for_paper:
            return
        page, size, alignment, source = page_context(self.template, self.snapshot, self.paper_page.index)
        dialog = AlignmentDialog(self, self, page, size, alignment, source, snapshot=self.snapshot,
                                 index=self.paper_page.index)
        try:
            if dialog.exec() and dialog.position is not None:
                self.use_alignment(dialog.alignment, dialog.position)
                self.message(f"当前页已对位 · {self.setup}")
        finally:
            dialog.deleteLater()

    def refresh_ports(self):
        self.scanned = True
        self.port_records = tuple(self.ports())
        if not self.port_records and self.device is None:
            self.message("未发现炽写 N1。请连接 USB 后打开设备管理。")
        self.refresh_buttons()

    def message(self, text, error=False):
        self.report.setText(text)
        set_tone(self.report, "danger" if error else "status")
        show_in_workspace = self.batch_active or self.is_moving or error
        self.status_changed.emit(f"写字机 · {text}" if show_in_workspace else "")
        self.machine_state.emit()

    @property
    def is_moving(self):
        return self.busy in {"dry", "write", "axis-trial", "jog", "device-jog", "return", "pen"}

    @property
    def pen_raised(self):
        return self.device is not None and abs(self.device.position[2] - PEN_UP) <= Z_TOLERANCE_MM

    def showEvent(self, event):
        super().showEvent(event)
        if not self.scanned:
            self.refresh_ports()
        self.refresh_document()

    def set_document(self, snapshot, index, ready, template=None):
        self.template = template
        self.candidate = (snapshot, index) if ready and snapshot and snapshot.pages else None
        if self.isVisible():
            self.refresh_document()

    def follow_page(self, index):
        if self.candidate is None or self.busy is not None or self.batch_active:
            return
        snapshot, _ = self.candidate
        if not 0 <= index < len(snapshot.pages):
            return
        self.candidate = snapshot, index
        if (snapshot is self.snapshot and self.scope.currentData() == "single"
                and self.page_list.currentRow() != index):
            with QtCore.QSignalBlocker(self.page_list):
                self.page_list.setCurrentRow(index)
            self.change_page()

    def refresh_document(self):
        if self.busy is not None or self.batch_active or self.candidate is None:
            self.refresh_buttons()
            return
        snapshot, index = self.candidate
        if snapshot is self.snapshot:
            self.refresh_buttons()
            return
        self.snapshot = snapshot
        self.plan = None
        self.plan_error = ""
        try:
            omissions = reference_image_export_scope(snapshot)
            self.plan = plan_from_snapshot(snapshot, omit_reference_images=bool(omissions))
        except ValueError:
            self.plan_error = "当前排版含无法书写的内容，请查看问题与定位。"
        self.completed_pages.clear()
        with QtCore.QSignalBlocker(self.page_list), QtCore.QSignalBlocker(self.scope):
            self.page_list.clear()
            self.page_list.addItems([f"第 {page + 1} 页" for page in range(len(snapshot.pages))])
            self.page_list.setCurrentRow(index)
            self.scope.setItemText(1, f"全部 {len(snapshot.pages)} 页")
            self.scope.setCurrentIndex(0)
        self.update_page_states()
        self.change_page()
        if self.plan_error:
            self.message(self.plan_error, error=True)
        elif self.device is not None:
            self.message("请确认当前页对位。")

    def select_page(self, index):
        if index >= 0:
            self.change_page()
            self.page_selected.emit(index)

    def change_scope(self):
        if self.scope.currentData() == "all" and self.page_list.count():
            self.page_list.setCurrentRow(0)
        self.refresh_buttons()

    def update_page_states(self):
        for index in range(self.page_list.count()):
            if index in self.completed_pages:
                status = "已完成"
            elif self.plan and self.plan.pages[index].strokes:
                status = "待写"
            else:
                status = "无可书写笔迹"
            self.page_list.item(index).setText(f"第 {index + 1} 页 · {status}")

    def change_page(self, *_):
        index = self.page_list.currentRow()
        paper = self.snapshot.page_profile
        self.paper_page = (self.plan.pages[index] if self.plan else
                           PlotPage(index, paper.width_mm, paper.height_mm, ()))
        self.unplaced_preview = None
        if self.paper_page.strokes:
            try:
                self.unplaced_preview = position_page(self.paper_page, PaperRegistration((0, 0)))
            except ValueError:
                pass
        self.preview.set_paper(self.snapshot, index)
        self.invalidate_registration()

    def invalidate_registration(self):
        self.registration = self.job = None
        self.update_preview()
        self.refresh_buttons()

    def update_preview(self):
        coords = self.registration
        if self.preview_enabled:
            self.preview.set_paths(self.job or self.unplaced_preview, coords, self.confirmed_area,
                                   (coords.origin,) if coords else ())
        self.alignment_status.setText(
            f"当前页已对位 · A 点 X {coords.origin[0]:.3f} · Y {coords.origin[1]:.3f} mm"
            if coords else "当前页未对位"
        )

    def refresh_buttons(self, *_):
        busy, connected = self.busy is not None or self.closing, self.device is not None
        moving = self.is_moving
        canceling = moving and self.worker.control.stop_requested.is_set()
        available = connected and not busy
        positioning = available and not self.waiting_for_paper
        safe = positioning and self.confirmed_area is not None
        ready = (self.batch_active or self.candidate is not None) and self.paper_page is not None
        self.scope.setEnabled(not busy and not self.batch_active and ready)
        self.page_list.setEnabled(self.scope.isEnabled() and self.scope.currentData() == "single")
        self.device_picker.setEnabled(not connected and not busy and not self.batch_active)
        self.manage_devices.setEnabled(not busy and not self.batch_active)
        self.link_button.setText("断开" if connected else "连接")
        self.link_button.setEnabled(not busy and not self.batch_active and
                                    (self.pen_raised if connected else self.available_port() is not None))
        self.confirm_range_button.setVisible(connected and self.confirmed_area is None)
        self.confirm_range_button.setEnabled(positioning)
        self.align_button.setEnabled(not busy and ready and not self.waiting_for_paper)
        self.preview_button.setEnabled(ready and not busy)
        self.nudge.setEnabled(safe)
        self.pen_button.setVisible(connected and not self.pen_raised)
        self.pen_button.setEnabled(positioning)
        self.return_button.setEnabled(safe and ready and self.registration is not None)
        self.dry_button.setEnabled(safe and ready and self.job is not None)
        if moving:
            paused = self.worker.control.pause_requested.is_set()
            self.write_button.setText("继续" if paused else "暂停")
            self.write_button.setEnabled(not canceling)
        elif self.waiting_for_paper:
            self.write_button.setText("换纸完成")
            self.write_button.setEnabled(available)
        else:
            self.write_button.setText("开始书写…")
            self.write_button.setEnabled(safe and ready and self.pen_raised and self.job is not None)
        self.stop_button.setVisible(moving or self.batch_active)
        self.stop_button.setEnabled(not self.closing and not canceling)
        self.machine_state.emit()

    def submit(self, kind, *args):
        if self.busy is not None or self.closing:
            return False
        self.busy = kind
        if not self.worker.submit(kind, *args):
            self.busy = None
            return False
        if not self.worker.isRunning():
            self.worker.start()
        self.refresh_buttons()
        return True

    def available_port(self):
        if self.profile is None:
            return None
        matches = [p.portName() for p in self.port_records
                   if (getattr(p, "serialNumber", lambda: "")() == self.profile.serial
                       if self.profile.serial else p.portName() == self.profile.port)]
        if self.profile.port in matches:
            return self.profile.port
        return matches[0] if len(matches) == 1 else None

    def toggle_connection(self):
        if self.device is None:
            self.refresh_ports()
            if port := self.available_port():
                self.submit("connect", port)
                self.message(f"正在读取 {port} 的设备状态…")
            else:
                self.message("所选设备尚未连接 USB。", error=True)
        else:
            self.submit("disconnect")

    def jog(self, x, y):
        if self.confirmed_area is not None and self.profile:
            self.submit("jog", self.profile.axes.map(x, y), self.confirmed_area)

    def return_to_origin(self):
        if self.registration is not None and self.confirmed_area is not None:
            self.submit("return", self.registration.origin, self.confirmed_area)

    def raise_pen(self):
        if self.device is not None and not self.pen_raised:
            self.submit("pen", False, self.confirmed_area)

    def handle_primary(self):
        if self.is_moving:
            self.toggle_pause()
        elif self.waiting_for_paper:
            self.waiting_for_paper = False
            self.message("请重新确认下一页的书写原点或纸面对位。")
            self.refresh_buttons()
        else:
            self.start_writing()

    def start_writing(self):
        if self.job is None or not self.pen_raised or (self.candidate is None and not self.batch_active):
            return
        if self.confirmed_area is None:
            return
        try:
            self.job.check(self.confirmed_area, self.device.position[:2])
        except ValueError as error:
            self.message(str(error), error=True)
            return
        pending = []
        multi = not self.batch_active and self.scope.currentData() == "all"
        if multi:
            if any(not page.strokes for page in self.plan.pages):
                self.message("有页面无可书写笔迹。请选择有笔迹的单页。", error=True)
                return
            pending = list(range(1, len(self.plan.pages)))
        if self.confirm(
            "开始书写", f"将按已对位的笔序书写第 {self.job.index + 1} 页。确认纸张与笔尖均已就绪？",
        ):
            if self.run_job("write") and not self.batch_active:
                self.completed_pages.clear()
                self.update_page_states()
                if multi:
                    self.batch_active = True
                    self.pending_pages = pending

    def run_job(self, kind):
        job = self.job
        area = self.confirmed_area
        if (job is None or area is None or self.device is None or self.waiting_for_paper or
                (self.candidate is None and not self.batch_active)):
            return False
        try:
            job.check(area, self.device.position[:2], dry_run=kind == "dry")
        except ValueError as error:
            self.message(str(error), error=True)
            return False
        if self.submit(kind, job, area, self.profile.feed if self.profile else DEFAULT_WRITE_FEED):
            self.progress.setRange(0, len(job.strokes))
            self.progress.setValue(0)
            self.progress.show()
            return True
        return False

    def confirm(self, title, text):
        return QtWidgets.QMessageBox.question(
            self, title, text, QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No,
        ) == QtWidgets.QMessageBox.StandardButton.Yes

    def on_phase(self, phase):
        if not self.closing:
            self.message({"running": "设备正在执行…", "pausing": "正在等待设备暂停…",
                          "paused": "设备已暂停。"}[phase])

    def on_progress(self, done, total):
        self.progress.setValue(done)
        if done == total:
            self.message("指令已发送，正在等待设备抬笔和 Idle…")

    def toggle_pause(self):
        if not self.is_moving or self.worker.control.stop_requested.is_set():
            return
        pause = self.worker.control.pause_requested
        if pause.is_set():
            pause.clear()
        else:
            pause.set()
        self.refresh_buttons()

    def stop(self):
        if self.busy is not None:
            self.worker.control.stop_requested.set()
            self.refresh_buttons()
            self.message("正在停止设备…")
        elif self.batch_active:
            self.end_batch()
            self.invalidate_registration()
            self.refresh_document()
            self.message("已停止后续页面。")

    def end_batch(self):
        self.pending_pages.clear()
        self.batch_active = self.waiting_for_paper = False

    def show_position(self):
        if self.device is None:
            self.position_label.setText("设备尚未连接")
            self.preview.point = None
        else:
            x, y, z = self.device.position
            self.position_label.setText(
                f"{self.device.state} · X {x:.3f} · Y {y:.3f} · Z {z:.3f} mm"
                + (" · 已抬笔" if abs(z - PEN_UP) <= Z_TOLERANCE_MM else "")
            )
            self.preview.point = (x, y)
        self.preview.update()

    def succeeded(self, kind, status):
        if self.closing:
            return
        self.busy = None
        self.device = status
        self.show_position()
        message = {"connect": "请确认工作范围，再移动笔尖。",
                   "disconnect": "已断开。", "dry": "抬笔试走完成，可以开始书写。",
                   "write": "书写完成。设备已抬笔并处于 Idle。",
                   "jog": "点动完成。",
                   "device-jog": "点动完成。",
                   "return": "笔尖已抬起并回到书写原点。",
                   "pen": "笔尖已抬起。",
                   "axis-trial": "X/Y 试画完成。设备已抬笔。"}.get(kind, "已记录位置。")
        if kind in {"connect", "disconnect"}:
            self.apply_profile()
            if kind == "connect":
                message = "已连接。请在设备管理中确认当前坐标下的工作范围。"
                if self.profile and self.profile.area and self.profile.offset != self.offset:
                    message = "已连接。设备工作零点已变化，请重新核对安全范围与纸面对位。"
        elif kind == "position-read":
            callback, self.position_callback = self.position_callback, None
            if callback is not None:
                callback(status)
        elif kind == "write":
            page = self.page_list.currentRow()
            self.completed_pages.add(page)
            self.update_page_states()
            if self.pending_pages:
                self.waiting_for_paper = True
                self.page_list.setCurrentRow(self.pending_pages.pop(0))
                message = f"第 {page + 1} 页已完成。换纸后点「换纸完成」。"
            else:
                self.end_batch()
        self.refresh_document()
        self.message(message)
        self.refresh_buttons()

    def failed(self, kind, detail, disconnected):
        if self.closing:
            return
        self.busy = None
        self.position_callback = None
        self.end_batch()
        self.progress.hide()
        if disconnected:
            self.device = None
            self.apply_profile()
        self.show_position()
        self.update_preview()
        self.refresh_document()
        self.message(detail, error=True)
        self.refresh_buttons()

    def close_blocker(self):
        if self.is_moving or self.batch_active:
            return "请先完成或停止当前写字机作业。"
        if self.busy is not None:
            return "请等待写字机完成设备操作。"
        if self.device is not None and not self.pen_raised:
            return "请先抬起笔尖，再关闭应用。"
        return ""

    def shutdown(self):
        self.closing = True
        self.worker.shutdown()
        if self.worker.isRunning():
            self.worker.wait()
