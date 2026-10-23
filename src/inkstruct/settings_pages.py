"""Reusable settings pages; changes remain local until the owner commits them."""

from dataclasses import fields, replace

from PySide6 import QtCore, QtGui, QtWidgets


def label(text):
    result = QtWidgets.QLabel(text)
    result.setWordWrap(True)
    result.setTextFormat(QtCore.Qt.TextFormat.PlainText)
    return result


class EmbeddedDialogKeys(QtCore.QObject):
    def eventFilter(self, watched, event):
        if event.type() == QtCore.QEvent.Type.KeyPress and event.key() == QtCore.Qt.Key.Key_Escape:
            # Embedded QDialogs must not hide just their own page on Escape.
            parent = watched.parentWidget()
            while parent is not None and not isinstance(parent, QtWidgets.QDialog):
                parent = parent.parentWidget()
            if parent is not None:
                parent.reject()
            return True
        return False


def embed(dialog):
    """Keep existing validators and precision rules without nested settings windows."""
    dialog.setWindowFlags(QtCore.Qt.WindowType.Widget)
    dialog.setMinimumSize(0, 0)
    dialog.setMaximumSize(16777215, 16777215)
    dialog._embedded_key_guard = EmbeddedDialogKeys(dialog)
    dialog.installEventFilter(dialog._embedded_key_guard)
    for buttons in dialog.findChildren(QtWidgets.QDialogButtonBox):
        buttons.hide()
    for button in dialog.findChildren(QtWidgets.QPushButton):
        if button.text() in {"恢复默认", "当前分类恢复默认"}:
            button.hide()
    return dialog


def acceptable(widget):
    for field in widget.findChildren(QtWidgets.QAbstractSpinBox):
        if field.isEnabled() and not field.hasAcceptableInput():
            field.setFocus()
            raise ValueError(
                f"{field.accessibleName() or field.objectName() or '数值'}输入无效，请检查范围。"
            )


class CompactSpinBox(QtWidgets.QDoubleSpinBox):
    def textFromValue(self, value):
        return (
            self.locale()
            .toString(value, "f", self.decimals())
            .rstrip("0")
            .rstrip(self.locale().decimalPoint())
        )


class ProfileForm(QtWidgets.QWidget):
    """Edit a subset of an immutable profile without rounding untouched fields."""

    def __init__(self, profile, specs, parent=None):
        super().__init__(parent)
        self.profile = profile
        self.controls, self.initial = {}, {}
        form = QtWidgets.QFormLayout(self)
        form.setRowWrapPolicy(QtWidgets.QFormLayout.RowWrapPolicy.WrapLongRows)
        for key, title, low, high, suffix in specs:
            control = CompactSpinBox(self)
            control.setObjectName(key)
            control.setAccessibleName(title)
            control.setDecimals(6)
            control.setRange(min(low, getattr(profile, key)), max(high, getattr(profile, key)))
            control.setSuffix(suffix)
            control.setSingleStep(0.5)
            control.setValue(getattr(profile, key))
            self.controls[key] = control
            self.initial[key] = control.value()
            form.addRow(title, control)

    def configuration(self):
        acceptable(self)
        return replace(
            self.profile,
            **{k: c.value() for k, c in self.controls.items() if c.value() != self.initial[k]},
        )

    def reset_defaults(self):
        default = type(self.profile)()
        owned = {field.name for field in fields(default)} & self.controls.keys()
        self.profile = replace(self.profile, **{k: getattr(default, k) for k in owned})
        for key, control in self.controls.items():
            control.setValue(getattr(default, key))
            self.initial[key] = control.value()


def section(layout, title, widget, *, expanded=False):
    toggle = QtWidgets.QToolButton()
    toggle.setText(title)
    toggle.setCheckable(True)
    toggle.setChecked(expanded)
    toggle.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon)

    def show(checked):
        toggle.setArrowType(
            QtCore.Qt.ArrowType.DownArrow if checked else QtCore.Qt.ArrowType.RightArrow
        )
        widget.setVisible(checked)

    toggle.toggled.connect(show)
    layout.addWidget(toggle)
    layout.addWidget(widget)
    show(expanded)
    return toggle


def fold_form(form, controls, title="更多设置"):
    content = QtWidgets.QWidget()
    nested = QtWidgets.QFormLayout(content)
    nested.setRowWrapPolicy(QtWidgets.QFormLayout.RowWrapPolicy.WrapLongRows)
    for control in controls:
        row = form.takeRow(control)
        if row.labelItem and row.labelItem.widget():
            nested.addRow(row.labelItem.widget(), control)
        else:
            nested.addRow(control)
    toggle = QtWidgets.QToolButton()
    toggle.setText(title)
    toggle.setCheckable(True)
    toggle.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon)

    def show(checked):
        toggle.setArrowType(
            QtCore.Qt.ArrowType.DownArrow if checked else QtCore.Qt.ArrowType.RightArrow
        )
        content.setVisible(checked)

    toggle.toggled.connect(show)
    form.addRow(toggle)
    form.addRow(content)
    show(False)
    return toggle


