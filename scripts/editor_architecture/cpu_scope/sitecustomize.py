"""Opt-in subprocess test scope; no global registry or application environment edits."""
import os
if os.environ.get('INKSTRUCT_TEST_CPU_SCOPE'):
    from PySide6 import QtCore
    QtCore.QSettings.setDefaultFormat(QtCore.QSettings.Format.IniFormat)
    QtCore.QSettings.setPath(QtCore.QSettings.Format.IniFormat,QtCore.QSettings.Scope.UserScope,
                             os.environ['INKSTRUCT_TEST_CPU_SCOPE'])
    private=QtCore.QSettings(QtCore.QSettings.defaultFormat(),QtCore.QSettings.Scope.UserScope,'InkStruct','UnifiedSettings')
    private.setValue('preview_backend_v1','cpu');private.sync()
