"""Paper marks on the source template and placement readings on this computer."""

import math
from dataclasses import replace

from PySide6 import QtCore, QtGui, QtWidgets

from ..document.flow_template import FlowTemplate
from ..document.schema import digest
from ..plotter.profiles import PageAlignment
from ..settings_pages import label


def page_context(template, snapshot=None, index=0, *, layout=None):
    if isinstance(template, FlowTemplate):
        source = layout or template.layout(index)
        size = (template.width_mm, template.height_mm)
        family = template.name
        page = digest([family, source.layout_id, source.source_sha256, source.source_page, size,
                       source.background.sha256 if source.background else None,
                       template.offset_x_mm, template.offset_y_mm])
        title = f"PDF 第 {source.source_page} 页" if source.source_page is not None else source.label
        return page, size, source.plotter_alignment, title
    paper = snapshot.page_profile
    size = paper.width_mm, paper.height_mm
    return digest([snapshot.document_id, index, size]), size, None, f"第 {index + 1} 页"


class AlignmentCanvas(QtWidgets.QWidget):
    picked = QtCore.Signal(float, float)

    def __init__(self, size, backdrop):
        super().__init__()
        self.size_mm = size
        self.backdrop = backdrop
        self.points = []
        self.editable = False
        self.setMinimumSize(240, 310)
        self.setAccessibleName("纸面预览 · 选择对位点")
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)

    def geometry_on_screen(self):
        w, h = self.size_mm
        scale = min((self.width() - 28) / w, (self.height() - 28) / h)
        rect = QtCore.QRectF(0, 0, w * scale, h * scale)
        rect.moveCenter(QtCore.QRectF(self.rect()).center())
        return rect, scale

    def mousePressEvent(self, event):
        rect, scale = self.geometry_on_screen()
        if self.editable and event.button() == QtCore.Qt.MouseButton.LeftButton and rect.contains(event.position()):
            spot = (event.position() - rect.topLeft()) / scale
            self.picked.emit(spot.x(), spot.y())

    def paintEvent(self, _event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), self.palette().window())
        rect, scale = self.geometry_on_screen()
        painter.fillRect(rect, QtGui.QColor("white"))
        if not self.backdrop.isNull():
            painter.drawImage(rect, self.backdrop)
        painter.save()
        painter.setClipRect(rect)
        for title, (x, y) in self.points:
            spot = rect.topLeft() + QtCore.QPointF(x * scale, y * scale)
            painter.setPen(QtGui.QPen(QtGui.QColor("#005c92"), 2))
            painter.drawLine(spot - QtCore.QPointF(7, 0), spot + QtCore.QPointF(7, 0))
            painter.drawLine(spot - QtCore.QPointF(0, 7), spot + QtCore.QPointF(0, 7))
            painter.drawText(spot + QtCore.QPointF(7, 15), title)
        painter.restore()


