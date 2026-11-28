"""Unified settings with separate document, defaults and application scopes."""

from dataclasses import replace

from PySide6 import QtCore, QtGui, QtWidgets

from .document.han_variation import HanVariation
from .document.styles import FlowStyle
from .global_defaults import GlobalDefaultsStore
from .settings_elements import ElementPage
from .settings_pages import (
    AboutPage,
    AppearancePage,
    CapturePage,
    CompactSpinBox,
    ProfileForm,
    acceptable,
    align_form_labels,
    compact_form_parameters,
    embed,
    label,
    scroll_page,
)
from .theme import set_tone

CATEGORIES = (
    ("appearance", "应用设置", "主题", "外观 深色 浅色 跟随系统 明暗 颜色"),
    ("preview", "应用设置", "预览绘制", "CPU GPU 栅格化 缓存 显卡 加速"),
    ("about", "应用设置", "关于", "InkStruct 墨构 应用版本 GitHub 文档站 官方 QQ 群 1035966437"),
    ("capture", "采集设置", "书写显示", "书写格 参考格 比例 田字格 配置"),
    (
        "body",
        "排版默认设置",
        "正文与段落",
        "内容模式 Markdown 字高 行高 笔宽 段距 标题 首行 列表 引用 缩进 汉字间距 英文 字母与数字间距 字距 标点 句读 间距 对齐 两端 抖动 中文 微扰 随机 种子",
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
)


class BodyPage(QtWidgets.QWidget):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        column = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()
        self.mode = QtWidgets.QComboBox()
        self.mode.addItem("Markdown 混排", "markdown")
        self.mode.addItem("纯文本", "plain-text")
        self.mode.setCurrentIndex(self.mode.findData(owner.mode))
        form.addRow("内容模式", self.mode)
        self.paragraph_align = QtWidgets.QComboBox()
        self.paragraph_align.setObjectName("paragraph_align")
        self.paragraph_align.setAccessibleName("正文对齐")
        self.paragraph_align.addItem("两端对齐（段尾靠左）", "justify")
        self.paragraph_align.addItem("左对齐（保留行尾空白）", "left")
        self.paragraph_align.setCurrentIndex(self.paragraph_align.findData(owner.flow.paragraph_align))
        self.paragraph_align.setToolTip("自动折行时，将余量分摊到汉字间隙、词间空格及公式边界；段尾与手动换行不拉伸，英文单词及公式内部不拆开。")
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
        column.addWidget(label("正文"))
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
                    ("list_indent_mm", "列表缩进"),
                    ("quote_indent_mm", "引用缩进"),
                ]
            ],
        )
        self.flow.layout().insertRow(1, "正文对齐", self.paragraph_align)
        paragraph_title = label("段落")
        column.addWidget(paragraph_title)
        column.addWidget(self.flow)
        self.heading_group = ProfileForm(owner.flow, [("heading_gap_mm", "标题段距", 0, 100, " mm")])
        heading_form = self.heading_group.layout()
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
        heading_title = label("标题")
        column.addWidget(heading_title)
        column.addWidget(self.heading_group)
        column.addWidget(natural)
        column.addWidget(label("尺寸单位为毫米。实际行距仍受笔迹边界限制；修改后将重新分页。"))
        column.addStretch()
        compact_form_parameters(self)
        align_form_labels(form, self.style.layout(), self.flow.layout(), heading_form)

        def show_mode_settings():
            markdown = self.mode.currentData() == "markdown"
            for widget in (paragraph_title, self.flow, heading_title, self.heading_group):
                widget.setVisible(markdown)

        self.mode.currentIndexChanged.connect(show_mode_settings)
        show_mode_settings()

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
            "heading_gap_mm": self.heading_group.configuration().heading_gap_mm,
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
        self.heading_group.reset_defaults()
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


