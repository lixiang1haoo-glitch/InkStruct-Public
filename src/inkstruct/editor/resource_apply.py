"""Isolated impact checks; only an explicit confirmation changes document resources."""

from dataclasses import replace
from pathlib import Path

from PySide6 import QtCore, QtWidgets

from ..assets.resolver import AssetResolver
from ..document.editing import SourceSession
from ..fonts.core import cached_font
from ..fonts.identity import release_identity
from ..fonts.library import fingerprint
from ..fonts.ui import Job


def document_token(editor):
    return (id(editor.source_session), editor.source_session.revision, editor.edit_generation,
            editor.run_path, editor.symbol_path, editor.flow, editor.page, editor.style,
            repr(editor.resolver.selection_records()))


def clone_resolver(resolver):
    return AssetResolver(embedded=tuple(g for pool in resolver.pools.values() for g in pool),
                         seed=resolver.seed, selections=tuple(resolver.selections.values()),
                         font_identity=resolver.font_identity)


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
    return AssetResolver(embedded=tuple(preserved.values()), seed=old.seed, selections=selected,
                         font_identity=release_identity(font.identity)), len(selected)


def template_replacement(flow, target, document):
    """Keep legacy bindings by stable slot/region identity and leave source text intact."""
    from ..document.flow_template import FlowTemplate
    from ..document.template_slots import KINDS

    old = flow.template
    source_nodes = {node.node_id: node for node in document.nodes}
    old_slots = {s.region: s for s in getattr(old, 'slots', ())}
    new_slots = {s.slot_id: s for s in getattr(target, 'slots', ())}
    bindings, invalid = [], []
    for binding in flow.template_bindings:
        old_slot = old_slots.get(binding.region)
        slot = new_slots.get(old_slot.slot_id) if old_slot else None
        candidate = slot.bind(binding.node_ids) if slot else binding
        if slot:
            kinds = KINDS[slot.kind]
            valid = all(key in source_nodes and (kinds is None or source_nodes[key].kind in kinds)
                        for key in candidate.node_ids)
        elif target is not None and not isinstance(target, FlowTemplate) and not old_slot and not new_slots:
            faces = (target.first, target.continuation) if binding.pages == 'all' else (target.first,)
            valid = (all(key in source_nodes for key in binding.node_ids)
                     and all(any(r.name == binding.region for r in face.reserved)
                             and (not binding.anchor or any(a.name == binding.anchor for a in face.anchors))
                             for face in faces))
        else:
            valid = False
        if valid:
            bindings.append(candidate)
        else:
            invalid.append(old_slot.slot_id if old_slot else binding.region)
    if isinstance(old, FlowTemplate):
        target_fields = {f.field_id: f for f in getattr(target, 'fields', ())}
        values = {dict(n.attributes)['field_id'] for n in document.nodes if n.kind == 'named_field'}
        invalid.extend(f.field_id for f in old.fields if f.field_id in values and (
            f.field_id not in target_fields or f.value_type != target_fields[f.field_id].value_type))
    return replace(flow, template=target, template_bindings=tuple(bindings)), tuple(invalid)


