"""Font library and publication UI; generator inputs stay outside the package."""

from __future__ import annotations

from pathlib import Path

from PySide6 import QtCore, QtWidgets

from .core import FontPackage, to_user
from .importer import build_font
from .library import entry, fingerprint, import_font
from .management_ui import FontManagement


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
        self.last_result = None
        self.font_entries = {}
        layout = QtWidgets.QVBoxLayout(self)
        heading = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel("我的字体")
        title.setStyleSheet("font-size: 20px; font-weight: 600")
        heading.addWidget(title)
        heading.addStretch()
        self.import_button = QtWidgets.QPushButton("导入字体…")
        self.import_button.clicked.connect(self.import_font)
        self.create_button = QtWidgets.QPushButton("制作字体…")
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
        actions.addStretch()
        self.publication = QtWidgets.QDialog(self)
        self.publication.setWindowTitle("制作字体")
        self.publication.setModal(True)
        self.publication.resize(620, 380)
        publication_layout = QtWidgets.QVBoxLayout(self.publication)
        hint = QtWidgets.QLabel("将完成的字形与可选符号样本封装为字体，不会重新生成字形。中英文共用标点无需分别补采。使用已确认的斜体／希腊字符复用时，请选择包含 tasks 和 samples 的完整 symbol_collection 目录或 ZIP；仅选择 samples 不含复用配置。")
        hint.setWordWrap(True)
        publication_layout.addWidget(hint)
        group = QtWidgets.QGroupBox("字体信息与内容")
        publication_layout.addWidget(group)
        self.publication_fields = group
        form = QtWidgets.QFormLayout(group)
        self.writer = QtWidgets.QLineEdit()
        self.name = QtWidgets.QLineEdit("我的手写体")
        self.run = QtWidgets.QLineEdit()
        self.symbols = QtWidgets.QLineEdit()
        form.addRow("书写者 ID", self.writer)
        form.addRow("字体名称", self.name)
        for label, field, kind in [
            ("生成结果", self.run, "dir"),
            ("符号样本 ZIP / 目录", self.symbols, "symbol"),
        ]:
            row = QtWidgets.QHBoxLayout()
            row.addWidget(field)
            b = QtWidgets.QPushButton("选择…")
            row.addWidget(b)
            b.clicked.connect(lambda checked=False, f=field, k=kind: self.choose(f, k))
            form.addRow(label, row)
        self.kind = QtWidgets.QComboBox()
        self.kind.addItem("用户版 · 用于排版与分享", "user")
        self.kind.addItem("开发者版 · 附来源详情", "developer")
        form.addRow("包类型", self.kind)
        b = QtWidgets.QPushButton("制作并加入字体库")
        self.build_button = b
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
        self.list.currentItemChanged.connect(self.describe)
        self.setup_management()
        self.refresh()

    def open_publication(self):
        if self.job:
            return
        self.publication.show()
        self.publication.raise_()
        self.name.setFocus()
        self.name.selectAll()

    def prepare_publication(self, run, writer):
        if self.job:
            return False
        # Do not accidentally attach another author's symbol samples.
        if self.writer.text().strip() != writer:
            self.symbols.clear()
        self.writer.setText(writer)
        self.run.setText(str(run))
        self.name.setText(writer + " 手写体")
        self.open_publication()
        return True

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
        run, symbols = self.run.text().strip(), self.symbols.text().strip()
        inputs_ready = bool(run or symbols) and (not run or Path(run).is_dir()) and (
            not symbols or Path(symbols).exists())
        self.build_button.setEnabled(self.job is None and bool(self.writer.text().strip())
            and bool(self.name.text().strip()) and inputs_ready)
        self.publication_fields.setEnabled(self.job is None)

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
                    title, _ = self.describe_font(p)
                    present.add(str(p))
                    data = self.catalog.get(p.name, {})
                    summary = self.metadata_for(p)
                    prefix = data.get('alias')
                    if prefix and summary:
                        title = prefix + ' · ' + summary['manifest']['writer_alias']
                    if summary:
                        title += '\n内容版本 ' + summary['manifest']['font_version']
                    if data.get('archived'):
                        title += ' · 已移出'
                    if defaults.run and str(p.resolve()) == str(Path(defaults.run).resolve()):
                        title += ' · 新文档默认'
                    item = QtWidgets.QListWidgetItem(title)
                    item.setData(QtCore.Qt.ItemDataRole.UserRole, str(p))
                    self.list.addItem(item)
                except (ValueError, OSError, KeyError) as error:
                    item = QtWidgets.QListWidgetItem(p.name + '\n不可读取：' + str(error))
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
                self._inspection_path = str(path)
                self.ink_preview.load(b'<svg xmlns="http://www.w3.org/2000/svg"/>')
                self.sample_count.clear()
                self.version_info.clear()
                self.version_list.clear()
                self.file_info.clear()
                self.character_preview.load(b'<svg xmlns="http://www.w3.org/2000/svg"/>')
            self.detail.setText(self.describe_font(self.selected())[1])
            self.update_management(self.selected())
        except (ValueError, OSError, KeyError) as error:
            self.detail.setText(('资源不可读取，记录保留：' + str(error)) if self.list.currentItem() else
                                '还没有字体。可导入字体包，或从已完成的生成结果制作字体。')
            if hasattr(self, 'ink_preview'):
                self.inspection_epoch += 1
                self.ink_preview.load(b'<svg xmlns="http://www.w3.org/2000/svg"/>')
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
        writer = self.writer.text().strip()
        name = self.name.text().strip()
        run = self.run.text().strip()
        symbols = self.symbols.text().strip()
        kind = self.kind.currentData()
        if not writer or not name:
            return self.failed("请填写书写者和字体名称")
        import uuid

        path = self.root / (str(uuid.uuid4()) + ".inkfont")

        def work(progress):
            build_font(
                path,
                writer=writer,
                name=name,
                run=run or None,
                symbols=symbols or None,
                package_kind=kind,
                progress=progress,
            )
            font = FontPackage(path, verify_all=False)
            stats = font.verify(progress=progress)
            return {"path": str(path), "published": True, "entry": (fingerprint(path), *entry(font)), "message": f"字体已发布并验证 · {stats['characters']} 字，{stats['candidates']} 份候选"}

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
