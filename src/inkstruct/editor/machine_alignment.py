"""Paper marks on the source template and placement readings on this computer."""

import math
from dataclasses import asdict, dataclass, replace

from PySide6 import QtCore, QtGui, QtWidgets

from ..document.flow_template import FlowTemplate
from ..document.schema import digest
from ..plotter.physical import machine_point
from ..plotter.profiles import PageAlignment
from ..sample_preview import InkViewport, SampleView
from ..settings_pages import label
from ..theme import set_tone


def same_alignment_profile(first, second):
    return first == second or (first is not None and second is not None and
                               replace(first, feed=second.feed) == second)


def page_context(template, snapshot=None, index=0, *, layout=None):
    if isinstance(template, FlowTemplate):
        source = layout or template.layout(index)
        size = (template.width_mm, template.height_mm)
        family = template.name
        page = digest([family, source.layout_id, source.source_sha256, source.source_page, size,
                       source.background.sha256 if source.background else None,
                       template.offset_x_mm, template.offset_y_mm])
        title = f"PDF 第 {source.source_page} 页" if source.source_page is not None else source.label
        return page, size, template.paper_origin(source), title
    paper = snapshot.page_profile
    size = paper.width_mm, paper.height_mm
    return digest([snapshot.document_id, index, size]), size, None, f"第 {index + 1} 页"


def fixture_page(page_key, source, snapshot, index):
    """Repeated sheets can share a fixture only when their physical layout matches."""
    if source is not None:
        return digest(["paper-stops", page_key, source.source_size_mm,
                       [asdict(frame) for frame in source.frames], [asdict(rule) for rule in source.rules]])
    if snapshot is not None:
        page = snapshot.pages[index]
        if page.background is None:
            return digest(["paper-stops", snapshot.document_id, asdict(snapshot.page_profile), page.source_layout])
        return digest(["paper-stops", page_key, page.background.sha256, page.source_layout])
    return digest(["paper-stops", page_key])


@dataclass(frozen=True)
class FixturePlacement:
    alignment: PageAlignment
    position: tuple[float, float]
    setup: str
    source: str
    session_only: bool = False


class SessionPageGroup:
    """Measurements for one template, device coordinate frame and sheet setup."""
    def __init__(self, template, context, setup, axes):
        self.template, self.context, self.setup, self.axes = template, context, setup, axes
        self.layouts = tuple(dict.fromkeys((*template.start_pages, *template.effective_loop)))
        self.entries = {}
        self.reference_layout = None
        self.paper_marks = {layout.layout_id: template.paper_origin(layout) for layout in template.effective_layouts
                            if layout.layout_id in self.layouts and template.paper_origin(layout) is not None}
        self.translated = False

    @property
    def complete(self):
        return len(self.entries) == len(self.layouts) and len(self.layouts) > 1

    def place_from_reference(self, layout, reference):
        mark = self.paper_marks.get(layout)
        if not mark or reference is None:
            return None
        if layout == self.reference_layout:
            return reference
        measured = reference.alignment
        transform = self.axes.register(measured.a, reference.position, angle=measured.angle, scale=measured.scale)
        alignment = replace(mark, angle=measured.angle, scale=measured.scale)
        return replace(reference, alignment=alignment, position=transform.place(mark.a))

    def measure(self, layout, alignment, position, source, *, translate=False, fixed=False, recalled=False):
        if layout not in self.layouts:
            raise ValueError("当前页面不属于这组模板版式。")
        if translate:
            if not self.complete:
                raise ValueError("请先分别对准此模板的所有版式。")
            previous = self.entries[layout]
            if (alignment.angle, alignment.scale) != (previous.alignment.angle, previous.alignment.scale):
                raise ValueError("方向或比例已变化，请重新测量各版式。")
            old_registration = self.axes.register(previous.alignment.a, previous.position,
                                                  angle=alignment.angle, scale=alignment.scale)
            old_x, old_y = old_registration.place(alignment.a)
            dx, dy = position[0] - old_x, position[1] - old_y
            entries = {key: replace(item, position=machine_point((item.position[0] + dx, item.position[1] + dy)),
                                    source=f"本次连接 · 按{source}平移")
                       for key, item in self.entries.items()}
            self.entries = entries
        elif self.complete and (self.translated or self.entries[layout].alignment.angle != alignment.angle
                                or self.entries[layout].alignment.scale != alignment.scale):
            self.entries.clear()
        action = "确认" if recalled else "实测"
        self.entries[layout] = FixturePlacement(alignment, position, self.setup, f"本次连接 · {source}{action}",
                                                session_only=not fixed)
        self.translated = translate
        self.reference_layout = layout if layout in self.paper_marks else None


