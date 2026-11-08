"""Generic millimetre geometry editor sharing the agent JSON contract."""

import json
from dataclasses import replace
from pathlib import Path

from PySide6 import QtCore, QtWidgets

from ..document.template_authoring import (
    import_reference_image,
    new_template,
    parse_template,
    read_template,
    template_json,
)
from ..document.template_validation import TemplateValidationError, json_value_span
from .template_canvas import TemplateCanvas
from .template_geometry import arrange_selection
from .template_viewport import TemplateViewport


class TemplateDesignerDialog(QtWidgets.QDialog):
    def __init__(self, template=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("模板设计 · 画布与毫米坐标")
        self.resize(1120, 820)
        self.valid_template = None
        self._syncing = False
        self._pending = None
        self._from_canvas = False
        layout = QtWidgets.QVBoxLayout(self)
        note = QtWidgets.QLabel(
            "蓝色为流式正文区，橙色为固定填写区，绿色为基线锚点。"
            "先修改属性并点击写入，再在外层窗口绑定 Markdown 内容。所有坐标单位为 mm。"
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        toolbar = QtWidgets.QHBoxLayout()
        for text, callback in (
            ("新建 A4", lambda: self.set_design(new_template())),
            ("导入 JSON…", self.import_file),
            ("导出 JSON…", self.export_file),
            ("内容字段…", self.design_slots),
            ("撤销", lambda: self.json_editor.undo()),
            ("重做", lambda: self.json_editor.redo()),
        ):
            button = QtWidgets.QPushButton(text, self)
            button.clicked.connect(callback)
            toolbar.addWidget(button)
        layout.addLayout(toolbar)
        self.face = QtWidgets.QComboBox(self)
        self.face.addItem("首页", "first")
        self.face.addItem("续页（重复使用）", "continuation")
        self.face.currentIndexChanged.connect(self.refresh)
        toolbar.addWidget(self.face)
        splitter = QtWidgets.QSplitter(self)
        layout.addWidget(splitter, 1)
        tabs = QtWidgets.QTabWidget(splitter)
        self.tabs = tabs
        properties = QtWidgets.QWidget(tabs)
        form = QtWidgets.QVBoxLayout(properties)
        form.addWidget(QtWidgets.QLabel("纸张与模式（预印纸 / 空白纸）"))
        self.page_properties = self.make_table(properties)
        form.addWidget(self.page_properties)
        self.apply_page = QtWidgets.QPushButton("写入纸张属性", properties)
        self.apply_page.clicked.connect(self.write_page)
        form.addWidget(self.apply_page)
        self.element = QtWidgets.QComboBox(properties)
        self.element.currentIndexChanged.connect(self.select_element)
        form.addWidget(self.element)
        self.element_properties = self.make_table(properties)
        form.addWidget(self.element_properties)
        row = QtWidgets.QHBoxLayout()
        self.apply_element = QtWidgets.QPushButton("写入元素属性", properties)
        self.apply_element.clicked.connect(self.write_element)
        row.addWidget(self.apply_element)
        self.remove_element = QtWidgets.QPushButton("删除元素", properties)
        self.remove_element.clicked.connect(self.delete_element)
        row.addWidget(self.remove_element)
        form.addLayout(row)
        row = QtWidgets.QHBoxLayout()
        for key, label in (("reserved", "+ 填写区"), ("anchors", "+ 锚点"), ("rules", "+ 框线")):
            button = QtWidgets.QPushButton(label, properties)
            button.clicked.connect(lambda checked=False, kind=key: self.add_element(kind))
            row.addWidget(button)
        form.addLayout(row)
        copy = QtWidgets.QPushButton("将当前正文宽度同步到另一页", properties)
        copy.clicked.connect(self.copy_body_width)
        form.addWidget(copy)
        tabs.addTab(properties, "属性")
        self.json_editor = QtWidgets.QPlainTextEdit(tabs)
        self.json_editor.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        tabs.addTab(self.json_editor, "JSON / Agent 接口")
        preview_panel = QtWidgets.QWidget(splitter)
        preview_layout = QtWidgets.QVBoxLayout(preview_panel)
        preview_layout.addWidget(QtWidgets.QLabel("几何预览 · 不含实际正文 · 不用于机器导出"))
        canvas_tools = QtWidgets.QHBoxLayout()
        self.canvas_tool = QtWidgets.QComboBox(preview_panel)
        for label, kind in (
            ("选择 / 移动", "select"),
            ("框选元素", "marquee"),
            ("绘制填写区", "reserved"),
            ("放置锚点", "anchors"),
            ("绘制直线", "rules"),
        ):
            self.canvas_tool.addItem(label, kind)
        canvas_tools.addWidget(self.canvas_tool)
        self.snap_grid = QtWidgets.QCheckBox("吸附", preview_panel)
        self.snap_grid.setChecked(True)
        canvas_tools.addWidget(self.snap_grid)
        self.grid_step = QtWidgets.QDoubleSpinBox(preview_panel)
        self.grid_step.setRange(0.1, 20)
        self.grid_step.setDecimals(1)
        self.grid_step.setValue(1)
        self.grid_step.setSuffix(" mm")
        canvas_tools.addWidget(self.grid_step)
        self.show_grid = QtWidgets.QCheckBox("网格", preview_panel)
        self.show_grid.setChecked(True)
        canvas_tools.addWidget(self.show_grid)
        preview_layout.addLayout(canvas_tools)
        self.link_width = QtWidgets.QCheckBox("联动首页 / 续页正文宽度", preview_panel)
        self.link_width.setChecked(True)
        preview_layout.addWidget(self.link_width)
        self.preview = TemplateCanvas(preview_panel)
        self.preview.selected.connect(self.canvas_select)
        self.preview.selection_changed.connect(self.selection_summary)
        self.preview.committed.connect(self.canvas_commit)
        self.preview.status.connect(lambda text: self.error.setText(text))
        for control in (self.snap_grid, self.show_grid, self.link_width):
            control.toggled.connect(self.canvas_options)
        self.grid_step.valueChanged.connect(self.canvas_options)
        self.canvas_tool.currentIndexChanged.connect(self.canvas_options)
        view_tools = QtWidgets.QHBoxLayout()
        view_tools.addWidget(QtWidgets.QLabel("视图", preview_panel))
        self.zoom_control = QtWidgets.QSpinBox(preview_panel)
        self.zoom_control.setRange(50, 600)
        self.zoom_control.setSingleStep(25)
        self.zoom_control.setValue(100)
        self.zoom_control.setSuffix(" %")
        self.zoom_control.setToolTip("相对于适合窗口的页面大小；不改变纸张毫米尺寸。")
        view_tools.addWidget(self.zoom_control)
        self.fit_button = QtWidgets.QPushButton("适合窗口", preview_panel)
        view_tools.addWidget(self.fit_button)
        self.ruler_toggle = QtWidgets.QCheckBox("毫米标尺", preview_panel)
        self.ruler_toggle.setChecked(True)
        view_tools.addWidget(self.ruler_toggle)
        preview_layout.addLayout(view_tools)
        self.canvas_view = TemplateViewport(self.preview, preview_panel)
        self.zoom_control.valueChanged.connect(lambda value: self.canvas_view.set_zoom(value / 100))
        self.canvas_view.zoom_changed.connect(self.zoom_display)
        self.fit_button.clicked.connect(self.canvas_view.fit_page)
        self.ruler_toggle.toggled.connect(self.canvas_view.show_rulers)
        preview_layout.addWidget(self.canvas_view, 1)
        arrange_tools = QtWidgets.QHBoxLayout()
        self.selection_count = QtWidgets.QLabel("未选中元素", preview_panel)
        self.selection_count.setToolTip("属性表只编辑最后选中的元素；拖动和排列作用于整个选区。")
        arrange_tools.addWidget(self.selection_count)
        self.arrange_mode = QtWidgets.QComboBox(preview_panel)
        for label, value in (
            ("左对齐", "left"),
            ("水平居中", "center-x"),
            ("右对齐", "right"),
            ("顶对齐", "top"),
            ("垂直居中", "center-y"),
            ("底对齐", "bottom"),
            ("水平等距", "distribute-x"),
            ("垂直等距", "distribute-y"),
        ):
            self.arrange_mode.addItem(label, value)
        arrange_tools.addWidget(self.arrange_mode)
        self.arrange_button = QtWidgets.QPushButton("应用排列", preview_panel)
        self.arrange_button.clicked.connect(self.arrange_elements)
        arrange_tools.addWidget(self.arrange_button)
        preview_layout.addLayout(arrange_tools)
        hint = QtWidgets.QLabel(
            "Shift 点击多选；框选后可整体移动或排列。单选角点可缩放。Alt 暂停吸附，Esc 取消拖动。"
        )
        hint.setWordWrap(True)
        preview_layout.addWidget(hint)
        background_tools = QtWidgets.QHBoxLayout()
        for label, callback in (
            ("导入当前页底图…", self.import_background),
            ("移除当前页底图", self.clear_background),
        ):
            button = QtWidgets.QPushButton(label, preview_panel)
            button.clicked.connect(callback)
            background_tools.addWidget(button)
        preview_layout.addLayout(background_tools)
        opacity_tools = QtWidgets.QHBoxLayout()
        opacity_tools.addWidget(QtWidgets.QLabel("底图显示", preview_panel))
        self.opacity_control = QtWidgets.QSlider(QtCore.Qt.Horizontal, preview_panel)
        self.opacity_control.setRange(0, 100)
        self.opacity_control.setValue(40)
        self.opacity_label = QtWidgets.QLabel("40 %", preview_panel)
        self.opacity_control.valueChanged.connect(self.opacity_changed)
        opacity_tools.addWidget(self.opacity_control, 1)
        opacity_tools.addWidget(self.opacity_label)
        preview_layout.addLayout(opacity_tools)
        background_note = QtWidgets.QLabel(
            "底图按当前纸张尺寸铺满，仅供对位。Ctrl / ⌘ + 滚轮缩放，中键拖动平移视图。"
        )
        background_note.setWordWrap(True)
        preview_layout.addWidget(background_note)
        splitter.setSizes([550, 500])
        self.error = QtWidgets.QLabel(self)
        self.error.setWordWrap(True)
        self.error.setTextFormat(QtCore.Qt.PlainText)
        layout.addWidget(self.error)
        issue_row = QtWidgets.QHBoxLayout()
        self.issue_picker = QtWidgets.QComboBox()
        self.issue_button = QtWidgets.QPushButton("定位问题对象 / JSON", self)
        self.issue_button.clicked.connect(self.locate_issue)
        issue_row.addWidget(self.issue_picker, 1)
        issue_row.addWidget(self.issue_button)
        layout.addLayout(issue_row)
        self.buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, self
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.json_editor.textChanged.connect(self.refresh)
        self.page_properties.itemChanged.connect(lambda: self.pending(self.page_properties))
        self.element_properties.itemChanged.connect(lambda: self.pending(self.element_properties))
        self.set_design(template or new_template())

    def zoom_display(self, value):
        blocker = QtCore.QSignalBlocker(self.zoom_control)
        self.zoom_control.setValue(round(value * 100))
        del blocker

    def opacity_changed(self, value):
        self.preview.set_background_opacity(value / 100)
        self.opacity_label.setText(f"{value} %")

    def canvas_options(self):
        self.preview.cancel_gesture()
        self.preview.tool = self.canvas_tool.currentData()
        self.preview.snap = self.snap_grid.isChecked()
        self.preview.grid_mm = self.grid_step.value()
        self.preview.grid_visible = self.show_grid.isChecked()
        self.preview.link_body_width = self.link_width.isChecked()
        self.preview.update()

    def canvas_select(self, key):
        if self._pending is not None:
            return
        if key is not None and key not in self.preview.selections:
            self.preview.set_selection(key)
        index = next(
            (i for i in range(self.element.count()) if self.element.itemData(i) == key), -1
        )
        self._from_canvas = True
        try:
            self.element.setCurrentIndex(index)
        finally:
            self._from_canvas = False

    def focus_target(self, target):
        """Locate a reported object without changing geometry or undo history."""
        if self._pending is not None:
            return False
        self.face.setCurrentIndex(self.face.findData(target.face))
        template = self.configuration()
        face = getattr(template, target.face)
        region = next((i for i, r in enumerate(face.reserved) if r.name == target.region), None)
        anchor = next((i for i, a in enumerate(face.anchors) if a.name == target.anchor), None)
        key = (
            ("reserved", region)
            if region is not None
            else ("anchors", anchor)
            if anchor is not None
            else None
        )
        self.canvas_select(key)
        if key is None:
            self.preview.set_selection(None)
            self.error.setText(f"目标对象已不存在：{target.region}。请恢复对象或解除失效绑定。")
            return False
        if target.anchor and anchor is None:
            self.error.setText(f"锚点 {target.anchor} 已不存在；已选中对应填写区。")
        return True

    def selection_summary(self, keys):
        self.selection_count.setText(f"已选 {len(keys)} 个元素")
        self.arrange_button.setEnabled(len(keys) >= 2 and self._pending is None)

    def arrange_elements(self):
        if self._pending is not None or self.valid_template is None:
            return
        keys = self.preview.selections
        try:
            template = arrange_selection(
                self.configuration(), self.face.currentData(), keys, self.arrange_mode.currentData()
            )
            if template != self.configuration():
                self.set_design(template)
                self.preview.set_selections(keys, notify=True)
        except (ValueError, TypeError) as error:
            self.error.setText(f"排列未应用：{error}")

    def canvas_commit(self, template, key):
        if self._pending is not None:
            return
        keys = self.preview.selections if key in self.preview.selections else (key,)
        self.set_design(template)
        self.preview.set_selections(keys, notify=True)
        self.canvas_tool.setCurrentIndex(0)

    def set_background(self, background):
        template = self.configuration()
        face_name = self.face.currentData()
        face = replace(getattr(template, face_name), background=background)
        self.set_design(
            replace(template, **{face_name: face}, source_sha256="", calibration="unreviewed")
        )

    def import_background(self):
        if self._pending is not None:
            return
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "导入当前页参考底图", "", "PDF 或图片 (*.pdf *.png *.jpg *.jpeg)"
        )
        if path:
            try:
                if Path(path).suffix.lower() == ".pdf":
                    from .template_pdf import PdfReferenceDialog

                    dialog = PdfReferenceDialog(
                        path, self.configuration(), self.face.currentData(), self
                    )
                    try:
                        if dialog.exec() == QtWidgets.QDialog.Accepted:
                            self.set_design(dialog.configuration())
                    finally:
                        dialog.pdf.close()
                        dialog.deleteLater()
                else:
                    self.set_background(import_reference_image(path))
            except (OSError, ValueError, TypeError, ImportError) as error:
                self.error.setText(str(error))

    def clear_background(self):
        try:
            self.set_background(None)
        except (ValueError, TypeError) as error:
            self.error.setText(str(error))

    @staticmethod
    def make_table(parent):
        table = QtWidgets.QTableWidget(0, 2, parent)
        table.setHorizontalHeaderLabels(["属性", "值"])
        table.horizontalHeader().setStretchLastSection(True)
        table.verticalHeader().hide()
        return table

    @staticmethod
    def fill_table(table, data):
        blocker = QtCore.QSignalBlocker(table)
        labels = {
            "name": "名称 / 标识",
            "width_mm": "宽度",
            "height_mm": "高度",
            "mode": "用纸模式",
            "offset_x_mm": "横向校准偏移",
            "offset_y_mm": "纵向校准偏移",
            "x_mm": "横坐标",
            "y_mm": "纵坐标",
            "points": "折线点 [[x,y],…]",
        }
        table.setRowCount(len(data))
        for row, (key, value) in enumerate(data.items()):
            label = QtWidgets.QTableWidgetItem(labels.get(key, key))
            label.setData(QtCore.Qt.UserRole, key)
            label.setToolTip(key)
            label.setFlags(label.flags() & ~QtCore.Qt.ItemIsEditable)
            table.setItem(row, 0, label)
            text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
            if key == "mode":
                text = {"preprinted": "预印纸", "blank": "空白纸"}.get(text, text)
            if key == "width_mm" and "points" in data:
                label.setText("线宽")
            table.setItem(row, 1, QtWidgets.QTableWidgetItem(text))
            if key == "name":
                table.item(row, 1).setToolTip(
                    "直接改名不会迁移文档绑定；有引用的填写区或锚点请在外层页面模板窗口使用“联动重命名”。"
                )
        del blocker

    def pending(self, table):
        self._pending = table
        self.arrange_button.setEnabled(False)
        self.issue_picker.setEnabled(False)
        self.issue_button.setEnabled(False)
        self.face.setEnabled(False)
        self.element.setEnabled(False)
        self.json_editor.setEnabled(False)
        self.page_properties.setEnabled(table is self.page_properties)
        self.element_properties.setEnabled(table is self.element_properties)
        self.apply_page.setEnabled(table is self.page_properties)
        self.apply_element.setEnabled(table is self.element_properties)
        self.buttons.button(QtWidgets.QDialogButtonBox.Ok).setEnabled(False)
        self.preview.hide()
        self.error.setText("属性尚未写入：请先点击对应的“写入”按钮，再切换页面、元素或导出。")

    @staticmethod
    def table_values(table):
        result = {}
        for row in range(table.rowCount()):
            key, value = table.item(row, 0).data(QtCore.Qt.UserRole), table.item(row, 1).text()
            if key == "mode":
                value = {"预印纸": "preprinted", "空白纸": "blank"}.get(value, value)
            result[key] = value if key in {"name", "mode"} else json.loads(value)
        return result

    def draft(self):
        # Validate only on apply/accept, allowing a multi-step geometry edit.
        try:
            value = json.loads(self.json_editor.toPlainText())
        except RecursionError as error:
            raise ValueError("模板 JSON 嵌套过深") from error
        if not isinstance(value, dict):
            raise TypeError("模板必须是 JSON 对象")
        return value

    def set_design(self, template):
        if self.json_editor.toPlainText():
            self.write_draft(json.loads(template_json(template)))
        else:
            self.json_editor.setPlainText(template_json(template))

    def write_draft(self, data):
        text = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        cursor = self.json_editor.textCursor()
        cursor.beginEditBlock()
        cursor.select(cursor.SelectionType.Document)
        cursor.insertText(text)
        cursor.endEditBlock()

    def refresh(self):
        if self._syncing:
            return
        self._syncing = True
        self._pending = None
        for widget in (
            self.face,
            self.element,
            self.json_editor,
            self.page_properties,
            self.element_properties,
            self.apply_page,
            self.apply_element,
        ):
            widget.setEnabled(True)
        self.valid_template = None
        with QtCore.QSignalBlocker(self.issue_picker):
            self.issue_picker.clear()
        try:
            template = parse_template(self.json_editor.toPlainText())
            self.valid_template = template
            self.preview.set_template(template, self.face.currentData())
            self.preview.show()
            self.error.setText("几何校验通过；应用后仍需检查内容是否越框。")
        except (ValueError, TypeError, KeyError, AttributeError, OverflowError) as error:
            self.preview.hide()  # Never show an old preview as if it matches this draft.
            self.error.setText(f"草稿尚未通过校验：{error}")
            paths = error.paths if isinstance(error, TemplateValidationError) else ((),)
            offset = getattr(error, "source_offset", None)
            for path in paths:
                self.issue_picker.addItem(self.issue_label(path), (path, offset))
        self.issue_picker.setEnabled(self.issue_picker.count() > 0)
        self.issue_button.setEnabled(self.issue_picker.count() > 0)
        self.buttons.button(QtWidgets.QDialogButtonBox.Ok).setEnabled(
            self.valid_template is not None
        )
        try:
            data = self.draft()
            self.fill_table(
                self.page_properties,
                {
                    k: data[k]
                    for k in ("name", "width_mm", "height_mm", "mode", "offset_x_mm", "offset_y_mm")
                    if k in data
                },
            )
            selected = self.element.currentData()
            self.element.clear()
            face = data[self.face.currentData()]
            self.element.addItem(f"正文区 · {face['body']['name']}", ("body", None))
            for kind, label in (("reserved", "填写区"), ("anchors", "锚点"), ("rules", "框线")):
                for index, item in enumerate(face.get(kind, [])):
                    self.element.addItem(f"{label} · {item['name']}", (kind, index))
            index = next(
                (i for i in range(self.element.count()) if self.element.itemData(i) == selected),
                0,
            )
            self.element.setCurrentIndex(max(0, index))
        except (ValueError, TypeError, KeyError, AttributeError):
            self.element.clear()
            self.page_properties.setRowCount(0)
        finally:
            self._syncing = False
        self.select_element()

    def issue_label(self, path):
        names = {
            "first": "首页",
            "continuation": "续页",
            "body": "正文区",
            "reserved": "填写区",
            "anchors": "锚点",
            "rules": "框线",
            "slots": "内容字段",
            "points": "折线点",
            "name": "名称",
            "width_mm": "宽度",
            "height_mm": "高度",
            "x_mm": "横坐标",
            "y_mm": "纵坐标",
            "offset_x_mm": "横向偏移",
            "offset_y_mm": "纵向偏移",
            "region": "目标填写区",
            "anchor": "基线锚点",
            "background": "参考底图",
        }
        if not path:
            return "JSON 草稿 / 语法位置"
        try:
            value = self.draft()
            labels = []
            for part in path:
                value = value[part]
                label = names.get(part, str(part + 1) if isinstance(part, int) else str(part))
                if isinstance(value, dict):
                    title = value.get("label", value.get("name", value.get("slot_id")))
                    if isinstance(title, str):
                        label += f"（{title}）"
                labels.append(label)
            return " · ".join(labels)
        except (KeyError, IndexError, TypeError, ValueError):
            return "/" + "/".join(map(str, path))

    def locate_issue(self):
        if self._pending is not None or self.issue_picker.currentIndex() < 0:
            return
        path, offset = self.issue_picker.currentData()
        text = self.json_editor.toPlainText()
        # A syntax failure still has a precise caret location; object paths need valid JSON.
        try:
            span = (
                (offset, min(offset + 1, len(text)))
                if offset is not None
                else json_value_span(text, path)
            )
        except (json.JSONDecodeError, RecursionError):
            span = None
        if span is not None:
            cursor = self.json_editor.textCursor()
            cursor.setPosition(len(text[: span[0]].encode("utf-16-le")) // 2)
            cursor.setPosition(
                len(text[: span[1]].encode("utf-16-le")) // 2, cursor.MoveMode.KeepAnchor
            )
            self.json_editor.setTextCursor(cursor)
            self.json_editor.ensureCursorVisible()
        table, property_name = None, None
        if path and path[0] in {"first", "continuation"}:
            self.face.setCurrentIndex(self.face.findData(path[0]))
            if len(path) >= 2 and path[1] in {"body", "reserved", "anchors", "rules"}:
                key = (path[1], None if path[1] == "body" else path[2] if len(path) > 2 else None)
                index = next(
                    (i for i in range(self.element.count()) if self.element.itemData(i) == key), -1
                )
                if index >= 0:
                    self.element.setCurrentIndex(index)
                    table = self.element_properties
                    property_name = (
                        path[2]
                        if path[1] == "body" and len(path) > 2
                        else path[3]
                        if len(path) > 3
                        else None
                    )
        elif len(path) == 1 and path[0] in {
            "name",
            "width_mm",
            "height_mm",
            "mode",
            "offset_x_mm",
            "offset_y_mm",
        }:
            table, property_name = self.page_properties, path[0]
        if table is not None and table.rowCount():
            row = next(
                (
                    i
                    for i in range(table.rowCount())
                    if table.item(i, 0).data(QtCore.Qt.UserRole) == property_name
                ),
                0,
            )
            self.tabs.setCurrentIndex(0)
            table.setCurrentCell(row, 1)
            table.setFocus()
        else:
            self.tabs.setCurrentIndex(1)
            self.json_editor.setFocus()
        # Switching faces refreshes validation. Retain which conflict participant was chosen.
        for index in range(self.issue_picker.count()):
            if self.issue_picker.itemData(index) == (path, offset):
                self.issue_picker.setCurrentIndex(index)
                break

    def select_element(self):
        if self._syncing:
            return
        selected = self.element.currentData()
        if not self._from_canvas:
            self.preview.set_selection(selected if self.valid_template is not None else None)
        self.element_properties.setRowCount(0)
        self.remove_element.setEnabled(bool(selected and selected[0] != "body"))
        if selected:
            kind, index = selected
            face = self.draft()[self.face.currentData()]
            item = face[kind] if index is None else face[kind][index]
            self.fill_table(self.element_properties, item)

    def mutate(self, action):
        try:
            data = self.draft()
            action(data)
            # A coordinate change invalidates an earlier physical calibration claim.
            data["calibration"] = "unreviewed"
            self.write_draft(data)
        except (ValueError, TypeError, KeyError, IndexError) as error:
            self.error.setText(f"属性未写入：{error}")

    def write_page(self):
        self.mutate(lambda data: data.update(self.table_values(self.page_properties)))

    def write_element(self):
        def edit(data):
            kind, index = self.element.currentData()
            face = data[self.face.currentData()]
            values = self.table_values(self.element_properties)
            if index is None:
                face[kind] = values
            else:
                face[kind][index] = values

        if self.element.currentData():
            self.mutate(edit)

    def add_element(self, kind):
        if self._pending is not None:
            return

        def edit(data):
            face = data[self.face.currentData()]
            existing = {face["body"]["name"]}
            existing.update(item["name"] for item in face.get(kind, []))
            index = 1
            while f"{kind}-{index}" in existing:
                index += 1
            item = {"name": f"{kind}-{index}"}
            if kind == "rules":
                item.update(points=[[20, 25], [80, 25]], width_mm=0.3)
            else:
                item.update(x_mm=20, y_mm=10)
                if kind == "reserved":
                    item.update(width_mm=60, height_mm=10)
            face.setdefault(kind, []).append(item)

        self.mutate(edit)
        self.element.setCurrentIndex(self.element.count() - 1)
        # Lists are grouped by type, so select the actual added item.
        for index in reversed(range(self.element.count())):
            if self.element.itemData(index)[0] == kind:
                self.element.setCurrentIndex(index)
                break

    def delete_element(self):
        if self._pending is not None:
            return
        selected = self.element.currentData()
        if selected and selected[0] != "body":
            self.mutate(lambda data: data[self.face.currentData()][selected[0]].pop(selected[1]))

    def copy_body_width(self):
        if self._pending is not None:
            return

        def edit(data):
            face = self.face.currentData()
            other = "continuation" if face == "first" else "first"
            data[other]["body"]["width_mm"] = data[face]["body"]["width_mm"]

        self.mutate(edit)

    def import_file(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "导入模板", "", "JSON (*.json)")
        if path:
            try:
                self.set_design(read_template(path))
            except (OSError, ValueError, TypeError) as error:
                self.error.setText(str(error))

    def export_file(self):
        try:
            raw = template_json(self.configuration()).encode("utf-8")
        except (ValueError, TypeError) as error:
            self.error.setText(str(error))
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "导出模板", "template.json", "JSON (*.json)"
        )
        if path:
            file = QtCore.QSaveFile(path)
            if not file.open(QtCore.QIODevice.WriteOnly):
                self.error.setText(file.errorString())
                return
            if file.write(raw) != len(raw):
                file.cancelWriting()
                self.error.setText(file.errorString())
            elif not file.commit():
                self.error.setText(file.errorString())

    def configuration(self):
        if self._pending is not None:
            raise ValueError("请先写入尚未保存的元素或纸张属性")
        return parse_template(self.json_editor.toPlainText())

    def design_slots(self):
        from .template_slots import TemplateSlotsDialog

        try:
            dialog = TemplateSlotsDialog(self.configuration(), self)
            if dialog.exec() == QtWidgets.QDialog.Accepted:
                self.set_design(dialog.configuration())
        except (ValueError, TypeError) as error:
            self.error.setText(str(error))

    def accept(self):
        try:
            self.configuration()
        except (ValueError, TypeError) as error:
            self.error.setText(str(error))
            return
        super().accept()
