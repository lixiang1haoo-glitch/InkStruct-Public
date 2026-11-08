from __future__ import annotations

import argparse
import threading
from dataclasses import replace
from pathlib import Path

from PySide6 import QtCore, QtGui, QtSvg, QtWidgets

from ..assets.glyph_provider import GlyphProvider
from ..cache import BoundedCache
from ..document.schema import PageProfile, StyleProfile, digest, new_id
from ..document.source import parse_plain_text, scalar_to_utf16, utf16_to_scalar
from ..layout.plain import layout_document
from ..renderers.pages import export_pages, page_svg, preview_key
from .continuous_preview import ContinuousPageCanvas, PreviewScrollArea
from .page_navigation import PageNumberSpinBox
from .review import (
    RATINGS,
    ReviewBook,
    SourceBuffer,
    atomic_write,
    file_hash,
    load_session,
    session_bytes,
)

COLORS = {"good": "#24845c", "bad": "#c34444", "review": "#bb841b"}


class TextEditor(QtWidgets.QPlainTextEdit):
    composition_finished = QtCore.Signal()
    input_transaction = QtCore.Signal(object)

    def __init__(self):
        super().__init__()
        self.composing = False
        self.history_handler = None
        self.ime_active = False

    def undo(self):
        if self.history_handler:
            self.history_handler("undo")
        else:
            super().undo()

    def redo(self):
        if self.history_handler:
            self.history_handler("redo")
        else:
            super().redo()

    def keyPressEvent(self, event):
        if self.history_handler and event.matches(QtGui.QKeySequence.StandardKey.Undo):
            self.undo()
            return
        if self.history_handler and event.matches(QtGui.QKeySequence.StandardKey.Redo):
            self.redo()
            return
        super().keyPressEvent(event)

    def contextMenuEvent(self, event):
        if not self.history_handler:
            return super().contextMenuEvent(event)
        menu = QtWidgets.QMenu(self)
        for title, callback in (
            ("撤销", self.undo),
            ("重做", self.redo),
            ("剪切", self.cut),
            ("复制", self.copy),
            ("粘贴", self.paste),
            ("全选", self.selectAll),
        ):
            menu.addAction(title, callback)
        menu.exec(event.globalPos())

    def inputMethodEvent(self, event):
        cursor = self.textCursor()
        transaction = (
            cursor.selectionStart(),
            cursor.selectionEnd(),
            event.replacementStart(),
            event.replacementLength(),
            event.commitString(),
        )
        self.composing = bool(event.preeditString())
        self.ime_active = True
        try:
            super().inputMethodEvent(event)
        finally:
            self.ime_active = False
        self.input_transaction.emit(transaction)
        if not self.composing:
            self.composition_finished.emit()


class WorkerSignals(QtCore.QObject):
    finished = QtCore.Signal(object)


class LayoutWorker(QtCore.QRunnable):
    def __init__(self, key, revision, document, run, cancelled):
        super().__init__()
        self.signals = WorkerSignals()
        self.key, self.revision, self.document, self.run_path = key, revision, document, run
        self.cancelled = cancelled

    def run(self):
        result = {"key": self.key, "revision": self.revision}
        try:
            if not self.cancelled.is_set():
                provider = GlyphProvider.from_run(self.run_path, self.document.source)
                if not self.cancelled.is_set():
                    snapshot = layout_document(self.document, provider, request_id=self.key)
                    result.update(provider=provider, snapshot=snapshot)
        except Exception as error:  # noqa: BLE001 - worker boundary transports errors to GUI
            result["error"] = str(error)
        self.signals.finished.emit(result)


