"""Explicitly rename cross-face template references without changing content."""

from PySide6 import QtCore, QtWidgets

from ..document.template_rename import rename_reference


class TemplateRenameDialog(QtWidgets.QDialog):
    def __init__(self, template, bindings=(), parent=None, *, region=None):
        super().__init__(parent)
        self.template, self.bindings = template, tuple(bindings)
        self.result_pair = None
        self.setWindowTitle("联动重命名")
        layout = QtWidgets.QFormLayout(self)
        note = QtWidgets.QLabel(
            "同时更新首页、续页的同名对象及引用它的字段和内容绑定。坐标、笔迹与绑定顺序保持不变。"
        )
        note.setWordWrap(True)
        layout.addRow(note)
        self.kind, self.old_name = QtWidgets.QComboBox(), QtWidgets.QComboBox()
        self.kind.addItem("填写区", "region")
        self.kind.addItem("锚点", "anchor")
        self.new_name = QtWidgets.QLineEdit()
        # Display legacy identifiers intact; validate genuinely new names on accept.
        self.new_name.setMaxLength(2 * 1024 * 1024)
        layout.addRow("对象类型", self.kind)
        layout.addRow("原名称", self.old_name)
        layout.addRow("新名称", self.new_name)
        self.error = QtWidgets.QLabel()
        self.error.setWordWrap(True)
        self.error.setTextFormat(QtCore.Qt.PlainText)
        layout.addRow(self.error)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)
        self.kind.currentIndexChanged.connect(self.refresh)
        self.old_name.currentTextChanged.connect(self.new_name.setText)
        self.refresh()
        if region is not None:
            index = self.old_name.findText(region)
            if index >= 0:
                self.old_name.setCurrentIndex(index)

    def refresh(self):
        self.old_name.clear()
        collection = "reserved" if self.kind.currentData() == "region" else "anchors"
        names = dict.fromkeys(
            v.name
            for face in (self.template.first, self.template.continuation)
            for v in getattr(face, collection)
        )
        self.old_name.addItems(list(names))
        self.new_name.setText(self.old_name.currentText())
        self.error.clear()

    def accept(self):
        self.result_pair = None
        try:
            self.result_pair = rename_reference(
                self.template,
                self.bindings,
                self.kind.currentData(),
                self.old_name.currentText(),
                self.new_name.text(),
            )
        except (ValueError, TypeError) as error:
            self.error.setText(str(error))
            return
        super().accept()

    def configuration(self):
        if self.result_pair is None:
            raise ValueError("重命名尚未确认")
        return self.result_pair
