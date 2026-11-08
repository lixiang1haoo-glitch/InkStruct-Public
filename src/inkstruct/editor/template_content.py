"""Current-document template selection, field form and fit evidence."""

from dataclasses import replace
from pathlib import Path

from PySide6 import QtCore, QtWidgets

from ..document.markdown import parse_markdown
from .template_field_form import FieldFormDialog

TemplateContentDialog = FieldFormDialog


class TemplateContentPanel(QtWidgets.QWidget):
    def __init__(self, editor):
        super().__init__()
        self.editor = editor
        self.template_undo, self.template_redo = [], []
        self.history_session = self.refresh_key = None
        col = QtWidgets.QVBoxLayout(self)
        col.addWidget(QtWidgets.QLabel('当前文档资源'))
        libraries = QtWidgets.QHBoxLayout()
        for category, title in [('fonts', '打开字体库'), ('templates', '打开模板库')]:
            button = QtWidgets.QPushButton(title)
            button.clicked.connect(lambda _checked=False, key=category: self.open_library(key))
            libraries.addWidget(button)
        col.addLayout(libraries)
        self.font_summary = QtWidgets.QLabel()
        self.font_summary.setWordWrap(True)
        self.font_summary.setTextFormat(QtCore.Qt.PlainText)
        col.addWidget(self.font_summary)
        choose_font = QtWidgets.QPushButton('更换本文字体…')
        choose_font.clicked.connect(self.choose_font)
        col.addWidget(choose_font)
        self.connect_font_button = QtWidgets.QPushButton('连接原版本…')
        self.connect_font_button.clicked.connect(self.connect_font)
        col.addWidget(self.connect_font_button)
        self.summary = QtWidgets.QLabel()
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(QtCore.Qt.PlainText)
        col.addWidget(self.summary)
        b = QtWidgets.QPushButton("更换模板…")
        b.clicked.connect(self.choose_template)
        col.addWidget(b)
        self.newer_template_button = QtWidgets.QPushButton('查看新版…')
        self.newer_template_button.clicked.connect(self.view_newer_template)
        col.addWidget(self.newer_template_button)
        self.revision_lookup = (None, None)
        edit_layout = QtWidgets.QPushButton('编辑本文页面版式…')
        edit_layout.clicked.connect(self.edit_layout)
        col.addWidget(edit_layout)
        col.addWidget(QtWidgets.QLabel("字段"))
        self.fields = QtWidgets.QTreeWidget()
        self.fields.setHeaderLabels(["字段", "当前内容"])
        self.fields.setRootIsDecorated(False)
        self.fields.setMaximumHeight(190)
        self.fields.itemDoubleClicked.connect(lambda *_: self.edit())
        col.addWidget(self.fields)
        self.fill = QtWidgets.QPushButton("填写字段…")
        self.fill.clicked.connect(self.edit)
        col.addWidget(self.fill)
        more = QtWidgets.QToolButton()
        more.setText("字段操作")
        more.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        menu = QtWidgets.QMenu(more)
        menu.addAction("复制全部字段骨架", self.copy_skeleton)
        menu.addAction("复制所选字段写法", self.copy_field)
        menu.addAction("在主编辑器查看所选字段", self.locate_field)
        more.setMenu(menu)
        col.addWidget(more)
        col.addWidget(QtWidgets.QLabel("当前文档适配检查"))
        self.issues = QtWidgets.QListWidget()
        self.issues.setMaximumHeight(150)
        self.issues.itemDoubleClicked.connect(lambda *_: self.locate_issue())
        col.addWidget(self.issues)
        for title, callback in [
            ("查看并定位所选问题", self.locate_issue),
            ("查看完整适配报告…", editor.template_fit_report),
        ]:
            b = QtWidgets.QPushButton(title)
            b.clicked.connect(callback)
            col.addWidget(b)
        note = QtWidgets.QLabel(
            "在模板库制作可复用模板。\n模板随文档保存，换版需明确确认。"
        )
        note.setWordWrap(True)
        col.addWidget(note)
        col.addStretch()
        self.message = QtWidgets.QLabel()
        self.message.setWordWrap(True)
        col.addWidget(self.message)
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(350)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        self.refresh()

    def refresh(self):
        from ..fonts.library import fingerprint
        from ..resource_catalog import TemplateStore, workspace_for

        w = self.editor
        t = w.flow.template
        store = TemplateStore(workspace_for(w) / 'templates')
        try:
            stamp = fingerprint(store.index)
        except OSError:
            stamp = None
        revision_key = (id(t), store.index, stamp)
        if revision_key != self.revision_lookup[0]:
            try:
                candidates = store.newer(t) if t and stamp else ()
                update = (store, candidates[0]) if candidates else None
            except (OSError, TypeError, ValueError) as error:
                self.message.setText(str(error))
                update = None
            self.revision_lookup = (revision_key, update)
        self.newer_template_button.setVisible(self.revision_lookup[1] is not None)
        self.connect_font_button.setVisible(bool(w.resolver.font_identity and not w.run_path))
        snapshot = getattr(w, "snapshot", None)
        key = (
            w.source_session.document_id,
            w.source_session.revision,
            t,
            id(snapshot),
            bool(getattr(w, "worker", None)),
            w.timer.isActive(),
            w.run_path,
            w.resolver.resource_key,
        )
        if key == self.refresh_key:
            return
        self.refresh_key = key
        path = getattr(w, 'run_path', '')
        from ..resource_catalog import FontMetadata
        label = ''
        if path and Path(path).suffix == '.inkfont':
            try:
                data = FontMetadata(Path(path).parent).read().get(Path(path).name, {})
                label = data.get('alias') or data.get('summary', {}).get('manifest', {}).get('name', '')
            except (ValueError, OSError):
                pass
        if not label:
            writers = {g.writer_id for pool in w.resolver.pools.values() for g in pool if g.font_core}
            label = '、'.join(sorted(writers)) + ' · 本文冻结字形' if writers else '本文资源（可在文件详情中查看路径）'
        self.font_summary.setText('字体：' + label +
                                 f'\n已冻结选样 {len(w.resolver.selections)} 处')
        self.fields.clear()
        self.issues.clear()
        kind = getattr(t, "kind", "legacy")
        detail = (
            "简单模板"
            if kind == "simple"
            else f"自定义模板 · {len(t.start_pages)} 张起始页 · {len(t.loop_pages)} 张循环页"
            if kind == "custom"
            else "旧版模板 · 保留原版式与内容对应"
        )
        self.summary.setText(
            f"模板：{t.name}" + (f" · 修订 {t.revision.number}" if t.revision else '') + f"\n{detail}"
            if t else "普通页面\n正文自动换行与分页。可更换为已有模板。"
        )
        self.fill.setEnabled(t is not None and (not w.flow.named_fields or bool(t.fields)))
        self.fill.setText("编辑旧版内容对应…" if t and not w.flow.named_fields else "填写字段…")
        if w.flow.named_fields:
            parsed = parse_markdown(w.source_session, field_blocks=True)
            values = {}
            for n in parsed.nodes:
                if n.kind == "named_field":
                    values.setdefault(dict(n.attributes)["field_id"], []).append(
                        " ".join(
                            parsed.source[n.span.start : n.span.end].splitlines()[1:-1]
                        ).strip()
                    )
            for f in t.fields:
                rows = values.get(f.field_id, [])
                value = (
                    "重复定义，请修正源码"
                    if len(rows) > 1
                    else rows[0]
                    if rows and rows[0]
                    else "未填写" + (" · 必填" if f.required else " · 可选")
                )
                item = QtWidgets.QTreeWidgetItem(
                    [f.label + (" *" if f.required else ""), value[:70]]
                )
                item.setData(0, QtCore.Qt.UserRole, f.field_id)
                item.setToolTip(0, f.field_id)
                self.fields.addTopLevelItem(item)
        elif t:
            self.fields.addTopLevelItem(
                QtWidgets.QTreeWidgetItem(["旧版内容对应", "点击下方按钮编辑"])
            )
        if snapshot is None or getattr(w, "worker", None) or w.timer.isActive():
            self.issues.addItem("正在排版；结果尚未更新。")
        elif not snapshot.diagnostics:
            self.issues.addItem("本次内容检查未发现问题。")
        else:
            for d in snapshot.diagnostics:
                item = QtWidgets.QListWidgetItem(
                    ("错误　" if d.severity == "error" else "提醒　") + d.message
                )
                item.setData(QtCore.Qt.UserRole, d)
                item.setToolTip(d.code + "\n" + d.message)
                self.issues.addItem(item)

    def selected_field(self):
        item = self.fields.currentItem()
        return item.data(0, QtCore.Qt.UserRole) if item else None

    def locate_field(self, field_id=None):
        w = self.editor
        key = field_id or self.selected_field()
        if w.flow.named_fields:
            doc = parse_markdown(w.source_session, field_blocks=True)
            node = next(
                (
                    n
                    for n in doc.nodes
                    if n.kind == "named_field" and dict(n.attributes)["field_id"] == key
                ),
                None,
            )
            if node:
                w.navigate_span(node.span)
                w.editor.setFocus()
                return
        self.message.setText("字段尚无源码块，可通过“填写字段”添加。")

    def copy_field(self):
        from ..document.named_fields import field_example

        if key := self.selected_field():
            QtWidgets.QApplication.clipboard().setText(field_example(key))

    def locate_issue(self):
        item = self.issues.currentItem()
        d = item.data(QtCore.Qt.UserRole) if item else None
        if d is None:
            return
        target = getattr(d, "target", None)
        if d.code == "template-field-required" and target:
            self.edit(field_id=target.slot_id)
        else:
            self.editor.navigate_span(d.span)
            self.message.setText(
                d.message + ("\n可编辑本文页面版式。" if target else "")
            )

    def choose_template(self):
        from .template_manager import TemplatePicker

        dialog = TemplatePicker(self.editor.flow.template, self)
        try:
            if dialog.exec() == QtWidgets.QDialog.Accepted:
                from .resource_apply import TemplateApplyDialog
                check = TemplateApplyDialog(self.editor, dialog.template, self)
                if check.exec() == QtWidgets.QDialog.Accepted:
                    self.message.setText("已应用到当前文档，正文、样式和选样保留。可用编辑菜单撤销。")
                check.deleteLater()
        except (ValueError, TypeError, OSError) as error:
            self.message.setText(str(error))
        finally:
            dialog.deleteLater()

    def choose_font(self):
        from ..resources_ui import FontPicker, use_document_font
        picker = FontPicker(self)
        if picker.exec() == QtWidgets.QDialog.Accepted:
            use_document_font(self.editor, picker.path, self)
        picker.deleteLater()

    def open_library(self, category):
        from ..resources_ui import open_management
        open_management(self.editor, category)

    def connect_font(self):
        from ..fonts.library import find_font_release
        from ..resource_catalog import workspace_for
        from .resource_apply import ResourceApplyDialog

        w = self.editor
        identity = w.resolver.font_identity
        if not identity:
            return
        try:
            path = find_font_release(workspace_for(w) / 'fonts', identity)
            if path is None:
                self.message.setText('字体库没有找到精确原版本。可选择原版文件，或使用“更换本文字体…”查看新版影响。')
                selected, _ = QtWidgets.QFileDialog.getOpenFileName(self, '选择本文原版字体', '', '字体 (*.inkfont)')
                if not selected:
                    return
                path = Path(selected)
            dialog = ResourceApplyDialog(w, font=path, exact_identity=identity, parent=self)
            if dialog.exec() == QtWidgets.QDialog.Accepted:
                self.message.setText('已完整验证并连接原版字体；原冻结选样保留。')
            dialog.deleteLater()
        except (OSError, ValueError) as error:
            self.message.setText(str(error))

    def view_newer_template(self):
        from .resource_apply import TemplateApplyDialog

        self.refresh()
        if self.revision_lookup[1] is None:
            return
        store, entry = self.revision_lookup[1]
        try:
            dialog = TemplateApplyDialog(self.editor, store.read(entry), self)
            if dialog.exec() == QtWidgets.QDialog.Accepted:
                self.message.setText('已换用新版模板，当前文档可撤销。')
            dialog.deleteLater()
        except (OSError, ValueError, TypeError) as error:
            self.message.setText(str(error))

    def edit_layout(self):
        from .template_manager import perform_template_action
        perform_template_action(self.editor, 'document', self.editor.flow.template)

    def apply_template(self, template, *, bindings=None):
        w = self.editor
        if w.source_session is not self.history_session:
            self.template_undo.clear()
            self.template_redo.clear()
            self.history_session = w.source_session
        flow = replace(w.flow, template=template,
                       template_bindings=w.flow.template_bindings if bindings is None else bindings)
        if flow == w.flow:
            return
        self.template_undo.append(
            (
                w.flow.template,
                w.flow.template_bindings,
                w.flow.schema_version,
                template,
                len(w.source_session._undo),
            )
        )
        self.template_redo.clear()
        w.flow = flow
        w.mark_dirty()
        w.schedule_layout()
        self.refresh_key = None
        self.refresh()

    def route_history(self, direction):
        w = self.editor
        stack = self.template_redo if direction == "redo" else self.template_undo
        if (
            w.source_session is self.history_session
            and stack
            and len(w.source_session._undo) == stack[-1][4]
            and w.flow.template == stack[-1][3]
        ):
            self.template_history(direction == "redo")
            return True
        return False

    def source_edited(self):
        self.template_redo.clear()

    def template_history(self, redo):
        w = self.editor
        source, target = (
            (self.template_redo, self.template_undo)
            if redo
            else (self.template_undo, self.template_redo)
        )
        if w.source_session is not self.history_session or not source:
            return
        template, bindings, version, expected, checkpoint = source[-1]
        if w.flow.template != expected:
            self.message.setText("当前页面版式已改变，无法撤销过期操作。")
            return
        flow = replace(
            w.flow, template=template, template_bindings=bindings, schema_version=version
        )
        source.pop()
        target.append(
            (w.flow.template, w.flow.template_bindings, w.flow.schema_version, template, checkpoint)
        )
        w.flow = flow
        w.mark_dirty()
        w.schedule_layout()

    def edit(self, *, field_id=None):
        w = self.editor
        if not w.flow.named_fields:
            if not w.flow.template:
                return
            from .template_bindings import TemplateBindingsWidget

            dialog = QtWidgets.QDialog(w)
            dialog.setWindowTitle("当前文档 · 旧版内容对应")
            dialog.resize(700, 620)
            col = QtWidgets.QVBoxLayout(dialog)
            binding = TemplateBindingsWidget(
                w.parse_current_source(), w.flow.template_bindings, dialog
            )
            binding.set_template(w.flow.template)
            col.addWidget(binding)
            buttons = QtWidgets.QDialogButtonBox(
                QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
            )
            buttons.accepted.connect(dialog.accept)
            buttons.rejected.connect(dialog.reject)
            col.addWidget(buttons)
            try:
                if dialog.exec() == QtWidgets.QDialog.Accepted:
                    w.flow = replace(w.flow, template_bindings=binding.bindings)
                    w.mark_dirty()
                    w.schedule_layout()
            finally:
                dialog.deleteLater()
            return
        session, revision = w.source_session, w.source_session.revision
        dialog = TemplateContentDialog(w.flow.template, session.source, w)
        dialog.focus_field(field_id or self.selected_field())
        try:
            result = dialog.exec()
            if result == QtWidgets.QDialog.Accepted:
                if w.source_session is not session or session.revision != revision:
                    raise ValueError("文档已经变化，请重新打开填写窗口。")
                if session.apply_preserving(dialog.configuration()):
                    self.source_edited()
                    w._display_session()
                    w.mark_dirty()
                    w.schedule_layout()
            elif result == 2:
                self.locate_field(dialog.source_field_id)
        except (ValueError, TypeError, UnicodeError) as error:
            self.message.setText(str(error))
        finally:
            dialog.deleteLater()

    def copy_skeleton(self):
        if self.editor.flow.named_fields:
            QtWidgets.QApplication.clipboard().setText(self.editor.flow.template.skeleton())
            self.message.setText("已复制全部字段骨架，未覆盖正文。")
