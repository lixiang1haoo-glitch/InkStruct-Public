"""Code grid configuration, applied as one editor transaction."""

from dataclasses import replace

from PySide6 import QtWidgets


class CodeSettingsDialog(QtWidgets.QDialog):
    def __init__(self, style, parent=None):
        super().__init__(parent)
        self.original = style
        self.setWindowTitle("代码块排版")
        form = QtWidgets.QFormLayout(self)
        self.controls, self.initial = {}, {}
        for key, label in (
            ("em_mm", "字形大小"),
            ("advance_mm", "固定字格宽度"),
            ("line_height_mm", "最小行高"),
        ):
            widget = QtWidgets.QDoubleSpinBox()
            widget.setDecimals(4)
            widget.setRange(min(0.0001, getattr(style, key)), 2000)
            widget.setSuffix(" mm")
            widget.setValue(getattr(style, key))
            widget.setSingleStep(0.25)
            self.controls[key] = widget
            self.initial[key] = widget.value()
            form.addRow(label, widget)
        self.tabs = QtWidgets.QSpinBox()
        self.tabs.setRange(1, 16)
        self.tabs.setValue(style.tab_columns)
        form.addRow("制表位列数", self.tabs)
        self.wrap = QtWidgets.QCheckBox("允许宽行换行并绘制续行标记")
        self.wrap.setChecked(style.wrap_lines)
        form.addRow(self.wrap)
        note = QtWidgets.QLabel(
            "保留空行和尾随空格。默认宽行报错；可明确开启换行，续行左侧绘制标记。字形超出字格仍报错，不会挤压字形。"
        )
        note.setWordWrap(True)
        form.addRow(note)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def configuration(self):
        changes = {k: c.value() for k, c in self.controls.items() if c.value() != self.initial[k]}
        return replace(
            self.original,
            **changes,
            tab_columns=self.tabs.value(),
            wrap_lines=self.wrap.isChecked(),
        )
