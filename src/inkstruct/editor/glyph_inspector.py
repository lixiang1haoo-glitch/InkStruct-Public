"""Explicit optical corrections beside a selected, frozen preview occurrence."""

from dataclasses import replace
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from ..document.glyph_corrections import GlyphCorrection, correction_for, update_corrections
from ..settings_pages import label
from .correction_context import surrounding_glyphs


class CorrectionPreview(QtWidgets.QWidget):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.context = ()
        self.context_key = None
        self.setMinimumHeight(190)
        self.setAccessibleName("字符校正预览：实际周边字符，灰色原字形，蓝色校正字形")

    def refresh_context(self):
        owner = self.owner
        key = (id(owner.editor.snapshot), owner.fragment.fragment_id if owner.fragment else None)
        if key != self.context_key:
            self.context_key = key
            self.context = (surrounding_glyphs(owner.editor.snapshot, owner.fragment,
                                              owner.editor.asset_for_fragment,
                                              flow=owner.editor.flow,
                                              document=owner.editor.markdown_document)
                            if owner.fragment and owner.glyph and owner.editor.snapshot else ())
            self.setToolTip("实际排版邻字：" + "".join(c.fragment.text for c in self.context))

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QtGui.QColor("white"))
        glyph = self.owner.glyph
        if glyph is None:
            return
        groups = self.drawing_groups()
        points = [p for strokes, _ in groups for s in strokes for p in s]
        if not points:
            return
        fragment = self.owner.fragment
        baseline = fragment.baseline_mm
        padding = fragment.glyph_em_mm * .25
        left, top = min(p[0] for p in points)-padding, min(p[1] for p in points)-padding
        right, bottom = max(p[0] for p in points)+padding, max(p[1] for p in points)+padding
        top, bottom = min(top, baseline - fragment.glyph_em_mm), max(bottom, baseline+padding)
        scale = min((self.width()-24)/(right-left), (self.height()-24)/(bottom-top))
        painter.translate((self.width()-(right-left)*scale)/2-left*scale,
                          (self.height()-(bottom-top)*scale)/2-top*scale)
        painter.scale(scale, scale)
        painter.fillRect(QtCore.QRectF(fragment.x_mm, top,
                                      fragment.advance_mm, bottom-top),
                         QtGui.QColor("#eef4ff"))
        painter.setPen(QtGui.QPen(QtGui.QColor("#a9b5c7"), 1/scale, QtCore.Qt.PenStyle.DashLine))
        painter.drawLine(QtCore.QPointF(left, baseline), QtCore.QPointF(right, baseline))
        for strokes, color in groups:
            painter.setPen(QtGui.QPen(QtGui.QColor(color), 2/scale,
                                     QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap))
            for stroke in strokes:
                path = QtGui.QPainterPath(QtCore.QPointF(*stroke[0]))
                for p in stroke[1:]:
                    path.lineTo(*p)
                painter.drawPath(path)

    def drawing_groups(self):
        """Testable geometry identical to document correction, in physical mm."""
        targets = self.owner.targets() if self.owner.glyph else ()
        rule, groups = self.owner.rule(), []
        for context in self.context:
            if context.glyph and any(t.matches(context.fragment) for t in targets):
                groups.extend(((context.original(), "#bcc5d2"),
                               (context.corrected(rule), "#245cec")))
            else:
                groups.append((context.strokes, "#374151"))
        return tuple(groups)


