"""Writing-first workspace: document panes, export and optional properties."""

import sys

from PySide6 import QtCore, QtGui, QtWidgets

def organize_workspace(w):
    old = w.takeCentralWidget()
    buttons = {b.text(): b for b in old.findChildren(QtWidgets.QPushButton)}
    root = QtWidgets.QWidget()
    root.setObjectName("writing_workspace")
    layout = QtWidgets.QVBoxLayout(root)
    layout.setContentsMargins(12, 8, 12, 8)
    layout.setSpacing(8)
    toolbar = QtWidgets.QHBoxLayout()
    layout.addLayout(toolbar)

    def action(menu, title, callback, shortcut=None):
        item = menu.addAction(title)
        item.setMenuRole(QtGui.QAction.MenuRole.NoRole)
        item.triggered.connect(lambda checked=False: callback())
        if shortcut:
            item.setShortcut(shortcut)
        return item

    def tool(title, callback=None):
        button = QtWidgets.QToolButton()
        button.setText(title)
        button.setMinimumHeight(32)
        if callback:
            button.clicked.connect(lambda checked=False: callback())
        toolbar.addWidget(button)
        return button

    file_menu = w.menuBar().addMenu("文件")
    action(file_menu, "新建文档", w.new_document, QtGui.QKeySequence.StandardKey.New)
    action(file_menu, "打开项目…", w.open_project, QtGui.QKeySequence.StandardKey.Open)
    action(file_menu, "导入 Markdown / 文本…", w.open_text)
    save = action(file_menu, "保存项目", w.request_project_save, QtGui.QKeySequence.StandardKey.Save)
    save.setAutoRepeat(False)
    save_as = action(file_menu, "另存项目…", lambda: w.request_project_save(save_as=True),
                     QtGui.QKeySequence.StandardKey.SaveAs)
    save_as.setAutoRepeat(False)
    action(file_menu, "保存 Markdown / 文本…", w.save_text)
    file_menu.addSeparator()
    action(file_menu, "打开恢复副本…", w.open_recovery)
    advanced = file_menu.addMenu("高级资源（仅当前文档）")
    action(advanced, "选择生成字形目录…", w.choose_run)
    action(advanced, "刷新当前外部资源", w.refresh_assets)

    # Native Edit actions route to the focused text control. Source input also has
    # an explicit paste button, independent of platform menu/shortcut dispatch.
    def edit(method):
        target = QtWidgets.QApplication.focusWidget()
        if not isinstance(
            target, (QtWidgets.QLineEdit, QtWidgets.QTextEdit, QtWidgets.QPlainTextEdit)
        ):
            target = w.editor
        if target is w.editor:
            w.workspace_views.focus_source()
        target.setFocus(QtCore.Qt.FocusReason.ShortcutFocusReason)
        getattr(target, method)()

    edit_menu = w.menuBar().addMenu("编辑")
    for title, method, shortcut in (
        ("撤销", "undo", QtGui.QKeySequence.StandardKey.Undo),
        ("重做", "redo", QtGui.QKeySequence.StandardKey.Redo),
        ("剪切", "cut", QtGui.QKeySequence.StandardKey.Cut),
        ("复制", "copy", QtGui.QKeySequence.StandardKey.Copy),
        ("粘贴", "paste", QtGui.QKeySequence.StandardKey.Paste),
        ("全选", "selectAll", QtGui.QKeySequence.StandardKey.SelectAll),
    ):
        action(edit_menu, title, lambda m=method: edit(m), shortcut)
    action(edit_menu, "聚焦 Markdown 源码", lambda: w.workspace_views.focus_source(), "Ctrl+1")
    toolbar.addStretch()

    # Keep backing controls owned but hidden. The unified dialog edits a draft,
    # while existing load/save paths continue using these authoritative controls.
    storage = QtWidgets.QWidget(w)
    storage.setObjectName('settings_backing_controls')
    controls = [w.mode_picker, w.dialect_picker, w.em, w.line_height, w.stroke,
                *w.flow_controls.values(), w.run_label, w.template_settings_button,
                w.math_settings_button, w.code_settings_button, w.table_settings_button,
                w.image_settings_button, w.footnote_settings_button]
    controls.extend(buttons[title] for title in ('标题字号…', '选择字形目录…', '刷新字形', '载入全部字'))
    controls.extend((w.optimize, w.page_export, w.filter, w.glyph_list, w.summary, w.inspector,
                     w.selection_label, w.note, w.show_marks, w.next_button, *w.rating_buttons,
                     buttons["撤销标记"], buttons["重做标记"]))
    for control in controls:
        control.setParent(storage)
    w.show_marks.setChecked(False)
    storage.hide()
    w.settings_storage = storage
    dock = QtWidgets.QDockWidget("问题与定位", w)
    dock.setObjectName("document_problems_dock")
    dock.setAllowedAreas(
        QtCore.Qt.DockWidgetArea.LeftDockWidgetArea | QtCore.Qt.DockWidgetArea.RightDockWidgetArea
    )
    tabs = QtWidgets.QTabWidget()
    tabs.setMinimumWidth(300)
    dock.setWidget(tabs)
    w.addDockWidget(QtCore.Qt.DockWidgetArea.RightDockWidgetArea, dock)
    w.problems_dock = dock

    def tab(title):
        content = QtWidgets.QWidget()
        column = QtWidgets.QVBoxLayout(content)
        column.setSpacing(12)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        scroll.setWidget(content)
        tabs.addTab(scroll, title)
        return column

    diagnostics = tab("问题")
    from .problems import ProblemsPanel
    w.problems_panel = ProblemsPanel(w)
    diagnostics.addWidget(w.problems_panel,1)
    w.diagnostic_picker.setParent(storage)
    navigation = tab('正文定位')
    navigation.addWidget(w.block_picker)
    navigation.addStretch()

    def reveal(index):
        tabs.setCurrentIndex(index)
        dock.show()
        dock.raise_()

    from ..settings_dialog import gear_button, open_settings
    w.settings_button = gear_button(w, lambda: open_settings(w))
    w.settings_shortcut = w.settings_button.settings_shortcut
    w.menuBar().setCornerWidget(w.settings_button, QtCore.Qt.Corner.TopRightCorner)
    action(file_menu, '载入当前字库全部字', w.load_all)
    w.export_button = tool("导出…", w.export_document)
    w.export_button.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    w.export_button.setObjectName("document_export")
    w.export_button.setEnabled(False)
    split = QtWidgets.QSplitter()
    split.setObjectName("document_splitter")
    split.setChildrenCollapsible(False)
    layout.addWidget(split, 1)
    left = QtWidgets.QWidget()
    left_layout = QtWidgets.QVBoxLayout(left)
    left_layout.setContentsMargins(0, 0, 0, 0)
    source_header = QtWidgets.QHBoxLayout()
    source_header.addWidget(QtWidgets.QLabel("Markdown 源码"))
    source_header.addStretch()
    paste = QtWidgets.QToolButton()
    paste.setText("粘贴")
    paste.setObjectName("paste_source")
    paste.setToolTip("将剪贴板文字粘贴到光标处；可撤销")

    def paste_source():
        w.workspace_views.focus_source()
        w.editor.paste()

    paste.clicked.connect(paste_source)
    source_header.addWidget(paste)
    left_layout.addLayout(source_header)
    left_layout.addWidget(w.editor, 1)
    w.editor.setReadOnly(False)
    w.editor.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
    w.editor.setMinimumSize(220, 180)
    w.editor.setPlaceholderText(
        "在这里输入或粘贴 Markdown…\n\n例如：12.34\n\n右侧会实时显示手写页面。"
    )
    w.editor.setProperty("inkRole", "sourceEditor")
    split.addWidget(left)
    right = QtWidgets.QWidget()
    right_layout = QtWidgets.QVBoxLayout(right)
    right_layout.setContentsMargins(0, 0, 0, 0)
    nav = QtWidgets.QHBoxLayout()
    nav.addWidget(QtWidgets.QLabel("页面预览 · 连续滚动"))
    w.page_picker.setToolTip("向上：上一页；向下：下一页。输入页码可直接跳转，滚动时页码自动更新")
    nav.addStretch()
    nav.addWidget(w.page_picker)
    nav.addWidget(w.zoom)
    right_layout.addLayout(nav)
    right_layout.addWidget(w.scroll, 1)
    split.addWidget(right)
    split.setSizes([480, 680])
    split.setStretchFactor(0, 4)
    split.setStretchFactor(1, 6)
    from .workspace_views import WorkspaceViews
    w.scroll.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
    w.workspace_views = WorkspaceViews(w, split, left, right)
    toolbar.insertWidget(0, w.workspace_views.widget)

    footer = QtWidgets.QHBoxLayout()
    footer.addWidget(w.status, 1)
    problems = QtWidgets.QToolButton()
    problems.setText("查看问题")
    problems.setAccessibleName("查看排版问题")
    w.problems_button = problems
    problems.clicked.connect(lambda: reveal(0))
    footer.addWidget(problems)
    layout.addLayout(footer)
    view_menu = w.menuBar().addMenu("视图")
    view_menu.addAction(dock.toggleViewAction())
    from .element_inspector import ElementInspector
    from .glyph_inspector import GlyphInspector
    properties = QtWidgets.QDockWidget('元素属性', w)
    properties.setObjectName('document_element_properties_dock')
    properties.setAllowedAreas(QtCore.Qt.DockWidgetArea.RightDockWidgetArea)
    properties.setMinimumWidth(280)
    w.element_inspector = ElementInspector(w)
    properties_scroll = QtWidgets.QScrollArea()
    properties_scroll.setWidgetResizable(True)
    properties_scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
    properties_scroll.setWidget(w.element_inspector)
    w.properties_tabs = QtWidgets.QTabWidget()
    w.properties_tabs.addTab(properties_scroll, "表格与图片")
    w.glyph_inspector = GlyphInspector(w)
    glyph_scroll = QtWidgets.QScrollArea()
    glyph_scroll.setWidgetResizable(True)
    glyph_scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
    glyph_scroll.setWidget(w.glyph_inspector)
    w.properties_tabs.addTab(glyph_scroll, "字符校正")
    from .template_content import TemplateContentPanel
    w.template_content_panel=TemplateContentPanel(w)
    resources_scroll = QtWidgets.QScrollArea()
    resources_scroll.setWidgetResizable(True)
    resources_scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
    resources_scroll.setWidget(w.template_content_panel)
    w.properties_tabs.addTab(resources_scroll,"文档资源")
    properties.setWidget(w.properties_tabs)
    w.element_properties_dock = properties
    w.addDockWidget(QtCore.Qt.DockWidgetArea.RightDockWidgetArea, properties)
    w.tabifyDockWidget(dock, properties)
    if sys.platform == "win32":
        from .machine_panel import MachinePanel

        machine = QtWidgets.QDockWidget("写字机", w)
        machine.setObjectName("document_machine_dock")
        machine.setAllowedAreas(QtCore.Qt.DockWidgetArea.RightDockWidgetArea)
        w.machine_panel = MachinePanel(machine)
        w.machine_dock = machine
        machine.setWidget(w.machine_panel)
        w.addDockWidget(QtCore.Qt.DockWidgetArea.RightDockWidgetArea, machine)
        w.tabifyDockWidget(properties, machine)
        w.setTabPosition(QtCore.Qt.DockWidgetArea.RightDockWidgetArea, QtWidgets.QTabWidget.TabPosition.North)
        w.machine_panel.page_selected.connect(lambda index: w.page_picker.setValue(index + 1))
        machine_status = QtWidgets.QLabel()
        machine_status.setWordWrap(True)
        machine_status.hide()
        footer.insertWidget(1, machine_status, 1)

        def show_machine_status(text):
            machine_status.setText(text)
            machine_status.setVisible(bool(text))

        w.machine_panel.status_changed.connect(show_machine_status)
        view_menu.addAction(machine.toggleViewAction())
    properties.raise_()
    w.resizeDocks([properties], [330], QtCore.Qt.Orientation.Horizontal)
    view_menu.addAction(properties.toggleViewAction())
    w.setCentralWidget(root)
    if sys.platform != "win32":
        dock.hide()
    old.deleteLater()
    # Schedule after initial show so keyboard input works immediately on launch.
    QtCore.QTimer.singleShot(0, w.workspace_views.focus_current)
