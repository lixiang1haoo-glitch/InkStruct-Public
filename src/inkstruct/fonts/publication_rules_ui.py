"""Edit publication-scoped rule settings and preview a specific donor."""

from PySide6 import QtCore, QtWidgets

from ..symbol_review_dialog import InkPreview
from .publication_rules import DonorChoice, PublicationRules


class PublicationRulesDialog(QtWidgets.QDialog):
    def __init__(self, rows, evidence, settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("复用与合成规则")
        self.resize(1040, 650)
        self.rows = rows
        self.evidence = evidence
        self.disabled = set(settings.disabled)
        self.donors = {choice.target: choice for choice in settings.donors}
        layout = QtWidgets.QVBoxLayout(self)
        note = QtWidgets.QLabel("逐项决定本次是否启用。借用已有笔迹需先选用供体，已在采集任务中确认的供体可沿用。"
                                "应用后自动重新核对清单。设置仅用于当前制包窗口。")
        note.setWordWrap(True)
        layout.addWidget(note)
        search = QtWidgets.QLineEdit()
        search.setPlaceholderText("按字符、规则类型或结果筛选")
        layout.addWidget(search)
        self.table = table = QtWidgets.QTreeWidget()
        table.setObjectName("publication_rule_table")
        table.setRootIsDecorated(False)
        table.setHeaderLabels(["本次启用", "规则类型", "目标字符", "依赖来源", "供体确认", "已核对结果"])
        for column in range(5):
            table.header().setSectionResizeMode(column, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        table.header().setSectionResizeMode(5, QtWidgets.QHeaderView.ResizeMode.Stretch)
        layout.addWidget(table, 1)
        for index, row in enumerate(rows):
            item = QtWidgets.QTreeWidgetItem(table, ["", row.kind, row.target, row.source, row.donor_status, row.outcome])
            item.setData(0, QtCore.Qt.ItemDataRole.UserRole, index)
            item.setToolTip(5, row.outcome)
            if row.key[0] == "shared":
                full, _, half = row.target.split()
                item.setToolTip(2, f"全角 {full} U+{ord(full):04X} ↔ 半角 {half} U+{ord(half):04X}")
            if row.donor_character and row.key not in evidence.confirmed:
                item.setFlags(item.flags() & ~QtCore.Qt.ItemFlag.ItemIsUserCheckable)
                item.setText(0, "—" if row.outcome == "独立录制优先" else "先选供体")
            else:
                item.setCheckState(0, QtCore.Qt.Checked if row.enabled else QtCore.Qt.Unchecked)
        search.textChanged.connect(self.filter_rows)
        table.itemChanged.connect(self.rule_toggled)
        table.currentItemChanged.connect(self.update_donor_button)

        actions = QtWidgets.QHBoxLayout()
        self.donor_button = QtWidgets.QPushButton("预览并选用供体…")
        self.donor_button.setObjectName("publication_choose_donor")
        self.donor_button.clicked.connect(self.choose_donor)
        actions.addWidget(self.donor_button)
        actions.addStretch()
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.button(QtWidgets.QDialogButtonBox.Ok).setText("应用本次设置")
        buttons.button(QtWidgets.QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        actions.addWidget(buttons)
        layout.addLayout(actions)
        self.update_donor_button()

    def row(self, item):
        return self.rows[item.data(0, QtCore.Qt.ItemDataRole.UserRole)]

    def filter_rows(self, value):
        for i in range(self.table.topLevelItemCount()):
            item = self.table.topLevelItem(i)
            content = " ".join(item.text(column) for column in range(6))
            item.setHidden(value.strip() not in content)
        self.update_donor_button()

    def rule_toggled(self, item, column):
        if column != 0:
            return
        key = self.row(item).key
        if item.checkState(0) == QtCore.Qt.Checked:
            self.disabled.discard(key)
        else:
            self.disabled.add(key)
        self.pending_result(item)

    @staticmethod
    def pending_result(item):
        item.setText(5, "应用后重新核对")
        item.setToolTip(5, "")

    def update_donor_button(self, *_):
        item = self.table.currentItem()
        self.donor_button.setEnabled(bool(item and not item.isHidden()
                                          and self.evidence.donors.get(self.row(item).donor_character)))

    def choose_donor(self):
        item = self.table.currentItem()
        if item is None:
            return
        row = self.row(item)
        samples = self.evidence.donors.get(row.donor_character)
        if not samples:
            return
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("预览笔迹供体")
        dialog.resize(540, 390)
        layout = QtWidgets.QVBoxLayout(dialog)
        layout.addWidget(QtWidgets.QLabel(f"{row.target} ← {row.source}"))
        choices = QtWidgets.QComboBox()
        for index, sid in enumerate(sorted(samples), 1):
            choices.addItem(f"样本 {index} · {sid}", sid)
        if row.key in self.donors:
            selected = choices.findData(self.donors[row.key].sample_id)
            if selected >= 0:
                choices.setCurrentIndex(selected)
        layout.addWidget(choices)
        preview = InkPreview()
        layout.addWidget(preview, 1)

        def show_ink():
            preview.value = samples[choices.currentData()][1]
            preview.update()

        choices.currentIndexChanged.connect(show_ink)
        show_ink()
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.button(QtWidgets.QDialogButtonBox.Ok).setText("选用此供体并启用")
        buttons.button(QtWidgets.QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        accepted = dialog.exec() == QtWidgets.QDialog.Accepted
        sid = choices.currentData()
        dialog.deleteLater()
        if not accepted:
            return
        self.donors[row.key] = DonorChoice(row.key, sid, samples[sid][0])
        self.disabled.discard(row.key)
        with QtCore.QSignalBlocker(self.table):
            item.setText(0, "")
            item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(0, QtCore.Qt.Checked)
            item.setText(4, "本次已选用")
            self.pending_result(item)

    def settings(self):
        return PublicationRules(frozenset(self.disabled), tuple(self.donors[key] for key in sorted(self.donors)))
