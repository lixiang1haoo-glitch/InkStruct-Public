"""Font library and publication UI; generator inputs stay outside the package."""

from __future__ import annotations

from pathlib import Path

from PySide6 import QtCore, QtWidgets

from .core import FontPackage, to_user
from .library import entry, fingerprint, import_font, publish_font
from .management_ui import FontManagement
from .publication import (COVERAGE, GROUPS, batch_label, generated_batches, publication_stamp,
                          require_publication_stamp, review_selection)


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
        self.list = QtWidgets.QListWidget()
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
        hint = QtWidgets.QLabel("先选择书写者、汉字批次及扩展来源，再核对待制包清单。已确认的复用随原采集根目录或含任务配置的 ZIP 读取。")
        hint.setWordWrap(True)
        publication_layout.addWidget(hint)
        group = QtWidgets.QGroupBox("按书写者汇总的待制包清单")
        publication_layout.addWidget(group)
        self.publication_fields = group
        form = QtWidgets.QFormLayout(group)
        self.author = QtWidgets.QComboBox()
        self.author.setEditable(True)
        self.author.setInsertPolicy(QtWidgets.QComboBox.InsertPolicy.NoInsert)
        self.writer = self.author.lineEdit()
        self.writer.setPlaceholderText("选择采集书写者，或输入外部样本的作者 ID")
        self.author.activated.connect(self.author_chosen)
        self.writer.editingFinished.connect(self.author_chosen)
        self.publication_author = ""
        self.name = QtWidgets.QLineEdit("我的手写体")
        self.run = QtWidgets.QLineEdit()
        self.symbols = QtWidgets.QLineEdit()
        form.addRow("书写者 ID", self.author)
        form.addRow("字体名称", self.name)
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
        form.addRow("包类型", self.kind)
        self.review_button = QtWidgets.QPushButton("核对待制包清单")
        self.review_button.clicked.connect(self.review_publication)
        form.addRow(self.review_button)
        self.contents = QtWidgets.QTreeWidget()
        self.contents.setHeaderLabels(["加入 / 类别", "独立录制", "中英文共用", "已确认复用", "规则合成", "未通过校验"])
        self.contents.setMinimumHeight(140)
        self.contents.header().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        for column in range(1, self.contents.columnCount()):
            self.contents.header().setSectionResizeMode(column, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        self.contents.itemChanged.connect(self.publication_groups_changed)
        form.addRow(self.contents)
        self.coverage_summary = QtWidgets.QLabel("列中数字为字符数 / 候选份数。展开类别查看字符与诊断。")
        self.coverage_summary.setWordWrap(True)
        form.addRow(self.coverage_summary)
        b = QtWidgets.QPushButton("制作并加入字体库")
        self.build_button = b
        b.setProperty("inkRole", "primary")
        b.clicked.connect(self.build)
        form.addRow(b)
        self.buttons.append(b)
        note = QtWidgets.QLabel(
            "来源不完整的有效字形可以使用；排版时会汇总提示。开发者版包含供体信息，请按需要分享。"
        )
        note.setWordWrap(True)
        publication_layout.addWidget(note)
        close = QtWidgets.QPushButton("返回字体库")
        close.clicked.connect(self.publication.reject)
        publication_layout.addWidget(close)
        self.publication_progress = QtWidgets.QLabel()
        self.publication_progress.setWordWrap(True)
        publication_layout.addWidget(self.publication_progress)
        self.progress = QtWidgets.QLabel("")
        layout.addWidget(self.progress)
        self.progress.setWordWrap(True)
        for field in (self.writer, self.name, self.run, self.symbols):
            field.textChanged.connect(self.update_actions)
        self.review_timer = QtCore.QTimer(self, interval=150, singleShot=True)
        self.review_timer.timeout.connect(self.recalculate_publication)
        self.watch_timer = QtCore.QTimer(self, interval=1800)
        self.watch_timer.timeout.connect(self.watch_publication)
        self.watch_timer.start()
        self.list.currentItemChanged.connect(self.describe)
        self.setup_management()
        self.refresh()

    def open_publication(self):
        if self.job or self.review_job:
            return
        from ..capture_management import CaptureCatalog
        current = self.writer.text()
        with QtCore.QSignalBlocker(self.author):
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
        self.publication.show()
        self.publication.raise_()
        (self.name if current else self.writer).setFocus()

    def prepare_publication(self, run, writer):
        if self.job or self.review_job:
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
        self.run.clear()
        self.symbols.clear()
        self.refresh_publication_batches()
        if valid_writer(writer):
            if self.capture_root_provider:
                root = Path(self.capture_root_provider()) / "symbol_collection"
                if (root / "samples" / writer).is_dir():
                    self.symbols.setText(str(root))
        self.update_actions()

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

    def invalidate_publication(self, message=""):
        self.review = self.review_stamp = self.review_result = self.review_groups = None
        self.contents.clear()
        self.batch_summary.clear()
        self.batch_summary.hide()
        self.coverage_summary.setText("列中数字为字符数 / 候选份数。展开类别查看字符与诊断。")
        if message:
            self.set_progress(message)

    def review_publication(self):
        if self.job or self.review_job:
            return
        self.invalidate_publication()
        self.start_publication_review()

    def start_publication_review(self, groups=None):
        inputs = self.publication_inputs()
        writer, run, symbols, name = inputs
        reviewed_stamp = self.review_stamp

        def work(_):
            stamp = reviewed_stamp if reviewed_stamp is not None else publication_stamp(writer, run, symbols)
            require_publication_stamp(writer, run, symbols, stamp)
            result = review_selection(writer, run, symbols, name, groups)
            require_publication_stamp(writer, run, symbols, stamp)
            return inputs, stamp, groups, result

        job = self.review_job = Job(work)
        job.signals.completed.connect(self.publication_reviewed)
        job.signals.failed.connect(self.publication_review_failed)
        self.set_progress("正在按勾选计算覆盖…" if groups is not None else "正在核对作者、来源与可用字符…")
        self.update_actions()
        QtCore.QThreadPool.globalInstance().start(job)

    def publication_review_failed(self, error):
        self.review_job = None
        self.invalidate_publication("清单未通过：" + error)
        self.update_actions()

    def publication_reviewed(self, response):
        self.review_job = None
        inputs, stamp, groups, result = response
        if inputs != self.publication_inputs() or (groups is not None and self.review_stamp != stamp):
            self.update_actions()
            return
        self.review, self.review_stamp = inputs, stamp
        if groups is None:
            self.unselected_issues = {}
            for item in result["issues"]:
                self.unselected_issues.setdefault(item["group"], []).append(item)
            self.create_publication_rows(result)
            groups = self.selected_publication_groups()
            all_groups = {key[0] for key in result["coverage"]}
            if groups != all_groups:
                self.recalculate_publication()
                return
        if groups != self.selected_publication_groups():
            self.recalculate_publication()
            return
        self.review_groups, self.review_result = groups, result
        self.show_publication_coverage(result)
        self.set_progress("已核对当前勾选。汉字来源与包完整性在制包时核验。")
        self.update_actions()

    def create_publication_rows(self, result):
        available = {group for group, _, _ in result["coverage"]}
        invalid = {item["group"] for item in result["issues"] if item.get("invalid")}
        with QtCore.QSignalBlocker(self.contents):
            self.contents.clear()
            for key, label in {"han": "汉字", **GROUPS}.items():
                row = QtWidgets.QTreeWidgetItem(self.contents, [label])
                row.setData(0, QtCore.Qt.ItemDataRole.UserRole, key)
                if key in available or key in invalid:
                    row.setCheckState(0, QtCore.Qt.Checked if key in available and key not in invalid else QtCore.Qt.Unchecked)
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
        from ..symbol_tasks import TASK_GROUPS

        coverage, issues = result["coverage"], result["issues"]

        def details(row, label, characters):
            chars = sorted(set(characters))
            for i in range(0, len(chars), 24):
                text = " ".join(chars[i:i + 24])
                child = QtWidgets.QTreeWidgetItem(row, [label + " · " + text])
                child.setFirstColumnSpanned(True)
                child.setToolTip(0, label + " · " + text)

        with QtCore.QSignalBlocker(self.contents):
            for i in range(self.contents.topLevelItemCount()):
                row = self.contents.topLevelItem(i)
                key = row.data(0, QtCore.Qt.ItemDataRole.UserRole)
                row.takeChildren()
                checked = key in self.review_groups
                for column, kind in enumerate(("recorded", "shared", "reuse", "constructed"), 1):
                    counts = {char: value for (group, origin, char), value in coverage.items()
                              if group == key and origin == kind}
                    row.setText(column, f"{len(counts)} / {sum(counts.values())}" if checked else "—")
                    details(row, COVERAGE[kind], counts)
                group_issues = [item for item in issues if item["group"] == key]
                if not checked:
                    group_issues = self.unselected_issues.get(key, [])
                invalid = [item for item in group_issues if item.get("invalid")]
                row.setText(5, f"{len({item['target'] for item in invalid})} / {len(invalid)}" if invalid else "—")
                for item in group_issues:
                    text = f"{item['target']} · {item['reason']}"
                    if item.get("source"):
                        text += f" · {item['source']}"
                    child = QtWidgets.QTreeWidgetItem(row, [text])
                    child.setFirstColumnSpanned(True)
                    child.setToolTip(0, text)
                covered = {char for group, _, char in coverage if group == key}
                if checked and key in TASK_GROUPS:
                    details(row, "缺字", set(TASK_GROUPS[key][1]) - covered)
                if key == "han" and result["batch"]:
                    batch = result["batch"]
                    generated = sum(v for k, v in coverage.items() if k[0] == "han")
                    row.setText(0, f"汉字 · 生成 {len(covered)} 字 / {generated} 份" if checked else "汉字")
                    row.setText(1, "—")
                    row.setText(5, "制包时核验" if checked else "—")
                    details(row, "已完成范围", batch["characters"])
                    details(row, "失败", [item["character"] for item in batch["failed"]])
                    details(row, "未完成", batch["pending"])
        chars = len({key[2] for key in coverage})
        self.coverage_summary.setText(f"预计入包 {chars} 字 · {sum(coverage.values())} 份候选。列中为字符数 / 份数。展开查看缺字和来源诊断。")

    def publication_groups_changed(self, *_):
        self.review_result = None
        self.coverage_summary.setText("正在按勾选重新计算字符数与候选份数…")
        self.update_actions()
        self.review_timer.start()

    def recalculate_publication(self):
        if self.review and not self.review_job and not self.job:
            self.start_publication_review(self.selected_publication_groups())

    def watch_publication(self):
        if not self.publication.isVisible() or self.job or self.review_job or self.watch_job or self.review_stamp is None:
            return
        stamp, inputs = self.review_stamp, self.publication_inputs()

        def work(_):
            try:
                require_publication_stamp(*inputs[:3], stamp)
                return stamp, inputs, True
            except ValueError:
                return stamp, inputs, False

        self.watch_job = Job(work)
        self.watch_job.signals.completed.connect(self.publication_watched)
        self.watch_job.signals.failed.connect(self.publication_watch_failed)
        QtCore.QThreadPool.globalInstance().start(self.watch_job)

    def publication_watched(self, result):
        self.watch_job = None
        stamp, inputs, valid = result
        if not valid and self.review_stamp is stamp and self.publication_inputs() == inputs:
            self.invalidate_publication("批次、样本或复用配置已变化，请重新核对待制包清单。")
            self.update_actions()

    def publication_watch_failed(self, error):
        self.watch_job = None
        if not self.review_job and self.review:
            self.invalidate_publication("清单核对失败：" + error)
            self.update_actions()

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
        run, symbols = self.run.text().strip(), self.symbols.text().strip()
        inputs_ready = bool(run or symbols) and (not run or Path(run).is_dir()) and (
            not symbols or Path(symbols).exists())
        if self.review is not None and self.review != self.publication_inputs():
            self.invalidate_publication("输入已改变，请重新核对待制包清单。")
        idle = self.job is None and self.review_job is None
        self.review_button.setEnabled(idle and bool(self.writer.text().strip()) and inputs_ready)
        self.build_button.setEnabled(idle and self.review_result is not None and bool(self.name.text().strip())
                                     and bool(self.review_result["coverage"]))
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
                    if defaults.run and str(p.resolve()) == str(Path(defaults.run).resolve()):
                        title += ' · 新文档默认'
                    item = QtWidgets.QListWidgetItem(title)
                    item.setToolTip(full_title + ('\n内容版本 ' + summary['manifest']['font_version'] if summary else '') + '\n' + str(p))
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
        if self.review != inputs or self.review_result is None or self.review_groups != self.selected_publication_groups():
            return self.failed("请先核对待制包清单")
        writer, run, symbols, name = inputs
        kind, stamp = self.kind.currentData(), self.review_stamp
        groups, expected = self.review_groups, self.review_result["coverage"]

        def work(progress):
            result = publish_font(self.root, writer=writer, run=run, symbols=symbols, name=name,
                                  package_kind=kind, groups=groups, stamp=stamp, expected=expected,
                                  progress=progress)
            stats = result["verification"]
            actual, difference = result["coverage"], result["difference"]
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
