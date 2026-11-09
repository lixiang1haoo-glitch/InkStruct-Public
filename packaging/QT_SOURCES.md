# InkStruct for Windows uses Qt

InkStruct dynamically links Qt 6.9.2 through PySide6 and Shiboken 6.9.2.
See the Qt LGPLv3 and GPLv3 texts in `runtime/`. For the exact source archive
names, upstream URLs and SHA-256 hashes, see `qt-windows-sources.json`.
These archives are also provided alongside the Windows ZIP and installer.

[InkStruct 0.1.69 downloads and corresponding sources](https://github.com/lixiang1haoo-glitch/InkStruct-Public/releases/tag/app-v0.1.69)

The LGPL permits modification of the covered libraries and reverse engineering
to debug those modifications. To run with compatible modified libraries, close
both InkStruct programs, extract an independent copy of the Windows ZIP, and
back up `_internal/PySide6` and `_internal/shiboken6`. Replace the affected x64
libraries, Python extensions and plugins in those directories. Keep Qt, plugins
that use private Qt APIs, PySide6 and Shiboken mutually compatible. Run
`InkStruct.exe` from the copy. The program does not require the original DLL
hashes or signatures. To build the libraries, use the matching source archives
and the Qt for Python build instructions.

[Qt for Python build instructions](https://doc.qt.io/qtforpython-6/building_from_source/index.html)

## 中文

Windows 版通过 PySide6 和 Shiboken 动态加载 Qt 6.9.2。`runtime/` 目录包含许可全文，
`qt-windows-sources.json` 记录对应源码的下载地址和 SHA-256。发行页也提供这些归档。
LGPL 允许修改受许可覆盖的库，以及为调试修改进行逆向工程。退出两个程序后，在免安装
ZIP 的独立副本中备份上述目录，再替换互相兼容的 x64 动态库、Python 扩展和插件。
