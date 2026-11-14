"""Markdown integration for the existing source/review/page window."""

from __future__ import annotations

import os
import sys
import threading
from contextlib import nullcontext
from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

from PySide6 import QtCore, QtGui, QtWidgets

from ..assets.glyph_provider import GlyphProvider, is_han
from ..assets.resolver import AssetResolver
from ..assets.symbol_provider import SymbolProvider
from ..document.editing import SourceSession
from ..document.limits import DocumentLimitError, validate_nodes, validate_snapshot
from ..document.markdown import parse_markdown
from ..document.package import load_package, save_package
from ..document.schema import SourceSpan, digest, new_id
from ..document.source import scalar_to_utf16, utf16_to_scalar
from ..document.table_import import import_table_project
from ..document.table_style import calibrate_tables
from ..fonts.identity import release_identity
from ..fonts.preview_candidates import PreviewCandidates, PreviewFontError
from ..document.tables import table_model
from ..layout.blocks import layout_markdown
from ..layout.continuation import continuation_scope
from ..layout.inline import LayoutCancelled, check_cancel
from ..layout.measurement_cache import measurement_scope
from ..plotter.adapters import (
    can_export_with_image_omission,
    reference_image_export_scope,
)
from .app import ReviewWindow, WorkerSignals
from .build_cache import (
    CachedLayout,
    MarkdownBuildCache,
    layout_key,
    parsed_weight,
    snapshot_weight,
    source_key,
)
from .review import RATINGS, Review, ReviewBook, SourceBuffer, atomic_write, file_hash, load_session
from .wrapping import WrappingLayout


def recovery_directory():
    private = os.environ.get("INKSTRUCT_LAYOUT_PREVIEW_HOME")
    if private:
        return Path(private).resolve() / "editor_recovery"
    if getattr(sys, "frozen", False):
        location = QtCore.QStandardPaths.writableLocation(QtCore.QStandardPaths.GenericDataLocation)
        if not location:
            raise ValueError("无法确定可写的用户恢复目录")
        return Path(location) / "InkStruct" / "editor_recovery"
    return Path.cwd() / "artifacts" / "editor_recovery"


def build_markdown(
    session, revision, resolver, run, symbols, page, style, flow, cancelled, cache=None,
    first_page=None,
):
    check_cancel(cancelled)
    source = source_key(session, flow.markdown_dialect)
    if flow.named_fields:
        source = (*source, "named-fields-v1")
    document = cache.parsed.get(source) if cache is not None else None
    if document is None:
        document = parse_markdown(session, dialect=flow.markdown_dialect, cancelled=cancelled,
                                  field_blocks=flow.named_fields)
        check_cancel(cancelled)
        if cache is not None:
            cache.parsed.put((source,), document, parsed_weight(session, document))
    document = replace(document, revision=revision)
    validate_nodes(document.nodes, cancelled=cancelled)
    visible = "".join(o.text for o in document.occurrences)
    resources = cache.resources if cache is not None else None
    embedded = tuple(g for pool in resolver.pools.values() for g in pool)
    font_glyphs = ()
    indexed = None
    font_identity = resolver.font_identity
    if run and Path(run).suffix == ".inkfont":
        from ..fonts.core import cached_font, verified_preview_font
        from ..symbol_capture import CHARACTERS
        characters = set(visible) | set(CHARACTERS)
        # Keep small documents on the existing resource path. Once a large
        # document has indexed choices, keep that path for subsequent edits.
        use_index = len(visible) >= 2048 or resolver.indexed is not None
        verified = verified_preview_font(run) if use_index and not symbols else None
        font = verified or cached_font(Path(run))
        current_identity = release_identity(font.identity)
        if font_identity is not None and font_identity != current_identity:
            raise ValueError('已连接的字体文件版本发生变化，请重新连接原版本或确认更换字体。')
        font_identity = current_identity
        if verified:
            deferred = {c for c in characters if is_han(c)}
            # Embedded candidates from other sources can affect tie order or
            # survive a release change. Keep their original eager merge.
            deferred.difference_update(g.character for g in embedded
                                       if getattr(g, "_preview_font_token", None) != font.preview_token)
            if deferred:
                indexed = PreviewCandidates(font, deferred,
                                            cache.font_trajectories if cache is not None else None,
                                            cancelled)
                characters -= deferred
        font_glyphs = tuple(font.glyphs(characters, reuse=embedded, cancelled=cancelled))
        generated = None
    else:
        generated = GlyphProvider.from_run(Path(run), visible, cache=resources) if run else None
    check_cancel(cancelled)
    samples = SymbolProvider.from_zip(Path(symbols), cache=resources) if symbols else None
    check_cancel(cancelled)
    resolved = AssetResolver(
        generated,
        samples,
        seed=resolver.seed,
        selections=resolver.selections.values(),
        embedded=(*embedded, *font_glyphs),
        builtin_numbers=True,
        font_identity=font_identity,
        indexed=indexed,
    )
    full_cache = cache is not None and indexed is None
    key = layout_key(source, resolved, page, style, flow) if full_cache else None
    cached = cache.layouts.get(key) if full_cache else None
    if cached is None:
        preview_page = None
        try:
            with indexed.opened() if indexed else nullcontext():
                if first_page and indexed:
                    prefix = stable_han_prefix(document, flow)
                    if prefix:
                        selections = dict(resolved.selections)
                        try:
                            draft = layout_markdown(prefix, resolved, page=page,
                                                    style=style, flow=flow, cancelled=cancelled)
                        except DocumentLimitError:
                            pass
                        else:
                            # Do not show a page that still contains the prefix's
                            # last line. It may change when the paragraph continues.
                            last = prefix.occurrences[-1].occurrence_id
                            if any(f.occurrence_id == last for p in draft.pages[1:] for f in p.fragments):
                                check_cancel(cancelled)
                                preview_page = draft.pages[0]
                                first_page(replace(draft, pages=draft.pages[:1]))
                        finally:
                            # Keep checked ink, but replay selection for the
                            # complete document, including synthetic occurrences.
                            resolved.selections = selections
                with (
                    measurement_scope(cache.measurements if cache is not None else None),
                    continuation_scope(cache.continuation if cache is not None else None),
                ):
                    snapshot = layout_markdown(
                        document, resolved, page=page, style=style, flow=flow, cancelled=cancelled
                    )
        except PreviewFontError as error:
            raise ValueError(str(error)) from error
        check_cancel(cancelled)
        if preview_page is not None and snapshot.pages and snapshot.pages[0] == preview_page:
            snapshot = replace(snapshot, pages=(preview_page, *snapshot.pages[1:]))
        if full_cache:
            after = layout_key(source, resolved, page, style, flow)
            cache.layouts.put(
                (key, after),
                CachedLayout(snapshot, tuple(resolved.selections.values())),
                snapshot_weight(snapshot, session, resolved),
            )
    else:
        snapshot = replace(cached.snapshot, revision=revision)
        resolved.selections = {s.occurrence_id: s for s in cached.selections}
    check_cancel(cancelled)
    validate_snapshot(snapshot, cancelled=cancelled)
    if indexed:
        # The inspector may ask for another sample after this request ends.
        indexed.cancelled = None
    lookup = {g.asset_id: g for pool in resolved.pools.values() for g in pool}
    return {
        "document": document,
        "resolver": resolved,
        "snapshot": snapshot,
        "asset_lookup": lookup,
        "provider": SimpleNamespace(assets={c: p[0] for c, p in resolved.pools.items()}),
    }


def stable_han_prefix(document, flow):
    """A plain single paragraph has no cross-page dependencies or trailing syntax."""
    if (len(document.source) < 2048 or len(document.nodes) != 1 or document.diagnostics
            or flow.glyph_corrections or flow.template_bindings
            or (flow.template and not flow.named_fields)
            or not all(is_han(c) for c in document.source)):
        return None
    paragraph = document.nodes[0]
    if paragraph.kind != "paragraph" or len(paragraph.children) != 1:
        return None
    inline = paragraph.children[0]
    if inline.kind != "inline" or len(inline.children) != 1:
        return None
    leaf = inline.children[0]
    if leaf.kind != "text" or len(leaf.occurrences) != len(document.source):
        return None
    end = 1024
    span = SourceSpan(0, end)
    leaf = replace(leaf, span=span, occurrences=leaf.occurrences[:end], raw_content=document.source[:end])
    inline = replace(inline, span=span, children=(leaf,))
    paragraph = replace(paragraph, span=span, children=(inline,))
    return replace(document, source=document.source[:end], nodes=(paragraph,))


class MarkdownSignals(WorkerSignals):
    first_page = QtCore.Signal(object)


