"""One management destination; settings and document pickers reuse its browsers."""

from pathlib import Path

from PySide6 import QtWidgets

from .fonts.ui import FontLibrary
from .resource_catalog import workspace_for


class ResourceLibrary(QtWidgets.QTabWidget):
    def __init__(self, editor, fonts, parent=None):
        super().__init__(parent)
        from .editor.template_library import TemplateLibrary
        self.fonts = fonts
        self.templates = TemplateLibrary(editor, self)
        self.addTab(fonts, '字体')
        self.addTab(self.templates, '模板')
        self.setObjectName('font_and_template_library')


class FontPicker(QtWidgets.QDialog):
    def __init__(self, parent=None, *, default=False):
        super().__init__(parent)
        self.setWindowTitle('选择新文档默认字体' if default else '选择本文字体')
        self.resize(1080, 730)
        self.path = None
        self.cancelled = False
        col = QtWidgets.QVBoxLayout(self)
        col.addWidget(QtWidgets.QLabel('只选择资源；新文档默认需在设置中应用，本文更换需另行确认影响。'))
        self.browser = FontLibrary(workspace_for(parent) / 'fonts')
        self.browser.create_button.hide()
        self.browser.default_button.hide()
        self.browser.more_button.hide()
        for button in self.browser.selection_buttons:
            if button.text() != '用于当前文档…':
                button.hide()
            else:
                button.setText('选择此字体')
        self.browser.use_requested.connect(self.choose)
        col.addWidget(self.browser, 1)
        close = QtWidgets.QPushButton('取消')
        close.clicked.connect(self.reject)
        col.addWidget(close)

    def choose(self, path):
        self.cancelled = False
        from .fonts.core import cached_font
        def verify(progress):
            cached_font(Path(path))
            return {'path': path, 'picked': True, 'verified': True, 'message': '字体完整验证通过'}
        self.browser.submit(verify)
        self.browser.job.signals.completed.connect(self.chosen)

    def chosen(self, result):
        if result.get('picked') and not self.cancelled:
            self.path = result['path']
            self.accept()

    def reject(self):
        # A running read may finish later; it does not select or apply a resource.
        self.path = None
        self.cancelled = True
        super().reject()


def open_management(editor, category='templates'):
    host = getattr(editor, 'settings_host', None)
    if host and hasattr(host, 'resources'):
        host.tabs.setCurrentIndex(2)
        host.resources.setCurrentIndex(1 if category == 'templates' else 0)
        if category == 'templates':
            host.resources.templates.refresh()
        else:
            host.library.refresh()
        return
    dialog = QtWidgets.QDialog(editor)
    dialog.setWindowTitle('字体与模板')
    dialog.resize(1100, 760)
    col = QtWidgets.QVBoxLayout(dialog)
    fonts = FontLibrary(workspace_for(editor) / 'fonts')
    resources = ResourceLibrary(editor, fonts, dialog)
    resources.setCurrentIndex(1 if category == 'templates' else 0)
    fonts.use_requested.connect(lambda path: use_document_font(editor, path, dialog))
    col.addWidget(resources)
    close = QtWidgets.QPushButton('关闭资源管理')
    close.clicked.connect(dialog.accept)
    col.addWidget(close)
    dialog.exec()
    dialog.deleteLater()


def use_document_font(editor, path, parent=None):
    from .editor.resource_apply import ResourceApplyDialog
    dialog = ResourceApplyDialog(editor, font=path, parent=parent)
    result = dialog.exec()
    dialog.deleteLater()
    return result == QtWidgets.QDialog.Accepted