def fixture_placement(panel, template, snapshot, index):
    """Return the explicitly registered fixture placement in this connection's coordinates."""
    if snapshot is None or not panel.profile or not panel.profile.datum or panel.frame is None:
        return None
    page_key, size, alignment, title = page_context(template, snapshot, index)
    source = template.layout(index) if isinstance(template, FlowTemplate) else None
    key = fixture_page(page_key, source, snapshot, index)
    setup = panel.store.fixture_setup(panel.profile, key, alignment)
    if not setup:
        return None
    record = panel.store.place(panel.profile, key, setup, alignment)
    position = panel.store.placed_position(panel.profile, record, connection=panel.connection_id,
                                           offset=panel.offset, datum_origin=panel.frame)
    if position is None:
        return None
    saved = PageAlignment(**record["correction"])
    saved = panel.profile.calibrated(saved)
    saved.validate_size(*size)
    provenance = record.get("source_page")
    if isinstance(provenance, dict) and provenance.get("document") == snapshot.document_id:
        number = provenance.get("number")
        if type(number) is int and number > 0:
            title += f" · 本稿第 {number} 页登记"
    return FixturePlacement(saved, position, setup, title)


class AlignmentCanvas(InkViewport):
    picked = QtCore.Signal(float, float)

    def __init__(self, size, backdrop):
        view = SampleView()
        super().__init__(view)
        view.bounds = QtCore.QRectF(0, 0, *size)
        view.reset()
        self.backdrop = backdrop
        self.points = []
        self.editable = False
        self.checking = False
        self.setMinimumSize(240, 310)
        self.setAccessibleName("纸面预览 · 选择对位点")
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)

    def has_ink(self):
        # The paper itself can be aligned even without a background image.
        return True

    def ink_clicked(self, position):
        inverse, invertible = self.drawing_transform().inverted()
        spot = inverse.map(position)
        if (self.editable or self.checking) and invertible and self.view.bounds.contains(spot):
            self.picked.emit(spot.x(), spot.y())

    def paintEvent(self, _event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), self.palette().window())
        transform = self.drawing_transform()
        rect = transform.mapRect(self.view.bounds)
        painter.fillRect(rect, QtGui.QColor("white"))
        if not self.backdrop.isNull():
            painter.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform)
            painter.drawImage(rect, self.backdrop)
        painter.save()
        painter.setClipRect(rect)
        for title, (x, y) in self.points:
            spot = transform.map(QtCore.QPointF(x, y))
            painter.setPen(QtGui.QPen(QtGui.QColor("#005c92"), 2))
            painter.drawLine(spot - QtCore.QPointF(7, 0), spot + QtCore.QPointF(7, 0))
            painter.drawLine(spot - QtCore.QPointF(0, 7), spot + QtCore.QPointF(0, 7))
            painter.drawText(spot + QtCore.QPointF(7, 15), title)
        painter.restore()