class AlignmentDialog(QtWidgets.QDialog):
    def __init__(self, panel, parent, page, size, alignment, title, *,
                 source=None, snapshot=None, index=0, configure=False):
        super().__init__(parent)
        from .machine_panel import MachinePreview, field, pair_widget

        self.panel, self.page, self.size_mm = panel, page, size
        self.original = alignment
        self.configure = configure
        self.position = None
        self.measurement = self.measurement_b = None
        self.offset = None
        self.setWindowTitle(f"书写原点与对位 · {title}")
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
        row.addWidget(self.canvas, 1)
        form = QtWidgets.QFormLayout()
        row.addLayout(form, 1)
        self.device_name = label("")
        manage = panel.button("设备管理…", lambda: panel.open_devices(self))
        self.manage = manage
        form.addRow(self.device_name, manage)
        self.setup = QtWidgets.QLineEdit(panel.setup)
        self.setup.setMaxLength(64)
        self.setup_names = QtCore.QStringListModel(self)
        self.setup.setCompleter(QtWidgets.QCompleter(self.setup_names, self.setup))
        self.setup_profile = None
        form.addRow("摆放基准", self.setup)
        self.setup.textChanged.connect(self.clear_measurement)
        current = alignment or PageAlignment((min(15., size[0] / 4), min(15., size[1] / 4)))
        self.a = tuple(field(value, low=0, high=limit) for value, limit in zip(current.a, size, strict=True))
        self.b = tuple(field(value, low=0, high=limit) for value, limit in zip(
            current.b or (size[0] - min(15., size[0] / 4), current.a[1]), size, strict=True
        ))
        self.pick = QtWidgets.QComboBox()
        self.pick.addItems(("A 点", "B 点"))
        self.canvas.editable = configure or alignment is None
        if self.canvas.editable:
            form.addRow("在预览放置", self.pick)
        self.canvas.picked.connect(self.pick_point)
        form.addRow("纸面 A 点 X / Y", pair_widget(self.a))
        self.use_b = QtWidgets.QCheckBox("补录 B 点以重测方向与比例")
        form.addRow(self.use_b)
        form.addRow("纸面 B 点 X / Y", pair_widget(self.b))
        self.record_a = panel.button("记录实地 A 点", self.capture_a)
        self.record_b = panel.button("记录实地 B 点", self.capture_b)
        form.addRow(pair_widget((self.record_a, self.record_b)))
        self.recall = panel.button("使用已保存的摆放…", self.restore)
        form.addRow(self.recall)
        self.details = label("")
        form.addRow(self.details)
        self.status = label("")
        form.addRow(self.status)
        for spin in self.a:
            spin.setReadOnly(not self.canvas.editable)
            spin.valueChanged.connect(self.clear_measurement)
        for spin in self.b:
            spin.setReadOnly(not self.canvas.editable and current.b is not None)
            spin.valueChanged.connect(self.clear_b)
        self.use_b.toggled.connect(self.clear_b)
        self.buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        self.save = self.buttons.addButton("保存页面与对位" if configure else "确认对位",
                                           QtWidgets.QDialogButtonBox.ButtonRole.AcceptRole)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        col.addWidget(self.buttons)
        panel.machine_state.connect(self.refresh)
        self.alignment = current
        self.refresh()

    def pick_point(self, x, y):
        point = self.b if self.pick.currentIndex() == 1 else self.a
        if point is self.b:
            self.use_b.setChecked(True)
        for spin, value in zip(point, (x, y), strict=True):
            spin.setValue(value)

    def clear_measurement(self):
        self.measurement = None
        self.clear_b()

    def clear_b(self):
        self.measurement_b = None
        self.refresh()

    def points(self):
        return tuple(tuple(spin.value() for spin in pair) for pair in (self.a, self.b))

    def markings(self):
        a, b = self.points()
        initial = self.original
        return PageAlignment(a, b if self.use_b.isChecked() else initial.b if initial else None,
                             initial.angle if initial else 0., initial.scale if initial else 1.)

    def refresh(self):
        profile = self.panel.profile
        connected = profile is not None and self.panel.device is not None
        idle = self.panel.busy is None
        if profile != self.setup_profile:
            self.setup_profile = profile
            try:
                self.setup_names.setStringList(self.panel.store.setups(profile, self.page) if profile else [])
            except (OSError, ValueError, KeyError, TypeError) as error:
                self.status.setText(str(error))
        if self.measurement is not None and (self.measured_device != profile or not connected):
            self.measurement = self.measurement_b = None
        self.device_name.setText(profile.name if profile else "尚未选择设备")
        self.manage.setEnabled(idle and not self.panel.batch_active)
        self.recall.setEnabled(idle and connected and bool(self.setup.text().strip()))
        self.record_a.setEnabled(connected and idle)
        self.record_b.setEnabled(connected and idle and self.measurement is not None and self.use_b.isChecked())
        for spin in self.b:
            spin.setEnabled(self.use_b.isChecked())
        self.save.setEnabled(idle and (self.configure or self.measurement is not None)
                             and (not self.use_b.isChecked() or self.measurement is None
                                  or self.measurement_b is not None))
        a, b = self.points()
        self.canvas.points = [("A", a)]
        if self.use_b.isChecked() or (self.original and self.original.b):
            self.canvas.points.append(("B", b))
        self.canvas.update()
        marks = []
        for name, point in (("A", self.measurement), ("B", self.measurement_b)):
            if point is not None:
                marks.append(f"实地 {name} · X {point[0]:.3f} · Y {point[1]:.3f} mm")
        self.details.setText("\n".join(marks) or "将笔尖移到纸面标记后记录。")

    def capture_a(self):
        def read(status):
            self.measured_device = self.panel.profile
            self.offset = self.panel.offset
            self.measurement = status.position[:2]
            self.clear_b()
        self.panel.capture_position(read)

    def capture_b(self):
        def read(status):
            if self.measurement is not None and self.offset == self.panel.offset:
                self.measurement_b = status.position[:2]
                self.refresh()
        self.panel.capture_position(read)

    def restore(self):
        try:
            key = self.markings() if self.configure else self.original
            record = self.panel.store.place(self.panel.profile, self.page, self.setup.text().strip(), key)
            if not record:
                raise ValueError("此设备、本页和摆放基准下没有保存的实测对位。")
            if record["offset"] != (list(self.panel.offset) if self.panel.offset is not None else None):
                raise ValueError("设备工作零点已变化，请重新记录 A 点。")
            if self.panel.confirm("确认纸张摆放", "请确认纸张和设备坐标仍与记录时一致。"):
                self.alignment = PageAlignment(**record["correction"])
                self.position = tuple(record["point"])
                self.panel.setup = self.setup.text().strip()
                super().accept()
        except (OSError, ValueError, KeyError, TypeError) as error:
            self.status.setText(str(error))

    def accept(self):
        if not self.save.isEnabled():
            return
        try:
            result = self.markings()
            if self.measurement_b is not None:
                angle, scale = self.panel.profile.axes.measure((result.a, result.b),
                                                               self.measurement, self.measurement_b)
                result = replace(result, angle=angle, scale=scale)
            result.validate_size(*self.size_mm)
            if self.measurement is not None:
                setup = self.setup.text().strip()
                if not setup:
                    raise ValueError("请填写摆放基准名称。")
                key = result if self.configure else self.original
                self.panel.store.place(self.panel.profile, self.page, setup, key, self.measurement,
                                       self.offset, result)
                self.panel.setup = setup
            self.alignment, self.position = result, self.measurement
            super().accept()
        except (OSError, ValueError, KeyError, TypeError) as error:
            self.status.setText(str(error))

    def reject(self):
        if self.panel.busy == "position-read":
            return
        super().reject()
