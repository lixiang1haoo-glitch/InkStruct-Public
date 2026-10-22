"""Three-pane template GUI over the existing immutable template draft operations."""

from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from PySide6 import QtCore, QtGui, QtWidgets

from ..document.flow_template import NamedField, PageLayout, TextFrame
from ..document.template import Region
from ..document.template_authoring import parse_template, template_json


class FieldDeclarationDialog(QtWidgets.QDialog):
    def __init__(self, field, parent=None):
        super().__init__(parent)
        self.original = field
        self.setWindowTitle("字段声明 · 不填写文档内容")
        form = QtWidgets.QFormLayout(self)
        self.label = QtWidgets.QLineEdit(field.label)
        form.addRow("显示名称", self.label)
        self.kind = QtWidgets.QComboBox()
        for title, key in [
            ("Markdown", "markdown"),
            ("文本", "text"),
            ("数值", "number"),
            ("日期", "date"),
        ]:
            self.kind.addItem(title, key)
        self.kind.setCurrentIndex(self.kind.findData(field.value_type))
        form.addRow("内容类型", self.kind)
        self.required = QtWidgets.QCheckBox("必填")
        self.required.setChecked(field.required)
        form.addRow(self.required)
        identity = QtWidgets.QLabel(
            "稳定标识：" + field.field_id + "\n改显示名不改标识，也不自动推断正文对应。"
        )
        identity.setTextFormat(QtCore.Qt.PlainText)
        form.addRow(identity)
        self.error = QtWidgets.QLabel()
        self.error.setWordWrap(True)
        form.addRow(self.error)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def configuration(self):
        return replace(
            self.original,
            label=self.label.text(),
            value_type=self.kind.currentData(),
            required=self.required.isChecked(),
        )

    def accept(self):
        try:
            self.configuration()
        except (ValueError, TypeError) as error:
            self.error.setText(str(error))
            return
        super().accept()


class PageTree(QtWidgets.QTreeWidget):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.setHeaderHidden(True)
        self.setDragDropMode(QtWidgets.QAbstractItemView.InternalMove)
        self.setDefaultDropAction(QtCore.Qt.MoveAction)

    def dropEvent(self, event):
        source = self.currentItem()
        target = self.itemAt(event.position().toPoint())
        if source is None or source.parent() is None or target is None:
            event.ignore()
            return
        group = source.parent()
        if (
            group.data(0, QtCore.Qt.UserRole) == "unused"
            or target not in (group, source)
            and target.parent() is not group
        ):
            event.ignore()
            return
        if not self.owner.flush():
            event.ignore()
            return
        super().dropEvent(event)
        key = group.data(0, QtCore.Qt.UserRole)
        values = tuple(
            group.child(i).data(0, QtCore.Qt.UserRole)[0] for i in range(group.childCount())
        )
        self.owner.guard(lambda: self.owner.commit(replace(self.owner.template, **{key: values})))


