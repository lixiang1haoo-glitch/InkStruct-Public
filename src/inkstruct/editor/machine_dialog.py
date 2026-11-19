"""Use the selected layout page with a USB-connected N1."""

import base64
import math

from PySide6 import QtCore, QtGui, QtWidgets

from ..plotter.adapters import plan_from_snapshot, reference_image_export_scope
from ..plotter.grbl import PEN_UP, Z_TOLERANCE_MM
from ..plotter.physical import PaperRegistration, WorkArea, position_page, registration_marks
from ..plotter.qt_connection import N1Worker, n1_ports
from ..plotter.schema import PlotPage
from ..renderers.pages import page_draw
from ..settings_pages import label, scroll_page
from ..theme import set_tone


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
        a, b = coords.scale * coords.cosine, coords.scale * coords.sine
        tx, ty = coords.place((0, 0))
        paper_transform = QtGui.QTransform(a, b, -b, a, tx, ty)
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


class MachineDialog(QtWidgets.QDialog):
    def __init__(self, snapshot, page_index, parent, *, worker_factory=N1Worker, ports=n1_ports):
        super().__init__(parent)
        self.snapshot = snapshot
        self.ports = ports
        self.plan_error = ""
        try:
            omissions = reference_image_export_scope(snapshot)
            self.plan = plan_from_snapshot(snapshot, omit_reference_images=bool(omissions))
        except ValueError as error:
            self.plan = None
            self.plan_error = str(error)
        self.device = None
        self.busy = None
        self.closing = False
        self.registration = None
        self.confirmed_area = None
        self.captured = {}
        self.job = self.dry_job = None
        self.setObjectName("machine_control_dialog")
        self.setWindowTitle("写字机 · 炽写 N1")
        self.resize(1030, 740)

        root = QtWidgets.QVBoxLayout(self)
        split = QtWidgets.QSplitter()
        root.addWidget(split, 1)
        form_widget = QtWidgets.QWidget()
        controls = QtWidgets.QVBoxLayout(form_widget)
        self.command_panel = scroll_page(form_widget)
        self.command_panel.setMinimumWidth(390)
        split.addWidget(self.command_panel)
        preview_pane = QtWidgets.QWidget()
        preview_panel = QtWidgets.QVBoxLayout(preview_pane)
        preview_panel.addWidget(label("设备坐标预览 · 蓝色为书写路径，绿框为已确认范围"))
        self.preview = MachinePreview()
        preview_panel.addWidget(self.preview, 1)
        self.position_label = label("设备尚未连接")
        preview_panel.addWidget(self.position_label)
        self.report = label("")
        preview_panel.addWidget(self.report)
        split.addWidget(preview_pane)
        split.setStretchFactor(1, 1)
        split.setSizes([420, 580])

        connection = QtWidgets.QGroupBox("连接设备")
        connect_form = QtWidgets.QFormLayout(connection)
        self.port_picker = QtWidgets.QComboBox()
        self.port_picker.setAccessibleName("炽写 N1 USB 串口")
        connect_form.addRow("USB 串口", self.port_picker)
        self.scan = self.button("重新扫描", self.refresh_ports)
        self.link_button = self.button("连接", self.toggle_connection)
        connect_form.addRow(pair_widget((self.scan, self.link_button)))
        controls.addWidget(connection)

        limits = QtWidgets.QGroupBox("工作范围")
        limit_form = QtWidgets.QFormLayout(limits)
        self.area_inputs = tuple(field(value) for value in (0, 0, 100, 100))
        for name, control in zip(("X 最小", "Y 最小", "X 最大", "Y 最大"), self.area_inputs, strict=True):
            limit_form.addRow(name, control)
            control.valueChanged.connect(self.invalidate_area)
        self.area_confirm = QtWidgets.QCheckBox("确认这是设备可安全移动的工作坐标范围")
        self.area_confirm.toggled.connect(self.confirm_area)
        limit_form.addRow(self.area_confirm)
        controls.addWidget(limits)

        position = QtWidgets.QGroupBox("笔尖位置")
        position_form = QtWidgets.QFormLayout(position)
        self.jog_step = field(1, low=.1, high=20)
        position_form.addRow("点动距离", self.jog_step)
        jogs = []
        for text, vector in (("← 左", (-1, 0)), ("→ 右", (1, 0)), ("↑ 上", (0, -1)), ("↓ 下", (0, 1))):
            jogs.append(self.button(text, lambda dxdy=vector: self.jog(dxdy)))
        self.jog_buttons = jogs
        position_form.addRow(pair_widget(jogs))
        self.read_position = self.button("读取位置", lambda: self.submit("position"))
        self.touch_button = self.button("试触纸…", self.touch)
        position_form.addRow(pair_widget((self.read_position, self.touch_button)))
        controls.addWidget(position)

        align_box = QtWidgets.QGroupBox("纸面对位")
        form = QtWidgets.QFormLayout(align_box)
        self.align_form = form
        self.page_picker = QtWidgets.QComboBox()
        for index in range(len(snapshot.pages)):
            self.page_picker.addItem(f"第 {index + 1} 页", index)
        self.page_picker.setCurrentIndex(page_index)
        form.addRow("冻结页面", self.page_picker)
        self.mode = QtWidgets.QComboBox()
        self.mode.addItem("空白纸 · 手动原点", "blank")
        self.mode.addItem("预印纸 · 两点对位", "preprinted")
        form.addRow("纸张", self.mode)
        self.origin = (field(), field())
        self.origin_row = pair_widget(self.origin)
        form.addRow("原点 X / Y", self.origin_row)
        self.origin_capture = self.button("以当前位置设原点", lambda: self.submit("position-origin"))
        form.addRow(self.origin_capture)
        self.scaling = QtWidgets.QCheckBox("等比校正（默认保持 100%）")
        form.addRow(self.scaling)
        self.point_fields, self.capture_buttons, self.mark_labels = [], [], []
        for index in range(3):
            inputs = (field(0, low=0), field(0, low=0))
            self.point_fields.append(inputs)
            form.addRow(f"纸面点 {index + 1} X / Y", pair_widget(inputs))
            capture = self.button(("记录实地第 1 点", "记录实地第 2 点", "核验实地第 3 点")[index],
                                  lambda n=index: self.submit(f"position-{n}"))
            self.capture_buttons.append(capture)
            measurement = label("未记录")
            self.mark_labels.append(measurement)
            form.addRow(pair_widget((capture, measurement)))
        self.verify_label = label("")
        form.addRow(self.verify_label)
        self.confirm_alignment = self.button("确认对位", self.place_job)
        form.addRow(self.confirm_alignment)
        controls.addWidget(align_box)

        self.feed = QtWidgets.QSpinBox()
        self.feed.setRange(60, 3000)
        self.feed.setValue(900)
        self.feed.setSuffix(" mm/min")
        execution = QtWidgets.QGroupBox("书写")
        write_form = QtWidgets.QFormLayout(execution)
        write_form.addRow("书写速度", self.feed)
        self.test_button = self.button("画三个测试点…", self.draw_test)
        self.dry_button = self.button("抬笔试走", lambda: self.run_job("dry"))
        self.write_button = self.button("开始书写…", self.start_writing)
        self.write_button.setProperty("inkRole", "primary")
        controls.addWidget(execution)
        controls.addStretch()

        footer = QtWidgets.QHBoxLayout()
        for button in (self.test_button, self.dry_button, self.write_button):
            footer.addWidget(button)
        self.progress = QtWidgets.QProgressBar()
        self.progress.hide()
        footer.addWidget(self.progress, 1)
        footer.addStretch()
        self.pause_button = self.button("暂停", self.toggle_pause)
        self.stop_button = self.button("停止", self.stop)
        self.close_button = self.button("关闭", self.reject)
        for button in (self.pause_button, self.stop_button, self.close_button):
            footer.addWidget(button)
        root.addLayout(footer)
        self.worker = worker_factory(self)
        self.worker.succeeded.connect(self.succeeded)
        self.worker.failed.connect(self.failed)
        self.worker.phase.connect(self.on_phase)
        self.worker.progress.connect(self.on_progress)
        self.worker.finished.connect(self.finish_close)
        self.worker.start()

        for control in self.origin:
            control.valueChanged.connect(self.invalidate_registration)
        for index, pair in enumerate(self.point_fields):
            for control in pair:
                control.valueChanged.connect(lambda _value, number=index: self.paper_point_changed(number))
        self.mode.currentIndexChanged.connect(self.change_mode)
        self.scaling.toggled.connect(self.invalidate_registration)
        self.page_picker.currentIndexChanged.connect(self.change_page)
        self.port_picker.currentIndexChanged.connect(self.refresh_buttons)
        self.feed.valueChanged.connect(self.invalidate_trial)
        self.refresh_ports()
        self.change_page()
        self.change_mode()
        if self.plan_error:
            self.message(self.plan_error, error=True)

    def button(self, text, callback):
        button = QtWidgets.QPushButton(text)
        button.setAutoDefault(False)
        button.clicked.connect(lambda _checked=False: callback())
        return button

    def refresh_ports(self):
        with QtCore.QSignalBlocker(self.port_picker):
            previous = self.port_picker.currentData()
            self.port_picker.clear()
            for port in self.ports():
                self.port_picker.addItem(port.portName(), port.portName())
            if (index := self.port_picker.findData(previous)) >= 0:
                self.port_picker.setCurrentIndex(index)
        if not self.port_picker.count() and self.device is None:
            self.message("未发现炽写 N1。连接 USB 后重新扫描。")
        self.refresh_buttons()

    def message(self, text, error=False):
        self.report.setText(text)
        set_tone(self.report, "danger" if error else "status")

    def change_page(self, *_):
        index = self.page_picker.currentIndex()
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
        x, y = min(15., paper.width_mm / 4), min(15., paper.height_mm / 4)
        for pair, point in zip(self.point_fields, ((x, y), (paper.width_mm - x, y), (x, paper.height_mm - y)),
                               strict=True):
            for control, value in zip(pair, point, strict=True):
                with QtCore.QSignalBlocker(control):
                    control.setValue(value)
        self.clear_measurements()
        self.invalidate_registration()

    def clear_measurements(self):
        self.captured.clear()
        for measurement in self.mark_labels:
            measurement.setText("未记录")

    def change_mode(self, *_):
        preprinted = self.mode.currentData() == "preprinted"
        self.align_form.setRowVisible(self.origin_row, not preprinted)
        self.origin_capture.setVisible(not preprinted)
        self.scaling.setVisible(preprinted)
        for capture in self.capture_buttons:
            capture.parentWidget().setVisible(preprinted)
        self.verify_label.setVisible(preprinted)
        self.invalidate_registration()

    def invalidate_trial(self, *_):
        self.dry_job = None
        self.refresh_buttons()

    def invalidate_registration(self, *_):
        self.registration = self.job = None
        self.verify_label.clear()
        self.invalidate_trial()
        self.update_preview()

    def invalidate_area(self, *_):
        self.confirmed_area = None
        with QtCore.QSignalBlocker(self.area_confirm):
            self.area_confirm.setChecked(False)
        self.invalidate_trial()
        self.update_preview()

    def confirm_area(self, checked):
        self.confirmed_area = None
        if checked:
            left, top, right, bottom = (control.value() for control in self.area_inputs)
            try:
                self.confirmed_area = WorkArea(left, top, right, bottom)
            except ValueError as error:
                self.invalidate_area()
                self.message(str(error), error=True)
        self.invalidate_trial()
        self.update_preview()

    def paper_points(self):
        return tuple(tuple(control.value() for control in pair) for pair in self.point_fields)

    def paper_point_changed(self, number):
        if number != 2 and self.mode.currentData() == "preprinted":
            self.invalidate_registration()
        else:
            self.update_verification()
            self.update_preview()

    def place_job(self):
        try:
            points = self.paper_points()
            if self.mode.currentData() == "blank":
                coords = PaperRegistration(tuple(control.value() for control in self.origin))
            else:
                coords = PaperRegistration.two_point(points[:2], (self.captured[0], self.captured[1]),
                                                     scale=self.scaling.isChecked())
            self.registration = coords
            self.job = position_page(self.paper_page, coords) if self.paper_page.strokes else None
            self.invalidate_trial()
            self.update_preview()
            self.update_verification()
            self.message(f"已确认纸面对位 · 比例 {coords.scale:.3%}"
                         + ("。当前页无可发送笔迹。" if self.job is None else "。"))
        except (KeyError, ValueError) as error:
            self.invalidate_registration()
            self.message(str(error), error=True)

    def update_preview(self, *, job=None):
        coords = self.registration
        self.preview.set_paths(job or self.job or self.unplaced_preview, coords, self.confirmed_area,
                               tuple(map(coords.place, self.paper_points())) if coords else self.paper_points())

    def update_verification(self):
        if self.registration is None or 2 not in self.captured:
            self.verify_label.clear()
            return
        actual = self.captured[2]
        expected = self.registration.place(self.paper_points()[2])
        dx, dy = (a - b for a, b in zip(actual, expected, strict=True))
        self.verify_label.setText(f"第三点偏差 {math.hypot(dx, dy):.3f} mm · X {dx:+.3f} · Y {dy:+.3f}")

    def refresh_buttons(self, *_):
        busy, connected = self.busy is not None or self.closing, self.device is not None
        available = connected and not busy
        safe = available and self.confirmed_area is not None
        self.command_panel.setEnabled(not busy)
        self.port_picker.setEnabled(not connected)
        self.scan.setEnabled(not connected)
        self.link_button.setText("断开" if connected else "连接")
        self.link_button.setEnabled(not busy and (connected or self.port_picker.count()))
        self.area_confirm.setEnabled(available)
        for button in (*self.jog_buttons, self.touch_button):
            button.setEnabled(safe)
        for button in (self.read_position, self.origin_capture, *self.capture_buttons):
            button.setEnabled(available)
        marks_ready = {0, 1} <= self.captured.keys()
        self.confirm_alignment.setEnabled(available and (self.mode.currentData() == "blank" or marks_ready))
        self.test_button.setEnabled(safe and self.registration is not None)
        self.dry_button.setEnabled(safe and self.job is not None)
        self.write_button.setEnabled(safe and self.job is not None and self.dry_job is self.job)
        run = self.busy in {"dry", "write", "test", "jog", "touch"}
        self.pause_button.setEnabled(run and not self.closing)
        self.stop_button.setEnabled(run and not self.closing)

    def submit(self, kind, *args):
        if self.busy is not None or self.closing:
            return False
        self.busy = kind
        if not self.worker.submit(kind, *args):
            self.busy = None
            return False
        self.refresh_buttons()
        return True

    def toggle_connection(self):
        if self.device is None:
            if port := self.port_picker.currentData():
                self.submit("connect", port)
                self.message(f"正在读取 {port} 的设备状态…")
        else:
            self.submit("disconnect")

    def jog(self, vector):
        if self.confirmed_area is not None:
            step = self.jog_step.value()
            self.submit("jog", tuple(component * step for component in vector), self.confirmed_area)

    def touch(self):
        area = self.confirmed_area
        if area is not None and self.confirm("试触纸", "笔尖将在当前位置落笔并抬起。确认已放好测试纸？"):
            self.submit("touch", area)

    def draw_test(self):
        if self.registration is None or self.confirmed_area is None or self.device is None:
            return
        try:
            job = registration_marks(self.paper_page, self.registration, self.paper_points())
            job.check(self.confirmed_area, self.device.position[:2])
        except ValueError as error:
            self.message(str(error), error=True)
            return
        self.update_preview(job=job)
        if self.confirm("画三个测试点", "将在纸上画三个半径 0.5 mm 的圆。确认当前放置的是测试纸？"):
            self.run_job("test", job)
        else:
            self.update_preview()

    def start_writing(self):
        if self.job is not None and self.dry_job is self.job and self.confirm(
            "开始书写", f"将按已对位的笔序书写第 {self.job.index + 1} 页。确认纸张与笔尖均已就绪？",
        ):
            self.run_job("write")

    def run_job(self, kind, job=None):
        job = job or self.job
        area = self.confirmed_area
        if job is None or area is None or self.device is None or (kind == "write" and self.dry_job is not job):
            return
        try:
            job.check(area, self.device.position[:2], dry_run=kind == "dry")
        except ValueError as error:
            self.message(str(error), error=True)
            return
        if self.submit(kind, job, area, self.feed.value()):
            self.progress.setRange(0, len(job.strokes))
            self.progress.setValue(0)
            self.progress.show()

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
        if self.busy is None:
            return
        pause = self.worker.control.pause_requested
        if pause.is_set():
            pause.clear()
            self.pause_button.setText("暂停")
        else:
            pause.set()
            self.pause_button.setText("继续")

    def stop(self):
        if self.busy is not None:
            self.worker.control.stop_requested.set()
            self.stop_button.setEnabled(False)
            self.pause_button.setEnabled(False)
            self.message("正在停止设备…")

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
        self.pause_button.setText("暂停")
        message = {"connect": "设备已连接。请确认工作范围并完成纸面对位。",
                   "disconnect": "已断开。", "dry": "抬笔试走完成，可以开始书写。",
                   "write": "书写完成。设备已抬笔并处于 Idle。",
                   "test": "三个测试点已画完，设备已抬笔。",
                   "touch": "试触纸完成，设备已抬笔。", "jog": "点动完成。",
                   "position": "已读取位置。"}.get(kind, "已记录位置。")
        if kind in {"connect", "disconnect"}:
            self.clear_measurements()
            self.invalidate_area()
            self.invalidate_registration()
        elif kind == "position-origin":
            for control, coordinate in zip(self.origin, status.position[:2], strict=True):
                control.setValue(coordinate)
        elif kind.startswith("position-"):
            index = int(kind.removeprefix("position-"))
            point = status.position[:2]
            self.captured[index] = point
            self.mark_labels[index].setText(f"X {point[0]:.3f} · Y {point[1]:.3f} mm")
            if index in (0, 1):
                self.invalidate_registration()
            else:
                self.update_verification()
        elif kind == "dry":
            self.dry_job = self.job
        elif kind == "write":
            self.invalidate_trial()
        elif kind == "test":
            self.update_preview()
        self.message(message)
        self.refresh_buttons()

    def failed(self, kind, detail, disconnected):
        if self.closing:
            return
        self.busy = None
        self.pause_button.setText("暂停")
        self.progress.hide()
        self.invalidate_trial()
        if disconnected:
            self.device = None
            self.clear_measurements()
            self.invalidate_area()
            self.invalidate_registration()
        self.show_position()
        self.update_preview()
        self.message(detail, error=True)
        self.refresh_buttons()

    def reject(self):
        if self.closing:
            return
        if self.busy in {"dry", "write", "test", "jog", "touch"} and not self.confirm(
            "停止并关闭", "停止当前作业并关闭写字机控制？",
        ):
            return
        self.closing = True
        self.refresh_buttons()
        self.worker.shutdown()
        if not self.worker.isRunning():
            self.finish_close()

    def finish_close(self):
        super().reject()
