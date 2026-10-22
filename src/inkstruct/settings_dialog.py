"""Persistent application defaults with an optional explicit document update."""

from dataclasses import replace
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from .assets.resolver import AssetResolver
from .document.markdown import parse_markdown
from .document.styles import FlowStyle
from .global_defaults import GlobalDefaultsStore, LayoutDefaults, apply_to_document
from .settings_elements import ElementPage
from .settings_pages import (
    CapturePage,
    CompactSpinBox,
    LocalPreview,
    ProfileForm,
    acceptable,
    embed,
    label,
)

CATEGORIES = (
    ("preview", "应用设置", "预览绘制", "CPU GPU 栅格化 缓存 显卡 加速"),
    ("capture", "采集设置", "书写显示", "笔迹 粗细 书写格 田字格 配置"),
    ("paper", "排版默认设置", "纸张与默认模板", "页面 尺寸 宽度 高度 页边距 默认模板"),
    ("templates", "字体与模板", "打开模板库", "制作 新建 简单 自定义 布局 PDF 字段 管理"),
    ("font", "排版默认设置", "字体与字形", "作者 资源 导入 目录 符号 覆盖"),
    (
        "body",
        "排版默认设置",
        "正文与段落",
        "内容模式 Markdown Obsidian 字高 行高 笔宽 段距 标题 首行 列表 引用 缩进 英文 字距 标点 句读 间距",
    ),
    (
        "math",
        "排版默认设置",
        "公式",
        "字号 对齐 上下标 分式 根式 积分 运算符 矩阵 向量 编号 括号 定界符",
    ),
    ("table", "排版默认设置", "表格", "默认 独立 总宽 行高 列宽 对齐 留白 重复表头 跨页 跨页表头"),
    ("image", "排版默认设置", "图片", "默认 独立 宽度 高度 对齐 图题 SVG 容差"),
    ("code", "排版默认设置", "代码块", "字号 字格 行高 制表位 换行"),
    ("footnote", "排版默认设置", "脚注", "字号 间距 编号 分隔线 高度"),
)


