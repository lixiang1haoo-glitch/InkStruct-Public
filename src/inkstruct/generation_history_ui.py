"""Non-modal batch history and read-only inspection of candidate ink."""

from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from .fonts.publication import STATUS
from .generation_history import (
    RECORD_ERRORS,
    Recording,
    SourceArchive,
    batch_history,
    character_query,
    inspect_candidates,
)
from .sample_preview import InkViewport, SampleView


class HistorySignals(QtCore.QObject):
    finished = QtCore.Signal(str, int, object, str)


class HistoryRead(QtCore.QRunnable):
    def __init__(self, key, revision, read):
        super().__init__()
        self.key, self.revision, self.read = key, revision, read
        self.signals = HistorySignals()

    def run(self):
        try:
            value = self.read()
        except RECORD_ERRORS as error:
            self.signals.finished.emit(self.key, self.revision, None, str(error) or type(error).__name__)
        else:
            self.signals.finished.emit(self.key, self.revision, value, "")


class StrokePreview(InkViewport):
    stroke_selected = QtCore.Signal(int)

    def __init__(self, view, description, *, interactive=False):
        super().__init__(view)
        self.setAccessibleName(description)
        self.setMinimumSize(105, 98)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Expanding)
        self.interactive = interactive
        self.selected = -1
        self.paths, self.colors = [], ()

    def set_ink(self, strokes=(), colors=()):
        self.colors, self.selected = colors, -1
        self.paths = []
        for stroke in strokes:
            if not stroke:
                self.paths.append(None)
                continue
            path = QtGui.QPainterPath(QtCore.QPointF(*stroke[0]))
            for x, y in stroke[1:]:
                path.lineTo(x, y)
            self.paths.append(path)
        self.press_position = self.drag_position = None
        self.view_changed()

    def has_ink(self):
        return any(path is not None for path in self.paths)

    def select(self, stroke):
        self.selected = stroke
        self.update()

    def display_path(self, index):
        path = self.paths[index]
        return self.drawing_transform().map(path) if path is not None else None

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        palette = self.palette()
        painter.fillRect(self.rect(), palette.base())
        transform = self.drawing_transform()
        box = transform.mapRect(self.view.bounds)
        guide = palette.text().color()
        guide.setAlpha(54)
        painter.setPen(QtGui.QPen(guide, 1))
        painter.drawRect(box)
        guide.setAlpha(30)
        painter.setPen(QtGui.QPen(guide, 1))
        x, y = box.center().x(), box.center().y()
        painter.drawLine(QtCore.QLineF(box.left(), y, box.right(), y))
        painter.drawLine(QtCore.QLineF(x, box.top(), x, box.bottom()))
        order = sorted(range(len(self.paths)), key=lambda i: i == self.selected)
        for i in order:
            path = self.paths[i]
            if path is None:
                continue
            accent = self.colors[i]
            color = QtGui.QColor(accent or palette.text().color())
            if accent is None:
                color.setAlpha(130)
            width = 4 if i == self.selected else 2 if accent else 1.4
            painter.setPen(QtGui.QPen(color, width, QtCore.Qt.PenStyle.SolidLine,
                                      QtCore.Qt.PenCapStyle.RoundCap, QtCore.Qt.PenJoinStyle.RoundJoin))
            if path.isEmpty():
                painter.drawPoint(transform.map(path.currentPosition()))
            else:
                painter.drawPath(transform.map(path))

    def ink_clicked(self, position):
        if not self.interactive:
            return
        paths = [self.display_path(i) for i in range(len(self.paths))]
        for width in (5, 11, 19):
            stroker = QtGui.QPainterPathStroker()
            stroker.setWidth(width)
            for i, path in enumerate(paths):
                if path is None:
                    continue
                if path.isEmpty():
                    delta = position - path.currentPosition()
                    hit = delta.x() ** 2 + delta.y() ** 2 <= (width / 2) ** 2
                else:
                    hit = stroker.createStroke(path).contains(position)
                if hit:
                    self.stroke_selected.emit(i)
                    return


