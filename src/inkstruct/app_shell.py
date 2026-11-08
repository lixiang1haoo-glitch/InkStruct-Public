"""Integrated Widgets shell; page controllers and resource identities stay owned by each module."""

from itertools import pairwise

from PySide6 import QtCore, QtGui, QtSvg, QtWidgets

# Small, local line icons share a grid and stroke weight; labels remain authoritative.
_PATHS = {
    'capture': '<path d="m14 4 6 6M4 20l4-1 12-12a2.1 2.1 0 0 0-3-3L5 16z"/>',
    'generate': '<path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5zM20 2v4M18 4h4"/>',
    'layout': '<rect x="4" y="3" width="16" height="18" rx="2"/><path d="M8 7h8M8 11h3v6H8zM14 11h2M14 14h2M14 17h2"/>',
    'library': '<path d="M3 4h7v16H3zM10 4h6v16h-6zM17 5l3-1 3 15-3 1zM6 8h1M12 8h2M6 16h1M12 16h2"/>',
    'templates': '<rect x="5" y="3" width="14" height="18" rx="2"/><path d="M8 7h8v3H8zM8 13h3v5H8zM14 13h2m-2 4h2"/>',
    'settings': '<path d="m9 3-.5 3-2 1.2L4 6l-2 3 2.3 2v2L2 15l2 3 2.5-1.2 2 1.2.5 3h4l.5-3 2-1.2L18 18l2-3-2.3-2v-2L20 9l-2-3-2.5 1.2-2-1.2-.5-3z"/><circle cx="11" cy="12" r="3"/>',
    'import': '<path d="M4 8V4h16v16H4v-4M2 12h11m-4-4 4 4-4 4"/>',
    'export': '<path d="M9 4H4v16h16v-5M12 3h9v9M21 3l-11 11"/>',
    'check': '<path d="M5 12l4 4L19 6"/>',
    'play': '<path d="m8 4 12 8-12 8z"/>',
    'undo': '<path d="M8 4 3 9l5 5M3 9h10a7 7 0 0 1 0 14" transform="translate(0 -2)"/>',
    'paste': '<path d="M8 5H5v16h14V5h-3M8 3h8v4H8zM8 12h8M8 16h6"/>',
}


def line_icon(name, color='#475569'):
    """Render bundled vector paths at multiple pixel ratios without platform emoji."""
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
           f'fill="none" stroke="{color}" stroke-width="1.7" '
           'stroke-linecap="round" stroke-linejoin="round">' + _PATHS[name] + '</svg>')
    renderer = QtSvg.QSvgRenderer(svg.encode())
    icon = QtGui.QIcon()
    for ratio in (1, 2, 3):
        pixmap = QtGui.QPixmap(20 * ratio, 20 * ratio)
        pixmap.fill(QtCore.Qt.GlobalColor.transparent)
        painter = QtGui.QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        pixmap.setDevicePixelRatio(ratio)
        icon.addPixmap(pixmap)
    return icon


