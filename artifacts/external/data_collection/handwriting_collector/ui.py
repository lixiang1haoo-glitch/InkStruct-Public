from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QKeySequence, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSlider,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from . import __version__
from .canvas import TrajectoryCanvas
from .config import UiSettings, UiSettingsStore
from .storage import SampleStorage, sanitize_writer_id
from .tasks import CollectionTask, TaskRepository, parse_character_file


APP_STYLE = """
QWidget {
    font-family: "Microsoft YaHei", "PingFang SC", sans-serif;
    font-size: 14px; color: #0F172A; background-color: #F8FAFC;
}
QMainWindow, QDialog, QMessageBox { background-color: #F8FAFC; color: #0F172A; }
QLabel { color: #0F172A; background-color: transparent; }
QLineEdit, QSpinBox {
    color: #0F172A; background-color: #FFFFFF;
    border: 1px solid #94A3B8; border-radius: 6px;
    padding: 6px 8px; min-height: 24px;
}
QLineEdit:read-only { color: #334155; background-color: #F1F5F9; }
QPushButton {
    color: #0F172A; background-color: #FFFFFF;
    border: 1px solid #94A3B8; border-radius: 7px;
    padding: 8px 14px;
}
QPushButton:hover { border-color: #2563EB; color: #1D4ED8; }
QPushButton:disabled { color: #94A3B8; background: #F1F5F9; }
QPushButton#primaryButton { background: #2563EB; color: white; border-color: #2563EB; }
QLabel#targetCharacter { font-size: 88px; font-weight: 600; color: #0F172A; }
QLabel#mutedLabel { color: #475569; }
QProgressBar { border: 0; background: #E2E8F0; border-radius: 5px; height: 10px; }
QProgressBar::chunk { background: #2563EB; border-radius: 5px; }
QTabWidget::pane { border: 0; }
QTabBar::tab {
    color: #334155; background-color: #E2E8F0;
    border: 1px solid #CBD5E1; padding: 8px 18px;
}
QTabBar::tab:selected { color: #0F172A; background-color: #FFFFFF; }
QMenuBar, QMenu, QStatusBar {
    color: #0F172A; background-color: #F8FAFC;
}
QMenu::item:selected { color: #FFFFFF; background-color: #2563EB; }
QGroupBox {
    color: #0F172A; border: 1px solid #CBD5E1; border-radius: 8px;
    margin-top: 12px; padding-top: 12px;
}
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }
QSlider::groove:horizontal { height: 8px; background: #CBD5E1; border-radius: 4px; }
QSlider::handle:horizontal {
    width: 22px; margin: -7px 0; background: #2563EB;
    border: 2px solid #FFFFFF; border-radius: 11px;
}
"""


def light_palette() -> QPalette:
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#F8FAFC"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#0F172A"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#FFFFFF"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#F1F5F9"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#0F172A"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#FFFFFF"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#0F172A"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#2563EB"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor("#64748B"))
    palette.setColor(
        QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor("#64748B")
    )
    return palette


