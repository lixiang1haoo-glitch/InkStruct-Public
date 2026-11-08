from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QEvent, QSettings, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QKeySequence, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
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
from .exporter import (
    DatasetExportError,
    audit_task_items,
    export_task_dataset,
)
from .line_tasks import (
    LineCollectionTask,
    LineTaskRepository,
    load_builtin_line_prompts,
    load_vocabulary,
    parse_line_file,
)
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
        self.writer_edit = QLineEdit("user_001")
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


class LineCollectionWidget(QWidget):
    def __init__(self, output_root_provider, parent=None):
        super().__init__(parent)
        self.output_root_provider = output_root_provider
        self.task: LineCollectionTask | None = None
        self._shift_shortcut_pending = False
        self._deferred_char_end = False
        self.settings = QSettings("HandwritingLab", "TrajectoryCollector")
        self._build_ui()
        self.canvas.trajectory_changed.connect(self._on_trajectory_changed)
        application = QApplication.instance()
        if application is not None:
            application.installEventFilter(self)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 20)
        root.setSpacing(12)

        inputs = QHBoxLayout()
        inputs.addWidget(QLabel("书写者 ID"))
        self.writer_edit = QLineEdit("user_001")
        inputs.addWidget(self.writer_edit)
        inputs.addWidget(QLabel("采集链路"))
        self.route_combo = QComboBox()
        self.route_combo.addItem("Surface / 本机数位笔", "direct_surface")
        self.route_combo.addItem("Sunshine / Moonlight 数位笔", "moonlight_pen")
        inputs.addWidget(self.route_combo)
        self.import_button = QPushButton("导入整行 TXT / CSV")
        self.builtin_button = QPushButton("创建内置 DiffInk 220 行任务（15–20 字）")
        self.resume_button = QPushButton("继续未完成任务")
        self.export_button = QPushButton("导出 DiffInk HDF5")
        inputs.addWidget(self.import_button)
        inputs.addWidget(self.builtin_button)
        inputs.addWidget(self.resume_button)
        inputs.addWidget(self.export_button)
        root.addLayout(inputs)

        self.task_label = QLabel("尚未载入整行任务")
        self.task_label.setObjectName("mutedLabel")
        self.progress_label = QLabel("可创建内置任务，或导入至少 220 行自定义文本")
        progress_row = QHBoxLayout()
        progress_row.addWidget(self.task_label)
        progress_row.addStretch()
        progress_row.addWidget(self.progress_label)
        root.addLayout(progress_row)
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        root.addWidget(self.progress_bar)

        self.prompt_label = QLabel("—")
        self.prompt_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.prompt_label.setWordWrap(True)
        self.prompt_label.setMinimumHeight(72)
        self.prompt_label.setStyleSheet(
            "font-size: 26px; font-weight: 600; padding: 8px; "
            "background: white; border: 1px solid #CBD5E1; border-radius: 8px;"
        )
        root.addWidget(self.prompt_label)
        self.boundary_label = QLabel("")
        self.boundary_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.boundary_label.setObjectName("mutedLabel")
        root.addWidget(self.boundary_label)

        self.canvas = TrajectoryCanvas(show_grid=False)
        root.addWidget(self.canvas, 1)

        buttons = QHBoxLayout()
        self.clear_button = QPushButton("重写当前行  Delete")
        self.undo_button = QPushButton("撤销上一笔  Ctrl+Z")
        self.undo_boundary_button = QPushButton("撤销字尾标记")
        self.mark_button = QPushButton("标记当前字符结束  Shift")
        self.skip_button = QPushButton("暂时跳过")
        self.redo_button = QPushButton("重录上一条")
        self.pilot_button = QPushButton("检查并通过 20 行试采")
        self.save_button = QPushButton("保存并下一个  Enter")
        self.save_button.setObjectName("primaryButton")
        buttons.addWidget(self.clear_button)
        buttons.addWidget(self.undo_button)
        buttons.addWidget(self.undo_boundary_button)
        buttons.addStretch()
        buttons.addWidget(self.redo_button)
        buttons.addWidget(self.skip_button)
        buttons.addWidget(self.pilot_button)
        buttons.addWidget(self.mark_button)
        buttons.addWidget(self.save_button)
        root.addLayout(buttons)

        self.import_button.clicked.connect(self.import_task)
        self.builtin_button.clicked.connect(self.create_builtin_task)
        self.resume_button.clicked.connect(self.resume_task)
        self.export_button.clicked.connect(self.export_dataset)
        self.clear_button.clicked.connect(self.clear_current)
        self.undo_button.clicked.connect(self.canvas.undo_last_stroke)
        self.undo_boundary_button.clicked.connect(self.canvas.undo_char_end)
        self.mark_button.clicked.connect(self.canvas.mark_char_end)
        self.skip_button.clicked.connect(self.skip_current)
        self.redo_button.clicked.connect(self.redo_previous)
        self.pilot_button.clicked.connect(self.approve_pilot)
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
        clear.triggered.connect(self.clear_current)
        self.addAction(clear)
        save = QAction(self)
        save.setShortcut(QKeySequence(Qt.Key.Key_Return))
        save.triggered.connect(self.save_current)
        self.addAction(save)

    def eventFilter(self, watched, event) -> bool:
        target_is_here = watched is self or (
            isinstance(watched, QWidget) and self.isAncestorOf(watched)
        )
        line_page_is_active = target_is_here or (
            self.isVisible() and self.window().isActiveWindow()
        )
        if line_page_is_active and event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Shift and not event.isAutoRepeat():
                self._shift_shortcut_pending = True
            elif self._shift_shortcut_pending:
                # Shift combined with another key remains a normal modifier.
                self._shift_shortcut_pending = False
        elif (
            line_page_is_active
            and event.type() == QEvent.Type.KeyRelease
            and event.key() == Qt.Key.Key_Shift
        ):
            trigger = self._shift_shortcut_pending and not event.isAutoRepeat()
            self._shift_shortcut_pending = False
            if trigger and self._mark_or_defer_char_end():
                return True
        return super().eventFilter(watched, event)

    def _mark_or_defer_char_end(self) -> bool:
        if self.mark_button.isEnabled():
            self.mark_button.click()
            return True
        item = self.task.current_item() if self.task else None
        if (
            item is not None
            and self.canvas.pen_down
            and self.canvas.trajectory.point_count > 0
            and len(self.canvas.char_ends) < len(item.text)
        ):
            # Remote capture can deliver the tablet release just after Shift.
            self._deferred_char_end = True
            return True
        return False

    def _on_trajectory_changed(self) -> None:
        self.refresh()
        if not self._deferred_char_end or self.canvas.pen_down:
            return
        self._deferred_char_end = False
        if self.mark_button.isEnabled():
            self.mark_button.click()

    def _dependencies(
        self,
    ) -> tuple[Path, LineTaskRepository, SampleStorage] | None:
        root = self.output_root_provider()
        if root is None:
            return None
        return root, LineTaskRepository(root), SampleStorage(root)

    def _default_vocabulary_path(self) -> Path | None:
        saved = self.settings.value("diffink_vocab_path", "", str)
        candidates = [
            Path(saved) if saved else None,
            Path(__file__).resolve().parents[2]
            / "diffink"
            / "datas"
            / "meta"
            / "All_zi.json",
            Path.cwd() / "datas" / "meta" / "All_zi.json",
        ]
        return next(
            (path for path in candidates if path is not None and path.is_file()),
            None,
        )

    def _ensure_vocabulary_path(self) -> Path | None:
        path = self._default_vocabulary_path()
        if path is not None:
            return path
        selected, _ = QFileDialog.getOpenFileName(
            self, "选择 DiffInk All_zi.json", "", "JSON 字表 (All_zi.json *.json)"
        )
        if not selected:
            return None
        path = Path(selected)
        try:
            load_vocabulary(path)
        except ValueError as error:
            QMessageBox.warning(self, "字表无效", str(error))
            return None
        self.settings.setValue("diffink_vocab_path", str(path))
        return path

    def import_task(self) -> None:
        dependencies = self._dependencies()
        if dependencies is None:
            return
        source_text, _ = QFileDialog.getOpenFileName(
            self, "选择整行任务", "", "整行任务 (*.txt *.csv)"
        )
        if not source_text:
            return
        vocabulary_path = self._ensure_vocabulary_path()
        if vocabulary_path is None:
            return
        name, accepted = QInputDialog.getText(
            self, "任务名称", "任务名称：", text=Path(source_text).stem
        )
        if not accepted or not name.strip():
            return
        try:
            writer = self.writer_edit.text().strip()
            sanitize_writer_id(writer)
            vocabulary = load_vocabulary(vocabulary_path)
            prompts = parse_line_file(Path(source_text), vocabulary)
            task = LineCollectionTask.create(
                name=name.strip(),
                source=Path(source_text).name,
                writer_id=writer,
                capture_route=str(self.route_combo.currentData()),
                vocabulary_path=vocabulary_path,
                prompts=prompts,
            )
            dependencies[1].save(task)
            self.settings.setValue("diffink_vocab_path", str(vocabulary_path))
            self.set_task(task)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "无法创建整行任务", str(error))

    def create_builtin_task(self) -> None:
        dependencies = self._dependencies()
        if dependencies is None:
            return
        vocabulary_path = self._ensure_vocabulary_path()
        if vocabulary_path is None:
            return
        try:
            writer = self.writer_edit.text().strip()
            sanitize_writer_id(writer)
            vocabulary = load_vocabulary(vocabulary_path)
            prompts = load_builtin_line_prompts(vocabulary)
            task = LineCollectionTask.create(
                name="内置 DiffInk 220 行任务（15–20 字）",
                source="builtin:diffink-220-v2-short",
                writer_id=writer,
                capture_route=str(self.route_combo.currentData()),
                vocabulary_path=vocabulary_path,
                prompts=prompts,
            )
            dependencies[1].save(task)
            self.settings.setValue("diffink_vocab_path", str(vocabulary_path))
            self.set_task(task)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "无法创建内置任务", str(error))

    def resume_task(self, *, quiet: bool = False) -> None:
        dependencies = self._dependencies()
        if dependencies is None:
            return
        _, repository, storage = dependencies
        tasks = repository.all_tasks()
        if not tasks:
            if not quiet:
                QMessageBox.information(self, "任务恢复", "还没有整行任务")
            return
        labels = [
            f"{task.name} — {task.writer_id} "
            f"({task.completed_count}/{len(task.items)})"
            + (" · 已完成" if task.is_complete else "")
            for _, task in tasks
        ]
        if quiet or len(tasks) == 1:
            chosen = 0
        else:
            label, accepted = QInputDialog.getItem(
                self, "继续整行任务", "选择任务：", labels, 0, False
            )
            if not accepted:
                return
            chosen = labels.index(label)
        task = tasks[chosen][1]
        recovered = storage.reconcile_line_task(task)
        if recovered:
            repository.save(task)
        self.set_task(task)

    def set_task(self, task: LineCollectionTask) -> None:
        self.task = task
        self.writer_edit.setText(task.writer_id)
        self.writer_edit.setReadOnly(True)
        route_index = self.route_combo.findData(task.capture_route)
        if route_index >= 0:
            self.route_combo.setCurrentIndex(route_index)
        self.route_combo.setEnabled(False)
        self.canvas.clear()
        self.refresh()

    def clear_current(self) -> None:
        self.canvas.clear()

    def skip_current(self) -> None:
        dependencies = self._dependencies()
        if self.task is None or dependencies is None:
            return
        self.task.skip_current()
        try:
            dependencies[1].save(self.task)
        except OSError as error:
            QMessageBox.warning(self, "无法更新整行任务", str(error))
            return
        self.canvas.clear()
        self.refresh()

    def redo_previous(self) -> None:
        dependencies = self._dependencies()
        if self.task is None or dependencies is None:
            return
        if not self.task.redo_previous():
            QMessageBox.information(self, "重录", "还没有可重录的已完成任务")
            return
        try:
            dependencies[1].save(self.task)
        except OSError as error:
            QMessageBox.warning(self, "无法更新整行任务", str(error))
            return
        self.canvas.clear()
        self.refresh()

    def save_current(self) -> None:
        dependencies = self._dependencies()
        if self.task is None or dependencies is None:
            return
        item = self.task.current_item()
        if item is None or not self.canvas.trajectory.point_count:
            return
        ends = list(self.canvas.char_ends)
        if len(ends) == len(item.text) - 1:
            ends.append(self.canvas.trajectory.point_count)
        if len(ends) != len(item.text):
            QMessageBox.warning(
                self,
                "字符标记错误",
                f"需要 {len(item.text)} 个字尾标记，当前为 {len(ends)} 个；"
                "最后一个字符可在保存时自动补齐。",
            )
            return
        root, repository, storage = dependencies
        try:
            sample_id, path = storage.save_line_raw(
                writer_id=self.writer_edit.text().strip(),
                task=self.task,
                item=item,
                trajectory=self.canvas.trajectory,
                char_ends=ends,
                canvas_width=self.canvas.width(),
                canvas_height=self.canvas.height(),
                device_pixel_ratio=self.canvas.devicePixelRatioF(),
                logical_dpi_x=self.canvas.logicalDpiX(),
                logical_dpi_y=self.canvas.logicalDpiY(),
                capture_route=str(self.route_combo.currentData()),
            )
        except (OSError, ValueError, FileExistsError) as error:
            QMessageBox.warning(self, "保存失败", str(error))
            return
        self.task.complete_current(sample_id, path.relative_to(root).as_posix())
        try:
            repository.save(self.task)
        except OSError as error:
            QMessageBox.warning(
                self,
                "样本已保存",
                f"原始样本已安全写入，但任务进度暂未落盘：\n{error}\n"
                "程序重启时会自动对账恢复。",
            )
        self.canvas.clear()
        self.refresh()
        if self.task.blocked_for_pilot:
            QMessageBox.information(
                self,
                "试采完成",
                "前 20 行已保存。请点击“检查并通过 20 行试采”，"
                "通过坐标、点数、压力与预览检查后继续。",
            )
        elif self.task.is_complete:
            QMessageBox.information(
                self, "整行任务完成", "200 行训练与 20 行验证数据均已采集。"
            )

    def approve_pilot(self) -> None:
        dependencies = self._dependencies()
        if self.task is None or dependencies is None:
            return
        root, repository, _ = dependencies
        try:
            vocabulary = load_vocabulary(Path(self.task.vocabulary_path))
            result = audit_task_items(
                root, self.task, vocabulary, self.task.pilot_items, category="pilot_audits"
            )
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "试采检查失败", str(error))
            return
        if result.rejected:
            for rejected in result.rejected:
                self.task.redo_item(rejected["item_id"])
            repository.save(self.task)
            self.canvas.clear()
            self.refresh()
            QMessageBox.warning(
                self,
                "试采未通过",
                f"{len(result.rejected)} 行需要重录。报告与预览位于：\n"
                f"{result.output_dir}",
            )
            return
        self.task.approve_pilot()
        repository.save(self.task)
        self.refresh()
        warning_count = sum(len(sample.warnings) for sample in result.accepted)
        QMessageBox.information(
            self,
            "试采通过",
            f"20 行结构检查全部通过，分布告警 {warning_count} 项。\n"
            f"请查看预览后继续采集：\n{result.output_dir}",
        )

    def export_dataset(self) -> None:
        dependencies = self._dependencies()
        if self.task is None or dependencies is None:
            return
        if not self.task.is_complete:
            QMessageBox.warning(
                self,
                "尚不能导出",
                f"任务需完成 220 行，当前为 {self.task.completed_count} 行。",
            )
            return
        try:
            vocabulary = load_vocabulary(Path(self.task.vocabulary_path))
            result = export_task_dataset(dependencies[0], self.task, vocabulary)
        except DatasetExportError as error:
            QMessageBox.warning(
                self, "导出未通过质检", f"{error}\n报告目录：{error.output_dir}"
            )
            return
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "导出失败", str(error))
            return
        QMessageBox.information(
            self,
            "DiffInk 数据集已导出",
            f"personal_train.h5、personal_val.h5 与作者表已生成：\n"
            f"{result.output_dir}",
        )

    def refresh(self) -> None:
        item = self.task.current_item() if self.task else None
        point_count = self.canvas.trajectory.point_count
        boundary_count = len(self.canvas.char_ends)
        has_item = item is not None
        expected_count = len(item.text) if item else 0
        self.undo_button.setEnabled(point_count > 0)
        self.clear_button.setEnabled(point_count > 0)
        self.undo_boundary_button.setEnabled(boundary_count > 0)
        self.mark_button.setEnabled(
            has_item
            and point_count > 0
            and not self.canvas.pen_down
            and boundary_count < expected_count
        )
        self.save_button.setEnabled(
            has_item
            and point_count > 0
            and not self.canvas.pen_down
            and boundary_count in {expected_count - 1, expected_count}
        )
        self.skip_button.setEnabled(has_item)
        self.redo_button.setEnabled(bool(self.task and self.task.completed_count))
        self.pilot_button.setEnabled(
            bool(self.task and self.task.blocked_for_pilot)
        )
        self.export_button.setEnabled(bool(self.task and self.task.is_complete))
        if self.task is None:
            self.progress_bar.setRange(0, 1)
            self.progress_bar.setValue(0)
            self.prompt_label.setText("—")
            self.boundary_label.clear()
            return
        total = len(self.task.items)
        completed = self.task.completed_count
        self.task_label.setText(
            f"{self.task.name} · {self.task.writer_id} · {self.task.capture_route}"
        )
        self.progress_label.setText(f"已完成 {completed} / {total}")
        self.progress_bar.setRange(0, total)
        self.progress_bar.setValue(completed)
        if item is not None:
            self.prompt_label.setText(item.text)
            if boundary_count < len(item.text):
                self.boundary_label.setText(
                    f"{item.split.upper()} · 任务 {item.source_index + 1} · "
                    f"下一字尾 {boundary_count + 1}/{len(item.text)}："
                    f"{item.text[boundary_count]}"
                )
            else:
                self.boundary_label.setText("全部字符边界已标记，可以保存")
        elif self.task.blocked_for_pilot:
            self.prompt_label.setText("20 行试采待检查")
            self.boundary_label.setText("点击“检查并通过 20 行试采”后继续")
        elif self.task.is_complete:
            self.prompt_label.setText("✓ 采集完成")
            self.boundary_label.setText("可导出 DiffInk HDF5")


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
        self.line_widget = LineCollectionWidget(self.ensure_output_root)
        self.tabs.addTab(self.single_widget, "单字任务采集")
        self.tabs.addTab(self.line_widget, "整行采集")
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
            QTimer.singleShot(0, lambda: self.line_widget.resume_task(quiet=True))

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
        self.line_widget.canvas.set_render_settings(
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
        self.line_widget.resume_task(quiet=True)
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