class CapturePreview(QtWidgets.QWidget):
    def __init__(self, page):
        super().__init__(page)
        self.page = page
        self.setMinimumSize(220, 190)
        self.setMaximumHeight(260)
        self.setAccessibleName("书写显示示意，仅影响屏幕")

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        r = QtCore.QRectF(self.rect()).adjusted(12, 12, -12, -12)
        size = min(r.width(), r.height()) * self.page.grid.value() / 100
        box = QtCore.QRectF(0, 0, size, size)
        box.moveCenter(r.center())
        p.fillRect(r, self.palette().base())
        p.setPen(QtGui.QPen(self.palette().mid().color(), 1))
        p.drawRect(box)
        p.drawLine(box.center().x(), box.top(), box.center().x(), box.bottom())
        p.drawLine(box.left(), box.center().y(), box.right(), box.center().y())
        p.setPen(
            QtGui.QPen(
                self.palette().text().color(),
                self.page.stroke.value() / 50,
                QtCore.Qt.PenStyle.SolidLine,
                QtCore.Qt.PenCapStyle.RoundCap,
            )
        )
        p.drawLine(
            box.left() + size * 0.2,
            box.top() + size * 0.75,
            box.center().x(),
            box.top() + size * 0.2,
        )
        p.drawLine(
            box.center().x(),
            box.top() + size * 0.2,
            box.right() - size * 0.2,
            box.top() + size * 0.75,
        )
        p.drawLine(
            box.left() + size * 0.32,
            box.top() + size * 0.55,
            box.right() - size * 0.32,
            box.top() + size * 0.55,
        )


class CapturePage(QtWidgets.QWidget):
    def __init__(self, collector):
        super().__init__()
        self.collector = collector
        self.base = collector.ui_settings
        column = QtWidgets.QVBoxLayout(self)
        column.addWidget(
            label("适用于汉字样本和标点与扩展。仅调整屏幕显示，不改变已录坐标、压力或采集进度。")
        )
        self.stroke = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.stroke.setRange(75, 400)
        self.stroke.setValue(round(self.base.stroke_width_scale * 100))
        self.grid = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.grid.setRange(45, 95)
        self.grid.setValue(round(self.base.grid_scale * 100))
        self.initial = (self.stroke.value(), self.grid.value())
        self.preview = CapturePreview(self)
        form = QtWidgets.QFormLayout()
        column.addLayout(form)
        self.values = []
        for title, slider in [("屏幕笔迹粗细", self.stroke), ("书写格大小", self.grid)]:
            row = QtWidgets.QHBoxLayout()
            value = QtWidgets.QSpinBox()
            value.setRange(slider.minimum(), slider.maximum())
            value.setSuffix(" %")
            value.setValue(slider.value())
            value.setAccessibleName(title)
            slider.valueChanged.connect(value.setValue)
            value.valueChanged.connect(slider.setValue)
            slider.valueChanged.connect(self.preview.update)
            row.addWidget(slider, 1)
            row.addWidget(value)
            form.addRow(title, row)
            self.values.append(value)
        column.addWidget(self.preview)
        column.addWidget(
            label(
                "示意：汉字、Aa、α 与括号均使用同一显示规则；字母正斜体和采集份数在“创建任务”中选择。"
            )
        )
        section(column, "配置位置", label(str(collector.ui_settings_store.path)))
        column.addStretch()

    def configuration(self):
        acceptable(self)
        changes = {}
        for key, control, initial in zip(
            ("stroke_width_scale", "grid_scale"), (self.stroke, self.grid), self.initial
        ):
            if control.value() != initial:
                changes[key] = control.value() / 100
        return replace(self.base, **changes).validated()

    def reset_defaults(self):
        default = type(self.base)()
        self.base = default
        self.stroke.setValue(round(default.stroke_width_scale * 100))
        self.grid.setValue(round(default.grid_scale * 100))
        self.initial = (self.stroke.value(), self.grid.value())


class LocalPreview(QtWidgets.QWidget):
    """Small isolated numeric sample; never re-layout the user's whole document."""

    def __init__(self, resolver, configuration, parent=None, *, letters=False):
        super().__init__(parent)
        from PySide6 import QtSvgWidgets

        from .assets.resolver import AssetResolver
        from .document.editing import SourceSession

        self.configuration = configuration
        available = "".join(c for c in "minimumWilliam" if c in resolver.pools) if letters else ""
        self.resolver = AssetResolver(
            embedded=tuple(g for char in dict.fromkeys("12345678." + available)
                           for g in resolver.pools.get(char, ())),
            builtin_numbers=True,
        )
        self.session = SourceSession(available + "\n\n12.34" if available else "12.34\n\n56.78")
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(label("局部预览 · 当前可用字形（不插入正文）"))
        self.svg = QtSvgWidgets.QSvgWidget()
        self.svg.setFixedHeight(160)
        layout.addWidget(self.svg)
        self.status = label("")
        layout.addWidget(self.status)
        self.timer = QtCore.QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(150)
        self.timer.timeout.connect(self.refresh)
        self.schedule()

    def schedule(self, *args):
        self.timer.start()

    def refresh(self):
        from xml.etree import ElementTree as ET

        from .document.markdown import parse_markdown
        from .document.schema import PageProfile
        from .layout.blocks import layout_markdown
        from .renderers.pages import page_svg

        try:
            style, flow = self.configuration()
            snapshot = layout_markdown(
                parse_markdown(self.session),
                self.resolver,
                page=PageProfile(width_mm=110, height_mm=120, margin_mm=5),
                style=style,
                flow=replace(flow, template=None, template_bindings=()),
            )
            svg = ET.fromstring(page_svg(snapshot, 0, debug=not snapshot.exportable))
            svg.set("viewBox", "0 0 110 60")
            self.svg.load(ET.tostring(svg))
            self.status.setText(
                "局部示例存在排版问题，请检查尺寸。" if not snapshot.exportable else ""
            )
        except (ValueError, TypeError) as error:
            self.svg.load(b'<svg xmlns="http://www.w3.org/2000/svg"/>')
            self.status.setText(str(error))
