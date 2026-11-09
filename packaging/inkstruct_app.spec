import os
import sys
import runpy
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, copy_metadata

root = Path(SPECPATH).parent
app_version = runpy.run_path(str(root / 'src/inkstruct/fonts/__init__.py'))['APP_VERSION']
layout_preview = os.environ.get('INKSTRUCT_BUILD_LAYOUT_PREVIEW') == '1'
product_name = 'InkStruct Layout Preview' if layout_preview else 'InkStruct'
excluded = ['inkstruct.train','inkstruct.model','inkstruct.dataset','torch','torchvision',
            'h5py','lmdb','pytest','scipy','pandas']
if sys.platform == 'win32':
    excluded += ['PySide6.QtPdf', 'PySide6.QtPdfWidgets']
else:
    excluded += ['inkstruct.editor.pdf_windows']

def windows_version(executable):
    if sys.platform != 'win32':
        return None
    from PyInstaller.utils.win32.versioninfo import (
        VSVersionInfo, FixedFileInfo, StringFileInfo, StringTable, StringStruct,
        VarFileInfo, VarStruct,
    )
    version = tuple(map(int, app_version.split('.'))) + (0,)
    return VSVersionInfo(
        ffi=FixedFileInfo(filevers=version, prodvers=version, mask=0x3f,
                          flags=0, OS=0x40004, fileType=1, subtype=0, date=(0, 0)),
        kids=[StringFileInfo([StringTable('040904B0', [
            StringStruct('FileDescription', product_name),
            StringStruct('FileVersion', app_version),
            StringStruct('ProductName', product_name),
            StringStruct('ProductVersion', app_version),
            StringStruct('InternalName', executable),
            StringStruct('OriginalFilename', executable + '.exe'),
        ])]), VarFileInfo([VarStruct('Translation', [1033, 1200])])],
    )

kernel = root / 'artifacts/external/data_collection'
# Desktop methods use NumPy only; neural research is excluded.
hidden = collect_submodules('inkstruct', filter=lambda n: not any(
    n == 'inkstruct.' + part for part in ('train', 'model', 'dataset')))
hidden += ['PySide6.QtTest', 'handwriting_collector.ui', 'handwriting_collector.canvas',
           'handwriting_collector.models', 'handwriting_collector.config',
           'handwriting_collector.storage', 'handwriting_collector.tasks']
data = [(str(root/'LICENSE'), 'licenses/inkstruct'),
        (str(root/'THIRD_PARTY_NOTICES.md'), 'licenses'),
        (str(root/'third_party/runtime-licenses'), 'licenses/runtime'),
        (str(root/'packaging/public-resources.lock.json'), 'licenses'),
        (str(root/'packaging/inkstruct_smoke.py'), '.'),
        (str(root/'src/inkstruct/editor/resources'), 'inkstruct/editor/resources'),
        (str(root/'packaging/inkstruct_layout_smoke.py'), '.'),
        (str(root/'artifacts/structures/characters.sqlite3'), 'data'),
        (str(kernel/'handwriting_collector'), 'collector_kernel/handwriting_collector'),
        (str(root/'configs'), 'configs'),
        (str(root/'third_party/makemeahanzi/graphics.txt'), 'third_party/makemeahanzi'),
        (str(root/'third_party/makemeahanzi/dictionary.txt'), 'third_party/makemeahanzi'),
        (str(root/'third_party/makemeahanzi/COPYING'), 'licenses/makemeahanzi'),
        (str(root/'third_party/makemeahanzi/LGPL'), 'licenses/makemeahanzi'),
        (str(root/'third_party/makemeahanzi/APL'), 'licenses/makemeahanzi/APL')]
# Exact source identities are used by reference correction and generation manifests.
data += [(str(p), 'inkstruct') for p in (root/'src/inkstruct').glob('*.py')
         if p.stem not in ('train', 'model', 'dataset')]
for package in ('numpy','Pillow','markdown-it-py','PySide6','matplotlib'):
    data += copy_metadata(package, recursive=True)
if sys.platform == 'win32':
    data += copy_metadata('winrt-Windows.Data.Pdf', recursive=True)
    data += [(str(root / 'packaging' / name), 'licenses')
             for name in ('QT_SOURCES.md', 'qt-windows-sources.json')]
entry = root/'packaging'/('inkstruct_layout_launcher.py' if layout_preview else 'inkstruct_launcher.py')
a=Analysis([str(entry)],pathex=[str(root/'src'),str(kernel),str(root/'packaging')],
    hiddenimports=hidden,datas=data,
    hooksconfig={"matplotlib": {"backends": []}},
    excludes=excluded)
a.datas=[('inkstruct-smoke.py' if name=='inkstruct_smoke.py' else name,path,kind)
         for name,path,kind in a.datas
         if '__pycache__' not in name and not name.endswith('.pyc')
         and not name.replace('\\','/').startswith('matplotlib/mpl-data/sample_data/')]
if sys.platform == 'win32':
    sys.path.insert(0, SPECPATH)
    from windows_bundle import excluded_binary

    a.binaries = [entry for entry in a.binaries if not excluded_binary(entry[0])]
pyz=PYZ(a.pure)
app_exe=EXE(pyz,a.scripts,[],exclude_binaries=True,name='InkStruct',console=False,
            version=windows_version('InkStruct'),
            icon=str(root/'src/inkstruct/editor/resources/inkstruct.ico') if sys.platform=='win32' else None,
            target_arch='arm64' if sys.platform=='darwin' else None)
tool=EXE(pyz,a.scripts,[],exclude_binaries=True,name='InkStructTool',console=True,
         version=windows_version('InkStructTool'),
         target_arch='arm64' if sys.platform=='darwin' else None)
collection=COLLECT(app_exe,tool,a.binaries,a.datas,name='InkStruct')
if sys.platform=='darwin':
    app=BUNDLE(collection,name='InkStruct.app',bundle_identifier='org.inkstruct.desktop',version=app_version,
        info_plist={'CFBundleShortVersionString':app_version,'CFBundleVersion':app_version,
                    'NSHighResolutionCapable':True,'LSMinimumSystemVersion':'14.0',
                    'LSBackgroundOnly':False,'LSUIElement':False})
