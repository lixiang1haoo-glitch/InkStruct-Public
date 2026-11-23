"""Scoped drafts shared by document and new-document layout settings."""

from dataclasses import asdict, is_dataclass, replace
from types import SimpleNamespace

from PySide6 import QtCore, QtWidgets

from ..document.flow_template import FlowTemplate
from ..document.markdown import parse_markdown
from ..global_defaults import GlobalDefaultsStore
from ..settings_dialog import CATEGORIES, layout_settings_page
from ..settings_pages import CompactSpinBox, acceptable, compact_form_parameters, label, scroll_page


LAYOUT_TITLES = {"body": "正文与段落", "page": "页面设置"}
LAYOUT_TITLES.update({key: title for key, group, title, _ in CATEGORIES if group == "排版默认设置"})
PAPER_SIZES = {"A4": (210, 297), "A5": (148, 210), "B5": (176, 250)}
PAGE_FIELDS = ("width_mm", "height_mm", "top_mm", "right_mm", "bottom_mm", "left_mm")
NAMES = {
    "width_mm": "纸张宽度", "height_mm": "纸张高度", "top_mm": "上边距",
    "right_mm": "右边距", "bottom_mm": "下边距", "left_mm": "左边距",
    "em_mm": "字高", "line_height_mm": "行高", "stroke_width_mm": "笔宽",
    "paragraph_gap_mm": "段距", "paragraph_align": "正文对齐", "first_line_indent_mm": "首行缩进",
    "heading_gap_mm": "标题段距", "list_indent_mm": "列表缩进", "quote_indent_mm": "引用缩进",
    "heading_scales": "标题字号倍率", "markdown_dialect": "Markdown 格式",
    "enabled": "启用自然书写",
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
    return FlowTemplate.ordinary(width_mm=page.width_mm,
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
            if advanced is not None:
                button = QtWidgets.QPushButton("编辑当前文档模板…")
                button.clicked.connect(advanced)
                column.addWidget(button, alignment=QtCore.Qt.AlignmentFlag.AlignLeft)
            else:
                column.addWidget(label("可在模板库中调整默认模板。"))
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
        self.size_label = label("")
        form.addRow("尺寸", self.size_label)
        self.form = form
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
            form.addRow(title, control)
        self.initial = {key: control.value() for key, control in self.controls.items()}
        width, height = (self.controls[key].value() for key in PAGE_FIELDS[:2])
        size = tuple(sorted((width, height)))
        self.paper.setCurrentText(next((name for name, dims in PAPER_SIZES.items() if dims == size), "自定义"))
        self.paper.currentTextChanged.connect(self.choose_paper)
        self.direction.currentIndexChanged.connect(self.choose_direction)
        for key in PAGE_FIELDS[:2]:
            self.controls[key].valueChanged.connect(self.show_dimensions)
        self.show_dimensions()
        column.addLayout(form)
        compact_form_parameters(self)
        column.addStretch()

    def show_dimensions(self):
        width, height = (self.controls[key].value() for key in PAGE_FIELDS[:2])
        custom = self.paper.currentText() == "自定义"
        self.size_label.setText(f"{width:g} × {height:g} mm")
        self.form.setRowVisible(self.size_label, not custom)
        for key in PAGE_FIELDS[:2]:
            self.form.setRowVisible(self.controls[key], custom)
        with QtCore.QSignalBlocker(self.direction):
            self.direction.setCurrentIndex(int(width > height))

    def choose_paper(self, name):
        if name == "自定义":
            self.show_dimensions()
            width = self.controls["width_mm"]
            width.setFocus()
            width.selectAll()
            return
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
        self.show_dimensions()

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


class LayoutSettings(QtWidgets.QStackedWidget):
    """Keep one draft per category for a single document or the new-document defaults."""

    changed = QtCore.Signal()

    def __init__(self, editor, *, defaults=False):
        super().__init__()
        self.editor = editor
        self.defaults = defaults
        self.session = editor.source_session
        self.drafts = {}
        self.pending = set()
        self.current = None
        self.select_error = None
        self.store = GlobalDefaultsStore() if defaults else None

    @property
    def pages(self):
        return {key: entry[1] for key, entry in self.drafts.items()}

    def select(self, key):
        self.current = key
        if key not in self.drafts:
            self.make_draft(key)
        self.setCurrentWidget(self.drafts[key][0])
        self.changed.emit()

    def draft_owner(self):
        editor = self.editor
        if self.defaults:
            layout, _ = self.store.for_new_document()
            return SimpleNamespace(style=layout.style, flow=layout.flow, mode=layout.mode,
                                   page=layout.page, session_path=None, run_path=layout.run)
        return editor

    def make_draft(self, key):
        state = self.draft_owner()
        owner = SimpleNamespace(
            style=state.style, flow=state.flow, mode=state.mode, run=state.run_path,
            resolver=self.editor.resolver, document=parse_markdown("") if key in {"table", "image"} else None,
        )
        advanced = self.edit_template if not self.defaults else None
        page = PageSetup(state, advanced) if key == "page" else layout_settings_page(
            owner, key, for_document=True, defaults=self.defaults,
        )
        if key == "body" and (state.session_path or state.run_path.endswith(".inkfont")):
            page.mode.setEnabled(False)
            page.mode.setToolTip("当前项目或字体沿用其内容模式。")
        panel = page if key == "math" else scroll_page(page)
        self.addWidget(panel)
        self.drafts[key] = (panel, page, self.values(key, page))
        for field in page.findChildren(QtWidgets.QWidget):
            if isinstance(field, (QtWidgets.QSpinBox, QtWidgets.QDoubleSpinBox)):
                field.valueChanged.connect(lambda _value, name=key: self.update_pending(name))
            elif isinstance(field, QtWidgets.QComboBox):
                field.currentIndexChanged.connect(lambda _index, name=key: self.update_pending(name))
            elif isinstance(field, QtWidgets.QLineEdit):
                field.textChanged.connect(lambda _text, name=key: self.update_pending(name))
            elif isinstance(field, QtWidgets.QAbstractButton):
                field.clicked.connect(lambda _checked, name=key: self.update_pending(name))
                field.toggled.connect(lambda _checked, name=key: self.update_pending(name))

    def values(self, key, page):
        if key == "body":
            style, flow = page.configuration()
            return asdict(style) | flow | {"mode": page.mode.currentData()}
        if key == "page":
            return page.configuration()
        if key in {"table", "image"}:
            return {key: page.default_style()}
        acceptable(page)
        return {key: page.configuration()}

    def update_pending(self, key):
        if key not in self.drafts:
            return
        _, page, initial = self.drafts[key]
        try:
            changed = initial != self.values(key, page)
        except (ValueError, TypeError):
            changed = True
        if changed:
            self.pending.add(key)
        else:
            self.pending.discard(key)
        self.changed.emit()

    def collect_changes(self):
        changes, geometry = {}, None
        for key, (_, page, initial) in self.drafts.items():
            if key not in self.pending:
                continue
            try:
                values = self.values(key, page)
                if key == "page":
                    geometry = with_geometry(page.template, values)
                else:
                    changes.update({name: value for name, value in values.items() if value != initial[name]})
            except (ValueError, TypeError):
                self.select_error = key
                raise
        return changes, geometry

    def reload(self, keys):
        for key in keys:
            entry = self.drafts.pop(key, None)
            if entry is not None:
                panel, _, _ = entry
                self.removeWidget(panel)
                panel.deleteLater()
            self.pending.discard(key)
        if self.current is not None:
            self.select(self.current)

    def validate_document(self):
        if self.editor.source_session is not self.session:
            raise ValueError("当前文档已更换，请重新打开设置。")

    def apply(self):
        self.select_error = None
        changes, geometry = self.collect_changes()
        if not changes and geometry is None:
            return False
        if self.defaults:
            defaults, warning = self.store.load()
            if warning:
                raise ValueError(warning)
            self.persist_defaults(self.store, defaults, changes, geometry)
        else:
            self.apply_to_document(changes, geometry)
        self.reload(tuple(self.pending))
        return True

    def apply_to_document(self, changes, geometry):
        self.validate_document()
        editor = self.editor
        if {"table", "image"} & changes.keys() and editor.element_inspector.has_pending():
            raise ValueError("请先在右侧元素属性中应用或取消修改，再应用文档设置。")
        style, flow, mode = self.updated_layout(editor.style, editor.flow, editor.mode, changes)
        if editor.run_path.endswith(".inkfont") and mode != "markdown":
            raise ValueError("当前字体包须使用 Markdown 模式。")
        page = editor.page
        if geometry is not None:
            opened = self.drafts["page"][1].template
            if editor.mode == "markdown" and editor.flow.template is not None and editor.flow.template != opened:
                raise ValueError("当前文档的模板已变化，请重新打开设置。")
            if mode == "plain-text":
                page = replace(page, width_mm=geometry.width_mm, height_mm=geometry.height_mm,
                               margin_mm=min(geometry.margins_mm))
        editor.loaded_style, editor.flow, editor.page, editor.mode = style, flow, page, mode
        editor._sync_document_controls(style)
        if geometry is not None and mode == "markdown" and geometry != flow.template:
            editor.template_content_panel.apply_template(geometry)
        else:
            editor.mark_dirty()
            editor.schedule_layout()

    def edit_template(self):
        self.editor.template_settings()
        self.reload(("page",))

    @staticmethod
    def updated_layout(style, flow, mode, values):
        values = values.copy()
        mode = values.pop("mode", mode)
        fields = {key: values.pop(key) for key in tuple(values) if hasattr(style, key)}
        return replace(style, **fields), replace(flow, **values), mode

    def default_geometry(self, store, defaults):
        if defaults.mode == "plain-text":
            return simple_template(defaults.page)
        return defaults.flow.template or store.ordinary_template(defaults.page)

    def persist_defaults(self, store, defaults, values, geometry):
        style, flow, mode = self.updated_layout(defaults.style, defaults.flow, defaults.mode, values)
        if defaults.run.endswith(".inkfont") and mode != "markdown":
            raise ValueError("使用字体包的新建文档须使用 Markdown 模式。")
        page, ordinary = defaults.page, None
        if geometry is not None:
            if mode == "plain-text":
                page = replace(page, width_mm=geometry.width_mm, height_mm=geometry.height_mm,
                               margin_mm=min(geometry.margins_mm))
            else:
                previous = defaults.flow.template or store.ordinary_template(defaults.page)
                if not isinstance(previous, FlowTemplate) or previous.kind != "simple":
                    raise ValueError("新建文档默认使用专用模板，请在模板库中调整版式。")
                template = with_geometry(previous, page_geometry(geometry))
                if defaults.flow.template is None:
                    ordinary = (previous, template)
                else:
                    flow = replace(flow, template=template)
        updated = replace(defaults, style=style, flow=flow, mode=mode, page=page)
        store.save(updated, ordinary=ordinary)

    def prepare_default_copy(self):
        self.validate_document()
        key = self.current
        _, page, initial = self.drafts[key]
        values = self.values(key, page)
        store = GlobalDefaultsStore()
        defaults, warning = store.load()
        if warning:
            raise ValueError(warning)
        if key == "page":
            previous = self.default_geometry(store, defaults)
            if not isinstance(previous, FlowTemplate) or previous.kind != "simple":
                raise ValueError("新建文档默认使用专用模板，请在模板库中调整版式。")
            geometry = with_geometry(previous, values)
            if defaults.mode == "plain-text" and len(set(geometry.margins_mm)) != 1:
                raise ValueError("纯文本的新建默认只支持一致的四向页边距。")
            old_values = page_geometry(previous)
            save = lambda: self.persist_defaults(store, defaults, {}, geometry)
        else:
            old_values = {name: defaults.mode if name == "mode" else
                          getattr(defaults.style, name) if hasattr(defaults.style, name) else
                          getattr(defaults.flow, name) for name in values}
            save = lambda: self.persist_defaults(store, defaults, values, None)
        old_fields = dict(flattened(old_values))
        rows = []
        for path, value in flattened(values):
            previous = old_fields.get(path)
            if previous != value:
                name = path[-1]
                rows.append((field_caption(page, key, name), display_value(name, previous),
                             display_value(name, value)))
        return key, rows, values != initial, save

    def can_copy(self):
        return self.current is not None and (
            self.current != "page" or self.pages["page"].editable
        )


def field_caption(page, category, key):
    control = page.findChild(QtWidgets.QWidget, key)
    if control is not None:
        if caption := control.accessibleName():
            return caption
        for form in page.findChildren(QtWidgets.QFormLayout):
            field_label = form.labelForField(control)
            if isinstance(field_label, QtWidgets.QLabel):
                return field_label.text()
    if category != "page" and key in {"width_mm", "height_mm"}:
        return "宽度" if key == "width_mm" else "高度"
    return NAMES.get(key, key)
