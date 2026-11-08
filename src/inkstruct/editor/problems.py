"""One searchable problem panel with grouped causes and explicit source navigation."""
from bisect import bisect_right

from PySide6 import QtCore, QtWidgets

from ..document.schema import Diagnostic, SourceSpan
from ..plotter.adapters import can_export_with_image_omission
from .problem_details import IssueGroup, group_issues


class ProblemsPanel(QtWidgets.QWidget):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.source = ""
        self.snapshot = None
        self.groups = ()
        self.position = 0
        self.ready = False
        self.base_summary = "排版完成后显示检查结果"
        self.line_starts = [0]
        column = QtWidgets.QVBoxLayout(self)
        column.setContentsMargins(0,0,0,0)
        self.summary = self.label("排版完成后显示检查结果")
        self.summary.setObjectName("layout_problem_summary")
        column.addWidget(self.summary)
        self.export_state = self.label("")
        column.addWidget(self.export_state)
        filters = QtWidgets.QHBoxLayout()
        self.filter = QtWidgets.QComboBox()
        for title,value in (("全部问题","all"),("需处理","error"),("提醒","warning"),("其他提示","info")):
            self.filter.addItem(title,value)
        filters.addWidget(self.filter)
        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText("搜索问题、字符或代码")
        self.search.setAccessibleName("搜索排版问题")
        filters.addWidget(self.search,1)
        column.addLayout(filters)
        self.list = QtWidgets.QTreeWidget()
        self.list.setObjectName("layout_problem_groups")
        self.list.setHeaderLabels(["问题","处数"])
        self.list.setRootIsDecorated(False)
        self.list.setMinimumHeight(120)
        self.list.header().setStretchLastSection(False)
        self.list.header().setSectionResizeMode(0,QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.list.header().setSectionResizeMode(1,QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        column.addWidget(self.list,2)
        self.empty = self.label("")
        column.addWidget(self.empty)
        self.title = self.label("")
        self.title.setStyleSheet("font-weight:600")
        column.addWidget(self.title)
        self.advice = self.label("")
        column.addWidget(self.advice)
        occurrences = QtWidgets.QHBoxLayout()
        self.previous = QtWidgets.QPushButton("上一处")
        self.next = QtWidgets.QPushButton("下一处")
        self.location = self.label("")
        occurrences.addWidget(self.previous)
        occurrences.addWidget(self.location,1)
        occurrences.addWidget(self.next)
        column.addLayout(occurrences)
        self.locate = QtWidgets.QPushButton("定位到源码")
        self.locate.setObjectName("locate_layout_problem")
        column.addWidget(self.locate)
        self.font_settings = QtWidgets.QPushButton("选择或补充字体…")
        column.addWidget(self.font_settings)
        self.font_warnings = QtWidgets.QPushButton("查看字体来源与类别…")
        column.addWidget(self.font_warnings)
        column.addWidget(owner.repair_template_button)
        self.technical_toggle = QtWidgets.QToolButton()
        self.technical_toggle.setText("技术详情")
        self.technical_toggle.setCheckable(True)
        column.addWidget(self.technical_toggle)
        self.technical = QtWidgets.QPlainTextEdit()
        self.technical.setReadOnly(True)
        self.technical.setMaximumHeight(100)
        self.technical.hide()
        column.addWidget(self.technical)
        self.technical_toggle.toggled.connect(self.technical.setVisible)
        self.copy = QtWidgets.QPushButton("复制问题报告")
        self.copy.clicked.connect(self.copy_report)
        column.addWidget(self.copy)
        column.addWidget(owner.template_fit_button)
        column.addStretch(1)
        self.filter.currentIndexChanged.connect(self.rebuild)
        self.search.textChanged.connect(self.rebuild)
        self.list.currentItemChanged.connect(self.select)
        self.previous.clicked.connect(lambda:self.step(-1))
        self.next.clicked.connect(lambda:self.step(1))
        self.locate.clicked.connect(owner.navigate_diagnostic)
        self.font_settings.clicked.connect(self.open_font_settings)
        self.font_warnings.clicked.connect(owner.show_font_warnings)
        self.rebuild()

    def label(self,text):
        label = QtWidgets.QLabel(text)
        label.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        return label

    def refresh(self,snapshot,source,*,font_warnings=False,notice=""):
        self.snapshot,self.source = snapshot,source
        self.line_starts = [0]+[i+1 for i,char in enumerate(source) if char=="\n"]
        groups = list(group_issues(snapshot.diagnostics,source))
        if font_warnings:
            groups.append(IssueGroup(("font-usage",),"字体来源或类别需要核对","字体与字形",
                                    "这些是来源或字形类别提示，可查看具体缺口后决定是否继续使用。","warning"))
        if notice:
            groups.append(IssueGroup(("migration",),"旧项目已迁移，请另存新文件","项目兼容",
                                    notice,"info"))
        self.groups = tuple(groups)
        self.ready = bool(self.owner.canvas.isEnabled())
        self.set_summary()
        self.rebuild()

    def clear_document(self):
        self.snapshot = None
        self.source = ""
        self.line_starts = [0]
        self.groups = ()
        self.ready = False
        self.base_summary = "排版完成后显示检查结果"
        self.summary.setText(self.base_summary)
        self.export_state.clear()
        self.owner.problems_button.setText("查看问题")
        self.rebuild()

    def set_failure(self,error,source):
        self.snapshot = None
        self.source = source
        self.line_starts = [0]+[i+1 for i,char in enumerate(source) if char=="\n"]
        self.groups = group_issues((Diagnostic("preview-failed",str(error),SourceSpan(0,0)),),source)
        self.ready = False
        self.base_summary = "预览未能完成；文档内容已保留"
        self.summary.setText(self.base_summary)
        self.export_state.setText("本次未生成可用快照，请处理后重试。")
        self.rebuild()

    def set_summary(self):
        errors = sum(len(g.diagnostics) for g in self.groups if g.severity=="error")
        warnings = sum(max(1,len(g.diagnostics)) for g in self.groups if g.severity=="warning")
        self.summary.setText(f"{len(self.groups)} 类问题 · {errors} 处需处理 · {warnings} 条提醒" if self.groups else "检查通过，未发现排版问题")
        self.base_summary = self.summary.text()
        snapshot = self.snapshot
        if snapshot and snapshot.plotter_exportable:
            text = "可正常导出 SVG。提醒不阻止导出。" if warnings else "可正常导出 SVG。"
        elif snapshot and can_export_with_image_omission(snapshot):
            text = "常规 SVG 导出可在确认后跳过参考图片。"
        else:
            text = "常规 SVG 暂不可用。可修正后重排，或通过导出菜单强制导出已有笔迹；缺失留空并附问题清单。"
        self.export_state.setText(text)
        if hasattr(self.owner,"problems_button"):
            self.owner.problems_button.setText(f"查看问题（{len(self.groups)}）" if self.groups else "查看问题")

    def rebuild(self,*_):
        previous = self.current_group()
        key = previous.key if previous else None
        self.list.blockSignals(True)
        self.list.clear()
        chosen = self.filter.currentData()
        query = self.search.text().strip().casefold()
        selected = None
        for group in self.groups:
            if chosen!="all" and group.severity!=chosen:
                continue
            search = " ".join((group.title,group.category,str(group.key),group.suggestion,
                               group.diagnostics[0].message if group.diagnostics else "")).casefold()
            if query and query not in search:
                continue
            severity = {"error":"需处理","warning":"提醒"}.get(group.severity,"提示")
            item = QtWidgets.QTreeWidgetItem([severity+" · "+group.title,str(len(group.diagnostics) or 1)])
            item.setData(0,QtCore.Qt.ItemDataRole.UserRole,group)
            item.setToolTip(0,group.category+" · "+group.title)
            self.list.addTopLevelItem(item)
            if group.key==key:selected=item
        self.list.blockSignals(False)
        self.list.setMaximumHeight(min(280,max(120,28+self.list.topLevelItemCount()*26)))
        self.empty.setText("未发现排版问题。" if not self.groups else "没有符合筛选条件的问题。")
        self.empty.setVisible(not self.list.topLevelItemCount())
        self.list.setVisible(bool(self.list.topLevelItemCount()))
        self.list.setCurrentItem(selected or self.list.topLevelItem(0))
        self.select()

    def current_group(self):
        item=self.list.currentItem()
        return item.data(0,QtCore.Qt.ItemDataRole.UserRole) if item else None

    def select(self,*_):
        self.position=0
        self.update_detail()

    def step(self,delta):
        group=self.current_group()
        if group and group.diagnostics:
            self.position=(self.position+delta)%len(group.diagnostics)
            self.update_detail()
            if self.locate.isEnabled():self.owner.navigate_diagnostic()

    def location_text(self,diagnostic):
        offset=min(len(self.source),max(0,diagnostic.span.start))
        line=bisect_right(self.line_starts,offset)
        text=f"第 {line} 行，第 {offset-self.line_starts[line-1]+1} 列"
        target=getattr(diagnostic,"target",None)
        page=getattr(target,"page_index",None)
        if page is not None:text+=f" · 第 {page+1} 页"
        return text if diagnostic.span.end>diagnostic.span.start else "模板或全局设置（无对应源码）"

    def update_detail(self):
        group=self.current_group()
        diagnostic=group.diagnostics[self.position] if group and group.diagnostics else None
        if diagnostic:
            for i in range(self.owner.diagnostic_picker.count()):
                if self.owner.diagnostic_picker.itemData(i) is diagnostic:
                    self.owner.diagnostic_picker.setCurrentIndex(i)
                    break
        self.title.setText(group.title if group else "")
        self.advice.setText(group.suggestion if group else "")
        self.location.setText(f"{self.position+1}/{len(group.diagnostics)} · "+self.location_text(diagnostic) if diagnostic else "")
        details = diagnostic.code+"\n"+diagnostic.message if diagnostic else ""
        if diagnostic and group.related:
            details += "\n\n已归并的关联诊断：\n"+"\n".join(d.code+": "+d.message for d in group.related
                if diagnostic.span.start>=d.span.start and diagnostic.span.end<=d.span.end)
        self.technical.setPlainText(details)
        self.font_settings.setVisible(bool(group and group.key[1:2]==("asset-missing",)))
        self.font_warnings.setVisible(bool(group and group.key==("font-usage",)))
        self.owner.repair_template_button.setVisible(bool(diagnostic and getattr(diagnostic,"target",None)))
        self.owner.template_fit_button.setVisible(bool(self.owner.flow.template))
        self.technical_toggle.setVisible(diagnostic is not None)
        self.technical.setVisible(bool(diagnostic and self.technical_toggle.isChecked()))
        self.readiness_changed()

    def readiness_changed(self):
        active=bool(self.owner.canvas.isEnabled() and not self.owner.source_syncing)
        group=self.current_group()
        diagnostic=group.diagnostics[self.position] if group and group.diagnostics else None
        if self.snapshot is not None:
            self.summary.setText(self.base_summary if active else self.base_summary+"（正在重排）")
        self.locate.setEnabled(bool(active and diagnostic and diagnostic.span.end>diagnostic.span.start))
        multiple=bool(active and group and len(group.diagnostics)>1)
        self.previous.setEnabled(multiple)
        self.next.setEnabled(multiple)
        self.font_settings.setEnabled(active)
        self.copy.setEnabled(bool(self.groups))
        self.list.setEnabled(active or self.snapshot is None)

    def open_font_settings(self):
        from ..resources_ui import open_management
        open_management(self.owner, "fonts")

    def copy_report(self):
        lines=["InkStruct 排版问题报告",self.summary.text(),self.export_state.text()]
        if self.snapshot is not None and not self.owner.canvas.isEnabled():
            lines.append("此报告来自上次预览，当前内容正在重排。")
        for group in self.groups:
            lines.extend(("",group.title,group.suggestion))
            for diagnostic in (*group.diagnostics,*group.related):
                lines.append(f"- {self.location_text(diagnostic)} [{diagnostic.code}] {diagnostic.message}")
        QtWidgets.QApplication.clipboard().setText("\n".join(lines))
