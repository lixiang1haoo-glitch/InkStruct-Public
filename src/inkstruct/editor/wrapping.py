"""Toolbar controls wrap as intact groups without changing document settings."""

from PySide6 import QtCore, QtWidgets


class WrappingLayout(QtWidgets.QLayout):
    def __init__(self, parent=None, *, spacing=6):
        super().__init__(parent)
        self.items = []
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(spacing)

    def addItem(self, item):
        self.items.append(item)

    def count(self):
        return len(self.items)

    def itemAt(self, index):
        return self.items[index] if 0 <= index < len(self.items) else None

    def takeAt(self, index):
        return self.items.pop(index) if 0 <= index < len(self.items) else None

    def expandingDirections(self):
        return QtCore.Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self.arrange(QtCore.QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self.arrange(rect, apply=True)

    def minimumSize(self):
        size = QtCore.QSize()
        for item in self.items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QtCore.QSize(
            margins.left() + margins.right(), margins.top() + margins.bottom()
        )

    def sizeHint(self):
        return self.minimumSize()

    def arrange(self, rect, *, apply):
        margins = self.contentsMargins()
        area = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        x, y, row_height = area.x(), area.y(), 0
        for item in self.items:
            if item.isEmpty():
                continue
            size = item.sizeHint().expandedTo(item.minimumSize())
            if x > area.x() and x + size.width() > area.x() + area.width():
                x = area.x()
                y += row_height + self.spacing()
                row_height = 0
            if apply:
                item.setGeometry(QtCore.QRect(QtCore.QPoint(x, y), size))
            x += size.width() + self.spacing()
            row_height = max(row_height, size.height())
        return y + row_height - rect.y() + margins.bottom()

    def add_group(self, *widgets):
        group = QtWidgets.QWidget()
        row = QtWidgets.QHBoxLayout(group)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        for widget in widgets:
            row.addWidget(widget)
        self.addWidget(group)
        return group
