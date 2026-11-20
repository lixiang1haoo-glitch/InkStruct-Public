"""Device management and commissioning for the shared N1 connection."""

from dataclasses import replace

from PySide6 import QtCore, QtWidgets

from ..plotter.grbl import DEFAULT_WRITE_FEED, MAX_WRITE_FEED
from ..plotter.physical import WorkArea
from ..plotter.profiles import DeviceAxes, DeviceProfile
from ..settings_pages import label, scroll_page
from .position_nudge import PositionNudge

AXIS_HELP = "点左右按钮时笔尖却上下移动，请勾选「交换 XY 轴」。笔尖沿正确的轴走反了方向，请勾选对应轴的镜像。已有纸角时，更改轴向或比例须先保存并重新登记纸角。"
TRIAL_HELP = "请确保笔尖四周 100 mm 内可绘制。正常书写视角下，X 轴正向指正右方，Y 轴正向指正下方。"


class DeviceDialog(QtWidgets.QDialog):
    def __init__(self, panel, parent=None):
        super().__init__(parent or panel)
        from .machine_panel import field, pair_widget

        self.panel = panel
        self.range_context = None
        self.setWindowTitle("写字机设备管理")
        self.resize(850, 680)
        col = QtWidgets.QVBoxLayout(self)
        layout = QtWidgets.QHBoxLayout()
        col.addLayout(layout, 1)
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

        body = QtWidgets.QWidget()
        form = QtWidgets.QVBoxLayout(body)
        layout.addWidget(scroll_page(body), 1)
        self.editor = QtWidgets.QWidget()
        options = QtWidgets.QVBoxLayout(self.editor)
        options.setContentsMargins(0, 0, 0, 0)
        form.addWidget(self.editor)

        locating = QtWidgets.QGroupBox("机身定位")
        locate = QtWidgets.QVBoxLayout(locating)
        self.datum_status = label("")
        locate.addWidget(self.datum_status)
        locate.addWidget(label("纸张两边靠齐同一组挡边，保持登记时的朝向。抬笔点动，目视对准纸角。"))
        self.position = label("")
        locate.addWidget(self.position)
        self.nudge = PositionNudge("抬笔点动", unit="mm", minimum=.1, maximum=100)
        self.nudge.moved.connect(self.move)
        jog_row = QtWidgets.QHBoxLayout()
        jog_row.addWidget(self.nudge)
        speed_form = QtWidgets.QFormLayout()
        self.feed = QtWidgets.QSpinBox()
        self.feed.setAccessibleName("运动速度")
        self.feed.setRange(60, MAX_WRITE_FEED)
        self.feed.setValue(DEFAULT_WRITE_FEED)
        self.feed.setSuffix(" mm/min")
        self.feed.setToolTip("点动和试画立即使用此 X/Y 速度。保存设备设置后用于排版的抬笔移动和落笔书写。")
        speed_form.addRow("运动速度", self.feed)
        speed_form.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        speed_form.setRowWrapPolicy(QtWidgets.QFormLayout.RowWrapPolicy.WrapAllRows)
        speed_form.setFormAlignment(QtCore.Qt.AlignmentFlag.AlignVCenter)
        jog_row.addLayout(speed_form)
        jog_row.addStretch()
        locate.addLayout(jog_row)
        self.raise_button = panel.button("抬笔", panel.raise_pen)
        locate.addWidget(self.raise_button)
        self.datum_register = panel.button("登记纸角…", self.register_datum)
        self.datum_recover = panel.button("笔尖已对准纸角", self.recover_datum)
        locate.addWidget(pair_widget((self.datum_recover, self.datum_register)))
        self.datum_alternate = panel.button("登记备用点…", self.register_alternate)
        self.datum_use_alternate = panel.button("笔尖已对准备用点", lambda: self.recover_datum(alternate=True))
        locate.addWidget(pair_widget((self.datum_use_alternate, self.datum_alternate)))
        self.datum_park = panel.button("抬笔停到纸角", panel.park_at_datum)
        self.datum_reset = panel.button("笔位有偏差，重新定位", panel.invalidate_datum)
        locate.addWidget(pair_widget((self.datum_park, self.datum_reset)))
        options.addWidget(locating)

        axes = QtWidgets.QGroupBox("X/Y 比例与轴向")
        axes_form = QtWidgets.QFormLayout(axes)
        self.scales = [field(100, low=.01, high=1000) for _ in range(2)]
        for name, spin in zip(("X 比例", "Y 比例"), self.scales, strict=True):
            spin.setSuffix(" %")
            axes_form.addRow(name, spin)
        self.axes = [QtWidgets.QCheckBox(text) for text in ("X 轴镜像", "Y 轴镜像", "交换 XY 轴")]
        axes_form.addRow(pair_widget(self.axes))
        axes_form.addRow(label(AXIS_HELP))
        options.addWidget(axes)

        limits = QtWidgets.QGroupBox("安全工作范围")
        ranges = QtWidgets.QFormLayout(limits)
        self.use_range = QtWidgets.QCheckBox("启用安全工作范围")
        ranges.addRow(self.use_range)
        self.range_help = label("")
        ranges.addRow(self.range_help)
        self.range_form = ranges
        self.bounds = [field() for _ in range(4)]
        ranges.addRow("最小角 X / Y", pair_widget(self.bounds[:2]))
        ranges.addRow("最大角 X / Y", pair_widget(self.bounds[2:]))
        self.record_buttons = [panel.button(text, lambda i=i: self.record_bound(i)) for i, text in enumerate(
            ("记当前笔位为最小角", "记当前笔位为最大角")
        )]
        ranges.addRow(pair_widget(self.record_buttons))
        self.range_confirm = panel.button("确认本次工作范围", lambda: self.save(confirm_range=True))
        ranges.addRow(self.range_confirm)
        options.addWidget(limits)
        self.save_button = panel.button("保存设备设置", self.save)
        self.save_button.setProperty("inkRole", "primary")
        options.addWidget(self.save_button)

        bench = QtWidgets.QGroupBox("试画")
        actions = QtWidgets.QFormLayout(bench)
        self.trial = panel.button("试画 X/Y", self.draw)
        actions.addRow(self.trial, label(TRIAL_HELP))
        form.addWidget(bench)
        form.addStretch()
        self.error = label("")
        col.addWidget(self.error)
        close = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)
        self.stop = panel.button("停止", panel.stop)
        self.stop.setProperty("inkRole", "danger")
        close.addButton(self.stop, QtWidgets.QDialogButtonBox.ButtonRole.ActionRole)
        col.addWidget(close)
        self.devices.currentItemChanged.connect(self.select)
        self.use_range.toggled.connect(self.refresh)
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
            self.feed.setValue(profile.feed)
        self.range_context = None
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

    def refresh(self, *_):
        connected = self.panel.device is not None
        idle = self.panel.busy is None
        profile = self.panel.profile
        datum = profile.datum if profile else None
        located = self.panel.frame is not None
        waiting = datum is not None and not located
        area = self.panel.confirmed_area
        context = (self.panel.connection_id, profile.id if profile else None,
                   profile.limit_area_enabled if profile else False, datum.id if datum else None,
                   self.panel.frame, area)
        if self.range_context != context:
            self.range_context = context
            shown = area or (profile.area if profile and not datum else None)
            if shown is None and datum and datum.area and located:
                shown = datum.to_work_area(datum.area, self.panel.frame)
            if shown:
                values = (shown.left, shown.top, shown.right, shown.bottom)
            elif datum and connected:
                values = self.panel.device.position[:2] * 2
            else:
                values = (0, 0, 100, 100)
            for spin, value in zip(self.bounds, values, strict=True):
                spin.setValue(value)
            self.original_bounds = tuple(spin.value() for spin in self.bounds)
            with QtCore.QSignalBlocker(self.use_range):
                self.use_range.setChecked(bool(profile and profile.limit_area_enabled))
        enabled = self.use_range.isChecked()
        ready = connected and idle and bool(profile)
        if not enabled:
            self.range_help.setText("关闭后按作业路径移动。范围设置保存后生效。")
        elif waiting:
            self.range_help.setText("请先对准已登记的纸角，找回本次连接的工作坐标。")
        elif area is None:
            self.range_help.setText("核对本次连接的两个角点后确认范围。坐标单位为 mm。")
        else:
            self.range_help.setText("本次连接的范围已确认，修改两角后请保存设备设置。坐标单位为 mm。")
        for row in (2, 3, 4):
            self.range_form.setRowVisible(row, enabled and not waiting)
        self.range_confirm.setVisible(enabled and not waiting and area is None and
                                      bool(profile and profile.limit_area_enabled))
        self.range_confirm.setEnabled(ready)
        readable = ready and self.panel.pen_raised
        self.raise_button.setVisible(ready and not self.panel.pen_raised)
        self.datum_status.setText((("机身已定位" if located else "机身待定位") + f" · {datum.label}")
                                  if datum else "尚未登记纸角")
        self.datum_register.setText("更换纸角…" if datum else "登记纸角…")
        self.datum_register.setEnabled(readable)
        self.datum_recover.setVisible(waiting)
        self.datum_recover.setEnabled(readable)
        self.datum_alternate.setVisible(located)
        self.datum_alternate.setEnabled(readable)
        self.datum_use_alternate.setVisible(waiting and datum.checkpoint is not None)
        self.datum_use_alternate.setEnabled(readable)
        self.datum_park.setVisible(located)
        self.datum_park.setEnabled(ready and located and (not profile.limit_area_enabled or
                                   (area is not None and area.contains(self.panel.frame)
                                    and area.contains(self.panel.device.position[:2]))))
        self.datum_reset.setVisible(located)
        self.devices.setEnabled(idle and not connected)
        self.add_button.setEnabled(idle and not connected)
        self.editor.setEnabled(idle and bool(profile))
        self.link.setEnabled(idle and bool(profile) and (not connected or self.panel.pen_raised))
        self.link.setText("断开" if connected else "连接")
        self.position.setText(self.panel.position_label.text())
        self.error.setText(self.panel.report.text())
        self.stop.setVisible(self.panel.is_moving)
        self.stop.setEnabled(self.panel.stop_button.isEnabled())
        self.nudge.setEnabled(ready)
        for button in self.record_buttons:
            button.setEnabled(ready and not waiting)
        self.trial.setEnabled(ready and self.panel.range_ready and (not datum or located))

    def register_datum(self):
        profile = self.panel.profile
        if profile is None:
            return
        name, accepted = QtWidgets.QInputDialog.getText(
            self, "登记纸角", "限位、纸型、朝向和纸角", text=profile.datum.label if profile.datum else "A4 纵向 · 左上角")
        if not accepted:
            return
        name = name.strip()
        if not name:
            self.error.setText("请填写纸张限位和角的位置，以便下次找正。")
            return
        replace_notice = "更换后请重新核对纸面摆放和已启用的安全范围。" if profile.datum else ""
        self.read_reference("登记纸角", f"确认抬起的笔尖正对「{name}」？{replace_notice}",
                            lambda status: self.panel.register_datum(name, status))

    def recover_datum(self, *, alternate=False):
        datum = self.panel.profile.datum if self.panel.profile else None
        if datum is None:
            return
        point = "登记过的备用点" if alternate else "登记过的纸角"
        self.read_reference("找回机身基准", f"请确认两边靠齐「{datum.label}」的挡边，抬起的笔尖已对准{point}。",
                            lambda status: self.panel.recover_datum(status, alternate=alternate),
                            confirm=not self.panel.profile.serial)

    def register_alternate(self):
        self.read_reference("登记备用点", "请先将笔尖对准装纸后仍可见的固定标记。以后可用此点恢复机身定位。"
                            "确认将当前笔位登记为备用点？",
                            self.panel.register_alternate)

    def read_reference(self, title, instruction, callback, *, confirm=True):
        panel = self.panel
        profile, connection = panel.profile, panel.connection_id
        if not profile or not connection or not panel.pen_raised or panel.busy:
            return
        if self.draft_axes() != profile.axes:
            self.error.setText("请先保存修改后的轴向和比例，再记录基准。")
            return
        if not profile.serial:
            instruction = f"设备没有 USB 序列号。请核对实际连接的是「{profile.name}」（{profile.port}）。\n" + instruction
        if confirm and not panel.confirm(title, instruction):
            return
        if panel.profile == profile and panel.connection_id == connection:
            panel.capture_position(callback, datum=True)

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

    def save(self, *, confirm_range=False):
        try:
            old = self.panel.profile
            axes = self.draft_axes()
            enabled = self.use_range.isChecked()
            profile = replace(old, feed=self.feed.value(), limit_area_enabled=enabled)
            new_calibration = old.datum is not None and axes != old.axes
            if new_calibration:
                profile = replace(profile, axes=axes, datum=None, area=None, offset=None)
                self.panel.save_profile(profile)
                self.error.setText("轴向或比例已变更。请重新登记用于找正的纸角。")
                return
            connected_frame = self.panel.connection_id is not None and (not old.datum or self.panel.datum_located)
            edited = tuple(spin.value() for spin in self.bounds) != self.original_bounds
            entering = enabled and not old.limit_area_enabled
            active = self.panel.confirmed_area
            if confirm_range and not (enabled and connected_frame):
                raise ValueError("请连接设备并核对当前坐标后确认范围。")
            confirm = enabled and connected_frame and (confirm_range or entering or edited or active is not None)
            if confirm:
                bounds = active if active is not None and not edited else self.draft_area()
                profile = replace(profile, area=bounds, offset=self.panel.offset)
            elif enabled and not old.datum and (entering or edited):
                profile = replace(profile, area=self.draft_area())
            self.panel.save_profile(replace(profile, axes=axes), confirm_range=confirm)
            self.error.setText("已保存设备设置。")
        except (OSError, ValueError) as error:
            self.error.setText(str(error))

    def move(self, x, y):
        axes = self.draft_axes()
        if self.panel.profile.datum and self.panel.profile.axes != axes:
            self.error.setText("请先保存修改后的轴向和比例，再按新方向点动。")
            return
        self.panel.submit("device-jog", axes.map(x, y), self.panel.confirmed_area, self.feed.value())

    def draw(self):
        try:
            if self.panel.profile.datum and self.panel.profile.axes != self.draft_axes():
                raise ValueError("请先保存修改后的轴向和比例，再按新设置试画。")
            area = self.draft_area() if self.panel.profile.limit_area_enabled else None
            if self.panel.confirm("试画 X/Y", TRIAL_HELP + "\n确认测试纸、笔尖和设备已就位？"):
                self.panel.submit("axis-trial", self.draft_axes(), area, self.feed.value(),
                                  self.panel.confirmed_area)
        except ValueError as error:
            self.error.setText(str(error))

    def reject(self):
        if self.panel.is_moving:
            self.error.setText("请先完成或停止设备运动。")
            return
        if self.panel.busy in {"position-read", "position-datum"}:
            return
        super().reject()
