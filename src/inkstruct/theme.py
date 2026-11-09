"""Semantic palette and component styling for the integrated desktop."""

import sys
from pathlib import Path
from string import Template

from PySide6 import QtCore, QtGui, QtWidgets


THEME_KEY = "appearance_theme_v1"
THEME_MODES = {
    "system": QtCore.Qt.ColorScheme.Unknown,
    "light": QtCore.Qt.ColorScheme.Light,
    "dark": QtCore.Qt.ColorScheme.Dark,
}


def theme_preference(settings):
    mode = settings.value(THEME_KEY, "system", str)
    return mode if mode in THEME_MODES else "system"


COLORS = {
    'text_primary': '#1f2937',
    'text_secondary': '#475569',
    'text_muted': '#64748b',
    'text_heading': '#334155',
    'text_disabled': '#64748b',
    'surface': '#ffffff',
    'canvas': '#f6f8fa',
    'surface_subtle': '#f8fafc',
    'surface_secondary': '#f1f5f9',
    'navigation_surface': '#f1f4f8',
    'navigation_hover': '#e8edf5',
    'surface_disabled': '#edf0f4',
    'line': '#cbd5e1',
    'line_subtle': '#dce3ec',
    'divider': '#e2e8f0',
    'brand': '#2563eb',
    'brand_hover': '#1d4ed8',
    'brand_pressed': '#163fa0',
    'brand_subtle': '#eff6ff',
    'selection': '#dbeafe',
    'selection_border': '#bfdbfe',
    'selection_text': '#1e3a8a',
    'focus': '#0f3872',
    'danger': '#b42318',
    'warning': '#8a5107',
    'success': '#18633d',
    'link_visited': '#6d28d9',
    'tooltip_surface': '#fffbe6',
    'mid': '#94a3b8',
    'scroll_track': '#f3f3f3',
    'scroll_thumb': '#858585',
    'scroll_hover': '#626262',
    'scroll_pressed': '#484848',
    'scroll_disabled': '#b8b8b8',
}

