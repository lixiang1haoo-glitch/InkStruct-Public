"""Edit publication-scoped rule settings and preview a specific donor."""

from PySide6 import QtCore, QtWidgets

from ..symbol_review_dialog import InkPreview
from .publication_rules import DonorChoice, PublicationRules, SHARED_FAMILIES


class PublicationRulesDialog(QtWidgets.QDialog):
    def __init__(self, rows, evidence, settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("复用与合成规则")
        self.resize(1040, 650)
        self.rows = rows
        self.evidence = evidence
        self.disabled = set(settings.disabled)
        self.enabled = set(settings.enabled)
        self.families = dict(settings.families)
        self.donors = {choice.target: choice for choice in settings.donors}
        layout = QtWidgets.QVBoxLayout(self)
        note = QtWidgets.QLabel("同形共用启用后自动补缺，独立录制优先。可整组启停，也可展开逐项覆盖。"
                                "已有指定供体优先，只有想指定某份笔迹时才需打开预览。设置仅用于当前制包窗口。")
        note.setWordWrap(True)
        layout.addWidget(note)
        search = QtWidgets.QLineEdit()
        search.setPlaceholderText("按字符、规则类型或结果筛选")
        layout.addWidget(search)
        self.table = table = QtWidgets.QTreeWidget()
        table.setObjectName("publication_rule_table")
        table.setHeaderLabels(["本次启用", "规则类型", "目标字符", "依赖来源", "供体选择", "已核对结果"])
        for column in range(5):
            table.header().setSectionResizeMode(column, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        table.header().setSectionResizeMode(5, QtWidgets.QHeaderView.ResizeMode.Stretch)
        layout.addWidget(table, 1)
        self.groups = {}
        for key, label in SHARED_FAMILIES.items():
            group = QtWidgets.QTreeWidgetItem(table, ["", "同形共用", label])
            group.setData(0, QtCore.Qt.ItemDataRole.UserRole, key)
            group.setFlags(group.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
            self.groups[key] = group
        construction = QtWidgets.QTreeWidgetItem(table, ["", "规则合成"])
        self.items = {}
        for index, row in enumerate(rows):
            parent = self.groups.get(row.key[0], construction)
            item = QtWidgets.QTreeWidgetItem(parent, ["", row.kind, row.target, row.source, row.donor_status, row.outcome])
            self.items[row.key] = item
            item.setData(0, QtCore.Qt.ItemDataRole.UserRole, index)
            item.setToolTip(5, row.outcome)
            if row.key[0] == "shared":
                full, _, half = row.target.split()
                item.setToolTip(2, f"全角 {full} U+{ord(full):04X} ↔ 半角 {half} U+{ord(half):04X}")
            item.setCheckState(0, QtCore.Qt.Checked if row.enabled else QtCore.Qt.Unchecked)
        for key in self.groups:
            self.update_group_check(key)
        search.textChanged.connect(self.filter_rows)
        table.itemChanged.connect(self.rule_toggled)
        table.currentItemChanged.connect(self.update_donor_button)

        actions = QtWidgets.QHBoxLayout()
        self.donor_button = QtWidgets.QPushButton("预览并指定供体…")
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
        index = item.data(0, QtCore.Qt.ItemDataRole.UserRole)
        return self.rows[index] if isinstance(index, int) else None

    def filter_rows(self, value):
        query = value.strip()
        for i in range(self.table.topLevelItemCount()):
            group = self.table.topLevelItem(i)
            parent_match = any(query in group.text(column) for column in (1, 2))
            visible = 0
            for j in range(group.childCount()):
                item = group.child(j)
                content = " ".join(item.text(column) for column in range(6))
                shown = parent_match or query in content
                item.setHidden(not shown)
                visible += shown
            group.setHidden(not visible)
            if query and visible:
                group.setExpanded(True)
        self.update_donor_button()

    def update_group_check(self, key):
        group = self.groups.get(key)
        if group is None:
            return
        states = {group.child(i).checkState(0) for i in range(group.childCount())}
        state = states.pop() if len(states) == 1 else QtCore.Qt.PartiallyChecked
        with QtCore.QSignalBlocker(self.table):
            group.setCheckState(0, state)

    def rule_toggled(self, item, column):
        if column != 0:
            return
        data = item.data(0, QtCore.Qt.ItemDataRole.UserRole)
        checked = item.checkState(0) == QtCore.Qt.Checked
        if data in self.groups:
            self.families[data] = checked
            with QtCore.QSignalBlocker(self.table):
                for i in range(item.childCount()):
                    child = item.child(i)
                    key = self.row(child).key
                    self.enabled.discard(key)
                    self.disabled.discard(key)
                    child.setCheckState(0, QtCore.Qt.Checked if checked else QtCore.Qt.Unchecked)
                    self.pending_result(child)
        elif (row := self.row(item)) is not None:
            on, off = (self.enabled, self.disabled) if checked else (self.disabled, self.enabled)
            on.add(row.key)
            off.discard(row.key)
            self.update_group_check(row.key[0])
            self.pending_result(item)

    @staticmethod
    def pending_result(item):
        item.setText(5, "应用后重新核对")
        item.setToolTip(5, "")

    def update_donor_button(self, *_):
        item = self.table.currentItem()
        row = self.row(item) if item is not None else None
        self.donor_button.setEnabled(bool(row and not item.isHidden()
                                          and self.evidence.donors.get(row.donor_character)))

    def choose_donor(self):
        item = self.table.currentItem()
        if item is None:
            return
        row = self.row(item)
        samples = self.evidence.donors.get(row.donor_character) if row else None
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
        buttons.button(QtWidgets.QDialogButtonBox.Ok).setText("指定此供体并启用")
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
        self.enabled.add(row.key)
        with QtCore.QSignalBlocker(self.table):
            item.setText(0, "")
            item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(0, QtCore.Qt.Checked)
            item.setText(4, "本次指定")
            self.pending_result(item)
        self.update_group_check(row.key[0])

    def settings(self):
        return PublicationRules(frozenset(self.disabled), tuple(self.donors[key] for key in sorted(self.donors)),
                                frozenset(self.enabled), tuple(sorted(self.families.items())))
