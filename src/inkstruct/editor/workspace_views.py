"""Workspace visibility preferences, independent of document layout and content."""

from PySide6 import QtCore, QtWidgets


class WorkspaceViews(QtCore.QObject):
    def __init__(self, owner, splitter, source_pane, preview_pane):
        super().__init__(owner)
        self.owner = owner
        self.splitter = splitter
        self.source_pane = source_pane
        self.preview_pane = preview_pane
        self.settings = QtCore.QSettings("InkStruct", "WorkspaceViews")
        self.mode = None
        try:
            self.split_sizes = [int(n) for n in self.settings.value("split_sizes", [480, 680])]
            if len(self.split_sizes) != 2 or min(self.split_sizes) <= 0:
                self.split_sizes = [480, 680]
        except (TypeError, ValueError, OverflowError):
            self.split_sizes = [480, 680]
        self.widget = QtWidgets.QWidget(owner)
        self.widget.setObjectName("workspace_view_modes")
        row = QtWidgets.QHBoxLayout(self.widget)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        self.group = QtWidgets.QButtonGroup(self)
        self.buttons = {}
        for key, title, description in (
            ("source", "源码", "只显示 Markdown 源码"),
            ("split", "并排", "并排显示源码和连续页面预览"),
            ("preview", "预览", "只显示连续页面预览"),
        ):
            button = QtWidgets.QToolButton()
            button.setObjectName("workspace_view_" + key)
            button.setText(title)
            button.setAccessibleName(title + "显示模式")
            button.setToolTip(description)
            button.setCheckable(True)
            button.setMinimumHeight(32)
            self.group.addButton(button)
            row.addWidget(button)
            self.buttons[key] = button
            button.clicked.connect(lambda checked=False, mode=key: self.set_mode(mode))
        splitter.splitterMoved.connect(self.remember_sizes)
        mode = self.settings.value("mode", "split")
        self.set_mode(mode if isinstance(mode, str) and mode in self.buttons else "split",
                      persist=False, focus=False)

    def remember_sizes(self, *_):
        if self.mode == "split" and all(n > 0 for n in self.splitter.sizes()):
            self.split_sizes = self.splitter.sizes()
            self.settings.setValue("split_sizes", self.split_sizes)

    def set_mode(self, mode, *, persist=True, focus=True):
        if mode == self.mode:
            return
        self.remember_sizes()
        self.mode = mode
        self.source_pane.setVisible(mode != "preview")
        self.preview_pane.setVisible(mode != "source")
        if mode == "split":
            self.splitter.setSizes(self.split_sizes)
        self.buttons[mode].setChecked(True)
        if persist:
            self.settings.setValue("mode", mode)
        if focus:
            self.focus_current()

    def focus_current(self):
        target = self.owner.scroll if self.mode == "preview" else self.owner.editor
        target.setFocus(QtCore.Qt.FocusReason.OtherFocusReason)

    def focus_source(self):
        if self.mode == "preview":
            self.set_mode("split")
        self.owner.editor.setFocus(QtCore.Qt.FocusReason.ShortcutFocusReason)
