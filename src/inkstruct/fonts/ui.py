"""Font library and publication UI; generator inputs stay outside the package."""

from __future__ import annotations

from pathlib import Path

from PySide6 import QtCore, QtWidgets

from ..settings_pages import section
from ..symbol_catalog import SYMBOL_GROUPS, character_preview
from ..theme import set_tone
from ..ui_behavior import compact_field
from .core import FontPackage, to_user
from .library import entry, fingerprint, import_font, publish_font
from .management_ui import DEFAULT_FONT_LABEL, DEFAULT_FONT_ROLE, FontList, FontManagement
from .publication import (COVERAGE, GROUPS, PublicationInputsChanged, batch_label, display_coverage, generated_batches, publication_stamp,
                          require_publication_stamp, review_selection, rule_rows)
from .publication_rules import PublicationRules


class Signals(QtCore.QObject):
    completed = QtCore.Signal(object)
    failed = QtCore.Signal(str)
    progress = QtCore.Signal(str)


class Job(QtCore.QRunnable):
    def __init__(self, function):
        super().__init__()
        self.function = function
        self.signals = Signals()

    def run(self):
        try:
            self.signals.completed.emit(self.function(self.signals.progress.emit))
        except Exception as error:  # noqa: BLE001 - transport worker failures to UI
            self.signals.failed.emit(str(error))


