"""Explicit review of complete named sets and unsupported characters."""
from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from .character_sets import CharacterSets
from .generation_targets import structure_targets


class CharacterSetsDialog(QtWidgets.QDialog):
    def __init__(self, supported, parent=None):
        super().__init__(parent)
        self.setWindowTitle('选择内置字表 · 不转换正文或供体')
        self.resize(960, 780)
        self.supported = tuple(supported)
        self.catalog = CharacterSets()
        self.result_manifest = None
        layout = QtWidgets.QVBoxLayout(self)
        intro = QtWidgets.QLabel('按明确版本选择完整字表，可自由合并；共用字去重，一简多繁保留全部独立字符。\n'
            '以下均有各自范围，不存在一份通用的“全部简繁字表”。关系数据不用于自动转换或替换缺字。')
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.all_structures = QtWidgets.QCheckBox(f"结构库全部汉字 · {len(self.supported)} 字")
        self.all_structures.setObjectName("structure_library_all")
        self.all_structures.setToolTip("采用当前结构库的完整范围，不能与其他内置字表合并。")
        self.all_structures.toggled.connect(self.structure_selection_changed)
        layout.addWidget(self.all_structures)
        self.checkboxes = {}
        for entry in self.catalog.entries:
            box = QtWidgets.QCheckBox(f"{entry['title']} · {entry['version']} · {entry['count']} 字")
            box.setObjectName(entry['id'])
            box.setToolTip(entry['scope'] + '\n' + entry['url'])
            self.checkboxes[entry['id']] = box
            layout.addWidget(box)
            box.toggled.connect(self.selection_changed)
        self.summary = QtWidgets.QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.details = QtWidgets.QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setMinimumHeight(220)
        layout.addWidget(self.details, 1)
        self.copy_button = QtWidgets.QPushButton('复制完整字表与缺口报告')
        self.copy_button.clicked.connect(lambda: QtWidgets.QApplication.clipboard().setText(self.details.toPlainText()))
        layout.addWidget(self.copy_button)
        lookup = QtWidgets.QHBoxLayout()
        lookup.addWidget(QtWidgets.QLabel('查看单字对应与地区字表成员'))
        self.lookup = QtWidgets.QLineEdit()
        self.lookup.setMaxLength(2)  # allow one supplementary-plane character
        lookup.addWidget(self.lookup)
        layout.addLayout(lookup)
        self.relationship = QtWidgets.QPlainTextEdit()
        self.relationship.setReadOnly(True)
        self.relationship.setMaximumHeight(150)
        self.lookup.textChanged.connect(lambda s: self.relationship.setPlainText(self.catalog.describe_character(s)))
        layout.addWidget(self.relationship)
        self.acknowledge = QtWidgets.QCheckBox('我已查看缺口，仅生成结构库支持的部分；完整字表与未支持字符随任务保存')
        self.acknowledge.toggled.connect(self.update_accept)
        layout.addWidget(self.acknowledge)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok |
                                            QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        self.accept_button = buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Ok)
        self.accept_button.setText('使用所选字表')
        buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Cancel).setText('取消')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.selection_changed()

    def structure_selection_changed(self, checked):
        for box in self.checkboxes.values():
            with QtCore.QSignalBlocker(box):
                if checked:
                    box.setChecked(False)
                box.setEnabled(not checked)
        self.selection_changed()

    def selected_ids(self):
        return [key for key, box in self.checkboxes.items() if box.isChecked()]

    def selection_changed(self):
        # Any selection change revokes an earlier omission acknowledgement.
        self.acknowledge.setChecked(False)
        if self.all_structures.isChecked():
            self.current = structure_targets(self.supported)
            self.summary.setText(f"结构库全部汉字 · {len(self.current['requested'])} 字 · 供体池保持完整。")
            self.details.setPlainText("当前结构库支持的完整目标\n" + "".join(self.current["requested"]))
            self.acknowledge.setEnabled(False)
            self.update_accept()
            return
        self.current = self.catalog.manifest(self.selected_ids(), self.supported)
        source = self.current['source']
        self.summary.setText(f"去重目标 {len(self.current['requested'])} 字；共用/重复成员 {source['shared_deduplicated_count']} 项；"
            f"结构库支持 {len(self.current['supported'])} 字，不支持 {len(self.current['unsupported'])} 字。供体池保持完整。")
        lines = ['目录版本：' + source['catalog_revision'], '目录 SHA-256：' + source['catalog_sha256']]
        for e in source['sets']:
            lines += ['', f"{e['title']} / {e['version']} / {e['count']} 字", e['scope'], e['url']]
            if e['errata']:
                lines += ['来源勘误：A02149 字符栏为“汨”U+6C68，Unicode 栏误写 6C69；保留原记录并依同部字典 A02149 核对。',
                          e['errata'][0]['corroboration']]
        lines += ['', '不支持字符（不会替换；未确认则禁止使用）：',
                  ' '.join(f'{c}(U+{ord(c):04X})' for c in self.current['unsupported']),
                  '', '完整去重目标（原始字符身份、按字表顺序）：', ''.join(self.current['requested']),
                  '', '字表不改变结构库。同一 Unicode 的地区笔形不由字集选择决定；未内置香港规范全表。']
        self.details.setPlainText('\n'.join(lines))
        self.acknowledge.setEnabled(bool(self.current['unsupported']))
        self.update_accept()

    def update_accept(self):
        current = getattr(self, 'current', None)
        if current is not None:
            self.accept_button.setEnabled(bool(current['supported']) and
                (not current['unsupported'] or self.acknowledge.isChecked()))

    def accept(self):
        if not self.accept_button.isEnabled():
            return
        self.result_manifest = (self.current if self.all_structures.isChecked() else
            self.catalog.manifest(self.selected_ids(), self.supported,
                                  reviewed_unsupported=self.acknowledge.isChecked()))
        super().accept()