def interactive_canvas(owner):
    from .flow_template_designer import FlowCanvas

    class Canvas(FlowCanvas):
        def __init__(self):
            super().__init__(owner)
            self.setFocusPolicy(QtCore.Qt.StrongFocus)
            self.start = self.original = self.ghost = None
            self.resize_drag = False

        def millimeters(self, pos):
            t = owner.template
            scale = min((self.width() - 20) / t.width_mm, (self.height() - 20) / t.height_mm)
            return QtCore.QPointF((pos.x() - 10) / scale, (pos.y() - 10) / scale)

        def mousePressEvent(self, event):
            if (
                event.button() != QtCore.Qt.LeftButton
                or owner.template.kind != "custom"
                or not owner.flush()
            ):
                return
            self.setFocus()
            self.start = self.millimeters(event.position())
            if owner.draw_role:
                self.original = None
                return
            selected = None
            for frame in reversed(owner.current_layout().frames):
                r = frame.region
                if QtCore.QRectF(r.x_mm, r.y_mm, r.width_mm, r.height_mm).contains(self.start):
                    selected = frame
                    break
            owner.select_frame(selected.frame_id if selected else None)
            self.original = selected
            if selected:
                r = selected.region
                self.resize_drag = (
                    abs(self.start.x() - r.x_mm - r.width_mm) < 3
                    and abs(self.start.y() - r.y_mm - r.height_mm) < 3
                )

        def mouseMoveEvent(self, event):
            if self.start is None:
                return
            point = self.millimeters(event.position())
            if owner.draw_role:
                self.ghost = QtCore.QRectF(self.start, point).normalized()
            elif self.original:
                r = self.original.region
                dx, dy = point.x() - self.start.x(), point.y() - self.start.y()
                self.ghost = (
                    QtCore.QRectF(
                        r.x_mm, r.y_mm, max(0.1, r.width_mm + dx), max(0.1, r.height_mm + dy)
                    )
                    if self.resize_drag
                    else QtCore.QRectF(r.x_mm + dx, r.y_mm + dy, r.width_mm, r.height_mm)
                )
            self.update()

        def mouseReleaseEvent(self, event):
            rect = self.ghost
            self.start = self.ghost = None
            if rect:
                values = [round(v, 3) for v in (rect.x(), rect.y(), rect.width(), rect.height())]
                if owner.draw_role:
                    role = owner.draw_role
                    owner.draw_role = None
                    owner.guard(lambda: owner.create_frame(role, values))
                elif self.original:
                    frame = self.original
                    owner.guard(
                        lambda: owner.replace_frame(
                            replace(frame, region=Region(frame.region.name, *values))
                        )
                    )
            self.original = None
            self.update()

        def keyPressEvent(self, event):
            if event.key() == QtCore.Qt.Key_Delete:
                owner.guard(owner.delete_selected_frame)
                return
            super().keyPressEvent(event)

        def paintEvent(self, event):
            super().paintEvent(event)
            frame = owner.selected_frame()
            rect = self.ghost
            if rect is None and frame:
                r = frame.region
                rect = QtCore.QRectF(r.x_mm, r.y_mm, r.width_mm, r.height_mm)
            if rect:
                painter = QtGui.QPainter(self)
                scale = min(
                    (self.width() - 20) / owner.template.width_mm,
                    (self.height() - 20) / owner.template.height_mm,
                )
                painter.translate(10, 10)
                painter.scale(scale, scale)
                painter.setPen(QtGui.QPen(QtGui.QColor("#1d4ed8"), 1))
                painter.drawRect(rect)
                painter.fillRect(
                    QtCore.QRectF(rect.right() - 1.2, rect.bottom() - 1.2, 2.4, 2.4),
                    QtGui.QColor("#1d4ed8"),
                )

    return Canvas()