def startup_page(arguments, *, first_only=False):
    """Build a display-only first page without opening the default font."""
    flow = arguments["flow"]
    template = flow.template
    if (arguments["session"].source or not (arguments["run"] or arguments["symbols"])
            or (template is not None and not flow.named_fields)):
        return None
    needs_ink = False
    if template is not None:
        first = template.layout(0)
        needs_ink = any(frame.role == "page_number" for frame in first.frames)
        if needs_ink:
            paper = replace(first, frames=tuple(f for f in first.frames if f.role != "page_number"))
            template = replace(template, layouts=tuple(
                paper if layout.layout_id == first.layout_id else layout
                for layout in template.layouts
            ))
            flow = replace(flow, template=template)
        if first_only and template.kind == "custom":
            flow = replace(flow, template=replace(
                template, start_pages=(first.layout_id,), finish_cycle=False
            ))
    draft = build_markdown(**{**arguments, "run": "", "symbols": "", "flow": flow, "cache": None})
    snapshot = draft["snapshot"]
    if not snapshot.pages:
        return None
    page = snapshot.pages[0]
    image = None
    # TemplateBackground already verifies the PNG and caps its decoded size.
    # A background-only page needs neither an SVG nor the raster process.
    if (snapshot.exportable and page.background and not
            (page.fragments or page.paint_ops or page.preview_ops or page.images)):
        image = QtGui.QImage.fromData(page.background.png_bytes(), "PNG")
        if image.isNull():
            image = None
    return (replace(snapshot, pages=(page,)),
            "startup-paper" if needs_ink else "startup-page", image)


class MarkdownWorker(QtCore.QRunnable):
    def __init__(self, key, revision, arguments, *, startup=False):
        super().__init__()
        self.key, self.revision, self.arguments = key, revision, arguments
        self.signals = MarkdownSignals()
        self.startup = startup

    def run(self):
        result = {"key": self.key, "revision": self.revision}
        try:
            early = None
            if self.startup:
                try:
                    early = startup_page(self.arguments)
                except (ValueError, OSError, KeyError, TypeError):
                    # Report any errors through the ordinary full preview.
                    pass
                if early is not None:
                    check_cancel(self.arguments["cancelled"])
                    self.signals.first_page.emit((self.key, self.revision, *early))
            built = build_markdown(**self.arguments, first_page=lambda snapshot:
                                   self.signals.first_page.emit((self.key, self.revision, snapshot)))
            snapshot = built["snapshot"]
            if early and snapshot.pages and early[0].pages[0] == snapshot.pages[0]:
                built["snapshot"] = replace(snapshot, pages=(early[0].pages[0], *snapshot.pages[1:]))
            result.update(built)
        except LayoutCancelled:
            pass
        except DocumentLimitError as error:
            result.update(error=str(error), limit=True)
        except Exception as error:  # noqa: BLE001 - transport worker errors to GUI
            result["error"] = str(error)
        self.signals.finished.emit(result)


class RecoveryWorker(QtCore.QRunnable):
    def __init__(self, request, arguments):
        super().__init__()
        self.request, self.arguments = request, arguments
        self.signals = WorkerSignals()

    def run(self):
        result = dict(self.request)
        try:
            result['hash'] = save_package(result['path'], **self.arguments)
        except Exception as error:  # noqa: BLE001 - transport worker errors to GUI
            result['error'] = str(error)
        self.signals.finished.emit(result)


class ProjectSaveWorker(QtCore.QRunnable):
    def __init__(self, path, expected, inspect_destination, arguments, optimize, reviews):
        super().__init__()
        self.path, self.expected = path, expected
        self.inspect_destination = inspect_destination
        self.arguments, self.optimize, self.reviews = arguments, optimize, reviews
        self.signals = WorkerSignals()

    def run(self):
        result = {}
        try:
            path = self.path
            expected = file_hash(path) if self.inspect_destination else self.expected
            args = self.arguments
            try:
                resolver = build_markdown(**args)["resolver"]
            except DocumentLimitError:
                result['limited'] = True
                resolver = args['resolver']
            try:
                old_data = path.read_bytes()
            except FileNotFoundError:
                old_data = None
            if (sha256(old_data).hexdigest() if old_data is not None else None) != expected:
                raise ValueError("文件已被其他程序修改，请另存为新文件")
            if old_data is not None:
                previous = path.with_name(path.name + ".previous.inkdoc")
                atomic_write(previous, old_data, file_hash(previous))
            del old_data
            result['hash'] = save_package(path, args['session'], resolver, args['page'], args['style'],
                                          flow=args['flow'], optimize=self.optimize,
                                          expected_hash=expected, reviews=self.reviews)
            result['resolver'] = resolver
        except Exception as error:  # noqa: BLE001 - report failure on the GUI thread
            result['error'] = str(error)
        self.signals.finished.emit(result)


