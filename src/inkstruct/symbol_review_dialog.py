"""Select saved symbol specimens to rerecord, with a read-only ink preview."""
from PySide6 import QtCore, QtGui, QtWidgets

from .symbol_revisions import read_sample
from .symbol_tasks import item_letter_style


class InkPreview(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.value = None
        self.setMinimumSize(240, 180)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.fillRect(self.rect(), QtGui.QColor('white'))
        if not self.value:
            return
        strokes = [s['points'] for s in self.value['strokes']]
        points = [p for s in strokes for p in s]
        if not points:
            return
        left, top = min(p['x'] for p in points), min(p['y'] for p in points)
        width = max(p['x'] for p in points)-left
        height = max(p['y'] for p in points)-top
        scale = min((self.width()-30)/max(width, 1), (self.height()-30)/max(height, 1))
        dx, dy = (self.width()-width*scale)/2, (self.height()-height*scale)/2
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.setPen(QtGui.QPen(QtGui.QColor('#18212f'), 2.2, QtCore.Qt.SolidLine,
                                 QtCore.Qt.RoundCap, QtCore.Qt.RoundJoin))
        for stroke in strokes:
            path = QtGui.QPainterPath()
            for i, point in enumerate(stroke):
                position = QtCore.QPointF(dx+(point['x']-left)*scale,dy+(point['y']-top)*scale)
                if i == 0:
                    path.moveTo(position)
                else:
                    path.lineTo(position)
            if len(stroke) == 1:
                painter.drawPoint(path.currentPosition())
            else:
                painter.drawPath(path)


class SymbolReviewDialog(QtWidgets.QDialog):
    def __init__(self, task, root, parent=None):
        super().__init__(parent)
        self.task, self.root = task, root
        self.items = {i.item_id:i for i in task.items if i.status == 'completed'}
        self.setWindowTitle('重录已保存样本')
        self.resize(760, 510)
        layout = QtWidgets.QVBoxLayout(self)
        hint = QtWidgets.QLabel('选择误录的份次（可用 Ctrl/Shift 多选）。重录后退回待采，原始笔迹保留备份，不再参与字体制作。已有字体和文档不会自动改写。')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        row = QtWidgets.QHBoxLayout()
        self.list = QtWidgets.QListWidget()
        self.list.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        for item in self.items.values():
            style = {'upright':'英文正体', 'italic':'英文斜体'}.get(item_letter_style(task,item),'')
            entry = QtWidgets.QListWidgetItem(f'{item.character} · {style} · 第 {item.repeat_index}/{item.repeat_total} 份')
            entry.setData(QtCore.Qt.UserRole,item.item_id)
            self.list.addItem(entry)
        row.addWidget(self.list, 1)
        self.preview = InkPreview()
        row.addWidget(self.preview, 1)
        layout.addLayout(row, 1)
        self.same_button = QtWidgets.QPushButton('选择同字符／写法的全部已保存份次')
        self.same_button.clicked.connect(self.select_same)
        layout.addWidget(self.same_button)
        self.info = QtWidgets.QLabel()
        self.info.setWordWrap(True)
        layout.addWidget(self.info)
        self.buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        self.buttons.button(QtWidgets.QDialogButtonBox.Ok).setText('重录所选（保留旧样本）')
        self.buttons.button(QtWidgets.QDialogButtonBox.Cancel).setText('取消')
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.list.itemSelectionChanged.connect(self.selection_changed)
        self.list.setCurrentRow(self.list.count()-1)
        self.selection_changed()

    def selected_ids(self):
        return [i.data(QtCore.Qt.UserRole) for i in self.list.selectedItems()]

    def select_same(self):
        entry = self.list.currentItem()
        if entry is None:
            return
        current = self.items[entry.data(QtCore.Qt.UserRole)]
        style = item_letter_style(self.task,current)
        with QtCore.QSignalBlocker(self.list):
            for row in range(self.list.count()):
                entry = self.list.item(row)
                item = self.items[entry.data(QtCore.Qt.UserRole)]
                entry.setSelected(item.character==current.character and item_letter_style(self.task,item)==style)
        self.selection_changed()

    def selection_changed(self):
        selected = self.selected_ids()
        self.preview.value = None
        valid = bool(selected)
        try:
            if selected:
                for item_id in selected:
                    _, _, value = read_sample(self.root,self.task,self.items[item_id])
                self.preview.value = value
            self.info.setText(f'已选择 {len(selected)} 份；右侧显示最后一份的原始笔迹预览。')
        except (OSError, ValueError, KeyError, TypeError) as error:
            self.info.setText('无法读取样本，未修改数据：'+str(error))
            valid = False
        self.buttons.button(QtWidgets.QDialogButtonBox.Ok).setEnabled(valid)
        self.preview.update()