class ApplicationPreferences(QtWidgets.QStackedWidget):
    changed = QtCore.Signal()

    def __init__(self, editor, collector, preferences):
        super().__init__()
        self.editor, self.collector, self.preferences = editor, collector, preferences
        self.pages, self.panels = {}, {}
        self.active = False

    def select(self, key):
        if key not in self.pages:
            if key == "appearance":
                page = AppearancePage(self.preferences)
                page.theme.currentIndexChanged.connect(self.changed)
            elif key == "preview":
                from .editor.preview_settings import PreviewSettingsPage

                page = PreviewSettingsPage()
                page.acceleration.toggled.connect(self.changed)
                page.acceleration.toggled.connect(self.refresh_preview)
                page.backend.currentIndexChanged.connect(self.changed)
            elif key == "capture":
                page = CapturePage(self.collector)
                page.grid.valueChanged.connect(self.changed)
            else:
                page = AboutPage()
            self.pages[key] = page
            self.panels[key] = scroll_page(page)
            self.addWidget(self.panels[key])
        self.setCurrentWidget(self.panels[key])

    def set_active(self, active):
        self.active = active
        self.refresh_preview()

    def refresh_preview(self, *_):
        if preview := self.pages.get("preview"):
            value = preview.acceleration.isChecked() if self.active else preview.saved_acceleration
            self.editor.canvas.set_render_acceleration(value)

    @property
    def pending(self):
        capture = self.pages.get("capture")
        if capture is not None:
            try:
                if capture.configuration() != self.collector.ui_settings:
                    return True
            except (ValueError, TypeError):
                return True
        return any(self.pages[key].changed for key in ("appearance", "preview") if key in self.pages)

    def apply(self):
        if not self.pending:
            return False
        capture = self.pages.get("capture")
        if capture is not None:
            settings = capture.configuration()
            if settings != self.collector.ui_settings:
                self.collector.ui_settings_store.save(settings)
                self.collector.ui_settings = settings
                self.collector.apply_ui_settings(settings)
                capture.base = settings
                capture.initial = capture.grid.value()
        preview = self.pages.get("preview")
        if preview is not None and preview.changed:
            preview.save()
            self.editor.canvas.set_render_acceleration(preview.saved_acceleration)
        appearance = self.pages.get("appearance")
        if appearance is not None:
            appearance.save()
        self.changed.emit()
        return True


