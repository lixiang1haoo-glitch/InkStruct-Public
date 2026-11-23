"""Control a USB-connected N1 from the layout sidebar."""

import base64
import json
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from time import monotonic
from dataclasses import asdict, replace
from math import dist
from uuid import uuid4

from PySide6 import QtCore, QtGui, QtWidgets

from ..document.schema import digest
from ..document.flow_template import FlowTemplate, same_layout_revision
from ..plotter.adapters import adapt_page, can_export_with_image_omission
from ..plotter.export import ROUTING_VERSION
from ..plotter.grbl import DEFAULT_WRITE_FEED, PEN_UP, PIN_INTERIOR_MM, XY_TOLERANCE_MM, Z_TOLERANCE_MM
from ..plotter.physical import PaperRegistration, WorkArea, machine_point, position_page
from ..plotter.profiles import DeviceDatum, PageAlignment, PlotterProfiles
from ..plotter.qt_connection import N1Worker, n1_ports
from ..plotter.schema import PlotPage
from ..plotter.write_session import LEGACY_ROUTE, estimate_seconds, motion_seconds, record_time, timing_factor
from ..renderers.pages import page_draw
from ..resource_catalog import workspace_for
from ..settings_pages import label, scroll_page
from ..theme import set_tone
from ..plotter.docking import DockTrial, at_zero, dock_from_mark, idle_checkpoint, idle_xy, restored_frame
from .machine_alignment import AlignmentDialog, FixturePlacement, page_context, template_family
from .machine_page_work import PageWork, measure_page, prepare_page
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
        self.review_path = {}
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

    def set_paths(self, job, coords, area, mark_points, review_index=None):
        if job is not self.job:
            self.paths.clear()
            if job:
                for stroke in job.strokes:
                    self.add_path(self.paths, stroke)
        self.review_path.clear()
        if job and review_index is not None and 0 <= review_index < len(job.strokes):
            self.add_path(self.review_path, job.strokes[review_index])
        self.job, self.coords, self.area, self.mark_points = job, coords, area, mark_points
        self.update()

    @staticmethod
    def add_path(paths, stroke):
        path = paths.setdefault(stroke.width_mm, QtGui.QPainterPath())
        path.moveTo(*stroke.points[0])
        for point in stroke.points[1:]:
            path.lineTo(*point)

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
        for width, path in self.review_path.items():
            painter.setPen(QtGui.QPen(QtGui.QColor("#d86200"), max(width, 3 / scale)))
            painter.drawPath(path)
        if boundary:
            painter.setPen(QtGui.QPen(QtGui.QColor("#34946a"), 1 / scale, QtCore.Qt.PenStyle.DashLine))
            painter.drawRect(boundary)
        painter.setPen(QtGui.QPen(QtGui.QColor("#9a5c12"), 1 / scale))
        for x, y in self.mark_points:
            painter.drawLine(QtCore.QPointF(x - 1.8, y), QtCore.QPointF(x + 1.8, y))
            painter.drawLine(QtCore.QPointF(x, y - 1.8), QtCore.QPointF(x, y + 1.8))
        if self.coords is not None and self.point is not None:
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
        self.candidate_template = None
        self.paper_page = self.unplaced_preview = None
        self.journal = self.raw_page = self.elapsed_start = None
        self.done, self.uncertain = 0, False
        self.progress_error = ""
        self.plan_error = ""
        self.device = self.busy = None
        self.connection_id = None
        self.frame = None  # WPos of the physical datum in this connection only.
        self.fixture_placement = self.inherited_placement = None
        self.page_report = False
        self.registration = self.confirmed_area = None
        self.job = None
        self.page_return = None
        self.completed_pages = set()
        self.dock_trial = None
        self.session_lock = None
        self.temporary = None
        self.closing = False
        self.profiles = []
        self.profile = None
        self.position_callback = None
        self.template = None
        self.preview_enabled = False
        self.page_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="plotter-page")
        self.placement_work = PageWork(self, self.page_executor)
        self.session_work = PageWork(self, self.page_executor)
        self.estimate_work = PageWork(self, self.page_executor)
        self.page_timing = None
        self.run_start = 0
        self.prepared = None
        self.preview_source = None

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
        self.confirm_range_button = self.button("初始化或恢复停靠点…", self.recovery_options)
        connect_layout.addWidget(self.confirm_range_button)
        controls.addWidget(self.connection)

        writing = QtWidgets.QGroupBox("书写")
        write_layout = QtWidgets.QVBoxLayout(writing)
        self.page_list = QtWidgets.QListWidget()
        self.page_list.setAccessibleName("书写页面")
        self.page_list.setMaximumHeight(112)
        write_layout.addWidget(self.page_list)
        self.progress = QtWidgets.QProgressBar()
        self.progress.hide()
        write_layout.addWidget(self.progress)
        self.report = label("连接设备后可定位。")
        write_layout.addWidget(self.report)
        self.align_button = self.button("对准纸张…", self.open_alignment)
        self.nudge = self.motion_controls(self.jog)
        write_layout.addWidget(self.nudge)
        self.return_button = self.button("回停靠点", self.park_at_datum)
        self.pen_button = self.button("落笔", self.toggle_pen)
        write_layout.addWidget(pair_widget((self.return_button, self.pen_button)))
        self.alignment_status = label("当前页待对位")
        write_layout.addWidget(self.alignment_status)
        self.temp_button = self.button("临时对位…", self.toggle_temporary)
        write_layout.addWidget(self.temp_button)
        write_layout.addWidget(self.align_button)
        self.preview_button = self.button("预览落笔区域", self.toggle_preview)
        self.preview_button.setCheckable(True)
        self.dry_button = self.button("抬笔试走", lambda: self.run_job("dry"))
        self.write_button = self.button("开始书写…", self.handle_primary)
        self.write_button.setProperty("inkRole", "primary")
        self.stop_button = self.button("停止", self.stop)
        self.stop_button.setProperty("inkRole", "danger")
        write_layout.addWidget(pair_widget((self.preview_button, self.dry_button)))
        self.estimate_label = label("")
        write_layout.addWidget(self.estimate_label)
        self.route_stats = label("")
        write_layout.addWidget(self.route_stats)
        self.route_stats.hide()
        self.optimize = QtWidgets.QCheckBox("优化书写路径（同 SVG 导出）")
        self.optimize.setChecked(True)
        self.optimize.toggled.connect(self.change_routing)
        write_layout.addWidget(self.optimize)
        self.resume_hint = label("")
        write_layout.addWidget(self.resume_hint)
        write_layout.addWidget(self.write_button)
        controls.addWidget(writing)
        self.finish_stroke = self.button("写完本笔并保留进度", self.interrupt_after_stroke)
        root.addWidget(self.finish_stroke)
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
        if self.device is not None or self.busy is not None:
            raise ValueError("请先断开写字机，再切换工作区。")
        self.frame = self.dock_trial = self.temporary = None
        self.store = PlotterProfiles(workspace)
        self.worker.jog_fault_path = self.store.path.with_name("plotter-last-jog-fault.json")
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

    def save_profile(self, profile, *, confirm_range=False):
        if self.busy is not None:
            raise ValueError("请先完成当前设备操作。")
        if self.device is not None and (not self.profile or self.profile.id != profile.id):
            raise ValueError("请先断开当前设备。")
        old = self.profile
        if (old and old.id == profile.id and old.datum and
                (old.axes != profile.axes or old.serial != profile.serial or
                 (not old.serial and old.port != profile.port))):
            profile = replace(profile, datum=None, area=None, offset=None)
            confirm_range = False
        same_axes = bool(old and (old.id, old.axes, old.serial, old.port) ==
                                 (profile.id, profile.axes, profile.serial, profile.port))
        same_datum = bool(same_axes and profile.datum and old.datum and old.datum.id == profile.datum.id)
        same_coordinates = same_datum or (same_axes and not profile.datum and not old.datum)
        if self.device is not None and (old.serial, old.port) != (profile.serial, profile.port):
            raise ValueError("请断开设备后更改 USB 标识。")
        if confirm_range and (self.connection_id is None or profile.area is None):
            raise ValueError("请连接后核对实际工作范围。")
        if confirm_range:
            profile = replace(profile, limit_area_enabled=True)
        if profile.datum and confirm_range:
            if not same_datum or not self.datum_located:
                raise ValueError("请先恢复停靠点。")
            area = profile.datum.to_body_area(profile.area, self.frame)
            profile = replace(profile, datum=replace(profile.datum, area=area))
        self._persist_profile(profile)
        if not same_datum:
            self.frame = None
            if old and old.datum and self.connection_id:
                self.connection_id = uuid4().hex
        retain_area = (same_coordinates and self.confirmed_area is not None and profile.limit_area_enabled
                       and old.area == profile.area)
        self.apply_profile(activate=confirm_range or retain_area, keep_alignment=same_coordinates)

    def _persist_profile(self, profile):
        self.store.save(profile)
        self.profile = profile
        self.profiles = [p for p in self.profiles if p.id != profile.id] + [profile]
        self.reload_profiles()

    def select_profile(self, identifier):
        if self.device is not None or self.busy is not None or self.dock_trial:
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

    def apply_profile(self, *, activate=False, keep_alignment=False):
        self.confirmed_area = None
        if activate and self.profile and self.profile.limit_area_enabled:
            if self.profile.datum:
                if self.datum_located and self.profile.datum.area:
                    self.confirmed_area = self.profile.datum.to_work_area(self.profile.datum.area, self.frame)
            else:
                self.confirmed_area = self.profile.area
        self.import_legacy_marks()
        self.show_position()
        if not keep_alignment:
            self.registration = self.inherited_placement = self.job = None
        if self.raw_page is not None:
            self.request_session()
        else:
            self.invalidate_registration()

    @property
    def range_ready(self):
        return self.profile is not None and (not self.profile.limit_area_enabled or self.confirmed_area is not None)

    @property
    def datum_located(self):
        return bool(self.frame is not None and self.connection_id and self.device and self.profile
                    and self.profile.datum and self.profile.datum.boot_mode)

    def _require_datum_reading(self, status):
        if (status is not self.device or self.connection_id is None or self.profile is None
                or status.state != "Idle" or not self.pen_raised or status.blocking_pins):
            raise ValueError("请确认已连接对应的设备，抬笔停稳并重新读取基准点。")
        return status.position[:2]

    def begin_dock_trial(self, status):
        point = self._require_datum_reading(status)
        self.invalidate_datum()
        self.dock_trial = DockTrial(self.profile.id, point, self.connection_id)
        self.refresh_buttons()

    def record_restart(self, status):
        trial = self.dock_trial
        if not trial or self.profile.id != trial.device_id:
            raise ValueError("请重新开始初始化。")
        try:
            trial.record_restart(self.connection_id, status)
        except ValueError:
            if len(trial.readings) >= 3:
                self.cancel_dock_trial()
            raise
        self.refresh_buttons()

    def cancel_dock_trial(self):
        self.dock_trial = None
        self.invalidate_datum()

    def initialize_axes(self, axes, area):
        trial = self.dock_trial
        if not (trial and trial.mode and trial.connection == self.connection_id
                and trial.trial_axes is not None and self.device and self.pen_raised):
            raise ValueError("请完成三轮重启和 X/Y 试画，再保存核对后的方向和比例。")
        profile = replace(self.profile, axes=axes, datum=None,
                          area=area, offset=self.offset, limit_area_enabled=area is not None)
        datum = replace(DeviceDatum.create(profile, "停靠点"), boot_mode=trial.mode,
                        restart_positions=(trial.initial, *trial.readings))
        if area is not None:
            area.require(trial.origin, "停靠点")
            datum = replace(datum, area=datum.to_body_area(area, trial.origin))
        self._persist_profile(replace(profile, datum=datum))
        self.dock_trial = None
        self._set_frame(trial.origin)

    def invalidate_datum(self):
        self.temporary = None
        self._set_frame(None)

    def _set_frame(self, origin):
        # A new mapping invalidates callbacks and temporary placements from the old frame.
        self.connection_id = uuid4().hex if self.device else None
        self.frame = origin
        self.temporary = None
        self.registration = self.job = self.inherited_placement = None
        if origin is not None:
            self.worker.restore_idle_reference(self.device.position[:2])
        self.apply_profile(activate=origin is not None)

    def park_at_datum(self):
        if not self.datum_located or not self.range_ready:
            return False
        if self.confirmed_area and not all(
            self.confirmed_area.contains(p) for p in (self.device.position[:2], self.frame)
        ):
            self.message("停车路径超出已确认的工作范围。", error=True)
            return False
        return self.submit("return", self.frame, self.confirmed_area, self.profile.feed)

    def change_paper_stops(self):
        if self.busy or not self.device or not self.profile or not self.confirm(
            "更换纸张挡边", "确认纸张的固定位置或方向已经改变？各版式保留选好的标记，下次使用时重新实测。"
        ):
            return
        self.temporary = None
        try:
            self._persist_profile(replace(self.profile, stop_generation=uuid4().hex))
        except (OSError, ValueError) as error:
            self.invalidate_datum()
            self.message(f"挡边变更未保存，请重新登记挡边：{error}", error=True)
            return
        self.reload_sheet()

    def recovery_options(self):
        if not self.device or self.datum_located or self.dock_trial:
            self.open_devices()
            return
        try:
            records = self.store.sheets(self.profile)
        except (ValueError, OSError) as error:
            self.message(f"无法读取本机纸面原点：{error}", error=True)
            return
        family = template_family(self.template, self.snapshot) if self.snapshot else None
        options = []
        seen = set()
        if self.snapshot:
            for index in range(len(self.snapshot.pages)):
                key, _, _, title = page_context(self.template, self.snapshot, index)
                if key not in seen and self.profile.accepts_sheet(records.get(key)):
                    options.append((f"第 {index + 1} 页 · {title}", key, index))
                seen.add(key)
        current_geometry = set(seen)
        if isinstance(self.template, FlowTemplate):
            current_geometry.update(page_context(self.template, self.snapshot, layout=source)[0]
                                    for source in self.template.effective_layouts)
        elif self.snapshot and self.template is not None:
            current_geometry.update(page_context(self.template, self.snapshot, i)[0] for i in (0, 1))
        for key, record in records.items():
            layout = record.get("layout")
            if (key not in seen and self.profile.accepts_sheet(record) and layout
                    and (layout["family"] != family or key in current_geometry)):
                options.append((layout["title"], key, None))
        if not options:
            self.open_devices()
            return
        labels = [f"{i + 1}. {item[0]}" for i, item in enumerate(options)]
        choice, ok = QtWidgets.QInputDialog.getItem(self, "恢复停靠点", "选择与当前纸张一致的实测版式",
                                                    [*labels, "重新初始化…"], 0, False)
        if not ok:
            return
        if choice not in labels:
            self.open_devices()
            return
        title, key, index = options[labels.index(choice)]
        if index is not None:
            self.page_list.setCurrentRow(index)
            if self.current_page_ready():
                self.open_alignment()
            else:
                self.message("页面准备好后，点击「用本页恢复停靠点」。")
            return
        record = records[key]
        dialog = AlignmentDialog(self, key, record["layout"]["size"], PageAlignment(record["mark"]),
                                 title, recovery=True, archived=True)
        try:
            dialog.exec()
        finally:
            dialog.deleteLater()

    def open_devices(self, parent=None):
        from .machine_devices import DeviceDialog

        if self.busy is not None:
            return
        self.refresh_ports()
        dialog = DeviceDialog(self, parent)
        try:
            dialog.exec()
        finally:
            dialog.deleteLater()

    def capture_position(self, callback, *, datum=False):
        if self.device is None:
            return False
        context = self.connection_id, self.profile, self.frame, self.offset
        if self.submit("position-datum" if datum else "position-read"):
            self.position_callback = callback, context
            return True
        return False

    def toggle_preview(self):
        self.preview_enabled = self.preview_button.isChecked()
        self.preview.setVisible(self.preview_enabled)
        if self.preview_enabled:
            self.update_preview()
            self.scroll.ensureWidgetVisible(self.preview)

    def positioned(self, job):
        self.job = job
        self.update_preview()
        self.refresh_buttons()

    def position_failed(self, error):
        self.registration = self.inherited_placement = self.job = None
        self.update_preview()
        self.message(str(error), error=True, page_specific=True)
        self.refresh_buttons()

    def import_legacy_marks(self):
        if not isinstance(self.template, FlowTemplate) or not self.profile:
            return
        marks = {}
        for layout in self.template.effective_layouts:
            if self.template.paper_origin(layout) is not None:
                key, size, mark, _ = page_context(self.template, self.snapshot, layout=layout)
                mark.validate_size(*size)
                marks[key] = mark.a
        if marks:
            try:
                self.store.import_marks(self.profile, marks)
            except (OSError, ValueError) as error:
                self.message(f"旧版纸面标记尚未导入：{error}", error=True)

    def sheet_context(self):
        return page_context(self.template, self.snapshot, self.paper_page.index)

    def sheet_record(self, key, legacy):
        record = self.store.sheet(self.profile, key)
        if record is None and legacy:
            # Legacy A is a validated paper coordinate. Legacy device coordinates
            # used an arbitrary paper corner or a per-connection WPos.
            self.store.import_marks(self.profile, {key: legacy.a})
            record = self.store.sheet(self.profile, key)
        return record

    def toggle_temporary(self):
        if self.temporary:
            self.temporary = None
            self.reload_sheet()
        else:
            self.open_alignment(temporary=True)

    def open_alignment(self, *, temporary=False):
        if not self.current_page_ready() or not self.device or self.busy or self.dock_trial:
            return
        key, _, legacy, title = self.sheet_context()
        try:
            record = self.sheet_record(key, legacy)
        except (OSError, ValueError, TypeError, KeyError) as error:
            self.message(f"无法读取本机纸面原点：{error}", error=True)
            return
        mark = PageAlignment(record["mark"]) if record else None
        recovery = not self.datum_located
        if recovery and not self.profile.accepts_sheet(record):
            self.message("此版式尚无可恢复的纸面原点。请选择已实测的版式，或在设备管理中初始化。")
            return
        dialog = AlignmentDialog(self, key, (self.paper_page.width_mm, self.paper_page.height_mm),
                                 mark, title, recovery=recovery, temporary=temporary)
        try:
            if not dialog.exec() and temporary:
                self.temporary = None
                self.reload_sheet()
        finally:
            dialog.deleteLater()

    def restore_from_sheet(self, key, mark, status):
        point = self._require_datum_reading(status)
        record = self.store.sheet(self.profile, key)
        if (self.datum_located or not self.profile.accepts_sheet(record) or tuple(record["mark"]) != mark.a):
            raise ValueError("此版式没有可用于恢复的实测记录。")
        self._set_frame(dock_from_mark(self.profile.axes, record["virtual"], point))

    def measure_sheet(self, key, mark, status, *, recovery=False, temporary=False):
        point = self._require_datum_reading(status)
        if not self.current_page_ready() or self.sheet_context()[0] != key:
            raise ValueError("页面已变化，请重新选择纸面原点。")
        mark.validate_size(self.paper_page.width_mm, self.paper_page.height_mm)
        if recovery:
            self.restore_from_sheet(key, mark, status)
        elif self.datum_located:
            if temporary:
                self.temporary = (key, FixturePlacement(mark, point, "本张纸临时对位"))
            else:
                virtual = self.profile.datum.to_body(point, self.frame)
                _, size, _, title = self.sheet_context()
                layout = {"family": template_family(self.template, self.snapshot), "size": list(size),
                          "title": f"{getattr(self.template, 'name', '普通页面')} · {title}"}
                self.store.save_sheet(self.profile, key, mark.a, virtual, self.paper_page.index + 1, layout=layout)
                self.temporary = None
        else:
            raise ValueError("请先恢复停靠点。")
        self.reload_sheet()

    def reload_sheet(self):
        self.invalidate_registration()
        if self.fixture_placement:
            self.apply_fixture()

    def refresh_ports(self):
        self.scanned = True
        self.port_records = tuple(self.ports())
        if not self.port_records and self.device is None:
            self.message("未发现炽写 N1。请连接 USB 后打开设备管理。")
        self.refresh_buttons()

    def message(self, text, error=False, *, page_specific=False):
        self.page_report = page_specific
        self.report.setText(text)
        set_tone(self.report, "danger" if error else "status")
        show_in_workspace = self.is_moving or error
        self.status_changed.emit(f"写字机 · {text}" if text and show_in_workspace else "")
        self.machine_state.emit()

    @property
    def is_moving(self):
        return self.busy in {"dry", "write", "axis-trial", "jog", "device-jog", "return", "page-return", "pen", "calibrate-line", "calibrate-height"}

    @property
    def pen_raised(self):
        return self.device is not None and abs(self.device.position[2] - PEN_UP) <= Z_TOLERANCE_MM

    def showEvent(self, event):
        super().showEvent(event)
        if not self.scanned:
            self.refresh_ports()
        self.refresh_document()

    def set_document(self, snapshot, index, ready, template=None):
        self.candidate_template = template
        self.candidate = (snapshot, index) if ready and snapshot and snapshot.pages else None
        if self.isVisible():
            self.refresh_document()

    def follow_page(self, index):
        if self.candidate is None or self.busy is not None:
            return
        snapshot, _ = self.candidate
        if not 0 <= index < len(snapshot.pages):
            return
        self.candidate = snapshot, index
        if (snapshot is self.snapshot
                and self.page_list.currentRow() != index):
            with QtCore.QSignalBlocker(self.page_list):
                self.page_list.setCurrentRow(index)
            self.change_page()

    def refresh_document(self):
        if self.busy is not None or self.candidate is None:
            self.refresh_buttons()
            return
        snapshot, index = self.candidate
        if snapshot is self.snapshot and self.template is self.candidate_template:
            self.refresh_buttons()
            return
        if snapshot is self.snapshot and same_layout_revision(self.template, self.candidate_template):
            self.template = self.candidate_template
            self.import_legacy_marks()
            self.update_page_states()
            self.placement_work.cancel()
            self.registration = self.inherited_placement = self.job = None
            self.refresh_fixture()
            if self.fixture_placement:
                self.apply_fixture()
            else:
                self.update_preview()
                self.refresh_buttons()
            return
        for work in (self.session_work, self.estimate_work):
            work.cancel()
            work.cache.clear()
        self.preview_source = None
        self.snapshot = snapshot
        self.template = self.candidate_template
        self.import_legacy_marks()
        self.completed_pages.clear()
        self.selected_pages = {}
        self.diagnostic_pages = {}
        if any(d.severity == "error" for d in snapshot.diagnostics):
            for pg in snapshot.pages:
                for item in (*pg.fragments, *pg.images):
                    self.diagnostic_pages.setdefault(item.span, set()).add(pg.index)
        with QtCore.QSignalBlocker(self.page_list):
            self.page_list.clear()
            self.page_list.addItems([f"第 {page + 1} 页" for page in range(len(snapshot.pages))])
            self.page_list.setCurrentRow(index)
        self.update_page_states()
        self.change_page()
        if self.plan_error:
            self.message(self.plan_error, error=True, page_specific=True)

    def select_page(self, index):
        if index >= 0:
            self.change_page()
            self.page_selected.emit(index)

    def update_page_states(self):
        for index in range(self.page_list.count()):
            if index in self.completed_pages:
                status = "已完成"
            elif self.snapshot.pages[index].paint_ops:
                status = "待写"
            else:
                status = "无可书写笔迹"
            self.page_list.item(index).setText(f"第 {index + 1} 页 · {status}")

    def change_page(self, *_):
        index = self.page_list.currentRow()
        self.temporary = None
        paper = self.snapshot.page_profile
        # Direct writing preflights only the selected page. Preserve its original
        # index for the resumable journal. Export still uses the complete snapshot.
        self.plan_error = ""
        page = self.snapshot.pages[index]
        diagnostics = tuple(d for d in self.snapshot.diagnostics
                            if d.span not in self.diagnostic_pages or index in self.diagnostic_pages[d.span])
        scoped = replace(self.snapshot, pages=(page,), diagnostics=diagnostics)
        try:
            from ..document.limits import validate_snapshot
            validate_snapshot(scoped)
            if not scoped.plotter_exportable and not can_export_with_image_omission(scoped):
                raise ValueError("请先处理影响本页书写的排版问题。")
            if index not in self.selected_pages:
                self.selected_pages[index] = adapt_page(page, paper)
            self.raw_page = self.selected_pages[index]
        except ValueError as error:
            self.plan_error = f"本页预检失败：{error}"
            self.raw_page = PlotPage(index, paper.width_mm, paper.height_mm, ())
        self.registration = self.inherited_placement = self.job = self.unplaced_preview = None
        self.progress.hide()
        self.progress.reset()
        if self.page_report:
            self.message("")
        self.request_session()

    def request_session(self):
        self.placement_work.cancel()
        self.placement_work.cache.clear()
        page = self.raw_page
        device_id = self.profile.id if self.profile else None
        key = self.store.path.parent, page.index, device_id
        self.estimate_work.cancel()
        self.page_timing = None
        if key not in self.session_work.cache:
            self.prepared = self.paper_page = self.journal = None
            self.done, self.uncertain = 0, False
            self.fixture_placement = None
            self.preview.paper = self.preview_source = None
            self.preview.update()
            self.update_resume_hint()
            self.alignment_status.setText("正在准备当前页…")
            self.estimate_label.setText("正在计算本页预计用时…")
            self.route_stats.hide()
            self.route_stats.clear()
            self.optimize.setEnabled(False)
            self.refresh_buttons()
        background = self.snapshot.pages[page.index].background
        args = (key[0], self.snapshot.document_id, page, background.sha256 if background else "", device_id)
        # Trivial pages can restore their checkpoint immediately; dense geometry runs in the worker.
        small = len(page.strokes) <= 16 and sum(len(s.points) for s in page.strokes) <= 128
        self.session_work.request(key, prepare_page, args, self.session_ready, self.session_failed, immediate=small)

    def session_failed(self, error):
        self.job = self.paper_page = self.registration = None
        self.progress_error = f"无法准备本页笔迹：{error}"
        self.estimate_label.setText(self.progress_error)
        self.message(self.progress_error, error=True)
        self.refresh_buttons()

    def session_ready(self, prepared):
        self.prepared = prepared
        self.prepare_session()
        self.refresh_fixture()
        if (self.fixture_placement is not None
                and (self.registration is None or self.inherited_placement is not None)):
            self.apply_fixture()
            return
        if self.inherited_placement is not None:
            self.registration = self.inherited_placement = self.job = None
        self.update_preview()
        self.refresh_buttons()

    def prepare_session(self):
        page = self.raw_page
        self.progress_error = ""
        self.saved_placement = None
        self.done, self.uncertain = 0, False
        self.journal, routed, legacy = self.prepared
        version = ROUTING_VERSION
        if self.journal:
            try:
                self.done, self.uncertain = self.journal.read()
                if self.done == len(page.strokes) and self.done > 0:
                    self.completed_pages.add(page.index)
                    self.update_page_states()
                if self.journal.path.exists():
                    data = json.loads(self.journal.path.read_bytes())
                    optimized = data["optimized"]
                    version = data.get("route_version", LEGACY_ROUTE)
                    if version not in (LEGACY_ROUTE, ROUTING_VERSION):
                        raise ValueError("续写记录使用了未知的路径优化版本。")
                    self.saved_placement = data.get("placement")
                    if type(optimized) is not bool:
                        raise ValueError("笔序记录损坏")
                    with QtCore.QSignalBlocker(self.optimize):
                        self.optimize.setChecked(optimized)
            except (KeyError, TypeError, ValueError, OSError) as error:
                self.progress_error = f"无法读取续写记录：{error}"
            self.journal = replace(self.journal, optimized=self.optimize.isChecked(), route_version=version)
        if version == LEGACY_ROUTE:
            routed = legacy
        selected = routed if self.optimize.isChecked() else page
        if selected is not self.paper_page:
            self.unplaced_preview = None
        self.paper_page = selected
        self.optimize.setEnabled(not (self.journal and self.journal.path.exists()))

    def placement_details(self):
        if not self.registration or not self.profile:
            return None
        marks = self.registration
        return {"anchor": list(marks.anchor), "origin": list(marks.origin),
                "axes": asdict(self.profile.axes), "setup": "纸面原点",
                "pen": self.profile.active_pen, "connection": self.connection_id}

    def change_routing(self):
        if self.prepared is None or self.busy:
            return
        self.placement_work.cancel()
        self.placement_work.cache.clear()
        self.prepare_session()
        self.unplaced_preview = None
        if self.paper_page.strokes and self.registration:
            self.job = position_page(self.paper_page, self.registration)
        self.update_preview()
        self.refresh_buttons()

    def update_estimate(self):
        if not self.paper_page or not self.paper_page.strokes or not self.profile:
            self.estimate_work.cancel()
            self.page_timing = None
            self.estimate_label.clear()
            self.route_stats.hide()
            self.route_stats.clear()
            return
        key = (self.raw_page.index, self.paper_page is self.raw_page,
               self.journal.route_version if self.journal else ROUTING_VERSION,
               self.job.registration if self.job else None)
        profile_key = sha256(f"{self.profile.id}|{self.profile.active_pen}|{self.profile.feed}".encode()).hexdigest()
        self.timing_path = self.store.path.parent / "plotter-times" / (profile_key + ".json")
        if key not in self.estimate_work.cache:
            self.page_timing = None
            self.estimate_label.setText("正在计算本页预计用时…")
            self.route_stats.hide()
            self.route_stats.clear()
        args = self.raw_page, self.paper_page, self.job
        self.estimate_work.request(key, measure_page, args, self.show_estimate,
                                   lambda error: self.estimate_label.setText(f"无法估算本页用时：{error}"))

    def show_estimate(self, measured):
        self.page_timing = measured
        self.time_factor = timing_factor(self.timing_path)
        self.display_remaining()

    def display_remaining(self):
        timing = self.page_timing
        if timing is None:
            return
        total = len(timing.remaining) - 1
        done = total if self.raw_page.index in self.completed_pages else self.done
        count = total - done
        distance = timing.remaining[done]
        travel = timing.remaining_travel[done]
        start = self.device.position[:2] if self.device and self.job else None
        if count and self.job:
            approach = start
            if self.busy == "write" and done > self.run_start:
                approach = self.job.strokes[done - 1].points[-1]
            if approach is not None:
                gap = dist(approach, self.job.strokes[done].points[0])
                distance += gap
                travel += gap
        self.base_estimate = motion_seconds(distance, count, self.profile.feed)
        seconds = round(self.base_estimate * self.time_factor)
        self.estimate_label.setText(f"本页预计剩余 {seconds // 60} 分 {seconds % 60} 秒")
        before, after = timing.before, timing.after
        if start is not None:
            before += dist(start, timing.original_start)
            after += dist(start, timing.routed_start)
        self.route_stats.setText(f"剩余抬笔 {count} 次 · 剩余空走 {travel:.1f} mm")
        self.route_stats.setToolTip(f"整页空走 {before:.1f} → {after:.1f} mm")
        self.route_stats.show()

    def update_resume_hint(self):
        text = self.progress_error
        if not text and (self.done or self.uncertain):
            text = f"已确认完成 {self.done} 笔。"
            if self.uncertain:
                text += f"请在原稿上核对第 {self.done + 1} 笔，可点「预览落笔区域」查看位置。"
            text += "续写前请确认本页对位。"
        self.resume_hint.setText(text)
        self.resume_hint.setVisible(bool(text))

    def invalidate_registration(self):
        self.placement_work.cancel()
        self.registration = self.inherited_placement = self.job = None
        self.refresh_fixture()
        self.update_preview()
        self.refresh_buttons()

    def current_page_ready(self):
        if self.paper_page is None:
            return False
        return (self.candidate is not None and self.candidate[0] is self.snapshot
                                     and self.template is self.candidate_template)

    def refresh_fixture(self):
        self.fixture_placement = None
        if not self.datum_located or not self.current_page_ready():
            return
        try:
            key, size, legacy, _ = self.sheet_context()
            if self.temporary and self.temporary[0] == key:
                self.fixture_placement = self.temporary[1]
                return
            record = self.sheet_record(key, legacy)
            if self.profile.accepts_sheet(record):
                mark = PageAlignment(record["mark"])
                mark.validate_size(*size)
                point = self.profile.datum.to_work(record["virtual"], self.frame)
                self.fixture_placement = FixturePlacement(mark, point, f"第 {record['source']} 页实测")
        except (OSError, ValueError, KeyError, TypeError) as error:
            self.message(f"无法读取本机纸面原点。{error}", error=True)

    def apply_fixture(self):
        fixture = self.fixture_placement
        if not self.datum_located or not fixture or not self.current_page_ready():
            return
        self.placement_work.cancel()
        registration = self.profile.axes.register(fixture.alignment.a, fixture.position)
        self.registration, self.inherited_placement, self.job = registration, fixture, None
        page = self.paper_page
        if page.strokes:
            key = (id(page), registration)
            small = len(page.strokes) <= 16 and sum(len(s.points) for s in page.strokes) <= 128
            self.placement_work.request(key, position_page, (page, registration), self.positioned,
                                        self.position_failed, immediate=small)
        self.update_preview()
        self.refresh_buttons()

    def fixture_still_matches(self, previous):
        self.refresh_fixture()
        if previous is not None and previous == self.fixture_placement:
            return True
        self.invalidate_registration()
        self.message("摆放或设备坐标已变化，请重新核对本页对位。", page_specific=True)
        return False

    def update_preview(self):
        coords = self.registration
        if self.preview_enabled and self.paper_page:
            index = self.paper_page.index
            if self.preview_source != (id(self.snapshot), index):
                self.preview.set_paper(self.snapshot, index)
                self.preview_source = id(self.snapshot), index
            if self.paper_page.strokes and not self.job and self.unplaced_preview is None:
                try:
                    self.unplaced_preview = position_page(self.paper_page, PaperRegistration((0, 0)))
                except ValueError:
                    pass
        self.update_resume_hint()
        self.update_estimate()
        if self.preview_enabled:
            self.preview.set_paths(self.job if coords else self.unplaced_preview, coords, self.confirmed_area if coords else None,
                                   (coords.origin,) if coords else (), self.done if self.uncertain else None)
        page = f"第 {self.raw_page.index + 1} 页" if self.raw_page else "当前页"
        if coords:
            source = self.inherited_placement
            self.alignment_status.setText(f"{page}已对位 · {source.source if source else '本张纸'}")
        elif self.raw_page and isinstance(self.template, FlowTemplate):
            self.alignment_status.setText(f"{page}待对位。请将笔尖对准本版式的纸面原点。")
        else:
            self.alignment_status.setText(f"{page}待对位")

    def refresh_buttons(self, *_):
        busy, connected = self.busy is not None or self.closing, self.device is not None
        moving = self.is_moving
        canceling = moving and self.worker.control.stop_requested.is_set()
        available = connected and not busy
        positioning = available
        safe = positioning and self.datum_located and self.range_ready
        ready = self.current_page_ready()
        document_ready = self.candidate is not None and self.candidate[0] is self.snapshot
        self.page_list.setEnabled(document_ready and not busy)
        self.device_picker.setEnabled(not connected and not busy)
        self.manage_devices.setEnabled(not busy)
        self.link_button.setText("断开" if connected else "连接")
        self.link_button.setEnabled(not busy and
                                    (self.pen_raised if connected else self.available_port() is not None))
        needs_datum = connected and not self.datum_located
        self.confirm_range_button.setVisible(bool(connected and (needs_datum or not self.range_ready)))
        self.confirm_range_button.setText("初始化或恢复停靠点…" if needs_datum else "确认工作范围…")
        self.confirm_range_button.setEnabled(positioning)
        self.align_button.setEnabled(bool(ready and available and not self.dock_trial))
        self.align_button.setText("用本页恢复停靠点…" if needs_datum else "设置纸面原点…")
        self.temp_button.setText("取消临时对位" if self.temporary else "临时对位…")
        self.temp_button.setEnabled(bool(safe and self.fixture_placement))
        self.preview_button.setEnabled(ready and not busy)
        self.refresh_motion_controls(self.nudge, positioning and self.datum_located)
        self.refresh_pen_button(self.pen_button)
        self.return_button.setEnabled(safe and self.pen_raised)
        self.dry_button.setEnabled(safe and ready and self.job is not None)
        if moving:
            paused = self.worker.control.pause_requested.is_set()
            self.write_button.setText("继续" if paused else "暂停")
            self.write_button.setEnabled(not canceling)
        else:
            self.write_button.setText("核对纸面并续写…" if self.done or self.uncertain else "开始书写…")
            if self.raw_page and self.done and self.done == len(self.raw_page.strokes):
                self.write_button.setText("换纸后重写本页…")
            self.write_button.setToolTip("")
            self.write_button.setEnabled(bool(safe and ready and self.pen_raised and self.job is not None
                                              and not self.progress_error))
        self.finish_stroke.setVisible(self.busy == "write")
        self.finish_stroke.setEnabled(self.busy == "write" and not canceling)
        self.stop_button.setVisible(moving)
        self.stop_button.setEnabled(not self.closing and not canceling)
        self.machine_state.emit()

    def submit(self, kind, *args):
        if self.busy is not None or self.closing:
            return False
        motion = kind not in {"connect", "disconnect", "position-datum", "position-read"}
        trial = self.dock_trial
        commissioning = trial and trial.mode and trial.connection == self.connection_id
        if trial and not trial.mode and motion:
            self.message("三轮重启期间请保持笔尖位置不变。")
            return False
        recovery_action = kind in {"jog", "device-jog"} or (kind == "pen" and not args[0])
        if motion and not self.datum_located and not recovery_action and not (commissioning and kind == "axis-trial"):
            self.message("请先恢复停靠点。", error=True)
            return False
        if kind in {"write", "dry"} and (args[0] is not self.job or not self.current_page_ready()
                                        or args[0].index != self.page_list.currentRow()):
            return False
        if kind in {"return", "page-return"}:
            try:
                if args[0] != self.frame:
                    raise ValueError("停靠点已变化，请重新核对。")
                idle_xy(self.device)
            except ValueError as error:
                self.message(str(error), error=True)
                return False
        if kind == "disconnect":
            self.datum_located_before_disconnect = self.datum_located
        area = self.confirmed_area
        if kind in {"device-jog", "jog"}:
            if self.profile is None or self.device is None:
                return False
            offset, _, feed = args
            if area is not None:
                x, y = self.device.position[:2]
                target = machine_point((x + offset[0], y + offset[1]))
                if not (area.contains((x, y)) and area.contains(target)):
                    self.message("点动路径超出已确认的工作范围。", error=True)
                    return False
            args = offset, area, feed, area is None
        elif kind in {"return", "page-return", "axis-trial", "write", "dry"}:
            if not self.range_ready and not (kind == "axis-trial" and commissioning):
                self.message("请先确认已启用的工作范围。", error=True)
                return False
            if kind == "axis-trial":
                axes, draft, feed, _ = args
                self.trial_axes_sent = axes
                # A draft can narrow a registered device's area. It must not
                # expand the work area or bypass it by unchecking the field.
                effective = draft if commissioning else area
                if commissioning and self.profile.limit_area_enabled and effective is None:
                    self.message("请核对初始化试画的安全范围。", error=True)
                    return False
                if area is not None and draft is not None:
                    try:
                        effective = WorkArea(max(area.left, draft.left), max(area.top, draft.top),
                                             min(area.right, draft.right), min(area.bottom, draft.bottom))
                    except ValueError:
                        self.message("试画范围与已确认的工作范围没有重合区域。", error=True)
                        return False
                args = axes, effective, feed, area
        # Consume the on-disk proof before opening the serial port. While
        # connected there is no reusable credential to survive a reset/crash.
        if kind == "connect":
            # Keep the consume/open/close/save sequence exclusive across app
            # instances, including the interval after the serial handle closes.
            try:
                self.store.path.parent.mkdir(parents=True, exist_ok=True)
            except OSError as error:
                self.message(f"无法打开设备档案：{error}", error=True)
                return False
            lock_path = self.store.path.parent / ("plotter-session-" + digest(self.profile.id) + ".lock")
            self.session_lock = QtCore.QLockFile(str(lock_path))
            self.session_lock.setStaleLockTime(0)
            if not self.session_lock.tryLock(0):
                self.session_lock = None
                self.message("此设备档案正在由另一个窗口使用。", error=True)
                return False
            try:
                self.previous_checkpoint = self.store.exchange_checkpoint(self.profile)
            except (ValueError, OSError) as error:
                self.release_session_lock()
                self.message(f"无法撤销上次停机记录：{error}", error=True)
                return False
        self.busy = kind
        if not self.worker.submit(kind, *args):
            if kind == "connect":
                self.release_session_lock()
            self.busy = None
            return False
        if not self.worker.isRunning():
            self.worker.start()
        self.refresh_buttons()
        return True

    def release_session_lock(self):
        if self.session_lock is not None:
            self.session_lock.unlock()
            self.session_lock = None

    def available_port(self):
        if self.profile is None:
            return None
        matches = [p.portName() for p in self.port_records
                   if (getattr(p, "serialNumber", lambda: "")() == self.profile.serial
                       if self.profile.serial else p.portName() == self.profile.port)]
        if self.profile.port in matches:
            return self.profile.port
        return matches[0] if len(matches) == 1 else None

    def recover_connection(self, status):
        saved, self.previous_checkpoint = self.previous_checkpoint, None
        if self.dock_trial or getattr(self.worker, "reset_on_connect", False):
            return False
        self.frame = restored_frame(self.profile, saved, status)
        if self.frame is not None:
            self.worker.restore_idle_reference(status.position[:2])
            return True
        return False

    def confirm_zero_dock(self, status):
        token = self.connection_id
        if self.device is not status or self.busy or self.dock_trial or self.datum_located:
            return
        if self.confirm("恢复停靠点", "笔尖现在确实停在初始化时的停靠点吗？"):
            def confirmed(fresh):
                if token == self.connection_id and at_zero(idle_xy(fresh)):
                    self._set_frame(fresh.position[:2])
            if token == self.connection_id:
                self.capture_position(confirmed, datum=True)
        else:
            self.message("请按原挡边放纸，用已实测版式的纸面标记恢复停靠点。")
            if token == self.connection_id and not self.closing:
                self.recovery_options()

    def toggle_connection(self):
        if self.device is None:
            self.refresh_ports()
            if port := self.available_port():
                if not self.profile.serial and not self.confirm("核对设备",
                        f"此串口没有设备序列号。请确认连接的是「{self.profile.name}」原先登记的写字机。"):
                    return
                if self.submit("connect", port, self.profile.serial):
                    self.message(f"正在读取 {port} 的设备状态…")
            else:
                self.message("所选设备尚未连接 USB。", error=True)
        else:
            self.submit("disconnect")

    def motion_controls(self, move):
        pad = PositionNudge("抬笔点动", unit="mm", minimum=.1, maximum=100, plotter=True)
        pad.moved.connect(move)
        pad.feed.currentIndexChanged.connect(lambda _: self.change_feed(pad.feed.currentData()))
        return pad

    def refresh_motion_controls(self, pad, can_move):
        feed = self.profile.feed if self.profile else DEFAULT_WRITE_FEED
        can_edit = bool(self.profile and self.busy is None and not self.closing)
        pad.show_motion_settings(feed, can_move=can_move, can_edit=can_edit)

    def change_feed(self, value):
        if not self.profile or self.busy or self.closing or self.profile.feed == value:
            return
        try:
            self._persist_profile(replace(self.profile, feed=value))
            self.update_estimate()
        except (OSError, ValueError) as error:
            self.message(f"运动速度未能保存。{error}", error=True)
        self.refresh_buttons()

    def jog(self, x, y):
        if self.profile and self.device is not None:
            self.submit("jog", self.profile.axes.map(x, y), self.confirmed_area, self.profile.feed)

    def refresh_pen_button(self, button):
        down = self.device is not None and not self.pen_raised
        button.setText("抬笔" if down else "落笔")
        button.setEnabled(self.device is not None and self.device.state == "Idle" and self.busy is None
                          and not self.closing and (down or (self.range_ready and self.datum_located)))

    def toggle_pen(self):
        if self.device is None or self.busy or self.closing or self.device.state != "Idle":
            return
        if not self.pen_raised:
            self.raise_pen()
        elif self.range_ready:
            self.submit("pen", True, self.confirmed_area, self.profile.writing_height)

    def raise_pen(self):
        if self.device is not None and not self.pen_raised:
            self.submit("pen", False, self.confirmed_area)

    def handle_primary(self):
        if self.is_moving:
            self.toggle_pause()
        else:
            self.start_writing()

    def start_writing(self):
        if self.job is None or not self.pen_raised or not self.current_page_ready():
            return
        if not self.range_ready:
            return
        if self.confirmed_area is not None:
            try:
                self.job.check(self.confirmed_area, self.device.position[:2])
            except ValueError as error:
                self.message(str(error), error=True)
                return
        job, connection = self.job, self.connection_id
        start = self.done
        if self.uncertain:
            box = QtWidgets.QMessageBox(self)
            box.setWindowTitle("核对中断笔")
            box.setText(f"请在原稿上核对第 {start + 1} 笔。未写完整可重写，已完整可从下一笔继续。")
            rewrite = box.addButton("重写这一笔", QtWidgets.QMessageBox.ButtonRole.ActionRole)
            skip = box.addButton("从下一笔继续", QtWidgets.QMessageBox.ButtonRole.ActionRole)
            box.setDefaultButton(box.addButton(QtWidgets.QMessageBox.StandardButton.Cancel))
            box.exec()
            if box.clickedButton() == skip:
                start += 1
            elif box.clickedButton() != rewrite:
                return
        placement_note = ""
        if (self.done or self.uncertain) and self.saved_placement:
            old = self.saved_placement
            setup_note = f"（{old['setup']}）" if old['setup'] not in ('默认摆放', '纸面原点') else ""
            placement_note = f"上次对位{setup_note}的纸面原点为 {old['anchor']} mm。"
            if old != self.placement_details():
                placement_note += "本次连接或对位已变化，请确认笔尖仍对准原稿的同一标记。"
        title = "原稿已对位，继续书写" if start or self.uncertain else "开始书写"
        text = f"{placement_note}第 {job.index + 1} 页 · 已有 {start} 笔可跳过。请确认当前纸张、页面和对位正确。"
        if self.done == len(job.strokes) and not self.uncertain:
            title = "在新纸上重写本页"
            text = f"第 {job.index + 1} 页已有完整书写记录。确认已经换上空白纸，要从第一笔重新书写？"
            start = 0
        return_target = self.frame
        text += " 写完后将抬笔回停靠点。"
        position = self.device.position[:2]
        local_area = None
        checkbox = None
        if not self.profile.limit_area_enabled and self.confirmed_area is None:
            local_area = job.clearance_box(position, PIN_INTERIOR_MM, return_target=return_target)
            text += (f"\n\n本页运动范围（含笔间移动及边缘余量），相对当前笔尖："
                     f"\n设备 X 方向 {local_area.left - position[0]:+.1f} 至 {local_area.right - position[0]:+.1f} mm"
                     f"\n设备 Y 方向 {local_area.top - position[1]:+.1f} 至 {local_area.bottom - position[1]:+.1f} mm。"
                     "\n核实整块区域均可到达并避开夹具后，可勾选下项，启用本次作业范围内的连续空走。")
            checkbox = QtWidgets.QCheckBox("我已核实上述区域，仅本次书写使用")
            accepted = self.confirm(title, text, checkbox)
        else:
            accepted = self.confirm(title, text)
        if (accepted and self.job is job and self.device and self.device.position[:2] == position
                and connection == self.connection_id):
            area = local_area if checkbox is not None and checkbox.isChecked() else None
            if self.run_job("write", start=start, local_area=area):
                self.completed_pages.discard(job.index)
                self.update_page_states()

    def run_job(self, kind, *, start=0, local_area=None):
        job = self.job
        area = self.confirmed_area
        if kind == "write" and self.profile and not self.profile.limit_area_enabled and area is None:
            area = local_area
        if (job is None or not self.range_ready or self.device is None or
                not self.current_page_ready()):
            return False
        target = self.frame if kind == "write" else None
        if not self.fixture_still_matches(self.inherited_placement):
            return False
        if area is not None:
            try:
                if target is not None:
                    area.require(target, "停靠点")
                job.check(area, self.device.position[:2], dry_run=kind == "dry")
            except ValueError as error:
                self.message(str(error), error=True)
                return False
        options = []
        if kind == "write":
            if self.progress_error:
                return False
            if self.journal is None and self.raw_page:
                self.prepare_session()
            if self.journal:
                self.journal = replace(self.journal, placement=self.placement_details())
            options.append(dict(height=self.profile.writing_height, start=start, journal=self.journal))
        if self.submit(kind, job, area, self.profile.feed, *options):
            self.preview_button.setChecked(False)
            self.toggle_preview()
            self.resume_hint.hide()
            if kind == "write":
                self.page_return = (target, area, self.profile.feed) if target is not None else None
                self.elapsed_start = monotonic()
                self.completed_pages.discard(job.index)
                self.run_start = self.done = start
                self.display_remaining()
                self.run_estimate = (self.base_estimate if self.page_timing else
                                     estimate_seconds(job.strokes[start:], self.profile.feed, self.device.position[:2]))
                self.optimize.setEnabled(False)
            self.progress.setRange(0, len(job.strokes))
            self.progress.setFormat("%v / %m 笔 · %p%")
            self.progress.setValue(start)
            self.progress.show()
            return True
        return False

    def confirm(self, title, text, checkbox=None):
        box = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Icon.Question, title, text,
                                    QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
                                    self)
        box.setDefaultButton(QtWidgets.QMessageBox.StandardButton.No)
        if checkbox is not None:
            box.setCheckBox(checkbox)
        answer = box.exec()
        if checkbox is not None:
            checkbox.setParent(None)
        box.deleteLater()
        return answer == QtWidgets.QMessageBox.StandardButton.Yes

    def on_phase(self, phase):
        if not self.closing and self.is_moving:
            running = "本页已写完，正在抬笔回停靠点…" if self.busy == "page-return" else "设备正在执行…"
            self.message({"running": running, "pausing": "正在等待设备暂停…",
                          "paused": "设备已暂停。"}[phase])

    def on_progress(self, done, total):
        if self.closing or self.busy not in {"write", "dry"}:
            return
        self.progress.setValue(done)
        if self.busy == "write":
            self.done, self.uncertain = done, False
            self.display_remaining()
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
            self.elapsed_start = None
        self.refresh_buttons()

    def interrupt_after_stroke(self):
        if self.busy == "write":
            self.worker.control.finish_stroke.set()
            self.worker.control.pause_requested.clear()
            self.message("正在写完当前笔，抬笔后将保留本页进度。")

    def stop(self):
        if self.busy is not None:
            self.worker.control.stop_requested.set()
            self.refresh_buttons()
            self.message("正在停止设备…")

    def show_position(self):
        if self.device is None:
            self.position_label.setText("设备尚未连接")
            self.preview.point = None
        else:
            x, y, z = self.device.position
            prefix = "待恢复停靠点"
            if self.datum_located:
                bx, by = self.profile.datum.to_body((x, y), self.frame)
                prefix = f"距停靠点 X {bx:.3f} · Y {by:.3f} mm"
            self.position_label.setText(prefix + (" · 已抬笔" if self.pen_raised else " · 已落笔"))
            self.preview.point = (x, y) if self.datum_located else None
        self.preview.update()

    def succeeded(self, kind, status):
        if self.closing or self.busy != kind:
            return
        self.busy = None
        self.device = status
        message = {"disconnect": "已断开。", "dry": "抬笔试走完成，可以开始书写。",
                   "write": "书写完成。设备已抬笔并处于 Idle。",
                   "jog": "点动完成。",
                   "device-jog": "点动完成。",
                   "return": "笔尖已抬起并到达目标位置。",
                   "page-return": "本页已写完，笔尖已抬起并回停靠点，可以取纸。",
                   "pen": "笔尖已抬起。" if self.pen_raised else "笔尖已落下。",
                   "axis-trial": "X/Y 试画完成。设备已抬笔。"}.get(kind, "已记录位置。")
        if kind in {"connect", "disconnect"}:
            checkpoint_error = ""
            if kind == "disconnect" and self.datum_located_before_disconnect:
                try:
                    saved = idle_checkpoint(self.profile, self.frame, self.worker.stopped_at)
                    self.store.exchange_checkpoint(self.profile, saved)
                except (OSError, ValueError) as error:
                    checkpoint_error = f" 本次静止位置未保存：{error}"
            self.temporary = None
            if kind == "disconnect":
                self.release_session_lock()
            if kind == "disconnect" and self.dock_trial and self.dock_trial.mode:
                self.dock_trial = None
            self.connection_id = uuid4().hex if kind == "connect" else None
            self.frame = None
            self.position_callback = None
            recovered = False
            if kind == "connect":
                try:
                    recovered = self.recover_connection(status)
                except (OSError, ValueError, TypeError, KeyError) as error:
                    checkpoint_error = f" 无法核对上次停机位置：{error}"
            self.apply_profile(activate=recovered)
            if kind == "connect":
                message = "已连接。请在设备管理中完成停靠点初始化。"
                if self.dock_trial:
                    message = "已重连，请在设备管理中记录本轮重启读数。"
                elif recovered:
                    message = "已恢复停靠点和本机纸面原点。"
                elif self.profile.datum and self.profile.datum.boot_mode:
                    message = "请选择已实测的版式并恢复停靠点，或重新初始化。"
                    if at_zero(status.position[:2]) and self.pen_raised:
                        QtCore.QTimer.singleShot(0, lambda: self.confirm_zero_dock(status))
            message += checkpoint_error
        elif kind in {"position-read", "position-datum"}:
            pending, self.position_callback = self.position_callback, None
            if pending is not None:
                callback, context = pending
                if context == (self.connection_id, self.profile, self.frame, self.offset):
                    try:
                        callback(status)
                    except (OSError, ValueError) as error:
                        self.message(str(error), error=True)
                        self.refresh_buttons()
                        return
                else:
                    message = "设备坐标已变化，已舍弃此前的位置读取。"
            if kind == "position-datum" and self.datum_located:
                message = "停靠点已定位。"
        elif kind == "write":
            control = self.worker.control
            if control.interrupted_cleanly:
                message = "本笔已写完并抬笔，已保留本页进度。"
            else:
                try:
                    if self.elapsed_start and self.run_estimate and hasattr(self, "timing_path"):
                        record_time(self.timing_path, monotonic() - self.elapsed_start, self.run_estimate)
                except OSError as error:
                    message += f" 本机耗时记录未能更新：{error}"
                self.completed_pages.add(self.page_list.currentRow())
                self.done, self.uncertain = len(self.raw_page.strokes), False
                self.update_page_states()
            self.interrupted_return = control.interrupted_cleanly
            move, self.page_return = self.page_return, None
            control = self.worker.control
            self.temporary = None
            self.reload_sheet()
            if move is not None and not control.stop_requested.is_set():
                if self.submit("page-return", *move):
                    self.show_position()
                    self.message("正在抬笔回停靠点…")
                    return
                message += " 回停靠点的操作未能开始。"
        if kind == "axis-trial" and self.dock_trial:
            self.dock_trial.trial_axes = self.trial_axes_sent
        if kind in {"return", "page-return"}:
            if kind == "page-return" and self.interrupted_return:
                message = "已保留续写进度，笔尖已回停靠点。"
            try:
                if dist(idle_xy(status), self.frame) > XY_TOLERANCE_MM:
                    raise ValueError("尚未确认到达停靠点。")
            except (TypeError, ValueError):
                self.invalidate_datum()
                message = "未确认停靠。请恢复停靠点。"
        self.show_position()
        self.refresh_document()
        self.message(message, page_specific=kind in {"write", "dry", "page-return"})
        self.refresh_buttons()

    def failed(self, kind, detail, disconnected):
        if self.closing or self.busy != kind:
            return
        self.busy = None
        self.position_callback = None
        self.temporary = None
        self.progress.hide()
        self.page_return = None
        if kind == "page-return":
            detail = f"回停靠点未完成。{detail}"
        if kind == "write" and self.job:
            if self.journal:
                try:
                    self.done, self.uncertain = self.journal.read()
                except (ValueError, OSError) as error:
                    self.progress_error = str(error)
            done = self.done
            detail += f" 第 {self.job.index + 1} 页已确认完成 {done}/{len(self.job.strokes)} 笔。"
            if self.uncertain and done < len(self.job.strokes):
                detail += f"请检查第 {done + 1} 笔的纸面笔迹。"
        if disconnected:
            self.release_session_lock()
            if self.dock_trial and (self.dock_trial.mode or kind not in {"connect", "disconnect"}):
                self.dock_trial = None
            self.device = None
            self.connection_id = None
            self.frame = None
            self.apply_profile()
        self.reload_sheet()
        self.show_position()
        self.update_preview()
        self.refresh_document()
        self.message(detail, error=True)
        self.refresh_buttons()

    def close_blocker(self):
        if self.is_moving:
            return "请先完成或停止当前写字机作业。"
        if self.busy is not None:
            return "请等待写字机完成设备操作。"
        if self.device is not None and not self.pen_raised:
            return "请先抬起笔尖，再关闭应用。"
        return ""

    def shutdown(self):
        closing_profile, closing_frame = self.profile, self.frame if self.datum_located and not self.busy else None
        self.closing = True
        for work in (self.estimate_work, self.session_work, self.placement_work):
            work.cancel()
        self.page_executor.shutdown(wait=False, cancel_futures=True)
        self.worker.shutdown()
        if self.worker.isRunning():
            self.worker.wait()
        if closing_frame is not None and getattr(self.worker, "closed_idle", None) is not None:
            try:
                proof = idle_checkpoint(closing_profile, closing_frame, self.worker.closed_idle)
                self.store.exchange_checkpoint(closing_profile, proof)
            except (ValueError, OSError) as error:
                self.message(f"本次静止位置未保存：{error}", error=True)
        self.release_session_lock()
