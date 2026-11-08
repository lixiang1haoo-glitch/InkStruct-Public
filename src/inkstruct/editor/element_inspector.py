"""Document-local table/image properties beside the continuous preview."""

from dataclasses import replace

from PySide6 import QtCore, QtWidgets

from ..document.source import utf16_to_scalar
from ..global_defaults import GlobalDefaultsStore, apply_to_document
from ..settings_elements import ElementPage
from ..settings_pages import label


class ElementInspector(QtWidgets.QWidget):
    def __init__(self, editor):
        super().__init__()
        self.editor = editor
        self.flow = editor.flow
        self.document = None
        self.pages = {}
        self.syncing = False
        column = QtWidgets.QVBoxLayout(self)
        self.context = label("未选择表格或图片")
        self.context.setObjectName("inspector_context")
        column.addWidget(self.context)
        self.selector = QtWidgets.QComboBox()
        self.selector.setAccessibleName("选中的表格或图片")
        self.selector.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.selector.setMinimumContentsLength(12)
        column.addWidget(self.selector)
        self.stack = QtWidgets.QStackedWidget()
        self.empty = label("在预览中点击表格或图片，或将源码光标放入元素内。也可从上方列表选择。")
        self.stack.addWidget(self.empty)
        column.addWidget(self.stack, 1)
        self.error = label("")
        column.addWidget(self.error)
        row = QtWidgets.QHBoxLayout()
        self.revert = QtWidgets.QPushButton("取消未应用修改")
        self.apply_button = QtWidgets.QPushButton("应用元素属性")
        self.apply_button.setProperty("inkRole", "primary")
        row.addWidget(self.revert)
        row.addWidget(self.apply_button)
        column.addLayout(row)
        self.defaults_info = label("")
        column.addWidget(self.defaults_info)
        self.use_defaults = QtWidgets.QPushButton("将全局默认排版参数用于本文")
        self.use_defaults.setToolTip(
            "明确更新当前文档的默认排版参数；保留字体、图片资源和表格/图片独立设置。"
        )
        column.addWidget(self.use_defaults)
        self.selector.currentIndexChanged.connect(self.select_item)
        self.selector.activated.connect(self.navigate_selected)
        self.apply_button.clicked.connect(self.apply)
        self.revert.clicked.connect(self.discard)
        self.use_defaults.clicked.connect(self.apply_defaults)
        editor.editor.cursorPositionChanged.connect(self.cursor_changed)
        self.refresh()

    def refresh(self):
        w = self.editor
        document = getattr(w, "markdown_document", None)
        ready = bool(
            document and document.source == w.source_session.source and w.canvas.isEnabled()
        )
        self.set_ready(ready)
        if not ready:
            return
        selected = self.selector.currentData()
        flow_changed = self.flow != w.flow
        self.flow, self.document = w.flow, document
        if flow_changed:
            self.clear_pages()
        all_nodes = [
            n for root in document.nodes for n in root.walk() if n.kind in {"table", "image"}
        ]
        with QtCore.QSignalBlocker(self.selector):
            self.selector.clear()
            self.selector.addItem("请选择表格或图片", None)
            counts = {"table": 0, "image": 0}
            for node in all_nodes:
                counts[node.kind] += 1
                name = "表格" if node.kind == "table" else "图片"
                snippet = document.source[node.span.start : node.span.end].replace("\n", " ")[:28]
                self.selector.addItem(f"{name} {counts[node.kind]} · {snippet}", node.node_id)
            self.selector.setCurrentIndex(max(0, self.selector.findData(selected)))
        for kind, page in self.pages.items():
            nodes = [n for n in all_nodes if n.kind == kind]
            page.document, page.nodes = document, nodes
            valid = {n.node_id for n in nodes}
            for key in list(page.editors):
                if key is not None and key not in valid:
                    old = page.editors.pop(key)
                    page.independent.pop(key, None)
                    page.stack.removeWidget(old)
                    old.deleteLater()
            with QtCore.QSignalBlocker(page.scope):
                page.scope.clear()
                page.scope.addItem("文档默认", None)
                for node in nodes:
                    page.scope.addItem(node.node_id, node.node_id)
        image_size = (f"图高 {w.flow.image.height_mm:g} mm，宽度按比例"
                      if w.flow.image.height_mm is not None else f"旧版图宽 {w.flow.image.width_mm:g} mm")
        self.defaults_info.setText(f"本文默认：表宽 {w.flow.table.width_mm:g} mm；{image_size}。")
        self.select_item()
        self.cursor_changed()

    def set_ready(self, ready):
        self.apply_button.setEnabled(ready)
        self.use_defaults.setEnabled(ready)
        self.revert.setEnabled(ready)
        self.selector.setEnabled(ready)
        self.stack.setEnabled(ready)
        if not ready:
            self.context.setText("预览正在更新，暂不可编辑元素属性。")

    def clear_pages(self):
        for page in self.pages.values():
            self.stack.removeWidget(page)
            page.deleteLater()
        self.pages.clear()
        self.stack.setCurrentWidget(self.empty)

    def select_item(self):
        key = self.selector.currentData()
        if (not self.document or self.document.source != self.editor.source_session.source
                or not self.editor.canvas.isEnabled()):
            return
        node = next(
            (n for root in self.document.nodes for n in root.walk() if n.node_id == key), None
        )
        if node is None:
            self.stack.setCurrentWidget(self.empty)
            self.context.setText("未选择表格或图片")
            return
        if node.kind not in self.pages:
            page = ElementPage(node.kind, self.document, self.flow)
            page.scope.hide()
            page.status.hide()
            page.custom.toggled.connect(self.update_context)
            self.pages[node.kind] = page
            self.stack.addWidget(page)
        page = self.pages[node.kind]
        page.scope.setCurrentIndex(page.scope.findData(key))
        self.stack.setCurrentWidget(page)
        self.update_context()

    def update_context(self, *_):
        page = self.stack.currentWidget()
        if (page is self.empty or not self.editor.canvas.isEnabled()
                or self.document.source != self.editor.source_session.source):
            return
        key = self.selector.currentData()
        number = next((i for i, node in enumerate(page.nodes, 1) if node.node_id == key), None)
        if number is None:
            return
        title = "表格" if page.kind == "table" else "图片"
        scope = "本文独立设置" if page.independent.get(key) else "沿用本文默认"
        self.context.setText(f"{title} {number} · {scope}")

    def cursor_changed(self):
        w = self.editor
        if not self.document or self.document.source != w.source_session.source or self.syncing:
            return
        offset = utf16_to_scalar(w.buffer.display, w.editor.textCursor().selectionStart())
        raw = w.buffer.boundaries()[offset]
        node = next(
            (
                n
                for root in self.document.nodes
                for n in root.walk()
                if n.kind in {"table", "image"} and n.span.start <= raw < n.span.end
            ),
            None,
        )
        if node:
            self.selector.setCurrentIndex(self.selector.findData(node.node_id))

    def navigate_selected(self):
        if (not self.document or self.document.source != self.editor.source_session.source
                or not self.editor.canvas.isEnabled()):
            return
        key = self.selector.currentData()
        node = next(
            (n for root in self.document.nodes for n in root.walk() if n.node_id == key), None
        )
        if node:
            self.syncing = True
            try:
                fragment = next(
                    (
                        f
                        for f in self.editor.snapshot.fragments
                        if node.span.start <= f.span.start < node.span.end
                    ),
                    None,
                )
                if fragment:
                    self.editor.select_fragment(fragment)
                else:
                    self.editor.navigate_span(node.span)
            finally:
                self.syncing = False

    def changes(self):
        changes = {}
        for kind, page in self.pages.items():
            try:
                result = page.configuration()
            except ValueError:
                self.selector.setCurrentIndex(self.selector.findData(page.current_key))
                raise
            changes[kind + "_overrides"] = result[kind + "_overrides"]
            if kind == "image":
                changes["images"] = result["images"]
        return changes

    def has_pending(self):
        try:
            return any(getattr(self.flow, key) != value for key, value in self.changes().items())
        except (ValueError, TypeError):
            return True

    def apply(self):
        try:
            w = self.editor
            if (
                not self.document
                or self.document.source != w.source_session.source
                or not w.canvas.isEnabled()
            ):
                raise ValueError("文档正在更新，请在预览完成后应用属性。")
            if w.flow != self.flow:
                raise ValueError("文档参数已变化，请重新选择元素后再修改。")
            flow = replace(w.flow, **self.changes())
            if flow != w.flow:
                w.flow = flow
                w.mark_dirty()
                w.schedule_layout()
            self.error.setStyleSheet("color: #236747;")
            self.error.setText("元素属性已应用，随当前项目保存。")
            return True
        except (ValueError, TypeError) as error:
            self.error.setStyleSheet("color: #b43d3d;")
            self.error.setText(str(error))
            return False

    def discard(self):
        self.clear_pages()
        self.flow = self.editor.flow
        self.error.clear()
        self.select_item()

    def apply_defaults(self):
        try:
            if self.has_pending():
                raise ValueError("请先应用或取消右侧尚未应用的元素属性。")
            defaults, warning = GlobalDefaultsStore().load()
            if warning:
                raise ValueError(warning)
            if self.editor.run_path.endswith(".inkfont") and defaults.mode != "markdown":
                raise ValueError("当前字体包文档需要 Markdown 模式，请先调整全局默认。")
            apply_to_document(self.editor, defaults)
            self.error.setStyleSheet("color: #236747;")
            self.error.setText("默认排版参数已用于本文；当前模板、纸张、独立设置和字体保留。")
        except (ValueError, TypeError) as error:
            self.error.setStyleSheet("color: #b43d3d;")
            self.error.setText(str(error))
