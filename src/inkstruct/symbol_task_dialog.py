"""Freely combined character selection and explicit reuse of recorded ink."""
import json
import re

from PySide6 import QtCore, QtWidgets

from .punctuation import capture_character, capture_label
from .symbol_catalog import SYMBOL_GROUPS, character_preview
from .symbol_reuse import inventory, reuse_options, validate_reuse
from .symbol_review_dialog import InkPreview
from .symbol_tasks import CUSTOM_PREFIX, TASK_GROUPS, imported_entries
from .ui_behavior import compact_field


class SymbolTaskDialog(QtWidgets.QDialog):
    plan_changed = QtCore.Signal()

    def __init__(self, writer, parent=None, *, imported=None, collection_root=None, catalog=None,
                 embedded=False):
        super().__init__(parent)
        self.setWindowTitle('创建标点与扩展任务')
        self.setObjectName('symbol_task_dialog')
        self.setStyleSheet('''
            QDialog#symbol_task_dialog QCheckBox::indicator:unchecked {
                background-color: transparent; border: 1px solid #8995a5;
                border-radius: 2px;
            }
        ''')
        self.resize(880, 760)
        if embedded:
            self.setWindowFlags(QtCore.Qt.WindowType.Widget)
        self.imported, self.collection_root = imported, collection_root
        self.embedded = embedded
        self._inventory_writer = None
        self.available, self.reuse = {}, {}
        self.checked = {key: set() for key in TASK_GROUPS}
        layout = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()
        self.name = QtWidgets.QLineEdit('标点与扩展采集')
        if catalog is None:
            self.writer = QtWidgets.QLineEdit(writer)
        else:
            from .capture_workflow_ui import WriterPicker, new_writer
            self.writer = WriterPicker(catalog, writer)
        self.repeats = QtWidgets.QSpinBox()
        self.repeats.setRange(1, 100)
        self.repeats.setValue(5)
        self.repeats.setSuffix(' 份')
        self.repeats.setObjectName('task_repeats')
        if embedded:
            self.name.hide()
            self.writer.hide()
        else:
            form.addRow('任务名称', compact_field(self.name, maximum=340))
        if catalog is None and not embedded:
            form.addRow('书写者 ID', compact_field(self.writer, maximum=340))
        elif not embedded:
            row = QtWidgets.QHBoxLayout()
            row.addWidget(self.writer, 1)
            create = QtWidgets.QPushButton('新建书写者…')
            create.clicked.connect(lambda: new_writer(catalog, self.writer, self))
            row.addWidget(create)
            form.addRow('书写者', row)
        if imported is None:
            form.addRow('每个字符目标份数', compact_field(self.repeats))
        else:
            self.repeats.hide()
            form.addRow('每个字符目标份数', QtWidgets.QLabel('按导入字表；空值默认 5 份'))
        layout.addLayout(form)
        hint = QtWidgets.QLabel('自由组合类别，展开后逐字勾选。只补已有样本不足的份数。未勾选的斜体不自动复用；复用须选用已有笔迹供体。中英文逗号、问号、括号等共用一次录制。')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.groups, self.characters, self.panels = {}, {}, {}
        body = QtWidgets.QWidget()
        body_layout = QtWidgets.QVBoxLayout(body)
        for key in TASK_GROUPS:
            label, characters, _ = TASK_GROUPS[key]
            header = QtWidgets.QHBoxLayout()
            check = QtWidgets.QCheckBox(f'{label}（{len(characters)} 个采集项）')
            check.setObjectName('task_group_' + key)
            check.checkStateChanged.connect(
                lambda state, g=key: self.select_group(g, state != QtCore.Qt.CheckState.Unchecked)
            )
            self.groups[key] = check
            header.addWidget(check)
            members = SYMBOL_GROUPS[key][1]
            preview = QtWidgets.QLabel(character_preview(key, members))
            preview.setTextFormat(QtCore.Qt.TextFormat.PlainText)
            preview.setToolTip(" ".join(members) + "\n同形的全角和半角字符只录一项。")
            header.addWidget(preview, 1)
            button = QtWidgets.QPushButton('展开逐字选择')
            button.setObjectName('task_expand_' + key)
            button.setMaximumWidth(150)
            header.addWidget(button)
            body_layout.addLayout(header)
            panel = QtWidgets.QWidget()
            self.characters[key] = {}
            panel.setVisible(False)
            self.panels[key] = panel
            if not embedded:
                self.populate_characters(key)
            button.clicked.connect(lambda _, g=key, b=button: self.toggle_panel(g, b))
            body_layout.addWidget(panel)
        body_layout.addStretch()
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)
        layout.addWidget(scroll, 1)
        row = QtWidgets.QHBoxLayout()
        for title, checked in (('全选字符', True), ('全不选', False)):
            button = QtWidgets.QPushButton(title)
            button.clicked.connect(lambda _, v=checked: self.select_all(v))
            row.addWidget(button)
        self.reuse_button = QtWidgets.QPushButton('指定共用供体…')
        self.reuse_button.clicked.connect(self.configure_reuse)
        row.addWidget(self.reuse_button)
        layout.addLayout(row)
        self.summary = QtWidgets.QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.error = QtWidgets.QLabel()
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        self.buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        self.buttons.button(QtWidgets.QDialogButtonBox.Ok).setText('创建任务')
        self.buttons.button(QtWidgets.QDialogButtonBox.Ok).setProperty("inkRole", "primary")
        self.buttons.button(QtWidgets.QDialogButtonBox.Cancel).setText('取消')
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        if embedded:
            self.buttons.hide()
            self.summary.hide()
            self.error.hide()
            self.reuse_button.setEnabled(False)
        self.repeats.valueChanged.connect(self.update_summary)
        self.writer.textChanged.connect(self.writer_changed)
        if imported is not None:
            self.set_imported(imported)
        else:
            self.update_summary()

    def populate_characters(self, group):
        grid = QtWidgets.QGridLayout(self.panels[group])
        for index, char in enumerate(TASK_GROUPS[group][1]):
            box = QtWidgets.QCheckBox(char)
            box.setObjectName(f'character_{group}_{ord(char):04X}')
            box.setStyleSheet('font-size: 19px;' + ('font-style: italic;' if group == 'latin_italic' else ''))
            box.setToolTip(capture_label(char))
            box.setChecked(char in self.checked[group])
            box.toggled.connect(lambda checked, g=group, c=char: self.character_changed(g, c, checked))
            self.characters[group][char] = box
            grid.addWidget(box, index // 10, index % 10)

    def toggle_panel(self, group, button):
        panel = self.panels[group]
        visible = panel.isHidden()
        if visible and panel.layout() is None:
            self.populate_characters(group)
        panel.setVisible(visible)
        button.setText('收起' if visible else '展开逐字选择')

    def writer_changed(self):
        self.reuse.clear()
        self._inventory_writer = None
        self.available = {}
        if self.embedded:
            self.reuse_button.setEnabled(False)
        self.update_summary()

    def apply_inventory(self, available):
        self.available = available
        self._inventory_writer = self.writer.text().strip()
        self.reuse_button.setEnabled(True)

    def load_inventory(self, *, force=False):
        if self.embedded:
            if self._inventory_writer is None:
                raise ValueError('请先核对当前书写者的样本')
            return
        writer = self.writer.text().strip()
        if force or writer != self._inventory_writer:
            self.available = inventory(self.collection_root, writer)
            self._inventory_writer = writer

    def select_group(self, group, checked):
        self.checked[group] = set(TASK_GROUPS[group][1]) if checked else set()
        self.sync_group(group)
        self.update_summary()

    def character_changed(self, group, char, checked):
        if checked:
            self.checked[group].add(char)
        else:
            self.checked[group].discard(char)
        self.sync_group(group)
        self.update_summary()

    def sync_group(self, group):
        selected = self.checked[group]
        count, total = len(selected), len(TASK_GROUPS[group][1])
        check = self.groups[group]
        with QtCore.QSignalBlocker(check):
            check.setTristate(0 < count < total)
            check.setCheckState(QtCore.Qt.Checked if count == total else
                                QtCore.Qt.PartiallyChecked if count else QtCore.Qt.Unchecked)
        for char, box in self.characters[group].items():
            with QtCore.QSignalBlocker(box):
                box.setChecked(char in selected)
        for char in selected:
            self.reuse.pop((group, char), None)

    def select_all(self, checked):
        for key, (_, characters, _) in TASK_GROUPS.items():
            self.checked[key] = set(characters) if checked else set()
            self.sync_group(key)
        self.update_summary()

    def selected(self):
        return {key: [char for char in chars if char in self.checked[key]]
                for key, (_, chars, _) in TASK_GROUPS.items()}

    def selection_entries(self):
        selected = self.selected()
        groups = [g for g in TASK_GROUPS if selected[g] or any(k[0] == g for k in self.reuse)]
        if not groups:
            raise ValueError('请选择需要采集的字符，或明确确认复用')
        if self.imported is None:
            entries = [(c, self.repeats.value(), index) for index, g in enumerate(groups) for c in selected[g]]
        else:
            entries = [(c, n, i) for c, n, i in imported_entries(groups, self.imported)
                       if c in selected[groups[i]]]
        return groups, entries

    def plan(self, selection=None):
        self.load_inventory()
        groups, entries = self.selection_entries() if selection is None else selection
        kept, self.existing_count = [], 0
        for char, count, index in entries:
            style = TASK_GROUPS[groups[index]][2]
            existing = len(self.available.get((capture_character(char), style), {}))
            self.existing_count += min(count, existing)
            if count > existing:
                kept.append((char, count - existing, index))
        reuse = []
        for record in self.reuse.values():
            validate_reuse(record)
            current = self.available.get((record['source'], 'upright'), {})
            if not set(record['sample_ids']) <= set(current):
                raise ValueError('复用来源已变化，请重新查看笔迹并确认')
            reuse.append(record)
        if not kept and not reuse:
            raise ValueError('所选字符的份数已满足，无需重复创建任务')
        return CUSTOM_PREFIX + json.dumps({'groups': groups, 'reuse': reuse}, ensure_ascii=False, separators=(',', ':')), kept

    def update_summary(self):
        if self.embedded:
            self.plan_changed.emit()
            return
        if not hasattr(self, 'summary'):
            return
        try:
            _, entries = self.plan()
            self.summary.setText(f'待采 {len(entries)} 个字符/写法，{sum(n for _, n, _ in entries)} 份；已有 {self.existing_count} 份；已确认复用 {len(self.reuse)} 个。' +
                                 ('仅保存复用配置，无需录制。' if not entries else ''))
            valid = True
            self.error.clear()
        except (OSError, ValueError) as error:
            self.summary.setText(str(error))
            valid = False
        self.buttons.button(QtWidgets.QDialogButtonBox.Ok).setEnabled(valid)
        self.plan_changed.emit()

    def set_imported(self, imported):
        self.imported = imported
        wanted = {capture_character(char) for char, _, _ in imported}
        for group, (_, characters, _) in TASK_GROUPS.items():
            self.checked[group] = wanted.intersection(characters)
            self.sync_group(group)
        self.update_summary()

    def configure_reuse(self):
        try:
            self.load_inventory(force=True)
            dialog = ReuseDialog(self.available, self.reuse, self)
            if dialog.exec() != QtWidgets.QDialog.Accepted:
                return
            self.reuse = dialog.confirmed()
            for group, char in self.reuse:
                self.checked[group].discard(char)
            for group in self.groups:
                self.sync_group(group)
            self.update_summary()
        except (OSError, ValueError) as error:
            self.error.setText(str(error))

    def accept(self):
        if not self.writer.text().strip():
            self.error.setText('请选择或新建书写者')
            return
        if not self.name.text().strip():
            self.error.setText('请输入任务名称')
            return
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,79}', self.writer.text().strip()):
            self.error.setText('书写者 ID 需以字母或数字开头，仅含字母、数字、点、横线或下划线')
            return
        try:
            self.load_inventory(force=True)
            self.plan()
        except (OSError, ValueError) as error:
            self.error.setText(str(error))
            return
        super().accept()


