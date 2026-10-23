"""Document-wide footnote settings, committed only after confirmation."""

from dataclasses import replace

from PySide6 import QtWidgets

from ..document.footnote_style import FootnoteStyle


class FootnoteSettingsDialog(QtWidgets.QDialog):
    def __init__(self, style, parent=None):
        super().__init__(parent)
        self.original = self.base = style
        self.setWindowTitle("脚注排版")
        self.setObjectName("footnote_settings_dialog")
        self.resize(540, 500)
        form = QtWidgets.QFormLayout(self)
        self.controls, self.initial, self.factors = {}, {}, {}
        for key, label, factor, low, high in (
            ("reference_scale", "引用编号字号 / 所在文字字号", 100, 10, 100),
            ("reference_raise_em", "引用编号上移 / 所在文字字号", 100, 0, 200),
            ("text_scale", "脚注字号 / 正文字号", 100, 10, 200),
            ("line_height_scale", "脚注最小行高 / 正文行高", 100, 10, 300),
            ("body_gap_mm", "正文到分隔线净距", 1, 0, 100),
            ("note_gap_mm", "分隔线到脚注净距", 1, 0, 100),
            ("separator_length_mm", "分隔线长度范围", 1, 1, 1000),
            ("page_fraction", "常规脚注区 / 正文区高度", 100, 10, 90),
            ("label_indent_mm", "编号栏最小宽度", 1, 1, 100),
        ):
            control = QtWidgets.QDoubleSpinBox(self)
            control.setObjectName(key)
            control.setDecimals(4)
            control.setRange(low, high)
            control.setSingleStep(5 if factor == 100 else 0.5)
            control.setSuffix(" %" if factor == 100 else " mm")
            self.controls[key], self.factors[key] = control, factor
            form.addRow(label, control)
        note = QtWidgets.QLabel(
            "引用编号比例随所在正文、标题、表格或图题字号计算。脚注内公式和代码随脚注字号比例缩放。\n\n"
            "常规高度比例用于正文持续排版时的预留；必要注释开头可超出比例，正文结束后的续注可用满余下空间。"
            "行高、编号栏宽度仍按实际笔迹扩展，过小字形或空间不足会报告诊断。\n\n"
            "分隔线从正文左边界内半个笔宽处起笔，到所设长度范围内结束；过长时按正文宽度截短。"
        )
        note.setWordWrap(True)
        form.addRow(note)
        reset = QtWidgets.QPushButton("恢复默认", self)
        reset.setObjectName("reset_footnote_settings")
        reset.clicked.connect(self.reset_defaults)
        form.addRow(reset)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Ok).setText("确定")
        buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self._load()

    def _load(self):
        for key, control in self.controls.items():
            control.setValue(getattr(self.base, key) * self.factors[key])
            self.initial[key] = control.value()

    def reset_defaults(self):
        self.base = FootnoteStyle()
        self._load()

    def configuration(self):
        # Opening and accepting a dialog must not round untouched stored values.
        return replace(
            self.base,
            **{
                key: control.value() / self.factors[key]
                for key, control in self.controls.items()
                if control.value() != self.initial[key]
            },
        )