class WorkbenchUI:
    def __init__(self, template=None, parent=None, *, editor=None, document_mode=True):
        self.ui_ready = False
        self.ui_loading = False
        self.selected_frame_id = None
        self.draw_role = None
        self.editor_context = editor
        self.document_mode = document_mode
        super().__init__(template, parent)
        self.setWindowTitle(
            "模板工作台 · 当前文档布局" if document_mode else "模板工作台 · 可复用模板副本"
        )
        # Retire the old tabbed forms but retain their draft commands for compatibility.
        self.tabs.hide()
        old = self.layout()
        footer = old.itemAt(old.count() - 1).layout()
        for i in range(footer.count()):
            if footer.itemAt(i).widget():
                footer.itemAt(i).widget().hide()
        root = QtWidgets.QWidget()
        col = QtWidgets.QVBoxLayout(root)
        heading = QtWidgets.QHBoxLayout()
        heading.addWidget(QtWidgets.QLabel("模板名称"))
        heading.addWidget(self.name, 1)
        self.name.editingFinished.connect(self.flush)
        for title, callback in [
            ("撤销", lambda: self.history(False)),
            ("重做", lambda: self.history(True)),
            ("试排当前文档" if editor else "示例预览", self.trial),
        ]:
            b = QtWidgets.QPushButton(title)
            b.clicked.connect(callback)
            heading.addWidget(b)
        more = QtWidgets.QToolButton()
        more.setText("更多操作")
        more.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        menu = QtWidgets.QMenu(more)
        menu.addAction("高级 JSON…", self.edit_json)
        menu.addAction("另存可复用模板副本…", self.save)
        menu.addAction(
            "复制全部字段骨架",
            lambda: QtWidgets.QApplication.clipboard().setText(self.template.skeleton()),
        )
        more.setMenu(menu)
        heading.addWidget(more)
        col.addLayout(heading)
        self.scope_label = QtWidgets.QLabel(
            "只修改本份文档的布局；确认后可撤销。"
            if document_mode
            else "编辑模板副本，另存新文件；不改变当前文档和全局默认。"
        )
        self.scope_label.setWordWrap(True)
        if self.template.migration:
            self.scope_label.setText(
                self.scope_label.text()
                + "\n显式迁移副本：仅复制布局；原正文与绑定保留，锚点、倍率和页面策略需人工核对。"
            )
        col.addWidget(self.scope_label)
        self.splitter = QtWidgets.QSplitter()
        col.addWidget(self.splitter, 1)
        left = QtWidgets.QWidget()
        left_col = QtWidgets.QVBoxLayout(left)
        left_col.addWidget(QtWidgets.QLabel("页面组织"))
        self.page_tree = PageTree(self)
        self.page_tree.currentItemChanged.connect(self.tree_selected)
        left_col.addWidget(self.page_tree, 1)
        row = QtWidgets.QHBoxLayout()
        for title, callback in [
            ("上移", lambda: self.tree_move(-1)),
            ("下移", lambda: self.tree_move(1)),
            ("移除引用", self.tree_remove),
        ]:
            b = QtWidgets.QPushButton(title)
            b.clicked.connect(callback)
            row.addWidget(b)
        left_col.addLayout(row)
        add = QtWidgets.QToolButton()
        add.setText("添加布局…")
        add.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        menu = QtWidgets.QMenu(add)
        menu.addAction("新增空布局", self.new_layout)
        menu.addAction("引用现有布局", self.reference_layout)
        menu.addAction("复制为独立布局", self.duplicate_layout)
        menu.addAction("导入 PDF 页面…", self.import_pdf)
        add.setMenu(menu)
        left_col.addWidget(add)
        self.finish.setParent(left)
        self.finish.toggled.disconnect()
        self.finish.toggled.connect(self.finish_changed)
        left_col.addWidget(self.finish)
        self.loop_info = QtWidgets.QLabel("循环组末尾 → 返回本组第一张布局；实际页码连续递增。")
        self.loop_info.setWordWrap(True)
        left_col.addWidget(self.loop_info)
        self.splitter.addWidget(left)
        center = QtWidgets.QWidget()
        center_col = QtWidgets.QVBoxLayout(center)
        self.layout_heading = QtWidgets.QLabel()
        self.layout_heading.setTextFormat(QtCore.Qt.PlainText)
        center_col.addWidget(self.layout_heading)
        tools = QtWidgets.QHBoxLayout()
        for title, role in [
            ("选择", None),
            ("正文框", "body"),
            ("字段框", "field"),
            ("页码", "page_number"),
        ]:
            b = QtWidgets.QPushButton(title)
            b.clicked.connect(lambda checked=False, role=role: self.start_draw(role))
            tools.addWidget(b)
        center_col.addLayout(tools)
        self.interactive = interactive_canvas(self)
        center_col.addWidget(self.interactive, 1)
        self.canvas = self.interactive
        self.hint = QtWidgets.QLabel("点击选择；拖动移动；右下角拖动调整尺寸。正文按编号连接。")
        self.hint.setWordWrap(True)
        center_col.addWidget(self.hint)
        self.splitter.addWidget(center)
        self.property_tabs = QtWidgets.QTabWidget()
        properties = QtWidgets.QWidget()
        self.property_form = QtWidgets.QVBoxLayout(properties)
        self.paper_box = QtWidgets.QGroupBox("纸张与布局")
        paper_form = QtWidgets.QFormLayout(self.paper_box)
        self.paper_form = paper_form
        for key, title in [
            ("width", "纸张宽度"),
            ("height", "纸张高度"),
            ("top", "上边距"),
            ("right", "右边距"),
            ("bottom", "下边距"),
            ("left", "左边距"),
        ]:
            paper_form.addRow(title, self.paper[key])
            self.paper[key].editingFinished.connect(self.flush)
        self.margin_rows = [self.paper[k] for k in ("top", "right", "bottom", "left")]
        self.mode_choice = QtWidgets.QComboBox()
        self.mode_choice.addItem("预印纸", "preprinted")
        self.mode_choice.addItem("空白纸", "blank")
        self.mode_choice.setToolTip("预印纸的背景仅参考；空白纸绘制明确配置的框线。")
        paper_form.addRow("用纸方式", self.mode_choice)
        self.mode_choice.currentIndexChanged.connect(self.flush)
        self.offset_controls = {}
        for key, title in [("offset_x_mm", "横向校准"), ("offset_y_mm", "纵向校准")]:
            c = QtWidgets.QDoubleSpinBox()
            c.setRange(-2000, 2000)
            c.setDecimals(4)
            c.setSuffix(" mm")
            c.editingFinished.connect(self.flush)
            self.offset_controls[key] = c
            paper_form.addRow(title, c)
        self.property_form.addWidget(self.paper_box)
        self.layout_box = QtWidgets.QGroupBox("当前布局")
        layout_form = QtWidgets.QVBoxLayout(self.layout_box)
        self.layout_label = QtWidgets.QLineEdit()
        self.layout_label.setPlaceholderText("布局名称")
        self.layout_label.editingFinished.connect(self.flush)
        layout_form.addWidget(self.layout_label)
        for title, callback in [
            ("选择图片背景…", self.import_image),
            ("清除背景", lambda: self.guard(lambda: self.update_layout(background=None))),
        ]:
            b = QtWidgets.QPushButton(title)
            b.clicked.connect(callback)
            layout_form.addWidget(b)
        self.property_form.addWidget(self.layout_box)
        self.frame_box = QtWidgets.QGroupBox("所选文本框")
        frame_form = QtWidgets.QFormLayout(self.frame_box)
        self.frame_name = QtWidgets.QLineEdit()
        self.frame_name.editingFinished.connect(self.flush)
        frame_form.addRow("框名称", self.frame_name)
        self.frame_order = QtWidgets.QSpinBox()
        self.frame_order.setRange(1, 10000)
        self.frame_order.editingFinished.connect(self.flush)
        frame_form.addRow("正文顺序", self.frame_order)
        self.field_choice = QtWidgets.QComboBox()
        self.field_choice.setSizeAdjustPolicy(
            QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon
        )
        self.field_choice.setMinimumContentsLength(10)
        self.field_choice.currentIndexChanged.connect(self.field_selected)
        frame_form.addRow("引用字段", self.field_choice)
        self.new_field_button = QtWidgets.QPushButton("新建字段声明…")
        self.new_field_button.clicked.connect(lambda: self.declare_field(True))
        frame_form.addRow(self.new_field_button)
        self.geometry_controls = {}
        for key, title in [
            ("x_mm", "左边位置"),
            ("y_mm", "上边位置"),
            ("width_mm", "宽度"),
            ("height_mm", "高度"),
        ]:
            c = QtWidgets.QDoubleSpinBox()
            c.setRange(0 if key in {"x_mm", "y_mm"} else 0.001, 2000)
            c.setDecimals(4)
            c.setSuffix(" mm")
            c.editingFinished.connect(self.flush)
            frame_form.addRow(title, c)
            self.geometry_controls[key] = c
        self.frame_list = QtWidgets.QListWidget()
        self.frame_list.setMaximumHeight(100)
        self.frame_list.currentRowChanged.connect(self.frame_list_selected)
        self.property_form.addWidget(self.frame_list)
        self.property_form.addWidget(self.frame_box)
        delete = QtWidgets.QPushButton("删除所选框")
        self.delete_frame_button = delete
        delete.clicked.connect(lambda: self.guard(self.delete_selected_frame))
        self.property_form.addWidget(delete)
        self.property_form.addStretch()
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(properties)
        self.property_scroll = scroll
        self.property_tabs.addTab(scroll, "属性")
        declarations = QtWidgets.QWidget()
        declarations_col = QtWidgets.QVBoxLayout(declarations)
        declarations_col.addWidget(QtWidgets.QLabel("声明字段；文档内容在主界面填写。"))
        self.field_list = QtWidgets.QListWidget()
        declarations_col.addWidget(self.field_list)
        for title, callback in [
            ("新增字段", lambda: self.declare_field(True)),
            ("编辑声明", lambda: self.declare_field(False)),
            ("删除字段", self.delete_declaration),
            ("复制字段写法", self.copy_declaration),
        ]:
            b = QtWidgets.QPushButton(title)
            b.clicked.connect(callback)
            declarations_col.addWidget(b)
        self.property_tabs.addTab(declarations, "字段声明")
        self.property_tabs.setMinimumWidth(340)
        self.splitter.addWidget(self.property_tabs)
        self.splitter.setSizes([240, 580, 290])
        self.template_status = QtWidgets.QLabel()
        self.template_status.setWordWrap(True)
        col.addWidget(self.template_status)
        self.error.setParent(root)
        col.addWidget(self.error)
        bottom = QtWidgets.QHBoxLayout()
        bottom.addStretch()
        cancel = QtWidgets.QPushButton("取消")
        cancel.clicked.connect(self.reject)
        bottom.addWidget(cancel)
        self.confirm = QtWidgets.QPushButton("应用到当前文档" if document_mode else "保存为新模板…")
        self.confirm.clicked.connect(self.accept)
        bottom.addWidget(self.confirm)
        col.addLayout(bottom)
        old.addWidget(root, 1)
        self.ui_root, self.left_panel, self.center_tools = root, left, tools
        self.ui_ready = True
        for button in self.ui_root.findChildren(QtWidgets.QPushButton):
            button.setAutoDefault(False)
        self.refresh()

    def finish_changed(self, value):
        if not self.ui_loading and self.flush():
            self.commit(replace(self.template, finish_cycle=value))

    def import_pdf(self):
        if self.flush():
            previous = len(self.template.layouts)
            super().import_pdf()
            if len(self.template.layouts) > previous:
                self.layouts.setCurrentRow(previous)
                self.refresh()

    def import_image(self):
        if self.flush():
            super().import_image()

    def guard(self, call):
        if not self.ui_ready or self.flush():
            super().guard(call)

    def refresh(self):
        self.ui_loading = True
        super().refresh()
        if not self.ui_ready:
            self.ui_loading = False
            return
        t = self.template
        layout = self.current_layout()
        chosen = layout.layout_id if layout else None
        self.page_tree.clear()
        used = (*t.start_pages, *t.loop_pages)
        for key, title, ids in [
            ("start_pages", "起始页组 · 顺序出现一次", t.start_pages),
            ("loop_pages", "循环页组 · 顺序循环", t.loop_pages),
            (
                "unused",
                "未使用布局",
                tuple(p.layout_id for p in t.layouts if p.layout_id not in used),
            ),
        ]:
            group = QtWidgets.QTreeWidgetItem([title])
            group.setData(0, QtCore.Qt.UserRole, key)
            group.setFlags(group.flags() & ~QtCore.Qt.ItemIsDragEnabled)
            self.page_tree.addTopLevelItem(group)
            for index, identity in enumerate(ids):
                p = next(p for p in t.layouts if p.layout_id == identity)
                count = used.count(identity)
                item = QtWidgets.QTreeWidgetItem(
                    [p.label + (f" · 共用 {count} 处" if count > 1 else "")]
                )
                item.setData(0, QtCore.Qt.UserRole, (identity, key, index))
                item.setFlags(
                    (item.flags() | QtCore.Qt.ItemIsDragEnabled) & ~QtCore.Qt.ItemIsDropEnabled
                )
                group.addChild(item)
                if identity == chosen:
                    self.page_tree.setCurrentItem(item)
            group.setExpanded(True)
        self.left_panel.setVisible(t.kind == "custom")
        self.property_tabs.setTabVisible(1, t.kind == "custom")
        self.layout_box.setVisible(t.kind == "custom")
        self.frame_list.setVisible(t.kind == "custom")
        for i in range(self.center_tools.count()):
            self.center_tools.itemAt(i).widget().setVisible(t.kind == "custom")
        self.layout_heading.setText(
            (
                "重复单页 · 正文自动分页"
                if t.kind == "simple"
                else f"布局：{layout.label} · 修改影响全部引用"
            )
            if layout
            else ""
        )
        self.layout_label.setText(layout.label if layout else "")
        self.layout_initial = self.layout_label.text()
        self.mode_choice.setCurrentIndex(self.mode_choice.findData(t.mode))
        self.paper_initial = {k: c.value() for k, c in self.paper.items()}
        self.offset_initial = {}
        for k, c in self.offset_controls.items():
            c.setValue(getattr(t, k))
            self.offset_initial[k] = c.value()
        self.frame_list.clear()
        if layout:
            for f in layout.frames:
                self.frame_list.addItem(
                    (
                        f"{f.order}. 正文 · "
                        if f.role == "body"
                        else "字段 · "
                        if f.role == "field"
                        else "页码 · "
                    )
                    + f.label
                )
        self.field_list.clear()
        for f in t.fields:
            self.field_list.addItem(f.label + (" *" if f.required else "") + f" · {f.field_id}")
        self.field_choice.clear()
        for f in t.fields:
            self.field_choice.addItem(f.label, f.field_id)
        self.update_frame_controls()
        self.template_status.setText("布局结构有效；实际内容、字形与越框问题请通过试排检查。")
        self.hint.setText(
            "简单模板只设置纸张与边距。预览采用当前排版样式；字号、行距仍由排版设置管理。"
            if t.kind == "simple"
            else "点击选择；拖动移动；右下角拖动调整尺寸。正文按编号连接。"
        )
        self.ui_loading = False
        self.canvas.update()

    def selected_frame(self):
        p = self.current_layout()
        return (
            next((f for f in p.frames if f.frame_id == self.selected_frame_id), None) if p else None
        )

    def update_frame_controls(self):
        frame = self.selected_frame()
        self.frame_box.setVisible(frame is not None and self.template.kind == "custom")
        self.paper_box.setVisible(frame is None)
        self.layout_box.setVisible(frame is None and self.template.kind == "custom")
        self.delete_frame_button.setVisible(frame is not None and self.template.kind == "custom")
        for control in self.margin_rows:
            control.setVisible(self.template.kind == "simple")
            self.paper_form.labelForField(control).setVisible(self.template.kind == "simple")
        if frame:
            self.frame_name.setText(frame.label)
            self.frame_order.setValue(frame.order)
            self.field_choice.setCurrentIndex(self.field_choice.findData(frame.field_id))
            for key, c in self.geometry_controls.items():
                c.setValue(getattr(frame.region, key))
            self.geometry_initial = {k: c.value() for k, c in self.geometry_controls.items()}
            self.frame_list.setCurrentRow(
                next(
                    i
                    for i, f in enumerate(self.current_layout().frames)
                    if f.frame_id == frame.frame_id
                )
            )
            self.frame_order.setEnabled(frame.role == "body")
            self.field_choice.setEnabled(frame.role == "field")
            self.new_field_button.setVisible(frame.role == "field")

    def flush(self):
        if not self.ui_ready or self.ui_loading:
            return True
        try:
            t = self.template
            changes = {"name": self.name.text()}
            for k, dest in [("width", "width_mm"), ("height", "height_mm")]:
                if self.paper[k].value() != self.paper_initial[k]:
                    changes[dest] = self.paper[k].value()
            margins = list(t.margins_mm)
            for i, k in enumerate(("top", "right", "bottom", "left")):
                if self.paper[k].value() != self.paper_initial[k]:
                    margins[i] = self.paper[k].value()
            changes["margins_mm"] = tuple(margins)
            changes["mode"] = self.mode_choice.currentData()
            changes.update(
                {
                    k: c.value()
                    for k, c in self.offset_controls.items()
                    if c.value() != self.offset_initial[k]
                }
            )
            p = self.current_layout()
            frame = self.selected_frame()
            if p and t.kind == "custom":
                frames = p.frames
                if frame:
                    values = {
                        k: c.value()
                        for k, c in self.geometry_controls.items()
                        if c.value() != self.geometry_initial[k]
                    }
                    updated = replace(
                        frame,
                        label=self.frame_name.text(),
                        order=self.frame_order.value() if frame.role == "body" else frame.order,
                        field_id=self.field_choice.currentData()
                        if frame.role == "field"
                        else frame.field_id,
                        region=replace(frame.region, **values),
                    )
                    frames = tuple(updated if f.frame_id == frame.frame_id else f for f in frames)
                updated_layout = replace(p, label=self.layout_label.text(), frames=frames)
                changes["layouts"] = tuple(
                    updated_layout if q.layout_id == p.layout_id else q for q in t.layouts
                )
            candidate = replace(t, **changes)
            if candidate != t:
                self.commit(candidate)
            self.error.clear()
            return True
        except (ValueError, TypeError) as error:
            self.error.setText(
                "尚未应用的无效输入：" + str(error) + "。请修正后继续，或取消整个草稿。"
            )
            return False

    def select_frame(self, identity):
        if not self.flush():
            return
        self.ui_loading = True
        self.selected_frame_id = identity
        self.update_frame_controls()
        self.ui_loading = False
        if identity:
            self.property_tabs.setCurrentIndex(0)
            self.property_scroll.ensureWidgetVisible(self.frame_box)
        self.canvas.update()

    def frame_list_selected(self, index):
        if not self.ui_loading and 0 <= index < len(self.current_layout().frames):
            self.select_frame(self.current_layout().frames[index].frame_id)

    def field_selected(self):
        if not self.ui_loading:
            self.flush()

    def tree_selected(self, item, previous=None):
        if self.ui_loading or item is None or item.parent() is None:
            return
        data = item.data(0, QtCore.Qt.UserRole)
        if not self.flush():
            self.ui_loading = True
            self.page_tree.setCurrentItem(previous)
            self.ui_loading = False
            return
        self.selected_frame_id = None
        index = next(
            i for i, p in enumerate(self.template.effective_layouts) if p.layout_id == data[0]
        )
        self.layouts.setCurrentRow(index)
        self.refresh()

    def tree_data(self):
        item = self.page_tree.currentItem()
        return item.data(0, QtCore.Qt.UserRole) if item and item.parent() else None

    def tree_move(self, direction):
        data = self.tree_data()
        if data and data[1] != "unused" and self.flush():
            _identity, key, index = data
            values = list(getattr(self.template, key))
            if 0 <= index + direction < len(values):
                values[index], values[index + direction] = values[index + direction], values[index]
                self.guard(lambda: self.commit(replace(self.template, **{key: tuple(values)})))

    def tree_remove(self):
        data = self.tree_data()
        if not data or not self.flush():
            return
        identity, key, index = data
        if key == "unused":
            self.guard(
                lambda: self.commit(
                    replace(
                        self.template,
                        layouts=tuple(p for p in self.template.layouts if p.layout_id != identity),
                    )
                )
            )
        else:
            values = list(getattr(self.template, key))
            values.pop(index)
            self.guard(lambda: self.commit(replace(self.template, **{key: tuple(values)})))

    def destination_group(self):
        value, ok = QtWidgets.QInputDialog.getItem(
            self, "加入页面组", "放置位置", ["循环页组", "起始页组"], 0, False
        )
        return ("loop_pages" if value == "循环页组" else "start_pages") if ok else None

    def new_layout(self):
        if not self.flush():
            return
        key = self.destination_group()
        if key:
            p = PageLayout(
                "layout-" + uuid4().hex[:12], "布局 " + str(len(self.template.layouts) + 1)
            )
            self.commit(
                replace(
                    self.template,
                    layouts=(*self.template.layouts, p),
                    **{key: (*getattr(self.template, key), p.layout_id)},
                )
            )
            self.layouts.setCurrentRow(len(self.template.layouts) - 1)
            self.refresh()

    def reference_layout(self):
        if not self.flush():
            return
        layouts = self.template.layouts
        labels = [f"{p.label} · {p.layout_id}" for p in layouts]
        value, ok = QtWidgets.QInputDialog.getItem(
            self, "引用共用布局", "修改该布局将影响全部引用", labels, 0, False
        )
        key = self.destination_group() if ok else None
        if key:
            p = layouts[labels.index(value)]
            self.guard(
                lambda: self.commit(
                    replace(self.template, **{key: (*getattr(self.template, key), p.layout_id)})
                )
            )

    def duplicate_layout(self):
        if not self.flush():
            return
        p = self.current_layout()
        key = self.destination_group()
        if key and p:
            duplicate = replace(p, layout_id="layout-" + uuid4().hex[:12], label=p.label + " 副本")
            self.commit(
                replace(
                    self.template,
                    layouts=(*self.template.layouts, duplicate),
                    **{key: (*getattr(self.template, key), duplicate.layout_id)},
                )
            )
            self.layouts.setCurrentRow(len(self.template.layouts) - 1)
            self.refresh()

    def start_draw(self, role):
        if self.flush():
            self.draw_role = role
            self.hint.setText(
                "在画布拖出新框；点击“选择”退出绘制。"
                if role
                else "点击选框，拖动移动或调整右下角尺寸。"
            )

    def create_frame(self, role, values):
        fid = ""
        if role == "field":
            labels = [f.label + " · " + f.field_id for f in self.template.fields] + ["新建字段…"]
            value, ok = QtWidgets.QInputDialog.getItem(
                self, "引用字段", "选择字段声明", labels, 0, False
            )
            if not ok:
                return
            if value == labels[-1]:
                field = self.declare_field(True)
                if not field:
                    return
                fid = field.field_id
            else:
                fid = self.template.fields[labels.index(value)].field_id
        p = self.current_layout()
        key = "frame-" + uuid4().hex[:12]
        order = max((f.order for f in p.body_frames), default=0) + 1
        frame = TextFrame(
            key,
            "正文框" if role == "body" else "字段框" if role == "field" else "页码框",
            Region(key, *values),
            role,
            order,
            fid,
        )
        self.selected_frame_id = key
        self.update_layout(frames=(*p.frames, frame))

    def replace_frame(self, frame):
        self.update_layout(
            frames=tuple(
                frame if f.frame_id == frame.frame_id else f for f in self.current_layout().frames
            )
        )

    def delete_selected_frame(self):
        if self.flush() and self.selected_frame():
            self.update_layout(
                frames=tuple(
                    f for f in self.current_layout().frames if f.frame_id != self.selected_frame_id
                )
            )

    def declare_field(self, new):
        if not self.flush():
            return None
        index = self.field_list.currentRow()
        if not new and index < 0:
            self.error.setText("请先选择字段声明。")
            return None
        field = (
            NamedField("field_" + uuid4().hex[:8], "新字段") if new else self.template.fields[index]
        )
        dialog = FieldDeclarationDialog(field, self)
        try:
            if dialog.exec() == QtWidgets.QDialog.Accepted:
                field = dialog.configuration()
                fields = (
                    (*self.template.fields, field)
                    if new
                    else tuple(
                        field if i == index else f for i, f in enumerate(self.template.fields)
                    )
                )
                selected = self.selected_frame()
                changes = {"fields": fields}
                if new and selected and selected.role == "field":
                    p = self.current_layout()
                    p = replace(
                        p,
                        frames=tuple(
                            replace(f, field_id=field.field_id)
                            if f.frame_id == selected.frame_id
                            else f
                            for f in p.frames
                        ),
                    )
                    changes["layouts"] = tuple(
                        p if q.layout_id == p.layout_id else q for q in self.template.layouts
                    )
                self.commit(replace(self.template, **changes))
                return field
        except (ValueError, TypeError) as error:
            self.error.setText(str(error))
        finally:
            dialog.deleteLater()
        return None

    def delete_declaration(self):
        index = self.field_list.currentRow()
        if index >= 0 and self.flush():
            key = self.template.fields[index].field_id
            if any(f.field_id == key for p in self.template.layouts for f in p.frames):
                self.error.setText("该字段仍被文本框引用，请先调整引用。")
            else:
                self.commit(
                    replace(
                        self.template,
                        fields=tuple(f for f in self.template.fields if f.field_id != key),
                    )
                )

    def copy_declaration(self):
        from ..document.named_fields import field_example

        index = self.field_list.currentRow()
        if index >= 0:
            QtWidgets.QApplication.clipboard().setText(
                field_example(self.template.fields[index].field_id)
            )

    def edit_json(self):
        if not self.flush():
            return
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("高级 JSON · 保留完整协议校验")
        dialog.resize(800, 650)
        col = QtWidgets.QVBoxLayout(dialog)
        text = QtWidgets.QPlainTextEdit(template_json(self.template))
        col.addWidget(text)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        col.addWidget(buttons)
        try:
            if dialog.exec() == QtWidgets.QDialog.Accepted:
                self.guard(lambda: self.commit(parse_template(text.toPlainText())))
        finally:
            dialog.deleteLater()

    def trial(self):
        if not self.flush():
            return
        from .template_trial import TemplateTrialDialog

        try:
            dialog = TemplateTrialDialog(self.template, self.editor_context, self)
            if dialog.exec() == QtWidgets.QDialog.Accepted and dialog.selected_diagnostic:
                diagnostic = dialog.selected_diagnostic
                target = getattr(diagnostic, "target", None)
                if target:
                    self.focus_target(target)
                elif self.editor_context:
                    self.editor_context.navigate_span(diagnostic.span)
            dialog.deleteLater()
        except (ValueError, TypeError) as error:
            self.error.setText(str(error))

    def save(self):
        if not self.flush():
            return False
        from .template_manager import remember_template

        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "保存为新模板（不覆盖原文件）", "", "模板 (*.json)"
        )
        if not path:
            return False
        written = False
        try:
            with Path(path).open("x", encoding="utf-8") as stream:
                stream.write(template_json(self.template))
            written = True
            remember_template(path)
            from ..resource_catalog import TemplateStore, workspace_for
            TemplateStore(workspace_for(self.editor_context or self) / 'templates').add(path)
            self.error.setText("已另存并加入模板库：" + path + "；当前文档与默认设置未改变。")
            return True
        except (ValueError, OSError) as error:
            self.error.setText(("模板文件已另存，但未加入模板库；可稍后显式导入：" + path + "\n" if written else "") + str(error))
            return False

    def configuration(self):
        if not self.flush():
            raise ValueError(self.error.text())
        return self.template

    def focus_target(self, target):
        super().focus_target(target)
        p = self.current_layout()
        self.selected_frame_id = (
            next(
                (
                    f.frame_id
                    for f in p.frames
                    if f.frame_id == target.region or f.field_id == target.slot_id
                ),
                None,
            )
            if p
            else None
        )
        self.refresh()
        if target.slot_id and not self.selected_frame_id:
            self.property_tabs.setCurrentIndex(1)

    def history(self, redo):
        if self.ui_ready:
            # Undo also discards a currently invalid property draft explicitly.
            self.ui_loading = True
            super().history(redo)
            self.refresh()
        else:
            super().history(redo)

    def accept(self):
        if self.flush() and (self.document_mode or self.save()):
            QtWidgets.QDialog.accept(self)
