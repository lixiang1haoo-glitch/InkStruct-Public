"""Guided commissioning of one connected plotter."""
from PySide6 import QtWidgets

from ..plotter.physical import WorkArea
from ..plotter.profiles import DeviceAxes
from ..settings_pages import label, scroll_page
from .machine_panel import field, pair_widget


class InitializationDialog(QtWidgets.QDialog):
    def __init__(self, panel, parent):
        super().__init__(parent)
        self.panel = panel
        self.setWindowTitle(f"初始化写字机 · {panel.profile.name}")
        self.resize(570, 590)
        layout = QtWidgets.QVBoxLayout(self)
        self.heading = label("")
        layout.addWidget(self.heading)
        body = QtWidgets.QWidget()
        form = QtWidgets.QVBoxLayout(body)
        layout.addWidget(scroll_page(body), 1)
        self.instructions = label("")
        form.addWidget(self.instructions)
        self.link = panel.button("连接", panel.toggle_connection)
        form.addWidget(self.link)
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
        self.feedback = label("")
        layout.addWidget(self.feedback)
        self.stop = panel.button("停止", panel.stop)
        self.stop.setProperty("inkRole", "danger")
        self.cancel = panel.button("取消", self.reject)
        self.advance = panel.button("", self.next_step)
        self.advance.setProperty("inkRole", "primary")
        layout.addWidget(pair_widget((self.stop, self.cancel, self.advance)))
        panel.machine_state.connect(self.refresh)
        self.refresh()
        self.feedback.clear()

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
        try:
            area = self.area()
            if self.panel.confirm("试画 X/Y", "确认已固定测试纸，且笔尖四周 100 mm 内均可绘制？"):
                self.panel.submit("axis-trial", self.draft_axes(), area, self.panel.profile.feed,
                                  self.panel.confirmed_area)
        except ValueError as error:
            self.feedback.setText(str(error))

    def next_step(self):
        trial = self.panel.dock_trial
        if trial is None:
            callback = self.panel.begin_dock_trial
        elif not trial.mode:
            callback = self.panel.record_restart
        else:
            callback = self.finish_initialization
        self.panel.capture_position(callback, datum=True)

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
        if trial is None:
            title = "第 1 步，共 3 步 · 选择停靠点"
            instructions = "抬笔后点动到方便取纸的位置，建议选机器左上方并留出限位余量。写完后笔尖会回到这里。"
            action = "笔尖已在停靠点，下一步"
            enabled = readable
        elif rebooting:
            n = len(trial.readings) + 1
            title = "第 2 步，共 3 步 · 核对重启读数"
            instructions = (f"第 {n} / 3 轮：保持笔尖不动，断开连接，用电源开关重启设备"
                            "（无开关时断电再通电），再点击连接。")
            action = f"已重启，记录第 {n} 轮读数"
            enabled = readable and trial.connection != panel.connection_id
        else:
            title = "第 3 步，共 3 步 · 试画并校正 X/Y"
            instructions = ("固定测试纸，点动至笔尖四周 100 mm 内均可绘制的位置。试画的两轴各长 50 mm，"
                            "X 应向右，Y 应向下。按实测结果调整方向和比例，可再次试画核对。")
            action = "保存并完成"
            enabled = readable and trial.trial_axes is not None
        self.heading.setText(title)
        self.instructions.setText(instructions)
        self.advance.setText(action)
        self.advance.setEnabled(bool(enabled))
        self.link.setVisible(rebooting or not connected)
        self.link.setText(panel.link_button.text())
        self.link.setEnabled(idle and (not connected or panel.pen_raised))
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
        self.feedback.setText(panel.report.text())
        self.cancel.setEnabled(idle)
        self.stop.setVisible(panel.is_moving)
        self.stop.setEnabled(panel.stop_button.isEnabled())

    def reject(self):
        if self.panel.busy is not None:
            return
        if self.panel.dock_trial is not None:
            self.panel.cancel_dock_trial()
        super().reject()
