"""Display the throughput of verified per-character generation results."""

from collections import deque
from math import ceil
from time import monotonic

from PySide6 import QtCore, QtGui, QtWidgets


def _remaining_time(seconds):
    seconds = ceil(seconds)
    if seconds < 60:
        return f"{seconds} 秒"
    if seconds < 3600:
        return f"{seconds // 60} 分 {seconds % 60} 秒"
    return f"{seconds // 3600} 小时 {(seconds % 3600) // 60} 分"


class _SpeedGraph(QtWidgets.QWidget):
    history_bins = 240
    label_gap = 3

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(86)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed)
        self.speed_label = QtWidgets.QLabel(self)
        self.speed_label.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAccessibleName("生成进度与速度图")
        description = "浅绿色表示已处理比例，深绿色表示各处理阶段的速度，横线表示当前近期速度。"
        self.setToolTip(description)
        self.setAccessibleDescription(description)
        self.reset()

    def reset(self):
        self.history = []
        self.scale = 1
        self.set_progress(0, None)

    def set_progress(self, fraction, speed, *, measuring=True):
        if speed is not None:
            while speed > self.scale:
                self.scale *= 2
            if not self.history or fraction > self.history[-1][0]:
                point = (fraction, speed)
                if self.history and int(fraction * self.history_bins) == int(self.history[-1][0] * self.history_bins):
                    self.history[-1] = point
                else:
                    self.history.append(point)
        self.fraction = fraction
        self.speed = speed
        if speed is None:
            self.speed_label.setText("测速中" if measuring else "速度：—")
        else:
            self.speed_label.setText(f"速度：{speed:.1f} 字/秒")
        self.speed_label.setEnabled(speed is not None)
        self.speed_label.adjustSize()
        self._place_label()
        self.update()

    def _area(self):
        return QtCore.QRectF(self.rect()).adjusted(1, 1, -1, -1)

    def _speed_y(self, speed):
        area = self._area()
        top = area.top() + self.speed_label.height() + 2 * self.label_gap
        bottom = area.bottom() - 1
        return bottom - (bottom - top) * speed / self.scale

    def _place_label(self):
        area = self._area()
        label = self.speed_label
        y = (area.center().y() - label.height() / 2 if self.speed is None
             else self._speed_y(self.speed) - label.height() - self.label_gap)
        label.move(max(1, int(area.right() - label.width() - 5)), round(y))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._place_label()

    def sizeHint(self):
        return QtCore.QSize(320, 86)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        area = self._area()
        painter.fillRect(area, QtGui.QColor("#f6faf6"))
        fill = QtCore.QRectF(area)
        fill.setWidth(area.width() * self.fraction)
        painter.fillRect(fill, QtGui.QColor("#d7ebd0"))
        painter.setPen(QtGui.QColor("#d5e3d5"))
        for step in range(1, 12):
            x = area.left() + area.width() * step / 12
            painter.drawLine(QtCore.QLineF(x, area.top(), x, area.bottom()))
        for step in range(1, 4):
            y = area.top() + area.height() * step / 4
            painter.drawLine(QtCore.QLineF(area.left(), y, area.right(), y))
        if self.history and self.fraction:
            speed_area = QtGui.QPainterPath()
            speed_area.moveTo(area.left(), area.bottom())
            speed_area.lineTo(area.left(), self._speed_y(self.history[0][1]))
            for fraction, speed in self.history:
                x = area.left() + area.width() * fraction
                speed_area.lineTo(x, self._speed_y(speed))
            speed_area.lineTo(fill.right(), self._speed_y(self.history[-1][1]))
            speed_area.lineTo(fill.right(), area.bottom())
            speed_area.closeSubpath()
            painter.fillPath(speed_area, QtGui.QColor("#248b40"))
        if self.speed is not None:
            painter.setPen(QtGui.QColor("#526557"))
            y = self._speed_y(self.speed)
            painter.drawLine(QtCore.QLineF(area.left(), y, area.right(), y))
        painter.setPen(QtGui.QColor("#9fb69f"))
        painter.drawRect(area)


class GenerationProgress(QtWidgets.QWidget):
    """Keep job progress separate from the generation workflow and its output."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 6, 0, 0)
        self.heading = QtWidgets.QLabel()
        font = self.heading.font()
        font.setBold(True)
        self.heading.setFont(font)
        layout.addWidget(self.heading)
        self.graph = _SpeedGraph()
        layout.addWidget(self.graph)
        self.detail = QtWidgets.QLabel()
        self.detail.setWordWrap(True)
        layout.addWidget(self.detail)
        self.timer = QtCore.QTimer(self, interval=250)
        self.timer.timeout.connect(self._render)
        self.hide()

    def start(self):
        self.total = self.done = self.failed = 0
        self.latest = ""
        self.state = "正在准备生成"
        self.samples = deque()
        self.graph.reset()
        self.timer.start()
        self._render()
        self.show()

    def record(self, progress):
        if not self.timer.isActive():
            return
        self.total = progress["requested_count"]
        self.failed = progress["failed_count"]
        self.done = progress["completed_count"] + self.failed
        character = progress["character"]
        self.latest = f"最近处理：{character}" if len(character) == 1 else character
        if len(character) == 1 and not self.samples:
            self.samples.append((monotonic(), self.done))
        if self.state == "正在准备生成":
            self.state = "正在生成"

    def preparation(self, stage, detail):
        if self.timer.isActive() and self.state != "正在取消":
            self.state = "正在生成" if stage == "生成字形" else stage
            self.latest = detail
            self._render()

    def cancelling(self):
        if self.timer.isActive():
            self.state = "正在取消"
            self._render()

    def finish(self, result=None):
        if not self.timer.isActive():
            return
        self.state = "生成未完成"
        if result is not None:
            self.failed = result["failed_count"]
            self.done = result["completed_count"] + self.failed
            self.total = result["requested_count"]
            if result.get("status") == "cancelled":
                self.state = "已取消生成"
            elif self.failed:
                self.state = "生成结束，部分字失败"
            else:
                self.state = "生成结束"
        self.timer.stop()
        self._render()

    def _render(self):
        now = monotonic()
        speed = None
        if self.samples:
            self.samples.append((now, self.done))
            while len(self.samples) > 1 and now - self.samples[1][0] >= 4:
                self.samples.popleft()
            first_at, first_count = self.samples[0]
            if now - first_at >= 0.2:
                speed = (self.done - first_count) / (now - first_at)
        fraction = self.done / self.total if self.total else 0
        self.graph.set_progress(fraction, speed, measuring=self.timer.isActive())
        percent = f" · 已处理 {self.done * 100 // self.total}%" if self.total else ""
        state = self.state
        if state == "正在生成" and self.total and self.done == self.total:
            state = "正在整理结果"
        self.heading.setText(state + percent)
        details = [self.latest] if self.latest else []
        if self.total:
            remaining = self.total - self.done
            details.extend((f"已处理 {self.done} / {self.total} 字", f"剩余 {remaining} 字", f"失败 {self.failed} 字"))
            if self.state == "正在生成" and remaining:
                estimate = _remaining_time(remaining / speed) if speed else "估算中"
                details.append(f"预计剩余：{estimate}")
        self.detail.setText("  ·  ".join(details))
