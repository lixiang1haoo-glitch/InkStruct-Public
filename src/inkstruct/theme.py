"""Application-only light appearance until all views support dark mode."""

from PySide6 import QtCore, QtGui


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