class GlyphInspector(QtWidgets.QWidget):
    def __init__(self, editor):
        super().__init__()
        self.editor, self.fragment, self.glyph, self.job = editor, None, None, None
        self.last_result = None
        self.pending_application = None
        self.undo_records, self.redo_records = [], []
        self.source_session = None
        column = QtWidgets.QVBoxLayout(self)
        self.selection = label("在排版预览中点击一个有字形的字符。")
        self.selection.setObjectName("inspector_context")
        column.addWidget(self.selection)
        self.impact = label("")
        self.impact.setObjectName("inspector_scope")
        column.addWidget(self.impact)
        self.fields = QtWidgets.QWidget()
        column.addWidget(self.fields)
        form = QtWidgets.QFormLayout(self.fields)
        form.setRowWrapPolicy(QtWidgets.QFormLayout.RowWrapPolicy.WrapLongRows)
        self.controls = {}
        for key, title, low, high, initial in (
            ("dx_em", "左右位移", -200, 200, 0), ("dy_em", "上下位移", -200, 200, 0),
            ("scale_x", "宽度缩放", 25, 400, 100), ("scale_y", "高度缩放", 25, 400, 100)):
            control = QtWidgets.QDoubleSpinBox()
            control.setRange(low, high)
            control.setDecimals(4)
            control.setSingleStep(1)
            control.setSuffix(" %")
            control.setValue(initial)
            control.setAccessibleName("字符校正" + title)
            form.addRow(title, control)
            self.controls[key] = control
            control.valueChanged.connect(lambda *_: self.preview.update())
        self.scope = QtWidgets.QComboBox()
        for title, key in (("仅此处", "occurrence"), ("本文同一样本", "sample"),
                           ("本文同一字符的全部样本", "character")):
            self.scope.addItem(title, key)
        self.scope.setAccessibleName("字符校正应用范围")
        form.addRow("应用范围", self.scope)
        self.include_styles = QtWidgets.QCheckBox("同时包含正体与斜体")
        form.addRow(self.include_styles)
        self.write_font = QtWidgets.QCheckBox("同时保存到字体包的新版本")
        self.write_font.setAccessibleName("同时保存到字体包的新版本")
        form.addRow(self.write_font)
        self.hint = label("位移以当前字高为单位，向右／向下为正；缩放以左侧基线为原点。")
        column.addWidget(self.hint)
        self.preview = CorrectionPreview(self)
        column.addWidget(self.preview)
        column.addWidget(label("显示同一行的周边字符及实际字距；深灰：周边字形，浅灰：原字形，蓝色：本次校正。文档内校正保留字距与换行。\n"
                               "批量应用统一更新范围内已有校正，包括单字校正；正体与斜体默认分开。"))
        actions = QtWidgets.QGridLayout()
        self.apply_button = QtWidgets.QPushButton("应用字符校正")
        self.apply_button.setProperty("inkRole", "primary")
        self.reset_button = QtWidgets.QPushButton("恢复所选范围")
        self.reset_button.setToolTip("恢复本文所选范围到字体原字形；不会删除或覆盖已经另存的字体包。")
        self.cancel_button = QtWidgets.QPushButton("取消未应用修改")
        self.undo_button = QtWidgets.QPushButton("撤销上次校正")
        self.redo_button = QtWidgets.QPushButton("重做校正")
        for i, button in enumerate((self.apply_button, self.reset_button, self.cancel_button,
                                    self.undo_button, self.redo_button)):
            actions.addWidget(button, i//2, i%2)
        column.addLayout(actions)
        self.message = label("")
        self.message.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        column.addWidget(self.message)
        column.addStretch()
        self.scope.currentIndexChanged.connect(self.scope_changed)
        self.include_styles.toggled.connect(self.scope_changed)
        self.write_font.toggled.connect(self.scope_changed)
        self.apply_button.clicked.connect(self.apply)
        self.reset_button.clicked.connect(lambda: self.apply(reset=True))
        self.cancel_button.clicked.connect(self.load_values)
        self.undo_button.clicked.connect(lambda: self.history(False))
        self.redo_button.clicked.connect(lambda: self.history(True))
        self.scope_changed()

    def set_ready(self, ready):
        ready = bool(ready and self.fragment and self.glyph and not self.job
                     and self.editor.mode == "markdown")
        self.fields.setEnabled(ready)
        self.apply_button.setEnabled(ready)
        self.reset_button.setEnabled(ready)
        self.cancel_button.setEnabled(ready)
        self.undo_button.setEnabled(bool(ready and self.undo_records))
        self.redo_button.setEnabled(bool(ready and self.redo_records))
        if not self.editor.canvas.isEnabled():
            self.selection.setText("预览正在更新，字符校正暂不可用。")
            self.impact.clear()

    def select(self, fragment):
        if self.job:
            return
        if not self.fragment or self.fragment.occurrence_id != fragment.occurrence_id:
            with QtCore.QSignalBlocker(self.include_styles), QtCore.QSignalBlocker(self.write_font):
                self.include_styles.setChecked(False)
                self.write_font.setChecked(False)
        self.fragment = fragment
        self.glyph = self.editor.asset_for_fragment(fragment) if fragment.asset_id else None
        if not self.glyph:
            self.selection.setText("该元素没有可校正的字形，请选择一个已载入的字符。")
        else:
            style = self.glyph.font_core["record"]["letter_style"] if self.glyph.font_core else ""
            samples = self.sample_index()
            index = next(i for i, candidate in enumerate(samples, 1)
                         if candidate.sample_id == self.glyph.sample_id
                         and getattr(candidate, "asset_id", self.glyph.asset_id) == self.glyph.asset_id)
            count = len({f.occurrence_id for f in self.editor.snapshot.fragments
                         if f.asset_id == self.glyph.asset_id and f.text == fragment.text})
            self.selection.setText(f"「{fragment.text}」 U+{ord(fragment.text):04X}\n"
                                   + {"upright": "英文正体", "italic": "英文斜体",
                                      "unspecified": "英文未分类"}.get(style, "字形")
                                   + f" · 样本 {index}/{len(samples)}\n"
                                   + f"ID {self.glyph.sample_id[:12]} · 本文使用 {count} 处")
        self.load_values()
        self.scope_changed()

    def refresh(self):
        session = self.editor.source_session
        if session is not self.source_session:
            self.source_session = session
            self.undo_records.clear()
            self.redo_records.clear()
            self.fragment = self.glyph = None
            self.selection.setText("在排版预览中点击一个有字形的字符。")
            self.impact.clear()
            self.preview.refresh_context()
            self.preview.update()
        if self.fragment and self.editor.snapshot:
            fragment = next((f for f in self.editor.snapshot.fragments
                             if f.occurrence_id == self.fragment.occurrence_id
                             and f.asset_id == self.fragment.asset_id), None)
            if fragment:
                self.editor.select_fragment(fragment, sync_source=False)
            else:
                self.fragment = self.glyph = None
                self.selection.setText("先前选择的字符已变化，请在新预览中重新选择。")
                self.impact.clear()
                self.preview.refresh_context()
                self.preview.update()
        self.set_ready(self.editor.canvas.isEnabled())

    def load_values(self):
        self.preview.refresh_context()
        rule = correction_for(self.editor.flow.glyph_corrections, self.fragment) if self.fragment else None
        for key, control in self.controls.items():
            with QtCore.QSignalBlocker(control):
                control.setValue(getattr(rule, key) * 100 if rule else
                                 (100 if key.startswith("scale") else 0))
        self.preview.update()

    def scope_changed(self, *_):
        scope = self.scope.currentData()
        same = self.sample_index()
        all_styles = self.sample_index(include_styles=True)
        self.include_styles.setVisible(scope == "character" and len(all_styles) > len(same))
        self.write_font.setVisible(scope != "occurrence")
        self.write_font.setEnabled(bool(self.glyph and self.glyph.font_core and not self.job))
        self.write_font.setToolTip("完整校验并另存新包，原包保留；本文继续使用冻结字体和本次文档校正，不重复叠加。")
        if self.fragment and self.glyph:
            ids = set(self.target_ids())
            count = len({f.occurrence_id for f in self.editor.snapshot.fragments
                         if f.text == self.fragment.text and f.asset_id in ids and
                         (scope != "occurrence" or f.occurrence_id == self.fragment.occurrence_id)})
            samples = len(all_styles if self.include_styles.isChecked() else same)
            text = f"仅此处 · 本文 {count} 处" if scope == "occurrence" else (
                f"本文同一样本 · {count} 处" if scope == "sample" else
                f"本文同一字符 · {samples} 份样本／{count} 处")
            if scope != "occurrence" and self.write_font.isChecked() and self.glyph.font_core:
                text += "；同时另存校正字体"
            self.impact.setText(text)
        else:
            self.impact.clear()
        self.set_ready(self.editor.canvas.isEnabled())
        self.preview.update()

    def matching_samples(self, pool, include_styles):
        core = self.glyph.font_metadata
        style = core["record"]["letter_style"] if core else None
        return tuple(g for g in pool
                     if not core or (g.font_metadata and g.font_metadata["identity"] == core["identity"]
                                     and (include_styles or g.font_metadata["record"]["letter_style"] == style)))

    def sample_index(self, *, include_styles=False):
        if not self.glyph:
            return ()
        return self.matching_samples(
            self.editor.resolver.candidate_index(self.glyph.character), include_styles
        )

    def target_ids(self, *, materialize=False):
        if not self.glyph:
            return ()
        if self.scope.currentData() != "character":
            return (self.glyph.asset_id,)
        resolver = self.editor.resolver
        char = self.glyph.character
        if materialize:
            from ..fonts.preview_candidates import PreviewFontError

            try:
                pool = resolver.candidate_pool(char)
            except PreviewFontError as error:
                raise ValueError(str(error)) from error
        else:
            pool = resolver.pools.get(char, ())
        return tuple(g.asset_id for g in self.matching_samples(pool, self.include_styles.isChecked()))

    def rule(self, **identity):
        if not identity:
            identity = {"scope": "document"}
        return GlyphCorrection(**identity, **{k: c.value()/100 for k, c in self.controls.items()})

    def targets(self):
        scope, f = self.scope.currentData(), self.fragment
        return [self.rule(scope="occurrence" if scope == "occurrence" else "character", character=f.text,
                          occurrence_id=f.occurrence_id if scope == "occurrence" else "", asset_id=a)
                for a in self.target_ids(materialize=True)]

    def ready(self):
        w = self.editor
        if (not self.fragment or not self.glyph or not w.canvas.isEnabled() or self.job
                or w.mode != "markdown" or w.selected_fragment is None
                or self.fragment not in w.snapshot.fragments):
            raise ValueError("预览正在更新或选择已变化，请重新选择字符后应用。")

    def commit(self, records):
        old = self.editor.flow.glyph_corrections
        if tuple(records) == old:
            return
        flow = replace(self.editor.flow, glyph_corrections=tuple(records))
        self.undo_records.append(old)
        self.undo_records = self.undo_records[-128:]
        self.redo_records.clear()
        self.editor.flow = flow
        self.editor.mark_dirty()
        self.editor.schedule_layout()

    def apply(self, checked=False, *, reset=False):
        try:
            self.ready()
            targets = self.targets()
            records = update_corrections(self.editor.flow.glyph_corrections, targets,
                                         self.editor.snapshot.fragments, reset=reset)
            # Validate before opening a file picker or publishing a new font.
            replace(self.editor.flow, glyph_corrections=records)
            if (not reset and self.scope.currentData() != "occurrence" and
                    self.write_font.isChecked()):
                self.save_font(records)
                return
            self.commit(records)
            self.message.setText("已将所选范围恢复为字体原字形；其他范围保持原样。" if reset else
                                 "校正已统一应用到所选范围，随当前文档保存，可整体撤销。")
        except (ValueError, TypeError, OSError) as error:
            self.message.setText(str(error))

    def history(self, redo):
        try:
            self.ready()
            source, target = ((self.redo_records, self.undo_records) if redo else
                              (self.undo_records, self.redo_records))
            if not source:
                return
            previous = source.pop()
            target.append(self.editor.flow.glyph_corrections)
            self.editor.flow = replace(self.editor.flow, glyph_corrections=previous)
            self.editor.mark_dirty()
            self.editor.schedule_layout()
        except ValueError as error:
            self.message.setText(str(error))

    def save_font(self, records):
        if not self.glyph.font_core:
            raise ValueError("请先在字体库制作字体包，再对该字体执行校正另存。")
        source = self.editor.run_path
        if not source or Path(source).suffix.lower() != ".inkfont":
            source, _ = QtWidgets.QFileDialog.getOpenFileName(
                self, "选择所选字形的原始字体包", "", "字体包 (*.inkfont)")
        if not source:
            self.message.setText("已取消字体保存；本文未应用此次校正。")
            return
        output, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "另存校正字体（保留原包）", str(Path(source).with_stem(Path(source).stem + "-校正")),
            "字体包 (*.inkfont)")
        if not output:
            self.message.setText("已取消字体保存；本文未应用此次校正。")
            return
        if Path(output).exists():
            raise ValueError("目标已存在，请选择新文件名；不会覆盖已有字体包。")
        self.start_font_job(source, output, records=records)

    def start_font_job(self, source, output, *, records=None):
        from ..fonts.corrections import correct_font
        from ..fonts.ui import Job
        glyph = self.glyph
        if self.scope.currentData() not in {"sample", "character"}:
            raise ValueError("仅此处的校正不能写入字体包，请选择样本或字符范围。")
        rule = self.rule(scope="character", character=glyph.character)
        all_samples = self.scope.currentData() == "character"
        include_styles = all_samples and self.include_styles.isChecked()
        if records is None:
            records = update_corrections(self.editor.flow.glyph_corrections, self.targets(),
                                         self.editor.snapshot.fragments)
        replace(self.editor.flow, glyph_corrections=tuple(records))
        w = self.editor
        self.pending_application = (w.source_session, w.flow, w.edit_generation,
                                    w.run_path, w.symbol_path, tuple(records))
        self.last_result = None
        self.job = Job(lambda progress: correct_font(source, output, glyph, rule,
                                                     all_samples=all_samples, include_styles=include_styles,
                                                     progress=progress))
        self.job.signals.progress.connect(self.message.setText)
        self.job.signals.completed.connect(self.font_completed)
        self.job.signals.failed.connect(self.font_failed)
        self.set_ready(False)
        self.message.setText("正在另存并完整校验校正字体；请等待完成。")
        QtCore.QThreadPool.globalInstance().start(self.job)

    def font_completed(self, result):
        self.last_result, self.job = result, None
        pending, self.pending_application = self.pending_application, None
        w = self.editor
        if pending and (w.source_session is pending[0] and w.flow == pending[1] and
                        w.edit_generation == pending[2] and w.run_path == pending[3] and
                        w.symbol_path == pending[4]):
            self.commit(pending[5])
            result["document_applied"] = True
            self.message.setText(f"本文校正已应用，新字体已另存：{result['path']}。\n"
                                 "本文保留原字体快照，不重复叠加；新字体可从字体库导入后使用。")
        else:
            result["document_applied"] = False
            self.message.setText(f"新字体已另存：{result['path']}。\n"
                                 "处理期间文档已变化，未自动应用本文校正，请重新选择后应用。")
        self.set_ready(self.editor.canvas.isEnabled())

    def font_failed(self, message):
        self.job = None
        self.pending_application = None
        self.message.setText("字体校正未完成：" + message)
        self.set_ready(self.editor.canvas.isEnabled())
