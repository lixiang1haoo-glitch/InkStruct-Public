"""A field form that edits ranges in the authoritative Markdown, never a second document."""

from PySide6 import QtCore, QtWidgets

from ..document.markdown import parse_markdown
from .review import SourceBuffer


class FieldFormDialog(QtWidgets.QDialog):
    def __init__(self, template, source, parent=None):
        super().__init__(parent)
        self.template, self.original = template, source
        self.setWindowTitle("填写当前文档字段")
        self.resize(650, min(720, 210 + 130 * max(1, len(template.fields))))
        self.source_field_id = template.fields[0].field_id if template.fields else None
        col = QtWidgets.QVBoxLayout(self)
        note = QtWidgets.QLabel("字段写入本份 Markdown；正文与未修改的字段原样保留。* 表示必填。")
        note.setWordWrap(True)
        col.addWidget(note)
        self.error = QtWidgets.QLabel()
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color: #b42318")
        col.addWidget(self.error)
        # Backing source is intentionally not a second visible Markdown editor.
        self.source = QtWidgets.QPlainTextEdit(source, self)
        self.source.hide()
        self.buffer = SourceBuffer(source)
        self.source.textChanged.connect(lambda: self.buffer.update(self.source.toPlainText()))
        self.document = parse_markdown(source, field_blocks=True)
        definitions = {}
        self.blocked = any(d.code == "template-field-syntax" for d in self.document.diagnostics)
        for n in self.document.nodes:
            if n.kind == "named_field":
                key = dict(n.attributes)["field_id"]
                if key in definitions:
                    self.blocked = True
                definitions[key] = n
        self.inputs, self.ranges, self.initial = {}, {}, {}
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        content = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(content)
        form.setFormAlignment(QtCore.Qt.AlignTop | QtCore.Qt.AlignLeft)
        for field in template.fields:
            n = definitions.get(field.field_id)
            text = ""
            if n:
                lines = source[n.span.start : n.span.end].splitlines(keepends=True)
                close = next(
                    (i for i in range(len(lines) - 1, 0, -1) if lines[i].strip() == ":::"), None
                )
                if close is None:
                    self.blocked = True
                else:
                    start = n.span.start + len(lines[0])
                    end = n.span.start + sum(map(len, lines[:close]))
                    raw = source[start:end]
                    ending = (
                        "\r\n"
                        if raw.endswith("\r\n")
                        else raw[-1:]
                        if raw.endswith(("\r", "\n"))
                        else ""
                    )
                    text = raw[: -len(ending)] if ending else raw
                    self.ranges[field.field_id] = (start, end, ending)
            entry = QtWidgets.QPlainTextEdit(text)
            entry.setAccessibleName(field.label + ("（必填）" if field.required else ""))
            entry.setMaximumHeight(100)
            entry.setMinimumHeight(62)
            entry.setPlaceholderText(
                {
                    "markdown": "支持 Markdown",
                    "date": "YYYY-MM-DD",
                    "number": "填写数值",
                    "text": "填写内容",
                }[field.value_type]
            )
            entry.setToolTip("字段标识：" + field.field_id)
            entry.setEnabled(not self.blocked)
            self.inputs[field.field_id] = entry
            entry.installEventFilter(self)
            self.initial[field.field_id] = entry.toPlainText()
            form.addRow(field.label + (" *" if field.required else "（可选）"), entry)
        scroll.setWidget(content)
        col.addWidget(scroll, 1)
        self.source_button = QtWidgets.QPushButton("在主编辑器查看源码")
        self.source_button.clicked.connect(self.view_source)
        col.addWidget(self.source_button)
        self.buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        self.buttons.button(QtWidgets.QDialogButtonBox.Ok).setText("应用字段修改")
        self.buttons.button(QtWidgets.QDialogButtonBox.Cancel).setText("取消")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        col.addWidget(self.buttons)
        if self.blocked:
            self.error.setText(
                "存在重复字段或字段块语法错误。请先在主编辑器修正；不会猜测或覆盖其中一份内容。"
            )
            self.buttons.button(QtWidgets.QDialogButtonBox.Ok).setEnabled(False)

    def configuration(self):
        if self.buffer.raw != self.original:
            return self.buffer.raw
        source = self.original
        newline = "\r\n" if "\r\n" in source else "\r" if "\r" in source else "\n"
        edits, missing = [], []
        for key, control in self.inputs.items():
            text = control.toPlainText()
            if text == self.initial[key]:
                continue
            old = self.ranges.get(key)
            if old:
                start, end, ending = old
                buffer = SourceBuffer(
                    self.original[start : end - len(ending)] if ending else self.original[start:end]
                )
                buffer.update(text)
                edits.append((start, end, buffer.raw + (ending or newline)))
            elif text:
                missing.append(
                    f":::field {key}{newline}{text.replace(chr(10), newline)}{newline}:::{newline}{newline}"
                )
        for start, end, text in sorted(edits, reverse=True):
            source = source[:start] + text + source[end:]
        return "".join(missing) + source

    def eventFilter(self, watched, event):
        if event.type() == QtCore.QEvent.FocusIn:
            for key, entry in self.inputs.items():
                if entry is watched:
                    self.source_field_id = key
                    break
        return super().eventFilter(watched, event)

    def view_source(self):
        if self.configuration() != self.original:
            answer = QtWidgets.QMessageBox.question(
                self,
                "尚有未应用的字段修改",
                "查看主源码会放弃本次尚未应用的表单修改。是否继续？",
                QtWidgets.QMessageBox.Discard | QtWidgets.QMessageBox.Cancel,
                QtWidgets.QMessageBox.Cancel,
            )
            if answer != QtWidgets.QMessageBox.Discard:
                return
        self.done(2)

    def accept(self):
        from ..document.editing import SourceSession

        try:
            if self.blocked:
                raise ValueError("请先修正主 Markdown 中的字段定义。")
            source = self.configuration()
            SourceSession._validate_source(source)
            parsed = parse_markdown(source, field_blocks=True)
            if any(d.code == "template-field-syntax" for d in parsed.diagnostics):
                raise ValueError("字段内容产生了无效字段标记，请在主编辑器检查。")
            # Form edits may not introduce another named block or remove an existing one.
            expected = [
                dict(n.attributes)["field_id"]
                for n in self.document.nodes
                if n.kind == "named_field"
            ]
            expected += [
                k for k in self.inputs if k not in expected and self.inputs[k].toPlainText()
            ]
            actual = [
                dict(n.attributes)["field_id"] for n in parsed.nodes if n.kind == "named_field"
            ]
            if sorted(actual) != sorted(expected):
                raise ValueError("字段内容不能改变字段块结构；请使用主编辑器编辑协议。")
        except (ValueError, UnicodeError) as error:
            self.error.setText(str(error))
            return
        super().accept()

    def focus_field(self, key):
        if key in self.inputs:
            self.source_field_id = key
            self.inputs[key].setFocus(QtCore.Qt.OtherFocusReason)