class BodyPage(QtWidgets.QWidget):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        column = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()
        self.mode = QtWidgets.QComboBox()
        self.mode.addItem("Markdown 混排", "markdown")
        self.mode.addItem("纯文本检查", "plain-text")
        self.mode.setCurrentIndex(self.mode.findData(owner.mode))
        self.dialect = QtWidgets.QComboBox()
        self.dialect.addItem("普通 Markdown", "markdown")
        self.dialect.addItem("Obsidian 静态扩展", "obsidian")
        self.dialect.setCurrentIndex(self.dialect.findData(owner.flow.markdown_dialect))
        form.addRow("内容模式", self.mode)
        form.addRow("Markdown 格式", self.dialect)
        self.latin_spacing = QtWidgets.QComboBox()
        self.latin_spacing.addItem("按笔迹宽度（推荐）", "handwriting")
        self.latin_spacing.addItem("保留采集位置留白（旧版）", "capture")
        self.latin_spacing.setCurrentIndex(self.latin_spacing.findData(owner.flow.latin_spacing))
        self.latin_spacing.setAccessibleName("英文字母间距")
        self.latin_spacing.setToolTip("按笔迹宽度排列正文英文字母，保留字形大小和基线；公式与等宽代码使用原有规则。旧文档不自动切换。")
        form.addRow("英文字母间距", self.latin_spacing)
        self.punctuation_spacing = QtWidgets.QComboBox()
        self.punctuation_spacing.addItem("按笔迹紧凑排列（推荐）", "handwriting")
        self.punctuation_spacing.addItem("保留采集位置留白（旧版）", "capture")
        self.punctuation_spacing.setCurrentIndex(self.punctuation_spacing.findData(owner.flow.punctuation_spacing))
        self.punctuation_spacing.setAccessibleName("标点间距")
        self.punctuation_spacing.setToolTip("中英文标点按实际笔迹宽度排列，不预留半字或整字空位；保留最小笔迹间距。公式和代码不受影响；旧文档不自动切换。")
        form.addRow("标点间距", self.punctuation_spacing)
        column.addLayout(form)
        self.style = ProfileForm(
            owner.style,
            [
                (k, title, 0.000001, 2000, " mm")
                for k, title in [
                    ("em_mm", "字高"),
                    ("stroke_width_mm", "笔宽"),
                    ("line_height_mm", "行高"),
                ]
            ],
        )
        column.addWidget(self.style)
        self.flow = ProfileForm(
            owner.flow,
            [
                (
                    k,
                    title,
                    0.000001 if k in {"list_indent_mm", "quote_indent_mm"} else 0,
                    100,
                    " mm",
                )
                for k, title in [
                    ("paragraph_gap_mm", "段距"),
                    ("first_line_indent_mm", "首行缩进"),
                    ("heading_gap_mm", "标题段距"),
                    ("list_indent_mm", "列表缩进"),
                    ("quote_indent_mm", "引用缩进"),
                ]
            ],
        )
        column.addWidget(self.flow)
        headings = QtWidgets.QWidget()
        heading_form = QtWidgets.QFormLayout(headings)
        self.headings, self.initial_headings = [], []
        for i, value in enumerate(owner.flow.heading_scales, 1):
            control = CompactSpinBox()
            control.setRange(min(0.000001, value), max(100, value))
            control.setDecimals(6)
            control.setSuffix(" 倍")
            control.setValue(value)
            control.setAccessibleName(f"H{i} 标题字号倍率")
            heading_form.addRow(f"H{i} 标题字号", control)
            self.headings.append(control)
            self.initial_headings.append(control.value())
        column.addWidget(label("标题字号"))
        column.addWidget(headings)
        column.addWidget(label("尺寸单位为毫米。实际行距仍受笔迹边界限制；修改后将重新分页。"))
        self.preview = LocalPreview(owner.resolver, self.preview_configuration, self, letters=True)
        self.timer = self.preview.timer
        self.latin_spacing.currentIndexChanged.connect(self.preview.schedule)
        self.punctuation_spacing.currentIndexChanged.connect(self.preview.schedule)
        column.addWidget(label("效果预览"))
        column.addWidget(self.preview)
        for control in self.findChildren(QtWidgets.QDoubleSpinBox):
            control.valueChanged.connect(self.preview.schedule)
        column.addStretch()

    def preview_configuration(self):
        style, changes = self.configuration()
        return style, replace(self.owner.flow, **changes)

    def configuration(self):
        acceptable(self)
        flow = self.flow.configuration()
        headings = tuple(
            c.value() if c.value() != initial else original
            for c, initial, original in zip(
                self.headings, self.initial_headings, self.owner.flow.heading_scales
            )
        )
        return self.style.configuration(), {k: getattr(flow, k) for k in self.flow.controls} | {
            "heading_scales": headings,
            "markdown_dialect": self.dialect.currentData(),
            "latin_spacing": self.latin_spacing.currentData(),
            "punctuation_spacing": self.punctuation_spacing.currentData(),
        }

    def reset_defaults(self):
        self.style.reset_defaults()
        self.flow.reset_defaults()
        self.mode.setCurrentIndex(0)
        self.dialect.setCurrentIndex(0)
        self.latin_spacing.setCurrentIndex(0)
        self.punctuation_spacing.setCurrentIndex(0)
        defaults = FlowStyle().heading_scales
        # Preserve exact initial values through the same comparison path.
        self.initial_headings = [None] * len(defaults)
        for c, value in zip(self.headings, defaults):
            c.setValue(value)