def template_changes(before, after):
    from ..document.flow_template import FlowTemplate

    def page_group(template, key):
        return getattr(template, key, ()) if isinstance(template, FlowTemplate) else ()

    def page_names(template, ids, *, identify=False):
        if not ids:
            return '无'
        names = {p.layout_id: p.label for p in template.layouts}
        return ' → '.join(f'{names[key]}〔{key}〕' if identify else names[key] for key in ids)

    for title, key in [('起始页组', 'start_pages'), ('循环页组', 'loop_pages')]:
        old, new = page_group(before, key), page_group(after, key)
        if old != new:
            a, b = page_names(before, old), page_names(after, new)
            if a == b:
                a, b = page_names(before, old, identify=True), page_names(after, new, identify=True)
            yield '页组顺序', title, f'原顺序 {a} / 新顺序 {b}'

    def backgrounds(template):
        if isinstance(template, FlowTemplate):
            return {p.layout_id: (p.label, p.background.sha256) for p in template.layouts if p.background}
        return {key: (label, face.background.sha256)
                for key, label in [('first', '首页'), ('continuation', '续页')]
                if (face := getattr(template, key, None)) and face.background}

    old, new = backgrounds(before), backgrounds(after)
    for key in sorted(old.keys() | new.keys()):
        label, previous_hash = old.get(key, ('', None))
        current_label, current_hash = new.get(key, ('', None))
        if previous_hash != current_hash:
            yield '页面底图', current_label or label, (
                '新增' if previous_hash is None else '移除' if current_hash is None else '已更换'
            )
    for title, key in [('横向偏移', 'offset_x_mm'), ('纵向偏移', 'offset_y_mm')]:
        old, new = getattr(before, key, 0), getattr(after, key, 0)
        if old != new:
            yield '整份模板偏移', title, f'{old:g} → {new:g} mm'
    old, new = (getattr(t, 'finish_cycle', False) for t in (before, after))
    if old != new:
        yield '循环设置', '末尾补齐整个循环页组', '开启' if new else '关闭'

    def regions(template):
        if isinstance(template, FlowTemplate):
            return {(page.layout_id, f.frame_id): (f.role, f.field_id, f.order, f.region.bounds)
                    for page in template.effective_layouts for f in page.frames}
        if template:
            return {(face, r.name): r.bounds for face in ('first', 'continuation')
                    for r in (getattr(template, face).body, *getattr(template, face).reserved)}
        return {}

    def fields(template):
        return {getattr(f, 'field_id', None) or f.slot_id: f
                for f in getattr(template, 'fields', getattr(template, 'slots', ()))}

    for category, getter in [('区域', regions), ('字段', fields)]:
        old, new = getter(before), getter(after)
        for key in sorted(old.keys() | new.keys()):
            if old.get(key) == new.get(key):
                continue
            name = '/'.join(key) if isinstance(key, tuple) else key
            if key not in old:
                yield category, name, '新增'
            elif key not in new:
                yield category, name, '移除'
            else:
                yield category, name, f'变更：{old[key]} → {new[key]}' if category == '区域' else '声明或规则变更'


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
    def __init__(self, editor, *, font=None, template=None, exact_identity=None, parent=None):
        super().__init__(parent or editor)
        self.editor, self.font, self.template = editor, str(font) if font else None, template
        self.is_font = font is not None
        self.setWindowTitle('连接原版本 · 完整验证' if exact_identity else
                            '更换本文字体 · 影响确认' if self.is_font else '更换本文模板 · 适配确认')
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
            target_resolver = resolver
            target_flow, invalid = flow, ()
            # Font previews compare against the authoritative embedded snapshot.
            # An unavailable external copy must not prevent a manual replacement.
            baseline_run = '' if self.is_font and Path(run).suffix == '.inkfont' else run
            baseline = build_markdown(session, revision, clone_resolver(resolver), baseline_run, symbols,
                                      page, style, flow, None)
            if self.is_font:
                progress('正在验证字体并检查本文…')
                package = cached_font(Path(self.font))
                if exact_identity and release_identity(package.identity) != exact_identity:
                    raise ValueError('所选字体的字体 ID、发布 ID 或核心哈希与本文原版本不同')
                if not exact_identity:
                    target_resolver, _ = font_resolver(package, resolver)
            else:
                target_flow, invalid = template_replacement(flow, template, baseline['document'])
            result = build_markdown(session, revision, target_resolver,
                                    self.font if self.is_font else run, '' if self.is_font else symbols,
                                    page, style, target_flow, None)
            return {**result, 'retained': len(target_resolver.selections),
                    'baseline': baseline['snapshot'], 'target_flow': target_flow,
                    'invalid_bindings': invalid, 'previous_choices': tuple(resolver.selections.values()),
                    'old_template': flow.template, 'page_profile': page}
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
            baseline = result['baseline']
            changes = []
            if self.is_font:
                by_id = {o.occurrence_id: o for o in result['document'].occurrences}
                nodes = {n.node_id: n for root in result['document'].nodes for n in root.walk()}
                changed = [s for s in result['previous_choices']
                           if result['resolver'].selections.get(s.occurrence_id) != s
                           and (s.occurrence_id in by_id or s.occurrence_id.split(':math-rule:')[0] in nodes)]
                previous = len(result['previous_choices'])
                old_missing = {(d.span.start, d.span.end) for d in baseline.diagnostics if d.code == 'asset-missing'}
                new_missing = [d for d in snapshot.diagnostics if d.code == 'asset-missing'
                               and (d.span.start, d.span.end) not in old_missing]
                impact = f'冻结选样保留 {previous-len(changed)}/{previous} 处；需要重新选样 {len(changed)} 处；新增缺字 {len(new_missing)} 处。'
                for choice in changed:
                    owner = by_id.get(choice.occurrence_id) or nodes[choice.occurrence_id.split(':math-rule:')[0]]
                    changes.append(('重新选样', f'{owner.span.start}–{owner.span.end}', choice.character))
                for diagnostic in new_missing:
                    changes.append(('新增缺字', f'{diagnostic.span.start}–{diagnostic.span.end}', diagnostic.message))
            else:
                old, new = result['old_template'], self.template
                old_page, new_page = (t.page if t else result['page_profile'] for t in (old, new))
                overflow = [sum('overflow' in d.code or 'too-tall' in d.code or 'no-progress' in d.code
                                for d in s.diagnostics) for s in (baseline, snapshot)]
                impact = (f'纸张 {old_page.width_mm:g} × {old_page.height_mm:g} → '
                          f'{new_page.width_mm:g} × {new_page.height_mm:g} mm；'
                          f'页数 {len(baseline.pages)} → {len(snapshot.pages)}；溢出问题 {overflow[0]} → {overflow[1]}。')
                changes.extend(template_changes(old, new))
                changes.extend(('失效绑定', key, '需重新检查字段对应；源码保留')
                               for key in result['invalid_bindings'])
            for change in changes:
                self.issues.addTopLevelItem(QtWidgets.QTreeWidgetItem(change))
            self.summary.setText(impact + '\n' +
                                 f'试排 {len(snapshot.pages)} 页 · {errors} 项错误 · {warnings} 项提醒。' +
                                 ('\n当前内容具备严格 SVG 条件。' if snapshot.plotter_exportable else '\n当前内容仍有导出限制，应用资源不会放行这些限制。'))
            for d in snapshot.diagnostics:
                item = QtWidgets.QTreeWidgetItem([d.severity, f'{d.span.start}–{d.span.end}', d.message])
                item.setData(0, QtCore.Qt.UserRole, d)
                self.issues.addTopLevelItem(item)
            for warning in result['resolver'].usage_warnings():
                self.issues.addTopLevelItem(QtWidgets.QTreeWidgetItem(['来源提醒', warning['character'], '；'.join(warning['reasons'])]))
            self.requires_acknowledgement = bool(snapshot.diagnostics or changes or result['resolver'].usage_warnings())
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
                w.template_content_panel.apply_template(self.template,
                    bindings=self.result['target_flow'].template_bindings)
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
