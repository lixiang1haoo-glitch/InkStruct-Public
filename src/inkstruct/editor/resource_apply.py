"""Isolated impact checks; only an explicit confirmation changes document resources."""

from dataclasses import replace
from pathlib import Path

from PySide6 import QtCore, QtWidgets

from ..assets.resolver import AssetResolver
from ..document.editing import SourceSession
from ..fonts.core import cached_font
from ..fonts.library import fingerprint
from ..fonts.ui import Job


def document_token(editor):
    return (id(editor.source_session), editor.source_session.revision, editor.edit_generation,
            editor.run_path, editor.symbol_path, editor.flow, editor.page, editor.style,
            repr(editor.resolver.selection_records()))


def clone_resolver(resolver):
    return AssetResolver(embedded=tuple(g for pool in resolver.pools.values() for g in pool),
                         seed=resolver.seed, selections=tuple(resolver.selections.values()))


def font_resolver(font, old):
    """Retain exact old frozen cores only if the new package proves them unchanged."""
    records = {r['candidate_id']: r for r in font.records}
    glyphs = {g.asset_id: g for pool in old.pools.values() for g in pool}
    preserved, selected = {}, []
    for choice in old.selections.values():
        glyph = glyphs.get(choice.asset_id)
        core = glyph.font_core if glyph else None
        record = records.get(choice.sample_id)
        if (core and record == core['record'] and font.metrics.get(choice.sample_id) == core['metrics']
                and font.provenance.get(choice.sample_id) == core['summary']
                and record['enabled'] and core['summary']['review_status'] not in {'rejected', 'needs_review'}):
            preserved[glyph.asset_id] = glyph
            selected.append(choice)
    return AssetResolver(embedded=tuple(preserved.values()), seed=old.seed, selections=selected), len(selected)


class ResourceHistory:
    def __init__(self, editor):
        self.editor = editor
        self.undo, self.redo = [], []

    def state(self):
        w = self.editor
        return (w.run_path, w.symbol_path, w.mode, clone_resolver(w.resolver))

    def push(self, old):
        w = self.editor
        self.undo.append((id(w.source_session), len(w.source_session._undo), w.flow,
                          (w.run_path, w.symbol_path, w.mode), old))
        self.redo.clear()

    def route(self, direction):
        w = self.editor
        source, destination = (self.undo, self.redo) if direction == 'undo' else (self.redo, self.undo)
        if not source:
            return False
        session, checkpoint, flow, expected, value = source[-1]
        if (id(w.source_session), len(w.source_session._undo), w.flow,
                (w.run_path, w.symbol_path, w.mode)) != (session, checkpoint, flow, expected):
            return False
        current = self.state()
        source.pop()
        w.run_path, w.symbol_path, w.mode, resolver = value
        w.resolver = clone_resolver(resolver)
        with QtCore.QSignalBlocker(w.mode_picker):
            w.mode_picker.setCurrentIndex(w.mode_picker.findData(w.mode))
        destination.append((session, checkpoint, flow, (w.run_path, w.symbol_path, w.mode), current))
        w.mark_dirty()
        w.schedule_layout()
        return True


