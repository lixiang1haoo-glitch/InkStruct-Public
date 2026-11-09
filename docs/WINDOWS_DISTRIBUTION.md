# Windows 构建与分发

0.1.68 是 InkStruct 的首个公开源码版本。应用源码、采集器代码、图标及项目贡献按仓库的 MIT 声明发布。第三方资源和依赖适用各自的许可。 [MIT 许可](../LICENSE) · [第三方声明](../THIRD_PARTY_NOTICES.md)

## 构建产物和验证

- `InkStruct-0.1.68-Windows-x64.zip` 可解压后直接运行 `InkStruct.exe`。安装程序 `InkStruct-0.1.68-Windows-x64-Installer.exe` 默认安装到当前用户的程序目录，创建开始菜单入口。
- 0.1.68 应用构建对应提交 `cee88ceb315fa3c12598c7b6d21b76f260632888`。在 Windows 11 x64 上，295 项源码回归全部通过。两个随包程序均通过公式与主题自检。隔离安装检查逐项核对了安装文件、启动程序，并确认卸载保留合成用户文件。
- 验证使用已有 Visual C++ x64 运行库的 Windows 11 环境。隔离模式跳过开始菜单与卸载注册。安装器尚未签名。验证记录中的二进制哈希供核对本地候选。 [构建验证记录](releases/0.1.68-windows.json) · [本机依赖清单](releases/0.1.68-native-components.json)

## 字形结构库

`characters.sqlite3` 由锁定的 Make Me a Hanzi 字典与图形数据生成。仓库保留转换器和原始数据的精确下载地址、版本及 SHA-256。运行 `python -B packaging/prepare_public_resources.py` 可重建数据库并校验文件与逻辑内容。转换包括坐标归一化、部件图提取和字表标签，数据库元数据记录了修改方式及时间。 [转换器](../packaging/prepare_public_resources.py) · [结构库实现](../src/inkstruct/structures.py) · [资源锁](../packaging/public-resources.lock.json)

分发结构库时，应随包提供 Make Me a Hanzi 的原始 `COPYING`、`LGPL` 及 `APL` 文件，并提供精确原始输入、完整修改及转换器。图形派生数据继续遵守 Arphic Public License，字典派生数据继续遵守 LGPL-3.0-or-later，Unihan 字表保留 Unicode License V3。 [Make Me a Hanzi COPYING](https://raw.githubusercontent.com/skishore/makemeahanzi/bddc96d41bef78427ed0e034e9f7e31d71fd1b92/COPYING) · [Arphic Public License](https://raw.githubusercontent.com/skishore/makemeahanzi/bddc96d41bef78427ed0e034e9f7e31d71fd1b92/APL/english/ARPHICPL.TXT) · [Unicode License V3](../configs/character_sets/UNICODE-LICENSE.txt)

## Qt、PySide6 和 Shiboken

Windows 构建通过 PySide6 动态加载 Qt。对应版本为 6.9.2，构建资源脚本下载 Qt LGPLv3 和 GPLv3 全文，构建脚本随包附上原文。Qt 6.9.2 模块来源按随包文件划分如下。 [Qt 许可义务](https://www.qt.io/development/open-source-lgpl-obligations)

| 随包组件 | 对应上游源码 |
| --- | --- |
| PySide6 Python 扩展、Shiboken | [pyside-setup 6.9.2](https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.9.2-src/) |
| Core、Gui、Network、OpenGL、Test、Widgets、Windows 平台与样式插件 | [qtbase 6.9.2](https://download.qt.io/archive/qt/6.9/6.9.2/submodules/qtbase-everywhere-src-6.9.2.tar.xz) |
| Qml、Quick | [qtdeclarative 6.9.2](https://download.qt.io/archive/qt/6.9/6.9.2/submodules/qtdeclarative-everywhere-src-6.9.2.tar.xz) |
| Svg、SvgWidgets | [qtsvg 6.9.2](https://download.qt.io/archive/qt/6.9/6.9.2/submodules/qtsvg-everywhere-src-6.9.2.tar.xz) |
| Qt PDF 与 PDFium | [qtwebengine 6.9.2](https://download.qt.io/archive/qt/6.9/6.9.2/submodules/qtwebengine-everywhere-src-6.9.2.tar.xz) · [Qt PDF 及内嵌组件许可](https://doc.qt.io/qt-6.8/qtpdf-licensing.html) |
| 额外图片格式插件、翻译文件 | [Qt 6.9.2 组件归档](https://download.qt.io/archive/qt/6.9/6.9.2/submodules/)中的 qtimageformats、qttranslations |

用户可按 LGPL 条款修改适用组件，并为调试修改进行相关逆向工程。替换时先退出 InkStruct，在独立的免安装副本中备份 `_internal/PySide6` 和 `_internal/shiboken6`，再用同一架构及 ABI 兼容的动态库和插件替换对应文件。保留 PySide6 与 Shiboken 版本匹配。也可在源码环境中用自己构建的兼容 PySide6、Shiboken 和 Qt 运行应用。发布前应实际复验这一流程，并提供精确对应的构建配置、源码及随附组件通知。 [Qt 6.9 第三方组件](https://doc.qt.io/archives/qt-6.9/licenses-used-in-qt.html)

## Windows 二进制分发状态

当前公开版本提供源码。0.1.68 候选的预编译安装程序与 ZIP 尚未作为公开附件发布。二进制分发前仍需补齐 Qt/PDFium 及随 wheel 提供的软件渲染器的对应源码和通知，验证动态库替换，并核实 NumPy wheel 内重命名的 Microsoft 运行库的再分发依据。独立的 Microsoft 运行库文件由 Windows 或用户安装的官方运行库提供。 [Visual C++ 文件的再分发条件](https://learn.microsoft.com/en-us/cpp/windows/redistributing-visual-cpp-files)
