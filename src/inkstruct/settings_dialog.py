"""Persistent application defaults with an optional explicit document update."""

from dataclasses import replace
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from .document.han_variation import HanVariation
from .document.markdown import parse_markdown
from .document.styles import FlowStyle
from .global_defaults import GlobalDefaultsStore, LayoutDefaults, apply_to_document
from .settings_elements import ElementPage
from .settings_pages import (
    AppearancePage,
    CapturePage,
    CompactSpinBox,
    ProfileForm,
    acceptable,
    align_form_labels,
    compact_form_parameters,
    embed,
    label,
)
from .theme import set_tone

CATEGORIES = (
    ("appearance", "应用设置", "主题", "外观 深色 浅色 跟随系统 明暗 颜色"),
    ("preview", "应用设置", "预览绘制", "CPU GPU 栅格化 缓存 显卡 加速"),
    ("capture", "采集设置", "书写显示", "书写格 参考格 比例 田字格 配置"),
    (
        "body",
        "排版默认设置",
        "正文与段落",
        "内容模式 Markdown Obsidian 字高 行高 笔宽 段距 标题 首行 列表 引用 缩进 英文 字距 标点 句读 间距 对齐 两端 抖动 中文 微扰 随机 种子",
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
        self.paragraph_align = QtWidgets.QComboBox()
        self.paragraph_align.setObjectName("paragraph_align")
        self.paragraph_align.setAccessibleName("正文对齐")
        self.paragraph_align.addItem("两端对齐（段尾靠左）", "justify")
        self.paragraph_align.addItem("左对齐（保留行尾空白）", "left")
        self.paragraph_align.setCurrentIndex(self.paragraph_align.findData(owner.flow.paragraph_align))
        self.paragraph_align.setToolTip("自动折行时，将余量分摊到汉字间隙、词间空格及公式边界；段尾与手动换行不拉伸，英文单词及公式内部不拆开。")
        form.addRow("正文对齐", self.paragraph_align)
        variation = owner.flow.han_variation
        self.original_variation = variation
        self.upgrade_variation = False
        natural = QtWidgets.QGroupBox("自然书写（中文 · 实验性）")
        natural_form = QtWidgets.QFormLayout(natural)
        self.han_enabled = QtWidgets.QCheckBox("启用自然书写")
        self.han_enabled.setObjectName("han_variation_enabled")
        self.han_enabled.setChecked(variation.enabled)
        natural_form.addRow(self.han_enabled)
        self.variation_controls = {}
        for name, title in (("strength", "笔画与倾斜变化"), ("size_strength", "字形大小变化"),
                            ("spacing_strength", "字距变化"), ("baseline_strength", "基线上下变化")):
            control = QtWidgets.QDoubleSpinBox()
            control.setObjectName("han_variation_"+name)
            control.setAccessibleName(title)
            control.setRange(0,100)
            control.setDecimals(1)
            control.setSuffix(" %")
            control.setSingleStep(5)
            control.setValue(getattr(variation,name)*100)
            self.han_enabled.toggled.connect(control.setEnabled)
            control.setEnabled(variation.enabled)
            self.variation_controls[name] = control
            setattr(self,"han_"+name,control)
            natural_form.addRow(title,control)
        self.initial_variation_values = {k:c.value() for k,c in self.variation_controls.items()}
        self.han_seed = QtWidgets.QSpinBox()
        self.han_seed.setObjectName("han_variation_seed")
        self.han_seed.setAccessibleName("自然书写随机种子")
        self.han_seed.setRange(0,2147483647)
        self.han_seed.setValue(variation.seed)
        self.han_enabled.toggled.connect(self.han_seed.setEnabled)
        self.han_seed.setEnabled(variation.enabled)
        natural_form.addRow("随机种子",self.han_seed)
        natural_form.addRow(label("四项强度可分别调节；100% 对应最大变化。字距和基线变化可能改变换行、分页。固定种子可复现；字体包、原始样本、公式和代码保持原样。"))
        if variation.schema_version == "inkstruct_han_variation_v1" and variation.enabled:
            natural_form.addRow(label("此项目保留旧版微扰效果；可主动切换新版，或修改任一自然书写选项后切换。"))
            self.upgrade_natural = QtWidgets.QPushButton("使用新版自然书写")
            self.upgrade_natural.clicked.connect(self.choose_natural_version)
            natural_form.addRow(self.upgrade_natural)
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
        column.addWidget(natural)
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
        column.addStretch()
        compact_form_parameters(self)
        align_form_labels(form, self.style.layout(), self.flow.layout(), heading_form)

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
            "paragraph_align": self.paragraph_align.currentData(),
            "han_variation": self.variation_configuration(),
        }

    def choose_natural_version(self):
        self.upgrade_variation = True
        self.upgrade_natural.setText("已选择新版算法")
        self.upgrade_natural.setEnabled(False)

    def variation_configuration(self):
        original = self.original_variation
        values = {key:(getattr(original,key) if control.value()==self.initial_variation_values.get(key)
                       else control.value()/100) for key,control in self.variation_controls.items()}
        if (not self.upgrade_variation and self.han_enabled.isChecked()==original.enabled and self.han_seed.value()==original.seed
                and all(value==getattr(original,key) for key,value in values.items())):
            return original
        return HanVariation(enabled=self.han_enabled.isChecked(),seed=self.han_seed.value(),**values)

    def reset_defaults(self):
        self.style.reset_defaults()
        self.flow.reset_defaults()
        self.mode.setCurrentIndex(0)
        self.dialect.setCurrentIndex(0)
        self.latin_spacing.setCurrentIndex(0)
        self.punctuation_spacing.setCurrentIndex(0)
        self.paragraph_align.setCurrentIndex(0)
        self.han_enabled.setChecked(False)
        self.han_seed.setValue(0)
        self.initial_variation_values = {}
        for key,control in self.variation_controls.items():
            control.setValue(getattr(HanVariation(),key)*100)
        defaults = FlowStyle().heading_scales
        # Preserve exact initial values through the same comparison path.
        self.initial_headings = [None] * len(defaults)
        for c, value in zip(self.headings, defaults):
            c.setValue(value)


class SettingsDialog(QtWidgets.QDialog):
    def __init__(
        self, editor, collector=None, parent=None, *, category=None
    ):
        super().__init__(parent or editor)
        from .ui_behavior import protect_parameter_wheels

        protect_parameter_wheels(QtWidgets.QApplication.instance())
        self.editor, self.collector = editor, collector
        self.defaults_store = GlobalDefaultsStore()
        defaults, self.defaults_warning = self.defaults_store.load()
        self.flow, self.style, self.page, self.mode = (
            defaults.flow,
            defaults.style,
            defaults.page,
            defaults.mode,
        )
        self.run, self.symbols, self.resolver = defaults.run, defaults.symbols, editor.resolver
        self.document = parse_markdown("", dialect=self.flow.markdown_dialect)
        self.pages, self.items = {}, {}
        self.current = None
        self.setObjectName("unified_settings_dialog")
        self.setWindowTitle("设置 · InkStruct")
        self.setModal(True)
        self.setSizeGripEnabled(True)
        self.preferences = GlobalDefaultsStore.make_settings()
        outer = QtWidgets.QVBoxLayout(self)
        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText("搜索设置，例如：行高、上下标、跨页表头")
        self.search.setAccessibleName("搜索设置")
        outer.addWidget(self.search)
        if self.defaults_warning:
            warning = label(self.defaults_warning)
            set_tone(warning, "warning")
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
        self.heading.setProperty("inkRole", "title")
        column.addWidget(self.heading)
        self.scope_info = label("")
        column.addWidget(self.scope_info)
        self.stack = QtWidgets.QStackedWidget()
        column.addWidget(self.stack, 1)
        splitter.addWidget(right)
        splitter.setStretchFactor(1, 1)
        self.error = label("")
        self.error.setProperty("inkRole", "status")
        set_tone(self.error, "danger")
        outer.addWidget(self.error)
        self.has_current_document = bool(editor.session_path or editor.dirty or editor.source_session.source
                                         or editor.document_started)
        footer = QtWidgets.QHBoxLayout()
        self.reset = QtWidgets.QPushButton("恢复本分类初始值")
        self.reset.setAutoDefault(False)
        self.reset.clicked.connect(self.reset_current)
        footer.addWidget(self.reset)
        footer.addStretch()
        self.buttons = QtWidgets.QWidget()
        actions = QtWidgets.QHBoxLayout(self.buttons)
        actions.setContentsMargins(0, 0, 0, 0)
        for text, callback in [("取消", self.reject), ("存为默认", self.accept),
                               ("应用并保存", lambda: self.apply(to_document=True))]:
            button = QtWidgets.QPushButton(text)
            button.setMinimumWidth(72)
            button.clicked.connect(callback)
            button.setAutoDefault(False)
            if text == ("应用并保存" if self.has_current_document else "存为默认"):
                button.setProperty("inkRole", "primary")
            if text == "存为默认":
                self.save_button = button
            actions.addWidget(button)
            if text == "应用并保存":
                self.apply_document = button
                hint = "更新当前文档，并保存为新文档默认"
                button.setToolTip(hint)
                button.setAccessibleDescription(hint)
                button.setVisible(self.has_current_document)
        footer.addWidget(self.buttons)
        outer.addLayout(footer)
        groups = {}
        for key, group, title, words in CATEGORIES:
            if key == "capture" and collector is None:
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
        size = self.preferences.value("size", QtCore.QSize(1480, 900))
        available = (parent or editor).screen().availableGeometry().size()
        self.setMinimumSize(min(840, available.width() - 40), min(640, available.height() - 64))
        self.resize(
            min(max(self.minimumWidth(), size.width()), available.width() - 40),
            min(max(self.minimumHeight(), size.height()), available.height() - 64),
        )
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
        page = self.pages[key]
        self.stack.setCurrentWidget(page if key == "math" else page.parentWidget().parentWidget())
        group, title = next((group, title) for k, group, title, _ in CATEGORIES if k == key)
        self.heading.setText(f"{group} › {title}")
        self.apply_document.setVisible(self.has_current_document and key != "appearance")
        self.save_button.setText("保存" if key == "appearance" else "存为默认")
        role = "primary" if self.apply_document.isHidden() else None
        if self.save_button.property("inkRole") != role:
            self.save_button.setProperty("inkRole", role)
            self.save_button.style().unpolish(self.save_button)
            self.save_button.style().polish(self.save_button)
        self.scope_info.setText(
            "生效范围：本机采集显示"
            if key == "capture"
            else "生效范围：本机应用界面，保存后立即切换。"
            if key == "appearance"
            else "生效范围：本机预览，下次启动应用生效；不修改文档。"
            if key == "preview"
            else "生效范围：全局默认，保存后新文档使用；已有文档保持原设置。"
        )
        self.reset.setText(
            "恢复沿用文档默认"
            if key in {"table", "image"} and self.pages[key].current_key
            else "恢复本分类初始值"
        )
        if key != "capture":
            self.preferences.setValue("last_layout_category", key)

    def make_page(self, key):
        if key == "appearance":
            page = AppearancePage(self.preferences)
        elif key == "preview":
            from .editor.preview_settings import PreviewSettingsPage
            page = PreviewSettingsPage()
        elif key == "capture":
            page = CapturePage(self.collector)
        elif key == "body":
            page = BodyPage(self)
        elif key in {"table", "image"}:
            page = ElementPage(key, self.document, self.flow, scrollable=False)
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
            from .editor.math_settings import MathSettingsDialog

            page = embed(MathSettingsDialog(
                self.flow.math, resolver=self.resolver, stroke_width=self.style.stroke_width_mm,
                embedded=True, font_path=self.run or self.editor.run_path,
            ))

            page.reset_defaults = page.reset_category
            self.stack.addWidget(page)
            self.pages[key] = page
            return
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

    def apply(self, *, to_document=False):
        try:
            flow, style, paper, mode, capture = self.collect()
            w = self.editor
            defaults = LayoutDefaults(paper, style, flow, mode, self.run, self.symbols)
            appearance = self.pages.get("appearance")
            theme_changed = appearance is not None and appearance.changed
            save_defaults = (
                not theme_changed or to_document
                or (flow, style, paper, mode) != (self.flow, self.style, self.page, self.mode)
            )
            inspector = getattr(w, "element_inspector", None)
            if to_document and not self.has_current_document:
                raise ValueError("没有当前文档。")
            if to_document and inspector and inspector.has_pending():
                raise ValueError("右侧有未应用的元素修改，请先应用或取消，再应用全局默认。")
            if (
                to_document
                and w.run_path.endswith(".inkfont")
                and mode != "markdown"
            ):
                raise ValueError("当前字体包文档须使用 Markdown 模式。")
            previous_capture = self.collector.ui_settings if self.collector else None
            capture_changed = capture is not None and capture != previous_capture
            if capture_changed:
                self.collector.ui_settings_store.save(capture)
            try:
                if save_defaults:
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
            if to_document:
                apply_to_document(w, defaults)
            self.flow, self.style, self.page, self.mode = flow, style, paper, mode
            if 'preview' in self.pages:
                self.pages['preview'].save()
            if theme_changed:
                appearance.save()
            set_tone(self.error, "success")
            self.error.setText(
                "已更新当前文档并存为默认。" if to_document
                else "已保存应用主题。" if theme_changed and not save_defaults
                else "已保存为新文档默认。"
            )
            return True
        except (ValueError, OSError, TypeError) as error:
            set_tone(self.error, "danger")
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


def open_settings(editor, collector=None, parent=None, *, category=None):
    dialog = SettingsDialog(editor, collector, parent, category=category)
    try:
        return dialog.exec()
    finally:
        dialog.hide()
        dialog.deleteLater()


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
