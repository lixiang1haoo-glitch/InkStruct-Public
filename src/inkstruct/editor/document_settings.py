"""Document layout drafts shown alongside the existing rendered preview."""

from dataclasses import asdict, is_dataclass, replace
from types import SimpleNamespace

from PySide6 import QtCore, QtWidgets

from ..document.flow_template import FlowTemplate
from ..document.markdown import parse_markdown
from ..global_defaults import GlobalDefaultsStore
from ..settings_dialog import CATEGORIES, layout_settings_page
from ..settings_pages import CompactSpinBox, acceptable, compact_form_parameters, label, section
from ..theme import set_tone


LAYOUT_TITLES = {key: title for key, group, title, _ in CATEGORIES if group == "排版默认设置"}
LAYOUT_TITLES["page"] = "页面设置"
PAPER_SIZES = {"A4": (210, 297), "A5": (148, 210), "B5": (176, 250)}
PAGE_FIELDS = ("width_mm", "height_mm", "top_mm", "right_mm", "bottom_mm", "left_mm")
NAMES = {
    "width_mm": "纸张宽度", "height_mm": "纸张高度", "top_mm": "上边距",
    "right_mm": "右边距", "bottom_mm": "下边距", "left_mm": "左边距",
    "em_mm": "字高", "line_height_mm": "行高", "stroke_width_mm": "笔宽",
    "paragraph_gap_mm": "段距", "paragraph_align": "正文对齐", "first_line_indent_mm": "首行缩进",
    "heading_gap_mm": "标题段距", "list_indent_mm": "列表缩进", "quote_indent_mm": "引用缩进",
    "heading_scales": "标题字号倍率", "markdown_dialect": "Markdown 格式",
    "han_spacing": "汉字间距", "latin_spacing": "字母与数字间距", "digits_follow_latin": "数字间距跟随字母",
    "punctuation_spacing": "标点间距", "enabled": "启用自然书写",
    "strength": "笔画与倾斜变化", "size_strength": "字形大小变化",
    "spacing_strength": "字距变化", "baseline_strength": "基线上下变化", "seed": "随机种子",
    "mode": "内容模式", "advance_mm": "固定字格宽度", "tab_columns": "制表位列数", "wrap_lines": "宽行换行",
}
OPTIONS = {
    "justify": "两端对齐", "left": "左对齐", "center": "居中", "right": "右对齐",
    "full": "整字宽", "handwriting": "按笔迹排列", "capture": "保留采集留白",
    "markdown": "Markdown 混排", "plain-text": "纯文本检查", "obsidian": "Obsidian 静态扩展",
}


def page_geometry(template):
    return dict(zip(PAGE_FIELDS, (template.width_mm, template.height_mm, *template.margins_mm), strict=True))


def simple_template(page):
    return FlowTemplate(name="普通页面", mode="blank", width_mm=page.width_mm,
                        height_mm=page.height_mm, margins_mm=(page.margin_mm,) * 4)


def with_geometry(template, values):
    width, height, top, right, bottom, left = (values[key] for key in PAGE_FIELDS)
    margins = (top, right, bottom, left)
    if left + right >= width or top + bottom >= height:
        raise ValueError("边距过大，页面需要留出正文区域。")
    return replace(template, width_mm=width, height_mm=height, margins_mm=margins, revision=None)