_STYLE = Template("""
QWidget { font-family: "Microsoft YaHei UI", "PingFang SC", "Segoe UI", sans-serif; font-size: 14px; }
QLabel { background: transparent; }
QLabel[inkRole="title"] { font-size: 20px; font-weight: 600; color: $text_primary; }
QLabel#inspector_context { font-weight: 600; color: $text_primary; padding-bottom: 4px; }
QLabel#inspector_scope { color: $text_secondary; padding-bottom: 8px; }
QPushButton, QToolButton {
    min-height: 26px; padding: 4px 10px; border: 1px solid $line;
    border-radius: 5px; background: $surface; color: $text_primary;
}
QPushButton:hover, QToolButton:hover { border-color: $brand; background: $brand_subtle; }
QPushButton:pressed, QToolButton:pressed { background: $selection; }
QToolButton:checked { background: $selection; border-color: $brand; color: $brand_hover; }
QPushButton[inkRole="primary"], QToolButton[inkRole="primary"], QPushButton#primaryButton {
    background: $brand; border-color: $brand; color: $surface;
}
QPushButton[inkRole="primary"]:hover, QToolButton[inkRole="primary"]:hover,
QPushButton#primaryButton:hover { background: $brand_hover; border-color: $brand_hover; }
QPushButton:disabled, QToolButton:disabled, QPushButton[inkRole="primary"]:disabled,
QToolButton[inkRole="primary"]:disabled, QPushButton#primaryButton:disabled {
    background: $surface_disabled; color: $text_disabled; border-color: $line_subtle;
}
QToolButton#unified_settings_button { font-size: 22px; min-height: 0; padding: 2px; }
QLineEdit, QAbstractSpinBox, QComboBox {
    min-height: 24px; padding: 3px 6px; background: $surface;
    border: 1px solid $line; border-radius: 4px; color: $text_primary;
}
QLineEdit:disabled, QAbstractSpinBox:disabled, QComboBox:disabled { background: $surface_secondary; color: $text_disabled; }
QTabWidget::pane { border: 1px solid $line_subtle; background: $surface; }
QTabBar::tab { padding: 7px 12px; background: $surface_secondary; border: 1px solid $line_subtle; color: $text_secondary; }
QTabBar::tab:selected { background: $surface; color: $brand_hover; border-bottom-color: $surface; }
QGroupBox { border: 1px solid $line_subtle; border-radius: 5px; margin-top: 12px; padding-top: 12px; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: $text_heading; }
QListView::item, QTreeView::item { padding: 4px; }
QListView::item:selected, QTreeView::item:selected { background: $selection; color: $selection_text; }
QMenu::item:selected { background: $selection; color: $selection_text; }
QLabel#targetCharacter { font-size: 88px; font-weight: 600; color: $text_primary; }
QLabel#mutedLabel { color: $text_secondary; }
QScrollBar:vertical { width: 15px; background: $scroll_track; border-radius: 7px; margin: 0; }
QScrollBar:horizontal { height: 15px; background: $scroll_track; border-radius: 7px; margin: 0; }
QScrollBar::handle { background: $scroll_thumb; border: 3px solid $scroll_track; border-radius: 7px; }
QScrollBar::handle:vertical { min-height: 28px; }
QScrollBar::handle:horizontal { min-width: 28px; }
QScrollBar::handle:hover { background: $scroll_hover; }
QScrollBar::handle:pressed { background: $scroll_pressed; }
QScrollBar::handle:disabled { background: $scroll_disabled; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; border: none; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

QWidget#inkstruct_shell { background: $surface; }
QFrame#app_navigation { background: $navigation_surface; border-right: 1px solid $divider; }
QToolButton[inkRole="navigation"] { text-align: left; padding: 8px 12px; min-height: 26px; border: 1px solid transparent; background: transparent; color: $text_secondary; }
QToolButton[inkRole="navigation"]:hover { background: $navigation_hover; }
QToolButton[inkRole="navigation"]:checked { background: $selection; border-color: $selection_border; color: $brand_hover; font-weight: 600; }
QToolButton#unified_settings_button { font-size: 14px; padding: 8px 12px; min-height: 26px; }
QWidget#inkstruct_shell QTabWidget::pane { border: none; background: $surface; }
QWidget#inkstruct_shell QTabBar::tab { background: transparent; border: none; border-bottom: 2px solid transparent; padding: 8px 14px; color: $text_disabled; }
QWidget#inkstruct_shell QTabBar::tab:selected { color: $brand_hover; border-bottom: 2px solid $brand; }
QWidget#capture_workspace, QWidget#generation_workspace, QWidget#writing_workspace { background: $surface; }
QListWidget#template_library_list { background: $navigation_surface; border: 1px solid $divider; padding: 8px; }
QLabel#template_selected_summary { color: $text_heading; font-size: 16px; font-weight: 600; }
QPlainTextEdit#template_resource_info { background: $surface_subtle; border: 1px solid $divider; border-radius: 4px; padding: 6px; }
QWidget#capture_writer_panel { background: $navigation_surface; border: 1px solid $divider; border-radius: 5px; }
QWidget#capture_writer_panel QLabel { border: none; background: transparent; }
QLabel[inkRole="hint"] { color: $text_disabled; font-size: 12px; }
QGroupBox[inkRole="workflowSection"] { background: $surface; border: 1px solid $divider; border-radius: 5px; margin-top: 12px; padding: 16px 10px 10px; }
QGroupBox[inkRole="workflowSection"]::title { color: $text_heading; font-weight: 600; }
QPlainTextEdit#generation_log { border: 1px solid $divider; background: $surface_subtle; border-radius: 4px; }
QPlainTextEdit[inkRole="sourceEditor"] { font-size: 16px; padding: 12px; border: 1px solid $line; border-radius: 5px; }
QPlainTextEdit[inkRole="sourceEditor"]:focus { border-color: $focus; }
QMainWindow#layout_workspace::separator { background: $divider; width: 1px; height: 1px; }
QMainWindow#layout_workspace QDockWidget { border: none; }
QMainWindow#layout_workspace QDockWidget::title { background: $navigation_surface; padding: 8px; color: $text_heading; }
QStatusBar { border-top: 1px solid $divider; color: $text_disabled; font-size: 12px; }

/* Use a separate focus color so the primary fill never hides keyboard focus. */
QPushButton:focus, QToolButton:focus, QLineEdit:focus, QAbstractSpinBox:focus, QComboBox:focus,
QTreeView:focus, QListView:focus, QPlainTextEdit:focus, QToolButton[inkRole="navigation"]:focus {
    border: 1px solid $focus;
}
QPushButton[inkRole="primary"]:focus, QToolButton[inkRole="primary"]:focus, QPushButton#primaryButton:focus {
    border: 2px solid $focus; padding: 3px 9px;
}
QPushButton[inkRole="primary"]:pressed, QToolButton[inkRole="primary"]:pressed, QPushButton#primaryButton:pressed {
    background: $brand_pressed; border-color: $focus;
}
QLineEdit:read-only { background: $surface_secondary; }
QLineEdit[inkInvalid="true"], QAbstractSpinBox[inkInvalid="true"] { border-color: $danger; }
QLabel[inkTone="warning"] { color: $warning; }
QLabel[inkTone="danger"] { color: $danger; }
QLabel[inkTone="success"] { color: $success; }
QLabel[inkRole="status"] { padding: 4px 0; }
QLabel[inkRole="sectionTitle"] { color: $text_heading; font-weight: 600; }
QWidget[inkRole="previewSurface"] { background: $navigation_surface; color: $text_heading; }
QCheckBox::indicator:unchecked { background: transparent; border: 1px solid $mid; border-radius: 2px; }
QAbstractSpinBox[buttonSymbols="UpDownArrows"] { padding-right: 25px; }
QAbstractSpinBox[buttonSymbols="UpDownArrows"]::up-button,
QAbstractSpinBox[buttonSymbols="UpDownArrows"]::down-button {
    subcontrol-origin: border; width: 21px; margin: 1px; border-left: 1px solid $line_subtle;
}
QAbstractSpinBox[buttonSymbols="UpDownArrows"]::up-button { subcontrol-position: top right; }
QAbstractSpinBox[buttonSymbols="UpDownArrows"]::down-button { subcontrol-position: bottom right; }
QAbstractSpinBox[buttonSymbols="UpDownArrows"]::up-button:hover,
QAbstractSpinBox[buttonSymbols="UpDownArrows"]::down-button:hover { background: $brand_subtle; }
QAbstractSpinBox[buttonSymbols="UpDownArrows"]::up-button:pressed,
QAbstractSpinBox[buttonSymbols="UpDownArrows"]::down-button:pressed { background: $selection; }
QAbstractSpinBox[buttonSymbols="UpDownArrows"]::up-arrow { image: url("$asset_dir/step-up.svg"); width: 10px; height: 7px; }
QAbstractSpinBox[buttonSymbols="UpDownArrows"]::down-arrow { image: url("$asset_dir/step-down.svg"); width: 10px; height: 7px; }
QAbstractSpinBox[buttonSymbols="UpDownArrows"]::up-arrow:off,
QAbstractSpinBox[buttonSymbols="UpDownArrows"]::down-arrow:off { image: none; }
QDialog#unified_settings_dialog QTreeWidget::item { min-height: 28px; }
*[settingsSearchHit="true"] { border-color: $warning; }
""")