class ResourceApplyDialog(QtWidgets.QDialog):
    def __init__(self, editor, *, font=None, template=None, parent=None):
        super().__init__(parent or editor)
        self.editor, self.font, self.template = editor, str(font) if font else None, template
        self.is_font = font is not None
        self.setWindowTitle('更换本文字体 · 影响确认' if self.is_font else '更换本文模板 · 适配确认')
        self.resize(820, 620)
        self.token = document_token(editor)
        self.result = None
        self.requires_acknowledgement = False
        self.closed = False
        self.path_stamp = fingerprint(font) if font else None
        col = QtWidgets.QVBoxLayout(self)
        self.summary = QtWidgets.QLabel('正在检查实际文档…检查期间文档保持不变。')
        self.summary.setWordWrap(True)
        col.addWidget(self.summary)
        self.issues = QtWidgets.QTreeWidget()
        self.issues.setHeaderLabels(['级别', '源码位置', '问题'])
        self.issues.setColumnWidth(0, 65)
        self.issues.setColumnWidth(1, 110)
        col.addWidget(self.issues, 1)
        self.issues.itemDoubleClicked.connect(self.locate)
        self.acknowledge = QtWidgets.QCheckBox('我已查看上述影响；仍将此资源应用到本文（问题继续保留）')
        self.acknowledge.hide()
        self.acknowledge.toggled.connect(self.update_action)
        col.addWidget(self.acknowledge)
        self.note = QtWidgets.QLabel('仅改变当前文档，不设置新文档默认。确认后可以撤销；原文、字段和现有校正配置保留。')
        self.note.setWordWrap(True)
        col.addWidget(self.note)
        self.buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        self.buttons.button(QtWidgets.QDialogButtonBox.Ok).setText('应用到本文')
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.buttons.button(QtWidgets.QDialogButtonBox.Ok).setEnabled(False)
        col.addWidget(self.buttons)
        session = SourceSession.restore(editor.source_session.source, editor.source_session.identity_record())
        resolver = clone_resolver(editor.resolver)
        run, symbols, page, style, flow = editor.run_path, editor.symbol_path, editor.page, editor.style, editor.flow
        revision = editor.revision
        def calculate(progress):
            from .mixed import build_markdown
            retained = len(resolver.selections)
            target_resolver = resolver
            if self.is_font:
                progress('正在验证字体并检查本文…')
                target_resolver, retained = font_resolver(cached_font(Path(self.font)), resolver)
            result = build_markdown(session, revision, target_resolver,
                                    self.font if self.is_font else run, '' if self.is_font else symbols,
                                    page, style, flow if self.is_font else replace(flow, template=template), None)
            return {**result, 'retained': retained, 'previous': len(resolver.selections)}
        self.job = Job(calculate)
        self.job.signals.completed.connect(self.completed)
        self.job.signals.failed.connect(self.failed)
        self.job.signals.progress.connect(self.summary.setText)
        QtCore.QThreadPool.globalInstance().start(self.job)

    def unchanged(self):
        return document_token(self.editor) == self.token and (not self.font or fingerprint(self.font) == self.path_stamp)

    def completed(self, result):
        if self.closed:
            return
        try:
            if not self.unchanged():
                raise ValueError('检查期间文档或资源已经变化，请取消后重新检查。')
            self.result = result
            snapshot = result['snapshot']
            errors = sum(d.severity == 'error' for d in snapshot.diagnostics)
            warnings = sum(d.severity == 'warning' for d in snapshot.diagnostics)
            retained, previous = result['retained'], result['previous']
            self.summary.setText((f'兼容冻结选样保留 {retained}/{previous} 处；需要重新选样 {previous-retained} 处。\n' if self.is_font else
                                  '字段按稳定标识对应，未声明字段和必填项问题如下；不删除原文内容。\n') +
                                 f'试排 {len(snapshot.pages)} 页 · {errors} 项错误 · {warnings} 项提醒。' +
                                 ('\n当前内容具备严格 SVG 条件。' if snapshot.plotter_exportable else '\n当前内容仍有导出限制，应用资源不会放行这些限制。'))
            for d in snapshot.diagnostics:
                item = QtWidgets.QTreeWidgetItem([d.severity, f'{d.span.start}–{d.span.end}', d.message])
                item.setData(0, QtCore.Qt.UserRole, d)
                self.issues.addTopLevelItem(item)
            for warning in result['resolver'].usage_warnings():
                self.issues.addTopLevelItem(QtWidgets.QTreeWidgetItem(['来源提醒', warning['character'], '；'.join(warning['reasons'])]))
            self.requires_acknowledgement = bool(snapshot.diagnostics or previous-retained or result['resolver'].usage_warnings())
            self.acknowledge.setVisible(self.requires_acknowledgement)
            self.update_action()
        except (ValueError, OSError) as error:
            self.failed(str(error))

    def failed(self, error):
        if not self.closed:
            self.result = None
            self.summary.setText('未应用：' + error)
            self.update_action()

    def update_action(self):
        self.buttons.button(QtWidgets.QDialogButtonBox.Ok).setEnabled(
            self.result is not None and (not self.requires_acknowledgement or self.acknowledge.isChecked()))

    def locate(self):
        item = self.issues.currentItem()
        diagnostic = item.data(0, QtCore.Qt.UserRole) if item else None
        if diagnostic:
            self.editor.navigate_span(diagnostic.span)

    def accept(self):
        if self.result is None or (self.requires_acknowledgement and not self.acknowledge.isChecked()):
            return
        try:
            if not self.unchanged():
                raise ValueError('文档或资源已经变化，未应用过期检查结果。')
            w = self.editor
            if self.is_font:
                if not hasattr(w, '_resource_history'):
                    w._resource_history = ResourceHistory(w)
                old = w._resource_history.state()
                w.run_path, w.symbol_path, w.mode = self.font, '', 'markdown'
                w.resolver = self.result['resolver']
                with QtCore.QSignalBlocker(w.mode_picker):
                    w.mode_picker.setCurrentIndex(w.mode_picker.findData('markdown'))
                w._resource_history.push(old)
                w.mark_dirty()
                w.schedule_layout()
            else:
                w.template_content_panel.apply_template(self.template)
            self.closed = True
            super().accept()
        except (ValueError, OSError) as error:
            self.failed(str(error))

    def reject(self):
        self.closed = True
        super().reject()


class TemplateApplyDialog(ResourceApplyDialog):
    def __init__(self, editor, template, parent=None):
        super().__init__(editor, template=template, parent=parent)