class SettingsDialog(QtWidgets.QDialog):
    """One settings dialog with independent document, default and app transactions."""

    SCOPES = (("document", "当前文档"), ("defaults", "新建文档默认"), ("app", "应用偏好"))
    ACTIONS = {"document": "应用到当前文档", "defaults": "保存新建默认", "app": "保存应用偏好"}

    def __init__(self, editor, collector=None, parent=None, *, category=None, scope=None):
        super().__init__(parent or editor)
        from .editor.document_settings import LAYOUT_TITLES, LayoutSettings
        from .ui_behavior import protect_parameter_wheels

        protect_parameter_wheels(QtWidgets.QApplication.instance())
        self.editor = editor
        self.preferences = GlobalDefaultsStore.make_settings()
        self.setObjectName("unified_settings_dialog")
        self.setWindowTitle("设置 · InkStruct")
        self.setModal(True)
        self.setSizeGripEnabled(True)
        self.scope = None
        self.current = None
        self.confirmation = None
        self.categories = {
            "document": LAYOUT_TITLES,
            "defaults": LAYOUT_TITLES,
            "app": {key: ("采集显示" if key == "capture" else title)
                    for key, group, title, _ in CATEGORIES if group != "排版默认设置"
                    and (key != "capture" or collector is not None)},
        }
        self.selected = {name: next(iter(self.categories[name])) for name, _ in self.SCOPES}
        self.document = LayoutSettings(editor)
        self.defaults = LayoutSettings(editor, defaults=True)
        self.application = ApplicationPreferences(editor, collector, self.preferences)
        self.sections = {"document": self.document, "defaults": self.defaults, "app": self.application}
        for section in self.sections.values():
            section.changed.connect(self.update_actions)

        outer = QtWidgets.QVBoxLayout(self)
        self.views = QtWidgets.QStackedWidget()
        outer.addWidget(self.views)
        self.edit = QtWidgets.QWidget()
        self.views.addWidget(self.edit)
        column = QtWidgets.QVBoxLayout(self.edit)
        column.setContentsMargins(0, 0, 0, 0)
        self.scope_picker = QtWidgets.QTabBar()
        self.scope_picker.setAccessibleName("设置范围")
        self.scope_picker.setExpanding(False)
        for key, title in self.SCOPES:
            self.scope_picker.setTabData(self.scope_picker.addTab(title), key)
        column.addWidget(self.scope_picker)
        row = QtWidgets.QHBoxLayout()
        column.addLayout(row, 1)
        self.navigation = QtWidgets.QListWidget()
        self.navigation.setAccessibleName("设置分类")
        self.navigation.setFixedWidth(150)
        row.addWidget(self.navigation)
        content = QtWidgets.QVBoxLayout()
        row.addLayout(content, 1)
        self.scope_info = label("")
        self.scope_info.setProperty("inkRole", "status")
        content.addWidget(self.scope_info)
        self.heading = label("")
        self.heading.setProperty("inkRole", "title")
        content.addWidget(self.heading)
        self.stack = QtWidgets.QStackedWidget()
        for section in self.sections.values():
            self.stack.addWidget(section)
        content.addWidget(self.stack, 1)

        self.error = label("")
        self.error.hide()
        column.addWidget(self.error)
        self.buttons = QtWidgets.QWidget()
        actions = QtWidgets.QHBoxLayout(self.buttons)
        actions.setContentsMargins(0, 0, 0, 0)
        self.copy_button = QtWidgets.QPushButton("设为新建默认…")
        self.copy_button.clicked.connect(self.begin_copy)
        actions.addWidget(self.copy_button)
        self.reset = QtWidgets.QPushButton("恢复本分类初始值")
        self.reset.clicked.connect(self.reset_current)
        actions.addWidget(self.reset)
        actions.addStretch()
        self.close_button = QtWidgets.QPushButton("关闭")
        self.close_button.clicked.connect(self.reject)
        actions.addWidget(self.close_button)
        self.save_button = QtWidgets.QPushButton("")
        self.save_button.setProperty("inkRole", "primary")
        self.save_button.clicked.connect(self.apply)
        actions.addWidget(self.save_button)
        column.addWidget(self.buttons)
        for button in self.buttons.findChildren(QtWidgets.QPushButton):
            button.setAutoDefault(False)

        self.confirm_page = QtWidgets.QWidget()
        self.views.addWidget(self.confirm_page)
        confirmation = QtWidgets.QVBoxLayout(self.confirm_page)
        title = label("设为新建文档默认")
        title.setProperty("inkRole", "title")
        confirmation.addWidget(title)
        self.confirm_scope = label("")
        confirmation.addWidget(self.confirm_scope)
        self.diff = QtWidgets.QTreeWidget()
        self.diff.setHeaderLabels(["设置项", "现有默认", "新默认"])
        self.diff.setRootIsDecorated(False)
        self.diff.setAlternatingRowColors(True)
        self.diff.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.NoSelection)
        self.diff.header().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Stretch)
        confirmation.addWidget(self.diff, 1)
        self.confirm_error = label("")
        set_tone(self.confirm_error, "danger")
        self.confirm_error.hide()
        confirmation.addWidget(self.confirm_error)
        confirm_actions = QtWidgets.QHBoxLayout()
        confirm_actions.addStretch()
        self.back_button = QtWidgets.QPushButton("返回编辑")
        self.back_button.clicked.connect(self.cancel_copy)
        confirm_actions.addWidget(self.back_button)
        self.confirm_button = QtWidgets.QPushButton("保存为新建默认")
        self.confirm_button.setProperty("inkRole", "primary")
        self.confirm_button.clicked.connect(self.confirm_copy)
        confirm_actions.addWidget(self.confirm_button)
        confirmation.addLayout(confirm_actions)

        self.scope_picker.currentChanged.connect(self.scope_changed)
        self.navigation.currentItemChanged.connect(self.category_selected)
        self.finished.connect(lambda _: self.preferences.setValue("size", self.size()))
        self.finished.connect(lambda _: self.application.set_active(False))
        size = self.preferences.value("size", QtCore.QSize(960, 720))
        available = (parent or editor).screen().availableGeometry().size()
        width, height = available.width() - 40, available.height() - 64
        self.setMinimumSize(min(760, width), min(550, height))
        self.resize(min(max(self.minimumWidth(), size.width()), width),
                    min(max(self.minimumHeight(), size.height()), height))
        initial = scope or ("app" if category in self.categories["app"] else "document")
        self.select(category or self.selected[initial], scope=initial)

    @property
    def items(self):
        return self.categories[self.scope]

    @property
    def pages(self):
        return self.sections[self.scope].pages

    def select(self, key, *, scope=None):
        if scope is None:
            scope = "app" if key in self.categories["app"] else (
                "defaults" if self.scope == "defaults" else "document"
            )
        self.selected[scope] = key
        index = next(i for i, (name, _) in enumerate(self.SCOPES) if name == scope)
        with QtCore.QSignalBlocker(self.scope_picker):
            self.scope_picker.setCurrentIndex(index)
        if self.scope != scope:
            self.scope_changed(index)
        else:
            row = list(self.items).index(key)
            self.navigation.setCurrentRow(row)

    def scope_changed(self, index):
        self.scope = self.scope_picker.tabData(index)
        self.application.set_active(self.scope == "app")
        self.stack.setCurrentWidget(self.sections[self.scope])
        with QtCore.QSignalBlocker(self.navigation):
            self.navigation.clear()
            self.navigation.addItems(list(self.items.values()))
            self.navigation.setCurrentRow(list(self.items).index(self.selected[self.scope]))
        self.category_selected(self.navigation.currentItem())

    def category_selected(self, item, previous=None):
        if item is None:
            return
        self.current = list(self.items)[self.navigation.row(item)]
        self.selected[self.scope] = self.current
        self.heading.setText(self.items[self.current])
        name = self.editor.session_path.name if self.editor.session_path else "未命名文档"
        self.scope_info.setText({
            "document": f"当前文档 · {name}",
            "defaults": "新建文档默认 · 仅用于此后新建的文档",
            "app": "应用偏好 · 保存在本机",
        }[self.scope])
        self.sections[self.scope].select(self.current)
        self.error.hide()
        self.update_actions()

    def update_actions(self, *_):
        if self.scope is None:
            return
        section = self.sections[self.scope]
        if self.scope in {"document", "defaults"}:
            body = section.drafts.get("body")
            mode = body[1].mode.currentData() if body else section.draft_owner().mode
            for index, key in enumerate(self.items):
                hidden = mode == "plain-text" and key in {"math", "table", "image", "code"}
                self.navigation.item(index).setHidden(hidden)
            if self.navigation.currentItem() and self.navigation.currentItem().isHidden():
                self.navigation.setCurrentRow(list(self.items).index("body"))
                return
        about = self.scope == "app" and self.current == "about"
        self.reset.setVisible(self.scope == "app" and not about)
        self.copy_button.setVisible(self.scope == "document" and self.document.can_copy())
        self.save_button.setVisible(not about)
        self.save_button.setEnabled(bool(section.pending))
        self.save_button.setText(self.ACTIONS[self.scope])
        for index, (key, title) in enumerate(self.SCOPES):
            self.scope_picker.setTabText(index, title + (" ●" if self.sections[key].pending else ""))

    def report(self, message, *, error=False):
        self.error.setText(message)
        set_tone(self.error, "danger" if error else "success")
        self.error.show()

    def apply(self):
        section = self.sections[self.scope]
        try:
            if not section.apply():
                return True
            self.report({"document": "已应用到当前文档。按 Ctrl+S 保存项目。",
                         "defaults": "已保存新建文档默认。",
                         "app": "已保存应用偏好。"}[self.scope])
            return True
        except (ValueError, OSError, TypeError) as error:
            if key := getattr(section, "select_error", None):
                self.select(key, scope=self.scope)
            self.report(str(error), error=True)
            return False

    def accept(self):
        if self.sections[self.scope].pending and not self.apply():
            return
        if not any(section.pending for section in self.sections.values()):
            super().accept()

    def confirm_discard(self):
        names = [title for key, title in self.SCOPES if self.sections[key].pending]
        if not names:
            return True
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle("设置尚未保存")
        box.setText("以下范围有未保存的修改：" + "、".join(names))
        back = box.addButton("返回编辑", QtWidgets.QMessageBox.ButtonRole.RejectRole)
        discard = box.addButton("放弃修改并关闭", QtWidgets.QMessageBox.ButtonRole.DestructiveRole)
        box.setDefaultButton(back)
        box.setEscapeButton(back)
        box.exec()
        return box.clickedButton() == discard

    def reject(self):
        if self.confirmation is not None:
            self.cancel_copy()
        elif self.confirm_discard():
            super().reject()

    def closeEvent(self, event):
        if self.confirm_discard():
            super().reject()
            event.accept()
        else:
            event.ignore()

    def reset_current(self):
        page = self.pages[self.current]
        if hasattr(page, "reset_defaults"):
            page.reset_defaults()

    def begin_copy(self):
        try:
            key, rows, pending, save = self.document.prepare_default_copy()
            if not rows:
                self.report("本分类的值与新建默认一致。")
                return
            self.confirmation = key, save
            text = f"更新「{self.items[key]}」的新建默认，用于此后新建的文档。"
            if pending:
                text += " 文档修改仍待应用。"
            if key in self.defaults.pending:
                text += " 本分类尚未保存的默认修改将被替换。"
            self.confirm_scope.setText(text)
            self.confirm_error.hide()
            self.diff.clear()
            self.diff.addTopLevelItems([QtWidgets.QTreeWidgetItem(list(row)) for row in rows])
            self.views.setCurrentWidget(self.confirm_page)
            self.back_button.setFocus()
        except (OSError, ValueError, TypeError) as error:
            self.report(str(error), error=True)

    def cancel_copy(self):
        self.confirmation = None
        self.views.setCurrentWidget(self.edit)
        self.copy_button.setFocus()

    def confirm_copy(self):
        key, save = self.confirmation
        try:
            save()
        except (OSError, ValueError, TypeError) as error:
            self.confirm_error.setText(str(error))
            self.confirm_error.show()
            return
        self.defaults.store = GlobalDefaultsStore()
        self.defaults.reload((key,))
        self.cancel_copy()
        self.update_actions()
        self.report("已保存本分类的新建默认。"
                    + (" 文档修改仍待应用。" if key in self.document.pending else ""))


def layout_settings_page(owner, key, *, for_document=False, defaults=False):
    if key == "body":
        return BodyPage(owner)
    if key in {"table", "image"}:
        page = ElementPage(key, owner.document, owner.flow, scrollable=False)
        page.scope.hide()
        page.explanation.setText(
            "适用于当前文档。单个表格或图片的独立设置可在右侧元素属性中编辑。"
            if for_document and not defaults else "新建文档使用这些值。"
        )
        page.status.hide()
        return page
    if key == "math":
        from .editor.math_settings import MathSettingsDialog

        page = embed(MathSettingsDialog(
            owner.flow.math, resolver=owner.resolver, stroke_width=owner.style.stroke_width_mm,
            embedded=True, font_path=owner.run,
        ))
        page.reset_defaults = page.reset_category
        return page
    if key == "code":
        from .editor.code_settings import CodeSettingsDialog

        return embed(CodeSettingsDialog(owner.flow.code))
    raise ValueError(f"未知设置分类：{key}")


def open_settings(editor, collector=None, parent=None, *, category=None, scope=None):
    dialog = SettingsDialog(editor, collector, parent, category=category, scope=scope)
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