_WINDOWS11_ACCENTS = """
QLabel[inkRole="title"] { font-size: 18px; font-weight: 600; }
QLabel[inkRole="sectionTitle"] { font-weight: 600; }
QLabel[inkRole="status"] { padding: 3px 0; }
QLabel[inkRole="hint"] { color: palette(placeholder-text); }
QFrame#app_navigation { border-right: 1px solid palette(mid); }
QPushButton[inkRole="primary"]:enabled {
    color: palette(highlighted-text); background: palette(highlight);
    border: 1px solid palette(highlight); border-radius: 5px; padding: 5px 12px;
}
QPushButton[inkRole="primary"]:enabled:hover { border-color: palette(text); }
QPushButton[inkRole="primary"]:enabled:focus {
    border: 2px solid palette(text); padding: 4px 11px;
}
QPushButton[inkRole="primary"]:enabled:pressed { border-color: palette(shadow); }
"""


def native_style_key(platform, windows_build):
    """Choose the platform adapter independently of Qt plugin availability."""
    if platform == "windows" and windows_build >= 22000:
        return "windows11"
    return None


def _refresh_native_stylesheet(application):
    if application.property("inkstructDesktopStyle") == "windows11" and application.styleSheet():
        application.setStyleSheet(application.styleSheet())


def use_platform_theme(application, *, windows11_accents=False, mode=None):
    """Apply the requested appearance without replacing the native palette."""
    from .ui_behavior import protect_parameter_wheels

    windows_build = sys.getwindowsversion().build if sys.platform == "win32" else 0
    key = native_style_key(application.platformName(), windows_build)
    if not key or application.property("inkstructDesktopStyle") != key:
        style = QtWidgets.QStyleFactory.create(key) if key else None
        if style is None:
            if mode == "dark":
                use_dark_fallback(application, accents=windows11_accents)
            else:
                use_light_theme(application)
            return "fusion"

        protect_parameter_wheels(application)
        application.setStyleSheet("")
        application.setPalette(QtGui.QPalette())
        application.setStyle(style)
        application.setProperty("inkstructDesktopStyle", key)
        if not application.property("inkstructRefreshOnSchemeChange"):
            # Cached palette() rules need to be polished after Qt updates the palette.
            application.styleHints().colorSchemeChanged.connect(
                lambda: _refresh_native_stylesheet(application), QtCore.Qt.ConnectionType.QueuedConnection
            )
            application.setProperty("inkstructRefreshOnSchemeChange", True)
        mode = mode or "system"

    if mode is not None:
        application.styleHints().setColorScheme(THEME_MODES[mode])
    sheet = _WINDOWS11_ACCENTS if windows11_accents else ""
    if application.styleSheet() != sheet:
        application.setStyleSheet(sheet)
    return key