class PageSetup(QtWidgets.QWidget):
    def __init__(self, editor, advanced):
        super().__init__()
        self.template = editor.flow.template if editor.mode == "markdown" else None
        self.editable = self.template is None or (
            isinstance(self.template, FlowTemplate) and self.template.kind == "simple"
        )
        self.template = self.template or simple_template(editor.page)
        self.controls = {}
        self.uniform = editor.mode == "plain-text"
        column = QtWidgets.QVBoxLayout(self)
        if not self.editable:
            from .template_manager import description

            column.addWidget(label(description(self.template)))
            column.addWidget(label("纸张与正文区域由模板定义。"))
            button = QtWidgets.QPushButton("编辑当前文档模板…")
            button.clicked.connect(advanced)
            column.addWidget(button, alignment=QtCore.Qt.AlignmentFlag.AlignLeft)
            column.addStretch()
            return
        self.original = page_geometry(self.template)
        form = QtWidgets.QFormLayout()
        form.setRowWrapPolicy(QtWidgets.QFormLayout.RowWrapPolicy.WrapLongRows)
        self.paper = QtWidgets.QComboBox()
        for name in (*PAPER_SIZES, "自定义"):
            self.paper.addItem(name)
        self.direction = QtWidgets.QComboBox()
        self.direction.addItems(["纵向", "横向"])
        form.addRow("纸张", self.paper)
        form.addRow("方向", self.direction)
        dimensions = QtWidgets.QWidget()
        dimension_form = QtWidgets.QFormLayout(dimensions)
        for i, key in enumerate(PAGE_FIELDS):
            if self.uniform and i > 2:
                break
            control = CompactSpinBox()
            control.setObjectName(key)
            title = "页边距" if self.uniform and i == 2 else NAMES[key]
            control.setAccessibleName(title)
            control.setDecimals(6)
            control.setRange(0.000001 if i < 2 else 0, 2000)
            control.setSingleStep(.5)
            control.setSuffix(" mm")
            control.setValue(self.original[key])
            self.controls[key] = control
            (dimension_form if i < 2 else form).addRow(title, control)
        self.initial = {key: control.value() for key, control in self.controls.items()}
        self.paper.currentTextChanged.connect(self.choose_paper)
        self.direction.currentIndexChanged.connect(self.choose_direction)
        for key in PAGE_FIELDS[:2]:
            self.controls[key].valueChanged.connect(self.sync_paper)
        self.sync_paper()
        column.addLayout(form)
        section(column, "纸张尺寸", dimensions)
        compact_form_parameters(self)
        column.addStretch()

    def sync_paper(self):
        width, height = (self.controls[key].value() for key in PAGE_FIELDS[:2])
        with QtCore.QSignalBlocker(self.paper), QtCore.QSignalBlocker(self.direction):
            size = tuple(sorted((width, height)))
            self.paper.setCurrentText(next((key for key, value in PAPER_SIZES.items() if value == size), "自定义"))
            self.direction.setCurrentIndex(int(width > height))

    def choose_paper(self, name):
        if name in PAPER_SIZES:
            width, height = PAPER_SIZES[name]
            if self.direction.currentIndex():
                width, height = height, width
            self.set_dimensions(width, height)

    def choose_direction(self, index):
        width, height = (self.controls[key].value() for key in PAGE_FIELDS[:2])
        if width != height and (width > height) != bool(index):
            self.set_dimensions(height, width)

    def set_dimensions(self, width, height):
        with QtCore.QSignalBlocker(self.controls["width_mm"]):
            self.controls["width_mm"].setValue(width)
        self.controls["height_mm"].setValue(height)
        self.sync_paper()

    def configuration(self):
        if not self.editable:
            return {}
        acceptable(self)
        values = self.original | {key: control.value() for key, control in self.controls.items()
                                  if control.value() != self.initial[key]}
        if self.uniform:
            for key in PAGE_FIELDS[3:]:
                values[key] = values["top_mm"]
        return values


def flattened(values, prefix=()):
    for key, value in values.items():
        path = (*prefix, key)
        if is_dataclass(value):
            yield from flattened(asdict(value), path)
        elif isinstance(value, dict):
            yield from flattened(value, path)
        elif key != "schema_version":
            yield path, value


def display_value(key, value):
    if value is None:
        return "自动"
    if isinstance(value, bool):
        return "开启" if value else "关闭"
    if isinstance(value, float) and key.endswith("_mm"):
        return f"{value:g} mm"
    if isinstance(value, (list, tuple)):
        return "、".join(map(str, value)) or "无"
    return OPTIONS.get(value, str(value))