class FontLibrary(FontManagement, QtWidgets.QWidget):
    use_requested = QtCore.Signal(str)

    def __init__(self, root):
        super().__init__()
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.job = None
        self.review_job = None
        self.review = None
        self.review_revision = 0
        self.attempted_review = None
        self.group_choices = {}
        self.rule_settings = PublicationRules()
        self.watch_job = None
        self.review_stamp = None
        self.review_result = None
        self.review_groups = None
        self.capture_root_provider = None
        self.last_result = None
        self.font_entries = {}
        layout = QtWidgets.QVBoxLayout(self)
        heading = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel("我的字体")
        title.setProperty("inkRole", "title")
        heading.addWidget(title)
        heading.addStretch()
        self.import_button = QtWidgets.QPushButton("导入字体…")
        self.import_button.setObjectName("font_import")
        self.import_button.clicked.connect(self.import_font)
        self.create_button = QtWidgets.QPushButton("制作字体…")
        self.create_button.setObjectName("font_create")
        self.create_button.clicked.connect(self.open_publication)
        heading.addWidget(self.import_button)
        heading.addWidget(self.create_button)
        layout.addLayout(heading)
        self.list = FontList()
        self.list.setObjectName("installed_fonts")
        self.list.setSpacing(6)
        layout.addWidget(self.list, 1)
        self.detail = QtWidgets.QLabel("还没有字体。可导入字体包，或从已完成的生成结果制作字体。")
        self.detail.setWordWrap(True)
        layout.addWidget(self.detail)
        actions = QtWidgets.QHBoxLayout()
        self.actions = actions
        layout.addLayout(actions)
        self.buttons = [self.import_button, self.create_button]
        self.selection_buttons = []
        for name, fn in [
            ("用于当前文档…", self.use),
            ("导出字体包…", self.export_user),
            ("完整验证", self.verify),
        ]:
            b = QtWidgets.QPushButton(name)
            b.clicked.connect(fn)
            actions.addWidget(b)
            self.buttons.append(b)
            self.selection_buttons.append(b)
        self.use_button = self.selection_buttons[0]
        self.use_button.setObjectName("font_use_document")
        self.use_button.setToolTip("先检查对当前文档的影响，再确认应用；不会自动重选旧文档的字形。")
        actions.addStretch()
        self.publication = QtWidgets.QDialog(self)
        self.publication.setWindowTitle("制作字体包")
        self.publication.setModal(True)
        self.publication.resize(940, 700)
        publication_layout = QtWidgets.QVBoxLayout(self.publication)
        hint = QtWidgets.QLabel("选择来源后自动核对。请勾选要入包的类别，并展开查看缺字。")
        hint.setWordWrap(True)
        publication_layout.addWidget(hint)
        group = QtWidgets.QWidget()
        self.source_toggle = section(publication_layout, "字体来源与包设置", group, expanded=True)
        self.source_toggle.setAccessibleName("展开或收起字体来源与包设置")
        self.publication_fields = group
        form = QtWidgets.QFormLayout(group)
        form.setContentsMargins(0, 0, 0, 0)
        form.setRowWrapPolicy(QtWidgets.QFormLayout.RowWrapPolicy.WrapLongRows)
        self.author = QtWidgets.QComboBox()
        self.author.setEditable(True)
        self.author.setInsertPolicy(QtWidgets.QComboBox.InsertPolicy.NoInsert)
        self.writer = self.author.lineEdit()
        self.writer.setPlaceholderText("选择采集书写者，或输入外部样本的作者 ID")
        self.publication_author = ""
        self.name = QtWidgets.QLineEdit("我的手写体")
        self.run = QtWidgets.QLineEdit()
        self.symbols = QtWidgets.QLineEdit()
        form.addRow("书写者 ID", compact_field(self.author, maximum=340))
        form.addRow("字体名称", compact_field(self.name, maximum=340))
        self.batches = QtWidgets.QComboBox()
        self.batches.activated.connect(lambda: self.run.setText(self.batches.currentData() or ""))
        self.run.textChanged.connect(self.sync_publication_batch)
        form.addRow("本地汉字批次", self.batches)
        self.batch_summary = QtWidgets.QLabel()
        self.batch_summary.setWordWrap(True)
        form.addRow(self.batch_summary)
        self.batch_summary.hide()
        for label, field, kind in [
            ("汉字生成目录", self.run, "dir"),
            ("标点与扩展来源", self.symbols, "symbol"),
        ]:
            row = QtWidgets.QHBoxLayout()
            row.addWidget(field)
            b = QtWidgets.QPushButton("添加标点与扩展样本…" if kind == "symbol" else "选择外部批次…")
            row.addWidget(b)
            b.clicked.connect(lambda checked=False, f=field, k=kind: self.choose(f, k))
            form.addRow(label, row)
        self.kind = QtWidgets.QComboBox()
        self.kind.addItem("用户版 · 用于排版与分享", "user")
        self.kind.addItem("开发者版 · 附来源详情", "developer")
        form.addRow("包类型", compact_field(self.kind))
        table_title = QtWidgets.QLabel("待制包清单")
        table_title.setProperty("inkRole", "sectionTitle")
        publication_layout.addWidget(table_title)
        self.contents = QtWidgets.QTreeWidget()
        self.contents.setAccessibleName("待制包清单")
        self.contents.setHeaderLabels(["加入 / 类别与字符", "独立录制", "同形共用", "规则合成", "未通过校验"])
        self.contents.setMinimumHeight(140)
        self.contents.header().setStretchLastSection(False)
        self.contents.header().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        for column in range(1, self.contents.columnCount()):
            self.contents.header().setSectionResizeMode(column, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        self.contents.itemChanged.connect(self.publication_groups_changed)
        publication_layout.addWidget(self.contents, 1)
        self.coverage_summary = QtWidgets.QLabel("列中数字为字符数 / 候选份数。展开类别查看字符与诊断。")
        self.coverage_summary.setWordWrap(True)
        coverage_row = QtWidgets.QHBoxLayout()
        coverage_row.addWidget(self.coverage_summary, 1)
        self.rules_button = QtWidgets.QPushButton("复用与合成规则…")
        self.rules_button.setAutoDefault(False)
        self.rules_button.clicked.connect(self.show_publication_rules)
        coverage_row.addWidget(self.rules_button)
        publication_layout.addLayout(coverage_row)
        note = QtWidgets.QLabel(
            "来源不完整的有效字形仍可使用。开发者版包含供体信息。"
        )
        note.setWordWrap(True)
        note.setProperty("inkRole", "hint")
        publication_layout.addWidget(note)
        self.publication_progress = QtWidgets.QLabel()
        self.publication_progress.setWordWrap(True)
        self.publication_progress.setProperty("inkRole", "status")
        publication_layout.addWidget(self.publication_progress)
        footer = QtWidgets.QHBoxLayout()
        footer.addStretch()
        close = QtWidgets.QPushButton("返回字体库")
        close.setAutoDefault(False)
        close.clicked.connect(self.publication.reject)
        footer.addWidget(close)
        self.build_button = QtWidgets.QPushButton("制作并加入字体库")
        self.build_button.setProperty("inkRole", "primary")
        self.build_button.setAutoDefault(False)
        self.build_button.clicked.connect(self.build)
        footer.addWidget(self.build_button)
        publication_layout.addLayout(footer)
        self.buttons.append(self.build_button)
        self.progress = QtWidgets.QLabel("")
        layout.addWidget(self.progress)
        self.progress.setWordWrap(True)
        self.writer.textChanged.connect(self.author_chosen)
        for field in (self.name, self.run):
            field.textChanged.connect(self.invalidate_publication)
        self.symbols.textChanged.connect(self.reset_publication_rules)
        self.publication.finished.connect(self.reset_publication_rules)
        self.review_timer = QtCore.QTimer(self, interval=150, singleShot=True)
        self.review_timer.timeout.connect(self.recalculate_publication)
        self.watch_timer = QtCore.QTimer(self, interval=1800)
        self.watch_timer.timeout.connect(self.watch_publication)
        self.watch_timer.start()
        self.list.currentItemChanged.connect(self.describe)
        self.setup_management()
        self.refresh()

    def open_publication(self):
        if self.job:
            return
        from ..capture_management import CaptureCatalog
        current = self.writer.text()
        with QtCore.QSignalBlocker(self.author), QtCore.QSignalBlocker(self.writer):
            self.author.clear()
            if self.capture_root_provider:
                try:
                    writers = CaptureCatalog(self.capture_root_provider()).writers()
                    self.author.addItems(sorted(writers))
                except (ValueError, OSError) as error:
                    self.set_progress(str(error))
            self.author.setEditText(current)
        self.author_chosen()
        self.refresh_publication_batches()
        self.source_toggle.setChecked(True)
        self.publication.show()
        self.publication.raise_()
        self.invalidate_publication()
        (self.name if current else self.writer).setFocus()

    def prepare_publication(self, run, writer):
        if self.job:
            return False
        self.writer.setText(writer)
        self.author_chosen()
        self.run.setText(str(run))
        self.name.setText(writer + " 手写体")
        self.open_publication()
        return True

    def author_chosen(self, *_):
        from ..capture_management import valid_writer

        writer = self.writer.text().strip()
        if writer == self.publication_author:
            return
        self.publication_author = writer
        self.rule_settings = PublicationRules()
        self.group_choices.clear()
        self.run.clear()
        self.symbols.clear()
        self.refresh_publication_batches()
        if valid_writer(writer):
            if self.capture_root_provider:
                root = Path(self.capture_root_provider()) / "symbol_collection"
                if (root / "samples" / writer).is_dir():
                    self.symbols.setText(str(root))
        self.invalidate_publication()

    def refresh_publication_batches(self):
        from ..capture_management import valid_writer

        writer = self.writer.text().strip()
        with QtCore.QSignalBlocker(self.batches):
            self.batches.clear()
            self.batches.addItem("未选本地批次", "")
            if valid_writer(writer):
                for label, path in generated_batches(self.root.parent / "generation" / "outputs", writer):
                    self.batches.addItem(label, str(path))
        self.sync_publication_batch(self.run.text())

    def sync_publication_batch(self, path):
        with QtCore.QSignalBlocker(self.batches):
            self.batches.setCurrentIndex(max(0, self.batches.findData(path)))

    def publication_inputs(self):
        return tuple(field.text().strip() for field in (self.writer, self.run, self.symbols, self.name))

    def publication_ready(self):
        from ..capture_management import valid_writer

        writer, run, symbols, _ = self.publication_inputs()
        return (valid_writer(writer) and bool(run or symbols)
                and (not run or Path(run).is_dir()) and (not symbols or Path(symbols).exists()))

    def reset_publication_rules(self, *_):
        self.rule_settings = PublicationRules()
        self.invalidate_publication()

    def invalidate_publication(self, *_):
        self.review_revision += 1
        self.review = self.review_stamp = self.review_result = self.review_groups = None
        with QtCore.QSignalBlocker(self.contents):
            self.contents.clear()
        self.batch_summary.clear()
        self.batch_summary.hide()
        self.review_timer.stop()
        if self.publication.isVisible():
            ready = self.publication_ready()
            self.publication_progress.setText("等待核对当前来源…" if ready else "制作前请选择书写者和至少一项可用来源。")
            set_tone(self.publication_progress, "")
            self.coverage_summary.setText("等待核对当前来源…" if ready
                                          else "选择书写者和可用的汉字批次或扩展来源。")
            self.review_timer.start()
        self.update_actions()

    def recalculate_publication(self):
        if (not self.publication.isVisible() or not self.publication_ready() or self.job
                or self.review_job or self.attempted_review == self.review_revision):
            return
        inputs = self.publication_inputs()
        writer, run, symbols, name = inputs
        revision = self.attempted_review = self.review_revision
        reviewed_stamp = self.review_stamp
        groups = self.selected_publication_groups() if self.review is not None else None
        rules = self.rule_settings

        def work(_):
            stamp = reviewed_stamp
            try:
                if stamp is None:
                    stamp = publication_stamp(writer, run, symbols)
                require_publication_stamp(writer, run, symbols, stamp)
                result = review_selection(writer, run, symbols, name, groups, rules=rules)
                require_publication_stamp(writer, run, symbols, stamp)
                return revision, inputs, stamp, groups, result, "", False
            except Exception as error:  # Carry the request identity with failures too.
                return revision, inputs, stamp, groups, None, str(error), isinstance(error, PublicationInputsChanged)

        job = self.review_job = Job(work)
        job.signals.completed.connect(self.publication_reviewed)
        self.coverage_summary.setText("正在按勾选计算覆盖…" if groups is not None else "正在核对作者、来源与可用字符…")
        self.publication_progress.setText("正在核对，完成后可制作。")
        set_tone(self.publication_progress, "")
        self.update_actions()
        QtCore.QThreadPool.globalInstance().start(job)

    def publication_reviewed(self, response):
        self.review_job = None
        revision, inputs, stamp, groups, result, error, changed = response
        if revision != self.review_revision or inputs != self.publication_inputs():
            self.update_actions()
            self.review_timer.start()
            return
        if changed:
            self.invalidate_publication()
            return
        self.review_stamp = stamp
        if result is None:
            self.coverage_summary.setText("清单核对失败：" + error)
            self.publication_progress.setText("制作前请处理清单中的核对错误。")
            set_tone(self.publication_progress, "danger")
            self.update_actions()
            return
        self.review = inputs
        if groups is None:
            self.unselected_issues = {}
            for item in result["issues"]:
                self.unselected_issues.setdefault(item["group"], []).append(item)
            self.create_publication_rows(result)
            groups = self.selected_publication_groups()
            all_groups = {key[0] for key in result["coverage"]}
            if groups != all_groups:
                self.review_revision += 1
                self.recalculate_publication()
                return
        self.review_groups, self.review_result = groups, result
        self.show_publication_coverage(result)
        if not self.name.text().strip():
            self.publication_progress.setText("请填写字体名称。")
        elif not result["coverage"]:
            self.publication_progress.setText("当前勾选没有可入包字形。")
        else:
            self.publication_progress.setText("已核对当前勾选。制包时验证汉字来源与包完整性。")
        set_tone(self.publication_progress, "")
        self.update_actions()

    def create_publication_rows(self, result):
        available = {group for group, _, _ in result["coverage"]}
        self.available_members = {}
        for group, _, char in result["coverage"]:
            self.available_members.setdefault(group, set()).add(char)
        invalid = {item["group"] for item in result["issues"] if item.get("invalid")}
        with QtCore.QSignalBlocker(self.contents):
            self.contents.clear()
            for key, label in {"han": "汉字", **GROUPS}.items():
                row = QtWidgets.QTreeWidgetItem(self.contents, [label])
                row.setData(0, QtCore.Qt.ItemDataRole.UserRole, key)
                if key in available or key in invalid or (key in SYMBOL_GROUPS and self.symbols.text().strip()):
                    checked = self.group_choices.get(key, key in available and key not in invalid)
                    row.setCheckState(0, QtCore.Qt.Checked if checked else QtCore.Qt.Unchecked)
                else:
                    row.setFlags(row.flags() & ~QtCore.Qt.ItemFlag.ItemIsUserCheckable)
                if key == "han":
                    row.setToolTip(0, self.run.text())
                else:
                    row.setToolTip(0, self.symbols.text())
        batch = result["batch"]
        external = batch is not None and self.batches.currentIndex() == 0
        self.batch_summary.setText(batch_label(batch) if external else "")
        self.batch_summary.setVisible(external)

    def show_publication_coverage(self, result):
        from collections import Counter, defaultdict

        coverage, issues = display_coverage(result["coverage"]), result["issues"]
        by_group = defaultdict(dict)
        for (group, kind, char), count in coverage.items():
            by_group[group].setdefault(char, Counter())[kind] += count
        origins = ("recorded", "shared", "constructed")

        def details(row, label, characters):
            chars = list(characters)
            for i in range(0, len(chars), 24):
                text = label + " · " + " ".join(chars[i:i + 24])
                child = QtWidgets.QTreeWidgetItem(row, [text])
                child.setFirstColumnSpanned(True)
                child.setToolTip(0, text)

        with QtCore.QSignalBlocker(self.contents):
            for i in range(self.contents.topLevelItemCount()):
                row = self.contents.topLevelItem(i)
                key = row.data(0, QtCore.Qt.ItemDataRole.UserRole)
                row.takeChildren()
                checked = key in self.review_groups
                available = by_group[key]
                if key == "han":
                    row.setText(0, "汉字")
                    row.setText(4, "制包时核验" if checked else "—")
                    batch = result["batch"]
                    if batch:
                        if checked:
                            row.setText(0, f"汉字 · 生成 {len(available)} 字 / {sum(v['generated'] for v in available.values())} 份")
                        details(row, "已完成范围", batch["characters"])
                        details(row, "失败", [item["character"] for item in batch["failed"]])
                        details(row, "未完成", batch["pending"])
                    continue
                group_issues = [item for item in issues if item["group"] == key] if checked else self.unselected_issues.get(key, [])
                by_char = defaultdict(list)
                for item in group_issues:
                    by_char[item["target"]].append(item)
                catalog = SYMBOL_GROUPS[key][1] if key in SYMBOL_GROUPS else ""
                known = self.available_members.get(key, set()) | set(available) | set(by_char)
                members = tuple(dict.fromkeys((*catalog, *sorted(known))))
                row.setText(0, GROUPS[key] + (" · " + character_preview(key, members) if members else ""))
                row.setToolTip(0, " ".join(members))
                for col, kind in enumerate(origins, 1):
                    counts = [v[kind] for v in available.values() if v[kind]]
                    row.setText(col, f"{len(counts)} / {sum(counts)}" if checked else "—")
                invalid = [item for item in group_issues if item.get("invalid")]
                row.setText(4, f"{len({item['target'] for item in invalid})} / {len(invalid)}" if invalid else "—")
                for char in members:
                    counts = available.get(char, Counter())
                    problems = by_char[char]
                    failed = sum(bool(item.get("invalid")) for item in problems)
                    selectable = row.flags() & QtCore.Qt.ItemFlag.ItemIsUserCheckable
                    status = ("未勾选" if not checked and selectable else f"可入包 · {sum(counts.values())} 份"
                              if counts else "未通过校验" if failed else "缺失")
                    child = QtWidgets.QTreeWidgetItem(row, [f"{char} · U+{ord(char):04X} · {status}",
                        *(str(counts[k]) if counts[k] else "—" for k in origins), str(failed) if failed else "—"])
                    if problems:
                        child.setToolTip(0, "\n".join(item["reason"] +
                            (f" · {item['source']}" if item.get("source") else "") for item in problems))
        chars = len({key[2] for key in coverage})
        self.coverage_summary.setText(f"预计入包 {chars} 个字符 · {sum(coverage.values())} 份候选。"
                                      "类别行显示字符数 / 候选份数，展开可查看每个字符。")

    def show_publication_rules(self):
        if not self.review_result:
            return
        from .publication_rules_ui import PublicationRulesDialog

        revision = self.review_revision
        result = self.review_result
        evidence = result["rule_evidence"]
        rows = rule_rows(result["coverage"], self.review_groups, evidence, result["issues"],
                         bool(self.symbols.text().strip()), self.rule_settings)
        dialog = PublicationRulesDialog(rows, evidence, self.rule_settings, self.publication)
        accepted = dialog.exec() == QtWidgets.QDialog.Accepted
        settings = dialog.settings()
        dialog.deleteLater()
        if not accepted:
            return
        if revision != self.review_revision:
            self.publication_progress.setText("来源已变化。请重新打开规则窗口核对供体。")
            return
        if settings != self.rule_settings:
            self.rule_settings = settings
            self.invalidate_publication()

    def publication_groups_changed(self, item, column):
        if column != 0 or item.parent() is not None:
            return
        key = item.data(0, QtCore.Qt.ItemDataRole.UserRole)
        self.group_choices[key] = item.checkState(0) == QtCore.Qt.Checked
        self.review_revision += 1
        self.review_result = None
        self.coverage_summary.setText("正在按勾选重新计算字符数与候选份数…")
        self.update_actions()
        self.review_timer.start()

    def watch_publication(self):
        if not self.publication.isVisible() or self.job or self.review_job or self.watch_job:
            return
        if self.review_stamp is None:
            self.recalculate_publication()
            return
        stamp, inputs = self.review_stamp, self.publication_inputs()

        def work(_):
            try:
                require_publication_stamp(*inputs[:3], stamp)
                return stamp, True
            except (ValueError, OSError):
                return stamp, False

        self.watch_job = Job(work)
        self.watch_job.signals.completed.connect(self.publication_watched)
        QtCore.QThreadPool.globalInstance().start(self.watch_job)

    def publication_watched(self, result):
        self.watch_job = None
        stamp, valid = result
        if not valid and self.review_stamp is stamp:
            self.invalidate_publication()
            self.publication_progress.setText("来源已变化，正在重新核对清单…")

    def selected_publication_groups(self):
        return {row.data(0, QtCore.Qt.ItemDataRole.UserRole)
                for i in range(self.contents.topLevelItemCount())
                if (row := self.contents.topLevelItem(i)).checkState(0) == QtCore.Qt.Checked}

    def update_actions(self):
        for button in self.buttons:
            button.setEnabled(self.job is None)
        selected = self.list.currentItem() is not None
        for button in self.selection_buttons:
            button.setEnabled(self.job is None and selected)
        if selected and hasattr(self, 'catalog'):
            data = self.catalog.get(self.selected().name, {})
            if data.get('archived') or data.get('error') or not self.selected().is_file():
                for button in self.selection_buttons:
                    button.setEnabled(False)
        if hasattr(self, 'more_button'):
            self.more_button.setEnabled(self.job is None)
            self.folder_action.setEnabled(self.job is None and selected)
            self.rename_action.setEnabled(self.job is None and selected)
            self.archive_action.setEnabled(self.job is None and selected)
        # Keep one main action; the same browser also serves the font picker.
        for button, primary in ((self.import_button, not self.use_button.isEnabled()),
                                (self.use_button, self.use_button.isEnabled())):
            role = 'primary' if primary else ''
            if button.property('inkRole') != role:
                button.setProperty('inkRole', role)
                button.style().unpolish(button)
                button.style().polish(button)
        idle = self.job is None and self.review_job is None
        self.build_button.setEnabled(idle and self.review_result is not None and bool(self.name.text().strip())
                                     and bool(self.review_result["coverage"]))
        self.rules_button.setEnabled(idle and self.review_result is not None)
        self.publication_fields.setEnabled(self.job is None)
        self.contents.setEnabled(self.review is not None and self.job is None)

    def set_progress(self, message):
        self.progress.setText(message)
        self.publication_progress.setText(message)

    def selected(self):
        item = self.list.currentItem()
        if not item:
            raise ValueError("请先选择字体")
        return Path(item.data(QtCore.Qt.ItemDataRole.UserRole))

    def choose(self, field, kind):
        if kind == "dir":
            path = QtWidgets.QFileDialog.getExistingDirectory(self, "选择生成结果目录")
        else:
            box = QtWidgets.QMessageBox(self)
            box.setWindowTitle("符号样本")
            box.setText("选择 ZIP 包或采集目录")
            z = box.addButton("ZIP 包", QtWidgets.QMessageBox.ButtonRole.AcceptRole)
            d = box.addButton("采集目录", QtWidgets.QMessageBox.ButtonRole.ActionRole)
            box.addButton(QtWidgets.QMessageBox.StandardButton.Cancel)
            box.exec()
            if box.clickedButton() == z:
                path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "符号样本", "", "ZIP (*.zip)")
            elif box.clickedButton() == d:
                path = QtWidgets.QFileDialog.getExistingDirectory(self, "符号采集目录")
            else:
                return
        if path:
            field.setText(path)

    def submit(self, fn):
        if self.job:
            return
        self.job = Job(fn)
        self.update_actions()
        self.set_progress("正在处理字体…")
        self.job.signals.progress.connect(self.set_progress)
        self.job.signals.completed.connect(self.completed)
        self.job.signals.failed.connect(self.failed)
        QtCore.QThreadPool.globalInstance().start(self.job)

    def completed(self, result):
        self.last_result = result
        self.job = None
        target = result.get("path") if isinstance(result, dict) else None
        if isinstance(result, dict) and result.get('default_ready'):
            try:
                from dataclasses import replace

                from ..global_defaults import GlobalDefaultsStore
                if fingerprint(target) != result['stamp']:
                    raise ValueError('字体在验证后发生变化，默认设置未改变')
                store = GlobalDefaultsStore()
                defaults, warning = store.load()
                if warning:
                    raise ValueError(warning)
                store.save(replace(defaults, run=str(Path(target).resolve()), symbols='', mode='markdown'))
            except (ValueError, OSError) as error:
                self.failed(str(error))
                return
        if target and 'entry' in result:
            self.font_entries[str(Path(target))] = result['entry']
        if target and ('verification' in result or result.get('published') or result.get('verified')):
            try:
                self.management.update(Path(target).name, verified_stamp=list(fingerprint(target)))
                self.catalog.setdefault(Path(target).name, {})['verified_stamp'] = list(fingerprint(target))
            except (OSError, ValueError) as error:
                self.catalog_error = str(error)
        self.refresh(target)
        self.set_progress(result["message"] if isinstance(result, dict) else str(result))
        self.update_actions()
        if isinstance(result, dict) and result.get("published"):
            self.publication.accept()

    def failed(self, message):
        self.job = None
        if "请重新核对待制包清单" in message:
            self.invalidate_publication()
        self.update_actions()
        self.set_progress("未完成：" + message)
        QtWidgets.QMessageBox.warning(self, "字体操作未完成", message)

    def refresh(self, selected_path=None):
        try:
            self.catalog = self.management.read()
        except (ValueError, OSError) as error:
            self.catalog_error = str(error)
        if selected_path is None and self.list.currentItem():
            selected_path = str(self.selected())
        present = set()
        from ..global_defaults import GlobalDefaultsStore
        defaults, _ = GlobalDefaultsStore().load()
        with QtCore.QSignalBlocker(self.list):
            self.list.clear()
            paths = set(self.root.glob('*.inkfont')) | {self.root/name for name in self.catalog
                       if Path(name).name == name and name.endswith('.inkfont')}
            for p in sorted(paths):
                try:
                    full_title, _ = self.describe_font(p)
                    present.add(str(p))
                    data = self.catalog.get(p.name, {})
                    summary = self.metadata_for(p)
                    title = data.get('alias') or (summary['manifest']['name'] if summary else p.stem)
                    if data.get('error'):
                        title += ' · 不可读取'
                    if data.get('archived'):
                        title += ' · 已移出'
                    item = QtWidgets.QListWidgetItem(title)
                    tooltip = full_title + ('\n内容版本 ' + summary['manifest']['font_version'] if summary else '') + '\n' + str(p)
                    if defaults.run and p.resolve() == Path(defaults.run).resolve():
                        item.setData(DEFAULT_FONT_ROLE, True)
                        item.setData(QtCore.Qt.ItemDataRole.AccessibleDescriptionRole, DEFAULT_FONT_LABEL)
                        tooltip = DEFAULT_FONT_LABEL + '\n' + tooltip
                    item.setToolTip(tooltip)
                    item.setData(QtCore.Qt.ItemDataRole.UserRole, str(p))
                    self.list.addItem(item)
                except (ValueError, OSError, KeyError) as error:
                    item = QtWidgets.QListWidgetItem(p.stem + ' · 不可读取')
                    item.setToolTip(str(p) + '\n' + str(error))
                    item.setData(QtCore.Qt.ItemDataRole.UserRole, str(p))
                    self.list.addItem(item)
            if self.list.count():
                row = next((i for i in range(self.list.count()) if
                    self.list.item(i).data(QtCore.Qt.ItemDataRole.UserRole) == str(selected_path)), 0)
                self.list.setCurrentRow(row)
        self.font_entries = {p: value for p, value in self.font_entries.items() if p in present}
        self.describe()
        self.update_actions()
        with QtCore.QSignalBlocker(self.writer_filter):
            selected_writer = self.writer_filter.currentData()
            self.writer_filter.clear()
            self.writer_filter.addItem('全部书写者', '')
            writers = sorted({s['summary']['manifest']['writer_alias'] for s in self.catalog.values() if s.get('summary')})
            for writer in writers:
                self.writer_filter.addItem(writer, writer)
            self.writer_filter.setCurrentIndex(max(0, self.writer_filter.findData(selected_writer)))
        self.filter_fonts()
        self.load_metadata()

    def describe_font(self, path):
        key, stamp = str(path), fingerprint(path)
        cached = self.font_entries.get(key)
        if cached is None or cached[0] != stamp:
            summary = self.metadata_for(path)
            if summary:
                cached = (stamp, summary['title'], summary['detail'])
                self.font_entries[key] = cached
            else:
                error = self.catalog.get(Path(path).name, {}).get('error')
                return Path(path).stem + (' · 不可读取' if error else ' · 正在读取摘要…'), error or '摘要尚未载入'
        return cached[1:]

    def describe(self, *args):
        try:
            path = self.selected()
            if getattr(self, '_inspection_path', None) != str(path):
                self.clear_font_details()
                self._inspection_path = str(path)
            error = self.catalog.get(path.name, {}).get('error')
            if error:
                raise ValueError(error)
            self.detail.setText(self.describe_font(self.selected())[1])
            self.detail_stack.setCurrentWidget(self.details_tabs)
            self.update_management(self.selected())
        except (ValueError, OSError, KeyError) as error:
            self.clear_font_details()
            if self.list.currentItem():
                self.show_font_message('字体暂不可读取', str(error) + '\n原文件和管理记录保留，可从“更多操作”刷新列表后重试。')
            else:
                self.show_unselected_font()
        self.update_actions()

    def import_font(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "导入字体", "", "InkStruct 字体 (*.inkfont)"
        )
        if not path:
            return

        def work(progress):
            return import_font(path, self.root, progress)

        self.submit(work)

    def build(self):
        inputs = self.publication_inputs()
        if not self.build_button.isEnabled() or self.review != inputs or self.review_groups != self.selected_publication_groups():
            return
        writer, run, symbols, name = inputs
        kind, stamp = self.kind.currentData(), self.review_stamp
        groups, expected = self.review_groups, self.review_result["coverage"]
        rules = self.rule_settings

        def work(progress):
            result = publish_font(self.root, writer=writer, run=run, symbols=symbols, name=name,
                                  package_kind=kind, groups=groups, stamp=stamp, expected=expected,
                                  progress=progress, rules=rules)
            stats = result["verification"]
            actual, difference = display_coverage(result["coverage"]), result["difference"]
            lines = [f"字体已验证并入库 · {stats['characters']} 字，{stats['candidates']} 份候选"]
            for origin, label in COVERAGE.items():
                counts = [(key[2], count) for key, count in actual.items() if key[1] == origin]
                if counts:
                    lines.append(f"{label} {len({char for char, _ in counts})} 字 / {sum(n for _, n in counts)} 份")
            if difference:
                changes = "、".join(f"{char} {delta:+} 份" for (_, _, char), delta in sorted(difference.items())[:24])
                lines.append("与待制包清单的差异 · " + changes + ("…" if len(difference) > 24 else ""))
            else:
                lines.append("实际覆盖与待制包清单一致。")
            lines.append(" · ".join(f"{label} {seconds:.2f} 秒" for label, seconds in result["timings"].items()))
            if result["log"]:
                lines.append("入包明细与阶段记录：" + result["log"])
            result["message"] = "\n".join(lines)
            return result

        self.submit(work)

    def use(self):
        try:
            self.use_requested.emit(str(self.selected()))
        except ValueError as e:
            self.failed(str(e))

    def verify(self):
        try:
            path = self.selected()
        except ValueError:
            return
        def work(progress):
            stats = FontPackage(path, verify_all=False).verify(progress=progress)
            return {'path': str(path), 'verified': True, 'message': '完整验证通过：' + str(stats)}
        self.submit(work)

    def export_user(self):
        try:
            source = self.selected()
        except ValueError:
            return
        kind, ok = QtWidgets.QInputDialog.getItem(self, '导出字体包', '用户版用于排版与分享；完整副本保留原包的全部来源资料。',
                                                 ['用户版', '完整副本（保留原包类型）'], 0, False)
        if not ok:
            return
        summary = self.metadata_for(source)
        name = (summary['manifest']['name'] + '-' + summary['manifest']['font_version']) if summary else source.stem
        for char in '<>:"/\\|?*':
            name = name.replace(char, '_')
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, '导出字体包（不覆盖已有文件）', name+'.inkfont', 'InkStruct 字体 (*.inkfont)')
        if path:
            def export(progress):
                if kind == '用户版':
                    to_user(source, path)
                else:
                    import shutil
                    FontPackage(source, verify_all=False).verify(progress=progress)
                    with source.open('rb') as original, Path(path).open('xb') as destination:
                        shutil.copyfileobj(original, destination)
                return '已导出，核心字形与选择身份保持不变'
            self.submit(
                export
            )
