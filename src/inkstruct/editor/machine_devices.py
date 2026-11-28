"""Device management and commissioning for the shared plotter connection."""

from dataclasses import replace


from PySide6 import QtCore, QtWidgets

from ..plotter.physical import WorkArea
from ..plotter.profiles import DeviceProfile
from ..settings_pages import label, scroll_page

class AddDeviceDialog(QtWidgets.QDialog):
    def __init__(self, panel, parent):
        super().__init__(parent)
        self.panel = panel
        self.setWindowTitle("添加写字机")
        form = QtWidgets.QFormLayout(self)
        self.ports = QtWidgets.QTreeWidget()
        self.ports.setHeaderHidden(True)
        self.ports.setAccessibleName("按识别结果选择串口")
        form.addRow(self.ports)
        refresh = QtWidgets.QPushButton("刷新")
        refresh.clicked.connect(self.refresh_ports)
        form.addRow(refresh)
        self.name = QtWidgets.QLineEdit()
        self.name.setMaxLength(40)
        form.addRow("设备名称", self.name)
        self.hint = label("")
        form.addRow(self.hint)
        self.buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok |
                                                QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        form.addRow(self.buttons)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.ports.currentItemChanged.connect(self.selection_changed)
        self.name.textChanged.connect(self.update_button)
        self.refresh_ports()

    def refresh_ports(self):
        from ..plotter.qt_connection import port_category
        role = QtCore.Qt.ItemDataRole.UserRole
        selected = self.ports.currentItem()
        previous = selected.data(0, role) if selected else None
        self.panel.refresh_ports()
        with QtCore.QSignalBlocker(self.ports):
            self.ports.clear()
            groups = {}
            for key in ("已识别的写字机", "待识别设备", "其他串口"):
                group = QtWidgets.QTreeWidgetItem(self.ports, [key])
                group.setFlags(QtCore.Qt.ItemFlag.ItemIsEnabled)
                groups[key] = group
            restored = None
            for port in self.panel.port_records:
                category = port_category(port)
                description = port.description().strip()
                text = " · ".join(filter(None, (port.portName(), description)))
                if category == "已识别的写字机":
                    text = "炽写 N1 · " + text
                item = QtWidgets.QTreeWidgetItem(groups[category], [text])
                key = (port.portName(), port.serialNumber(), category)
                item.setData(0, role, key)
                if category == "其他串口":
                    item.setFlags(QtCore.Qt.ItemFlag.NoItemFlags)
                elif key == previous:
                    restored = item
            self.ports.expandAll()
            known = groups["已识别的写字机"]
            if restored is None and previous is None and known.childCount() == 1:
                restored = known.child(0)
            self.ports.setCurrentItem(restored)
        self.selection_changed()

    def selection_changed(self, *_):
        item = self.ports.currentItem()
        self.selection = item.data(0, QtCore.Qt.ItemDataRole.UserRole) if item else None
        name = ""
        if self.selection and self.selection[2] != "其他串口":
            known = self.selection[2] == "已识别的写字机"
            name = "炽写 N1" if known else "写字机 " + self.selection[0]
            self.hint.setText("连接时核对设备。" if known else "请确认此串口连接的是写字机，连接时将核对协议。")
        else:
            self.hint.setText("请选择写字机或待识别设备。" if self.panel.port_records else "未发现串口。连接设备后点击「刷新」。")
        self.name.setPlaceholderText(name)
        self.update_button()

    def update_button(self):
        button = self.buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Ok)
        button.setEnabled(bool(self.selection and self.selection[2] != "其他串口"))
        button.setText("添加待识别设备" if self.selection and self.selection[2] == "待识别设备" else "添加")

    def profile(self):
        port, serial, _ = self.selection
        return DeviceProfile.create(self.name.text().strip() or self.name.placeholderText(), port, serial)


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
        self.rename_button = panel.button("重命名…", self.rename_device)
        self.remove_button = panel.button("移除…", self.remove_device)
        rail.addWidget(pair_widget((self.rename_button, self.remove_button)))
        self.link = panel.button("连接", self.toggle_connection)
        rail.addWidget(self.link)

        body = QtWidgets.QWidget()
        form = QtWidgets.QVBoxLayout(body)
        layout.addWidget(scroll_page(body), 1)
        self.editor = QtWidgets.QWidget()
        options = QtWidgets.QVBoxLayout(self.editor)
        options.setContentsMargins(0, 0, 0, 0)
        form.addWidget(self.editor)

        locating = QtWidgets.QGroupBox("停靠点")
        locate = QtWidgets.QVBoxLayout(locating)
        self.datum_status = label("")
        locate.addWidget(self.datum_status)
        self.position = label("")
        locate.addWidget(self.position)
        self.nudge = panel.motion_controls(self.move)
        locate.addWidget(self.nudge)
        self.raise_button = panel.button("抬笔", panel.raise_pen)
        locate.addWidget(self.raise_button)
        self.datum_register = panel.button("开始初始化…", lambda: panel.open_initialization(self))
        locate.addWidget(self.datum_register)
        self.datum_park = panel.button("回停靠点", panel.park_at_datum)
        self.datum_reset = panel.button("重新恢复位置", panel.invalidate_datum)
        locate.addWidget(pair_widget((self.datum_park, self.datum_reset)))
        options.addWidget(locating)
        self.pen_choice = QtWidgets.QComboBox()
        self.pen_choice.setAccessibleName("当前笔具")
        self.pen_choice.activated.connect(self.select_pen)
        self.calibrate = panel.button("校准笔高…", self.calibrate_pen)
        options.addWidget(pair_widget((self.pen_choice, self.calibrate)))

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
        self.range_context = None
        self.refresh()

    def select(self, item, _previous):
        if item and self.panel.select_profile(item.data(QtCore.Qt.ItemDataRole.UserRole)):
            self.load()
        else:
            self.reload()

    def add(self):
        dialog = AddDeviceDialog(self.panel, self)
        try:
            if dialog.exec():
                self.panel.save_profile(dialog.profile())
                self.reload()
        except (OSError, ValueError) as error:
            self.error.setText(str(error))
        finally:
            dialog.deleteLater()

    def rename_device(self):
        old = self.panel.profile
        if old is None:
            return
        name, ok = QtWidgets.QInputDialog.getText(self, "重命名写字机", "设备名称", text=old.name)
        if ok and name.strip() != old.name:
            try:
                self.panel.rename_device(old.id, name.strip())
                self.reload()
            except (OSError, ValueError) as error:
                self.error.setText(str(error))

    def remove_device(self):
        old = self.panel.profile
        if old is None or not self.panel.confirm("移除写字机", f"移除「{old.name}」({old.port}) 的本机档案？该设备的校正和纸面原点也会移除。"):
            return
        try:
            self.panel.remove_device(old.id)
            self.reload()
        except (OSError, ValueError) as error:
            self.error.setText(str(error))

    def refresh(self, *_):
        connected = self.panel.device is not None
        retained = bool(getattr(self.panel.worker, "retained_port", None))
        idle = self.panel.busy is None
        profile = self.panel.profile
        choices = ["设备默认"] + list(dict(profile.pen_heights)) if profile else []
        if choices != [self.pen_choice.itemText(i) for i in range(self.pen_choice.count())]:
            self.pen_choice.clear()
            self.pen_choice.addItems(choices)
        self.pen_choice.setCurrentIndex(choices.index(profile.active_pen) if profile and profile.active_pen else 0)
        self.pen_choice.setEnabled(bool(profile and idle))
        self.calibrate.setEnabled(bool(profile and connected and idle and self.panel.datum_located and self.panel.range_ready))
        trial = self.panel.dock_trial
        datum = profile.datum if profile and profile.datum and profile.datum.boot_mode else None
        located = self.panel.datum_located
        waiting = datum is not None and not located and not (trial and trial.mode)
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
            self.range_help.setText("请先恢复停靠点。")
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
        self.datum_status.setText("停靠点已定位。" if located else "请恢复停靠点。" if datum else "设备尚未初始化。")
        self.datum_register.setText("重新初始化…" if datum else "开始初始化…")
        self.datum_register.setEnabled(ready and not trial)
        self.datum_park.setVisible(located)
        self.datum_park.setEnabled(readable and located and (not profile.limit_area_enabled or
                                   (area is not None and area.contains(self.panel.frame)
                                    and area.contains(self.panel.device.position[:2]))))
        self.datum_reset.setVisible(located)
        self.devices.setEnabled(idle and not connected and not retained and not trial)
        self.add_button.setEnabled(idle and not connected and not retained and not trial)
        self.rename_button.setEnabled(bool(profile and idle and not trial))
        self.remove_button.setEnabled(bool(profile and self.add_button.isEnabled()))
        self.editor.setEnabled(idle and bool(profile) and not retained)
        self.link.setEnabled(idle and bool(profile) and (not connected or self.panel.pen_raised))
        self.link.setText(self.panel.link_button.text())
        self.position.setText(self.panel.position_label.text())
        self.error.setText(self.panel.report.text())
        self.stop.setVisible(self.panel.is_moving)
        self.stop.setEnabled(self.panel.stop_button.isEnabled())
        self.panel.refresh_motion_controls(self.nudge, ready)
        for button in self.record_buttons:
            button.setEnabled(ready and not waiting)
        self.save_button.setEnabled(idle and not retained and not trial)

    def select_pen(self, index):
        try:
            self.panel.save_profile(replace(self.panel.profile, active_pen=self.pen_choice.itemText(index) if index else ""))
        except (OSError, ValueError) as error:
            self.error.setText(str(error))
            self.refresh()

    def calibrate_pen(self):
        from .pen_calibration import PenCalibration
        dialog = PenCalibration(self.panel, self)
        try:
            dialog.exec()
        finally:
            dialog.deleteLater()

    def toggle_connection(self):
        self.panel.toggle_connection()

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
            enabled = self.use_range.isChecked()
            profile = replace(old, limit_area_enabled=enabled)
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
            self.panel.save_profile(profile, confirm_range=confirm)
            self.error.setText("已保存设备设置。")
        except (OSError, ValueError) as error:
            self.error.setText(str(error))

    def move(self, x, y):
        profile = self.panel.profile
        self.panel.submit("device-jog", profile.axes.map(x, y), self.panel.confirmed_area, profile.feed)

    def reject(self):
        if self.panel.is_moving:
            self.error.setText("请先完成或停止设备运动。")
            return
        if self.panel.busy in {"position-read", "position-datum"}:
            return
        super().reject()