class MixedWindow(ReviewWindow):
    project_save_finished = QtCore.Signal(bool)

    def __init__(self, *, source="", run=None, symbols=None, mode="markdown", parent=None):
        self.integrated = False
        self.export_job = None
        self.export_progress = None
        self.export_preparing = False
        self.export_preference_epoch = 0
        self.loaded_style = None
        self.project_save = None
        self.project_save_pending = False
        self.project_save_dialog = False
        self.project_save_waiting = False
        super().__init__(source=source, run=run, parent=parent)
        self.timer.stop()
        self.source_session = SourceSession(source)
        self.document_started = bool(source)
        self.imported_image_edits = {}
        self.build_cache = MarkdownBuildCache()
        self.resolver = AssetResolver()
        self.asset_lookup = {}
        self.partial_revision = None
        self.partial_kind = ""
        self.startup_layout_pending = False
        self.startup_preview_key = None
        from ..global_defaults import GlobalDefaultsStore
        defaults, defaults_warning = GlobalDefaultsStore().for_new_document()
        self.flow = defaults.flow
        self.page, self.loaded_style = defaults.page, defaults.style
        if run is None:
            self.run_path = defaults.run
        if symbols:
            self.flow = calibrate_tables(self.flow, SymbolProvider.from_zip(Path(symbols)))
        self.symbol_path = str(Path(symbols).resolve()) if symbols else defaults.symbols
        self.mode = mode if mode != 'markdown' or source or run or symbols else defaults.mode
        self.markdown_document = None
        self.source_syncing = False
        self.source_error = None
        self.recovery_path = None
        self.recovery_hash = None
        self.recovery_worker = None
        self.recovery_epoch = 0
        self.recovery_pending = False
        self.edit_generation = 0
        self.recovery_timer = QtCore.QTimer(self)
        self.recovery_timer.setSingleShot(True)
        self.recovery_timer.setInterval(2000)
        self.recovery_timer.timeout.connect(self.start_recovery)
        self.integrated = True
        self.canvas.task_activated.connect(self.toggle_task)
        self.editor.setUndoRedoEnabled(False)
        self.editor.history_handler = self.source_history
        self.editor.document().contentsChange.connect(self.source_contents_changed)
        self.editor.input_transaction.connect(self.source_input_transaction)
        self._add_mixed_controls()
        for control, value in [(self.em, self.style.em_mm), (self.line_height, self.style.line_height_mm),
                               (self.stroke, self.style.stroke_width_mm)]:
            with QtCore.QSignalBlocker(control):
                control.setDecimals(6)
                control.setRange(min(control.minimum(), value), max(control.maximum(), value))
                control.setValue(value)
        if defaults_warning:
            self.status.setText(defaults_warning)
        self.schedule_layout()

        self.canvas._process.prewarm()

    def use_font(self, path):
        from ..fonts.core import cached_font
        cached_font(Path(path))
        self.run_path = str(Path(path).resolve())
        self.symbol_path = ""
        self.resolver = AssetResolver()
        self.mode = "markdown"
        self.mode_picker.setCurrentIndex(self.mode_picker.findData("markdown"))
        self.mark_dirty()
        self.schedule_layout()

    def current_font_warnings(self, *, pending_only=False):
        document = getattr(self, 'markdown_document', None)
        if document is None:
            return []
        ids = {o.occurrence_id for o in document.occurrences}
        owners = {n.node_id for root in document.nodes for n in root.walk()}
        ids.update(k for k in self.resolver.selections if any(k.startswith(owner + ':math-rule:') for owner in owners))
        return self.resolver.usage_warnings(pending_only=pending_only, occurrence_ids=ids)

    def show_font_warnings(self):
        warnings = self.current_font_warnings()
        if not warnings:
            QtWidgets.QMessageBox.information(self, "字体来源", "当前使用的字形没有来源或类别缺口。")
            return True
        lines = []
        for item in warnings:
            detail = "; ".join(item["reasons"])
            if item["reference_strokes"]:
                detail += " · 参考笔序 " + ",".join(map(str, item["reference_strokes"]))
            for gap in item["gaps"]:
                detail += f" · 第{gap['order']}笔：{gap['reason']}"
            lines.append(f"{item['character']}（{item['occurrences']}处）：{detail}")
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle("字体来源与字形类别提示")
        box.setText(f"当前使用的 {len(warnings)} 个字形候选含来源或类别缺口。可继续使用，无需立即补采。")
        box.setDetailedText("\n".join(lines))
        box.setStandardButtons(QtWidgets.QMessageBox.StandardButton.Ok | QtWidgets.QMessageBox.StandardButton.Cancel)
        box.button(QtWidgets.QMessageBox.StandardButton.Ok).setText("继续使用")
        if box.exec() == QtWidgets.QMessageBox.StandardButton.Ok:
            self.resolver.accept_usage_warnings()
            self.mark_dirty()
            return True
        return False

    def _add_mixed_controls(self):
        self.page_picker.setMinimumWidth(120)
        self.summary.setMinimumHeight(42)
        row = WrappingLayout()
        self.mode_picker = QtWidgets.QComboBox()
        self.mode_picker.addItem("Markdown 混排", "markdown")
        self.mode_picker.addItem("纯文本检查", "plain-text")
        self.mode_picker.setCurrentIndex(self.mode_picker.findData(self.mode))
        self.mode_picker.currentIndexChanged.connect(self.mode_changed)
        row.add_group(QtWidgets.QLabel("内容模式"), self.mode_picker)
        self.dialect_picker = QtWidgets.QComboBox()
        self.dialect_picker.addItem("普通 Markdown", "markdown")
        self.dialect_picker.addItem("Obsidian 静态扩展", "obsidian")
        self.dialect_picker.setToolTip(
            "双链显示文字；Callout 展开；嵌入仅显示显式标签，不读取库内容"
        )
        self.dialect_picker.currentIndexChanged.connect(self.dialect_changed)
        row.addWidget(self.dialect_picker)
        self.button("撤销正文", lambda: self.source_history("undo"), row)
        self.button("重做正文", lambda: self.source_history("redo"), row)
        self.optimize = QtWidgets.QCheckBox("优化路径（自动允许反转）")
        self.optimize.setChecked(True)
        self.optimize.toggled.connect(self.mark_dirty)
        self.optimize.toggled.connect(self.export_preference_changed)
        self.optimize.hide()  # Saved document preference, edited by the export dialog.
        self.machine_export = self.button("导出写字机 SVG…", self.export_machine, row)
        self.force_machine_export = self.button("强制导出 SVG…", self.export_machine_forced, row)
        self.force_machine_export.setToolTip("仅导出已有有效笔迹，缺失处留空，并附问题清单；不宣称为完整成品。")
        self.button("打开恢复副本…", self.open_recovery, row)
        self.centralWidget().layout().insertLayout(2, row)
        settings = WrappingLayout()
        self.flow_controls = {}
        for name, title in (
            ("paragraph_gap_mm", "段距"),
            ("heading_gap_mm", "标题段距"),
            ("first_line_indent_mm", "首行缩进"),
            ("list_indent_mm", "列表缩进"),
            ("quote_indent_mm", "引用缩进"),
        ):
            control = QtWidgets.QDoubleSpinBox()
            control.setRange(0.5 if name in {"list_indent_mm", "quote_indent_mm"} else 0, 100)
            control.setSingleStep(0.5)
            control.setValue(getattr(self.flow, name))
            control.valueChanged.connect(self.flow_changed)
            self.flow_controls[name] = control
            settings.add_group(QtWidgets.QLabel(title + " mm"), control)
        self.button("标题字号…", self.heading_settings, settings)
        self.math_settings_button = self.button("公式设置…", self.math_settings, settings)
        self.code_settings_button = self.button("代码设置…", self.code_settings, settings)
        self.template_settings_button = self.button("页面模板…", self.template_settings, settings)
        self.image_settings_button = self.button("图片设置…", self.image_settings, settings)
        self.centralWidget().layout().insertLayout(4, settings)
        navigation = WrappingLayout()
        self.block_picker = QtWidgets.QComboBox()
        self.block_picker.setMinimumWidth(200)
        self.block_picker.setSizeAdjustPolicy(
            QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon
        )
        self.block_picker.setMinimumContentsLength(14)
        self.block_picker.activated.connect(self.navigate_block)
        self.diagnostic_picker = QtWidgets.QComboBox()
        self.diagnostic_picker.setMinimumWidth(260)
        self.diagnostic_picker.setSizeAdjustPolicy(
            QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon
        )
        self.diagnostic_picker.setMinimumContentsLength(20)
        self.diagnostic_picker.activated.connect(self.navigate_diagnostic)
        self.diagnostic_picker.currentIndexChanged.connect(self.update_diagnostic_action)
        navigation.add_group(QtWidgets.QLabel("正文块"), self.block_picker)
        self.table_settings_button = self.button("表格设置…", self.table_settings, navigation)
        self.footnote_settings_button = self.button("脚注设置…", self.footnote_settings, navigation)
        navigation.add_group(QtWidgets.QLabel("诊断"), self.diagnostic_picker)
        self.repair_template_button = self.button(
            "修正模板…", self.repair_template_diagnostic, navigation
        )
        self.repair_template_button.setEnabled(False)
        self.template_fit_button = self.button("适配报告…", self.template_fit_report, navigation)
        self.template_fit_button.setEnabled(False)
        self.centralWidget().layout().insertLayout(5, navigation)
        labels = {
            "打开文本…": "打开源码…",
            "保存文本…": "保存源码…",
            "打开检查项目…": "打开项目…",
            "保存检查项目": "保存项目",
        }
        for button in self.findChildren(QtWidgets.QPushButton):
            if button.text() in labels:
                button.setText(labels[button.text()])
        for label in self.findChildren(QtWidgets.QLabel):
            if label.text() == "纯文本正文":
                label.setText("可编辑源码 · 页面点击可定位")
        self.editor.setPlaceholderText("输入 Markdown 源码或纯文本。缺少字形时会显示诊断。")
        self.update_mode_controls()
        from .workspace import organize_workspace

        organize_workspace(self)

    def update_mode_controls(self):
        markdown = self.mode == "markdown"
        for control in (
            *self.flow_controls.values(),
            self.dialect_picker,
            self.block_picker,
            self.diagnostic_picker,
            self.table_settings_button,
            self.footnote_settings_button,
            self.math_settings_button,
            self.code_settings_button,
            self.template_settings_button,
            self.image_settings_button,
        ):
            control.setEnabled(markdown)
        self.setWindowTitle(
            "InkStruct · "
            + ("Markdown 混排" if markdown else "纯文本字形检查")
            + (" *" if self.dirty else "")
        )

    def mark_dirty(self, *_):
        if not self.integrated:
            return super().mark_dirty()
        self.dirty = True
        self.edit_generation += 1
        if hasattr(self, "flow_controls"):
            self.update_mode_controls()
        self.recovery_timer.start()

    def source_contents_changed(self, position, removed, added):
        if self.source_syncing or not self.integrated or self.editor.ime_active:
            return
        old, new = self.buffer.display, self.editor.toPlainText()
        if old == new and (self.editor.composing or (not removed and not added)):
            return
        # Stop obsolete work before source mapping competes for the GUI thread's GIL.
        # The normal textChanged path still owns revision changes and publication guards.
        if self.cancelled:
            self.cancelled.set()
        try:
            old_units = scalar_to_utf16(old, len(old))
            new_units = scalar_to_utf16(new, len(new))
            start = utf16_to_scalar(old, min(position, old_units))
            end = utf16_to_scalar(old, min(position + removed, old_units))
            new_start = utf16_to_scalar(new, min(position, new_units))
            new_end = utf16_to_scalar(new, min(position + added, new_units))
            offsets = self.buffer.boundaries()
            newline = (
                "\r\n" if "\r\n" in self.buffer.raw else "\r" if "\r" in self.buffer.raw else "\n"
            )
            inserted = new[new_start:new_end].replace("\n", newline)
            candidate = (
                self.buffer.raw[: offsets[start]] + inserted + self.buffer.raw[offsets[end] :]
            )
            if SourceBuffer(candidate).display != new:
                raise ValueError("编辑区间无法与源码对应，已停止更新和导出")
            self.source_session.apply(offsets[start], offsets[end], inserted)
            if hasattr(self, 'template_content_panel'):
                self.template_content_panel.source_edited()
            self.buffer = SourceBuffer(self.source_session.source)
            self.source_error = None
        except (ValueError, IndexError) as error:
            self.source_error = str(error)

    def source_input_transaction(self, transaction):
        # Qt's IME contentsChange can cover an entire block, including unchanged
        # text. Use the explicit preedit anchor and replacement range instead.
        old, new = self.buffer.display, self.editor.toPlainText()
        if old == new:
            return
        if self.cancelled:
            self.cancelled.set()
        try:
            start_units, end_units, relative, length, commit = transaction
            a, b = utf16_to_scalar(old, start_units), utf16_to_scalar(old, end_units)
            stripped = old[:a] + old[b:]
            left = utf16_to_scalar(stripped, start_units + relative)
            right = utf16_to_scalar(stripped, start_units + relative + length)
            expected = stripped[:left] + commit + stripped[right:]
            if expected != new:
                raise ValueError("输入法提交区间无法对应源码，已停止更新；撤销可恢复提交前内容")
            start = min(a, left if left <= a else left + b - a)
            end = max(b, right if right <= a else right + b - a)
            inserted = new[start : len(new) - (len(old) - end)]
            offsets = self.buffer.boundaries()
            newline = (
                "\r\n" if "\r\n" in self.buffer.raw else "\r" if "\r" in self.buffer.raw else "\n"
            )
            self.source_session.apply(offsets[start], offsets[end], inserted.replace("\n", newline))
            if hasattr(self, 'template_content_panel'):
                self.template_content_panel.source_edited()
            self.buffer = SourceBuffer(self.source_session.source)
            self.source_error = None
        except (ValueError, IndexError) as error:
            self.source_error = str(error)
        self.mark_dirty()
        self.schedule_layout()

    def text_changed(self):
        if not self.integrated:
            return super().text_changed()
        if self.source_syncing or self.editor.ime_active:
            return
        self.mark_dirty()
        self.schedule_layout()

    def source_history(self, direction):
        if self.editor.composing:
            return
        if hasattr(self, '_resource_history') and self._resource_history.route(direction):
            return
        if hasattr(self, 'template_content_panel') and self.template_content_panel.route_history(direction):
            return
        if self.source_error:
            self._display_session()
            self.source_error = None
            self.schedule_layout()
            return
        stack = self.source_session._undo if direction == "undo" else self.source_session._redo
        edit = stack[-1] if stack else None
        if getattr(self.source_session, direction)():
            transaction = self.imported_image_edits.get(id(edit))
            if transaction:
                _, old_images, new_images = transaction
                self.flow = replace(self.flow, images=old_images if direction == "undo" else new_images)
            self._display_session()
            end = edit.start + len(edit.removed if direction == "undo" else edit.inserted)
            cursor = self.editor.textCursor()
            cursor.setPosition(
                scalar_to_utf16(self.buffer.display, self.buffer.raw_to_display(end))
            )
            self.editor.setTextCursor(cursor)
            self.source_error = None
            self.mark_dirty()
            self.schedule_layout()

    def _display_session(self):
        syncing_selection = self._syncing
        self._syncing = True
        self.source_syncing = True
        try:
            self.buffer = SourceBuffer(self.source_session.source)
            self.editor.setPlainText(self.buffer.display)
        finally:
            self.source_syncing = False
            self._syncing = syncing_selection

    def replace_text(self, source):
        if not self.integrated:
            return super().replace_text(source)
        self.source_session.apply(0, len(self.source_session.source), source)
        self._display_session()
        self.mark_dirty()
        self.schedule_layout()

    def mode_changed(self):
        if self.run_path and Path(self.run_path).suffix == '.inkfont' and self.mode_picker.currentData() != 'markdown':
            self.mode_picker.setCurrentIndex(self.mode_picker.findData('markdown'))
            self.status.setText('字体包使用 Markdown 模式；普通文字可直接输入。')
            return
        self.mode = self.mode_picker.currentData()
        self.session_path = self.session_hash = None
        self.mark_dirty()
        self.schedule_layout()

    def dialect_changed(self):
        self.flow = replace(self.flow, markdown_dialect=self.dialect_picker.currentData())
        self.mark_dirty()
        self.schedule_layout()

    def flow_changed(self):
        changed = {k: c.value() for k, c in self.flow_controls.items() if c is self.sender()}
        self.flow = replace(self.flow, **changed)
        self.mark_dirty()
        self.schedule_layout()

    @property
    def style(self):
        return self.loaded_style or super().style

    def settings_changed(self):
        if self.loaded_style:
            fields = {
                self.em: "em_mm",
                self.line_height: "line_height_mm",
                self.stroke: "stroke_width_mm",
            }
            control = self.sender()
            if control in fields:
                self.loaded_style = replace(self.loaded_style, **{fields[control]: control.value()})
        super().settings_changed()

    def heading_settings(self):
        value, ok = QtWidgets.QInputDialog.getText(
            self,
            "标题字号倍率",
            "H1 至 H6，逗号分隔",
            text=", ".join(str(v) for v in self.flow.heading_scales),
        )
        if ok:
            try:
                self.flow = replace(
                    self.flow, heading_scales=tuple(float(v.strip()) for v in value.split(","))
                )
                self.mark_dirty()
                self.schedule_layout()
            except ValueError as error:
                self.message_error(error)

    def math_settings(self):
        from .math_settings import MathSettingsDialog

        dialog = MathSettingsDialog(
            self.flow.math, self, resolver=self.resolver, stroke_width=self.style.stroke_width_mm,
            font_path=self.run_path,
        )
        try:
            if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
                self.flow = replace(self.flow, math=dialog.configuration())
                self.mark_dirty()
                self.schedule_layout()
        finally:
            dialog.deleteLater()

    def footnote_settings(self):
        from .footnote_settings import FootnoteSettingsDialog

        dialog = FootnoteSettingsDialog(self.flow.footnote, self)
        try:
            if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
                configured = dialog.configuration()
                if configured != self.flow.footnote:
                    self.flow = replace(self.flow, footnote=configured)
                    self.mark_dirty()
                    self.schedule_layout()
        finally:
            dialog.deleteLater()

    def code_settings(self):
        from .code_settings import CodeSettingsDialog

        dialog = CodeSettingsDialog(self.flow.code, self)
        if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            self.flow = replace(self.flow, code=dialog.configuration())
            self.mark_dirty()
            self.schedule_layout()

    def parse_current_source(self):
        try:
            return parse_markdown(self.source_session, dialect=self.flow.markdown_dialect,
                                  field_blocks=self.flow.named_fields)
        except DocumentLimitError as error:
            self.message_error(error)
            return None

    def template_settings(self, *, target=None, reason=""):
        from ..document.flow_template import FlowTemplate
        if isinstance(self.flow.template, FlowTemplate):
            from .template_manager import perform_template_action
            return perform_template_action(self, 'document', self.flow.template, target=target)
        from .template_settings import TemplateSettingsDialog

        # Parse the current authoritative source instead of a possibly stale
        # worker result. Bindings refer to complete source nodes, not UI labels.
        document = self.parse_current_source()
        if document is None:
            return
        dialog = TemplateSettingsDialog(
            self.flow.template,
            self,
            document=document,
            bindings=self.flow.template_bindings,
            target=target,
            reason=reason,
        )
        try:
            if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
                self.flow = replace(
                    self.flow,
                    template=dialog.configuration(),
                    template_bindings=dialog.binding_configuration(),
                )
                self.mark_dirty()
                self.schedule_layout()
        finally:
            # Dispose through Qt's event loop, including cancelled dialogs.
            # Keeping hidden child dialogs until interpreter teardown can cause
            # QObject ownership failures and retains large source/background data.
            dialog.deleteLater()

    def image_settings(self):
        from .image_settings import ImageSettingsDialog

        document = self.parse_current_source()
        if document is None:
            return
        dialog = ImageSettingsDialog(document, self.flow, self)
        try:
            if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
                self.flow = dialog.configuration()
                self.mark_dirty()
                self.schedule_layout()
        finally:
            dialog.deleteLater()

    def set_run(self, path):
        self.resolver = AssetResolver()
        super().set_run(path)

    def schedule_layout(self):
        self.startup_layout_pending = False
        keep_startup = (self.integrated and self.startup_preview_key is not None
                        and not self.source_session.source
                        and self.startup_preview_key == self.startup_inputs())
        if self.integrated and self.partial_revision is not None and not keep_startup:
            self.partial_revision = None
            self.partial_kind = ""
            self.startup_preview_key = None
            if self.snapshot:
                self.canvas.load_page(self.snapshot, self.page_picker.value() - 1)
            else:
                self.canvas.clear_document()
            self.page_picker.setEnabled(True)
        super().schedule_layout()
        if keep_startup:
            self.partial_revision = self.revision
            self.canvas.load_page(replace(self.canvas.snapshot, revision=self.revision), 0)
        if self.integrated and self.mode == "markdown":
            if not keep_startup:
                self.status.setText("正在更新 Markdown 分页预览…旧快照暂不可标记或导出")
            self.run_label.setText(
                "汉字："
                + (self.run_path or "项目内嵌资源")
                + " · 符号："
                + (self.symbol_path or "项目内嵌 / 内置数字")
            )
            if self.source_error:
                self.timer.stop()
                self.status.setText(self.source_error)

    def begin_startup_preview(self):
        self.startup_layout_pending = self.mode == "markdown" and not self.source_session.source
        if self.startup_layout_pending and not self.source_error:
            # Prepare the bounded, background-only PDF before scheduling the
            # first font job. A show-time relayout must not put it behind I/O.
            template = self.flow.template
            if (template and self.flow.named_fields and template.layout(0).background
                    and (self.run_path or self.symbol_path)):
                try:
                    draft = startup_page(self.build_arguments(), first_only=True)
                except (ValueError, OSError, KeyError, TypeError):
                    draft = None
                if draft is not None and draft[2] is not None:
                    self.startup_preview_key = self.startup_inputs()
                    self.show_partial_page(*draft)
                    self.startup_layout_pending = False
            self.timer.start(0)

    def startup_inputs(self):
        return (self.source_session.document_id, self.mode, self.page, self.style,
                self.flow, self.run_path, self.symbol_path)

    def build_arguments(self):
        return {
            "session": SourceSession.restore(
                self.source_session.source, self.source_session.identity_record()
            ),
            "revision": self.revision,
            "resolver": self.resolver,
            "run": self.run_path,
            "symbols": self.symbol_path,
            "page": self.page,
            "style": self.style,
            "flow": self.flow,
            "cancelled": threading.Event(),
            "cache": self.build_cache,
        }

    def launch_layout(self):
        if not self.integrated or self.mode == "plain-text":
            return super().launch_layout()
        if self.closed or self.editor.composing or self.worker or self.source_error:
            return
        args = self.build_arguments()
        key = digest([self.revision, self.mode, self.source_session.document_id])
        self.current_key, self.cancelled = key, args["cancelled"]
        self.worker = MarkdownWorker(key, self.revision, args, startup=self.startup_layout_pending)
        self.startup_layout_pending = False
        self.worker.signals.finished.connect(self.publish)
        self.worker.signals.first_page.connect(self.publish_first_page)
        self.pool.start(self.worker)

    @QtCore.Slot(object)
    def publish_first_page(self, result):
        key, revision, snapshot, *kind = result
        if self.closed or key != self.current_key or revision != self.revision or not self.worker:
            return
        self.show_partial_page(snapshot, *kind)

    def show_partial_page(self, snapshot, kind="", startup_image=None):
        self.partial_revision = snapshot.revision
        self.partial_kind = kind
        with QtCore.QSignalBlocker(self.page_picker):
            self.page_picker.setRange(1, 1)
            self.page_picker.setSuffix(" / … 页")
        self.page_picker.setEnabled(False)
        if startup_image is not None:
            self.canvas.load_page(snapshot, 0, startup_image=startup_image)
        else:
            self.canvas.load_page(snapshot, 0)
        self.status.setText({
            "startup-paper": "正在加载首页内容 · 正在校验默认字体资源",
            "startup-page": "首页预览 · 正在校验默认字体资源",
        }.get(self.partial_kind, "仍在排版 · 已排定首页 · 总页数待定"))

    def publish(self, result):
        accepted = result["revision"] == self.revision and result["key"] == self.current_key
        if accepted and "resolver" in result:
            if self.startup_preview_key is not None and self.partial_revision == self.revision:
                early = self.canvas.snapshot.pages[0]
                snapshot = result["snapshot"]
                if snapshot.pages and snapshot.pages[0] == early:
                    result["snapshot"] = replace(snapshot, pages=(early, *snapshot.pages[1:]))
            self.startup_preview_key = None
            self.partial_revision = None
            self.partial_kind = ""
            self.page_picker.setEnabled(True)
            self.resolver = result["resolver"]
            self.asset_lookup = result["asset_lookup"]
            self.markdown_document = result["document"]
        super().publish(result)
        if accepted and hasattr(self, 'element_inspector'):
            self.element_inspector.refresh()
            self.glyph_inspector.refresh()
        if accepted and "snapshot" in result:
            with QtCore.QSignalBlocker(self.block_picker):
                self.block_picker.clear()
                for root in (self.markdown_document.nodes if self.mode=="markdown" and self.markdown_document else ()):
                    for node in root.walk():
                        if node.kind in {"heading", "paragraph", "table", "html_block", "fence"}:
                            label = self.buffer.raw[node.span.start : node.span.end].replace(
                                "\n", " "
                            )[:45]
                            self.block_picker.addItem(node.kind + " · " + label, node.span)
            with QtCore.QSignalBlocker(self.diagnostic_picker):
                self.diagnostic_picker.clear()
                for d in self.snapshot.diagnostics:
                    self.diagnostic_picker.addItem(d.code+" · "+d.message,d)
                if not self.snapshot.diagnostics:
                    self.diagnostic_picker.addItem("无诊断",None)
            self.problems_panel.refresh(self.snapshot,self.buffer.raw,
                                        font_warnings=bool(self.current_font_warnings()),
                                        notice=getattr(self,"project_migration_notice",""))
            self.update_diagnostic_action()
            errors=sum(len(g.diagnostics) for g in self.problems_panel.groups if g.severity=="error")
            warnings=sum(max(1,len(g.diagnostics)) for g in self.problems_panel.groups if g.severity=="warning")
            stopped=any(d.code=="template-body-no-progress" for d in self.snapshot.diagnostics)
            state="预览已停止 · 后续正文尚未排版" if stopped else "预览已更新"
            self.status.setText(f"{state} · {len(self.snapshot.pages)} 页 · {errors} 处需处理 · {warnings} 条提醒")
            if self.dirty:
                self.recovery_timer.start()
        elif accepted and "error" in result:
            self.problems_panel.set_failure(result["error"],self.buffer.raw)
            detail = result["error"] if result.get("limit") else "打开问题面板查看原因"
            state = ("仅显示首页底图" if self.partial_kind == "startup-paper" else
                     "仅显示首页" if self.partial_revision == self.revision else "预览未完成")
            self.status.setText(f"{state} · {detail}")

    def set_ready(self, ready):
        super().set_ready(ready)
        if hasattr(self, "glyph_inspector"):
            self.glyph_inspector.set_ready(ready)
        if hasattr(self, "element_inspector"):
            self.element_inspector.set_ready(ready)
        if hasattr(self, "machine_export"):
            self.machine_export.setEnabled(
                bool(ready and self.snapshot and can_export_with_image_omission(self.snapshot)
                     and self.export_job is None)
            )
        if hasattr(self, "force_machine_export"):
            self.force_machine_export.setEnabled(bool(ready and self.snapshot and self.export_job is None))
        self.update_diagnostic_action()

    def current_table(self):
        if (
            not self.markdown_document
            or self.mode != "markdown"
            or not self.canvas.isEnabled()
            or self.source_syncing
            or self.editor.toPlainText() != self.buffer.display
        ):
            return None
        offset = utf16_to_scalar(self.buffer.display, self.editor.textCursor().selectionStart())
        raw = self.buffer.boundaries()[offset]
        return next(
            (
                n
                for root in self.markdown_document.nodes
                for n in root.walk()
                if n.kind == "table" and n.span.start <= raw < n.span.end
            ),
            None,
        )

    def toggle_task(self, fragment):
        from ..document.tasks import task_patch

        if (
            not self.integrated
            or self.mode != "markdown"
            or self.editor.composing
            or self.source_error
            or not self.canvas.isEnabled()
            or not self.snapshot
            or self.snapshot.revision != self.revision
            or not self.markdown_document
            or self.markdown_document.source != self.source_session.source
            or fragment.status not in {"task-checked", "task-unchecked"}
            or fragment not in self.snapshot.fragments
        ):
            return
        document = self.parse_current_source()
        if document is None:
            return
        start, end, inserted = task_patch(document, fragment.occurrence_id)
        self.source_session.apply(start, end, inserted, expected_revision=document.revision)
        self._display_session()
        cursor = self.editor.textCursor()
        cursor.setPosition(scalar_to_utf16(self.buffer.display, self.buffer.raw_to_display(start)))
        cursor.setPosition(
            scalar_to_utf16(self.buffer.display, self.buffer.raw_to_display(end)),
            QtGui.QTextCursor.MoveMode.KeepAnchor,
        )
        self.editor.setTextCursor(cursor)
        self.mark_dirty()
        self.schedule_layout()

    def table_settings(self):
        from .table_settings import TableSettingsDialog

        document = self.parse_current_source()
        if document is None:
            return
        node = self.current_table()
        tables = [n for root in document.nodes for n in root.walk() if n.kind == "table"]
        dialog = TableSettingsDialog(
            self.flow,
            node.node_id if node else None,
            table_model(node).columns if node else None,
            self,
            tables=[(n.node_id, table_model(n).columns, f"表格 {i}（{table_model(n).columns} 列）")
                    for i, n in enumerate(tables, 1)],
        )
        try:
            if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
                self.apply_table_settings(*dialog.configuration())
        finally:
            dialog.deleteLater()

    def apply_table_settings(self, target, style):
        if target:
            overrides = dict(self.flow.table_overrides)
            if style is None:
                overrides.pop(target, None)
            else:
                overrides[target] = style
            self.flow = replace(self.flow, table_overrides=tuple(overrides.items()))
        else:
            self.flow = replace(self.flow, table=style)
        self.mark_dirty()
        self.schedule_layout()

    def export_document(self):
        if self.current_font_warnings(pending_only=True) and not self.show_font_warnings():
            return
        return super().export_document()

    def load_all(self):
        if self.run_path and Path(self.run_path).suffix == '.inkfont':
            from ..fonts.core import cached_font
            self.replace_text(''.join(sorted(cached_font(self.run_path).pools)))
            return
        return super().load_all()

    def asset_for_fragment(self, fragment):
        if self.integrated and self.mode == "markdown":
            return self.asset_lookup.get(fragment.asset_id)
        return super().asset_for_fragment(fragment)

    def select_fragment(self, fragment, *, sync_source=True):
        super().select_fragment(fragment, sync_source=sync_source)
        if hasattr(self, "glyph_inspector") and self.canvas.isEnabled():
            self.glyph_inspector.select(fragment)
            is_image = fragment.status in {"image-vector", "image-reference", "image-missing"}
            if sync_source and (fragment.asset_id or is_image):
                self.properties_tabs.setCurrentIndex(0 if is_image else 1)
                self.element_properties_dock.show()
                self.element_properties_dock.raise_()

    def navigate_span(self, span):
        if not isinstance(span, SourceSpan):
            return
        if hasattr(self, "workspace_views"):
            self.workspace_views.focus_source()
        cursor = self.editor.textCursor()
        cursor.setPosition(
            scalar_to_utf16(self.buffer.display, self.buffer.raw_to_display(span.start))
        )
        cursor.setPosition(
            scalar_to_utf16(self.buffer.display, self.buffer.raw_to_display(span.end)),
            QtGui.QTextCursor.MoveMode.KeepAnchor,
        )
        self.editor.setTextCursor(cursor)
        self.editor.ensureCursorVisible()
        if self.snapshot and self.canvas.isEnabled():
            for f in self.snapshot.fragments:
                if span.start <= f.span.start < span.end:
                    self.select_fragment(f, sync_source=False)
                    break

    def navigate_block(self, *_):
        self.navigate_span(self.block_picker.currentData())

    def navigate_diagnostic(self, *_):
        diagnostic = self.diagnostic_picker.currentData()
        span = getattr(diagnostic, "span", diagnostic)
        if not getattr(diagnostic, "target", None) or (span and span.end > span.start):
            self.navigate_span(span)

    def update_diagnostic_action(self, *_):
        if not hasattr(self, "repair_template_button"):
            return
        diagnostic = self.diagnostic_picker.currentData()
        self.template_fit_button.setEnabled(
            bool(
                self.mode == "markdown"
                and self.flow.template
                and self.snapshot
                and self.markdown_document
                and self.canvas.isEnabled()
                and not self.source_syncing
                and self.editor.toPlainText() == self.buffer.display
            )
        )
        self.repair_template_button.setEnabled(
            bool(
                self.mode == "markdown"
                and self.canvas.isEnabled()
                and not self.source_syncing
                and self.editor.toPlainText() == self.buffer.display
                and getattr(diagnostic, "target", None)
            )
        )
        if hasattr(self,"problems_panel"):
            self.problems_panel.readiness_changed()

    def repair_template_diagnostic(self):
        self.update_diagnostic_action()
        if not self.repair_template_button.isEnabled():
            return
        diagnostic = self.diagnostic_picker.currentData()
        self.navigate_diagnostic()
        self.template_settings(target=diagnostic.target, reason=diagnostic.message)

    def template_fit_report(self):
        from ..document.template_fit import template_fit_report
        from .template_fit import TemplateFitDialog

        self.update_diagnostic_action()
        if not self.template_fit_button.isEnabled():
            return
        report = template_fit_report(self.markdown_document, self.flow, self.snapshot)
        key, revision = self.current_key, self.revision
        dialog = TemplateFitDialog(report, self.snapshot.diagnostics, self,
                                   omission_exportable=can_export_with_image_omission(self.snapshot))
        try:
            if (
                dialog.exec() == QtWidgets.QDialog.Accepted
                and key == self.current_key
                and revision == self.revision
            ):
                diagnostic = dialog.selected_diagnostic
                if diagnostic is not None:
                    target = getattr(diagnostic, "target", None)
                    if target:
                        if not self.flow.named_fields:
                            self.template_settings(target=target, reason=diagnostic.message)
                        elif diagnostic.code == 'template-field-required':
                            self.template_content_panel.edit(field_id=target.slot_id)
                        else:
                            self.navigate_span(diagnostic.span)
                            dialog.hide()
                            from .template_manager import perform_template_action
                            perform_template_action(self, "document", self.flow.template, target=target)
                    else:
                        self.navigate_span(diagnostic.span)
        finally:
            dialog.deleteLater()

    def confirm_image_omissions(self, scope):
        loaded = [i for i in scope['omitted_images'] if i['reason'] == 'loaded-raster']
        missing = [i for i in scope['omitted_images'] if i['reason'] == 'resource-not-loaded']
        dialog = QtWidgets.QMessageBox(self)
        dialog.setWindowTitle("导出 SVG：跳过非 SVG 图片")
        dialog.setIcon(QtWidgets.QMessageBox.Question)
        dialog.setText("导出的 SVG 不包含非 SVG 图片，包括尚未载入的图片；"
                       "保留当前预览中的图片占位与图题，导出其余可书写内容。")
        dialog.setInformativeText(f"已载入位图：{len(loaded)} 处；尚未载入的位图引用：{len(missing)} 处。\n"
                                  "可展开详情查看文件名。原文档、资源与缺失诊断保持不变。是否继续？")
        dialog.setDetailedText('\n\n'.join(
            title + '\n' + ('\n'.join(f"第 {i['page_number']} 页 · {i['display_name']}\n引用：{i['source']}" for i in items) or '无')
            for title, items in (('已载入位图', loaded), ('尚未载入的位图引用', missing))))
        dialog.setStandardButtons(QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.Cancel)
        dialog.button(QtWidgets.QMessageBox.Yes).setText("继续导出")
        dialog.button(QtWidgets.QMessageBox.Cancel).setText("取消")
        dialog.setDefaultButton(QtWidgets.QMessageBox.Cancel)
        try:
            return dialog.exec() == QtWidgets.QMessageBox.Yes
        finally:
            dialog.deleteLater()

    def configure_svg_export(self, snapshot, *, force=False):
        from .svg_export_dialog import SvgExportDialog
        dialog = SvgExportDialog(len(snapshot.pages), self.optimize.isChecked(), self, force=force)
        try:
            if dialog.exec() == QtWidgets.QDialog.Accepted:
                return dialog.options, dialog.optimize.isChecked()
            return None
        finally:
            dialog.deleteLater()

    def export_preference_changed(self, _value):
        self.export_preference_epoch += 1

    def export_machine_forced(self):
        return self.export_machine(force=True)

    def export_machine(self, *, force=False):
        if self.export_preparing:
            return
        if self.export_job is not None:
            if self.export_progress:
                self.export_progress.show()
                self.export_progress.raise_()
            return
        self.export_preparing = True
        try:
            self._configure_and_start_machine_export(force=force)
        finally:
            self.export_preparing = False

    def _configure_and_start_machine_export(self, *, force=False):
        if not force and self.current_font_warnings(pending_only=True) and not self.show_font_warnings():
            return
        if not self.snapshot or not self.canvas.isEnabled() or (not force and not can_export_with_image_omission(self.snapshot)):
            return
        snapshot = self.snapshot
        selected = self.configure_svg_export(snapshot, force=True) if force else self.configure_svg_export(snapshot)
        if selected is None:
            return
        options, optimize = selected
        if self.snapshot is not snapshot or not self.canvas.isEnabled():
            return
        from ..plotter.options import prepare_export
        scope = None if options.force else reference_image_export_scope(snapshot)
        if scope:
            scope = {**scope, 'omitted_images': [i for i in scope['omitted_images'] if i['page_index'] in options.pages]}
            if not scope['omitted_images']:
                scope = None
        if scope and not self.confirm_image_omissions(scope):
            return
        if self.snapshot is not snapshot or not self.canvas.isEnabled():
            return
        try:
            # Freeze geometry, page selection, omissions and calibration before
            # the destination picker can process arbitrary GUI events.
            plan, export_scope = prepare_export(snapshot, self.markdown_document, self.flow, options)
            if options.force:
                export_scope["font_usage_warnings"] = self.current_font_warnings()
        except ValueError as error:
            self.message_error(error)
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "指定新的强制 SVG 输出文件夹" if options.force else "指定新的写字机输出文件夹")
        if path:
            from .export_job import ExportJob, ExportProgress
            job = ExportJob(plan, Path(path), optimize=optimize, route_cache=self.build_cache.routes,
                            export_scope=export_scope, page_indices=options.pages, parent=self)
            self.export_job = job
            job.preference_epoch = self.export_preference_epoch
            job.source_session = self.source_session
            self.export_progress = ExportProgress(job, self)
            self.machine_export.setEnabled(False)
            self.force_machine_export.setEnabled(False)
            job.forced = options.force
            job.finished.connect(lambda: self.finish_machine_export(job, optimize, scope))
            self.export_progress.show()
            job.start()

    def finish_machine_export(self, job, optimize, scope):
        if self.export_job is not job:
            return
        result = self.last_export_result = job.result
        self.export_job = None
        self.export_progress.close()
        self.export_progress.deleteLater()
        self.export_progress = None
        job.deleteLater()
        self.set_ready(bool(self.snapshot and self.canvas.isEnabled()))
        if result['error']:
            self.message_error(result['error'])
        elif result['cancelled']:
            self.status.setText('SVG 导出已取消；未发布输出目录，文档与选样不变。')
        else:
            if (self.source_session is job.source_session and self.source_session.document_id == job.plan.document_id
                    and self.export_preference_epoch == job.preference_epoch):
                self.optimize.setChecked(optimize)
            self.status.setText(('已强制导出可用笔迹 SVG；缺失处留空，问题见 issues.txt / issues.json' if getattr(job, 'forced', False)
                                 else '已导出冻结排版的逐页写字机 SVG 和路径来源清单') +
                                (f"；已跳过 {len(scope['omitted_images'])} 处非 SVG 图片，保留占位与图题" if scope else '') +
                                ('；并行不可用，已串行重算未完成页' if result['routing']['fallback'] else ''))

    def new_document(self):
        if self.editor.composing or not self.confirm_discard():
            return
        from ..global_defaults import GlobalDefaultsStore

        defaults, warning = GlobalDefaultsStore().for_new_document()
        self.source_session = SourceSession()
        self.document_started = True
        self.document_id = self.source_session.document_id
        self.resolver = AssetResolver()
        self.book = ReviewBook()
        self.flow, self.page, self.loaded_style = defaults.flow, defaults.page, defaults.style
        self.run_path, self.symbol_path, self.mode = defaults.run, defaults.symbols, defaults.mode
        self.source_error = None
        self.project_migration_notice = ""
        self.session_path = self.session_hash = None
        self.imported_image_edits.clear()
        self.recovery_path = self.recovery_hash = None
        self.recovery_pending = False
        self.recovery_epoch += 1
        self.recovery_timer.stop()
        self.edit_generation += 1
        self.dirty = False
        self.snapshot = self.provider = self.selected_fragment = self.markdown_document = None
        self.asset_lookup = {}
        self.canvas.clear_document()
        self.canvas.reviews = self.book.records
        self.problems_panel.clear_document()
        self.inspector.asset = None
        self.inspector.update()
        self.note.clear()
        for picker in (self.block_picker, self.diagnostic_picker):
            with QtCore.QSignalBlocker(picker):
                picker.clear()
        with QtCore.QSignalBlocker(self.page_picker):
            self.page_picker.setRange(1, 1)
            self.page_picker.setSuffix(" / 1 页")
        self._display_session()
        self._sync_document_controls(defaults.style)
        self.optimize.setChecked(True)
        self.update_mode_controls()
        self.schedule_layout()
        if warning:
            self.status.setText(warning)

    def open_text(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "打开源码", "", "源码 (*.md *.markdown *.txt);;所有文件 (*)"
        )
        if path:
            try:
                p = Path(path)
                if p.stat().st_size > 2 * 1024 * 1024:
                    raise ValueError("源码超过 2 MiB")
                source = p.read_bytes().decode("utf-8-sig")
                if p.suffix.lower() in {".md", ".markdown"} or self.mode == "markdown":
                    self.import_markdown(source, p.parent)
                else:
                    self.replace_text(source)
            except (ValueError, OSError) as error:
                self.message_error(error)

    def import_markdown(self, source, root):
        from ..document.images import import_local_images

        document = parse_markdown(source, dialect=self.flow.markdown_dialect,
                                  field_blocks=self.flow.named_fields)
        references = {dict(node.attributes).get("src") for top in document.nodes
                      for node in top.walk() if node.kind == "image"}
        previous = self.flow.images
        kept = tuple(image for image in previous if image.source not in references)
        flow, issues = import_local_images(document, replace(self.flow, images=kept), root)
        edit = self.source_session.apply(0, len(self.source_session.source), source)
        self.flow = flow
        self.source_error = None
        if self.mode != "markdown":
            self.mode = "markdown"
            self.session_path = self.session_hash = None
            with QtCore.QSignalBlocker(self.mode_picker):
                self.mode_picker.setCurrentIndex(self.mode_picker.findData(self.mode))
        if previous != flow.images:
            # Keep image replacement reversible alongside the source edit.
            history = self.source_session._undo
            self.imported_image_edits = {id(edit): self.imported_image_edits[id(edit)]
                                         for edit in history if id(edit) in self.imported_image_edits}
            self.imported_image_edits[id(edit)] = (edit, previous, flow.images)
        self.template_content_panel.source_edited()
        self._display_session()
        self.mark_dirty()
        self.schedule_layout()
        loaded = len(flow.images) - len(kept)
        if issues:
            message = QtWidgets.QMessageBox(self)
            message.setIcon(QtWidgets.QMessageBox.Icon.Warning)
            message.setWindowTitle("Markdown 图片导入")
            message.setText(f"已嵌入 {loaded} 个图片资源；{len(issues)} 处引用未导入。")
            message.setDetailedText("\n".join(
                f"{source[issue.span.start:issue.span.end]}\n{issue.message}" for issue in issues
            ))
            message.exec()
        elif loaded:
            self.status.setText(f"已嵌入 {loaded} 个图片资源，正在更新预览…")

    def save_text(self):
        if self.source_error:
            self.message_error(self.source_error)
            return
        name = "正文.md" if self.mode == "markdown" else "正文.txt"
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "另存源码", name)
        if path:
            try:
                atomic_write(Path(path), self.buffer.raw.encode(), file_hash(Path(path)))
                self.status.setText("源码已保存；项目设置和字形选择请保存项目")
            except (ValueError, OSError) as error:
                self.message_error(error)

    def request_project_save(self, *, save_as=False, force=False):
        if self.project_save_dialog or self.closed:
            return False
        if self.project_save is not None:
            if save_as or self.mode == 'plain-text':
                self.status.setText('正在保存项目，请保存完成后重试。')
                return False
            if self.edit_generation != self.project_save.generation:
                self.project_save_pending = True
            return True
        if not self.integrated or self.mode == 'plain-text':
            return super().save_project_as() if save_as else super().save_project()
        if self.source_error:
            self.message_error(self.source_error)
            return False
        bound_path, expected = self.session_path, self.session_hash
        if bound_path and not self.dirty and not save_as and not force:
            self.status.setText('项目已是最新版本。')
            return True
        path = None if save_as else bound_path
        inspect_destination = not path
        if inspect_destination:
            self.project_save_dialog = True
            try:
                selected, _ = QtWidgets.QFileDialog.getSaveFileName(
                    self, "保存排版项目", "正文.inkdoc", "排版项目 (*.inkdoc)"
                )
            finally:
                self.project_save_dialog = False
            if not selected:
                return False
            path = Path(selected)
        try:
            if self.source_error:
                raise ValueError(self.source_error)
            # A Save As to the currently open file still honors its saved hash.
            inspect_destination = inspect_destination and (bound_path is None or path.resolve() != bound_path.resolve())
            args = self.build_arguments()
            args['resolver'] = args['resolver'].copy_choices()
            job = ProjectSaveWorker(path, expected, inspect_destination, args, self.optimize.isChecked(),
                                    [asdict(r) for r in self.book.records.values()])
        except (ValueError, OSError, KeyError, TypeError) as error:
            self.message_error(error)
            return False
        job.signals.finished.connect(self.project_save_completed)
        self.project_save = SimpleNamespace(generation=self.edit_generation, path=path, bound_path=bound_path,
                                            bound_hash=expected, epoch=self.recovery_epoch)
        self.recovery_timer.stop()
        self.status.setText(f'正在保存项目：{path}')
        self.pool.start(job)
        return True

    @QtCore.Slot(object)
    def project_save_completed(self, result):
        request, self.project_save = self.project_save, None
        pending, self.project_save_pending = self.project_save_pending, False
        if 'error' in result:
            self.status.setText('项目未保存。')
            if self.dirty:
                self.recovery_timer.start()
            self.message_error(result['error'])
            self.project_save_finished.emit(False)
            return
        same_document = (request.epoch == self.recovery_epoch and self.mode == 'markdown'
                         and (self.session_path, self.session_hash) == (request.bound_path, request.bound_hash))
        if same_document:
            self.session_path, self.session_hash = request.path, result['hash']
            self.project_migration_notice = ''
            if request.generation == self.edit_generation:
                self.resolver = result["resolver"]
                self.dirty = False
                self.recovery_timer.stop()
                self.update_mode_controls()
        self.status.setText(f"项目已保存：{request.path}"
                            + ("；排版超限草稿，需拆分或简化后重排" if result.get('limited') else "")
                            + ("；保存期间的新修改尚未保存" if self.dirty else ""))
        if self.dirty:
            self.recovery_timer.start()
        if pending and self.dirty and same_document:
            if self.request_project_save() and self.project_save is not None:
                return
            self.project_save_finished.emit(False)
            return
        self.project_save_finished.emit(True)

    def wait_for_project_save(self):
        if self.project_save_waiting:
            return False
        if self.project_save is None:
            return True
        self.project_save_waiting = True
        loop = QtCore.QEventLoop(self)
        saved = False

        def finished(success):
            nonlocal saved
            saved = success
            loop.quit()

        self.project_save_finished.connect(finished)
        try:
            loop.exec()
            return saved
        finally:
            self.project_save_finished.disconnect(finished)
            self.project_save_waiting = False

    def save_project(self):
        return self.request_project_save(force=True) and self.wait_for_project_save()

    def save_project_as(self):
        return self.request_project_save(save_as=True) and self.wait_for_project_save()

    def save_before_discard(self):
        return self.save_project() and not self.dirty

    def confirm_discard(self):
        if self.project_save_dialog or not self.wait_for_project_save():
            return False
        return super().confirm_discard()

    def load_project_path(self, path):
        self.canvas._process.prewarm()
        path = Path(path)
        legacy = path.suffix.lower() == ".inktable"
        self.project_migration_notice = ""
        if path.suffix.lower() == ".inkreview":
            expected = file_hash(path)
            buffer, run, book, page, style = load_session(path)
            if file_hash(path) != expected:
                raise ValueError("读取期间检查项目发生变化，请重新打开")
            self.source_session = SourceSession(buffer.raw)
            self.run_path, self.book, self.page = run, book, page
            self.resolver = AssetResolver()
            self.symbol_path = ""
            self.mode = "plain-text"
            self.session_hash = expected
        else:
            loaded = import_table_project(path) if legacy else load_package(path)
            self.project_migration_notice = loaded.migration_notice
            reviews = [Review(**r) for r in loaded.reviews]
            if any(r.rating not in RATINGS for r in reviews):
                raise ValueError("项目含未知评价类型")
            self.source_session, self.resolver = loaded.session, loaded.resolver
            self.page, style, self.flow = loaded.page, loaded.style, loaded.flow
            self.book = ReviewBook(reviews)
            self.run_path = self.symbol_path = ""
            self.mode = "markdown"
            self.optimize.setChecked(loaded.optimize)
            self.session_hash = loaded.file_hash
        self.source_error = None
        self.loaded_style = style
        self.imported_image_edits.clear()
        self._display_session()
        self._sync_document_controls(style)
        migrated = bool(self.project_migration_notice)
        self.document_started = True
        self.session_path = None if legacy or migrated else path
        if legacy or migrated:
            self.session_hash = None
        self.recovery_path = self.recovery_hash = None
        self.recovery_epoch += 1
        self.recovery_timer.stop()
        self.edit_generation += 1
        self.dirty = False
        self.update_mode_controls()
        self.schedule_layout()
        if legacy or migrated:
            self.mark_dirty()
        if migrated:
            self.status.setText(self.project_migration_notice)

    def _sync_document_controls(self, style):
        for c, v in (
            (self.em, style.em_mm),
            (self.line_height, style.line_height_mm),
            (self.stroke, style.stroke_width_mm),
        ):
            with QtCore.QSignalBlocker(c):
                c.setRange(min(c.minimum(), v), max(c.maximum(), v))
                c.setDecimals(6)
                c.setValue(v)
        for name, c in self.flow_controls.items():
            with QtCore.QSignalBlocker(c):
                value = getattr(self.flow, name)
                c.setRange(min(c.minimum(), value), max(c.maximum(), value))
                c.setValue(value)
        with QtCore.QSignalBlocker(self.mode_picker):
            self.mode_picker.setCurrentIndex(self.mode_picker.findData(self.mode))
        with QtCore.QSignalBlocker(self.dialect_picker):
            self.dialect_picker.setCurrentIndex(
                self.dialect_picker.findData(self.flow.markdown_dialect)
            )

    def open_project(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "打开项目或导入旧表格", "", "项目 (*.inkdoc *.inkreview *.inktable)"
        )
        if path and self.confirm_discard():
            try:
                self.load_project_path(path)
            except (ValueError, OSError, KeyError, TypeError) as error:
                self.message_error(error)

    def recovery_arguments(self):
        if self.recovery_path is None:
            self.recovery_path = recovery_directory() / (
                digest(["recovery", self.source_session.document_id])[:16]
                + "-" + new_id() + ".inkdoc"
            )
            self.recovery_hash = None
        # The worker owns mutable session/selection maps. Glyphs and profiles
        # are immutable and can be shared with concurrent layout and editing.
        return {
            'session': SourceSession.restore(
                self.source_session.source, self.source_session.identity_record()
            ),
            'resolver': AssetResolver(
                embedded=tuple(g for pool in self.resolver.pools.values() for g in pool),
                selections=tuple(self.resolver.selections.values()), seed=self.resolver.seed,
                font_identity=self.resolver.font_identity,
            ),
            'page': self.page, 'style': self.style, 'flow': self.flow,
            'optimize': self.optimize.isChecked(), 'expected_hash': self.recovery_hash,
            'reviews': [asdict(r) for r in self.book.records.values()],
        }

    def start_recovery(self):
        if (self.closed or self.mode != 'markdown' or not self.dirty or self.source_error
                or self.project_save is not None):
            return
        if self.recovery_worker is not None:
            self.recovery_pending = True
            return
        try:
            arguments = self.recovery_arguments()
            request = {'epoch': self.recovery_epoch, 'generation': self.edit_generation,
                       'path': self.recovery_path}
            self.recovery_pending = False
            self.recovery_worker = RecoveryWorker(request, arguments)
            self.recovery_worker.signals.finished.connect(self.recovery_completed)
            self.pool.start(self.recovery_worker)
        except (ValueError, OSError) as error:
            self.status.setText('自动恢复副本未保存：' + str(error))

    @QtCore.Slot(object)
    def recovery_completed(self, result):
        self.recovery_worker = None
        if self.closed:
            return
        if result['epoch'] == self.recovery_epoch and result['path'] == self.recovery_path:
            if 'error' in result:
                self.status.setText('自动恢复副本未保存：' + result['error'])
            else:
                self.recovery_hash = result['hash']
        pending = self.recovery_pending or result['generation'] != self.edit_generation
        self.recovery_pending = False
        if pending and self.dirty:
            self.recovery_timer.start()

    def write_recovery(self):
        """Explicit synchronous save; automatic saves use start_recovery instead."""
        if self.closed or self.mode != "markdown" or not self.dirty or self.source_error:
            return
        if self.recovery_worker is not None:
            self.recovery_pending = True
            return
        try:
            arguments = self.recovery_arguments()
            self.recovery_hash = save_package(self.recovery_path, **arguments)
        except (ValueError, OSError) as error:
            self.status.setText("自动恢复副本未保存：" + str(error))

    def open_recovery(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "打开恢复副本",
            str(recovery_directory()),
            "排版项目 (*.inkdoc)",
        )
        if path and self.confirm_discard():
            try:
                self.load_project_path(path)
                self.session_path = self.session_hash = None
                self.mark_dirty()
                self.status.setText("已恢复源码与资源，正式项目请另存")
            except (ValueError, OSError) as error:
                self.message_error(error)

    def closeEvent(self, event):
        if self.export_job is not None:
            self.export_progress.cancel()
            self.export_progress.show()
            self.status.setText('正在取消 SVG 导出，请等待临时文件和子进程清理完成后再关闭。')
            event.ignore()
            return
        if getattr(getattr(self, "glyph_inspector", None), "job", None):
            QtWidgets.QMessageBox.information(self, "字体校正进行中", "请等待校正字体写入和完整校验完成后再退出。")
            event.ignore()
            return
        super().closeEvent(event)
        if event.isAccepted():
            self.recovery_timer.stop()