def use_dark_fallback(application, *, accents):
    from .ui_behavior import protect_parameter_wheels

    protect_parameter_wheels(application)
    application.setStyleSheet("")
    application.setStyle("Fusion")
    application.styleHints().setColorScheme(QtCore.Qt.ColorScheme.Dark)
    palette = QtGui.QPalette(QtGui.QColor("#343942"), QtGui.QColor("#23262c"))
    role = QtGui.QPalette.ColorRole
    for color_role, value in {
        role.Base: "#191c21",
        role.AlternateBase: "#252932",
        role.Highlight: "#88b8ff",
        role.Accent: "#88b8ff",
        role.HighlightedText: "#101820",
        role.Link: "#9bc5ff",
        role.LinkVisited: "#d0a5ff",
        role.PlaceholderText: "#a9b3c1",
        role.ToolTipBase: "#343942",
        role.ToolTipText: "#f2f4f7",
    }.items():
        palette.setColor(color_role, QtGui.QColor(value))
    for color_role in (role.WindowText, role.Text, role.ButtonText):
        palette.setColor(QtGui.QPalette.ColorGroup.Disabled, color_role, QtGui.QColor("#8e98a8"))
    application.setPalette(palette)
    if accents:
        application.setStyleSheet(_WINDOWS11_ACCENTS)
    application.setProperty("inkstructDesktopStyle", "fusion")


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
        role.Window: COLORS["canvas"],
        role.WindowText: COLORS["text_primary"],
        role.Base: COLORS["surface"],
        role.AlternateBase: COLORS["surface_secondary"],
        role.Text: COLORS["text_primary"],
        role.Button: COLORS["surface_secondary"],
        role.ButtonText: COLORS["text_primary"],
        role.ToolTipBase: COLORS["tooltip_surface"],
        role.ToolTipText: COLORS["text_primary"],
        role.PlaceholderText: COLORS["text_muted"],
        role.BrightText: COLORS["surface"],
        role.Highlight: COLORS["brand"],
        role.HighlightedText: COLORS["surface"],
        role.Link: COLORS["brand_hover"],
        role.LinkVisited: COLORS["link_visited"],
        role.Accent: COLORS["brand"],
        role.Light: COLORS["surface"],
        role.Midlight: COLORS["divider"],
        role.Mid: COLORS["mid"],
        role.Dark: COLORS["text_muted"],
        role.Shadow: COLORS["text_heading"],
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
        palette.setColor(disabled, color_role, QtGui.QColor(COLORS["text_disabled"]))
    palette.setColor(disabled, role.Base, QtGui.QColor(COLORS["surface_secondary"]))
    palette.setColor(disabled, role.Button, QtGui.QColor(COLORS["surface_disabled"]))
    palette.setColor(disabled, role.Highlight, QtGui.QColor(COLORS["line_subtle"]))
    palette.setColor(disabled, role.HighlightedText, QtGui.QColor(COLORS["text_muted"]))
    application.setPalette(palette)
    assets = (Path(__file__).parent / "editor/resources").as_posix()
    application.setStyleSheet(_STYLE.substitute(COLORS, asset_dir=assets))
    application.setProperty("inkstructDesktopStyle", "fusion")

def set_tone(widget, tone):
    """Update the shared status presentation when a workflow changes state."""
    if widget.property("inkTone") != tone:
        widget.setProperty("inkTone", tone)
        widget.style().unpolish(widget)
        widget.style().polish(widget)
