import os
import subprocess
import sys


def test_generation_progress_lifecycle(tmp_path):
    code = r"""
import os
from pathlib import Path
import sys
from threading import Event

from PySide6 import QtCore, QtGui, QtWidgets, QtTest
from inkstruct.desktop import main
from inkstruct.generation_workflow import GenerationWorkflow
from inkstruct.theme import use_light_theme

workspace = Path(sys.argv[1])
app = QtWidgets.QApplication([])
QtCore.QSettings.setDefaultFormat(QtCore.QSettings.Format.IniFormat)
QtCore.QSettings.setPath(QtCore.QSettings.Format.IniFormat, QtCore.QSettings.Scope.UserScope, str(workspace))
use_light_theme(app)
GenerationWorkflow.readiness = lambda *args: {
    "start": True, "message": "已准备",
}
ready = Event()
release = Event()

def generate(self, *args, progress, cancelled, **kwargs):
    for processed in range(1, 5):
        failed = int(processed >= 2)
        progress(dict(requested_count=10, completed_count=processed-failed,
                      failed_count=failed, character="孔正明木"[processed-1]))
        release.wait(.17)
    ready.set()
    release.wait(5)
    if cancelled():
        return dict(requested_count=10, completed_count=3, failed_count=1, status="cancelled",
                    writer="test", message="已取消", output=str(workspace))
    return dict(requested_count=10, completed_count=9, failed_count=1, status="completed",
                writer="test", message="已完成", output=str(workspace))

GenerationWorkflow.generate = generate
window = main(["test"], create_only=True, workspace=workspace)
window.resize(940, 840)
window.show()
page = window.centralWidget()
page.writer.setText("示例书写者")
page.text.setText("孔正明木林森山水春秋")
panel = page.progress_panel
button = QtCore.Qt.MouseButton.LeftButton
assert panel.isHidden()
QtTest.QTest.mouseClick(page.generate_button, button)
assert panel.isVisible() and panel.heading.text() == "正在准备生成"
graph = panel.graph
assert graph.speed_label.text() == "测速中"
for _ in range(100):
    QtTest.QTest.qWait(20)
    if ready.is_set():
        break
QtTest.QTest.qWait(300)
assert "40%" in panel.heading.text()
assert "剩余 6 字" in panel.detail.text() and "失败 1 字" in panel.detail.text()
assert "预计剩余：" in panel.detail.text()
assert "字/秒" in graph.speed_label.text() and graph.history

def assert_label_alignment():
    label = graph.speed_label.geometry()
    assert abs(graph._area().right() - (label.x() + label.width()) - 5) <= 1
    assert abs(graph._speed_y(graph.speed) - (label.y() + label.height()) - 3) <= 1

def assert_fill_boundary():
    raster = graph.grab().toImage()
    area = graph._area()
    boundary = area.left() + area.width() * graph.fraction
    scale = raster.devicePixelRatio()
    for y, fill in [(area.top() + 5, "#d7ebd0"), (area.bottom() - 3, "#248b40")]:
        assert raster.pixelColor(round((boundary - 3) * scale), round(y * scale)) == QtGui.QColor(fill)
        assert raster.pixelColor(round((boundary + 3) * scale), round(y * scale)) == QtGui.QColor("#f6faf6")

assert_label_alignment()
assert_fill_boundary()
first_label_y = graph.speed_label.y()
first_history = graph.history.copy()
if target := os.environ.get("INKSTRUCT_PROGRESS_TEST_SCREENSHOT"):
    assert window.grab().save(target)
    assert panel.grab().save(str(Path(target).with_name("progress-detail.png")))
for _ in range(18):
    QtTest.QTest.qWait(100)
    if graph.speed_label.y() >= first_label_y + 6:
        break
assert graph.speed_label.y() >= first_label_y + 6
assert_label_alignment()
assert graph.fraction == .4 and graph.history == first_history
assert_fill_boundary()
if target:
    assert panel.grab().save(str(Path(target).with_name("progress-slower.png")))
QtTest.QTest.mouseClick(page.cancel_button, button)
assert panel.heading.text().startswith("正在取消")
release.set()
for _ in range(100):
    QtTest.QTest.qWait(20)
    if not page.busy:
        break
assert panel.heading.text() == "已取消生成 · 已处理 40%"
assert not panel.timer.isActive() and "预计剩余" not in panel.detail.text()

QtTest.QTest.mouseClick(page.generate_button, button)
assert not panel.graph.history
for _ in range(100):
    QtTest.QTest.qWait(20)
    if not page.busy:
        break
assert panel.heading.text() == "生成结束，部分字失败 · 已处理 100%"
assert panel.graph.fraction == 1
assert not panel.timer.isActive()

previous_run = page.last_generated_run
def zero(*args, **kwargs):
    return dict(requested_count=10, completed_count=0, failed_count=0, status="cancelled",
                writer="test", message="已取消", output=str(workspace / "zero"))

GenerationWorkflow.generate = zero
QtTest.QTest.mouseClick(page.generate_button, button)
for _ in range(100):
    QtTest.QTest.qWait(20)
    if not page.busy:
        break
assert page.last_generated_run == previous_run
assert page.publish_button.text() == "制作上次批次…"
assert "test" in page.publish_batch_summary.text() and "9 字" in page.publish_batch_summary.text()

def fail(*args, **kwargs):
    raise ValueError("测试读取失败")

GenerationWorkflow.generate = fail
QtTest.QTest.mouseClick(page.generate_button, button)
for _ in range(100):
    QtTest.QTest.qWait(20)
    if not page.busy:
        break
assert panel.heading.text() == "生成未完成"
assert "测试读取失败" in page.status.text()
assert not panel.timer.isActive()
window.close()
"""
    result = subprocess.run(
        [sys.executable, "-B", "-X", "utf8", "-c", code, str(tmp_path)],
        env={**os.environ, "QT_QPA_PLATFORM": os.environ.get("INKSTRUCT_PROGRESS_TEST_PLATFORM", "offscreen")},
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
