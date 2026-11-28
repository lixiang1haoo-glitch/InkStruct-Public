"""Guided commissioning of one connected plotter."""
from PySide6 import QtWidgets

from ..plotter.physical import WorkArea
from ..plotter.profiles import DeviceAxes
from ..settings_pages import label, scroll_page
from .machine_panel import field, pair_widget


class InitializationDialog(QtWidgets.QDialog):
    def __init__(self, panel, parent, *, detect=False):
        super().__init__(parent)
        self.panel = panel
        self.read_after_connect = False
        self.disconnect_pending = False
        self.fault = ""
        self.setWindowTitle(f"初始化写字机 · {panel.profile.name}")
        self.resize(570, 590)
        layout = QtWidgets.QVBoxLayout(self)
        self.heading = label("")

        body = QtWidgets.QWidget()
        form = QtWidgets.QVBoxLayout(body)
        layout.addWidget(scroll_page(body), 1)
        self.choice = QtWidgets.QGroupBox("写字机重启后的坐标")
        choices = QtWidgets.QVBoxLayout(self.choice)
        self.modes = {}
        initial = "" if detect or not panel.profile.datum else panel.profile.datum.boot_mode
        for mode, title in (("zero", "重启后坐标归零"), ("retained", "重启后保留坐标"), ("", "不确定，帮我检测")):
            option = QtWidgets.QRadioButton(title)
            choices.addWidget(option)
            self.modes[mode] = option
            option.setChecked(mode == initial)
        form.addWidget(self.choice)
        self.position = label("")
        form.addWidget(self.position)
        self.nudge = panel.motion_controls(self.move)
        form.addWidget(self.nudge)
        self.raise_pen = panel.button("抬笔", panel.raise_pen)
        form.addWidget(self.raise_pen)

        self.calibration = QtWidgets.QWidget()
        axes = QtWidgets.QFormLayout(self.calibration)
        config = panel.profile.axes
        self.scales = []
        for name, value in (("X 比例", config.x_scale), ("Y 比例", config.y_scale)):
            spin = field(value * 100, low=.01, high=1000)
            spin.setSuffix(" %")
            self.scales.append(spin)
            axes.addRow(name, spin)
        self.axes = []
        for name, value in (("X 轴镜像", config.mirror_x), ("Y 轴镜像", config.mirror_y),
                            ("交换 XY 轴", config.swap)):
            check = QtWidgets.QCheckBox(name)
            check.setChecked(value)
            self.axes.append(check)
        axes.addRow(pair_widget(self.axes))
        axes.addRow(label("左右与上下互换时选「交换 XY 轴」，方向相反时选对应轴的镜像。"))
        self.bounds = []
        if panel.profile.limit_area_enabled:
            area = panel.confirmed_area or panel.profile.area
            axes.addRow(label("请按本次连接的读数核对试画和停靠使用的安全工作范围（mm）。"))
            for value in ((area.left, area.top, area.right, area.bottom) if area else (0, 0, 0, 0)):
                self.bounds.append(field(value))
            axes.addRow("最小角 X / Y", pair_widget(self.bounds[:2]))
            axes.addRow("最大角 X / Y", pair_widget(self.bounds[2:]))
        self.trial_button = panel.button("试画 X/Y", self.draw)
        axes.addRow(self.trial_button)
        form.addWidget(self.calibration)
        form.addStretch()
        prompt = QtWidgets.QFrame()
        prompt.setObjectName("commissioningPrompt")
        prompt.setStyleSheet("#commissioningPrompt { background: #183650; border-radius: 6px; }"
                             "#commissioningPrompt QLabel { color: white; background: transparent; }")
        prompt_layout = QtWidgets.QVBoxLayout(prompt)
        prompt_layout.setContentsMargins(16, 12, 16, 12)
        prompt_layout.setSpacing(6)
        self.instructions = label("")
        font = self.heading.font()
        font.setBold(True)
        font.setPointSizeF(max(14, font.pointSizeF() + 2))
        self.heading.setFont(font)
        instruction_font = self.instructions.font()
        instruction_font.setPointSizeF(max(12, instruction_font.pointSizeF() + 1))
        self.instructions.setFont(instruction_font)
        prompt_layout.addWidget(self.heading)
        prompt_layout.addWidget(self.instructions)
        layout.addWidget(prompt)
        self.stop = panel.button("停止", panel.stop)
        self.stop.setProperty("inkRole", "danger")
        self.cancel = panel.button("取消", self.reject)
        self.advance = panel.button("", self.next_step)
        self.advance.setProperty("inkRole", "primary")
        layout.addWidget(pair_widget((self.stop, self.cancel, self.advance)))
        panel.machine_state.connect(self.refresh)
        panel.connection_changed.connect(self.connection_changed)
        panel.machine_error.connect(self.show_error)
        for option in self.modes.values():
            option.toggled.connect(self.refresh)
        self.refresh()

    def draft_axes(self):
        return DeviceAxes(*(spin.value() / 100 for spin in self.scales),
                          *(check.isChecked() for check in self.axes))

    def area(self):
        if self.bounds:
            return WorkArea(*(spin.value() for spin in self.bounds))
        return None

    def move(self, x, y):
        self.panel.submit("device-jog", self.draft_axes().map(x, y),
                          self.panel.confirmed_area, self.panel.profile.feed)

    def draw(self):
        self.fault = ""
        self.refresh()
        try:
            area = self.area()
            if self.panel.confirm("试画 X/Y", "确认已固定测试纸，且笔尖四周 100 mm 内均可绘制？"):
                self.panel.submit("axis-trial", self.draft_axes(), area, self.panel.profile.feed,
                                  self.panel.confirmed_area)
        except ValueError as error:
            self.show_error(str(error))

    def selected_mode(self):
        return next((mode for mode, button in self.modes.items() if button.isChecked()), "")

    def show_error(self, text):
        self.read_after_connect = False
        self.fault = text
        self.refresh()

    def connection_changed(self, connected):
        if not connected:
            self.disconnect_pending = False
            self.refresh()
        elif self.read_after_connect and self.isVisible():
            self.read_after_connect = False
            self.read_position()

    def next_step(self):
        panel = self.panel
        self.fault = ""
        trial = panel.dock_trial
        if self.disconnect_pending:
            panel.submit("disconnect")
        elif panel.device is None:
            self.read_after_connect = bool(trial and not trial.mode)
            panel.toggle_connection(confirmed_profile=panel.profile.id)
        else:
            self.read_position()
        self.refresh()

    def read_position(self):
        panel = self.panel
        trial = panel.dock_trial
        if trial and trial.mode:
            callback = self.finish_initialization
        else:
            def callback(status):
                if trial:
                    panel.record_restart(status)
                else:
                    panel.begin_dock_trial(status, self.selected_mode())
                if not panel.dock_trial.mode:
                    self.disconnect_pending = True
                    panel.submit("disconnect")
        if not panel.capture_position(callback, datum=True, commissioning=True):
            self.show_error("未能开始读取，请检查连接后重试。")

    def finish_initialization(self, status):
        self.panel._require_datum_reading(status)
        self.panel.initialize_axes(self.draft_axes(), self.area())
        self.accept()

    def refresh(self):
        panel = self.panel
        trial = panel.dock_trial
        rebooting = trial is not None and not trial.mode
        calibrating = bool(trial and trial.mode)
        connected = panel.device is not None
        idle = panel.busy is None
        readable = connected and idle and panel.pen_raised
        self.choice.setVisible(trial is None)
        self.choice.setEnabled(idle)
        n = len(trial.readings) + 1 if rebooting else 0
        enabled = readable
        if calibrating:
            title = "检测完成 · 校准 X/Y" if trial.readings else "停靠点已确认 · 校准 X/Y"
            instructions = ("固定测试纸，点动至笔尖四周 100 mm 内均可绘制的位置。试画的两轴各长 50 mm，"
                            "X 应向右，Y 应向下。核对方向和比例后保存。")
            action = "保存并完成"
            enabled = readable and trial.trial_axes is not None
        elif rebooting:
            title = f"重启检测 · 第 {n} / 3 轮"
            if self.disconnect_pending:
                instructions = "停靠点读数已记录。请先断开连接，再按提示重启设备。"
                action = "断开连接"
                enabled = idle
            elif connected:
                instructions = "保持笔尖不动，重新读取本轮坐标。"
                action = "重新读取并继续校准" if n == 3 else "重新读取并断开"
            else:
                instructions = "保持笔尖不动。请关闭写字机电源，再重新通电。\n通电后点击下方连接按钮。"
                action = "连接、读取并继续校准" if n == 3 else "连接、读取并断开"
                enabled = idle
        else:
            title = "选择物理停靠点"
            instructions = "抬笔点动到方便取纸的位置，建议选机器左上方并留出限位余量。停稳后选择重启行为。"
            action = "确认停靠点，继续校准" if self.selected_mode() else "记录停靠点并断开连接"
            if not connected:
                instructions = "请重新连接设备，核对笔尖是否仍在停靠点。"
                action = "连接设备"
                enabled = idle
        if not connected and not panel.profile.serial:
            instructions += f" 请核对串口仍连接「{panel.profile.name}」。"
        if panel.busy in ("connect", "disconnect", "position-datum"):
            title = {"connect": "正在连接设备", "disconnect": "正在断开连接",
                     "position-datum": "正在读取稳定坐标"}[panel.busy]
            if rebooting and panel.busy == "disconnect":
                title += f" · 已记录 {len(trial.readings)} / 3 轮"
            elif rebooting:
                title += f" · 第 {n} / 3 轮"
            instructions = "请保持笔尖不动，等待读取结束。" if panel.busy != "disconnect" else "请等断开完成后再关闭电源。"
            action = title
        elif self.fault:
            title = ("读取失败 · " if rebooting or trial is None else "校准未完成 · ") + title
            instructions = self.fault
            if not connected and rebooting and not self.disconnect_pending:
                instructions += " 确认设备已通电，再重试本轮。"
                if not panel.profile.serial:
                    instructions += f" 请核对串口仍连接「{panel.profile.name}」。"
        self.heading.setText(title)
        self.instructions.setText(instructions)
        self.advance.setText(action)
        self.advance.setEnabled(bool(enabled and idle))
        if connected:
            pen = "已抬笔" if panel.pen_raised else "已落笔"
            if calibrating and self.bounds:
                x, y = panel.device.position[:2]
                pen += f" · 设备当前读数 X {x:.3f} · Y {y:.3f} mm"
            self.position.setText(pen)
        else:
            self.position.setText(panel.position_label.text())
        self.nudge.setVisible(not rebooting)
        panel.refresh_motion_controls(self.nudge, connected and idle and not rebooting)
        self.raise_pen.setVisible(connected and not panel.pen_raised)
        self.raise_pen.setEnabled(idle)
        self.calibration.setVisible(calibrating)
        self.calibration.setEnabled(readable)
        self.cancel.setEnabled(idle)
        self.stop.setVisible(panel.is_moving)
        self.stop.setEnabled(panel.stop_button.isEnabled())

    def reject(self):
        if self.panel.busy is not None:
            return
        if self.panel.dock_trial is not None:
            self.panel.cancel_dock_trial()
        super().reject()
