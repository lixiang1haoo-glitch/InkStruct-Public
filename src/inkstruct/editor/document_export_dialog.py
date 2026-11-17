"""Choose how to use the frozen document, then review the selected pages."""
from PySide6 import QtWidgets

from ..plotter.options import ExportOptions, parse_pages
from ..ui_behavior import protect_parameter_wheels
from .export_check import check_export


class DocumentExportDialog(QtWidgets.QDialog):
    def __init__(self, snapshot, document, flow, current, optimize, parent=None):
        super().__init__(parent)
        protect_parameter_wheels(QtWidgets.QApplication.instance())
        self.snapshot, self.document, self.flow, self.current = snapshot, document, flow, current
        self.checked = self.selection = None
        self.view_problems = False
        self.setObjectName('document_export_dialog')
        self.setWindowTitle('导出')
        self.setMinimumWidth(565)
        column = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()
        self.purpose = QtWidgets.QComboBox()
        self.purpose.addItem('写字机 SVG', 'machine')
        self.purpose.addItem('整页排版图', 'page')
        self.purpose.addItem('整篇 PDF', 'pdf')
        form.addRow('用途', self.purpose)
        self.description = QtWidgets.QLabel()
        self.description.setWordWrap(True)
        form.addRow(self.description)
        self.format = QtWidgets.QComboBox()
        self.format.addItem('PNG', 'png')
        self.format.addItem('页面 SVG', 'svg')
        form.addRow('格式', self.format)
        self.range = QtWidgets.QComboBox()
        self.range.addItem(f'全部页（{len(snapshot.pages)} 页）', 'all')
        self.range.addItem(f'当前页（第 {current + 1} 页）', 'current')
        self.range.addItem('指定页', 'selection')
        form.addRow('范围', self.range)
        self.pages = QtWidgets.QLineEdit()
        self.pages.setPlaceholderText('例如 1-3,5')
        form.addRow('页码', self.pages)
        self.form = form
        column.addLayout(form)

        self.advanced_panel = QtWidgets.QGroupBox('高级设置')
        choices = QtWidgets.QFormLayout(self.advanced_panel)
        self.tables = QtWidgets.QCheckBox('导出表格内内容（取消后保留表格线和表格外内容）')
        self.tables.setChecked(True)
        choices.addRow(self.tables)
        self.optimize = QtWidgets.QCheckBox('优化路径（允许反转笔画执行方向）')
        self.optimize.setChecked(optimize)
        choices.addRow(self.optimize)
        self.scales = []
        for label in ('横向比例校正', '纵向比例校正'):
            control = QtWidgets.QDoubleSpinBox()
            control.setDecimals(4)
            control.setRange(10, 1000)
            control.setSuffix(' %')
            control.setValue(100)
            self.scales.append(control)
            choices.addRow(label, control)
        self.registration = QtWidgets.QCheckBox('添加定位点')
        choices.addRow(self.registration)
        note = QtWidgets.QLabel('比例校正以左上角为原点，同步缩放坐标和纸面，笔宽保持原值。')
        note.setWordWrap(True)
        choices.addRow(note)
        column.addWidget(self.advanced_panel)

        self.report = QtWidgets.QPlainTextEdit()
        self.report.setReadOnly(True)
        self.report.setMinimumHeight(110)
        self.report.setAccessibleName('导出检查结果')
        column.addWidget(self.report)
        self.confirm_images = QtWidgets.QCheckBox('我确认跳过位图，保留图题和留白')
        column.addWidget(self.confirm_images)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        self.check_button = buttons.addButton('检查导出', QtWidgets.QDialogButtonBox.ButtonRole.ActionRole)
        self.problems = buttons.addButton('查看问题', QtWidgets.QDialogButtonBox.ButtonRole.ActionRole)
        self.partial = buttons.addButton('仅导出可用笔迹…', QtWidgets.QDialogButtonBox.ButtonRole.ActionRole)
        self.save = buttons.addButton('选择保存位置…', QtWidgets.QDialogButtonBox.ButtonRole.AcceptRole)
        self.check_button.clicked.connect(self.run_check)
        self.problems.clicked.connect(self.open_problems)
        self.partial.clicked.connect(self.accept_partial)
        self.save.clicked.connect(self.accept)
        buttons.rejected.connect(self.reject)
        column.addWidget(buttons)
        for control in (self.purpose, self.format, self.range):
            control.currentIndexChanged.connect(self.reset_check)
        self.pages.textChanged.connect(self.reset_check)
        for control in (self.tables, self.optimize, self.registration):
            control.toggled.connect(self.reset_check)
        for control in self.scales:
            control.valueChanged.connect(self.reset_check)
        self.confirm_images.toggled.connect(self.update_save)
        self.reset_check()
        self.check_button.setDefault(True)

    def reset_check(self, *_):
        kind = self.purpose.currentData()
        self.description.setText({
            'machine': '逐页导出可执行笔迹。模板底图与位图留在排版中。',
            'page': '保留模板底图、图片、笔迹和表格，可查看或分享单页。',
            'pdf': '合成一个多页文件，保留原有页序、纸张尺寸和页面内容。',
        }[kind])
        self.form.setRowVisible(self.format, kind == 'page')
        self.form.setRowVisible(self.range, kind != 'pdf')
        self.form.setRowVisible(self.pages, kind != 'pdf' and self.range.currentData() == 'selection')
        self.advanced_panel.setVisible(kind == 'machine')
        self.checked = None
        self.report.setPlainText('选择用途和范围后检查导出。')
        self.confirm_images.setChecked(False)
        self.confirm_images.hide()
        self.problems.hide()
        self.partial.hide()
        self.update_save()

    def run_check(self):
        kind = self.purpose.currentData()
        try:
            range_kind = 'all' if kind == 'pdf' else self.range.currentData()
            count = len(self.snapshot.pages)
            if range_kind == 'selection' and not self.pages.text().strip():
                raise ValueError('请输入指定页码，例如 1-3,5')
            indices = ((self.current,) if range_kind == 'current'
                       else parse_pages(self.pages.text() if range_kind == 'selection' else '', count))
            machine = kind == 'machine'
            options = (ExportOptions(indices, self.tables.isChecked(), self.scales[0].value() / 100,
                                     self.scales[1].value() / 100, self.registration.isChecked())
                       if machine else ExportOptions(indices))
            self.checked = check_export(self.snapshot, self.document, self.flow, options, machine=machine,
                                        png=kind == 'page' and self.format.currentData() == 'png')
        except ValueError as error:
            self.report.setPlainText(str(error))
            return
        checked = self.checked
        lines = [f"检查范围：第 {self.page_numbers(checked.pages)} 页，共 {len(checked.pages)} 页"]
        lines.extend(checked.errors or ('检查通过',))
        if checked.machine:
            skipped = checked.machine.scope['skipped_empty_pages']
            if skipped:
                lines.append('跳过无可写笔迹的页：' + '、'.join(map(str, skipped)))
        if machine and checked.images:
            lines.append('以下位图将跳过，图题和留白保留')
            lines.extend(f"第 {item['page_number']} 页 · {item['display_name']}" for item in checked.images)
        lines.extend(f'提醒 · {warning}' for warning in checked.warnings)
        self.report.setPlainText('\n'.join(lines))
        self.problems.setVisible(any(error != '所选页没有可写笔迹' for error in checked.errors))
        self.partial.setVisible(checked.partial is not None)
        self.confirm_images.setVisible(bool(checked.machine and checked.images))
        self.update_save()

    @staticmethod
    def page_numbers(indices):
        return '、'.join(str(i + 1) for i in indices)

    def update_save(self, *_):
        checked = self.checked
        self.save.setEnabled(bool(checked and not checked.errors and (
            not (checked.machine and checked.images) or self.confirm_images.isChecked())))

    def open_problems(self):
        self.view_problems = True
        self.reject()

    def accept_partial(self):
        partial = self.checked.partial if self.checked else None
        if partial is None:
            return
        text = (f'将写出第 {self.page_numbers(partial.pages)} 页的可用笔迹。'
                '\n缺字、无效和越界的笔画留空，输出目录附问题清单。')
        images = sorted({item['page_index'] for item in partial.scope['omitted_images']})
        if images:
            text += f'\n第 {self.page_numbers(images)} 页含将跳过的位图，保留图题和留白。'
        yes = QtWidgets.QMessageBox.StandardButton.Yes
        cancel = QtWidgets.QMessageBox.StandardButton.Cancel
        if QtWidgets.QMessageBox.question(self, '仅导出可用笔迹', text, yes | cancel, cancel) == yes:
            self.selection = ('machine', self.checked, partial, self.optimize.isChecked())
            super().accept()

    def accept(self):
        if self.save.isEnabled():
            kind = self.purpose.currentData()
            format = self.format.currentData() if kind == 'page' else kind
            self.selection = (format, self.checked, self.checked.machine, self.optimize.isChecked())
            super().accept()