class SourceCard(QtWidgets.QFrame):
    def __init__(self, view, index, source, recording, raw_orders, color):
        super().__init__()
        self.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(5, 4, 5, 4)
        layout.setSpacing(3)
        identity = source.sample or source.digest or "样本编号未记录"
        character = source.character or "源字未记录"
        self.button = QtWidgets.QToolButton()
        self.button.setText(f"{character} · 样本 {index}")
        self.button.setCheckable(True)
        self.button.setToolTip(f"{character} · {identity}\n{recording.status}")
        self.button.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed)
        layout.addWidget(self.button)
        self.preview = StrokePreview(view, f"{character}的源录制笔迹")
        strokes = recording.framed_strokes()
        if strokes:
            self.preview.setFixedHeight(108)
            self.preview.set_ink(strokes, [color if i in raw_orders else None for i in range(1, len(strokes) + 1)])
            layout.addWidget(self.preview)
            text = "原笔序 " + "、".join(map(str, sorted(raw_orders))) if raw_orders else "原笔序未记录"
            if recording.status != "原录制":
                text = "索引笔迹 · " + text
        else:
            empty = QtWidgets.QLabel("原录制不可用")
            empty.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            empty.setMinimumHeight(108)
            layout.addWidget(empty)
            text = "批次来源记录"
        note = QtWidgets.QLabel(text)
        note.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        note.setWordWrap(True)
        note.setToolTip(recording.status)
        layout.addWidget(note)

    def select(self, active, raw_order=None):
        self.button.setChecked(active)
        self.preview.select(raw_order - 1 if raw_order else -1)


def table(columns):
    widget = QtWidgets.QTableWidget(0, len(columns))
    widget.setHorizontalHeaderLabels(columns)
    widget.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
    widget.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
    widget.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
    widget.verticalHeader().hide()
    widget.setAlternatingRowColors(True)
    widget.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
    widget.horizontalHeader().setStretchLastSection(True)
    return widget


def fill_table(widget, rows):
    with QtCore.QSignalBlocker(widget):
        widget.clearContents()
        widget.setRowCount(len(rows))
        for row, values in enumerate(rows):
            for column, value in enumerate(values):
                item = QtWidgets.QTableWidgetItem(str(value))
                item.setToolTip(str(value))
                widget.setItem(row, column, item)


