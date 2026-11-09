"""Shared symbol collection tab for the source and Windows portable launchers."""

from __future__ import annotations

from pathlib import Path

from .capture_boundary import install_capture_boundary_guard
from .capture_controls import canvas_slider_row
from .capture_workflow_ui import CaptureLifecycleMixin
from .symbol_capture import (
    FRAME,
    SymbolStorage,
    parse_symbol_file,
    scaled_frame,
    symbol_info,
)
from .symbol_task_dialog import SymbolTaskDialog
from .symbol_tasks import item_letter_style


def create_symbol_widget_class(collector_ui, QtCore, QtGui, QtWidgets):
    from handwriting_collector.canvas import TrajectoryCanvas
    from handwriting_collector.tasks import CollectionTask, TaskRepository

    class SymbolCanvas(TrajectoryCanvas):
        def __init__(self):
            super().__init__(show_grid=True)
            self.set_canvas_percent(100)

        def set_canvas_percent(self, percent):
            self.canvas_percent = percent
            guides = scaled_frame(percent)
            self.setFixedSize(guides["canvas_width"], guides["canvas_height"])
            self.update()

        def _draw_grid(self, painter):
            painter.save()
            painter.scale(self.canvas_percent / 100, self.canvas_percent / 100)
            baseline, em = FRAME["baseline_y_px"], FRAME["em_px"]
            for title, level, color in [
                ("大写字高", FRAME["cap_height_em"], "#94a3b8"),
                ("小写字高", FRAME["x_height_em"], "#94a3b8"),
                ("数学轴", FRAME["math_axis_em"], "#c084fc"),
                ("基线", 0, "#2563eb"),
                ("下伸线", -FRAME["descender_em"], "#94a3b8"),
            ]:
                y = baseline - level * em
                painter.setPen(QtGui.QPen(QtGui.QColor(color), 1, QtCore.Qt.PenStyle.DashLine))
                painter.drawLine(QtCore.QPointF(95, y), QtCore.QPointF(525, y))
                painter.drawText(QtCore.QPointF(8, y - 3), title)
            painter.setPen(QtGui.QPen(QtGui.QColor("#94a3b8"), 1, QtCore.Qt.PenStyle.DotLine))
            x = FRAME["origin_x_px"]
            painter.drawLine(QtCore.QPointF(x, 25), QtCore.QPointF(x, 305))
            painter.restore()

    class SymbolWidget(CaptureLifecycleMixin, collector_ui.SingleCharacterWidget):
        def __init__(self, output_root_provider, parent=None, *, settings=None):
            self.canvas_settings = (
                settings if settings is not None else QtCore.QSettings("InkStruct", "SymbolCollector")
            )
            super().__init__(output_root_provider, parent)

        def _build_ui(self):
            self._task_root = None
            self._switching = False
            root = QtWidgets.QVBoxLayout(self)
            top = QtWidgets.QHBoxLayout()
            top.addWidget(QtWidgets.QLabel("书写者 ID"))
            self.writer_edit = QtWidgets.QLineEdit("demo_writer")
            self.writer_edit.setMaximumWidth(160)
            top.addWidget(self.writer_edit)
            top.addStretch()
            self.example_button = QtWidgets.QPushButton("创建任务")
            self.import_button = QtWidgets.QPushButton("导入 TXT / CSV")
            self.resume_button = QtWidgets.QPushButton("继续／打开任务")
            self.review_button = QtWidgets.QPushButton("重录已保存…")
            self.review_button.setObjectName('rerecord_saved_symbols')
            for button in (self.example_button, self.import_button, self.resume_button, self.review_button):
                top.addWidget(button)
            root.addLayout(top)
            self.task_name_label = QtWidgets.QLabel("尚未载入任务")
            self.task_name_label.setWordWrap(True)
            root.addWidget(self.task_name_label)
            status = QtWidgets.QHBoxLayout()
            self.target_label = QtWidgets.QLabel("—")
            self.target_label.setObjectName("targetCharacter")
            self.target_label.setFixedSize(160, 150)
            self.target_label.setAlignment(QtCore.Qt.AlignCenter)
            self.target_label.setStyleSheet('font-size: 88px; font-weight: 600;')
            status.addWidget(self.target_label)
            detail = QtWidgets.QVBoxLayout()
            self.progress_label = QtWidgets.QLabel()
            self.repeat_label = QtWidgets.QLabel()
            self.identity_label = QtWidgets.QLabel()
            self.identity_label.setWordWrap(True)
            self.progress_bar = QtWidgets.QProgressBar()
            for widget in (
                self.progress_label,
                self.repeat_label,
                self.identity_label,
                self.progress_bar,
            ):
                detail.addWidget(widget)
            status.addLayout(detail, 1)
            root.addLayout(status)
            explanation = QtWidgets.QLabel(
                "从竖虚线附近起笔：大写/数字参考大写字高，小写参考小写字高，g/p 等可伸到基线下；"
                "+、= 等围绕紫色数学轴书写。按任务设定份数自然书写，可用不同笔数。"
            )
            explanation.setWordWrap(True)
            root.addWidget(explanation)
            self.canvas = SymbolCanvas()
            size_row, self.canvas_size_slider, self.canvas_size_label = canvas_slider_row(
                "画布大小", "标点与扩展画布大小", "先保存或重写当前笔迹，再调整画布大小"
            )
            self.canvas_size_slider.setObjectName("symbolCanvasSizeSlider")
            self.canvas_size_slider.setRange(10, 30)  # 50%–150%, in 5% steps.
            self.canvas_size_slider.setPageStep(2)
            try:
                percent = int(self.canvas_settings.value("canvas_percent", 100))
                scaled_frame(percent)
            except (TypeError, ValueError, OverflowError):
                percent = 100
            self.canvas_size_slider.setValue(percent // 5)
            root.addLayout(size_row)
            self.canvas_scroll = QtWidgets.QScrollArea()
            self.canvas_scroll.setWidget(self.canvas)
            self.canvas_scroll.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            root.addWidget(self.canvas_scroll, 1)
            self._apply_canvas_size(percent)
            self.canvas_size_slider.valueChanged.connect(self._change_canvas_size)
            self.variant_note = QtWidgets.QLineEdit()
            self.variant_note.setPlaceholderText(
                "可选：写法备注，如斜体、直体、开口 4；不同 Unicode 字符请分别采集"
            )
            root.addWidget(self.variant_note)
            buttons = QtWidgets.QHBoxLayout()
            self.undo_button = QtWidgets.QPushButton("撤销上一笔")
            self.clear_button = QtWidgets.QPushButton("清空当前笔迹")
            self.skip_button = QtWidgets.QPushButton("跳过")
            self.save_button = QtWidgets.QPushButton("保存并下一个 · Enter")
            self.save_button.setObjectName("primaryButton")
            for button in (self.undo_button, self.clear_button, self.skip_button, self.save_button):
                buttons.addWidget(button)
            root.addLayout(buttons)
            self.import_button.clicked.connect(self.import_task)
            self.example_button.clicked.connect(self.create_task)
            self.resume_button.clicked.connect(lambda: self.resume_task())
            self.review_button.clicked.connect(self.review_saved)
            self.undo_button.clicked.connect(self.canvas.undo_last_stroke)
            self.clear_button.clicked.connect(self.canvas.clear)
            self.skip_button.clicked.connect(self.skip_current)
            self.save_button.clicked.connect(self.save_current)
            self._add_shortcuts()
            self.refresh()
            self.boundary_guard = install_capture_boundary_guard(self, QtCore, QtGui, QtWidgets)

        def _apply_canvas_size(self, percent):
            self.canvas.set_canvas_percent(percent)
            self.canvas_scroll.setMinimumHeight(min(335, self.canvas.height() + 15))
            self.canvas_size_label.setText(
                f"{percent}% · {self.canvas.width()} × {self.canvas.height()} px"
            )

        def _change_canvas_size(self, value):
            if self.canvas.pen_down or self.canvas.trajectory.point_count:
                previous = self.canvas_size_slider.blockSignals(True)
                self.canvas_size_slider.setValue(self.canvas.canvas_percent // 5)
                self.canvas_size_slider.blockSignals(previous)
                return
            percent = value * 5
            self._apply_canvas_size(percent)
            self.canvas_settings.setValue("canvas_percent", percent)
            self.canvas_settings.sync()

        def _add_shortcuts(self):
            for key, callback in [
                ("Return", self.save_current),
                ("Ctrl+Z", self.canvas.undo_last_stroke),
            ]:
                action = QtGui.QAction(self)
                action.setShortcut(QtGui.QKeySequence(key))
                action.setShortcutContext(QtCore.Qt.ShortcutContext.WidgetWithChildrenShortcut)
                action.triggered.connect(callback)
                self.addAction(action)

        def _task_dependencies(self):
            if getattr(self, '_capture_catalog', None):
                return CaptureLifecycleMixin._task_dependencies(self)
            if self._task_root is not None and not self._switching:
                root = self._task_root
                return root, TaskRepository(root), SymbolStorage(root, self.variant_note.text)
            base = self.output_root_provider()
            if base is None:
                return None
            root = Path(base) / "symbol_collection"
            return root, TaskRepository(root), SymbolStorage(root, self.variant_note.text)

        def _start(self, name, characters, source='inkstruct:symbol_catalog_v1:unspecified', writer=None):
            self._switching = True
            try:
                dependencies = self._task_dependencies()
            finally:
                self._switching = False
            if dependencies is None:
                return
            writer = writer if writer is not None else self.writer_edit.text().strip()
            import re

            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", writer):
                raise ValueError("书写者 ID 需以字母或数字开头，仅含字母、数字、点、横线或下划线")
            if getattr(self, '_capture_catalog', None):
                from .capture_management import check_capture_paths
                check_capture_paths(dependencies[0], writer)
            task = CollectionTask.create(name, source, writer, characters)
            if getattr(self, '_capture_catalog', None):
                from handwriting_collector.tasks import TaskRepository
                TaskRepository(dependencies[0]).save(task)
                if self.task:
                    self._capture_catalog.set_state('symbol', self.task.task_id, 'paused')
            else:
                dependencies[1].save(task)
            self.writer_edit.setText(writer)
            self._task_root = dependencies[0]
            self.set_task(task)

        def _can_switch(self):
            if getattr(self, '_capture_catalog', None):
                return CaptureLifecycleMixin._can_switch(self)
            if self.canvas.pen_down:
                return False
            if not self.canvas.trajectory.point_count:
                return True
            return (
                QtWidgets.QMessageBox.question(
                    self,
                    "尚未保存",
                    "当前笔迹尚未保存，放弃后切换任务？",
                    QtWidgets.QMessageBox.StandardButton.Yes
                    | QtWidgets.QMessageBox.StandardButton.No,
                    QtWidgets.QMessageBox.StandardButton.No,
                )
                == QtWidgets.QMessageBox.StandardButton.Yes
            )

        def create_task(self):
            if not self._can_switch():
                return
            self.configure_task()

        def configure_task(self, imported=None, name=None):
            base = self.output_root_provider()
            if base is None:
                return
            dialog = SymbolTaskDialog(self.writer_edit.text().strip(), self, imported=imported,
                                      collection_root=Path(base) / 'symbol_collection',
                                      catalog=getattr(self, '_capture_catalog', None))
            if name:
                dialog.name.setText(name)
            if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
                return
            try:
                source, entries = dialog.plan()
                self._start(dialog.name.text().strip(), entries, source, dialog.writer.text().strip())
            except (OSError, ValueError) as error:
                QtWidgets.QMessageBox.warning(self, "无法创建任务", str(error))

        def import_task(self):
            if not self._can_switch():
                return
            path, _ = QtWidgets.QFileDialog.getOpenFileName(
                self, "选择符号字表", "", "字表 (*.txt *.csv)"
            )
            if not path:
                return
            try:
                self.configure_task(parse_symbol_file(Path(path)), Path(path).stem)
            except (OSError, ValueError) as error:
                QtWidgets.QMessageBox.warning(self, "无法导入", str(error))

        def resume_task(self, *, quiet=False):
            if getattr(self, '_capture_catalog', None):
                return CaptureLifecycleMixin.resume_task(self, quiet=quiet)
            if self._can_switch():
                self._switching = True
                try:
                    dependencies = self._task_dependencies()
                    if dependencies is None:
                        return
                    _, repository, storage = dependencies
                    tasks = []
                    for path in repository.tasks_dir.glob('*/state.json'):
                        try:
                            task = repository.load(path)
                            if not quiet or not task.is_complete:
                                tasks.append((path, task))
                        except ValueError:
                            continue
                    tasks.sort(key=lambda pair: pair[0].stat().st_mtime, reverse=True)
                    if not tasks:
                        if not quiet:
                            QtWidgets.QMessageBox.information(self,'采集任务','没有已保存任务')
                        return
                    chosen = 0
                    if len(tasks) > 1:
                        labels = [f'{t.name} — {t.writer_id} ({t.completed_count}/{len(t.items)})' for _,t in tasks]
                        label, accepted = QtWidgets.QInputDialog.getItem(self,'打开采集任务','选择任务（包含已完成任务）：',labels,0,False)
                        if not accepted:
                            return
                        chosen = labels.index(label)
                    task = tasks[chosen][1]
                    if storage.reconcile_task(task):
                        repository.save(task)
                    self.set_task(task)
                except (OSError, ValueError) as error:
                    QtWidgets.QMessageBox.warning(self,'无法打开任务',str(error))
                finally:
                    self._switching = False

        def review_saved(self):
            if getattr(self, '_capture_catalog', None):
                return CaptureLifecycleMixin.review_saved(self)
            if not self.task or not self.task.completed_count or not self._can_switch():
                return
            from .symbol_review_dialog import SymbolReviewDialog
            from .symbol_revisions import requeue_completed
            dependencies = self._task_dependencies()
            if dependencies is None:
                return
            dialog = SymbolReviewDialog(self.task, dependencies[0], self)
            try:
                if dialog.exec() == QtWidgets.QDialog.Accepted:
                    revision = requeue_completed(dependencies[0], self.task, dependencies[1], dialog.selected_ids())
                    self.variant_note.clear()
                    self.canvas.clear()
                    self.refresh()
                    self.review_button.setToolTip('上次重录备份：'+str(revision))
            except (OSError, ValueError) as error:
                QtWidgets.QMessageBox.warning(self,'未能重录',str(error))
            finally:
                dialog.deleteLater()

        def set_task(self, task):
            for item in task.items:
                symbol_info(item.character)
                item_letter_style(task, item)
            dependencies = self._task_dependencies()
            if dependencies is not None:
                self._task_root = dependencies[0]
            self.variant_note.clear()
            super().set_task(task)

        def refresh(self):
            super().refresh()
            self.review_button.setEnabled(bool(self.task and self.task.completed_count and not self.canvas.pen_down))
            self.canvas_size_slider.setEnabled(
                not self.canvas.pen_down and not self.canvas.trajectory.point_count
            )
            item = self.task.current_item() if self.task else None
            if self.task and self._task_root is not None:
                self.task_name_label.setText(f"{self.task.name} · {self._task_root}")
            self.save_button.setEnabled(
                bool(item and self.canvas.trajectory.point_count and not self.canvas.pen_down)
            )
            if item:
                info = symbol_info(item.character)
                from .punctuation import capture_label
                from .symbol_catalog import SYMBOL_GROUPS, symbol_group
                style = item_letter_style(self.task, item)
                key = symbol_group(item.character, style)
                label = SYMBOL_GROUPS[key][0] if key in SYMBOL_GROUPS else "英文 · 写法未标注"
                italic = 'italic' if style == 'italic' else 'normal'
                self.target_label.setStyleSheet(f'font-size: 88px; font-weight: 600; font-style: {italic};')
                self.identity_label.setText(
                    f"{capture_label(item.character)} · {label} · {info['codepoint']} · {info['unicode_name']}\n"
                    f"当前 {len(self.canvas.trajectory.strokes)} 笔 · 笔数不限"
                )
            else:
                self.identity_label.clear()
                if self.task and not self.task.items:
                    from .symbol_tasks import source_configuration
                    count = len(source_configuration(self.task.source)['reuse'])
                    if count:
                        self.progress_label.setText(f'已保存 {count} 个字符的复用配置，无待录制字符')

        def skip_current(self):
            if getattr(self, '_capture_catalog', None):
                return CaptureLifecycleMixin.skip_current(self)
            if self._can_switch():
                super().skip_current()
                self.variant_note.clear()

        def save_current(self):
            if self.canvas.pen_down or not self.boundary_guard.allow_save():
                return
            before = self.task.completed_count if self.task else 0
            super().save_current()
            if self.task and self.task.completed_count > before:
                self.variant_note.clear()

    return SymbolWidget


def install_symbol_tab(window, collector_ui, QtCore, QtGui, QtWidgets):
    cls = create_symbol_widget_class(collector_ui, QtCore, QtGui, QtWidgets)
    window.symbol_widget = cls(window.ensure_output_root)
    window.tabs.addTab(window.symbol_widget, "标点与扩展")

    class CloseGuard(QtCore.QObject):
        def eventFilter(self, watched, event):
            if event.type() == QtCore.QEvent.Type.Close:
                if getattr(window.symbol_widget, '_capture_catalog', None):
                    if not all(w._can_switch() for w in (window.single_widget, window.symbol_widget)):
                        event.ignore()
                        return True
                    return False
                canvas = window.symbol_widget.canvas
                if canvas.trajectory.point_count:
                    answer = QtWidgets.QMessageBox.question(
                        window,
                        "符号笔迹尚未保存",
                        "放弃当前未保存的符号笔迹并关闭？",
                        QtWidgets.QMessageBox.StandardButton.Yes
                        | QtWidgets.QMessageBox.StandardButton.No,
                        QtWidgets.QMessageBox.StandardButton.No,
                    )
                    if answer != QtWidgets.QMessageBox.StandardButton.Yes:
                        event.ignore()
                        return True
            return False

    window.symbol_close_guard = CloseGuard(window)
    window.installEventFilter(window.symbol_close_guard)
    # The external collector uses window-wide shortcuts. Scope existing actions so
    # Enter in the symbol tab cannot also save a pending Han sample.
    for action in window.single_widget.actions():
        action.setShortcutContext(QtCore.Qt.ShortcutContext.WidgetWithChildrenShortcut)
