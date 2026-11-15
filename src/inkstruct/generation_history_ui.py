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


class StrokePreview(QtWidgets.QWidget):
    stroke_selected = QtCore.Signal(int)

    def __init__(self, description, *, interactive=False):
        super().__init__()
        self.setAccessibleName(description)
        self.setMinimumSize(180, 174)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Expanding)
        self.interactive = interactive
        self.selected = -1
        self.strokes, self.colors, self.paths = (), (), []

    def set_ink(self, strokes=(), colors=(), selected=-1):
        self.strokes, self.colors, self.selected = strokes, colors, selected
        self.paths = []
        self.update()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        palette = self.palette()
        painter.fillRect(self.rect(), palette.base())
        if not self.strokes:
            return
        points = [point for stroke in self.strokes for point in stroke]
        if not points:
            return
        box = self.rect().adjusted(18, 18, -18, -18)
        left, right = min(x for x, _ in points), max(x for x, _ in points)
        top, bottom = min(y for _, y in points), max(y for _, y in points)
        scale = min(box.width() / max(right - left, 1e-9), box.height() / max(bottom - top, 1e-9))
        center = QtCore.QPointF(box.center())
        self.paths = []
        for stroke in self.strokes:
            path = QtGui.QPainterPath()
            for i, (x, y) in enumerate(stroke):
                point = center + QtCore.QPointF((x - (left + right) / 2) * scale,
                                                  (y - (top + bottom) / 2) * scale)
                if i == 0:
                    path.moveTo(point)
                else:
                    path.lineTo(point)
            self.paths.append(path)
        order = sorted(range(len(self.paths)), key=lambda i: i == self.selected)
        for i in order:
            if not self.strokes[i]:
                continue
            color = QtGui.QColor(self.colors[i] if self.colors else palette.text().color())
            if not self.interactive and i != self.selected:
                color.setAlpha(88)
            width = 4 if i == self.selected else 2.2
            painter.setPen(QtGui.QPen(color, width, QtCore.Qt.PenStyle.SolidLine,
                                      QtCore.Qt.PenCapStyle.RoundCap, QtCore.Qt.PenJoinStyle.RoundJoin))
            if self.paths[i].isEmpty():
                painter.drawPoint(self.paths[i].currentPosition())
            else:
                painter.drawPath(self.paths[i])

    def mousePressEvent(self, event):
        if not self.interactive or event.button() != QtCore.Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        for width in (5, 12, 20):
            stroker = QtGui.QPainterPathStroker()
            stroker.setWidth(width)
            for i, path in enumerate(self.paths):
                if not self.strokes[i]:
                    continue
                if path.isEmpty():
                    delta = event.position() - path.currentPosition()
                    hit = delta.x() ** 2 + delta.y() ** 2 <= (width / 2) ** 2
                else:
                    hit = stroker.createStroke(path).contains(event.position())
                if hit:
                    self.stroke_selected.emit(i)
                    return


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
        self.strokes, self.recordings, self.source_keys = (), {}, []
        self.version = ""
        self.default_writer = writer

        layout = QtWidgets.QVBoxLayout(self)
        splitter = QtWidgets.QSplitter()
        splitter.setChildrenCollapsible(False)
        layout.addWidget(splitter, 1)
        left = QtWidgets.QWidget()
        left_layout = QtWidgets.QVBoxLayout(left)
        filters = QtWidgets.QHBoxLayout()
        self.writers = QtWidgets.QComboBox()
        self.writers.setAccessibleName("按书写者筛选批次")
        filters.addWidget(QtWidgets.QLabel("书写者"))
        filters.addWidget(self.writers, 1)
        refresh = QtWidgets.QPushButton("刷新")
        refresh.clicked.connect(lambda: self.reload(self.writers.currentData() or ""))
        filters.addWidget(refresh)
        left_layout.addLayout(filters)
        self.batches_table = table(("生成时间", "书写者", "算法", "完成 / 目标", "状态"))
        self.batches_table.setAccessibleName("生成批次")
        left_layout.addWidget(self.batches_table)
        actions = QtWidgets.QHBoxLayout()
        self.folder_button = QtWidgets.QPushButton("打开结果目录")
        self.folder_button.clicked.connect(self.open_folder)
        self.font_button = QtWidgets.QPushButton("用所选批次制作字体…")
        self.font_button.setVisible(can_publish)
        self.font_button.clicked.connect(self.publish_batch)
        actions.addWidget(self.folder_button)
        actions.addWidget(self.font_button)
        left_layout.addLayout(actions)
        splitter.addWidget(left)

        right = QtWidgets.QWidget()
        right_layout = QtWidgets.QVBoxLayout(right)
        self.heading = QtWidgets.QLabel("字形来源")
        self.heading.setProperty("inkRole", "title")
        right_layout.addWidget(self.heading)
        selector = QtWidgets.QHBoxLayout()
        self.search = QtWidgets.QLineEdit()
        self.search.setAccessibleName("搜索目标字")
        self.search.setPlaceholderText("输入目标字或 U+ 编码")
        self.character = QtWidgets.QComboBox()
        self.character.setAccessibleName("目标字")
        self.character.setMinimumContentsLength(8)
        self.candidate = QtWidgets.QComboBox()
        self.candidate.setAccessibleName("生成候选")
        selector.addWidget(self.search, 1)
        selector.addWidget(self.character)
        selector.addWidget(self.candidate)
        right_layout.addLayout(selector)
        previews = QtWidgets.QHBoxLayout()
        generated = QtWidgets.QGroupBox("生成字形")
        generated_layout = QtWidgets.QVBoxLayout(generated)
        self.generated = StrokePreview("按来源样本着色的生成笔画", interactive=True)
        generated_layout.addWidget(self.generated, 1)
        self.target_note = QtWidgets.QLabel("选择批次后查看字形")
        self.target_note.setWordWrap(True)
        generated_layout.addWidget(self.target_note)
        previews.addWidget(generated, 1)
        original = QtWidgets.QGroupBox("源录制")
        original_layout = QtWidgets.QVBoxLayout(original)
        self.original = StrokePreview("源录制笔迹")
        self.sources = QtWidgets.QComboBox()
        self.sources.setAccessibleName("来源样本")
        self.sources.setSizeAdjustPolicy(QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.sources.setMinimumContentsLength(12)
        original_layout.addWidget(self.sources)
        original_layout.addWidget(self.original, 1)
        self.source_note = QtWidgets.QLabel()
        self.source_note.setWordWrap(True)
        original_layout.addWidget(self.source_note)
        previews.addWidget(original, 1)
        right_layout.addLayout(previews, 1)
        self.stroke_table = table(("实体笔段", "目标笔位", "来源方式", "源字", "原笔序"))
        self.stroke_table.setAccessibleName("生成字形的笔段和来源")
        self.stroke_table.setMinimumHeight(132)
        right_layout.addWidget(self.stroke_table)
        self.copy = QtWidgets.QPushButton("复制复查信息")
        self.copy.clicked.connect(self.copy_info)
        right_layout.addWidget(self.copy, alignment=QtCore.Qt.AlignmentFlag.AlignRight)
        splitter.addWidget(right)
        splitter.setSizes([510, 810])
        splitter.setStretchFactor(1, 1)

        self.message = QtWidgets.QLabel()
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self.writers.currentIndexChanged.connect(self.filter_batches)
        self.batches_table.currentCellChanged.connect(self.batch_changed)
        self.search.textChanged.connect(self.filter_characters)
        self.character.currentIndexChanged.connect(self.character_changed)
        self.candidate.currentIndexChanged.connect(self.candidate_changed)
        self.generated.stroke_selected.connect(self.stroke_table.selectRow)
        self.stroke_table.currentCellChanged.connect(self.stroke_changed)
        self.sources.currentIndexChanged.connect(self.source_changed)
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
        self.visible = [item for item in self.batches if not writer or item["writer"] == writer]
        fill_table(self.batches_table, [
            (item["date"].strftime("%Y-%m-%d %H:%M"), item["writer"], item["method"],
             f"{len(item['characters'])} / {item['target']}", STATUS.get(item["status"], item["status"]))
            for item in self.visible
        ])
        if self.visible:
            with QtCore.QSignalBlocker(self.batches_table):
                self.batches_table.setCurrentCell(0, 0)
        self.batch_changed(0 if self.visible else -1)
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
        query = character_query(self.search.text())
        self.characters = [c for c in self.batch["characters"] if not query or c == query] if self.batch else []
        with QtCore.QSignalBlocker(self.character):
            self.character.clear()
            self.character.addItems(self.characters)
        self.character.setEnabled(bool(self.characters))
        self.character_changed(self.character.currentIndex())

    def character_changed(self, i):
        self.revisions["glyph"] = self.revisions.get("glyph", 0) + 1
        self.candidates = []
        with QtCore.QSignalBlocker(self.candidate):
            self.candidate.clear()
        self.candidate_changed(-1)
        if i < 0 or not self.batch:
            self.message.setText("没有匹配的已完成字形" if self.batch else "")
            return
        self.message.setText("正在读取字形和候选…")
        batch, character = self.batch, self.characters[i]
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

    def colors(self):
        dark = self.palette().base().color().lightness() < 128
        lightness = 178 if dark else 86
        lookup = {key: QtGui.QColor.fromHsl((203 + 137 * i) % 360, 175, lightness)
                  for i, key in enumerate(self.source_keys)}
        neutral = self.palette().mid().color()
        return [lookup.get(s.key, neutral) for s in self.strokes]

    def show_strokes(self, strokes, recordings):
        self.strokes, self.recordings = strokes, recordings
        self.source_keys = list(dict.fromkeys(s.key for s in strokes if any(s.key)))
        with QtCore.QSignalBlocker(self.sources):
            self.sources.clear()
            for i, key in enumerate(self.source_keys, 1):
                source = next(s for s in strokes if s.key == key)
                identity = source.sample or source.digest or "样本编号未记录"
                self.sources.addItem(f"样本 {i} · {source.character} · {identity}", key)
                self.sources.setItemData(i - 1, identity, QtCore.Qt.ItemDataRole.ToolTipRole)
        fill_table(self.stroke_table, [
            (i, " + ".join(s.slots), s.kind, s.character or "—", s.raw_order or "—")
            for i, s in enumerate(strokes, 1)
        ])
        self.copy.setEnabled(bool(strokes))
        self.target_note.setText("点击生成笔迹或下方笔段查看原录制" if strokes else "暂无可查看的字形")
        if strokes:
            self.message.setText(f"批次 {self.batch['path'].name} · 算法版本 {self.version}")
            with QtCore.QSignalBlocker(self.stroke_table):
                self.stroke_table.setCurrentCell(0, 0)
        self.stroke_changed(0 if strokes else -1)

    def stroke_changed(self, row, *_):
        color = self.colors()
        self.generated.set_ink([s.points for s in self.strokes], color, row)
        if 0 <= row < len(self.strokes):
            source = self.strokes[row]
            i = self.source_keys.index(source.key) if source.key in self.source_keys else -1
        else:
            i = -1
        with QtCore.QSignalBlocker(self.sources):
            self.sources.setCurrentIndex(i)
        self.source_changed(i)

    def source_changed(self, i):
        if not 0 <= i < len(self.source_keys):
            self.original.set_ink()
            self.source_note.setText("此笔段没有可定位的源录制" if self.strokes else "")
            return
        key = self.source_keys[i]
        recording = self.recordings.get(key, Recording())
        row = self.stroke_table.currentRow()
        stroke = self.strokes[row] if 0 <= row < len(self.strokes) and self.strokes[row].key == key else None
        raw_order = stroke.raw_order if stroke else None
        selected = raw_order - 1 if raw_order and 1 <= raw_order <= len(recording.strokes) else -1
        color = next(c for s, c in zip(self.strokes, self.colors()) if s.key == key)
        self.original.set_ink(recording.strokes, [color] * len(recording.strokes), selected)
        detail = f" · 原笔序 {raw_order}" if raw_order else " · 原笔序未记录" if stroke else ""
        if stroke and stroke.standard_id:
            detail += f" · 源标准笔位 {stroke.standard_id}"
        sample = next(s for s in self.strokes if s.key == key)
        identity = sample.sample or sample.digest or "样本编号未记录"
        self.source_note.setText(f"{sample.character} · {identity}\n{recording.status}{detail}")

    def copy_info(self):
        rows = [
            f"批次 {self.batch['path'].name} · 书写者 {self.batch['writer']}",
            f"算法 {self.batch['method']} · 版本 {self.version}",
            f"目标字 {self.character.currentText()} · {self.candidate.currentText()}",
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