class TemplateOriginDialog(QtWidgets.QDialog):
    """Pick a paper coordinate on the reusable source layout, independently of the plotter."""
    def __init__(self, template, layout, parent):
        super().__init__(parent)
        _, size, _, title = page_context(template, layout=layout)
        self.setWindowTitle(f"补设模板原点 · {title}")
        self.resize(600, 650)
        column = QtWidgets.QVBoxLayout(self)
        column.addWidget(label("点击每次换纸时容易找到的标记。Ctrl + 滚轮缩放，放大后可拖动。"))
        image = QtGui.QImage.fromData(layout.background.png_bytes(), "PNG") if layout.background else QtGui.QImage()
        self.canvas = AlignmentCanvas(size, image)
        self.canvas.editable = True
        column.addWidget(self.canvas, 1)
        self.coordinates = label("请选择纸面原点。")
        column.addWidget(self.coordinates)
        column.addWidget(label("纸面原点将同步保存到模板库和当前文档。使用此版式的所有循环页会一起更新。"))
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        self.save = buttons.addButton("保存并应用", QtWidgets.QDialogButtonBox.ButtonRole.AcceptRole)
        self.save.setEnabled(False)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        column.addWidget(buttons)
        self.alignment = None
        self.canvas.picked.connect(self.pick)

    def pick(self, x, y):
        self.alignment = PageAlignment((round(x, 3), round(y, 3)))
        self.canvas.points = [("原点", self.alignment.a)]
        self.canvas.update()
        self.coordinates.setText(f"纸面原点 X {x:.3f} · Y {y:.3f} mm")
        self.save.setEnabled(True)


