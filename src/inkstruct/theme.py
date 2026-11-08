"""Application-only light appearance until all views support dark mode."""

from PySide6 import QtCore, QtGui


APP_STYLE = """
QWidget { font-family: "Microsoft YaHei UI", "PingFang SC", "Segoe UI", sans-serif; font-size: 14px; }
QLabel { background: transparent; }
QLabel[inkRole="title"] { font-size: 20px; font-weight: 600; color: #1f2937; }
QLabel#inspector_context { font-weight: 600; color: #1f2937; padding-bottom: 4px; }
QLabel#inspector_scope { color: #475569; padding-bottom: 8px; }
QPushButton, QToolButton {
    min-height: 26px; padding: 4px 10px; border: 1px solid #cbd5e1;
    border-radius: 5px; background: #ffffff; color: #1f2937;
}
QPushButton:hover, QToolButton:hover { border-color: #2563eb; background: #eff6ff; }
QPushButton:focus, QToolButton:focus { border-color: #2563eb; }
QPushButton:pressed, QToolButton:pressed { background: #dbeafe; }
QToolButton:checked { background: #dbeafe; border-color: #2563eb; color: #1d4ed8; }
QPushButton[inkRole="primary"], QToolButton[inkRole="primary"], QPushButton#primaryButton {
    background: #2563eb; border-color: #2563eb; color: #ffffff;
}
QPushButton[inkRole="primary"]:hover, QToolButton[inkRole="primary"]:hover,
QPushButton#primaryButton:hover { background: #1d4ed8; border-color: #1d4ed8; }
QPushButton:disabled, QToolButton:disabled, QPushButton[inkRole="primary"]:disabled,
QToolButton[inkRole="primary"]:disabled, QPushButton#primaryButton:disabled {
    background: #edf0f4; color: #7c8795; border-color: #dce3ec;
}
QToolButton#unified_settings_button { font-size: 22px; min-height: 0; padding: 2px; }
QLineEdit, QAbstractSpinBox, QComboBox {
    min-height: 24px; padding: 3px 6px; background: #ffffff;
    border: 1px solid #cbd5e1; border-radius: 4px; color: #1f2937;
}
QLineEdit:focus, QAbstractSpinBox:focus, QComboBox:focus { border-color: #2563eb; }
QLineEdit:disabled, QAbstractSpinBox:disabled, QComboBox:disabled { background: #f1f5f9; color: #7c8795; }
QTabWidget::pane { border: 1px solid #dce3ec; background: #ffffff; }
QTabBar::tab { padding: 7px 12px; background: #f1f5f9; border: 1px solid #dce3ec; color: #475569; }
QTabBar::tab:selected { background: #ffffff; color: #1d4ed8; border-bottom-color: #ffffff; }
QGroupBox { border: 1px solid #dce3ec; border-radius: 5px; margin-top: 12px; padding-top: 12px; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #334155; }
QListView::item, QTreeView::item { padding: 4px; }
QListView::item:selected, QTreeView::item:selected { background: #dbeafe; color: #1e3a8a; }
QMenu::item:selected { background: #dbeafe; color: #1e3a8a; }
QLabel#targetCharacter { font-size: 88px; font-weight: 600; color: #1f2937; }
QLabel#mutedLabel { color: #475569; }
QScrollBar:vertical { width: 15px; background: #f3f3f3; border-radius: 7px; margin: 0; }
QScrollBar:horizontal { height: 15px; background: #f3f3f3; border-radius: 7px; margin: 0; }
QScrollBar::handle { background: #858585; border: 3px solid #f3f3f3; border-radius: 7px; }
QScrollBar::handle:vertical { min-height: 28px; }
QScrollBar::handle:horizontal { min-width: 28px; }
QScrollBar::handle:hover { background: #626262; }
QScrollBar::handle:pressed { background: #484848; }
QScrollBar::handle:disabled { background: #b8b8b8; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; border: none; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
"""


def use_light_theme(application):
    from .ui_behavior import protect_parameter_wheels
    protect_parameter_wheels(application)
    # Fusion chooses control geometry, not the system color scheme. Request light
    # explicitly as well as setting every palette group, including disabled items.
    application.styleHints().setColorScheme(QtCore.Qt.ColorScheme.Light)
    if application.style().objectName().lower() != "fusion":
        application.setStyle("Fusion")
    palette = QtGui.QPalette(application.style().standardPalette())
    role = QtGui.QPalette.ColorRole
    colors = {
        role.Window: "#f6f8fa",
        role.WindowText: "#1f2937",
        role.Base: "#ffffff",
        role.AlternateBase: "#f1f5f9",
        role.Text: "#1f2937",
        role.Button: "#f1f5f9",
        role.ButtonText: "#1f2937",
        role.ToolTipBase: "#fffbe6",
        role.ToolTipText: "#1f2937",
        role.PlaceholderText: "#64748b",
        role.BrightText: "#ffffff",
        role.Highlight: "#2563eb",
        role.HighlightedText: "#ffffff",
        role.Link: "#1d4ed8",
        role.LinkVisited: "#6d28d9",
        role.Accent: "#2563eb",
        role.Light: "#ffffff",
        role.Midlight: "#e2e8f0",
        role.Mid: "#94a3b8",
        role.Dark: "#64748b",
        role.Shadow: "#334155",
    }
    for group in (
        QtGui.QPalette.ColorGroup.Active,
        QtGui.QPalette.ColorGroup.Inactive,
        QtGui.QPalette.ColorGroup.Disabled,
    ):
        for color_role, color in colors.items():
            palette.setColor(group, color_role, QtGui.QColor(color))
    disabled = QtGui.QPalette.ColorGroup.Disabled
    for color_role in (role.WindowText, role.Text, role.ButtonText, role.PlaceholderText):
        palette.setColor(disabled, color_role, QtGui.QColor("#7c8795"))
    palette.setColor(disabled, role.Base, QtGui.QColor("#f1f5f9"))
    palette.setColor(disabled, role.Button, QtGui.QColor("#edf0f4"))
    palette.setColor(disabled, role.Highlight, QtGui.QColor("#dce3ec"))
    palette.setColor(disabled, role.HighlightedText, QtGui.QColor("#64748b"))
    application.setPalette(palette)
    application.setStyleSheet(APP_STYLE)