class DocumentSettings(QtWidgets.QWidget):
    dismissed = QtCore.Signal()

    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor
        self.key = None
        self.session = None
        self.drafts = {}
        self.changed_categories = set()
        self.setObjectName("document_layout_settings")
        column = QtWidgets.QVBoxLayout(self)
        self.title = label("")
        self.title.setProperty("inkRole", "title")
        self.document_name = label("")
        column.addWidget(self.title)
        column.addWidget(self.document_name)
        self.stack = QtWidgets.QStackedWidget()
        column.addWidget(self.stack, 1)
        self.message = label("")
        self.message.hide()
        column.addWidget(self.message)
        row = QtWidgets.QHBoxLayout()
        self.defaults_button = QtWidgets.QPushButton("设为新建默认…")
        self.defaults_button.clicked.connect(self.save_default)
        row.addWidget(self.defaults_button)
        row.addStretch()
        self.close_button = QtWidgets.QPushButton("关闭")
        self.close_button.clicked.connect(self.dismissed)
        row.addWidget(self.close_button)
        self.apply_button = QtWidgets.QPushButton("应用")
        self.apply_button.setProperty("inkRole", "primary")
        self.apply_button.clicked.connect(self.apply)
        row.addWidget(self.apply_button)
        column.addLayout(row)

    def refresh_document(self):
        name = self.editor.session_path.name if self.editor.session_path else "未命名文档"
        self.document_name.setText(f"当前文档 · {name}")
        if self.session is not self.editor.source_session:
            active = self.key
            self.clear()
            self.session = self.editor.source_session
            if active is not None:
                self.open_category(active)

    def clear(self):
        self.key = None
        self.session = None
        self.drafts.clear()
        self.changed_categories.clear()
        while self.stack.count():
            page = self.stack.widget(0)
            self.stack.removeWidget(page)
            page.deleteLater()

    def open_category(self, key, *, focus=False):
        if self.session is not self.editor.source_session:
            self.clear()
            self.refresh_document()
        self.key = key
        self.title.setText(LAYOUT_TITLES[key])
        self.message.hide()
        if key not in self.drafts:
            self.make_draft(key)
        panel, page, _ = self.drafts[key]
        self.stack.setCurrentWidget(panel)
        self.update_actions()
        if focus:
            editable = next((field for field in page.findChildren(QtWidgets.QWidget)
                             if isinstance(field, (QtWidgets.QAbstractSpinBox, QtWidgets.QComboBox))
                             and field.isEnabled() and field.isVisible()), None)
            (editable or self.close_button).setFocus()

    def make_draft(self, key):
        editor = self.editor
        owner = SimpleNamespace(
            style=editor.style, flow=editor.flow, mode=editor.mode, run=editor.run_path,
            resolver=editor.resolver, document=parse_markdown("") if key in {"table", "image"} else None,
        )
        page = PageSetup(editor, self.edit_template) if key == "page" else layout_settings_page(
            owner, key, for_document=True
        )
        if key == "body" and (editor.session_path or editor.run_path.endswith(".inkfont")):
            page.mode.setEnabled(False)
            page.mode.setToolTip("已打开的项目沿用其内容模式。")
        panel = page
        if key != "math":
            panel = QtWidgets.QScrollArea()
            panel.setWidgetResizable(True)
            panel.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
            panel.setWidget(page)
        self.stack.addWidget(panel)
        self.drafts[key] = (panel, page, self.values(key, page))
        for field in page.findChildren(QtWidgets.QWidget):
            if isinstance(field, (QtWidgets.QSpinBox, QtWidgets.QDoubleSpinBox, QtWidgets.QComboBox, QtWidgets.QLineEdit)):
                signal = (field.valueChanged if isinstance(field, (QtWidgets.QSpinBox, QtWidgets.QDoubleSpinBox))
                          else field.currentIndexChanged if isinstance(field, QtWidgets.QComboBox)
                          else field.textChanged)
                signal.connect(self.update_actions)
            elif isinstance(field, QtWidgets.QAbstractButton):
                field.clicked.connect(self.update_actions)
                field.toggled.connect(self.update_actions)

    def values(self, key, page):
        if key == "body":
            style, flow = page.configuration()
            flow["digits_follow_latin"] = page.digits_follow.isChecked()
            return asdict(style) | flow | {"mode": page.mode.currentData()}
        if key == "page":
            return page.configuration()
        if key in {"table", "image"}:
            return {key: page.default_style()}
        acceptable(page)
        return {key: page.configuration()}

    def draft(self):
        _, page, initial = self.drafts[self.key]
        return page, initial, self.values(self.key, page)

    def update_actions(self, *_):
        if self.key not in self.drafts:
            return
        try:
            _, initial, values = self.draft()
            changed = initial != values
        except (ValueError, TypeError):
            changed = True  # Apply exposes the existing field validator's message.
        if changed:
            self.changed_categories.add(self.key)
        else:
            self.changed_categories.discard(self.key)
        self.apply_button.setEnabled(changed)
        self.close_button.setText("取消" if self.changed_categories else "关闭")
        page = self.drafts[self.key][1]
        self.defaults_button.setVisible(self.key != "page" or page.editable)

    def report(self, message, *, error=False):
        set_tone(self.message, "danger" if error else "success")
        self.message.setText(message)
        self.message.show()

    def apply(self):
        if self.session is not self.editor.source_session:
            self.refresh_document()
            return False
        try:
            page, initial, values = self.draft()
            if values == initial:
                return False
            editor = self.editor
            key = self.key
            if key in {"table", "image"} and editor.element_inspector.has_pending():
                raise ValueError("请先应用或取消右侧的元素修改。")
            changes = {key: value for key, value in values.items() if value != initial[key]}
            if key == "page":
                template = with_geometry(page.template, values)
                if editor.mode == "markdown":
                    if editor.flow.template is not None and editor.flow.template != page.template:
                        raise ValueError("当前文档的模板已变化，请重新打开页面设置。")
                    editor.template_content_panel.apply_template(template)
                else:
                    editor.page = replace(editor.page, width_mm=template.width_mm, height_mm=template.height_mm,
                                          margin_mm=template.margins_mm[0])
                    editor.mark_dirty()
                    editor.schedule_layout()
            else:
                style, flow, mode = self.updated_layout(editor.style, editor.flow, editor.mode, changes)
                editor.loaded_style, editor.flow, editor.mode = style, flow, mode
                editor._sync_document_controls(style)
                editor.mark_dirty()
                editor.schedule_layout()
            self.reload_category()
            self.report("已应用到当前文档。按 Ctrl+S 保存项目。")
            return True
        except (ValueError, TypeError) as error:
            self.report(str(error), error=True)
            return False

    def reload_category(self):
        panel, _, _ = self.drafts.pop(self.key)
        self.stack.removeWidget(panel)
        panel.deleteLater()
        self.open_category(self.key)

    def edit_template(self):
        self.editor.template_settings()
        self.reload_category()

    @staticmethod
    def updated_layout(style, flow, mode, values):
        values = values.copy()
        mode = values.pop("mode", mode)
        fields = {key: values.pop(key) for key in tuple(values) if hasattr(style, key)}
        return replace(style, **fields), replace(flow, **values), mode

    def save_default(self):
        try:
            _, initial, values = self.draft()
            store = GlobalDefaultsStore()
            defaults, warning = store.load()
            if warning:
                raise ValueError(warning)
            if self.key == "page":
                previous = defaults.flow.template or store.ordinary_template(defaults.page)
                if not isinstance(previous, FlowTemplate) or previous.kind != "simple":
                    raise ValueError("新建文档的默认模板有专用版式，请在模板库中编辑。")
                new_template = with_geometry(previous, values)
                old_values = page_geometry(previous)
                if defaults.flow.template is None:
                    save = lambda: store.save_ordinary(previous, new_template)
                else:
                    save = lambda: store.save(replace(defaults, flow=replace(defaults.flow, template=new_template)))
            else:
                old_values = {key: defaults.mode if key == "mode" else
                              getattr(defaults.style, key) if hasattr(defaults.style, key) else
                              getattr(defaults.flow, key) for key in values}
                style, flow, mode = self.updated_layout(defaults.style, defaults.flow, defaults.mode, values)
                if defaults.run.endswith(".inkfont") and mode != "markdown":
                    raise ValueError("使用字体包的新建文档须使用 Markdown 模式。")
                save = lambda: store.save(replace(defaults, style=style, flow=flow, mode=mode))
            old_fields = dict(flattened(old_values))
            changes = [(path, old_fields.get(path), value) for path, value in flattened(values)
                       if old_fields.get(path) != value]
            if not changes:
                self.report("面板中的值已经是新建默认。")
                return False
            if not self.confirm_default(changes, values != initial):
                return False
            save()
            self.report("已保存本分类的新建默认。"
                        + ("面板中的改动仍待应用到当前文档。" if values != initial else ""))
            return True
        except (OSError, ValueError, TypeError) as error:
            self.report(str(error), error=True)
            return False

    def confirm_default(self, changes, pending):
        dialog = QtWidgets.QDialog(self)
        dialog.setObjectName("document_layout_default_confirmation")
        dialog.setWindowTitle("设为新建文档默认")
        column = QtWidgets.QVBoxLayout(dialog)
        scope = f"更新「{LAYOUT_TITLES[self.key]}」的新建默认，用于此后新建的文档。"
        if pending:
            scope += " 面板中的改动仍待应用到当前文档。"
        column.addWidget(label(scope))
        table = QtWidgets.QTreeWidget()
        table.setHeaderLabels(["设置项", "现有默认", "新默认"])
        table.setRootIsDecorated(False)
        table.setAlternatingRowColors(True)
        table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.NoSelection)
        table.header().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Stretch)
        page = self.drafts[self.key][1]
        for path, before, after in changes:
            key = path[-1]
            control = page.findChild(QtWidgets.QWidget, key)
            caption = control.accessibleName() if control is not None else ""
            if not caption and control is not None:
                for form in page.findChildren(QtWidgets.QFormLayout):
                    field_label = form.labelForField(control)
                    if isinstance(field_label, QtWidgets.QLabel):
                        caption = field_label.text()
                        break
            if not caption:
                if self.key != "page" and key in {"width_mm", "height_mm"}:
                    caption = "宽度" if key == "width_mm" else "高度"
                else:
                    caption = NAMES.get(key, key)
            table.addTopLevelItem(QtWidgets.QTreeWidgetItem(
                [caption, display_value(key, before), display_value(key, after)]
            ))
        column.addWidget(table, 1)
        buttons = QtWidgets.QDialogButtonBox()
        confirm = buttons.addButton("保存为新建默认", QtWidgets.QDialogButtonBox.ButtonRole.AcceptRole)
        confirm.setProperty("inkRole", "primary")
        cancel = buttons.addButton("取消", QtWidgets.QDialogButtonBox.ButtonRole.RejectRole)
        cancel.setDefault(True)
        cancel.setFocus()
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        column.addWidget(buttons)
        dialog.resize(550, min(450, 130 + 28 * len(changes)))
        try:
            return dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted
        finally:
            dialog.deleteLater()
