"""Edit one image's labels in a larger preview, using the document's ink."""

from dataclasses import replace

from PySide6 import QtCore, QtWidgets

from ..document.editing import SourceSession
from ..document.image_labels import ImageLabel, MAX_LABEL_LENGTH, PATTERN
from ..document.markdown import parse_markdown
from ..document.schema import PageProfile, new_id
from .continuous_preview import ContinuousPageCanvas


def labels_of(image):
    return [child for child in image.children if child.kind == "image_label"]


def comment_span(source, label):
    match = PATTERN.search(source, label.span.start, label.span.end)
    return match.span() if match else None


def move_label(session, node, dx, dy):
    label = ImageLabel.from_node(node)
    updated = replace(label, x=min(100, max(0, label.x + dx)), y=min(100, max(0, label.y + dy)))
    if updated.position == label.position:
        return False
    match = PATTERN.search(session.source, node.span.start, node.span.end)
    start, end = match.span("position")
    session.apply(start, end, updated.position)
    return True


class ImageLabelDialog(QtWidgets.QDialog):
    def __init__(self, editor, image, fragment, selected_id, parent):
        super().__init__(parent)
        self.setWindowTitle("图片标注")
        self.setWindowFlag(QtCore.Qt.WindowType.WindowMaximizeButtonHint)
        self.resize(1120, 720)
        self.setMinimumSize(720, 440)
        self.editor = editor
        self.image = image
        self.source_session = editor.source_session
        self.source_revision = self.source_session.revision
        self.result_edit = None

        # Render an excerpt with the original label identities, so the preview
        # uses the very same frozen glyphs and excludes the rest of the document.
        self.image_source = "![](preview-image)\n"
        self.session = SourceSession(self.image_source, document_id=self.source_session.document_id)
        for node in labels_of(image):
            span = comment_span(self.source_session.source, node)
            if span:
                start, end = span
                line = self.source_session.source[start:end] + "\n"
                ids = (*self.source_session.atom_ids[start:end], new_id())
                self.session.apply(len(self.session.source), len(self.session.source), line, inserted_ids=ids)
        self.original = self.session.source
        self._read_labels()

        source = dict(image.attributes)["src"]
        resource = next(resource for resource in editor.flow.images if resource.source == source)
        self.flow = replace(
            editor.flow, template=None, template_bindings=(),
            images=(replace(resource, source="preview-image"),),
            image=editor.flow.image_for(image.node_id), image_overrides=(),
        )
        x0, y0, x1, y1 = fragment.logical_bounds
        self.page = PageProfile(x1 - x0 + 16, y1 - y0 + 16, 8)
        self.preview_timer = QtCore.QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.timeout.connect(self.refresh_preview)

        self.canvas = ContinuousPageCanvas()
        self.canvas.label_placed.connect(self.add_at)
        self.canvas.label_selected.connect(lambda _, label_id: self.select_id(label_id))
        self.canvas.label_moved.connect(self.move)
        self.canvas.label_placement_cancelled.connect(self._cancel_placement)
        self.scroll = QtWidgets.QScrollArea()
        self.scroll.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.scroll.setWidget(self.canvas)
        self.scroll.viewport().installEventFilter(self)

        column = QtWidgets.QVBoxLayout(self)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.scroll, 1)
        panel = QtWidgets.QWidget()
        panel.setFixedWidth(288)
        options = QtWidgets.QVBoxLayout(panel)
        options.setContentsMargins(0, 0, 0, 0)
        actions = QtWidgets.QHBoxLayout()
        self.add = QtWidgets.QPushButton("添加文字…")
        self.add.setCheckable(True)
        self.add.toggled.connect(self.place)
        actions.addWidget(self.add)
        self.remove = QtWidgets.QPushButton("删除")
        self.remove.clicked.connect(self.delete_selected)
        actions.addWidget(self.remove)
        actions.addStretch()
        options.addLayout(actions)
        self.hint = QtWidgets.QLabel("点击图内放置文字，拖动图上的文字可微调位置。")
        self.hint.setWordWrap(True)
        options.addWidget(self.hint)
        self.labels = QtWidgets.QListWidget()
        self.labels.setAccessibleName("图片标注列表")
        self.labels.setMinimumHeight(80)
        self.labels.setMaximumHeight(168)
        self.labels.currentRowChanged.connect(self.show_label)
        options.addWidget(self.labels)
        self.text = QtWidgets.QLineEdit()
        self.text.setAccessibleName("单行文字或行内公式")
        self.text.setPlaceholderText("例如 焦点$F_1$")
        self.text.setMaxLength(MAX_LABEL_LENGTH)
        self.text.textEdited.connect(self.change_label)
        options.addWidget(QtWidgets.QLabel("单行文字或行内公式"))
        options.addWidget(self.text)
        self.inherit = QtWidgets.QCheckBox("沿用文档字号")
        self.inherit.toggled.connect(self.change_label)
        options.addWidget(self.inherit)
        form = QtWidgets.QFormLayout()
        self.size = QtWidgets.QDoubleSpinBox()
        self.size.setRange(1, 100)
        self.size.setDecimals(2)
        self.size.setSuffix(" mm")
        self.size.setMaximumWidth(108)
        self.size.valueChanged.connect(self.change_label)
        form.addRow("标注字号", self.size)
        options.addLayout(form)
        self.error = QtWidgets.QLabel()
        self.error.setWordWrap(True)
        options.addWidget(self.error)
        options.addStretch(1)
        row.addWidget(panel)
        column.addLayout(row, 1)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        self.apply_button = buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Ok)
        self.apply_button.setText("应用")
        buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        column.addWidget(buttons)
        self.fill_list(selected_id)
        self.refresh_preview()

    def _read_labels(self):
        document = parse_markdown(self.session)
        self.preview_image = document.nodes[0].children[0].children[0]
        self.nodes = labels_of(self.preview_image)

    def fill_list(self, selected_id=None):
        with QtCore.QSignalBlocker(self.labels):
            self.labels.clear()
            for node in self.nodes:
                self.labels.addItem(node.raw_content)
        row = next((i for i, node in enumerate(self.nodes) if node.node_id == selected_id), 0)
        with QtCore.QSignalBlocker(self.labels):
            self.labels.setCurrentRow(row if self.nodes else -1)
        self.show_label(self.labels.currentRow())

    def select_id(self, label_id):
        for row, node in enumerate(self.nodes):
            if node.node_id == label_id:
                self.labels.setCurrentRow(row)
                return

    def show_label(self, row):
        node = self.nodes[row] if 0 <= row < len(self.nodes) else None
        label = ImageLabel.from_node(node) if node else ImageLabel(50, 50)
        with (QtCore.QSignalBlocker(self.text), QtCore.QSignalBlocker(self.inherit),
              QtCore.QSignalBlocker(self.size)):
            self.text.setText(node.raw_content if node else "")
            self.inherit.setChecked(label.em_mm is None)
            self.size.setValue(label.em_mm or self.editor.style.em_mm)
        for control in (self.remove, self.text, self.inherit):
            control.setEnabled(node is not None)
        self.size.setEnabled(node is not None and label.em_mm is not None)
        self.canvas.highlight_image_label(self.preview_image.node_id, node.node_id if node else None)
        self.apply_button.setEnabled(True)
        self.error.clear()

    def change_label(self, *_):
        row = self.labels.currentRow()
        if row < 0:
            return
        node = self.nodes[row]
        self.size.setEnabled(not self.inherit.isChecked())
        label = replace(ImageLabel.from_node(node), em_mm=None if self.inherit.isChecked() else self.size.value())
        try:
            line = label.source_line(self.text.text())
        except ValueError as error:
            self.preview_timer.stop()
            self.error.setText(str(error))
            self.apply_button.setEnabled(False)
            return
        self.apply_button.setEnabled(True)
        self.error.clear()
        start, end = comment_span(self.session.source, node)
        self.session.apply_preserving(self.session.source[:start] + line + self.session.source[end:])
        self._read_labels()
        self.labels.currentItem().setText(self.nodes[row].raw_content)
        self.preview_timer.start(150)

    def place(self, enabled):
        self.hint.setText("点击图内选择新标注的中心位置。" if enabled
                          else "点击图内放置文字，拖动图上的文字可微调位置。")
        self.canvas.place_image_label(self.preview_image.node_id if enabled else None)

    def _cancel_placement(self):
        self.add.setChecked(False)

    def add_at(self, _, x, y):
        self.session.apply(len(self.session.source), len(self.session.source),
                           ImageLabel(x, y).source_line("文字") + "\n")
        self._read_labels()
        self.fill_list(self.nodes[-1].node_id)
        self.text.setFocus()
        self.text.selectAll()
        self.refresh_preview()

    def delete_selected(self):
        row = self.labels.currentRow()
        if row < 0:
            return
        node = self.nodes[row]
        self.session.apply(node.span.start, node.span.end, "")
        self._read_labels()
        self.fill_list(self.nodes[min(row, len(self.nodes) - 1)].node_id if self.nodes else None)
        self.refresh_preview()

    def move(self, _, label_id, dx, dy):
        node = next((node for node in self.nodes if node.node_id == label_id), None)
        if node and move_label(self.session, node, dx, dy):
            self._read_labels()
            self.refresh_preview()

    def refresh_preview(self):
        from .mixed import build_markdown

        self.preview_timer.stop()
        w = self.editor
        try:
            result = build_markdown(self.session, self.session.revision, w.resolver, w.run_path,
                                    w.symbol_path, self.page, w.style, self.flow, None)
        except (ValueError, OSError) as error:
            self.error.setText(str(error))
            return
        snapshot = result["snapshot"]
        self.canvas.load_page(snapshot, 0)
        self.fit_preview()
        issue = next((d for d in snapshot.diagnostics if d.severity == "error" or d.code == "image-label-overflow"), None)
        self.error.setText(issue.message if issue else "")

    def eventFilter(self, widget, event):
        if widget is self.scroll.viewport() and event.type() == QtCore.QEvent.Type.Resize:
            self.fit_preview()
        return super().eventFilter(widget, event)

    def fit_preview(self):
        size = self.scroll.viewport().size()
        inset = 2 * self.canvas.margin + 2
        if self.canvas.snapshot and min(size.width(), size.height()) > inset:
            scale = min((size.width() - inset) / self.page.width_mm,
                        (size.height() - inset) / self.page.height_mm, 28)
            if abs(self.canvas.scale - scale) > 1e-6:
                self.canvas.scale = scale
                self.canvas.resize_page()

    def accept(self):
        if not self.apply_button.isEnabled():
            return
        if self.session.source != self.original:
            self.result_edit = self.make_edit()
        super().accept()

    def make_edit(self):
        source = self.source_session.source
        image = self.image
        next_lf = source.find("\n", image.span.end)
        start = len(source) if next_lf < 0 else next_lf + 1
        end = max((node.span.end for node in labels_of(image)), default=start)
        line_start = source.rfind("\n", 0, image.span.start) + 1
        prefix = source[line_start:image.span.start]
        newline = "\r\n" if next_lf > 0 and source[next_lf - 1] == "\r" else "\n"
        parts, ids = [], []
        if self.nodes and next_lf < 0:
            parts.append(newline)
            ids.extend(new_id() for _ in newline)
        for node in self.nodes:
            a, b = comment_span(self.session.source, node)
            parts.extend((prefix, self.session.source[a:b], newline))
            ids.extend(new_id() for _ in prefix)
            ids.extend(self.session.atom_ids[a:b])
            ids.extend(new_id() for _ in newline)
        if not self.nodes and end < len(source) and not source.startswith(("\n", "\r\n"), end):
            parts.append(prefix.rstrip() + newline)
            ids.extend(new_id() for _ in parts[-1])
        return start, end, "".join(parts), tuple(ids)

    def done(self, result):
        self.preview_timer.stop()
        self.canvas.stop_rendering()
        super().done(result)


