"""Guided contact and lift check for a named pen on the connected N1."""

from dataclasses import replace
from PySide6 import QtWidgets

from ..plotter.grbl import PEN_DOWN
from ..plotter.physical import MachinePage, MachineStroke, PaperRegistration
from ..settings_pages import label


class PenCalibration(QtWidgets.QDialog):
    def __init__(self, panel, parent):
        super().__init__(parent)
        self.panel = panel
        self.setWindowTitle("校准笔高")
        self.profile_id = panel.profile.id
        self.connection_id = panel.connection_id
        self.pending = None
        self.tested = None
        form = QtWidgets.QVBoxLayout(self)
        form.addWidget(label("在笔尖下放一张试纸，右侧留出 2 mm 供试写。"))
        self.name = QtWidgets.QComboBox()
        self.name.setEditable(True)
        self.name.addItems(list(dict(panel.profile.pen_heights)) or ["当前笔"])
        self.name.setCurrentText(panel.profile.active_pen or "当前笔")
        form.addWidget(label("笔具名称（可输入新名称）"))
        form.addWidget(self.name)
        self.height = QtWidgets.QDoubleSpinBox()
        self.height.setRange(PEN_DOWN, -.1)
        self.height.setDecimals(2)
        self.height.setSingleStep(.1)
        self.height.setSuffix(" mm")
        self.height.setValue(-.1)
        self.name.currentTextChanged.connect(self.select_pen)
        form.addWidget(label("① 从接近 0 的高度开始。每次调低一点，点「试触纸」，直到笔尖刚好接触纸面。"))
        form.addWidget(self.height)
        self.touch = panel.button("试触纸", self.contact)
        form.addWidget(self.touch)
        self.line = panel.button("② 已刚好触纸，向右试写 2 mm 并抬笔", self.draw)
        form.addWidget(self.line)
        self.lift = panel.button("抬笔", panel.raise_pen)
        form.addWidget(self.lift)
        self.save = panel.button("③ 线条清楚、笔尖已离纸，保存笔高", self.finish)
        form.addWidget(self.save)
        self.info = label("")
        form.addWidget(self.info)
        self.stop = panel.button("停止", panel.stop)
        form.addWidget(self.stop)
        self.height.valueChanged.connect(self.reset_test)
        panel.machine_state.connect(self.refresh)
        panel.worker.succeeded.connect(self.finished_move)
        self.select_pen(self.name.currentText())

    def select_pen(self, name):
        self.height.setValue(dict(self.panel.profile.pen_heights).get(name, -.1))
        self.reset_test()

    def reset_test(self, *_):
        self.tested = None
        self.contact_height = None
        self.refresh()

    def contact(self):
        if self.panel.submit("calibrate-height", self.height.value(), self.panel.confirmed_area):
            self.pending = "calibrate-height"

    def draw(self):
        panel = self.panel
        start = panel.device.position[:2]
        dx, dy = panel.profile.axes.map(2., 0.)
        end = (start[0] + dx, start[1] + dy)
        page = MachinePage(0, (MachineStroke("试写短线", (start, end), .25),), PaperRegistration(start))
        if panel.submit("calibrate-line", page, panel.confirmed_area, panel.profile.feed, self.height.value()):
            self.pending = "calibrate-line"

    def finished_move(self, kind, _status):
        if kind == self.pending:
            if kind == "calibrate-height":
                self.contact_height = self.height.value()
            else:
                self.tested = self.height.value()
            self.pending = None
            self.refresh()

    def refresh(self):
        panel = self.panel
        connected = panel.device is not None and panel.connection_id == self.connection_id
        idle = connected and panel.busy is None and panel.range_ready
        self.name.setEnabled(idle)
        self.height.setEnabled(idle)
        self.touch.setEnabled(idle)
        self.line.setEnabled(idle and self.contact_height == self.height.value())
        self.lift.setEnabled(connected and panel.busy is None and not panel.pen_raised)
        self.save.setEnabled(idle and bool(self.name.currentText().strip()) and panel.pen_raised
                             and self.tested == self.height.value())
        self.info.setText(panel.report.text() if not connected or not panel.range_ready else
                          "观察纸面短线和笔尖间隙，再保存。" if self.tested is not None else
                          "触纸后观察笔尖，必要时抬笔并微调。")
        self.stop.setVisible(panel.busy is not None)

    def finish(self):
        if not self.save.isEnabled():
            return
        name = self.name.currentText().strip()
        heights = dict(self.panel.profile.pen_heights)
        heights[name] = self.tested
        try:
            self.panel.save_profile(replace(self.panel.profile, active_pen=name, pen_heights=tuple(heights.items())))
        except (ValueError, OSError) as error:
            self.info.setText(str(error))
            return
        self.accept()

    def reject(self):
        if self.panel.busy:
            return
        if self.panel.device and not self.panel.pen_raised:
            self.panel.raise_pen()
            self.info.setText("正在抬笔，完成后可关闭。")
            return
        super().reject()