class AppearanceSettingsDialog(QDialog):
    """Modal placement keeps rendering sliders away from the writing surface."""

    def __init__(self, settings: UiSettings, config_path: Path, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("书写界面设置")
        self.setModal(True)
        self.setMinimumWidth(480)
        root = QVBoxLayout(self)
        explanation = QLabel(
            "这些选项只影响屏幕显示，不改变 JSON 中保存的原始坐标与压力。"
        )
        explanation.setWordWrap(True)
        root.addWidget(explanation)

        group = QGroupBox("显示参数")
        form = QFormLayout(group)
        self.stroke_slider = QSlider(Qt.Orientation.Horizontal)
        self.stroke_slider.setRange(75, 400)
        self.stroke_slider.setSingleStep(5)
        self.stroke_slider.setPageStep(25)
        self.stroke_slider.setValue(round(settings.stroke_width_scale * 100))
        self.stroke_value = QLabel()
        stroke_row = QHBoxLayout()
        stroke_row.addWidget(self.stroke_slider, 1)
        stroke_row.addWidget(self.stroke_value)
        form.addRow("笔画粗细", stroke_row)

        self.grid_slider = QSlider(Qt.Orientation.Horizontal)
        self.grid_slider.setRange(45, 95)
        self.grid_slider.setSingleStep(1)
        self.grid_slider.setPageStep(5)
        self.grid_slider.setValue(round(settings.grid_scale * 100))
        self.grid_value = QLabel()
        grid_row = QHBoxLayout()
        grid_row.addWidget(self.grid_slider, 1)
        grid_row.addWidget(self.grid_value)
        form.addRow("田字格大小", grid_row)
        root.addWidget(group)

        path_label = QLabel(f"配置文件：{config_path}")
        path_label.setObjectName("mutedLabel")
        path_label.setWordWrap(True)
        root.addWidget(path_label)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.RestoreDefaults
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("保存")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults).setText("恢复默认")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(
            QDialogButtonBox.StandardButton.RestoreDefaults
        ).clicked.connect(self.restore_defaults)
        root.addWidget(buttons)
        self.stroke_slider.valueChanged.connect(self._update_labels)
        self.grid_slider.valueChanged.connect(self._update_labels)
        self._update_labels()

    def _update_labels(self) -> None:
        self.stroke_value.setText(f"{self.stroke_slider.value()}%")
        self.stroke_value.setMinimumWidth(52)
        self.grid_value.setText(f"{self.grid_slider.value()}%")
        self.grid_value.setMinimumWidth(52)

    def restore_defaults(self) -> None:
        defaults = UiSettings()
        self.stroke_slider.setValue(round(defaults.stroke_width_scale * 100))
        self.grid_slider.setValue(round(defaults.grid_scale * 100))

    def selected_settings(self) -> UiSettings:
        return replace(
            self.settings,
            stroke_width_scale=self.stroke_slider.value() / 100.0,
            grid_scale=self.grid_slider.value() / 100.0,
        )