class PageCanvas(QtWidgets.QWidget):
    selected = QtCore.Signal(object)
    task_activated = QtCore.Signal(object)

    def __init__(self):
        super().__init__()
        self.setObjectName("page_canvas")
        self.snapshot = None
        self.page_index = 0
        self.renderer = QtSvg.QSvgRenderer()
        # Renderers have no QObject parent: LRU eviction must release native data.
        # Access stays on the GUI thread; reviews/selection are painted separately.
        self.preview_cache = BoundedCache(max_entries=4, max_weight=64 * 1024**2)
        self.reviews = {}
        self.selected_id = None
        self.scale = 3.0
        self.show_marks = True
        self.setMinimumSize(300, 400)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)

    def load_page(self, snapshot, index):
        debug = not snapshot.exportable
        key = preview_key(snapshot, index, debug=debug)
        cached = self.preview_cache.get(key)
        if cached is None:
            data = page_svg(snapshot, index, debug=debug).encode()
            renderer = QtSvg.QSvgRenderer(QtCore.QByteArray(data))
            page = snapshot.pages[index]
            weight = len(data) * 4 + len(page.fragments) * 512
            weight += sum(len(op.points) * 128 for op in (*page.paint_ops, *page.preview_ops))
            self.preview_cache.put((key,), renderer, weight)
        else:
            renderer = cached
        self.snapshot, self.page_index, self.renderer = snapshot, index, renderer
        self.resize_page()

    def resize_page(self):
        if self.snapshot:
            profile = self.snapshot.page_profile
            self.setFixedSize(
                round(profile.width_mm * self.scale), round(profile.height_mm * self.scale)
            )
        self.update()

    def rect_for(self, fragment):
        p = self.snapshot.page_profile
        x0, y0, x1, y1 = fragment.selection_bounds
        return QtCore.QRectF(
            x0 * self.width() / p.width_mm,
            y0 * self.height() / p.height_mm,
            (x1 - x0) * self.width() / p.width_mm,
            (y1 - y0) * self.height() / p.height_mm,
        )

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.fillRect(self.rect(), QtGui.QColor("white"))
        if not self.snapshot:
            painter.setPen(QtGui.QColor("#728095"))
            painter.drawText(
                self.rect(),
                QtCore.Qt.AlignmentFlag.AlignCenter,
                "选择生成结果目录，再输入或打开纯文本",
            )
            return
        self.renderer.render(painter, QtCore.QRectF(self.rect()))
        for f in self.snapshot.pages[self.page_index].fragments:
            rect = self.rect_for(f)
            record = self.reviews.get(f.asset_id)
            if record and self.show_marks:
                color = QtGui.QColor(COLORS[record.rating])
                color.setAlpha(30)
                painter.fillRect(rect, color)
                painter.setPen(QtGui.QPen(QtGui.QColor(COLORS[record.rating]), 2))
                painter.drawLine(rect.bottomLeft(), rect.bottomRight())
            if f.status in ("missing", "failed", "unsupported"):
                painter.setPen(QtGui.QColor("#b43d3d"))
                font = painter.font()
                font.setPixelSize(max(9, round(rect.height() * 0.55)))
                painter.setFont(font)
                painter.drawText(rect, QtCore.Qt.AlignmentFlag.AlignCenter, f.text)
            if f.occurrence_id == self.selected_id:
                painter.setPen(QtGui.QPen(QtGui.QColor("#3c6bd9"), 2))
                painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
                painter.drawRect(rect.adjusted(-2, -2, 2, 2))

    def mousePressEvent(self, event):
        if not self.snapshot or not self.isEnabled():
            return
        for f in self.snapshot.pages[self.page_index].fragments:
            if f.status not in ("space", "line-break") and self.rect_for(f).contains(
                event.position()
            ):
                self.selected.emit(f)
                if event.button() == QtCore.Qt.MouseButton.LeftButton and f.status in {
                    "task-checked",
                    "task-unchecked",
                }:
                    self.task_activated.emit(f)
                return