class ImageLabelControls(QtWidgets.QPushButton):
    def __init__(self, inspector):
        super().__init__("编辑图片标注…", inspector)
        self.inspector = inspector
        self.editor = inspector.editor
        self.image = None
        self.selected_id = None
        self.clicked.connect(self.open_editor)
        self.editor.canvas.label_selected.connect(self.select_label)
        self.editor.canvas.label_moved.connect(self.move)
        self.hide()

    def set_image(self, node):
        image = node if node and node.kind == "image" and self.editor.snapshot and any(
            f.node_id == node.node_id and f.status in {"image-vector", "image-reference"}
            for f in self.editor.snapshot.fragments
        ) else None
        if not self.image or not image or self.image.node_id != image.node_id:
            self.selected_id = None
        self.image = image
        self.setVisible(image is not None)
        self.editor.canvas.highlight_image_label(image.node_id if image else None, self.selected_id)

    def select_label(self, image_id, label_id):
        index = self.inspector.selector.findData(image_id)
        if index >= 0:
            self.inspector.selector.setCurrentIndex(index)
            self.selected_id = label_id
            self.editor.canvas.highlight_image_label(image_id, label_id)
            self.editor.properties_tabs.setCurrentIndex(0)
            self.editor.element_properties_dock.show()
            self.editor.element_properties_dock.raise_()

    def ready(self):
        w = self.editor
        return (self.image is not None and w.canvas.isEnabled() and not w.editor.composing
                and w.markdown_document and self.inspector.document is w.markdown_document
                and w.markdown_document.source == w.source_session.source)

    def commit(self):
        self.editor._display_session()
        self.editor.mark_dirty()
        self.editor.schedule_layout()

    def open_editor(self):
        if not self.ready():
            return
        w = self.editor
        fragment = next(f for f in w.snapshot.fragments if f.node_id == self.image.node_id
                        and f.status in {"image-vector", "image-reference"})
        dialog = ImageLabelDialog(w, self.image, fragment, self.selected_id, w)
        try:
            if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted or not dialog.result_edit:
                return
            if not self.ready() or w.source_session is not dialog.source_session:
                raise ValueError("文档已变化，请重新打开图片标注窗口。")
            start, end, text, ids = dialog.result_edit
            w.source_session.apply(start, end, text, expected_revision=dialog.source_revision, inserted_ids=ids)
            self.commit()
        except (ValueError, OSError) as error:
            w.message_error(error)
        finally:
            dialog.deleteLater()

    def move(self, image_id, label_id, dx, dy):
        if not self.ready() or self.image.node_id != image_id:
            return
        node = next((node for node in labels_of(self.image) if node.node_id == label_id), None)
        if node and move_label(self.editor.source_session, node, dx, dy):
            self.commit()
