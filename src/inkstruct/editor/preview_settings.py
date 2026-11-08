"""Local display preferences, separate from document/default layout protocols."""
from PySide6 import QtCore, QtWidgets

from ..global_defaults import GlobalDefaultsStore
from ..ui_behavior import compact_field


class PreviewSettingsPage(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        column = QtWidgets.QVBoxLayout(self)
        self.backend = QtWidgets.QComboBox()
        self.backend.setObjectName('preview_backend')
        self.backend.addItem('CPU（默认，兼容性优先）', 'cpu')
        self.backend.addItem('GPU 栅格化（可选，失败自动回退 CPU）', 'gpu')
        current = GlobalDefaultsStore.make_settings().value('preview_backend_v1', 'cpu', str)
        self.backend.setCurrentIndex(max(0, self.backend.findData(current)))
        column.addWidget(QtWidgets.QLabel('页面预览绘制后端'))
        column.addWidget(compact_field(self.backend))
        text = QtWidgets.QLabel('保存后下次启动应用生效。仅影响屏幕栅格化，不改变排版、选字或 SVG 导出。'
                               '\nCPU 与 GPU 均启用有限 SVG 解析缓存及预取优化。GPU 保留 8 倍抗锯齿；设备不支持或发生错误时使用 CPU。')
        text.setWordWrap(True)
        column.addWidget(text)
        column.addStretch()

    def save(self):
        settings = GlobalDefaultsStore.make_settings()
        settings.setValue('preview_backend_v1', self.backend.currentData())
        settings.sync()
        if settings.status() != QtCore.QSettings.Status.NoError:
            raise OSError('预览设置保存失败')

    def reset_defaults(self):
        self.backend.setCurrentIndex(0)
