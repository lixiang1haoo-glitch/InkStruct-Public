"""Transactional template-v3 designer. Geometry is edited on source layouts only."""

from dataclasses import replace
from itertools import pairwise
from math import hypot
from pathlib import Path
from uuid import uuid4

from PySide6 import QtCore, QtGui, QtWidgets

from ..document.flow_template import FlowTemplate, NamedField, PageLayout, TextFrame
from ..document.template import Region
from ..document.template_authoring import import_reference_image, parse_template, template_json


def button(layout, text, callback):
    b = QtWidgets.QPushButton(text)
    b.clicked.connect(lambda: callback())
    layout.addWidget(b)
    return b


class FlowCanvas(QtWidgets.QWidget):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.setMinimumSize(300, 350)
        self.setAccessibleName("页面版式画布，显示正文框编号与连接顺序")

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.fillRect(self.rect(), QtGui.QColor("#e7ebf0"))
        t = self.owner.template
        layout = self.owner.current_layout()
        if not layout:
            return
        scale = min((self.width() - 20) / t.width_mm, (self.height() - 20) / t.height_mm)
        p.translate(10, 10)
        p.scale(scale, scale)
        p.fillRect(QtCore.QRectF(0, 0, t.width_mm, t.height_mm), QtCore.Qt.GlobalColor.white)
        if layout.background:
            p.setOpacity(0.45)
            p.drawImage(
                QtCore.QRectF(0, 0, t.width_mm, t.height_mm),
                QtGui.QImage.fromData(layout.background.png_bytes(), "PNG"),
            )
            p.setOpacity(1)
        p.setPen(QtGui.QPen(QtGui.QColor("#94a3b8"), 0.3))
        for r in layout.rules:
            p.drawPolyline(QtGui.QPolygonF([QtCore.QPointF(x, y) for x, y in r.points]))
        font = QtGui.QFont()
        font.setPointSizeF(3)
        p.setFont(font)
        for f in layout.frames:
            r = f.region
            color = QtGui.QColor("#2563eb" if f.role == "body" else "#b45309")
            p.setPen(QtGui.QPen(color, 0.5))
            p.setBrush(
                QtGui.QColor(37, 99, 235, 18) if f.role == "body" else QtGui.QColor(180, 83, 9, 18)
            )
            p.drawRect(QtCore.QRectF(r.x_mm, r.y_mm, r.width_mm, r.height_mm))
            if f.paper_grid:
                p.setPen(QtGui.QPen(QtGui.QColor("#0284c7"), 0.35, QtCore.Qt.PenStyle.DashLine))
                for baseline in f.paper_grid.baselines():
                    y = r.y_mm + baseline + t.offset_y_mm
                    x = r.x_mm + t.offset_x_mm
                    p.drawLine(QtCore.QPointF(x, y), QtCore.QPointF(x + r.width_mm, y))
                p.setPen(QtGui.QPen(color, 0.5))
            title = (
                f"{f.order}. 正文"
                if f.role == "body"
                else f"字段 {f.field_id}"
                if f.role == "field"
                else "自动页码"
            )
            p.drawText(QtCore.QPointF(r.x_mm + 1, r.y_mm + 4), title + " · " + f.label)
        body = layout.body_frames
        p.setPen(QtGui.QPen(QtGui.QColor("#2563eb"), 0.6, QtCore.Qt.PenStyle.DashLine))
        for a, b in pairwise(body):
            x, y = a.region.x_mm + a.region.width_mm / 2, a.region.y_mm + a.region.height_mm / 2
            u, v = b.region.x_mm + b.region.width_mm / 2, b.region.y_mm + b.region.height_mm / 2
            p.drawLine(QtCore.QPointF(x, y), QtCore.QPointF(u, v))
            dx, dy = u - x, v - y
            length = hypot(dx, dy)
            if length:
                mx, my = x + dx * 0.7, y + dy * 0.7
                for sign in (-1, 1):
                    p.drawLine(
                        QtCore.QPointF(mx, my),
                        QtCore.QPointF(
                            mx - 2 * dx / length + sign * dy / length,
                            my - 2 * dy / length - sign * dx / length,
                        ),
                    )
            p.drawText(QtCore.QPointF((x + u) / 2, (y + v) / 2), f"{a.order} → {b.order}")


