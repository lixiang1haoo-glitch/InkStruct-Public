# Windows 构建与分发

0.1.74 提供 Windows 安装程序、免安装 ZIP 和对应源码。应用源码、采集器代码、图标及项目贡献按仓库的 MIT 声明发布。第三方资源和依赖适用各自的许可。[发行页与 SHA-256](https://github.com/lixiang1haoo-glitch/InkStruct-Public/releases/tag/app-v0.1.74) · [MIT 许可](../LICENSE) · [第三方声明](../THIRD_PARTY_NOTICES.md)

## 构建产物和验证

- 解压 `InkStruct-0.1.74-Windows-x64.zip` 后运行 `InkStruct.exe`。安装程序 `InkStruct-0.1.74-Windows-x64-Installer.exe` 默认安装到当前用户的程序目录，创建开始菜单入口。
- 安装和免安装版本依赖 Microsoft Visual C++ x64 运行库 14.51 或更新版本。安装程序在运行库缺失或版本过低时提供微软下载入口。静默安装返回退出码 10。安装好运行库后重新运行安装程序。[微软官方下载](https://aka.ms/vc14/vc_redist.x64.exe)
- 发行页附构建提交、依赖哈希和回归记录。隔离安装验收会跳过开始菜单与卸载注册。安装器未签名。

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
| 额外图片格式插件、翻译文件 | [Qt 6.9.2 组件归档](https://download.qt.io/archive/qt/6.9/6.9.2/submodules/)中的 qtimageformats、qttranslations |

应用包的 `_internal/licenses/QT_SOURCES.md` 提供替换说明。发行页附有上表的源码归档，清单记录上游地址和 SHA-256。[替换说明](../packaging/QT_SOURCES.md) · [源码清单](../packaging/qt-windows-sources.json) · [Qt 6.9 第三方组件](https://doc.qt.io/archives/qt-6.9/licenses-used-in-qt.html)

## Windows 图像与运行库

Windows PDF 底图由系统的 Windows.Data.Pdf 渲染。JPEG 参考图片由 Pillow 读取。预览可使用受支持的 GPU，GPU 不可用时回退到 CPU。Windows 构建会排除 Qt PDF、Qt JPEG 插件和 Qt 的 Mesa 软件渲染器。

构建脚本将锁定的 NumPy wheel 中两个扩展的运行库导入名改为系统的 `msvcp140.dll`。ZIP 和安装程序都使用微软提供的系统运行库。[Windows PDF API](https://learn.microsoft.com/uwp/api/windows.data.pdf) · [构建依赖清单](../packaging/windows-x64-py313.lock)

0.1.68 的源码和历史验证记录可从原发行页查阅。[0.1.68 发行页](https://github.com/lixiang1haoo-glitch/InkStruct-Public/releases/tag/app-v0.1.68) · [历史构建记录](releases/0.1.68-windows.json)