class GlyphInspector(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.asset = None
        self.relative_width = 0.05
        self.setFixedSize(154, 154)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QtGui.QColor("white"))
        painter.setPen(QtGui.QPen(QtGui.QColor("#d7dde5"), 1))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))
        if not self.asset:
            painter.drawText(self.rect(), QtCore.Qt.AlignmentFlag.AlignCenter, "字形放大查看")
            return
        pen = QtGui.QPen(QtGui.QColor("#111827"), self.relative_width * 128)
        pen.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(QtCore.Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        for stroke in self.asset.strokes:
            points = [
                QtCore.QPointF(
                    13 + (p[0] if isinstance(p, tuple) else p.x) * 128,
                    13 + (p[1] if isinstance(p, tuple) else p.y) * 128,
                )
                for p in stroke
            ]
            if len(points) == 1:
                painter.drawPoint(points[0])
            else:
                painter.drawPolyline(QtGui.QPolygonF(points))


class ReviewWindow(QtWidgets.QMainWindow):
    def __init__(self, *, source="", run=None, parent=None):
        super().__init__(parent)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowFlag(QtCore.Qt.WindowType.Window, True)
        self.setWindowTitle("InkStruct · 纯文本字形检查")
        self.resize(1340, 880)
        self.buffer = SourceBuffer(source)
        self.run_path = str(Path(run).resolve()) if run else ""
        self.page = PageProfile()
        self.book = ReviewBook()
        self.snapshot = self.provider = self.selected_fragment = None
        self.document_id = new_id()
        self.revision = 0
        self.current_key = None
        self.worker = None
        self.cancelled = None
        self.closed = False
        self.dirty = False
        self.session_path = None
        self.session_hash = None
        self._syncing = False
        self.pool = QtCore.QThreadPool.globalInstance()
        self.timer = QtCore.QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(280)
        self.timer.timeout.connect(self.launch_layout)
        self._build_ui()
        self.editor.setPlainText(self.buffer.display)
        self.editor.textChanged.connect(self.text_changed)
        self.editor.composition_finished.connect(self.schedule_layout)
        self.editor.cursorPositionChanged.connect(self.source_selected)
        self.schedule_layout()

    def button(self, title, callback, layout, name=None):
        button = QtWidgets.QPushButton(title)
        if name:
            button.setObjectName(name)
        button.clicked.connect(callback)
        layout.addWidget(button)
        return button

    def _build_ui(self):
        body = QtWidgets.QWidget()
        self.setCentralWidget(body)
        layout = QtWidgets.QVBoxLayout(body)
        toolbar = QtWidgets.QHBoxLayout()
        self.button("打开文本…", self.open_text, toolbar)
        self.button("保存文本…", self.save_text, toolbar)
        self.button("选择字形目录…", self.choose_run, toolbar, "choose_run")
        self.button("刷新字形", self.refresh_assets, toolbar)
        self.button("载入全部字", self.load_all, toolbar)
        toolbar.addStretch()
        self.button("打开检查项目…", self.open_project, toolbar)
        self.button("保存检查项目", self.save_project, toolbar, "save_project")
        self.button("另存项目…", self.save_project_as, toolbar)
        self.button("导出评价 CSV…", self.export_csv, toolbar)
        layout.addLayout(toolbar)
        self.run_label = QtWidgets.QLabel()
        self.run_label.setWordWrap(True)
        self.run_label.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        self.run_label.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.run_label)
        options = QtWidgets.QHBoxLayout()
        options.addWidget(QtWidgets.QLabel("字大小 mm"))
        self.em = QtWidgets.QDoubleSpinBox()
        self.em.setRange(2, 20)
        self.em.setValue(6)
        self.em.setSingleStep(0.5)
        self.em.valueChanged.connect(self.settings_changed)
        options.addWidget(self.em)
        options.addWidget(QtWidgets.QLabel("行高 mm"))
        self.line_height = QtWidgets.QDoubleSpinBox()
        self.line_height.setRange(3, 30)
        self.line_height.setValue(9)
        self.line_height.valueChanged.connect(self.settings_changed)
        options.addWidget(self.line_height)
        options.addWidget(QtWidgets.QLabel("笔宽 mm"))
        self.stroke = QtWidgets.QDoubleSpinBox()
        self.stroke.setRange(0.05, 1)
        self.stroke.setSingleStep(0.05)
        self.stroke.setValue(0.3)
        self.stroke.valueChanged.connect(self.settings_changed)
        options.addWidget(self.stroke)
        options.addStretch()
        self.show_marks = QtWidgets.QCheckBox("显示评价色标")
        self.show_marks.setChecked(True)
        self.show_marks.toggled.connect(self.toggle_marks)
        options.addWidget(self.show_marks)
        self.page_export = self.button("导出页面…", self.export_document, options)
        layout.addLayout(options)
        split = QtWidgets.QSplitter()
        layout.addWidget(split, 1)
        left = QtWidgets.QWidget()
        left_layout = QtWidgets.QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QtWidgets.QLabel("纯文本正文"))
        self.editor = TextEditor()
        self.editor.setObjectName("source_editor")
        self.editor.setPlaceholderText("输入或粘贴正文。也可载入目录中的全部字，逐字检查。")
        self.editor.setStyleSheet("QPlainTextEdit {font-size: 16px; padding: 10px;}")
        left_layout.addWidget(self.editor, 3)
        review_title = QtWidgets.QHBoxLayout()
        review_title.addWidget(QtWidgets.QLabel("当前正文中的字形"))
        self.filter = QtWidgets.QComboBox()
        for label, key in [
            ("全部", "all"),
            ("不好", "bad"),
            ("待复核", "review"),
            ("好", "good"),
            ("未标注", "unrated"),
            ("缺失 / 失败", "missing"),
        ]:
            self.filter.addItem(label, key)
        self.filter.currentIndexChanged.connect(self.refresh_list)
        review_title.addWidget(self.filter)
        left_layout.addLayout(review_title)
        self.glyph_list = QtWidgets.QListWidget()
        self.glyph_list.setObjectName("glyph_list")
        self.glyph_list.itemClicked.connect(self.list_selected)
        left_layout.addWidget(self.glyph_list, 2)
        self.summary = QtWidgets.QLabel("尚未载入字形")
        self.summary.setWordWrap(True)
        left_layout.addWidget(self.summary)
        split.addWidget(left)
        right = QtWidgets.QWidget()
        right_layout = QtWidgets.QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        nav = QtWidgets.QHBoxLayout()
        self.page_picker = PageNumberSpinBox()
        self.page_picker.setObjectName("page_picker")
        self.page_picker.setMinimum(1)
        self.page_picker.setPrefix("第 ")
        self.page_picker.valueChanged.connect(self.change_page)
        nav.addWidget(self.page_picker)
        self.zoom = QtWidgets.QComboBox()
        for label, scale in [("75%", 2.25), ("100%", 3.0), ("150%", 4.5), ("200%", 6.0)]:
            self.zoom.addItem(label, scale)
        self.zoom.setCurrentIndex(1)
        self.zoom.setToolTip("在页面预览区按住 Ctrl 滚动可缩放")
        self.zoom.currentIndexChanged.connect(self.zoom_changed)
        nav.addWidget(self.zoom)
        nav.addStretch()
        self.next_button = self.button("下一未评字 →", self.next_unrated, nav)
        right_layout.addLayout(nav)
        self.canvas = ContinuousPageCanvas()
        self.canvas.selected.connect(self.select_fragment)
        self.scroll = PreviewScrollArea()
        self.scroll.zoom_requested.connect(self.preview_zoom_wheel)
        self.scroll.setObjectName("page_scroll")
        self.scroll.setWidget(self.canvas)
        self.scroll.setAlignment(QtCore.Qt.AlignmentFlag.AlignHCenter)
        self.scroll.setStyleSheet("QScrollArea {background: #e7ebf0; border: 1px solid #d7dde5;}")
        self.scroll.verticalScrollBar().valueChanged.connect(self.preview_scrolled)
        self.scroll.horizontalScrollBar().valueChanged.connect(self.preview_scrolled)
        right_layout.addWidget(self.scroll, 1)
        inspect_row = QtWidgets.QHBoxLayout()
        self.inspector = GlyphInspector()
        inspect_row.addWidget(self.inspector)
        details = QtWidgets.QVBoxLayout()
        inspect_row.addLayout(details, 1)
        right_layout.addLayout(inspect_row)
        self.selection_label = QtWidgets.QLabel("点击页面中的字，记录你的判断")
        self.selection_label.setWordWrap(True)
        self.selection_label.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        details.addWidget(self.selection_label)
        ratings = QtWidgets.QHBoxLayout()
        self.rating_buttons = []
        for key, title in RATINGS.items():
            button = self.button(
                title, lambda checked=False, k=key: self.rate(k), ratings, "rate_" + key
            )
            button.setStyleSheet(
                f"QPushButton {{ color: {COLORS[key]}; font-weight: bold; }}"
                "QPushButton:disabled {color: #a0a8b2;}"
            )
            self.rating_buttons.append(button)
        self.rating_buttons.append(self.button("清除评价", lambda: self.rate(None), ratings))
        self.button("撤销标记", self.undo_rating, ratings)
        self.button("重做标记", self.redo_rating, ratings)
        details.addLayout(ratings)
        note_row = QtWidgets.QHBoxLayout()
        self.note = QtWidgets.QLineEdit()
        self.note.setObjectName("review_note")
        self.note.setPlaceholderText("问题备注，例如：右部偏大、折钩丢失、笔画挤在一起")
        self.note.textEdited.connect(self.note_changed)
        note_row.addWidget(self.note)
        details.addLayout(note_row)
        split.addWidget(right)
        split.setSizes([400, 900])
        self.status = QtWidgets.QLabel("选择已有生成结果即可开始检查")
        self.status.setWordWrap(True)
        self.status.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        self.set_ready(False)

    @property
    def style(self):
        return StyleProfile(self.em.value(), self.line_height.value(), self.stroke.value())

    def mark_dirty(self):
        self.dirty = True
        self.setWindowTitle("InkStruct · 纯文本字形检查 *")

    def text_changed(self):
        if self.editor.toPlainText() == self.buffer.display:
            return
        self.buffer.update(self.editor.toPlainText())
        self.mark_dirty()
        self.schedule_layout()

    def settings_changed(self):
        self.mark_dirty()
        self.schedule_layout()

    def set_ready(self, ready):
        self.canvas.setEnabled(ready)
        self.glyph_list.setEnabled(ready)
        self.page_export.setEnabled(bool(ready and self.snapshot and self.snapshot.exportable))
        self.next_button.setEnabled(ready)
        for button in self.rating_buttons:
            button.setEnabled(
                bool(ready and self.selected_fragment and self.selected_fragment.asset_id)
            )
        self.note.setEnabled(
            bool(ready and self.selected_fragment and self.selected_fragment.asset_id)
        )

    def schedule_layout(self):
        self.revision += 1
        self.current_key = None
        if self.cancelled:
            self.cancelled.set()
        self.set_ready(False)
        self.run_label.setText("字形目录：" + (self.run_path or "未选择"))
        self.status.setText(
            "正在更新预览…旧页面暂不可标记" if self.run_path else "请先选择生成结果目录"
        )
        if not self.editor.composing:
            self.timer.start()

    def refresh_assets(self):
        self.schedule_layout()

    def launch_layout(self):
        if self.closed or self.editor.composing or self.worker or not self.run_path:
            return
        if len(self.buffer.raw) > 100_000:
            self.status.setText("正文超过十万字符限制，请分批检查。")
            return
        document = replace(
            parse_plain_text(self.buffer.raw, page=self.page, style=self.style),
            document_id=self.document_id,
            revision=self.revision,
        )
        key = digest(
            {
                "revision": self.revision,
                "source": document.source,
                "run": self.run_path,
                "style": repr(self.style),
                "page": repr(self.page),
            }
        )
        self.current_key = key
        self.cancelled = threading.Event()
        self.worker = LayoutWorker(
            key, self.revision, document, Path(self.run_path), self.cancelled
        )
        self.worker.signals.finished.connect(self.publish)
        self.pool.start(self.worker)

    @QtCore.Slot(object)
    def publish(self, result):
        self.worker = None
        if self.closed:
            return
        if result["revision"] != self.revision or result["key"] != self.current_key:
            if not self.editor.composing:
                self.timer.start(0)
            return
        if "error" in result:
            self.status.setText("预览失败：" + result["error"])
            return
        if "snapshot" not in result:
            return
        self.snapshot, self.provider = result["snapshot"], result["provider"]
        self.selected_fragment = None
        self.inspector.asset = None
        self.inspector.update()
        self.canvas.selected_id = None
        old_page = self.page_picker.value()
        with QtCore.QSignalBlocker(self.page_picker):
            self.page_picker.setMaximum(len(self.snapshot.pages))
            self.page_picker.setSuffix(f" / {len(self.snapshot.pages)} 页")
            self.page_picker.setValue(min(old_page, len(self.snapshot.pages)))
        self.canvas.reviews = self.book.records
        # A fresh layout replaces display data without resetting the reader's
        # continuous scroll position. Explicit page navigation is separate.
        self.canvas.load_page(self.snapshot, self.page_picker.value() - 1)
        self.refresh_list()
        self.set_ready(True)
        self.note.clear()
        self.selection_label.setText("点击页面中的字，记录你的判断（同一字形的重复字共享评价）")
        issues = self.snapshot.diagnostics
        self.status.setText(
            f"{len(self.snapshot.pages)} 页 · {len(self.snapshot.fragments)} 个文本实例 · "
            + (
                "预览已更新"
                if not issues
                else f"{len(issues)} 项提示，预览已更新，可查看诊断详情。"
                if self.snapshot.exportable
                else f"{len(issues)} 项缺字或排版问题，成品导出不可用；已有字形仍可检查。"
            )
        )

    def change_page(self, *_):
        if self.snapshot:
            index = self.page_picker.value() - 1
            if self.canvas.snapshot is not self.snapshot:
                self.canvas.load_page(self.snapshot, index)
            self.canvas.page_index = index
            self.scroll.verticalScrollBar().setValue(
                max(0, round(self.canvas.page_rect(index).top()) - self.canvas.margin)
            )
            self.canvas.viewport_changed()

    def preview_scrolled(self, *_):
        if self.canvas.snapshot:
            self.canvas.viewport_changed()
            index = self.canvas.page_at(self.canvas.viewport_rect().center().y())
            self.canvas.page_index = index
            with QtCore.QSignalBlocker(self.page_picker):
                self.page_picker.setValue(index + 1)

    def preview_zoom_wheel(self, steps, position):
        index = max(0, min(self.zoom.count() - 1, self.zoom.currentIndex() + steps))
        if index != self.zoom.currentIndex():
            with QtCore.QSignalBlocker(self.zoom):
                self.zoom.setCurrentIndex(index)
            self.zoom_changed(position=position)

    def zoom_changed(self, *, position=None):
        anchor = None
        if self.canvas.snapshot:
            visible = self.canvas.viewport_rect()
            point = visible.topLeft() + position if position is not None else visible.topLeft()
            index = self.canvas.page_at(point.y())
            page = self.canvas.page_rect(index)
            horizontal = ((point.x() - page.left()) if position is not None else
                          self.scroll.horizontalScrollBar().value()) / page.width()
            anchor = (index, (point.y() - page.top()) / page.height(), horizontal)
        self.canvas.scale = self.zoom.currentData()
        self.canvas.resize_page()
        if anchor:
            index, fraction, horizontal = anchor
            page = self.canvas.page_rect(index)
            x, y = horizontal * page.width(), page.top() + fraction * page.height()
            if position is not None:
                x += page.left() - position.x()
                y -= position.y()
            self.scroll.verticalScrollBar().setValue(round(y))
            self.scroll.horizontalScrollBar().setValue(round(x))
        self.preview_scrolled()

    def toggle_marks(self, value):
        self.canvas.show_marks = value
        self.canvas.update()

    def asset_for_fragment(self, fragment):
        return self.provider.assets.get(fragment.text) if fragment.asset_id else None

    def select_fragment(self, fragment, *, sync_source=True):
        if not self.canvas.isEnabled():
            return
        self.selected_fragment = fragment
        self.canvas.selected_id = fragment.occurrence_id
        with QtCore.QSignalBlocker(self.page_picker):
            self.page_picker.setValue(fragment.page_index + 1)
        self.canvas.page_index = fragment.page_index
        self.canvas.update()
        rect = self.canvas.rect_for(fragment)
        self.scroll.ensureVisible(round(rect.center().x()), round(rect.center().y()), 40, 40)
        record = self.book.records.get(fragment.asset_id)
        self.inspector.asset = self.asset_for_fragment(fragment)
        self.inspector.relative_width = self.style.stroke_width_mm / self.style.em_mm
        self.inspector.update()
        self.note.setText(record.note if record else "")
        rating = RATINGS[record.rating] if record else "未标注"
        if fragment.asset_id:
            self.selection_label.setText(
                f"选中「{fragment.text}」 · {rating} · 字形 {fragment.asset_id[:10]}"
            )
        elif fragment.status in {"task-checked", "task-unchecked"}:
            self.selection_label.setText("任务复选框 · 点击切换源码状态，可撤销")
        elif fragment.status in {"image-reference", "image-missing", "image-vector"}:
            self.selection_label.setText(
                "选中单线 SVG · 可写字机导出，使用文档笔宽"
                if fragment.status == "image-vector"
                else "选中图片 · 仅供参考预览，不能导出到写字机"
                if fragment.status == "image-reference"
                else "选中图片 · 缺少文件，请从图片设置导入"
            )
        else:
            self.selection_label.setText(
                f"「{fragment.text}」没有可评价的字形（{fragment.status}）"
            )
        self.set_ready(True)
        if sync_source:
            self._syncing = True
            start = self.buffer.raw_to_display(fragment.span.start)
            end = self.buffer.raw_to_display(fragment.span.end)
            cursor = self.editor.textCursor()
            cursor.setPosition(scalar_to_utf16(self.buffer.display, start))
            cursor.setPosition(
                scalar_to_utf16(self.buffer.display, end), QtGui.QTextCursor.MoveMode.KeepAnchor
            )
            self.editor.setTextCursor(cursor)
            self.editor.ensureCursorVisible()
            self._syncing = False

    def source_selected(self):
        if self._syncing or not self.snapshot or not self.canvas.isEnabled():
            return
        try:
            index = utf16_to_scalar(self.buffer.display, self.editor.textCursor().selectionStart())
            raw = self.buffer.boundaries()[index]
        except (ValueError, IndexError):
            return
        for f in self.snapshot.fragments:
            if f.span.start <= raw < f.span.end and f.status not in ("space", "line-break"):
                self.select_fragment(f, sync_source=False)
                return

    def rate(self, rating):
        f = self.selected_fragment
        if not f or not f.asset_id or not self.canvas.isEnabled():
            return
        self.book.set(
            self.asset_for_fragment(f),
            rating,
            self.note.text(),
            Path(self.run_path),
            self.buffer.raw,
            f.span.start,
        )
        self.mark_dirty()
        self.refresh_list()
        self.select_fragment(f, sync_source=False)

    def note_changed(self):
        f = self.selected_fragment
        if f and f.asset_id and self.canvas.isEnabled():
            record = self.book.records.get(f.asset_id)
            # Notes on a previously unrated glyph create a visible "needs review" record.
            self.book.set(
                self.asset_for_fragment(f),
                record.rating if record else "review",
                self.note.text(),
                Path(self.run_path),
                self.buffer.raw,
                f.span.start,
            )
            self.mark_dirty()
            self.refresh_list()
            self.selection_label.setText(
                f"选中「{f.text}」 · {RATINGS[self.book.records[f.asset_id].rating]}"
                f" · 字形 {f.asset_id[:10]}"
            )

    def undo_rating(self):
        if self.book.undo_stack:
            self.book.undo()
            self.review_changed()

    def redo_rating(self):
        if self.book.redo_stack:
            self.book.redo()
            self.review_changed()

    def review_changed(self):
        self.mark_dirty()
        self.refresh_list()
        self.canvas.update()
        if self.selected_fragment:
            self.select_fragment(self.selected_fragment, sync_source=False)

    def refresh_list(self, *_):
        self.glyph_list.clear()
        if not self.snapshot:
            return
        counts = dict.fromkeys(["good", "bad", "review", "unrated", "missing"], 0)
        seen, present = set(), set()
        for f in self.snapshot.fragments:
            if f.status in (
                "space",
                "line-break",
                "image-reference",
                "image-missing",
                "image-vector",
                "task-checked",
                "task-unchecked",
            ):
                continue
            key = f.asset_id or ("missing", f.text)
            if key in seen:
                continue
            seen.add(key)
            if f.asset_id:
                present.add(f.asset_id)
            record = self.book.records.get(f.asset_id)
            kind = record.rating if record else "unrated" if f.asset_id else "missing"
            counts[kind] += 1
            if self.filter.currentData() not in ("all", kind):
                continue
            label = RATINGS.get(kind, "未标注" if kind == "unrated" else "缺失 / 失败")
            item = QtWidgets.QListWidgetItem(
                f"{f.text}    {label}" + (f" · {record.note}" if record and record.note else "")
            )
            item.setData(QtCore.Qt.ItemDataRole.UserRole, f)
            if kind in COLORS:
                item.setForeground(QtGui.QColor(COLORS[kind]))
            self.glyph_list.addItem(item)
        retained = len(set(self.book.records) - present)
        self.summary.setText(
            f"好 {counts['good']} · 不好 {counts['bad']} · 待复核 {counts['review']}\n"
            f"未标注 {counts['unrated']} · 缺失 {counts['missing']}"
            + (f"\n另保留 {retained} 个不在当前正文/版本中的评价" if retained else "")
        )
        self.canvas.update()

    def list_selected(self, item):
        self.select_fragment(item.data(QtCore.Qt.ItemDataRole.UserRole))

    def next_unrated(self):
        if not self.snapshot or not self.canvas.isEnabled():
            return
        fragments = self.snapshot.fragments
        start = next(
            (
                i + 1
                for i, f in enumerate(fragments)
                if self.selected_fragment
                and f.occurrence_id == self.selected_fragment.occurrence_id
            ),
            0,
        )
        for f in fragments[start:] + fragments[:start]:
            if f.asset_id and f.asset_id not in self.book.records:
                self.select_fragment(f)
                return
        self.status.setText("当前正文中的可用字形已全部评价。")

    def message_error(self, error):
        QtWidgets.QMessageBox.critical(self, "操作未完成", str(error))

    def replace_text(self, source):
        self.buffer = SourceBuffer(source)
        with QtCore.QSignalBlocker(self.editor):
            self.editor.setPlainText(self.buffer.display)
        self.mark_dirty()
        self.schedule_layout()

    def open_text(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "打开纯文本", "", "文本 (*.txt);;所有文件 (*)"
        )
        if path:
            try:
                p = Path(path)
                if p.stat().st_size > 2 * 1024 * 1024:
                    raise ValueError("正文超过 2 MiB 限制")
                source = p.read_bytes().decode("utf-8")
                if len(source) > 100_000:
                    raise ValueError("正文超过十万字符限制")
                self.editor.selectAll()
                self.editor.insertPlainText(source.replace("\r\n", "\n").replace("\r", "\n"))
                self.buffer = SourceBuffer(source)
                self.mark_dirty()
                self.schedule_layout()
            except (OSError, ValueError) as error:
                self.message_error(error)

    def choose_run(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(
            self, "选择包含 trajectories 子文件夹的生成结果目录", self.run_path
        )
        if path:
            self.set_run(path)

    def set_run(self, path):
        self.run_path = str(Path(path).resolve())
        self.mark_dirty()
        self.schedule_layout()

    def load_all(self):
        if not self.run_path:
            self.status.setText("请先选择生成结果目录。")
            return
        try:
            chars = []
            for path in sorted((Path(self.run_path) / "trajectories").glob("U+*.json")):
                try:
                    char = chr(int(path.stem.removeprefix("U+"), 16))
                    char.encode("utf-8")
                    chars.append(char)
                except (ValueError, UnicodeError):
                    continue
            if not chars:
                raise ValueError("此目录没有可识别的单字轨迹文件")
            # One undoable source edit; keep all prior asset reviews.
            self.editor.selectAll()
            self.editor.insertPlainText("".join(chars[:100_000]))
        except (OSError, ValueError) as error:
            self.message_error(error)

    def save_project(self):
        path = self.session_path
        if not path:
            selected, _ = QtWidgets.QFileDialog.getSaveFileName(
                self, "保存检查项目", "检查项目.inkreview", "检查项目 (*.inkreview)"
            )
            if not selected:
                return False
            path = Path(selected)
            expected = file_hash(path)
        else:
            expected = self.session_hash
        try:
            data = session_bytes(self.buffer.raw, self.run_path, self.book, self.page, self.style)
            self.session_hash = atomic_write(path, data, expected)
            self.session_path = path
            self.dirty = False
            self.setWindowTitle("InkStruct · 纯文本字形检查")
            self.status.setText(f"检查项目已保存：{path}")
            return True
        except (OSError, ValueError) as error:
            self.message_error(error)
            return False

    def confirm_discard(self):
        if not self.dirty:
            return True
        buttons = QtWidgets.QMessageBox.StandardButton
        result = QtWidgets.QMessageBox.question(
            self,
            "保存检查项目",
            "正文或评价尚未保存。是否保存后继续？",
            buttons.Save | buttons.Discard | buttons.Cancel,
            buttons.Save,
        )
        if result == buttons.Save:
            return self.save_project()
        return result == buttons.Discard

    def save_project_as(self):
        old_path, old_hash = self.session_path, self.session_hash
        self.session_path, self.session_hash = None, None
        if not self.save_project():
            self.session_path, self.session_hash = old_path, old_hash

    def open_project(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "打开检查项目", "", "检查项目 (*.inkreview)"
        )
        if path and self.confirm_discard():
            try:
                expected = file_hash(Path(path))
                buffer, run, book, page, style = load_session(Path(path))
                if file_hash(Path(path)) != expected:
                    raise ValueError("读取期间检查项目发生变化，请重新打开。")
                self.buffer, self.run_path, self.book, self.page = buffer, run, book, page
                with QtCore.QSignalBlocker(self.editor):
                    self.editor.setPlainText(buffer.display)
                for control, value in [
                    (self.em, style.em_mm),
                    (self.stroke, style.stroke_width_mm),
                    (self.line_height, style.line_height_mm),
                ]:
                    with QtCore.QSignalBlocker(control):
                        control.setValue(value)
                self.session_path, self.session_hash = Path(path), expected
                self.dirty = False
                self.setWindowTitle("InkStruct · 纯文本字形检查")
                self.schedule_layout()
            except (OSError, ValueError, KeyError, TypeError) as error:
                self.message_error(error)

    def save_text(self):
        selected, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "另存纯文本", "正文.txt", "文本 (*.txt)"
        )
        if selected:
            try:
                path = Path(selected)
                atomic_write(path, self.buffer.raw.encode(), file_hash(path))
                self.status.setText("正文已保存；评价请另存检查项目。")
            except (OSError, ValueError) as error:
                self.message_error(error)

    def export_csv(self):
        selected, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "导出全部评价", "字形评价.csv", "CSV (*.csv)"
        )
        if selected:
            try:
                path = Path(selected)
                atomic_write(path, self.book.csv_bytes(), file_hash(path))
                self.status.setText("评价已导出，含所有已记录版本及来源；不修改字形资产。")
            except (OSError, ValueError) as error:
                self.message_error(error)

    def export_document(self):
        if not self.snapshot or not self.canvas.isEnabled() or not self.snapshot.exportable:
            return
        snapshot = self.snapshot
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "指定新的页面输出文件夹")
        if path:
            try:
                export_pages(snapshot, Path(path))
                self.status.setText("页面已导出；选择框和评价色标不写入成品。")
            except (OSError, ValueError) as error:
                self.message_error(error)

    def closeEvent(self, event):
        if not self.confirm_discard():
            event.ignore()
            return
        self.closed = True
        self.timer.stop()
        self.canvas.stop_rendering()
        if self.cancelled:
            self.cancelled.set()
        event.accept()