class _TemplateDraft(QtWidgets.QDialog):
    def __init__(self, template=None, parent=None):
        super().__init__(parent)
        self.template = template or FlowTemplate()
        self.undo_stack = []
        self.redo_stack = []
        self.loading = False
        self.setWindowTitle("制作模板 · 简单模板 / 自定义模板")
        self.setMinimumSize(1000, 650)
        self.resize(1200, 850)
        col = QtWidgets.QVBoxLayout(self)
        self.tabs = QtWidgets.QTabWidget()
        col.addWidget(self.tabs, 1)
        paper = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(paper)
        self.name = QtWidgets.QLineEdit()
        form.addRow("模板名称", self.name)
        self.kind = QtWidgets.QComboBox()
        self.kind.addItem("简单模板：重复单页正文", "simple")
        self.kind.addItem("自定义模板：起始页组 + 循环页组", "custom")
        form.addRow("模板类型", self.kind)
        self.paper = {}
        for key, title in [
            ("width", "纸张宽度"),
            ("height", "纸张高度"),
            ("top", "上边距"),
            ("right", "右边距"),
            ("bottom", "下边距"),
            ("left", "左边距"),
        ]:
            control = QtWidgets.QDoubleSpinBox()
            control.setRange(0.001 if key in {"width", "height"} else 0, 2000)
            control.setDecimals(4)
            control.setSuffix(" mm")
            self.paper[key] = control
            form.addRow(title, control)
        note = QtWidgets.QLabel(
            "简单模板正文自动换行和分页。默认字号、行距、段距在齿轮 → 正文与段落统一设置。\n自定义模板改变纸张大小时，背景拉伸铺满新纸张，框几何保持毫米值；越界时拒绝应用。只做平移校准，不识别或描摹背景。"
        )
        note.setWordWrap(True)
        form.addRow(note)
        apply = QtWidgets.QPushButton("应用纸张与类型草稿")
        apply.clicked.connect(lambda: self.guard(self.apply_paper))
        form.addRow(apply)
        self.tabs.addTab(paper, "纸张与基础设置")
        design = QtWidgets.QWidget()
        row = QtWidgets.QHBoxLayout(design)
        left = QtWidgets.QVBoxLayout()
        row.addLayout(left, 1)
        self.layouts = QtWidgets.QListWidget()
        self.layouts.currentRowChanged.connect(self.select_layout)
        left.addWidget(QtWidgets.QLabel("源页面版式（修改统一影响所有自动页面）"))
        left.addWidget(self.layouts)
        bar = QtWidgets.QHBoxLayout()
        button(bar, "新增页面版式", lambda: self.guard(self.add_layout))
        button(bar, "删除页面版式", lambda: self.guard(self.remove_layout))
        left.addLayout(bar)
        self.groups = {}
        for key, title in [
            ("start_pages", "起始页组（可选，按顺序一次）"),
            ("loop_pages", "循环页组（必填，按顺序循环）"),
        ]:
            left.addWidget(QtWidgets.QLabel(title))
            listing = QtWidgets.QListWidget()
            listing.setMaximumHeight(100)
            self.groups[key] = listing
            left.addWidget(listing)
            bar = QtWidgets.QHBoxLayout()
            button(bar, "加入当前页面版式", lambda key=key: self.guard(lambda: self.group_add(key)))
            button(bar, "↑", lambda key=key: self.guard(lambda: self.group_move(key, -1)))
            button(bar, "↓", lambda key=key: self.guard(lambda: self.group_move(key, 1)))
            button(bar, "移除", lambda key=key: self.guard(lambda: self.group_remove(key)))
            left.addLayout(bar)
        self.finish = QtWidgets.QCheckBox("末尾补齐整个循环页组")
        self.finish.toggled.connect(
            lambda v: (
                self.guard(lambda: self.commit(replace(self.template, finish_cycle=v)))
                if not self.loading
                else None
            )
        )
        left.addWidget(self.finish)
        self.connection = QtWidgets.QLabel()
        self.connection.setWordWrap(True)
        left.addWidget(self.connection)
        center = QtWidgets.QVBoxLayout()
        row.addLayout(center, 2)
        self.canvas = FlowCanvas(self)
        center.addWidget(self.canvas, 1)
        bar = QtWidgets.QHBoxLayout()
        button(bar, "导入 PDF 页面…", self.import_pdf)
        button(bar, "图片底图…", lambda: self.guard(self.import_image))
        button(bar, "清除底图", lambda: self.guard(lambda: self.update_layout(background=None)))
        center.addLayout(bar)
        self.layout_name = QtWidgets.QLineEdit()
        center.addWidget(self.layout_name)
        self.background_info = QtWidgets.QLabel()
        self.background_info.setWordWrap(True)
        center.addWidget(self.background_info)
        self.frames = QtWidgets.QTableWidget(0, 9)
        self.frames.setHorizontalHeaderLabels(
            ["框名称", "角色", "正文顺序", "字段标识", "x mm", "y mm", "宽 mm", "高 mm", "框 ID"]
        )
        self.frames.setColumnHidden(8, True)
        self.frames.setMaximumHeight(190)
        self.frames.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeMode.ResizeToContents
        )
        center.addWidget(self.frames)
        bar = QtWidgets.QHBoxLayout()
        for title, role in [
            ("添加正文框", "body"),
            ("添加字段框", "field"),
            ("添加页码框", "page_number"),
        ]:
            button(bar, title, lambda role=role: self.add_frame(role))
        button(bar, "删除框", self.remove_frame)
        button(bar, "应用版式草稿", lambda: self.guard(self.apply_layout))
        center.addLayout(bar)
        self.tabs.addTab(design, "页面组与文本框")
        field_page = QtWidgets.QWidget()
        fields_col = QtWidgets.QVBoxLayout(field_page)
        fields_col.addWidget(
            QtWidgets.QLabel(
                "标识用于内容对应，显示名用于界面；修改框名或显示名不会改变标识。请选择字段类型与必填规则。"
            )
        )
        self.fields = QtWidgets.QTableWidget(0, 4)
        self.fields.setHorizontalHeaderLabels(["稳定字段标识", "显示名称", "类型", "必填规则"])
        self.fields.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeMode.Stretch
        )
        fields_col.addWidget(self.fields)
        bar = QtWidgets.QHBoxLayout()
        button(bar, "新增字段", self.add_field)
        button(bar, "删除字段", lambda: self.fields.removeRow(self.fields.currentRow()))
        button(bar, "应用字段声明", lambda: self.guard(self.apply_fields))
        button(bar, "复制字段写法", lambda: self.guard(self.copy_field))
        button(
            bar,
            "复制全部字段 Markdown 骨架",
            lambda: QtWidgets.QApplication.clipboard().setText(self.template.skeleton()),
        )
        fields_col.addLayout(bar)
        self.tabs.addTab(field_page, "字段声明与 Markdown")
        advanced = QtWidgets.QWidget()
        adv = QtWidgets.QVBoxLayout(advanced)
        self.json = QtWidgets.QPlainTextEdit()
        adv.addWidget(self.json)
        button(
            adv,
            "应用 JSON 草稿",
            lambda: self.guard(lambda: self.commit(parse_template(self.json.toPlainText()))),
        )
        self.tabs.addTab(advanced, "JSON（高级）")
        self.error = QtWidgets.QLabel()
        self.error.setWordWrap(True)
        self.error.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        col.addWidget(self.error)
        bar = QtWidgets.QHBoxLayout()
        button(bar, "撤销模板修改", lambda: self.history(False))
        button(bar, "重做模板修改", lambda: self.history(True))
        button(bar, "另存模板 JSON…", lambda: self.guard(self.save))
        bar.addStretch()
        button(bar, "取消", self.reject)
        button(bar, "确定", self.accept)
        col.addLayout(bar)
        self.refresh()

    def guard(self, call):
        try:
            call()
            self.error.clear()
        except (ValueError, TypeError, OSError) as error:
            self.error.setText(str(error))

    def commit(self, t):
        if not isinstance(t, FlowTemplate):
            raise TypeError("此设计器只编辑 v3；旧模板请使用保留的旧设计器或显式迁移。")
        if t != self.template:
            self.undo_stack.append(self.template)
            self.redo_stack.clear()
            self.template = t
        self.refresh()

    def refresh(self):
        previous = self.layouts.currentItem()
        selected = previous.data(QtCore.Qt.UserRole) if previous else None
        self.loading = True
        t = self.template
        self.name.setText(t.name)
        self.kind.setCurrentIndex(self.kind.findData(t.kind))
        for k, v in zip(
            ("width", "height", "top", "right", "bottom", "left"),
            (t.width_mm, t.height_mm, *t.margins_mm),
        ):
            self.paper[k].setValue(v)
        rows = {p.layout_id: row for row, p in enumerate(t.effective_layouts)}
        with QtCore.QSignalBlocker(self.layouts):
            self.layouts.clear()
            for p in t.effective_layouts:
                item = QtWidgets.QListWidgetItem(p.label)
                item.setData(QtCore.Qt.UserRole, p.layout_id)
                self.layouts.addItem(item)
            self.layouts.setCurrentRow(rows.get(selected, rows[t.layout(0).layout_id]))
        for key, listbox in self.groups.items():
            listbox.clear()
            for item in getattr(t, key):
                listbox.addItem(next(p.label for p in t.layouts if p.layout_id == item))
        self.finish.setChecked(t.finish_cycle)
        sequence = " → ".join(
            next(p.label for p in t.effective_layouts if p.layout_id == key)
            for key in t.effective_loop
        )
        self.connection.setText(
            "正文按页组顺序，再按框编号流动。\n循环："
            + sequence
            + " → 回到首个页面版式的正文框 1；实际页码继续递增。"
        )
        self.fields.setRowCount(0)
        for f in t.fields:
            self.append(self.fields, [f.field_id, f.label, f.value_type, str(f.required).lower()])
        self.json.setPlainText(template_json(t))
        self.tabs.setTabEnabled(1, t.kind == "custom")
        self.tabs.setTabEnabled(2, t.kind == "custom")
        self.loading = False
        self.select_layout(self.layouts.currentRow())

    def current_layout(self):
        item = self.layouts.currentItem()
        key = item.data(QtCore.Qt.UserRole) if item else None
        return next((p for p in self.template.effective_layouts if p.layout_id == key), None)

    def select_layout(self, row):
        p = self.current_layout()
        self.frames.setRowCount(0)
        if p:
            self.layout_name.setText(p.label)
            self.background_info.setText(
                (
                    f"PDF 原尺寸 {p.source_size_mm[0]:.3f} × {p.source_size_mm[1]:.3f} mm；"
                    if p.source_size_mm
                    else ""
                )
                + f"纸张 {self.template.width_mm:g} × {self.template.height_mm:g} mm。背景分别按宽高拉伸铺满，框保持毫米坐标。"
            )
            for f in p.frames:
                self.append(
                    self.frames,
                    [
                        f.label,
                        f.role,
                        f.order,
                        f.field_id,
                        f.region.x_mm,
                        f.region.y_mm,
                        f.region.width_mm,
                        f.region.height_mm,
                        f.frame_id,
                    ],
                )
        self.canvas.update()

    @staticmethod
    def append(table, values):
        row = table.rowCount()
        table.insertRow(row)
        for c, v in enumerate(values):
            table.setItem(row, c, QtWidgets.QTableWidgetItem(str(v)))
        if table.columnCount() == 9:
            combo = QtWidgets.QComboBox()
            for title, key in [
                ("正文框", "body"),
                ("字段框", "field"),
                ("自动页码框", "page_number"),
            ]:
                combo.addItem(title, key)
            combo.setCurrentIndex(combo.findData(values[1]))
            table.setCellWidget(row, 1, combo)
        elif table.columnCount() == 4:
            for col, choices, current in [
                (
                    2,
                    [
                        ("Markdown", "markdown"),
                        ("文本", "text"),
                        ("数值", "number"),
                        ("日期", "date"),
                    ],
                    values[2],
                ),
                (3, [("可选", "false"), ("必填", "true")], values[3]),
            ]:
                combo = QtWidgets.QComboBox()
                for title, key in choices:
                    combo.addItem(title, key)
                combo.setCurrentIndex(combo.findData(current))
                table.setCellWidget(row, col, combo)

    def apply_paper(self):
        values = {k: c.value() for k, c in self.paper.items()}
        changes = {
            "name": self.name.text(),
            "width_mm": values["width"],
            "height_mm": values["height"],
            "margins_mm": tuple(values[k] for k in ("top", "right", "bottom", "left")),
        }
        kind = self.kind.currentData()
        if kind == "custom" and self.template.kind == "simple":
            changes.update(
                kind=kind, layouts=self.template.effective_layouts, loop_pages=("simple",)
            )
        elif kind == "simple" and self.template.kind == "custom":
            raise ValueError("请通过外层“新建简单模板”另建；不会自动丢弃现有页面版式、字段和规则。")
        self.commit(replace(self.template, **changes))

    def update_layout(self, **changes):
        old = self.current_layout()
        if old is None or self.template.kind != "custom":
            raise ValueError("请先选择自定义模板的页面版式")
        new = replace(old, **changes)
        self.commit(
            replace(
                self.template,
                layouts=tuple(
                    new if p.layout_id == old.layout_id else p for p in self.template.layouts
                ),
            )
        )

    def add_layout(self):
        key = "layout-" + uuid4().hex[:12]
        p = PageLayout(key, "页面版式 " + str(len(self.template.layouts) + 1))
        self.commit(replace(self.template, layouts=(*self.template.layouts, p)))
        self.layouts.setCurrentRow(len(self.template.layouts) - 1)

    def remove_layout(self):
        key = self.current_layout().layout_id
        if key in (*self.template.start_pages, *self.template.loop_pages):
            raise ValueError("请先从起始／循环页组移除此页面版式；循环页组必须保留至少一项。")
        self.commit(
            replace(
                self.template, layouts=tuple(p for p in self.template.layouts if p.layout_id != key)
            )
        )

    def group_add(self, key):
        self.commit(
            replace(
                self.template,
                **{key: (*getattr(self.template, key), self.current_layout().layout_id)},
            )
        )

    def group_move(self, key, direction):
        items = list(getattr(self.template, key))
        i = self.groups[key].currentRow()
        if not 0 <= i < len(items) or not 0 <= i + direction < len(items):
            return
        items[i], items[i + direction] = items[i + direction], items[i]
        self.commit(replace(self.template, **{key: tuple(items)}))
        self.groups[key].setCurrentRow(i + direction)

    def group_remove(self, key):
        items = list(getattr(self.template, key))
        i = self.groups[key].currentRow()
        if i >= 0:
            items.pop(i)
            self.commit(replace(self.template, **{key: tuple(items)}))

    def add_frame(self, role):
        n = self.frames.rowCount() + 1
        fid = self.template.fields[0].field_id if role == "field" and self.template.fields else ""
        self.append(
            self.frames,
            [
                ("正文" if role == "body" else "字段" if role == "field" else "页码") + str(n),
                role,
                n,
                fid,
                20,
                20,
                80,
                30,
                "frame-" + uuid4().hex[:12],
            ],
        )

    def remove_frame(self):
        self.frames.removeRow(self.frames.currentRow())

    def apply_layout(self):
        result = []
        for row in range(self.frames.rowCount()):
            v = [self.frames.item(row, c).text() for c in range(9)]
            v[1] = self.frames.cellWidget(row, 1).currentData()
            result.append(
                TextFrame(
                    v[8], v[0], Region(v[8], *(float(x) for x in v[4:8])), v[1], int(v[2]), v[3]
                )
            )
        self.update_layout(label=self.layout_name.text(), frames=tuple(result))

    def add_field(self):
        self.append(
            self.fields, ["field_" + str(self.fields.rowCount() + 1), "新字段", "markdown", "false"]
        )

    def apply_fields(self):
        result = []
        for row in range(self.fields.rowCount()):
            v = [self.fields.item(row, c).text() for c in range(4)]
            v[2] = self.fields.cellWidget(row, 2).currentData()
            v[3] = self.fields.cellWidget(row, 3).currentData()
            if v[3] not in {"true", "false"}:
                raise ValueError("必填只接受 true 或 false")
            result.append(NamedField(v[0], v[1], v[3] == "true", v[2]))
        self.commit(replace(self.template, fields=tuple(result)))

    def copy_field(self):
        from ..document.named_fields import field_example

        i = self.fields.currentRow()
        if i < 0:
            raise ValueError("请先选择字段")
        QtWidgets.QApplication.clipboard().setText(field_example(self.fields.item(i, 0).text()))

    def import_image(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "选择参考图片", "", "图片 (*.png *.jpg *.jpeg)"
        )
        if path:
            self.update_layout(
                background=import_reference_image(path),
                source_page=None,
                source_sha256="",
                source_size_mm=None,
            )

    def import_pdf(self):
        from .flow_template_pdf import PdfPagesDialog

        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "导入多个 PDF 页面", "", "PDF (*.pdf)"
        )
        if not path:
            return
        dialog = PdfPagesDialog(path, self.template, self, initial_blank=self.initial_blank)
        try:
            if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
                key = dialog.group.currentData()
                index = len(getattr(self.template, key)) if dialog.mode.currentData() == "append" else 0
                self.page_selection = (getattr(dialog.candidate, key)[index], key, index)
                self.selected_frame_id = None
                self.commit(dialog.candidate)
        finally:
            dialog.close_worker()
            dialog.deleteLater()

    def history(self, redo):
        source, target = (
            (self.redo_stack, self.undo_stack) if redo else (self.undo_stack, self.redo_stack)
        )
        if source:
            target.append(self.template)
            self.template = source.pop()
            self.refresh()

    def save(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "另存可复用模板（保留原文件）", "", "JSON (*.json)"
        )
        if path:
            with Path(path).open("x", encoding="utf-8") as stream:
                stream.write(template_json(self.template))

    def configuration(self):
        return self.template

    def focus_target(self, target):
        for i, p in enumerate(self.template.effective_layouts):
            if p.layout_id == target.face or any(
                f.frame_id == target.region or f.field_id == target.slot_id for f in p.frames
            ):
                self.tabs.setCurrentIndex(1)
                self.layouts.setCurrentRow(i)
                for j, f in enumerate(p.frames):
                    if f.frame_id == target.region or f.field_id == target.slot_id:
                        self.frames.selectRow(j)
                        return
        if target.slot_id:
            self.tabs.setCurrentIndex(2)
            for i, f in enumerate(self.template.fields):
                if f.field_id == target.slot_id:
                    self.fields.selectRow(i)
                    return
        self.error.setText("当前页面版式中没有此诊断对象，请检查字段声明和正文框。")

    def accept(self):
        # Apply the active draft only; unrelated, unapplied tabs remain drafts.
        try:
            if self.tabs.currentIndex() == 0:
                self.apply_paper()
            elif self.tabs.currentIndex() == 1:
                self.apply_layout()
            elif self.tabs.currentIndex() == 2:
                self.apply_fields()
            else:
                self.commit(parse_template(self.json.toPlainText()))
        except (ValueError, TypeError, OSError) as error:
            self.error.setText(str(error))
            return
        super().accept()


from .template_workbench import WorkbenchUI


class FlowTemplateDesigner(WorkbenchUI, _TemplateDraft):
    """User-facing workbench; the shared draft operations preserve the v3 protocol."""
