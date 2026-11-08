"""Human-readable, read-only view of current template fit evidence."""

import json
from pathlib import Path

from PySide6 import QtCore, QtWidgets

from .problem_details import ISSUE_LABELS
from .review import atomic_write


class TemplateFitDialog(QtWidgets.QDialog):
    def __init__(self, report, diagnostics, parent=None, *, omission_exportable=False):
        super().__init__(parent)
        self.report, self.diagnostics = report, tuple(diagnostics)
        self.selected_diagnostic = None
        self.setWindowTitle("模板适配报告")
        self.resize(780, 540)
        layout = QtWidgets.QVBoxLayout(self)
        counts = report["severity_counts"]
        summary = QtWidgets.QLabel(
            f"{report['template_name']} · {report['pages']} 页 · "
            f"{counts.get('error', 0)} 项错误 · {counts.get('warning', 0)} 项提醒\n"
            + ("内容检查通过" if report["exportable"] else "内容检查未通过，请修正后重新排版")
            + (" · 具备写字机导出条件" if report["plotter_exportable"]
               else " · 完整写字机导出不可用；可确认跳过位图导出其余内容" if omission_exportable
               else " · 写字机导出不可用")
            + "\n字段状态只表示该字段的诊断；全局问题见下表。严格 SVG 和纸面定位尚未在此验证。"
        )
        summary.setTextFormat(QtCore.Qt.PlainText)
        summary.setWordWrap(True)
        layout.addWidget(summary)
        self.fields = QtWidgets.QTableWidget(len(report["fields"]), 3)
        self.fields.setHorizontalHeaderLabels(["字段 / 填写区", "字段内容" if report['schema_version']=='inkstruct_template_fit_report_v2' else "源码对应", "检查状态"])
        statuses = {
            "error": "有错误",
            "unbound": "未绑定",
            "warning": "有提醒",
            "no-local-error": "未发现字段内错误",
        }
        for row, field in enumerate(report["fields"]):
            binding = field["binding"]
            for col, value in enumerate(
                (
                    field["label"],
                    ("命名字段块已定义" if report['schema_version']=='inkstruct_template_fit_report_v2' else f"{len(binding['node_ids'])} 个源码块") if binding else "无",
                    statuses[field["status"]],
                )
            ):
                self.fields.setItem(row, col, QtWidgets.QTableWidgetItem(value))
        self.fields.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.fields.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self.fields.setMaximumHeight(140)
        self.issues = QtWidgets.QTreeWidget()
        self.issues.setHeaderLabels(["级别", "位置", "问题"])
        labels = {field["region"]: field["label"] for field in report["fields"]}
        for i, diagnostic in enumerate(diagnostics):
            target = getattr(diagnostic, "target", None)
            location = labels.get(target.slot_id or target.region, target.region) if target else "正文 / 全局"
            if target:
                location += " · " + (
                    f"第 {target.page_index + 1} 页"
                    if target.page_index is not None
                    else "字段声明" if report['schema_version']=='inkstruct_template_fit_report_v2' else "首页"
                    if target.face == "first"
                    else "续页"
                )
            item = QtWidgets.QTreeWidgetItem(
                [
                    {"error": "错误", "warning": "提醒"}.get(diagnostic.severity, "提示"),
                    location,
                    ISSUE_LABELS.get(diagnostic.code, diagnostic.message),
                ]
            )
            item.setData(0, QtCore.Qt.UserRole, i)
            item.setToolTip(2, diagnostic.code + "\n" + diagnostic.message)
            self.issues.addTopLevelItem(item)
        self.issues.setColumnWidth(0, 55)
        self.issues.setColumnWidth(1, 180)
        layout.addWidget(self.issues, 2)
        layout.addWidget(QtWidgets.QLabel('字段明细'))
        layout.addWidget(self.fields)
        buttons = QtWidgets.QHBoxLayout()
        self.locate = QtWidgets.QPushButton("定位所选问题…")
        self.locate.setEnabled(False)
        self.issues.currentItemChanged.connect(
            lambda item, _: self.locate.setEnabled(item is not None)
        )
        self.locate.clicked.connect(self.locate_issue)
        buttons.addWidget(self.locate)
        self.save = QtWidgets.QPushButton("另存报告 JSON…")
        self.save.clicked.connect(self.save_report)
        buttons.addWidget(self.save)
        buttons.addStretch()
        close = QtWidgets.QPushButton("关闭")
        close.clicked.connect(self.reject)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self.message = QtWidgets.QLabel()
        self.message.setTextFormat(QtCore.Qt.PlainText)
        self.message.setWordWrap(True)
        layout.addWidget(self.message)

    def locate_issue(self):
        item = self.issues.currentItem()
        if item is not None:
            self.selected_diagnostic = self.diagnostics[item.data(0, QtCore.Qt.UserRole)]
            self.accept()

    def save_report(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "另存适配报告（新文件）", "模板适配报告.json", "JSON (*.json)"
        )
        if path:
            try:
                if Path(path).is_symlink():
                    raise ValueError("请选择新的报告文件，不能替换符号链接")
                atomic_write(
                    Path(path),
                    (json.dumps(self.report, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
                )
                self.message.setText("报告已保存：" + path)
            except (OSError, ValueError) as error:
                self.message.setText(str(error))