class ReuseDialog(QtWidgets.QDialog):
    def __init__(self, available, selected, parent=None):
        super().__init__(parent)
        self.available = available
        self.setWindowTitle('指定共用供体')
        self.setStyleSheet('QListView::indicator:unchecked { background: transparent; border: 1px solid #8995a5; border-radius: 2px; }')
        self.resize(800, 540)
        layout = QtWidgets.QVBoxLayout(self)
        note = QtWidgets.QLabel('逐项确认目标字符采用右侧英文正体笔迹，保留目标编码和原始笔迹。'
                                '缺少正体来源的规则仍会列出。已确认的来源变化后须重新确认。')
        note.setWordWrap(True)
        layout.addWidget(note)
        row = QtWidgets.QHBoxLayout()
        self.list = QtWidgets.QListWidget()
        self.records = []
        for group, target, source in reuse_options():
            samples = available.get((source, 'upright'), {})
            previous = selected.get((group, target))
            valid_previous = previous and set(previous['sample_ids']) <= set(samples)
            record = {'group': group, 'target': target, 'source': source, 'source_style': 'upright',
                      'sample_ids': previous['sample_ids'] if valid_previous else sorted(samples), 'confirmed': True}
            self.records.append(record)
            label = '英文斜体' if group == 'latin_italic' else '希腊字母'
            status = '缺少录制来源' if not samples else '来源已变化，须重新确认' if previous and not valid_previous else f'{len(record["sample_ids"])} 份可用'
            item = QtWidgets.QListWidgetItem(f'{target}（{label}）← {source}（英文正体） · {status}')
            if samples:
                item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
                item.setCheckState(QtCore.Qt.Checked if valid_previous else QtCore.Qt.Unchecked)
            else:
                item.setFlags(item.flags() & ~QtCore.Qt.ItemIsUserCheckable)
            self.list.addItem(item)
        row.addWidget(self.list, 1)
        right = QtWidgets.QVBoxLayout()
        self.specimens = QtWidgets.QComboBox()
        right.addWidget(self.specimens)
        self.preview = InkPreview()
        right.addWidget(self.preview, 1)
        row.addLayout(right, 1)
        layout.addLayout(row, 1)
        selection = QtWidgets.QHBoxLayout()
        for title, checked in (('勾选全部可用复用', True), ('清除复用勾选', False)):
            button = QtWidgets.QPushButton(title)
            button.clicked.connect(lambda _, v=checked: self.select_all(v))
            selection.addWidget(button)
        layout.addLayout(selection)
        self.list.currentRowChanged.connect(self.show_source)
        self.specimens.currentIndexChanged.connect(self.show_specimen)
        first = next((index for index, record in enumerate(self.records) if record['sample_ids']), -1)
        self.list.setCurrentRow(first)
        if first == -1:
            layout.addWidget(QtWidgets.QLabel('此作者尚无可复用的英文正体样本。请先录制所需正体字符。'))
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.button(QtWidgets.QDialogButtonBox.Ok).setText('确认选用所勾选的供体')
        buttons.button(QtWidgets.QDialogButtonBox.Cancel).setText('取消')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def show_source(self, index):
        self.specimens.clear()
        if index >= 0:
            record = self.records[index]
            for n, sid in enumerate(record['sample_ids'], 1):
                self.specimens.addItem(f'查看第 {n} 份 · {sid[:8]}', sid)

    def show_specimen(self):
        index, sid = self.list.currentRow(), self.specimens.currentData()
        self.preview.value = (self.available[(self.records[index]['source'], 'upright')][sid]
                              if index >= 0 and sid else None)
        self.preview.update()

    def confirmed(self):
        return {(r['group'], r['target']): r for index, r in enumerate(self.records)
                if r['sample_ids'] and self.list.item(index).checkState() == QtCore.Qt.Checked}

    def select_all(self, checked):
        for i, record in enumerate(self.records):
            if record['sample_ids']:
                self.list.item(i).setCheckState(QtCore.Qt.Checked if checked else QtCore.Qt.Unchecked)