class PaperPage(QtWidgets.QWidget):
    def __init__(self, owner):
        super().__init__()
        from .editor.template_manager import DefaultTemplateChoice

        column = QtWidgets.QVBoxLayout(self)
        self.page = ProfileForm(
            owner.page,
            [
                ("width_mm", "纸张宽度", 0.000001, 2000, " mm"),
                ("height_mm", "纸张高度", 0.000001, 2000, " mm"),
                ("margin_mm", "页边距", 0, 1000, " mm"),
            ],
        )
        column.addWidget(self.page)
        column.addWidget(label("新文档默认；启用模板时采用模板中的纸张与书写区域。"))
        self.template = DefaultTemplateChoice(owner.flow.template)
        column.addWidget(self.template)
        column.addWidget(label("制作模板：主窗口“字体与模板 → 模板”。修改本文布局：排版右侧“文档资源”。"))
        column.addStretch()

    def configuration(self):
        acceptable(self)
        return self.page.configuration(), self.template.configuration(), ()

    def reset_defaults(self):
        self.page.reset_defaults()
        self.template.set_template(None)


class FontPage(QtWidgets.QWidget):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        column = QtWidgets.QVBoxLayout(self)
        self.info = label("")
        column.addWidget(self.info)
        column.addWidget(
            label(
                "默认字体供新文档使用。选择后点击“应用”保存；已有项目继续使用其冻结字形。制作与管理在“字体与模板 → 字体”。"
            )
        )
        for text, callback in [
            ("选择已有字体包…", self.choose_font),
            ("选择生成字形目录…", self.choose_run),
            ("导入符号样本…", self.choose_symbols),
            ("刷新当前资源", self.refresh),
        ]:
            button = QtWidgets.QPushButton(text)
            button.clicked.connect(lambda checked=False, callback=callback: self.guard(callback))
            column.addWidget(button)
        column.addStretch()
        self.update_info()

    def guard(self, callback):
        try:
            callback()
            self.update_info()
            self.owner.error.clear()
        except (ValueError, OSError, TypeError) as error:
            self.owner.error.setText(str(error))

    def update_info(self):
        d = self.owner
        source = d.run or d.symbols or "未指定默认字体（新文档以内置数字试排）"
        self.info.setText(
            f"当前资源：{source}\n可用字符：{len(d.resolver.pools)} 种。完整覆盖情况由文档排版检查。"
        )

    def set_font(self, path):
        from .fonts.core import cached_font

        font = cached_font(Path(path))
        from .symbol_capture import CHARACTERS

        visible = set(self.owner.editor.source_session.source) | set(CHARACTERS)
        resolver = AssetResolver(embedded=font.glyphs(visible), builtin_numbers=True)
        self.owner.run, self.owner.symbols = str(Path(path).resolve()), ""
        self.owner.mode = "markdown"
        self.owner.resource_changed(resolver)
        if "body" in self.owner.pages:
            self.owner.pages["body"].mode.setCurrentIndex(0)

    def choose_font(self):
        from .resources_ui import FontPicker
        picker = FontPicker(self, default=True)
        if picker.exec() == QtWidgets.QDialog.Accepted:
            self.set_font(picker.path)
        picker.deleteLater()

    def set_run(self, path):
        from .assets.glyph_provider import GlyphProvider
        from .assets.symbol_provider import SymbolProvider

        generated = GlyphProvider.from_run(Path(path), self.owner.editor.source_session.source)
        samples = SymbolProvider.from_zip(Path(self.owner.symbols)) if self.owner.symbols else None
        self.owner.run = str(Path(path).resolve())
        self.owner.resource_changed(AssetResolver(generated, samples, builtin_numbers=True))

    def choose_run(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "选择生成字形目录", self.owner.run)
        if path:
            self.set_run(path)

    def choose_symbols(self):
        from .assets.symbol_provider import SymbolProvider
        from .document.table_style import calibrate_tables

        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "导入符号样本", "", "样本 (*.zip)")
        if path:
            samples = SymbolProvider.from_zip(Path(path))
            self.owner.flow = calibrate_tables(self.owner.flow, samples)
            self.owner.symbols = str(Path(path).resolve())
            resolver = AssetResolver(
                symbols=samples,
                embedded=tuple(g for pool in self.owner.resolver.pools.values() for g in pool),
                builtin_numbers=True,
            )
            self.owner.resource_changed(resolver)

    def refresh(self):
        if self.owner.run:
            if Path(self.owner.run).suffix == ".inkfont":
                self.set_font(self.owner.run)
            else:
                self.set_run(self.owner.run)
        else:
            raise ValueError("当前使用内嵌资源，无外部目录需要刷新。")


