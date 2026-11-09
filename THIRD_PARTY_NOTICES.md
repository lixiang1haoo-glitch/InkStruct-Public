# 第三方许可与来源

仓库根目录的 MIT 文本适用于有权按 MIT 提供的项目源码及合成示例。下列第三方项目继续使用各自的许可。

## 字形结构数据

- Make Me a Hanzi 固定到 `bddc96d41bef78427ed0e034e9f7e31d71fd1b92`。`dictionary.txt` 来自 Unihan、CJKlib，按 LGPL-3.0-or-later 提供。保留 COPYING 和 LGPL，保留原始可编辑输入及生成器。 [固定版本 COPYING](https://raw.githubusercontent.com/skishore/makemeahanzi/bddc96d41bef78427ed0e034e9f7e31d71fd1b92/COPYING)
- `graphics.txt` 来自 Arphic PL KaitiM GB、Arphic PL UKai。保留原始 APL 和版权声明。分发派生字形数据时，按 APL 提供完整修改、变更说明和同等的复制及修改权限。 [Arphic 原文](https://raw.githubusercontent.com/skishore/makemeahanzi/bddc96d41bef78427ed0e034e9f7e31d71fd1b92/APL/english/ARPHICPL.TXT)
- `characters.sqlite3` 由本仓库构建步骤从上述源生成。它组合了笔画中线、部件关系与 Unihan 字表标签，保留二者的许可边界。0.1.68 的转换包括坐标归一化、部件图提取和地区标签，数据库元数据记录变更。本仓库提供转换源码和原始输入的精确锁。 [资源锁](packaging/public-resources.lock.json)

## 字表与公式参考

- 内置字表取自 Unicode Unihan 17.0.0 的 `kTGH`、`kGB1` 及变体关系。保留 Unicode License V3 及来源说明。 [仓库内许可](configs/character_sets/UNICODE-LICENSE.txt) · [上游数据](https://www.unicode.org/Public/17.0.0/ucd/)
- Latin Modern Math 1.959 由 Bogusław Jackowski、Piotr Strzelczyk 与 Piotr Pianowski 提供。完整 CTAN ZIP 保留 GUST Font License、清单、字体及文档，构建时原样下载。 [CTAN](https://ctan.org/pkg/lm-math)

## Windows 运行及构建依赖

依赖版本和 wheel 哈希见 [Windows 依赖锁](packaging/windows-x64-py313.lock)。保留 wheel 中的著作权、许可和随附组件说明。

- CPython 采用 PSF 许可及其历史和组件说明。 [Python 许可](https://docs.python.org/3/license.html)
- Qt、PySide6、Shiboken6 包含 LGPL/GPL 或商业许可条件。发布二进制前须核对实际 Qt 插件与模块，提供适用许可证、对应源码和可替换动态库的说明。 [Qt 许可](https://doc.qt.io/qt-6/licensing.html) · [LGPL 义务](https://www.qt.io/development/open-source-lgpl-obligations)
- PyInstaller 的引导器适用其打包例外。该例外保留应用及运行依赖自身的条件。 [PyInstaller 许可](https://pyinstaller.org/en/stable/license.html)
- Windows 安装程序由 NSIS 3.13 构建，随安装载荷提供该版本的 COPYING。 [NSIS 下载](https://nsis.sourceforge.io/Download) · [编译器资源锁](packaging/nsis-win.lock.json)
- NumPy、Pillow、Matplotlib 及其捆绑的本机组件使用各自的许可。源代码和二进制分发分别保留适用的许可、版权和通知。Markdown 解析依赖 markdown-it-py 与 mdurl（MIT）。 [Markdown 适配器许可](licenses/markdown-it-py.txt)