SHELL_STYLE = """
QWidget#inkstruct_shell { background: #ffffff; }
QFrame#app_navigation { background: #f1f4f8; border-right: 1px solid #e2e8f0; }
QToolButton[inkRole="navigation"] { text-align: left; padding: 8px 12px; min-height: 26px; border: 1px solid transparent; background: transparent; color: #475569; }
QToolButton[inkRole="navigation"]:hover { background: #e8edf5; }
QToolButton[inkRole="navigation"]:checked { background: #dbeafe; border-color: #bfdbfe; color: #1d4ed8; font-weight: 600; }
QToolButton[inkRole="navigation"]:focus { border-color: #2563eb; }
QToolButton#unified_settings_button { font-size: 14px; padding: 8px 12px; min-height: 26px; }
QWidget#inkstruct_shell QTabWidget::pane { border: none; background: #ffffff; }
QWidget#inkstruct_shell QTabBar::tab { background: transparent; border: none; border-bottom: 2px solid transparent; padding: 8px 14px; color: #64748b; }
QWidget#inkstruct_shell QTabBar::tab:selected { color: #1d4ed8; border-bottom: 2px solid #2563eb; }
QWidget#capture_workspace, QWidget#generation_workspace, QWidget#writing_workspace { background: #ffffff; }
QListWidget#template_library_list { background: #f1f4f8; border: 1px solid #e2e8f0; padding: 8px; }
QLabel#template_selected_summary { color: #334155; font-size: 16px; font-weight: 600; }
QPlainTextEdit#template_resource_info { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 4px; padding: 6px; }
QWidget#capture_writer_panel { background: #f1f4f8; border: 1px solid #e2e8f0; border-radius: 5px; }
QWidget#capture_writer_panel QLabel { border: none; background: transparent; }
QLabel[inkRole="hint"] { color: #64748b; font-size: 12px; }
QGroupBox[inkRole="workflowSection"] { background: #ffffff; border: 1px solid #e2e8f0; border-radius: 5px; margin-top: 12px; padding: 16px 10px 10px; }
QGroupBox[inkRole="workflowSection"]::title { color: #334155; font-weight: 600; }
QPlainTextEdit#generation_log { border: 1px solid #e2e8f0; background: #f8fafc; border-radius: 4px; }
QMainWindow#layout_workspace::separator { background: #e2e8f0; width: 1px; height: 1px; }
QMainWindow#layout_workspace QDockWidget { border: none; }
QMainWindow#layout_workspace QDockWidget::title { background: #f1f4f8; padding: 8px; color: #334155; }
QStatusBar { border-top: 1px solid #e2e8f0; color: #64748b; font-size: 12px; }
"""


def install_shell(window, about):
    """Use existing module indexes and widgets, with persistent external navigation."""
    shell = QtWidgets.QWidget()
    shell.setObjectName('inkstruct_shell')
    shell.setStyleSheet(SHELL_STYLE)
    body = QtWidgets.QHBoxLayout(shell)
    body.setContentsMargins(0, 0, 0, 0)
    body.setSpacing(0)
    sidebar = QtWidgets.QFrame()
    sidebar.setObjectName('app_navigation')
    sidebar.setFixedWidth(124)
    navigation = QtWidgets.QVBoxLayout(sidebar)
    navigation.setContentsMargins(10, 16, 10, 16)
    navigation.setSpacing(6)
    group = QtWidgets.QButtonGroup(shell)
    group.setExclusive(True)
    window.navigation_buttons = {}
    for index, title, key, shortcut in (
        (0, '采集', 'capture', 'Alt+1'), (1, '生成', 'generate', 'Alt+2'),
        (3, '排版', 'layout', 'Alt+3'), (2, '字体库', 'library', 'Alt+4'),
        (4, '模板库', 'templates', 'Alt+5'),
    ):
        if index == 2:
            navigation.addStretch(1)
            line = QtWidgets.QFrame()
            line.setFrameShape(QtWidgets.QFrame.Shape.HLine)
            navigation.addWidget(line)
        item = QtWidgets.QToolButton()
        item.setObjectName('navigate_' + key)
        item.setProperty('inkRole', 'navigation')
        item.setText(title)
        item.setIcon(line_icon(key))
        item.setIconSize(QtCore.QSize(20, 20))
        item.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        item.setCheckable(True)
        item.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed)
        item.setAccessibleName(title)
        item.setToolTip(title + f' ({shortcut})')
        group.addButton(item, index)
        window.navigation_buttons[index] = item
        navigation.addWidget(item)
        key_action = QtGui.QShortcut(QtGui.QKeySequence(shortcut), shell)
        key_action.activated.connect(item.click)
    button = window.settings_button
    button.setText('设置')
    button.setProperty('inkRole', 'navigation')
    button.setIcon(line_icon('settings'))
    button.setIconSize(QtCore.QSize(20, 20))
    button.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    button.setMinimumSize(0, 0)
    button.setMaximumSize(16777215, 16777215)
    button.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed)
    navigation.addWidget(button)
    # The native title bar already displays the app name/version. Keep About
    # reachable after retiring the duplicate brand button, without another row.
    about.setShortcut(QtGui.QKeySequence('F1'))
    window.addAction(about)
    sidebar.addAction(about)
    sidebar.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.ActionsContextMenu)
    button.setToolTip('设置 (Ctrl+,) · 侧栏右键查看关于 InkStruct (F1)')
    group.idClicked.connect(window.tabs.setCurrentIndex)
    window.tabs.currentChanged.connect(lambda index: window.navigation_buttons[index].setChecked(True))
    window.navigation_buttons[window.tabs.currentIndex()].setChecked(True)
    # Keep the tab widget as the module owner and API; only its obsolete top bar is hidden.
    window.tabs.tabBar().hide()
    body.addWidget(sidebar)
    body.addWidget(window.tabs, 1)
    window.setCentralWidget(shell)
    window.menuBar().hide()
    window.navigation = group
    window.shell_sidebar = sidebar
    order = [*window.navigation_buttons.values(), button]
    for first, second in pairwise(order):
        QtWidgets.QWidget.setTabOrder(first, second)