class SettingsDialog(QtWidgets.QDialog):
    def __init__(
        self, editor, collector=None, parent=None, *, category=None, target=None, reason=""
    ):
        super().__init__(parent or editor)
        from .ui_behavior import protect_parameter_wheels

        protect_parameter_wheels(QtWidgets.QApplication.instance())
        self.editor, self.collector = editor, collector
        self.defaults_store = GlobalDefaultsStore()
        defaults, self.defaults_warning = self.defaults_store.load()
        self.template_target, self.template_reason = target, reason
        self.requested_template_action = None
        self.flow, self.style, self.page, self.mode = (
            defaults.flow,
            defaults.style,
            defaults.page,
            defaults.mode,
        )
        self.run, self.symbols, self.resolver = defaults.run, defaults.symbols, editor.resolver
        self.resources_changed = False
        self.document = parse_markdown("", dialect=self.flow.markdown_dialect)
        self.pages, self.items = {}, {}
        self.current = None
        self.setObjectName("unified_settings_dialog")
        self.setWindowTitle("设置 · InkStruct")
        self.setModal(True)
        self.setSizeGripEnabled(True)
        self.setMinimumSize(980, 640)
        self.setStyleSheet(
            "QCheckBox::indicator:unchecked {background: transparent; border: 1px solid #8995a5;} "
            "QTreeWidget::item {min-height: 28px;} "
            '*[settingsSearchHit="true"] {border: 1px solid #d4982e;}'
        )
        self.preferences = GlobalDefaultsStore.make_settings()
        outer = QtWidgets.QVBoxLayout(self)
        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText("搜索设置，例如：行高、上下标、跨页表头")
        self.search.setAccessibleName("搜索设置")
        outer.addWidget(self.search)
        if self.defaults_warning:
            warning = label(self.defaults_warning)
            warning.setStyleSheet("color: #9a6010;")
            outer.addWidget(warning)
        splitter = QtWidgets.QSplitter()
        outer.addWidget(splitter, 1)
        self.navigation = QtWidgets.QTreeWidget()
        self.navigation.setHeaderHidden(True)
        self.navigation.setMinimumWidth(150)
        self.navigation.setMaximumWidth(190)
        self.navigation.setFixedWidth(180)
        splitter.addWidget(self.navigation)
        right = QtWidgets.QWidget()
        column = QtWidgets.QVBoxLayout(right)
        self.heading = label("")
        self.heading.setStyleSheet("font-size: 19px; font-weight: bold;")
        column.addWidget(self.heading)
        self.scope_info = label("")
        column.addWidget(self.scope_info)
        self.stack = QtWidgets.QStackedWidget()
        column.addWidget(self.stack, 1)
        splitter.addWidget(right)
        splitter.setStretchFactor(1, 1)
        self.error = label("")
        self.error.setStyleSheet("color: #c44d4d;")
        outer.addWidget(self.error)
        self.apply_current = QtWidgets.QCheckBox(
            "同时将默认排版参数应用到当前文档（保留表格、图片独立设置）"
        )
        self.apply_current.setObjectName("apply_defaults_to_current_document")
        outer.addWidget(self.apply_current)
        footer = QtWidgets.QHBoxLayout()
        self.reset = QtWidgets.QPushButton("恢复本分类初始值")
        self.reset.clicked.connect(self.reset_current)
        footer.addWidget(self.reset)
        footer.addStretch()
        self.buttons = QtWidgets.QWidget()
        actions = QtWidgets.QHBoxLayout(self.buttons)
        actions.setContentsMargins(0, 0, 0, 0)
        for text, callback in [("取消", self.reject), ("应用", self.apply), ("确定", self.accept)]:
            button = QtWidgets.QPushButton(text)
            button.setMinimumWidth(72)
            button.clicked.connect(callback)
            button.setAutoDefault(False)
            actions.addWidget(button)
        footer.addWidget(self.buttons)
        self.close_management = QtWidgets.QPushButton("关闭设置")
        self.close_management.clicked.connect(self.reject)
        footer.addWidget(self.close_management)
        outer.addLayout(footer)
        groups = {}
        for key, group, title, words in CATEGORIES:
            if key == "capture" and collector is None:
                continue
            if key == "templates":
                item = QtWidgets.QTreeWidgetItem(self.navigation, [title])
                item.setData(0, QtCore.Qt.ItemDataRole.UserRole, key)
                self.items[key] = item
                continue
            if group not in groups:
                item = QtWidgets.QTreeWidgetItem(self.navigation, [group])
                item.setFlags(item.flags() & ~QtCore.Qt.ItemFlag.ItemIsSelectable)
                groups[group] = item
            item = QtWidgets.QTreeWidgetItem(groups[group], [title])
            item.setData(0, QtCore.Qt.ItemDataRole.UserRole, key)
            item.setToolTip(0, f"{group} › {title}：{words}")
            self.items[key] = item
        self.navigation.expandAll()
        self.navigation.currentItemChanged.connect(self.category_selected)
        self.search.textChanged.connect(self.filter_categories)
        self.finished.connect(self.remember)
        size = self.preferences.value("size", QtCore.QSize(1100, 780))
        available = self.screen().availableGeometry().size()
        self.resize(
            min(size.width(), available.width() - 40), min(size.height(), available.height() - 64)
        )
        # Reserve the largest formula structure's intrinsic width, including
        # its controls. Do not hide a scrollbar while clipping the contents.
        self.make_page("math")
        self.pages["math"].ensurePolished()
        self.pages["math"].layout().activate()
        self.setMinimumWidth(max(980, self.pages["math"].minimumSizeHint().width() + 330))
        initial = category or self.preferences.value("last_layout_category", "body", str)
        self.select(initial if initial in self.items else "body")

    def select(self, key):
        self.items[key].setHidden(False)
        if self.items[key].parent() is not None:
            self.items[key].parent().setHidden(False)
        self.navigation.setCurrentItem(self.items[key])

    def category_selected(self, item, previous=None):
        if item is None or not item.data(0, QtCore.Qt.ItemDataRole.UserRole):
            return
        key = item.data(0, QtCore.Qt.ItemDataRole.UserRole)
        self.current = key
        self.error.clear()
        if key not in self.pages:
            self.make_page(key)
        self.stack.setCurrentWidget(self.pages[key].parentWidget().parentWidget())
        group, title = next((group, title) for k, group, title, _ in CATEGORIES if k == key)
        self.heading.setText(title if key == "templates" else f"{group} › {title}")
        self.scope_info.setText(
            "生效范围：本机采集显示"
            if key == "capture"
            else "生效范围：本机预览，下次启动应用生效；不修改文档。"
            if key == "preview"
            else "生效范围：全局默认，保存后新文档使用；已有文档保持原设置。"
        )
        management = key == "templates"
        self.apply_current.setVisible(not management)
        self.buttons.setVisible(not management)
        self.reset.setVisible(not management)
        self.close_management.setVisible(management)
        self.scope_info.setText(
            "此处只提供管理入口；新文档默认与本文操作分别确认。"
            if management
            else self.scope_info.text()
        )
        self.reset.setEnabled(key != "font")
        self.reset.setText(
            "恢复沿用文档默认"
            if key in {"table", "image"} and self.pages[key].current_key
            else "恢复本分类初始值"
        )
        if key != "capture":
            self.preferences.setValue("last_layout_category", key)

    def make_page(self, key):
        if key == "preview":
            from .editor.preview_settings import PreviewSettingsPage
            page = PreviewSettingsPage()
        elif key == "capture":
            page = CapturePage(self.collector)
        elif key == "templates":
            page = QtWidgets.QWidget()
            column = QtWidgets.QVBoxLayout(page)
            column.addWidget(label('模板制作、整理与导出已集中在“字体与模板 → 模板”。\n新文档默认模板仍在“纸张与默认模板”中设置；本文布局在排版右侧编辑。'))
            open_library = QtWidgets.QPushButton('打开模板库')
            open_library.clicked.connect(lambda: self.request_template_action('manage', None))
            column.addWidget(open_library)
            column.addStretch()
        elif key == "paper":
            page = PaperPage(self)
        elif key == "body":
            page = BodyPage(self)
        elif key == "font":
            page = FontPage(self)
        elif key in {"table", "image"}:
            page = ElementPage(key, self.document, self.flow)
            page.scope.hide()
            page.explanation.setText(
                "保存为全局默认，重启后保留；新文档使用这些值，已有文档保持原设置。"
            )
            page.status.setText("全局默认；单个表格或图片的独立属性请在排版右侧调整。")
            page.scope.currentIndexChanged.connect(
                lambda: self.reset.setText(
                    "恢复沿用文档默认" if page.current_key else "恢复本分类初始值"
                )
            )
        elif key == "math":
            from .editor.math_settings import GROUPS, MathSettingsDialog

            page = embed(
                MathSettingsDialog(
                    self.flow.math, resolver=self.resolver, stroke_width=self.style.stroke_width_mm
                )
            )
            page.categories.hide()
            choice = QtWidgets.QComboBox()
            choice.setAccessibleName("公式结构")
            choice.addItems([group[0] for group in GROUPS])
            choice.currentIndexChanged.connect(page.categories.setCurrentRow)
            page.categories.currentRowChanged.connect(choice.setCurrentIndex)
            page.layout().insertWidget(1, choice)
            page.structure_choice = choice
            # The unified page supplies the outer scroll area and title.
            # Remove the legacy inner scroll container, retaining its controls.
            legacy_body = page.layout().itemAt(2).layout()
            inner_scroll = legacy_body.itemAt(1).widget()
            content = inner_scroll.takeWidget()
            # Deferred deletes posted before a modal event loop can stay alive
            # until it closes. Hide the retired viewport and its scroll arrows now.
            inner_scroll.hide()
            inner_scroll.setObjectName("retired_math_scroll")
            legacy_body.removeWidget(inner_scroll)
            inner_scroll.deleteLater()
            page.layout().removeItem(legacy_body)
            page.layout().insertWidget(2, content)
            heading = page.layout().itemAt(0).layout()
            for i in range(heading.count()):
                widget = heading.itemAt(i).widget()
                if widget:
                    widget.hide()

            def reset_math():
                from .math.style import MathStyle

                index = page.categories.currentRow()
                defaults = MathStyle.handwriting()
                keys = {field for field, _ in GROUPS[index][2]}
                source = {3: "fraction_source", 4: "radical_source", 7: "delimiter_source"}.get(
                    index
                )
                if source:
                    keys.add(source)
                if index == 0:
                    keys.add("display_align")
                    keys.add("spacing_policy")
                page.original = replace(page.original, **{k: getattr(defaults, k) for k in keys})
                page.reset_category()
                for field_key in keys & page.controls.keys():
                    page.initial[field_key] = page.controls[field_key].value()

            page.reset_defaults = reset_math
        else:
            if key == "code":
                from .editor.code_settings import CodeSettingsDialog

                page = embed(CodeSettingsDialog(self.flow.code))
            else:
                from .editor.footnote_settings import FootnoteSettingsDialog

                page = embed(FootnoteSettingsDialog(self.flow.footnote))
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        scroll.setWidget(page)
        self.stack.addWidget(scroll)
        self.pages[key] = page

    def filter_categories(self, text):
        query = text.strip().casefold()
        found = []
        for key, group, title, words in CATEGORIES:
            if key not in self.items:
                continue
            item = self.items[key]
            visible = not query or query in f"{group} {title} {words}".casefold()
            item.setHidden(not visible)
            if visible:
                found.append(key)
        for i in range(self.navigation.topLevelItemCount()):
            group = self.navigation.topLevelItem(i)
            if group.childCount():
                group.setHidden(all(group.child(j).isHidden() for j in range(group.childCount())))
        if query and found:
            self.select(found[0])
            self.scope_info.setText(f"搜索结果：{self.heading.text()}。修改仅在点击应用后生效。")
        elif query:
            self.scope_info.setText("没有匹配的设置，可尝试“行高”“图片”“公式”等关键词。")
        page = self.pages[self.current]
        for widget in page.findChildren(QtWidgets.QWidget):
            text = (
                widget.text()
                if isinstance(widget, (QtWidgets.QLabel, QtWidgets.QAbstractButton))
                else widget.accessibleName()
            )
            hit = bool(query and query in text.casefold())
            widget.setProperty("settingsSearchHit", hit)
            widget.style().unpolish(widget)
            widget.style().polish(widget)
        if query:
            for button in page.findChildren(QtWidgets.QToolButton):
                if button.isCheckable():
                    button.setChecked(True)

    def request_template_action(self, action, template):
        try:
            flow, style, paper, mode, capture = self.collect()
            changed = (flow, style, paper, mode) != (
                self.flow,
                self.style,
                self.page,
                self.mode,
            ) or self.resources_changed
            changed = changed or (
                capture is not None
                and self.collector is not None
                and capture != self.collector.ui_settings
            )
            if changed:
                answer = QtWidgets.QMessageBox.question(
                    self,
                    "尚有未保存的默认设置",
                    "进入模板工作台前，是否保存这些默认设置？",
                    QtWidgets.QMessageBox.Save
                    | QtWidgets.QMessageBox.Discard
                    | QtWidgets.QMessageBox.Cancel,
                    QtWidgets.QMessageBox.Cancel,
                )
                if answer == QtWidgets.QMessageBox.Cancel:
                    return
                if answer == QtWidgets.QMessageBox.Save and not self.apply():
                    return
            self.requested_template_action = (action, template)
            self.done(20)
        except (ValueError, TypeError) as error:
            self.error.setText(str(error))

    def resource_changed(self, resolver):
        self.resolver = resolver
        self.resources_changed = True
        if "math" in self.pages:
            page = self.pages["math"]
            page.preview_resolver = AssetResolver(
                embedded=tuple(g for p in resolver.pools.values() for g in p), seed=resolver.seed
            )
            page.schedule_preview()

    def collect(self):
        flow, style, paper, mode = self.flow, self.style, self.page, self.mode
        capture = None
        for key, page in self.pages.items():
            try:
                if key == "capture":
                    capture = page.configuration()
                elif key == "body":
                    style, changes = page.configuration()
                    flow = replace(flow, **changes)
                    mode = page.mode.currentData()
                elif key == "paper":
                    paper, template, bindings = page.configuration()
                    flow = replace(flow, template=template, template_bindings=bindings)
                elif key in {"table", "image"}:
                    flow = replace(flow, **page.configuration())
                elif key in {"math", "code", "footnote"}:
                    acceptable(page)
                    flow = replace(flow, **{key: page.configuration()})
            except (ValueError, TypeError) as error:
                self.select(key)
                raise ValueError(f"{self.heading.text()}：{error}") from error
        if self.run and Path(self.run).suffix == ".inkfont" and mode != "markdown":
            self.select("body")
            raise ValueError("字体包使用 Markdown 模式；普通文字可直接输入。")
        return flow, style, paper, mode, capture

    def apply(self):
        try:
            flow, style, paper, mode, capture = self.collect()
            w = self.editor
            defaults = LayoutDefaults(paper, style, flow, mode, self.run, self.symbols)
            inspector = getattr(w, "element_inspector", None)
            if self.apply_current.isChecked() and inspector and inspector.has_pending():
                raise ValueError("右侧有未应用的元素修改，请先应用或取消，再应用全局默认。")
            if (
                self.apply_current.isChecked()
                and w.run_path.endswith(".inkfont")
                and mode != "markdown"
            ):
                raise ValueError("当前字体包文档须使用 Markdown 模式。")
            previous_capture = self.collector.ui_settings if self.collector else None
            capture_changed = capture is not None and capture != previous_capture
            if capture_changed:
                self.collector.ui_settings_store.save(capture)
            try:
                self.defaults_store.save(defaults)
            except (ValueError, OSError, TypeError) as error:
                if capture_changed:
                    try:
                        self.collector.ui_settings_store.save(previous_capture)
                    except (ValueError, OSError, TypeError) as rollback_error:
                        raise OSError(f"{error}；采集显示配置恢复失败：{rollback_error}") from error
                raise
            if capture_changed:
                self.collector.ui_settings = capture
                self.collector.apply_ui_settings(capture)
            if self.apply_current.isChecked():
                resources = (
                    (self.run, self.symbols, self.resolver) if self.resources_changed else None
                )
                apply_to_document(w, defaults, resources=resources)
            self.flow, self.style, self.page, self.mode = flow, style, paper, mode
            if 'preview' in self.pages:
                self.pages['preview'].save()
            self.resources_changed = False
            self.error.setStyleSheet("color: #236747;")
            self.error.setText("全局默认已保存；取消仅放弃尚未应用的修改。")
            return True
        except (ValueError, OSError, TypeError) as error:
            self.error.setStyleSheet("color: #c44d4d;")
            self.error.setText(str(error))
            return False

    def accept(self):
        if self.apply():
            super().accept()

    def reset_current(self):
        page = self.pages[self.current]
        if self.current == "code":
            from .document.code_style import CodeStyle

            default = CodeStyle()
            page.original = default
            for key, control in page.controls.items():
                control.setValue(getattr(default, key))
                page.initial[key] = control.value()
            page.tabs.setValue(default.tab_columns)
            page.wrap.setChecked(default.wrap_lines)
        elif hasattr(page, "reset_defaults"):
            page.reset_defaults()

    def remember(self, result):
        self.preferences.setValue("size", self.size())
        for page in self.pages.values():
            timer = getattr(page, "timer", None)
            if timer:
                timer.stop()


def open_settings(editor, collector=None, parent=None, *, category=None, target=None, reason=""):
    while True:
        dialog = SettingsDialog(
            editor, collector, parent, category=category, target=target, reason=reason
        )
        try:
            result = dialog.exec()
            requested = dialog.requested_template_action
        finally:
            dialog.hide()
            dialog.deleteLater()
        if not requested:
            return result
        if requested[0] == 'manage':
            from .resources_ui import open_management
            open_management(editor, 'templates')
            return result
        from .editor.template_manager import perform_template_action

        perform_template_action(editor, *requested, target=target)
        category, target = "templates", None


def gear_button(parent, callback):
    button = QtWidgets.QToolButton(parent)
    button.setObjectName("unified_settings_button")
    button.setText("⚙")
    font = button.font()
    font.setPointSize(17)
    button.setFont(font)
    button.setFixedSize(40, 36)
    button.setAccessibleName("设置")
    button.setToolTip("设置 (Ctrl+,)")
    button.clicked.connect(callback)
    shortcut = QtGui.QShortcut(QtGui.QKeySequence("Ctrl+,"), parent)
    shortcut.activated.connect(callback)
    button.settings_shortcut = shortcut
    return button
