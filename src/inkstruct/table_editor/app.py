from __future__ import annotations

import argparse
import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path

from .core import Settings, compile_html, drawing_svg
from .routing import optimize_paths
from .samples import load_sample_zip

EXAMPLE = """<table border="1">
  <tr>
    <td rowspan="2">1</td>
    <td colspan="2">12.50</td>
  </tr>
  <tr>
    <td align="right">0.125</td>
    <td align="right">23.60</td>
  </tr>
  <tr>
    <td>2</td>
    <td align="right">100.00</td>
    <td align="right">8.75</td>
  </tr>
</table>
"""


def atomic_save(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def create_window(*, sample_bank=None, sample_seed=0):
    from PySide6 import QtCore, QtSvgWidgets, QtWidgets

    class Window(QtWidgets.QMainWindow):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("InkStruct · 数字表格排版")
            self.resize(1180, 850)
            self.svg = None
            self.drawing = None
            self.sample_bank = sample_bank
            self.glyph_trace = []
            self.source_path = None
            self.project_path = None
            self.project_dirty = False
            central = QtWidgets.QWidget()
            self.setCentralWidget(central)
            root = QtWidgets.QVBoxLayout(central)
            actions = QtWidgets.QHBoxLayout()
            for title, slot in [
                ("打开 HTML", self.open_html),
                ("保存 HTML", self.save_html),
                ("打开项目", self.open_project),
                ("保存项目", self.save_project),
            ]:
                button = QtWidgets.QPushButton(title)
                button.clicked.connect(slot)
                actions.addWidget(button)
            self.export_button = QtWidgets.QPushButton("导出写字机 SVG")
            self.export_button.clicked.connect(self.export_svg)
            actions.addStretch()
            actions.addWidget(self.export_button)
            root.addLayout(actions)
            routing = QtWidgets.QHBoxLayout()
            self.optimize_checkbox = QtWidgets.QCheckBox("优化路径（减少空行程）")
            routing.addWidget(self.optimize_checkbox)
            routing.addWidget(
                QtWidgets.QLabel("自动排序并允许反转；空行程按纸张左上角起点估算，不含回零")
            )
            routing.addStretch()
            root.addLayout(routing)
            self.optimize_checkbox.toggled.connect(self.routing_changed)
            samples = QtWidgets.QHBoxLayout()
            import_samples = QtWidgets.QPushButton("导入手写数字 ZIP")
            import_samples.clicked.connect(self.open_samples)
            builtin = QtWidgets.QPushButton("使用内置数字")
            builtin.clicked.connect(lambda: self.set_sample_bank(None))
            samples.addWidget(import_samples)
            samples.addWidget(builtin)
            self.sample_label = QtWidgets.QLabel(
                sample_bank.summary if sample_bank else "内置单线数字"
            )
            samples.addWidget(self.sample_label, 1)
            samples.addWidget(QtWidgets.QLabel("选样种子"))
            self.sample_seed = QtWidgets.QSpinBox()
            self.sample_seed.setRange(0, 2147483647)
            self.sample_seed.setValue(sample_seed)
            samples.addWidget(self.sample_seed)
            root.addLayout(samples)
            self.controls = {}
            form = QtWidgets.QGridLayout()
            defaults = Settings()
            for i, (key, label, low, high) in enumerate(
                [
                    ("page_width", "纸宽 mm", 10, 2000),
                    ("page_height", "纸高 mm", 10, 2000),
                    ("margin", "页边距 mm", 0.1, 200),
                    ("table_width", "表宽 mm", 1, 1900),
                    ("row_height", "行高 mm", 1, 200),
                    ("digit_height", "数字高度 mm", 0.5, 100),
                    ("padding", "格内留白 mm", 0, 50),
                    ("stroke_width", "笔宽 mm", 0.01, 3),
                ]
            ):
                spin = QtWidgets.QDoubleSpinBox()
                spin.setRange(low, high)
                spin.setDecimals(2)
                spin.setValue(getattr(defaults, key))
                spin.setSingleStep(0.1 if key == "stroke_width" else 0.5)
                form.addWidget(QtWidgets.QLabel(label), i // 4, (i % 4) * 2)
                form.addWidget(spin, i // 4, (i % 4) * 2 + 1)
                self.controls[key] = spin
            root.addLayout(form)
            widths = QtWidgets.QHBoxLayout()
            widths.addWidget(QtWidgets.QLabel("列宽比例"))
            self.weights = QtWidgets.QLineEdit()
            self.weights.setPlaceholderText("留空为等宽；例如 1, 2, 2")
            widths.addWidget(self.weights)
            widths.addWidget(QtWidgets.QLabel("预览缩放"))
            self.zoom = QtWidgets.QSpinBox()
            self.zoom.setRange(25, 200)
            self.zoom.setValue(100)
            self.zoom.setSuffix("%")
            widths.addWidget(self.zoom)
            root.addLayout(widths)
            help_label = QtWidgets.QLabel(
                "左侧输入一个 HTML 表格；支持空格、数字、小数、合并单元格与左/中/右对齐。"
                "框线统一绘制，尺寸由上方控制。手写数字按出现位置选样，固定种子可复现。"
            )
            help_label.setWordWrap(True)
            root.addWidget(help_label)
            splitter = QtWidgets.QSplitter()
            self.editor = QtWidgets.QPlainTextEdit()
            self.editor.setPlainText(EXAMPLE)
            self.editor.setMinimumWidth(300)
            splitter.addWidget(self.editor)
            scroll = QtWidgets.QScrollArea()
            self.preview = QtSvgWidgets.QSvgWidget()
            self.preview.setStyleSheet("background: white;")
            scroll.setWidget(self.preview)
            scroll.setStyleSheet("QScrollArea { background: #e2e5e9; }")
            scroll.setAlignment(QtCore.Qt.AlignmentFlag.AlignHCenter)
            splitter.addWidget(scroll)
            splitter.setSizes([420, 730])
            root.addWidget(splitter, 1)
            self.status = QtWidgets.QLabel()
            self.status.setWordWrap(True)
            root.addWidget(self.status)
            self.timer = QtCore.QTimer(self)
            self.timer.setSingleShot(True)
            self.timer.setInterval(220)
            self.timer.timeout.connect(self.refresh)
            self.editor.textChanged.connect(self.schedule)
            self.weights.textChanged.connect(self.schedule)
            self.sample_seed.valueChanged.connect(self.schedule)
            for spin in self.controls.values():
                spin.valueChanged.connect(self.schedule)
            self.zoom.valueChanged.connect(self.resize_preview)
            self.refresh()
            self.editor.document().setModified(False)

        def settings(self):
            raw = self.weights.text().strip()
            try:
                weights = (
                    tuple(float(v.strip()) for v in raw.replace("，", ",").split(","))
                    if raw
                    else ()
                )
            except ValueError as error:
                raise ValueError("列宽比例请输入逗号分隔的正数") from error
            return Settings(
                **{k: w.value() for k, w in self.controls.items()}, column_weights=weights
            )

        def routing_changed(self):
            self.project_dirty = True

        def set_sample_bank(self, bank):
            self.sample_bank = bank
            self.sample_label.setText(bank.summary if bank else "内置单线数字")
            self.schedule()

        def open_samples(self):
            name, _ = QtWidgets.QFileDialog.getOpenFileName(
                self, "导入符号采集样本", "", "采集样本 (*.zip)"
            )
            if name:
                try:
                    self.set_sample_bank(load_sample_zip(Path(name)))
                    self.refresh()
                except (OSError, ValueError) as error:
                    QtWidgets.QMessageBox.warning(self, "导入失败", str(error))

        def schedule(self):
            self.project_dirty = True
            self.svg = None
            self.export_button.setEnabled(False)
            self.status.setText("正在更新预览…")
            self.timer.start()

        def resize_preview(self):
            factor = self.zoom.value() / 100 * 3
            self.preview.setFixedSize(
                round(self.controls["page_width"].value() * factor),
                round(self.controls["page_height"].value() * factor),
            )

        def refresh(self):
            self.timer.stop()
            try:
                selection = (
                    self.sample_bank.select(self.sample_seed.value()) if self.sample_bank else None
                )
                drawing, self.svg = compile_html(
                    self.editor.toPlainText(), self.settings(), glyphs=selection
                )
                self.drawing = drawing
                self.glyph_trace = selection.trace if selection is not None else []
            except ValueError as error:
                self.svg = None
                self.preview.hide()
                self.export_button.setEnabled(False)
                self.status.setText(f"无法排版：{error}")
                self.status.setStyleSheet("color: #b42318;")
                return False
            self.preview.load(QtCore.QByteArray(self.svg.encode("utf-8")))
            self.resize_preview()
            self.preview.show()
            self.export_button.setEnabled(True)
            self.status.setStyleSheet("color: #236747;")
            self.status.setText(
                f"{drawing.rows} 行 × {drawing.columns} 列 · {len(drawing.borders)} 条框线 · "
                f"{len(drawing.numbers)} 笔数字轨迹 · 导出仅含 path，指令仅 M/L"
            )
            return True

        def can_discard(self):
            if not self.editor.document().isModified() and not self.project_dirty:
                return True
            result = QtWidgets.QMessageBox.question(
                self,
                "表格项目尚未保存",
                "放弃当前未保存的表格或排版设置？",
                QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
                QtWidgets.QMessageBox.StandardButton.No,
            )
            return result == QtWidgets.QMessageBox.StandardButton.Yes

        def open_html(self):
            if not self.can_discard():
                return
            name, _ = QtWidgets.QFileDialog.getOpenFileName(
                self, "打开 HTML 表格", "", "HTML (*.html *.htm *.txt)"
            )
            if name:
                try:
                    path = Path(name)
                    if path.stat().st_size > 800_000:
                        raise ValueError("文件超过 800 KB")
                    self.editor.setPlainText(path.read_text(encoding="utf-8-sig"))
                    self.source_path = path
                    self.editor.document().setModified(False)
                except (OSError, ValueError) as error:
                    QtWidgets.QMessageBox.warning(self, "打开失败", str(error))

        def save_html(self):
            name, _ = QtWidgets.QFileDialog.getSaveFileName(
                self, "保存 HTML", str(self.source_path or "table.html"), "HTML (*.html)"
            )
            if name:
                try:
                    atomic_save(Path(name), self.editor.toPlainText())
                    self.source_path = Path(name)
                    self.editor.document().setModified(False)
                except OSError as error:
                    QtWidgets.QMessageBox.warning(self, "保存失败", str(error))

        def save_project(self):
            name, _ = QtWidgets.QFileDialog.getSaveFileName(
                self,
                "保存表格项目",
                str(self.project_path or "table.inktable"),
                "表格项目 (*.inktable)",
            )
            if not name:
                return
            try:
                payload = {
                    "schema_version": "inkstruct_table_v1",
                    "html": self.editor.toPlainText(),
                    "settings": asdict(self.settings()),
                    "routing": {
                        "optimize": self.optimize_checkbox.isChecked(),
                        "allow_reverse": self.optimize_checkbox.isChecked(),
                    },
                    "samples": {
                        "path": str(self.sample_bank.path),
                        "sha256": self.sample_bank.sha256,
                        "seed": self.sample_seed.value(),
                    }
                    if self.sample_bank
                    else None,
                }
                atomic_save(
                    Path(name), json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)
                )
                self.project_path = Path(name)
                self.project_dirty = False
                self.editor.document().setModified(False)
            except (OSError, ValueError) as error:
                QtWidgets.QMessageBox.warning(self, "保存失败", str(error))

        def open_project(self):
            if not self.can_discard():
                return
            name, _ = QtWidgets.QFileDialog.getOpenFileName(
                self, "打开表格项目", "", "表格项目 (*.inktable)"
            )
            if not name:
                return
            try:
                path = Path(name)
                if path.stat().st_size > 1_000_000:
                    raise ValueError("表格项目超过 1 MB")
                payload = json.loads(path.read_text(encoding="utf-8"))
                if payload.get("schema_version") != "inkstruct_table_v1" or not isinstance(
                    payload.get("html"), str
                ):
                    raise ValueError("不是受支持的表格项目")
                routing = payload.get("routing", {"optimize": False, "allow_reverse": False})
                if not isinstance(routing, dict) or any(
                    type(routing.get(k, False)) is not bool for k in ("optimize", "allow_reverse")
                ):
                    raise ValueError("路径优化选项必须为布尔值")
                settings = Settings(**payload["settings"])
                sample_ref = payload.get("samples")
                bank, seed = None, 0
                if sample_ref is not None:
                    seed = sample_ref["seed"]
                    if type(seed) is not int or not 0 <= seed <= 2147483647:
                        raise ValueError("选样种子超出范围")
                    bank = load_sample_zip(path.parent / sample_ref["path"])
                    if bank.sha256 != sample_ref["sha256"]:
                        raise ValueError("样本压缩包已变化，请重新导入后确认笔迹")
                # Do not silently clamp settings from another version into the UI.
                for key, widget in self.controls.items():
                    value = getattr(settings, key)
                    if (
                        not isinstance(value, (float, int))
                        or not widget.minimum() <= value <= widget.maximum()
                    ):
                        raise ValueError(f"{key} 超出界面支持范围")
                raw_weights = ", ".join(str(v) for v in settings.column_weights)
                if len(payload["html"]) > 200_000 or len(raw_weights) > 2000:
                    raise ValueError("项目内容过长")
                for key, widget in self.controls.items():
                    widget.setValue(getattr(settings, key))
                self.set_sample_bank(bank)
                self.sample_seed.setValue(seed)
                self.optimize_checkbox.setChecked(routing.get("optimize", False))
                self.weights.setText(raw_weights)
                self.editor.setPlainText(payload["html"])
                self.project_path = path
                self.source_path = None
                self.editor.document().setModified(False)
                self.project_dirty = False
                self.refresh()
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
                QtWidgets.QMessageBox.warning(self, "打开失败", str(error))

        def export_svg(self):
            # Always compile current input again; never export the previous preview.
            if not self.refresh():
                return
            name, _ = QtWidgets.QFileDialog.getSaveFileName(
                self, "导出写字机 SVG", "table.svg", "SVG (*.svg)"
            )
            if name:
                try:
                    svg = self.svg
                    description = ""
                    if self.optimize_checkbox.isChecked():
                        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
                        try:
                            route = optimize_paths(
                                (*self.drawing.borders, *self.drawing.numbers),
                            )
                            svg = drawing_svg(self.drawing, paths=route.paths)
                        finally:
                            QtWidgets.QApplication.restoreOverrideCursor()
                        description = (
                            f" · 空行程 {route.before_mm:.1f} → {route.after_mm:.1f} mm"
                            f"（减少 {route.saved_percent:.1f}%）· 反转 {sum(route.reversed_paths)} 条"
                        )
                    atomic_save(Path(name), svg)
                    self.status.setText(f"已导出：{name}{description}")
                except OSError as error:
                    QtWidgets.QMessageBox.warning(self, "导出失败", str(error))

        def closeEvent(self, event):
            event.accept() if self.can_discard() else event.ignore()

    return Window()


def main(argv=None):
    parser = argparse.ArgumentParser(description="HTML numeric tables to path-only M/L SVG")
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--optimize-paths", action="store_true")
    parser.add_argument(
        "--allow-reverse", action="store_true", help="兼容旧命令；优化路径已自动允许反转"
    )
    parser.add_argument("--samples", type=Path, help="符号采集器 ZIP，需包含全部数字")
    parser.add_argument("--sample-seed", type=int, default=0)
    args = parser.parse_args(argv)
    if not 0 <= args.sample_seed <= 2147483647:
        parser.error("--sample-seed must be between 0 and 2147483647")
    try:
        bank = load_sample_zip(args.samples) if args.samples else None
    except (OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")
    if args.allow_reverse and not args.optimize_paths:
        parser.error("--allow-reverse requires --optimize-paths")
    if args.output:
        if not args.input:
            parser.error("--output requires --input")
        try:
            if args.input.stat().st_size > 800_000:
                raise ValueError("HTML 文件过大")
            drawing, svg = compile_html(
                args.input.read_text(encoding="utf-8-sig"),
                glyphs=bank.select(args.sample_seed) if bank else None,
            )
            if bank:
                print(bank.summary)
            if args.optimize_paths:
                route = optimize_paths((*drawing.borders, *drawing.numbers))
                svg = drawing_svg(drawing, paths=route.paths)
                print(
                    f"空行程 {route.before_mm:.1f} → {route.after_mm:.1f} mm，减少 {route.saved_percent:.1f}%"
                )
            atomic_save(args.output, svg)
        except (OSError, ValueError) as error:
            parser.exit(1, f"{error}\n")
        return 0
    from PySide6 import QtWidgets

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = create_window(sample_bank=bank, sample_seed=args.sample_seed)
    window.optimize_checkbox.setChecked(args.optimize_paths)
    if args.input:
        if args.input.stat().st_size > 800_000:
            parser.error("HTML 文件过大")
        window.editor.setPlainText(args.input.read_text(encoding="utf-8-sig"))
        window.source_path = args.input
        window.editor.document().setModified(False)
        window.refresh()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