def main(argv=None):
    parser = argparse.ArgumentParser(description="InkStruct Markdown 排版与字形检查")
    parser.add_argument("--source", type=Path)
    parser.add_argument("--run", type=Path)
    parser.add_argument("--symbols", type=Path)
    parser.add_argument("--project", type=Path)
    parser.add_argument("--mode", choices=("plain-text", "markdown"), default="markdown")
    parser.add_argument("--smoke-screenshot", type=Path)
    args = parser.parse_args(argv)
    if args.project and any((args.source, args.run, args.symbols)):
        parser.error("--project 使用项目内保存的源码与资源，不能同时指定 --source/--run/--symbols")
    if args.source and args.source.stat().st_size > 2 * 1024 * 1024:
        parser.error("正文超过 2 MiB 限制")
    source = args.source.read_bytes().decode("utf-8") if args.source else ""
    if len(source) > 100_000:
        parser.error("正文超过十万字符限制")
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from ..theme import use_light_theme
    use_light_theme(application)
    from .mixed import MixedWindow

    window = MixedWindow(source=source, run=args.run, symbols=args.symbols, mode=args.mode)
    if args.project:
        try:
            window.load_project_path(args.project)
        except (ValueError, OSError) as error:
            parser.error(str(error))
    window.show()
    if args.smoke_screenshot:

        def capture():
            if window.worker or window.timer.isActive():
                QtCore.QTimer.singleShot(100, capture)
                return
            args.smoke_screenshot.parent.mkdir(parents=True, exist_ok=True)
            window.grab().save(str(args.smoke_screenshot))
            window.dirty = False
            window.close()
            application.quit()

        QtCore.QTimer.singleShot(400, capture)
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
