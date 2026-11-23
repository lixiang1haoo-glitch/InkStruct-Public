"""Local paper marks and single-sheet registration."""
from dataclasses import asdict, dataclass
from uuid import UUID

from PySide6 import QtCore, QtGui, QtWidgets

from ..document.flow_template import FlowTemplate
from ..document.schema import digest
from ..document.template import PageTemplate
from ..plotter.profiles import PageAlignment
from ..sample_preview import InkViewport, SampleView
from ..settings_pages import label


def template_family(template, snapshot):
    if getattr(template, 'revision', None):
        return template.revision.template_id
    local = getattr(template, 'family_id', '')
    return str(UUID(hex=local)) if local else snapshot.document_id


def page_context(template, snapshot=None, index=0, *, layout=None):
    if isinstance(template, FlowTemplate):
        source = layout or template.layout(index)
        size = template.width_mm, template.height_mm
        family = template_family(template, snapshot)
        frames = [(frame.frame_id, frame.role, frame.order, frame.field_id, frame.region.bounds,
                   asdict(frame.paper_grid) if frame.paper_grid else None) for frame in source.frames]
        key = digest([family, source.layout_id, size, template.offset_x_mm, template.offset_y_mm,
                      source.source_size_mm, source.source_sha256, source.source_page,
                      source.background.sha256 if source.background else None, frames,
                      [(rule.points, rule.width_mm) for rule in source.rules]])
        title = f"PDF 第 {source.source_page} 页" if source.source_page else source.label
        legacy = template.paper_origin(source)
        return key, size, PageAlignment(legacy.a) if legacy else None, title
    if isinstance(template, PageTemplate):
        face = template.first if index == 0 else template.continuation
        size = template.width_mm, template.height_mm
        role = '首页' if index == 0 else '续页'
        return digest([template_family(template, snapshot), role, size, asdict(face),
                       template.offset_x_mm, template.offset_y_mm]), size, None, role
    paper = snapshot.page_profile
    size = paper.width_mm, paper.height_mm
    page = snapshot.pages[index]
    return digest([snapshot.document_id, page.source_layout, asdict(paper),
                   page.background.sha256 if page.background else None]), size, None, page.source_layout or "普通页面"


@dataclass(frozen=True)
class FixturePlacement:
    alignment: PageAlignment
    position: tuple
    source: str


class AlignmentCanvas(InkViewport):
    picked = QtCore.Signal(float, float)

    def __init__(self, size, backdrop):
        view = SampleView()
        super().__init__(view)
        view.bounds = QtCore.QRectF(0, 0, *size)
        view.reset()
        self.backdrop = backdrop
        self.points = []
        self.editable = False
        self.checking = False
        self.setMinimumSize(240, 310)
        self.setAccessibleName("纸面预览 · 选择对位点")
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)

    def has_ink(self):
        # The paper itself can be aligned even without a background image.
        return True

    def ink_clicked(self, position):
        inverse, invertible = self.drawing_transform().inverted()
        spot = inverse.map(position)
        if (self.editable or self.checking) and invertible and self.view.bounds.contains(spot):
            self.picked.emit(spot.x(), spot.y())

    def paintEvent(self, _event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), self.palette().window())
        transform = self.drawing_transform()
        rect = transform.mapRect(self.view.bounds)
        painter.fillRect(rect, QtGui.QColor("white"))
        if not self.backdrop.isNull():
            painter.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform)
            painter.drawImage(rect, self.backdrop)
        painter.save()
        painter.setClipRect(rect)
        for title, (x, y) in self.points:
            spot = transform.map(QtCore.QPointF(x, y))
            painter.setPen(QtGui.QPen(QtGui.QColor("#005c92"), 2))
            painter.drawLine(spot - QtCore.QPointF(7, 0), spot + QtCore.QPointF(7, 0))
            painter.drawLine(spot - QtCore.QPointF(0, 7), spot + QtCore.QPointF(0, 7))
            painter.drawText(spot + QtCore.QPointF(7, 15), title)
        painter.restore()


class AlignmentDialog(QtWidgets.QDialog):
    def __init__(self, panel, key, size, mark, title, *, recovery=False, temporary=False, archived=False):
        super().__init__(panel)
        self.panel = panel
        self.key = key
        self.sheet = None if archived else (panel.snapshot, panel.paper_page.index)
        self.mark = mark
        self.recovery = recovery
        self.temporary = temporary
        self.setWindowTitle(("恢复停靠点" if recovery else "临时对位" if temporary else "纸面原点") + " · " + title)
        self.resize(680, 600)
        col = QtWidgets.QVBoxLayout(self)
        page = None if archived else panel.snapshot.pages[panel.paper_page.index]
        backdrop = QtGui.QImage.fromData(page.background.png_bytes(), "PNG") if page and page.background else QtGui.QImage()
        self.canvas = AlignmentCanvas(size, backdrop)
        self.canvas.editable = not (temporary or recovery)
        self.canvas.picked.connect(self.pick)
        col.addWidget(self.canvas, 1)
        if archived:
            col.addWidget(label(f'请放入此版式的原规格印刷纸（{size[0]:g} × {size[1]:g} mm）。'))
        col.addWidget(label("请按原挡边摆纸，把笔尖移到标记。" if self.mark else
                            "请点击纸面标记，再把笔尖移到该处。"))
        self.pad = panel.motion_controls(panel.jog)
        col.addWidget(self.pad)
        self.pen = panel.button("抬笔", panel.toggle_pen)
        col.addWidget(self.pen)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        self.record = buttons.addButton("恢复停靠点" if recovery else "应用到本张纸" if temporary else
                                        "保存本机原点", QtWidgets.QDialogButtonBox.ButtonRole.AcceptRole)
        self.record.clicked.connect(self.capture)
        buttons.rejected.connect(self.reject)
        col.addWidget(buttons)
        self.session = panel.connection_id
        self.panel.machine_state.connect(self.refresh)
        self.refresh()

    def pick(self, x, y):
        self.mark = PageAlignment((round(x, 3), round(y, 3)))
        self.refresh()

    def refresh(self):
        p = self.panel
        ready = bool(p.device and self.session == p.connection_id and not p.busy)
        self.canvas.points = [("纸面原点", self.mark.a)] if self.mark else []
        self.canvas.update()
        p.refresh_motion_controls(self.pad, ready)
        p.refresh_pen_button(self.pen)
        if self.session != p.connection_id:
            self.pen.setEnabled(False)
        self.record.setEnabled(bool(ready and p.pen_raised and self.mark and (p.datum_located or self.recovery)))

    def capture(self):
        def measured(status):
            if not self.isVisible() or self.session != self.panel.connection_id:
                return
            if self.sheet is None:
                self.panel.restore_from_sheet(self.key, self.mark, status)
            elif (self.panel.snapshot is self.sheet[0] and self.panel.current_page_ready()
                  and self.panel.paper_page.index == self.sheet[1]):
                self.panel.measure_sheet(self.key, self.mark, status, recovery=self.recovery, temporary=self.temporary)
            else:
                return
            self.accept()
        self.panel.capture_position(measured, datum=True)

    def reject(self):
        if not self.panel.busy:
            super().reject()