class SingleCharacterWidget(QWidget):
    def __init__(self, output_root_provider, parent=None):
        super().__init__(parent)
        self.output_root_provider = output_root_provider
        self.task: CollectionTask | None = None
        self._build_ui()
        self.canvas.trajectory_changed.connect(self.refresh)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 20)
        root.setSpacing(12)

        top = QHBoxLayout()
        form = QFormLayout()
        self.writer_edit = QLineEdit("demo_writer")
        self.task_name_label = QLabel("尚未载入任务")
        self.task_name_label.setObjectName("mutedLabel")
        form.addRow("书写者 ID", self.writer_edit)
        form.addRow("当前任务", self.task_name_label)
        top.addLayout(form, 1)
        self.import_button = QPushButton("导入 TXT / CSV")
        self.example_button = QPushButton("创建示例任务")
        self.resume_button = QPushButton("继续未完成任务")
        top.addWidget(self.import_button)
        top.addWidget(self.example_button)
        top.addWidget(self.resume_button)
        root.addLayout(top)

        status = QHBoxLayout()
        self.target_label = QLabel("—")
        self.target_label.setObjectName("targetCharacter")
        self.target_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.target_label.setFixedWidth(150)
        status.addWidget(self.target_label)
        progress_column = QVBoxLayout()
        self.progress_label = QLabel("请先创建或继续任务")
        self.repeat_label = QLabel("")
        self.repeat_label.setObjectName("mutedLabel")
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        progress_column.addStretch()
        progress_column.addWidget(self.progress_label)
        progress_column.addWidget(self.repeat_label)
        progress_column.addWidget(self.progress_bar)
        progress_column.addStretch()
        status.addLayout(progress_column, 1)
        root.addLayout(status)

        self.canvas = TrajectoryCanvas(show_grid=True)
        root.addWidget(self.canvas, 1)

        buttons = QHBoxLayout()
        self.undo_button = QPushButton("撤销上一笔  Ctrl+Z")
        self.clear_button = QPushButton("重写当前字  Delete")
        self.skip_button = QPushButton("暂时跳过")
        self.save_button = QPushButton("保存并下一个  Enter")
        self.save_button.setObjectName("primaryButton")
        buttons.addWidget(self.undo_button)
        buttons.addWidget(self.clear_button)
        buttons.addStretch()
        buttons.addWidget(self.skip_button)
        buttons.addWidget(self.save_button)
        root.addLayout(buttons)

        self.import_button.clicked.connect(self.import_task)
        self.example_button.clicked.connect(self.create_example_task)
        self.resume_button.clicked.connect(self.resume_task)
        self.undo_button.clicked.connect(self.canvas.undo_last_stroke)
        self.clear_button.clicked.connect(self.canvas.clear)
        self.skip_button.clicked.connect(self.skip_current)
        self.save_button.clicked.connect(self.save_current)
        self._add_shortcuts()
        self.refresh()

    def _add_shortcuts(self) -> None:
        undo = QAction(self)
        undo.setShortcut(QKeySequence.StandardKey.Undo)
        undo.triggered.connect(self.canvas.undo_last_stroke)
        self.addAction(undo)
        clear = QAction(self)
        clear.setShortcut(QKeySequence(Qt.Key.Key_Delete))
        clear.triggered.connect(self.canvas.clear)
        self.addAction(clear)
        save = QAction(self)
        save.setShortcut(QKeySequence(Qt.Key.Key_Return))
        save.triggered.connect(self.save_current)
        self.addAction(save)

    def _task_dependencies(self) -> tuple[Path, TaskRepository, SampleStorage] | None:
        root = self.output_root_provider()
        if root is None:
            return None
        return root, TaskRepository(root), SampleStorage(root)

    def import_task(self) -> None:
        dependencies = self._task_dependencies()
        if dependencies is None:
            return
        path_text, _ = QFileDialog.getOpenFileName(
            self, "选择字表", "", "字符任务 (*.txt *.csv)"
        )
        if not path_text:
            return
        repeats, accepted = QInputDialog.getInt(
            self, "重复次数", "未在 CSV 指定时，每字采集次数：", 1, 1, 100
        )
        if not accepted:
            return
        name, accepted = QInputDialog.getText(
            self, "任务名称", "任务名称：", text=Path(path_text).stem
        )
        if not accepted or not name.strip():
            return
        try:
            writer = self.writer_edit.text().strip()
            sanitize_writer_id(writer)
            characters = parse_character_file(Path(path_text), repeats)
            task = CollectionTask.create(name.strip(), Path(path_text).name, writer, characters)
            dependencies[1].save(task)
            self.set_task(task)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "无法创建任务", str(error))

    def create_example_task(self) -> None:
        dependencies = self._task_dependencies()
        if dependencies is None:
            return
        repeats, accepted = QInputDialog.getInt(
            self, "示例任务", "每字采集次数：", 1, 1, 20
        )
        if not accepted:
            return
        try:
            writer = self.writer_edit.text().strip()
            sanitize_writer_id(writer)
            characters = [
                (character, repeats, index)
                for index, character in enumerate("永中人大小天地日月山水")
            ]
            task = CollectionTask.create("内置示例任务", "builtin:cjk-demo", writer, characters)
            dependencies[1].save(task)
            self.set_task(task)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "无法创建任务", str(error))

    def resume_task(self, *, quiet: bool = False) -> None:
        dependencies = self._task_dependencies()
        if dependencies is None:
            return
        _, repository, storage = dependencies
        tasks = repository.incomplete_tasks()
        if not tasks:
            if not quiet:
                QMessageBox.information(self, "任务恢复", "没有未完成任务")
            return
        labels = [
            f"{task.name} — {task.writer_id} "
            f"({task.completed_count}/{len(task.items)})"
            for _, task in tasks
        ]
        if len(tasks) == 1:
            chosen = 0
        else:
            label, accepted = QInputDialog.getItem(
                self, "继续任务", "选择任务：", labels, 0, False
            )
            if not accepted:
                return
            chosen = labels.index(label)
        task = tasks[chosen][1]
        recovered = storage.reconcile_task(task)
        if recovered:
            repository.save(task)
        self.set_task(task)

    def set_task(self, task: CollectionTask) -> None:
        self.task = task
        self.writer_edit.setText(task.writer_id)
        self.writer_edit.setReadOnly(True)
        self.canvas.clear()
        self.refresh()

    def refresh(self) -> None:
        item = self.task.current_item() if self.task else None
        has_item = item is not None
        has_trajectory = self.canvas.trajectory.point_count > 0
        self.undo_button.setEnabled(has_trajectory)
        self.clear_button.setEnabled(has_trajectory)
        self.save_button.setEnabled(has_item and has_trajectory)
        self.skip_button.setEnabled(has_item)
        if not self.task:
            self.target_label.setText("—")
            self.task_name_label.setText("尚未载入任务")
            self.progress_label.setText("请先创建或继续任务")
            self.repeat_label.clear()
            self.progress_bar.setRange(0, 1)
            self.progress_bar.setValue(0)
            return
        self.task_name_label.setText(self.task.name)
        total = len(self.task.items)
        completed = self.task.completed_count
        self.progress_bar.setRange(0, total)
        self.progress_bar.setValue(completed)
        self.progress_label.setText(f"已完成 {completed} / {total}")
        if item:
            self.target_label.setText(item.character)
            self.repeat_label.setText(
                f"第 {item.repeat_index} / {item.repeat_total} 次 · "
                f"字表位置 {item.source_index + 1}"
            )
        else:
            self.target_label.setText("✓")
            self.repeat_label.setText("任务已完成")

    def skip_current(self) -> None:
        dependencies = self._task_dependencies()
        if not self.task or dependencies is None:
            return
        previous_cursor = self.task.cursor
        item = self.task.current_item()
        previous_status = item.status if item else None
        self.task.skip_current()
        try:
            dependencies[1].save(self.task)
        except OSError as error:
            self.task.cursor = previous_cursor
            if item is not None and previous_status is not None:
                item.status = previous_status
            QMessageBox.warning(self, "无法更新任务", str(error))
            return
        self.canvas.clear()
        self.refresh()

    def save_current(self) -> None:
        dependencies = self._task_dependencies()
        if not self.task or dependencies is None:
            return
        item = self.task.current_item()
        if item is None or self.canvas.trajectory.point_count == 0:
            return
        _, repository, storage = dependencies
        try:
            sample_id, path = storage.save_single(
                writer_id=self.writer_edit.text().strip(),
                task=self.task,
                item=item,
                trajectory=self.canvas.trajectory,
                canvas_width=self.canvas.width(),
                canvas_height=self.canvas.height(),
                device_pixel_ratio=self.canvas.devicePixelRatioF(),
            )
        except (OSError, ValueError, FileExistsError) as error:
            QMessageBox.warning(self, "保存失败", str(error))
            return
        # The sample is now durable. Advance in memory before persisting progress;
        # reconciliation will recover this exact item if state persistence fails.
        self.task.complete_current(sample_id)
        try:
            repository.save(self.task)
        except OSError as error:
            QMessageBox.warning(
                self,
                "样本已保存",
                f"样本已安全写入，但任务进度暂未落盘：\n{error}\n"
                "可继续采集；程序重启时会自动对账恢复。",
            )
        self.canvas.clear()
        self.refresh()
        if self.task.is_complete:
            QMessageBox.information(self, "任务完成", f"所有样本均已保存。\n最后样本：{path}")


