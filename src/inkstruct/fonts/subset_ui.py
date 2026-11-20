"""Choose a portable subset without creating a widget for every candidate."""
from collections import defaultdict

from PySide6 import QtCore, QtWidgets

from .core import FontPackage
from .exchange_codec import MAX_CANDIDATES, valid_character
from .library import fingerprint


def subset_choices(source):
    font = FontPackage(source, verify_all=False)
    choices = defaultdict(list)
    for row in font.records:
        cid, char = row["candidate_id"], row["character"]
        if (row["enabled"] and valid_character(char)
                and font.provenance[cid]["review_status"] not in {"needs_review", "rejected"}):
            choices[char].append((cid, row["letter_style"]))
    return {"source": source, "name": font.manifest["name"], "stamp": fingerprint(source),
            "subset_choices": dict(choices)}


class SubsetDialog(QtWidgets.QDialog):
    def __init__(self, choices, parent=None):
        super().__init__(parent)
        self.setWindowTitle("选择通用 v1 副本的候选")
        self.resize(620, 470)
        self.choices, self.selected = choices, set()
        layout = QtWidgets.QVBoxLayout(self)
        search = QtWidgets.QLineEdit()
        search.setPlaceholderText("查找字符")
        layout.addWidget(search)
        row = QtWidgets.QHBoxLayout()
        layout.addLayout(row, 1)
        self.chars, self.candidates = QtWidgets.QListWidget(), QtWidgets.QListWidget()
        row.addWidget(self.chars, 1)
        row.addWidget(self.candidates, 3)
        actions = QtWidgets.QHBoxLayout()
        layout.addLayout(actions)
        for title, func in (("每字每种字形各选一份", self.one_per_style), ("清空选择", self.clear)):
            button = QtWidgets.QPushButton(title)
            button.clicked.connect(func)
            actions.addWidget(button)
        self.count = QtWidgets.QLabel()
        layout.addWidget(self.count)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        self.next_button = buttons.addButton("继续导出…", QtWidgets.QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.chars.addItems(sorted(choices))
        self.chars.currentTextChanged.connect(self.show_character)
        self.candidates.itemChanged.connect(self.toggle)
        search.textChanged.connect(self.filter)
        self.chars.setCurrentRow(0)
        self.update_count()

    def filter(self, text):
        first = None
        for index in range(self.chars.count()):
            item = self.chars.item(index)
            show = not text or item.text() in text
            item.setHidden(not show)
            if show and first is None:
                first = item
        self.chars.setCurrentItem(first)

    def show_character(self, char):
        styles = {"upright": "正体", "italic": "斜体", "unspecified": "未注明字形"}
        with QtCore.QSignalBlocker(self.candidates):
            self.candidates.clear()
            for i, (cid, style) in enumerate(self.choices.get(char, ()), 1):
                item = QtWidgets.QListWidgetItem(f"{char} · 候选 {i} · {styles.get(style, '常规')} · {cid[:8]}")
                item.setToolTip(cid)
                item.setData(QtCore.Qt.ItemDataRole.UserRole, cid)
                item.setCheckState(QtCore.Qt.CheckState.Checked if cid in self.selected else QtCore.Qt.CheckState.Unchecked)
                self.candidates.addItem(item)

    def one_per_style(self):
        self.selected.clear()
        for records in self.choices.values():
            seen = set()
            for cid, style in records:
                if style not in seen:
                    self.selected.add(cid)
                    seen.add(style)
        self.show_character(self.chars.currentItem().text() if self.chars.currentItem() else "")
        self.update_count()

    def clear(self):
        self.selected.clear()
        self.show_character(self.chars.currentItem().text() if self.chars.currentItem() else "")
        self.update_count()

    def toggle(self, item):
        cid = item.data(QtCore.Qt.ItemDataRole.UserRole)
        if item.checkState() == QtCore.Qt.CheckState.Checked:
            self.selected.add(cid)
        else:
            self.selected.discard(cid)
        self.update_count()

    def update_count(self):
        count = len(self.selected)
        self.count.setText(f"已选 {count:,} / {MAX_CANDIDATES:,} 份候选")
        self.next_button.setEnabled(0 < count <= MAX_CANDIDATES)
