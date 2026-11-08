# Build with a platform-native Python environment containing desktop dependencies.
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules, copy_metadata

root = Path(SPECPATH).parent
hidden = ['PySide6.QtTest']
for package in ('editor', 'document', 'layout', 'math', 'assets', 'scene', 'renderers', 'plotter'):
    hidden += collect_submodules('inkstruct.' + package)
data = [(str(root / 'packaging/editor_offline/smoke.py'), '.'),
        (str(root / 'src/inkstruct/editor/resources'), 'inkstruct/editor/resources')]
# Preserve metadata and licenses; self-check records exact installed versions.
for package in ('inkstruct', 'numpy', 'Pillow', 'markdown-it-py', 'mdurl', 'PySide6', 'PySide6_Essentials', 'PySide6_Addons', 'shiboken6'):
    data += copy_metadata(package)
a = Analysis(
    [str(root / 'packaging/editor_launcher.py')],
    pathex=[str(root / 'src')],
    hiddenimports=hidden,
    datas=data,
    excludes=['torch', 'torchvision', 'h5py', 'lmdb', 'matplotlib', 'pytest', 'scipy', 'pandas'],
)
# Rename the trusted verification script without changing its source.
a.datas = [('editor-smoke.py' if name == 'smoke.py' else name, path, kind) for name, path, kind in a.datas]
pyz = PYZ(a.pure)
editor = EXE(pyz, a.scripts, [], exclude_binaries=True, name='InkStructEditor', console=False, target_arch='arm64' if sys.platform == 'darwin' else None)
# A separate console binary is required for stdin/stdout JSON on Windows.
tool = EXE(pyz, a.scripts, [], exclude_binaries=True, name='InkStructTool', console=True, target_arch='arm64' if sys.platform == 'darwin' else None)
collection = COLLECT(editor, tool, a.binaries, a.datas, name='InkStructEditor')
if sys.platform == 'darwin':
    # COLLECT inherits console=True from the companion tool. Override the bundle
    # classification explicitly: the Finder entrypoint is the foreground editor.
    app = BUNDLE(collection, name='InkStructEditor.app', bundle_identifier='org.inkstruct.editor', info_plist={
        'NSHighResolutionCapable': True,
        'LSMinimumSystemVersion': '14.0',
        'LSBackgroundOnly': False,
        'LSUIElement': False,
    })