class MainWindow(QMainWindow):
    def __init__(self, *, auto_resume=True):
        super().__init__()
        self.settings = QSettings("HandwritingLab", "TrajectoryCollector")
        self.ui_settings_store = UiSettingsStore()
        self.ui_settings, config_warning = self.ui_settings_store.load()
        self.output_root: Path | None = None
        saved_root = self.settings.value("output_root", "", str)
        if saved_root:
            self.output_root = Path(saved_root)
        self.setWindowTitle(f"手写轨迹数据采集器 v{__version__}")
        self.resize(1180, 820)
        self.tabs = QTabWidget()
        self.single_widget = SingleCharacterWidget(self.ensure_output_root)
        self.tabs.addTab(self.single_widget, "单字任务采集")
        self.setCentralWidget(self.tabs)
        self.apply_ui_settings(self.ui_settings)
        self._build_menu()
        self._update_status()
        if config_warning:
            QTimer.singleShot(
                0,
                lambda message=config_warning: QMessageBox.warning(
                    self, "界面配置", message
                ),
            )
        if not auto_resume:
            return
        if self.output_root is None:
            QTimer.singleShot(0, self.choose_output_root)
        else:
            QTimer.singleShot(0, lambda: self.single_widget.resume_task(quiet=True))

    def _build_menu(self) -> None:
        data_menu = self.menuBar().addMenu("数据")
        choose = QAction("选择输出目录…", self)
        choose.triggered.connect(self.choose_output_root)
        data_menu.addAction(choose)
        self.output_action = QAction(self)
        self.output_action.setEnabled(False)
        data_menu.addAction(self.output_action)
        settings_menu = self.menuBar().addMenu("设置")
        appearance = QAction("书写界面设置…", self)
        appearance.setToolTip("调整笔画粗细与田字格尺寸")
        appearance.triggered.connect(self.open_appearance_settings)
        settings_menu.addAction(appearance)

    def open_appearance_settings(self) -> None:
        dialog = AppearanceSettingsDialog(
            self.ui_settings, self.ui_settings_store.path, self
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        selected = dialog.selected_settings()
        try:
            self.ui_settings_store.save(selected)
        except OSError as error:
            QMessageBox.warning(self, "配置保存失败", str(error))
            return
        self.ui_settings = selected
        self.apply_ui_settings(selected)
        self.statusBar().showMessage("书写界面设置已保存", 4000)

    def apply_ui_settings(self, settings: UiSettings) -> None:
        self.single_widget.canvas.set_render_settings(
            settings.stroke_width_scale, settings.grid_scale
        )

    def choose_output_root(self) -> Path | None:
        initial = str(self.output_root or Path.home())
        selected = QFileDialog.getExistingDirectory(self, "选择数据输出目录", initial)
        if not selected:
            return self.output_root
        self.output_root = Path(selected)
        self.settings.setValue("output_root", str(self.output_root))
        self._update_status()
        self.single_widget.resume_task(quiet=True)
        return self.output_root

    def ensure_output_root(self) -> Path | None:
        if self.output_root is None:
            return self.choose_output_root()
        try:
            self.output_root.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            QMessageBox.warning(self, "输出目录不可用", str(error))
            return None
        return self.output_root

    def _update_status(self) -> None:
        text = str(self.output_root) if self.output_root else "尚未选择输出目录"
        self.output_action.setText(f"输出目录：{text}")
        self.statusBar().showMessage(text)


def run() -> int:
    import sys

    application = QApplication.instance() or QApplication(sys.argv)
    application.setOrganizationName("HandwritingLab")
    application.setApplicationName("Handwriting Trajectory Collector")
    application.setStyle("Fusion")
    application.setPalette(light_palette())
    application.setStyleSheet(APP_STYLE)
    window = MainWindow()
    window.show()
    return application.exec()