class GenerationHistoryDialog(QtWidgets.QDialog):
    publish_requested = QtCore.Signal(object, str)

    def __init__(self, generation_root, capture_root, writer, parent=None, *, can_publish=True):
        super().__init__(parent)
        self.setWindowTitle("历史生成结果")
        available = self.screen().availableGeometry()
        self.resize(min(1320, available.width() - 40), min(740, available.height() - 72))
        self.root = Path(generation_root)
        self.capture = Path(capture_root)
        self.revisions = {}
        self.readers = {}
        self.batches = self.visible = self.characters = self.candidates = []
        self.batch = self.archive = None
        self.strokes, self.recordings, self.source_cards = (), {}, {}
        self.version = ""
        self.default_writer = writer
        self.view = SampleView(self)
        self.view.bounds = QtCore.QRectF(0, 0, 1, 1)
        self.view.reset()

        layout = QtWidgets.QVBoxLayout(self)
        splitter = QtWidgets.QSplitter()
        splitter.setChildrenCollapsible(False)
        layout.addWidget(splitter, 1)
        left = QtWidgets.QWidget()
        left_layout = QtWidgets.QVBoxLayout(left)
        batch_title = QtWidgets.QHBoxLayout()
        batch_title.addWidget(QtWidgets.QLabel("历史批次"), 1)
        self.writers = QtWidgets.QComboBox()
        self.writers.setAccessibleName("按书写者筛选批次")
        self.writers.setSizeAdjustPolicy(QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.writers.setMinimumContentsLength(10)
        refresh = QtWidgets.QPushButton("刷新")
        refresh.clicked.connect(lambda: self.reload(self.writers.currentData() or ""))
        batch_title.addWidget(refresh)
        left_layout.addLayout(batch_title)
        left_layout.addWidget(self.writers)
        self.batch_list = QtWidgets.QListWidget()
        self.batch_list.setAccessibleName("生成批次")
        self.batch_list.setUniformItemSizes(True)
        self.batch_list.setSpacing(2)
        left_layout.addWidget(self.batch_list)
        actions = QtWidgets.QHBoxLayout()
        self.folder_button = QtWidgets.QPushButton("打开目录")
        self.folder_button.clicked.connect(self.open_folder)
        self.font_button = QtWidgets.QPushButton("制作字体…")
        self.font_button.setVisible(can_publish)
        self.font_button.clicked.connect(self.publish_batch)
        actions.addWidget(self.folder_button)
        actions.addWidget(self.font_button)
        left_layout.addLayout(actions)
        splitter.addWidget(left)

        middle = QtWidgets.QWidget()
        middle_layout = QtWidgets.QVBoxLayout(middle)
        character_title = QtWidgets.QHBoxLayout()
        character_title.addWidget(QtWidgets.QLabel("字符列表"), 1)
        self.character_count = QtWidgets.QLabel()
        character_title.addWidget(self.character_count)
        middle_layout.addLayout(character_title)
        self.search = QtWidgets.QLineEdit()
        self.search.setAccessibleName("搜索目标字")
        self.search.setPlaceholderText("字符或 U+ 编码")
        self.search.setClearButtonEnabled(True)
        middle_layout.addWidget(self.search)
        self.character = QtWidgets.QListView()
        self.character.setAccessibleName("目标字")
        self.character.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.character.setUniformItemSizes(True)
        self.character_model = QtCore.QStringListModel(self.character)
        self.character.setModel(self.character_model)
        middle_layout.addWidget(self.character)
        splitter.addWidget(middle)

        right = QtWidgets.QWidget()
        right_layout = QtWidgets.QVBoxLayout(right)
        selector = QtWidgets.QHBoxLayout()
        self.heading = QtWidgets.QLabel("结果预览")
        self.heading.setProperty("inkRole", "title")
        selector.addWidget(self.heading, 1)
        self.candidate = QtWidgets.QComboBox()
        self.candidate.setAccessibleName("生成候选")
        selector.addWidget(self.candidate)
        self.zoom_button = QtWidgets.QToolButton()
        self.zoom_button.setAccessibleName("重置预览倍率")
        self.zoom_button.setToolTip("点击恢复默认视野")
        self.zoom_button.setText("100%")
        self.zoom_button.clicked.connect(self.view.reset)
        self.view.changed.connect(lambda: self.zoom_button.setText(f"{self.view.zoom:.0%}"))
        selector.addWidget(self.zoom_button)
        right_layout.addLayout(selector)
        previews = QtWidgets.QHBoxLayout()
        generated = QtWidgets.QGroupBox("生成字形")
        generated_layout = QtWidgets.QVBoxLayout(generated)
        self.generated = StrokePreview(self.view, "按来源样本着色的生成笔画", interactive=True)
        generated_layout.addWidget(self.generated, 1)
        self.target_note = QtWidgets.QLabel("选择批次后查看字形")
        self.target_note.setWordWrap(True)
        generated_layout.addWidget(self.target_note)
        previews.addWidget(generated, 1)
        original = QtWidgets.QGroupBox("来源字")
        original_layout = QtWidgets.QVBoxLayout(original)
        self.source_scroll = QtWidgets.QScrollArea()
        self.source_scroll.setAccessibleName("来源样本网格")
        self.source_scroll.setWidgetResizable(True)
        self.source_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.source_scroll.setMinimumWidth(247)
        original_layout.addWidget(self.source_scroll, 1)
        self.source_note = QtWidgets.QLabel()
        self.source_note.setWordWrap(True)
        original_layout.addWidget(self.source_note)
        previews.addWidget(original, 2)
        right_layout.addLayout(previews, 1)
        self.stroke_table = table(("实体笔段", "目标笔位", "来源方式", "源字", "原笔序"))
        self.stroke_table.setAccessibleName("生成字形的笔段和来源")
        self.stroke_table.setMinimumHeight(132)
        right_layout.addWidget(self.stroke_table)
        self.copy = QtWidgets.QPushButton("复制复查信息")
        self.copy.clicked.connect(self.copy_info)
        right_layout.addWidget(self.copy, alignment=QtCore.Qt.AlignmentFlag.AlignRight)
        splitter.addWidget(right)
        splitter.setSizes([245, 160, 875])
        splitter.setStretchFactor(2, 1)

        self.message = QtWidgets.QLabel()
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self.writers.currentIndexChanged.connect(self.filter_batches)
        self.batch_list.currentRowChanged.connect(self.batch_changed)
        self.search.textChanged.connect(self.filter_characters)
        self.character.selectionModel().currentChanged.connect(self.character_changed)
        self.candidate.currentIndexChanged.connect(self.candidate_changed)
        self.generated.stroke_selected.connect(self.select_segment)
        self.stroke_table.currentCellChanged.connect(self.stroke_changed)
        self.batch_changed(-1)
        self.reload(writer)

    def call(self, key, read):
        revision = self.revisions.get(key, 0) + 1
        self.revisions[key] = revision
        worker = HistoryRead(key, revision, read)
        self.readers[key, revision] = worker
        worker.signals.finished.connect(self.deliver)
        QtCore.QThreadPool.globalInstance().start(worker)

    @QtCore.Slot(str, int, object, str)
    def deliver(self, key, revision, result, error):
        self.readers.pop((key, revision), None)
        if revision != self.revisions.get(key):
            return
        if error:
            self.message.setText("读取失败 · " + error)
        elif key == "batches":
            self.batches = result
            self.update_writers()
        elif key == "glyph":
            self.candidates = result
            with QtCore.QSignalBlocker(self.candidate):
                self.candidate.clear()
                for i, (_, strokes, _) in enumerate(result, 1):
                    replay = " · 整字复用" if strokes and all(s.kind == "整字复用" for s in strokes) else ""
                    self.candidate.addItem(f"候选 {i}{replay}")
            self.candidate_changed(self.candidate.currentIndex())
        else:
            self.show_strokes(*result)

    def reload(self, writer):
        self.default_writer = writer
        self.message.setText("正在读取历史生成结果…")
        root = self.root / "outputs"
        self.call("batches", lambda: batch_history(root))

    def update_writers(self):
        with QtCore.QSignalBlocker(self.writers):
            self.writers.clear()
            self.writers.addItem("全部书写者", "")
            writers = {batch["writer"] for batch in self.batches}
            if self.default_writer:
                writers.add(self.default_writer)
            for writer in sorted(writers, key=str.casefold):
                self.writers.addItem(writer, writer)
            self.writers.setCurrentIndex(max(0, self.writers.findData(self.default_writer)))
        self.filter_batches()

    def filter_batches(self, *_):
        writer = self.writers.currentData()
        selected = self.batch["path"] if self.batch else None
        self.visible = [item for item in self.batches if not writer or item["writer"] == writer]
        row = next((i for i, batch in enumerate(self.visible) if batch["path"] == selected),
                   0 if self.visible else -1)
        with QtCore.QSignalBlocker(self.batch_list):
            self.batch_list.clear()
            for batch in self.visible:
                date = batch["date"].strftime("%Y-%m-%d %H:%M")
                count = f"{len(batch['characters'])} / {batch['target']}"
                status = STATUS.get(batch["status"], batch["status"])
                item = QtWidgets.QListWidgetItem(
                    f"{date} · {batch['writer']}\n{batch['method']} · {count} · {status}")
                item.setToolTip(f"{item.text()}\n{batch['path'].name}")
                item.setSizeHint(QtCore.QSize(0, self.batch_list.fontMetrics().lineSpacing() * 2 + 9))
                self.batch_list.addItem(item)
            self.batch_list.setCurrentRow(row)
        self.batch_changed(row)
        if not self.visible:
            self.message.setText("此书写者暂无生成记录" if writer else "暂无历史生成记录")

    def batch_changed(self, row, *_):
        self.batch = self.visible[row] if 0 <= row < len(self.visible) else None
        self.archive = None
        self.folder_button.setEnabled(self.batch is not None)
        done = bool(self.batch and self.batch["characters"] and self.batch["status"] not in
                    {"running", "preparing", "failed"})
        self.font_button.setEnabled(done)
        self.search.setEnabled(bool(self.batch and self.batch["characters"]))
        with QtCore.QSignalBlocker(self.search):
            self.search.clear()
        self.filter_characters()

    def filter_characters(self, *_):
        previous = self.current_character()
        query = character_query(self.search.text())
        self.characters = [c for c in self.batch["characters"] if not query or c == query] if self.batch else []
        row = self.characters.index(previous) if previous in self.characters else 0
        with QtCore.QSignalBlocker(self.character.selectionModel()):
            self.character_model.setStringList([f"{c}    U+{ord(c):04X}" for c in self.characters])
            self.character.setCurrentIndex(self.character_model.index(row))
        self.character_count.setText(f"{len(self.characters)} 字")
        self.character.setEnabled(bool(self.characters))
        self.character_changed(self.character.currentIndex())

    def current_character(self):
        row = self.character.currentIndex().row()
        return self.characters[row] if 0 <= row < len(self.characters) else ""

    def character_changed(self, *_):
        self.revisions["glyph"] = self.revisions.get("glyph", 0) + 1
        character = self.current_character()
        self.heading.setText(f"结果预览 · {character}" if character else "结果预览")
        self.view.reset()
        self.candidates = []
        with QtCore.QSignalBlocker(self.candidate):
            self.candidate.clear()
        self.candidate_changed(-1)
        if not character or not self.batch:
            self.message.setText("没有匹配的已完成字形" if self.batch else "")
            return
        self.message.setText("正在读取字形和候选…")
        batch = self.batch
        self.call("glyph", lambda: list(inspect_candidates(batch, character)))

    def candidate_changed(self, i):
        self.revisions["source"] = self.revisions.get("source", 0) + 1
        self.show_strokes([], {})
        if not 0 <= i < len(self.candidates):
            return
        self.version, strokes, profile = self.candidates[i]
        if self.archive is None:
            self.archive = SourceArchive(self.batch["writer"], profile, self.root / "imports", self.capture)
        archive = self.archive
        self.message.setText("正在查找源录制…")
        self.call("source", lambda: archive.resolve(strokes))

    def colors(self, keys):
        dark = self.palette().base().color().lightness() < 128
        lightness = 178 if dark else 86
        return {key: QtGui.QColor.fromHsl((203 + 137 * i) % 360, 175, lightness)
                for i, key in enumerate(keys)}

    def show_strokes(self, strokes, recordings):
        self.strokes, self.recordings = strokes, recordings
        groups = {}
        for row, stroke in enumerate(strokes):
            if any(stroke.key):
                groups.setdefault(stroke.key, []).append(row)
        colors = self.colors(groups)
        self.generated.set_ink([s.points for s in strokes], [colors.get(s.key) for s in strokes])
        self.source_cards = {}
        content = QtWidgets.QWidget()
        grid = QtWidgets.QGridLayout(content)
        grid.setContentsMargins(4, 4, 4, 4)
        grid.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        for index, (key, rows) in enumerate(groups.items()):
            first = rows[0]
            orders = {strokes[row].raw_order for row in rows if strokes[row].raw_order is not None}
            card = SourceCard(self.view, index + 1, strokes[first], recordings.get(key, Recording()),
                              orders, colors[key])
            card.button.clicked.connect(lambda _, row=first: self.select_segment(row))
            grid.addWidget(card, index // 2, index % 2)
            self.source_cards[key] = card
        if not self.source_cards:
            empty = QtWidgets.QLabel("此候选未记录来源字" if strokes else "选择字符后查看来源字")
            empty.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            grid.addWidget(empty, 0, 0, 1, 2)
        self.source_scroll.setWidget(content)
        fill_table(self.stroke_table, [
            (i, " + ".join(s.slots), s.kind, s.character or "—", s.raw_order or "—")
            for i, s in enumerate(strokes, 1)
        ])
        self.copy.setEnabled(bool(strokes))
        self.zoom_button.setEnabled(self.generated.has_ink())
        self.target_note.setText("点击笔迹查看来源 · Ctrl + 滚轮缩放" if strokes else "暂无可查看的字形")
        if strokes:
            self.message.setText(f"批次 {self.batch['path'].name} · 算法版本 {self.version}")
            with QtCore.QSignalBlocker(self.stroke_table):
                self.stroke_table.setCurrentCell(0, 0)
        self.stroke_changed(0 if strokes else -1)

    def select_segment(self, row):
        previous = self.stroke_table.currentRow()
        self.stroke_table.setCurrentCell(row, 0)
        self.stroke_table.scrollToItem(self.stroke_table.item(row, 0))
        if previous == row:
            self.stroke_changed(row)

    def stroke_changed(self, row, *_):
        self.generated.select(row)
        stroke = self.strokes[row] if 0 <= row < len(self.strokes) else None
        key = stroke.key if stroke else None
        for source_key, card in self.source_cards.items():
            active = source_key == key
            order = stroke.raw_order if active else None
            card.select(active, order if order and 1 <= order <= len(card.preview.paths) else None)
        card = self.source_cards.get(key)
        if card is None:
            self.source_note.setText("此笔段没有可定位的源录制" if self.strokes else "")
            return
        self.source_scroll.ensureWidgetVisible(card, 0, 6)
        recording = self.recordings.get(key, Recording())
        detail = f" · 原笔序 {stroke.raw_order}" if stroke.raw_order else " · 原笔序未记录"
        if stroke.standard_id:
            detail += f" · 源标准笔位 {stroke.standard_id}"
        self.source_note.setText(f"{recording.status}{detail}")

    def copy_info(self):
        rows = [
            f"批次 {self.batch['path'].name} · 书写者 {self.batch['writer']}",
            f"算法 {self.batch['method']} · 版本 {self.version}",
            f"目标字 {self.current_character()} · {self.candidate.currentText()}",
        ]
        for i, s in enumerate(self.strokes, 1):
            rows.append(f"笔段 {i} · {' + '.join(s.slots)} · {s.kind} · 源字 {s.character or '未记录'}"
                        f" · 样本 {s.sample or s.digest or '未记录'} · 原笔序 {s.raw_order or '未记录'}"
                        + (f" · 源标准笔位 {s.standard_id}" if s.standard_id else ""))
        QtWidgets.QApplication.clipboard().setText("\n".join(rows))
        self.message.setText("已复制当前候选的复查信息")

    def open_folder(self):
        if self.batch and not QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(self.batch["path"]))):
            self.message.setText("无法打开结果目录")

    def publish_batch(self):
        if self.batch and self.font_button.isEnabled():
            self.publish_requested.emit(self.batch["path"], self.batch["writer"])
