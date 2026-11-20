"""Device management and commissioning for the shared N1 connection."""

from dataclasses import replace

from PySide6 import QtCore, QtWidgets

from ..plotter.grbl import MAX_WRITE_FEED
from ..plotter.physical import WorkArea
from ..plotter.profiles import DeviceAxes, DeviceProfile
from ..settings_pages import label, scroll_page
from .position_nudge import PositionNudge

AXIS_HELP = "点左右按钮时笔尖却上下移动，请勾选「交换 XY 轴」。笔尖沿正确的轴走反了方向，请勾选对应轴的镜像。勾选后可立即点动或试画确认。"
TRIAL_HELP = "请确保笔尖四周 100 mm 内可绘制。正常书写视角下，X 轴正向指正右方，Y 轴正向指正下方。"


class DeviceDialog(QtWidgets.QDialog):
    def __init__(self, panel, parent=None):
        super().__init__(parent or panel)
        from .machine_panel import field, pair_widget

        self.panel = panel
        self.setWindowTitle("写字机设备管理")
        self.resize(850, 680)
        col = QtWidgets.QVBoxLayout(self)
        body = QtWidgets.QWidget()
        col.addWidget(scroll_page(body))
        layout = QtWidgets.QHBoxLayout(body)
        rail = QtWidgets.QVBoxLayout()
        layout.addLayout(rail)
        rail.addWidget(label("写字机设备"))
        self.devices = QtWidgets.QListWidget()
        self.devices.setMinimumWidth(170)
        self.devices.setMaximumWidth(230)
        rail.addWidget(self.devices, 1)
        self.add_button = panel.button("添加写字机…", self.add)
        rail.addWidget(self.add_button)
        self.link = panel.button("连接", self.toggle_connection)
        rail.addWidget(self.link)

        form = QtWidgets.QVBoxLayout()
        layout.addLayout(form, 1)
        self.editor = QtWidgets.QWidget()
        options = QtWidgets.QVBoxLayout(self.editor)
        options.setContentsMargins(0, 0, 0, 0)
        form.addWidget(self.editor)
        axes = QtWidgets.QGroupBox("X/Y 比例与轴向")
        axes_form = QtWidgets.QFormLayout(axes)
        self.scales = [field(100, low=.01, high=1000) for _ in range(2)]
        for name, spin in zip(("X 比例", "Y 比例"), self.scales, strict=True):
            spin.setSuffix(" %")
            axes_form.addRow(name, spin)
        self.axes = [QtWidgets.QCheckBox(text) for text in ("X 轴镜像", "Y 轴镜像", "交换 XY 轴")]
        axes_form.addRow(pair_widget(self.axes))
        axes_form.addRow(label(AXIS_HELP))
        self.feed = QtWidgets.QSpinBox()
        self.feed.setRange(60, MAX_WRITE_FEED)
        self.feed.setSuffix(" mm/min")
        axes_form.addRow("书写速度", self.feed)
        options.addWidget(axes)

        limits = QtWidgets.QGroupBox("安全工作范围")
        ranges = QtWidgets.QFormLayout(limits)
        self.use_range = QtWidgets.QCheckBox("确认设备坐标及实际安全范围")
        ranges.addRow(self.use_range)
        self.bounds = [field() for _ in range(4)]
        ranges.addRow("最小角 X / Y", pair_widget(self.bounds[:2]))
        ranges.addRow("最大角 X / Y", pair_widget(self.bounds[2:]))
        self.record_buttons = [panel.button(text, lambda i=i: self.record_bound(i)) for i, text in enumerate(
            ("记当前笔位为最小角", "记当前笔位为最大角")
        )]
        ranges.addRow(pair_widget(self.record_buttons))
        options.addWidget(limits)
        self.save_button = panel.button("保存设备设置", self.save)
        self.save_button.setProperty("inkRole", "primary")
        options.addWidget(self.save_button)

        bench = QtWidgets.QGroupBox("点动与试画")
        actions = QtWidgets.QFormLayout(bench)
        self.position = label("")
        actions.addRow("当前笔位", self.position)
        self.nudge = PositionNudge("抬笔点动", unit="mm", minimum=.1, maximum=20)
        self.nudge.moved.connect(self.move)
        actions.addRow(self.nudge)
        actions.addRow(label("调试点动可超出软件范围。确认范围后，其内部可复核瞬时 X/Y 限位。"
                             "其余调试移动以 500 mm/min 为上限。"))
        self.trial = panel.button("试画 X/Y", self.draw)
        actions.addRow(self.trial, label(TRIAL_HELP))
        form.addWidget(bench)
        self.error = label("")
        form.addWidget(self.error)
        form.addStretch()
        close = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)
        self.stop = panel.button("停止", panel.stop)
        self.stop.setProperty("inkRole", "danger")
        close.addButton(self.stop, QtWidgets.QDialogButtonBox.ButtonRole.ActionRole)
        col.addWidget(close)
        self.devices.currentItemChanged.connect(self.select)
        panel.machine_state.connect(self.refresh)
        self.reload()

    def reload(self):
        with QtCore.QSignalBlocker(self.devices):
            self.devices.clear()
            for device in self.panel.profiles:
                item = QtWidgets.QListWidgetItem(f"{device.name}\n{device.port}", self.devices)
                item.setData(QtCore.Qt.ItemDataRole.UserRole, device.id)
                if device == self.panel.profile:
                    self.devices.setCurrentItem(item)
        self.load()

    def load(self):
        if profile := self.panel.profile:
            for spin, scale in zip(self.scales, (profile.axes.x_scale, profile.axes.y_scale), strict=True):
                spin.setValue(scale * 100)
            for check, on in zip(self.axes, (profile.axes.mirror_x, profile.axes.mirror_y, profile.axes.swap),
                                 strict=True):
                check.setChecked(on)
            area = profile.area
            for spin, value in zip(self.bounds, (area.left, area.top, area.right, area.bottom)
                                   if area else (0, 0, 100, 100), strict=True):
                spin.setValue(value)
            self.use_range.setChecked(area is not None)
            self.feed.setValue(profile.feed)
        self.refresh()

    def select(self, item, _previous):
        if item and self.panel.select_profile(item.data(QtCore.Qt.ItemDataRole.UserRole)):
            self.load()
        else:
            self.reload()

    def add(self):
        self.panel.refresh_ports()
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("添加写字机")
        form = QtWidgets.QFormLayout(dialog)
        name = QtWidgets.QLineEdit("炽写 N1")
        name.setMaxLength(40)
        ports = QtWidgets.QComboBox()
        for port in self.panel.port_records:
            serial = getattr(port, "serialNumber", lambda: "")()
            ports.addItem(port.portName(), (port.portName(), serial))
        form.addRow("设备名称", name)
        form.addRow("USB 串口", ports)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok |
                                             QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Ok).setEnabled(bool(ports.count()))
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        if not ports.count():
            form.addRow(label("连接炽写 N1 后再添加设备。"))
        form.addRow(buttons)
        if dialog.exec():
            try:
                profile = DeviceProfile.create(name.text(), *ports.currentData())
                self.panel.save_profile(profile)
                self.reload()
            except (OSError, ValueError) as error:
                self.error.setText(str(error))

    def refresh(self):
        connected = self.panel.device is not None
        idle = self.panel.busy is None
        profile = self.panel.profile is not None
        self.devices.setEnabled(idle and not connected)
        self.add_button.setEnabled(idle and not connected)
        self.editor.setEnabled(idle and profile)
        self.link.setEnabled(idle and profile and (not connected or self.panel.pen_raised))
        self.link.setText("断开" if connected else "连接")
        self.position.setText(self.panel.position_label.text())
        self.error.setText(self.panel.report.text())
        self.stop.setVisible(self.panel.is_moving)
        self.stop.setEnabled(self.panel.stop_button.isEnabled())
        self.nudge.setEnabled(connected and idle and profile)
        for button in (*self.record_buttons, self.trial):
            button.setEnabled(connected and idle and profile)

    def toggle_connection(self):
        self.panel.toggle_connection()

    def draft_axes(self):
        return DeviceAxes(*(spin.value() / 100 for spin in self.scales),
                          *(check.isChecked() for check in self.axes))

    def draft_area(self):
        if self.use_range.isChecked():
            return WorkArea(*(spin.value() for spin in self.bounds))
        return None

    def record_bound(self, index):
        def captured(status):
            for spin, value in zip(self.bounds[2*index:2*index + 2], status.position[:2], strict=True):
                spin.setValue(value)
        self.panel.capture_position(captured)

    def save(self):
        try:
            area = self.draft_area()
            old = self.panel.profile
            if area != old.area and self.panel.device is None:
                raise ValueError("请连接设备后确认实际工作范围。")
            offset = old.offset if self.panel.device is None else self.panel.offset
            profile = replace(old, axes=self.draft_axes(), area=area, offset=offset, feed=self.feed.value())
            self.panel.save_profile(profile)
            self.error.setText("已保存设备设置。")
        except (OSError, ValueError) as error:
            self.error.setText(str(error))

    def move(self, x, y):
        self.panel.submit("device-jog", self.draft_axes().map(x, y), self.panel.confirmed_area)

    def draw(self):
        try:
            area = self.draft_area()
            if self.panel.confirm("试画 X/Y", TRIAL_HELP + "\n确认测试纸、笔尖和设备已就位？"):
                self.panel.submit("axis-trial", self.draft_axes(), area, self.feed.value(),
                                  self.panel.confirmed_area)
        except ValueError as error:
            self.error.setText(str(error))

    def reject(self):
        if self.panel.is_moving:
            self.error.setText("请先完成或停止设备运动。")
            return
        if self.panel.busy == "position-read":
            return
        super().reject()