def style_module_pages(window):
    """Presentation only: retain controls, signals, canvas coordinates, and page ownership."""
    collector = window.collector
    root = QtWidgets.QWidget()
    root.setObjectName('capture_workspace')
    column = QtWidgets.QVBoxLayout(root)
    column.setContentsMargins(16, 12, 16, 12)
    column.setSpacing(10)
    title = QtWidgets.QLabel('采集样本')
    title.setProperty('inkRole', 'title')
    column.addWidget(title)
    column.addWidget(collector.takeCentralWidget(), 1)
    collector.setCentralWidget(root)
    def capture_page_size(index):
        # QStackedLayout otherwise takes the tallest hidden page's minimum height.
        # The active page keeps its full minimum; its existing outer scroll handles overflow.
        for number in range(collector.tabs.count()):
            page = collector.tabs.widget(number)
            policy = page.sizePolicy()
            policy.setVerticalPolicy(QtWidgets.QSizePolicy.Policy.Preferred if number == index
                                     else QtWidgets.QSizePolicy.Policy.Ignored)
            page.setSizePolicy(policy)
        collector.tabs.updateGeometry()
        collector.updateGeometry()
    collector.tabs.currentChanged.connect(capture_page_size)
    capture_page_size(collector.tabs.currentIndex())
    for widget in (collector.single_widget, collector.symbol_widget):
        for control, name in ((widget.import_button, 'import'), (widget.save_button, 'check'),
                              (widget.undo_button, 'undo')):
            control.setIcon(line_icon(name, '#ffffff' if control is widget.save_button else '#475569'))
        widget.task_help.setProperty('inkRole', 'hint')
    workflow = window.generator.centralWidget()
    workflow.setObjectName('generation_workspace')
    workflow.layout().setContentsMargins(20, 16, 20, 16)
    workflow.layout().setSpacing(12)
    for section in workflow.findChildren(QtWidgets.QGroupBox):
        section.setProperty('inkRole', 'workflowSection')
    for control, name in ((workflow.generate_button, 'play'), (workflow.publish_button, 'library')):
        control.setIcon(line_icon(name, '#ffffff' if control.property('inkRole') == 'primary' else '#475569'))
    workflow.target_summary.setProperty('inkRole', 'hint')
    workflow.candidate_hint.setProperty('inkRole', 'hint')
    workflow.log.setObjectName('generation_log')
    editor = window.editor
    editor.setObjectName('layout_workspace')
    editor.machine_export.setIcon(line_icon('export', '#ffffff'))
    editor.machine_export.setProperty('inkRole', 'primary')
    paste = editor.findChild(QtWidgets.QToolButton, 'paste_source')
    paste.setIcon(line_icon('paste'))
    paste.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    # This is the existing toolbar; no extra row, document action, or layout state.
    title = QtWidgets.QLabel('排版')
    title.setProperty('inkRole', 'title')
    editor.centralWidget().layout().itemAt(0).layout().insertWidget(0, title)
    templates = window.template_library
    templates.summary.setObjectName('template_selected_summary')
    templates.info.setObjectName('template_resource_info')