class AlignmentDialog(QtWidgets.QDialog):
    def __init__(self, panel, parent, page, size, alignment, title, *,
                 source=None, snapshot=None, index=0, configure=False, calibration=False):
        super().__init__(parent)
        from .machine_panel import MachinePreview, field, pair_widget

        self.panel, self.page, self.size_mm = panel, page, size
        layout = source
        if layout is None and isinstance(panel.template, FlowTemplate):
            layout = panel.template.layout(index)
        self.source_page = dict(document=snapshot.document_id, number=index + 1) if snapshot else None
        self.fixture_page = fixture_page(page, layout, snapshot, index)
        self.document_snapshot = snapshot
        self.layout_id = layout.layout_id if layout is not None else None
        self.group = panel.session_group() if snapshot is not None and not configure and not calibration else None
        self.live_measurement = False
        self.original = alignment
        self.recalled_alignment = None
        self.configure = configure
        self.calibration = calibration
        self.position = None
        self.accepted_connection = None
        self.measurement = self.measurement_b = None
        self.offset = None
        self.setWindowTitle(("初始化纸面校准" if calibration else "模板原点" if configure else "对准纸张") + f" · {title}")
        self.resize(730, 530)
        col = QtWidgets.QVBoxLayout(self)
        row = QtWidgets.QHBoxLayout()
        col.addLayout(row, 1)
        image = QtGui.QImage()
        if source and source.background:
            image = QtGui.QImage.fromData(source.background.png_bytes(), "PNG")
        elif snapshot:
            image = MachinePreview.raster(
                snapshot.pages[index].background.png_base64 if snapshot.pages[index].background else None
            )
        self.canvas = AlignmentCanvas(size, image)
        preview = QtWidgets.QVBoxLayout()
        row.addLayout(preview, 1)
        preview.addWidget(self.canvas, 1)
        tools = QtWidgets.QHBoxLayout()
        preview.addLayout(tools)
        tools.addWidget(label("Ctrl + 滚轮缩放 · 放大后拖动"))
        tools.addStretch()
        self.zoom_reset = QtWidgets.QToolButton()
        self.zoom_reset.setText("100%")
        self.zoom_reset.setToolTip("恢复整页视图")
        self.zoom_reset.setAccessibleName("恢复整页视图")
        self.zoom_reset.clicked.connect(self.canvas.view.reset)
        self.canvas.view.changed.connect(
            lambda: self.zoom_reset.setText(f"{self.canvas.view.zoom:.0%}"))
        tools.addWidget(self.zoom_reset)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        controls = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(controls)
        form.setContentsMargins(0, 0, 0, 0)
        scroll.setWidget(controls)
        row.addWidget(scroll, 1)
        self.device_name = label("")
        manage = panel.button("设备管理…", lambda: panel.open_devices(self))
        self.manage = manage
        if calibration:
            form.addRow(self.device_name)
            form.addRow(label("在纸上选两个已知位置，分别对准并记录 A、B。保存的方向和比例用于这台设备的所有摆放。"))
        else:
            form.addRow(self.device_name, manage)
        self.setup = QtWidgets.QLineEdit(panel.setup)
        self.setup.setMaxLength(64)
        self.setup_names = QtCore.QStringListModel(self)
        self.setup.setCompleter(QtWidgets.QCompleter(self.setup_names, self.setup))
        self.setup_profile = None
        if not calibration:
            form.addRow("摆放基准", self.setup)
        self.setup.textChanged.connect(self.change_setup)
        self.fixture = QtWidgets.QCheckBox("使用固定纸张限位")
        self.fixture.setToolTip("在设备管理中登记并找回纸角后，可保存同一挡边、纸型、朝向和本页版式的摆放。")
        self.fixture.toggled.connect(self.change_setup)
        if not calibration:
            form.addRow(self.fixture)
        self.fixture_hint = label("")
        form.addRow(self.fixture_hint)
        self.pdf_page = title.startswith("PDF ") or (snapshot is not None and snapshot.pages[index].background is not None)
        self.shift_group = QtWidgets.QCheckBox("纸张方向未变，用本次实测原点平移其余版式")
        self.shift_group.setToolTip("只在本次连接中生效。移动纸张后保持相同朝向和比例，各版式保留原有角度、比例和相对位置。")
        form.addRow(self.shift_group)
        old = self.group.entries.get(self.layout_id) if self.group else None
        current = alignment or (old.alignment if old else None)
        if configure and current is None and panel.profile:
            try:
                record = panel.store.place(panel.profile, self.page, panel.setup, None)
                if record is None and panel.profile.datum:
                    setup = panel.store.fixture_setup(panel.profile, self.fixture_page, None)
                    if setup:
                        record = panel.store.place(panel.profile, self.fixture_page, setup, None)
                if record:
                    candidate = PageAlignment(record["correction"]["a"])
                    candidate.validate_size(*size)
                    current = candidate
                    form.addRow(label("已填入本机对此版式记录的纸面原点。确认后请保存模板修改。"))
            except (OSError, ValueError, KeyError, TypeError) as error:
                form.addRow(label(f"无法读取已存原点：{error}"))
        if current is None:
            current = PageAlignment((min(15., size[0] / 4), min(15., size[1] / 4)))
        self.a = tuple(field(value, low=0, high=limit) for value, limit in zip(current.a, size, strict=True))
        self.b = tuple(field(value, low=0, high=limit) for value, limit in zip(
            current.b or (size[0] - min(15., size[0] / 4), current.a[1]), size, strict=True
        ))
        self.pick = QtWidgets.QComboBox()
        self.pick.addItems(("A 点", "B 点"))
        self.canvas.editable = calibration or configure or alignment is None
        if calibration:
            form.addRow("在预览放置", self.pick)
        self.canvas.picked.connect(self.pick_point)
        form.addRow("纸面 A 点 X / Y" if calibration else "纸面原点 X / Y", pair_widget(self.a))
        if calibration:
            form.addRow("纸面 B 点 X / Y", pair_widget(self.b))
        self.nudge = panel.motion_controls(panel.jog)
        form.addRow(self.nudge)
        self.pen_button = panel.button("落笔", panel.toggle_pen)
        form.addRow(self.pen_button)
        self.pen_position = label("")
        form.addRow("当前笔位", self.pen_position)
        self.record_a = panel.button("记录实地 A 点" if calibration else "将当前笔位设为原点", self.capture_a)
        self.record_b = panel.button("记录实地 B 点", self.capture_b)
        form.addRow(pair_widget((self.record_a, self.record_b)) if calibration else self.record_a)
        self.c_point = self.c_visit = None
        self.check_c = QtWidgets.QCheckBox("用第三点复核套打位置（可选）")
        form.addRow(self.check_c)
        self.c_help = label("点击预览中离 A 较远的清晰交点 C，再将笔尖移过去。")
        self.c_move = panel.button("抬笔移到预测的 C 点", self.visit_c)
        self.c_read = panel.button("已对准纸面交点，读取偏差", self.read_c)
        self.c_result = label("")
        for control in (self.c_help, self.c_move, self.c_read, self.c_result):
            form.addRow(control)
        self.check_c.toggled.connect(self.toggle_c)
        self.recall = panel.button("使用已保存的摆放…", self.restore)
        if not calibration:
            form.addRow(self.recall)
        self.details = label("")
        form.addRow(self.details)
        if not configure and not calibration:
            if alignment:
                form.addRow(label("模板已设置纸面原点。将笔尖对准图中的纸面原点并确认。同一摆放下，其他已设原点的版式会自动换算。"))
            else:
                form.addRow(label("本页可临时对位。要随模板保存纸面原点，请在模板工作台设置并保存，再应用到当前文档。"))
        self.status = label("")
        form.addRow(self.status)
        self.motion_error = label("")
        set_tone(self.motion_error, "danger")
        form.addRow(self.motion_error)
        for spin in self.a:
            spin.setReadOnly(not self.canvas.editable)
            spin.valueChanged.connect(self.clear_measurement)
        for spin in self.b:
            spin.setReadOnly(not self.canvas.editable and current.b is not None)
            spin.valueChanged.connect(self.clear_b)
        self.buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        self.stop = panel.button("停止点动", panel.stop)
        self.stop.setProperty("inkRole", "danger")
        self.buttons.addButton(self.stop, QtWidgets.QDialogButtonBox.ButtonRole.ActionRole)
        self.save = self.buttons.addButton("保存设备校准" if calibration else "保存模板原点" if configure else "确认原点",
                                           QtWidgets.QDialogButtonBox.ButtonRole.AcceptRole)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        col.addWidget(self.buttons)
        panel.machine_state.connect(self.refresh)
        panel.worker.succeeded.connect(self.c_motion_finished)
        self.alignment = current
        self.refresh()

    def pick_point(self, x, y):
        if self.check_c.isChecked():
            self.c_point = (x, y)
            self.c_visit = None
            self.c_result.clear()
            self.refresh()
            return
        point = self.b if self.calibration and self.pick.currentIndex() == 1 else self.a
        for spin, value in zip(point, (x, y), strict=True):
            spin.setValue(value)

    def toggle_c(self, enabled):
        self.canvas.checking = enabled
        self.c_visit = None
        self.c_result.clear()
        self.refresh()
        if enabled:
            self.canvas.setFocus()

    def c_target(self):
        if not self.calibration or self.c_point is None or self.measurement is None or not self.panel.profile:
            return None
        marks = self.markings()
        axes = self.panel.profile.axes
        if self.measurement_b is None:
            return None
        angle, scale = axes.measure((marks.a, marks.b), self.measurement, self.measurement_b)
        return axes.register(marks.a, self.measurement, angle=angle, scale=scale)

    def visit_c(self):
        try:
            transform = self.c_target()
            if transform and self.panel.submit("return", transform.place(self.c_point),
                                               self.panel.confirmed_area, self.panel.profile.feed):
                self.c_visit = (self.panel.connection_id, transform, self.c_point)
                self.c_result.setText("到位后用方向按钮微调至纸面交点。")
                self.canvas.setFocus()
        except ValueError as error:
            self.status.setText(str(error))

    def c_motion_finished(self, kind, status):
        if kind in {"return", "jog"} and self.c_visit and status and self.check_c.isChecked():
            dx, dy = self.c_delta(status)
            self.c_result.setText(f"相对预测点已微调：横向 {dx:+.3f} mm，纵向 {dy:+.3f} mm。"
                                  "对准交点后读取最终偏差。")

    def c_delta(self, status):
        _, transform, point = self.c_visit
        x, y = transform.place(point)
        u, v = self.panel.profile.axes.unmap(status.position[0] - x, status.position[1] - y)
        return ((transform.cosine * u + transform.sine * v) / transform.scale,
                (-transform.sine * u + transform.cosine * v) / transform.scale)

    def read_c(self):
        context = self.c_visit
        def measured(status):
            if context != self.c_visit or context is None:
                return
            dx, dy = self.c_delta(status)
            self.c_result.setText(f"纸面交点相对预测位置：横向 {dx:+.3f} mm，纵向 {dy:+.3f} mm（右、下为正）。")
        self.panel.capture_position(measured)

    def keyPressEvent(self, event):
        key = QtCore.Qt.Key
        directions = {key.Key_Left: (-1, 0), key.Key_Right: (1, 0),
                      key.Key_Up: (0, -1), key.Key_Down: (0, 1)}
        if (event.key() in directions and self.canvas.hasFocus() and self.nudge.step.isEnabled()
                and not event.modifiers() and not event.isAutoRepeat()):
            self.nudge.buttons[directions[event.key()]].click()
            event.accept()
            return
        super().keyPressEvent(event)

    def change_setup(self):
        self.recalled_alignment = None
        self.status.clear()
        self.clear_measurement()

    def clear_measurement(self):
        self.live_measurement = False
        self.measurement = None
        self.clear_b()

    def clear_b(self):
        self.measurement_b = None
        self.c_visit = None
        self.c_result.clear()
        self.refresh()

    def points(self):
        return tuple(tuple(spin.value() for spin in pair) for pair in (self.a, self.b))

    def markings(self):
        a, b = self.points()
        prior = None
        if self.group and self.group.setup == self.setup.text().strip():
            prior = self.group.entries.get(self.layout_id)
        initial = self.recalled_alignment or (prior.alignment if prior else self.original)
        legacy_b = initial.b if initial and initial.a == a else None
        return PageAlignment(a, b if self.calibration else legacy_b,
                             initial.angle if initial else 0., initial.scale if initial else 1.)

    def refresh(self):
        profile = self.panel.profile
        connected = profile is not None and self.panel.device is not None
        idle = self.panel.busy is None
        if not self.calibration and not same_alignment_profile(profile, self.setup_profile):
            previous = self.setup_profile.datum if self.setup_profile else None
            datum = profile.datum if profile else None
            new_datum = datum and (not previous or previous.id != datum.id)
            if new_datum:
                with QtCore.QSignalBlocker(self.fixture):
                    self.fixture.setChecked(True)
            elif not profile or not profile.datum:
                with QtCore.QSignalBlocker(self.fixture):
                    self.fixture.setChecked(False)
            self.setup_profile = profile
            self.recalled_alignment = None
            try:
                setups = set(self.panel.store.setups(profile, self.page)) if profile else set()
                if profile and profile.datum:
                    setups.update(self.panel.store.setups(profile, self.fixture_page))
                if new_datum:
                    setup = self.panel.store.fixture_setup(profile, self.fixture_page, self.original)
                    if setup:
                        with QtCore.QSignalBlocker(self.setup):
                            self.setup.setText(setup)
                self.setup_names.setStringList(sorted(setups))
            except (OSError, ValueError, KeyError, TypeError) as error:
                self.status.setText(str(error))
        if self.measurement is not None and (not same_alignment_profile(self.measured_device, profile) or not connected
                                             or self.measured_connection != self.panel.connection_id
                                             or self.measured_frame != self.panel.frame
                                             or self.offset != self.panel.offset):
            self.measurement = self.measurement_b = None
        group = self.group
        matched = (group is not None and group is self.panel.session_group()
                   and group.setup == self.setup.text().strip())
        self.shift_group.setVisible(matched and not group.paper_marks and group.complete)
        self.shift_group.setEnabled(bool(matched and not group.paper_marks and group.complete
                                        and self.live_measurement and self.measurement is not None and idle))
        self.fixture.setEnabled(idle and bool(profile and profile.datum))
        fixed = self.fixture.isChecked()
        located = not (profile and profile.datum) or self.panel.frame is not None
        self.fixture_hint.setVisible(fixed and not self.calibration)
        if fixed:
            hint = ("请先在设备管理中对准已登记的纸角，找回机身基准。" if not located else
                    "两条纸边靠齐原挡边，保持同一纸型和朝向。记录原点后保存，换纸时可沿用。")
            if self.pdf_page:
                hint += "套打前请核对原稿上的标记。"
            self.fixture_hint.setText(hint)
        self.device_name.setText(profile.name if profile else "尚未选择设备")
        self.panel.refresh_motion_controls(self.nudge, connected and idle and not self.panel.closing
                                           and not self.panel.waiting_for_paper)
        self.pen_position.setText("正在抬笔点动…" if self.panel.busy == "jog" else
                                  self.panel.position_label.text() if connected else "请在设备管理中连接写字机。")
        self.panel.refresh_pen_button(self.pen_button)
        self.stop.setVisible(self.panel.busy in {"jog", "return", "pen"})
        self.stop.setEnabled(self.panel.stop_button.isEnabled())
        error = self.panel.report.text() if self.panel.report.property("inkTone") == "danger" else ""
        self.motion_error.setText(error)
        self.motion_error.setVisible(bool(error))
        self.manage.setEnabled(idle and not self.panel.batch_active)
        self.recall.setText("纸已靠齐，沿用对位" if fixed else "使用已保存的摆放…")
        self.recall.setEnabled(idle and connected and bool(self.setup.text().strip()))
        self.record_a.setEnabled(connected and idle and (located or self.calibration))
        self.record_b.setEnabled(connected and idle and self.measurement is not None and self.calibration)
        for spin in self.b:
            spin.setEnabled(self.calibration)
        self.save.setEnabled(idle and (self.configure or self.measurement is not None)
                             and (not self.calibration or self.measurement_b is not None))
        a, b = self.points()
        self.canvas.points = [("A" if self.calibration else "原点", a)]
        if self.calibration:
            self.canvas.points.append(("B", b))
        checking = self.check_c.isChecked()
        self.pick.setEnabled(not checking)
        self.check_c.setEnabled(idle)
        self.check_c.setVisible(self.calibration)
        for control in (self.c_help, self.c_move, self.c_read, self.c_result):
            control.setVisible(checking)
        try:
            transform = self.c_target()
        except ValueError:
            transform = None
        if not transform or self.c_visit != (self.panel.connection_id, transform, self.c_point):
            self.c_visit = None
            self.c_result.clear()
        self.c_move.setEnabled(bool(idle and connected and transform and self.panel.range_ready))
        self.c_read.setEnabled(bool(self.c_visit and connected and idle and self.panel.pen_raised))
        if checking and self.c_point is not None:
            self.canvas.points.append(("C", self.c_point))
        self.canvas.update()
        marks = []
        for name, point in (("A" if self.calibration else "原点", self.measurement), ("B", self.measurement_b)):
            if point is not None:
                marks.append(f"实地 {name} · X {point[0]:.3f} · Y {point[1]:.3f} mm")
        self.details.setText("\n".join(marks) or "点击方向按钮，将笔尖移到纸面标记，再记录实地点。")

    def capture_a(self):
        def read(status):
            self.measured_device = self.panel.profile
            self.measured_connection = self.panel.connection_id
            self.measured_frame = self.panel.frame
            self.offset = self.panel.offset
            self.measurement = status.position[:2]
            self.live_measurement = True
            self.clear_b()
            self.status.clear()
        self.panel.capture_position(read)

    def capture_b(self):
        def read(status):
            if self.measurement is not None and self.offset == self.panel.offset:
                self.measurement_b = status.position[:2]
                self.refresh()
        self.panel.capture_position(read)

    def restore(self):
        self.live_measurement = False
        try:
            key = self.markings() if self.configure else self.original
            fixed = self.fixture.isChecked()
            page = self.fixture_page if fixed else self.page
            record = self.panel.store.place(self.panel.profile, page, self.setup.text().strip(), key)
            if not record:
                raise ValueError("此设备、本页和摆放基准下没有保存的实测对位。")
            saved = PageAlignment(**record["correction"])
            saved.validate_size(*self.size_mm)
            position = self.panel.store.placed_position(
                self.panel.profile, record, connection=self.panel.connection_id,
                offset=self.panel.offset, datum_origin=self.panel.frame)
            if fixed and (self.panel.frame is None or position is None):
                raise ValueError("请在设备管理中找回已登记的纸角，再沿用固定限位的摆放。")
            if position is None or (not fixed and record.get("connection") != self.panel.connection_id):
                self.recalled_alignment = saved
                for controls, point in ((self.a, saved.a), (self.b, saved.b)):
                    if point is not None:
                        for control, value in zip(controls, point, strict=True):
                            with QtCore.QSignalBlocker(control):
                                control.setValue(value)
                self.clear_measurement()
                self.status.setText("已载入保存的方向与比例。请按本次连接的坐标重新记录原点。")
                return
            context = self.panel.connection_id, self.panel.profile, self.panel.frame, self.panel.offset
            if fixed or self.panel.confirm("确认纸张摆放", "请确认纸张和设备坐标仍与记录时一致。"):
                if context != (self.panel.connection_id, self.panel.profile, self.panel.frame, self.panel.offset):
                    raise ValueError("设备定位已变化，请重新核对摆放。")
                setup = self.setup.text().strip()
                if fixed:
                    self.panel.store.select_fixture_setup(self.panel.profile, page, key, setup)
                if self.source_page and not self.configure:
                    group = self.panel.session_group(setup)
                    if group:
                        source = f"第 {self.source_page['number']} 页"
                        group.measure(self.layout_id, self.panel.profile.calibrated(saved), position, source, recalled=True, fixed=fixed)
                self.alignment = saved
                self.position = position
                self.accepted_connection = self.panel.connection_id
                self.panel.setup = setup
                if not fixed and self.panel.datum_located:
                    self.panel.store.select_fixture_setup(self.panel.profile, self.fixture_page, key, "")
                super().accept()
        except (OSError, ValueError, KeyError, TypeError) as error:
            self.status.setText(str(error))

    def accept(self):
        self.refresh()
        if not self.save.isEnabled():
            return
        try:
            result = self.markings()
            if self.measurement_b is not None:
                angle, scale = self.panel.profile.axes.measure((result.a, result.b),
                                                               self.measurement, self.measurement_b)
                result = replace(result, angle=angle, scale=scale)
            result.validate_size(*self.size_mm)
            if self.calibration:
                self.panel.save_profile(replace(self.panel.profile, paper_calibration=(result.angle, result.scale)))
                self.alignment = result
                super().accept()
                return
            if self.measurement is not None:
                setup = self.setup.text().strip()
                if not setup:
                    raise ValueError("请填写摆放基准名称。")
                key = result if self.configure else self.original
                page = self.fixture_page if self.fixture.isChecked() else self.page
                if self.document_snapshot is not None and self.panel.snapshot is not self.document_snapshot:
                    raise ValueError("文档已更新，请重新打开当前页对位。")
                group = self.panel.session_group(setup) if not self.configure and self.source_page else None
                translate = self.shift_group.isEnabled() and self.shift_group.isChecked()
                if translate and (group is None or group is not self.group):
                    raise ValueError("设备定位或摆放已变化，请重新记录原点。")
                if not translate:
                    self.panel.store.place(self.panel.profile, page, setup, key, self.measurement,
                                           self.offset, result, connection=self.measured_connection,
                                           datum_origin=self.measured_frame, select_fixture=self.fixture.isChecked(),
                                           source_page=self.source_page)
                    if not self.fixture.isChecked() and self.panel.datum_located:
                        self.panel.store.select_fixture_setup(self.panel.profile, self.fixture_page, key, "")
                if group is not None and self.live_measurement:
                    source = f"第 {self.source_page['number']} 页"
                    group.measure(self.layout_id, self.panel.profile.calibrated(result), self.measurement, source,
                                  translate=translate, fixed=self.fixture.isChecked())
                self.accepted_connection = self.measured_connection
                self.panel.setup = setup
            self.alignment, self.position = result, self.measurement
            super().accept()
        except (OSError, ValueError, KeyError, TypeError) as error:
            self.status.setText(str(error))

    def reject(self):
        if self.panel.busy in {"position-read", "jog", "return", "pen"}:
            return
        super().reject()
