"""Export settings edit a draft; accepting never edits document geometry."""
from PySide6 import QtWidgets

from ..plotter.options import ExportOptions, parse_pages
from ..ui_behavior import protect_parameter_wheels


class SvgExportDialog(QtWidgets.QDialog):
    def __init__(self, count, optimize=True, parent=None, *, force=False):
        super().__init__(parent)
        protect_parameter_wheels(QtWidgets.QApplication.instance())
        self.force = force
        self.count = count
        self.options = None
        self.setObjectName('svg_export_dialog')
        self.setWindowTitle('强制导出 SVG' if force else '导出 SVG')
        self.setMinimumWidth(540)
        column = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()
        self.pages = QtWidgets.QLineEdit()
        self.pages.setObjectName('svg_export_pages')
        self.pages.setPlaceholderText(f'全部 {count} 页；例如 1-3,5')
        form.addRow('导出页码', self.pages)
        self.tables = QtWidgets.QCheckBox('导出表格内内容（取消后仅保留表格线和表外内容）')
        self.tables.setChecked(True)
        self.tables.setObjectName('svg_export_tables')
        form.addRow(self.tables)
        self.optimize = QtWidgets.QCheckBox('优化路径（允许反转笔画执行方向）')
        self.optimize.setChecked(optimize)
        form.addRow(self.optimize)
        self.scales = []
        for title, name in [('横向比例校正', 'svg_scale_x'), ('纵向比例校正', 'svg_scale_y')]:
            control = QtWidgets.QDoubleSpinBox()
            control.setObjectName(name)
            control.setDecimals(4)
            control.setRange(10, 1000)
            control.setSuffix(' %')
            control.setValue(100)
            self.scales.append(control)
            form.addRow(title, control)
        self.registration = QtWidgets.QCheckBox('添加定位点')
        self.registration.setObjectName('svg_registration')
        form.addRow(self.registration)
        column.addLayout(form)
        note = QtWidgets.QLabel('定位点是在各内容文本框左上角、右下角边界上的 0.1 mm 短线，笔宽 0.01 mm。'
                               '\n先校验原始排版，再以左上角为原点同步缩放输出坐标与 SVG 画布（含 viewBox）；笔宽不变。'
                               '\n输出尺寸随比例改变，仍会校验缩放后的画布边界；原文档纸张和预览不变。'
                               '\n所有选项只作用于本次冻结的导出，不重新排版。文件沿用原文档页码。')
        if force:
            note.setText("强制导出只保留已排出的有效笔迹，缺失处留空；不绘制错误占位框。"
                         "\n无效、单点或越出纸张的笔画会跳过；未排出的后续内容不自动补排。"
                         "\n随 SVG 提供 issues.txt / issues.json 问题清单，页码、比例和路径优化仅作用于导出。")
        note.setWordWrap(True)
        column.addWidget(note)
        self.error = QtWidgets.QLabel('')
        self.error.setStyleSheet('color:#b43d3d')
        self.error.setWordWrap(True)
        column.addWidget(self.error)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.button(QtWidgets.QDialogButtonBox.Ok).setText('选择输出位置…')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        column.addWidget(buttons)

    def accept(self):
        try:
            if any(not c.hasAcceptableInput() for c in self.scales):
                raise ValueError('比例输入无效')
            self.options = ExportOptions(parse_pages(self.pages.text(), self.count), self.tables.isChecked(),
                self.scales[0].value() / 100, self.scales[1].value() / 100, self.registration.isChecked(), self.force)
        except ValueError as error:
            self.error.setText(str(error))
            return
        super().accept()
