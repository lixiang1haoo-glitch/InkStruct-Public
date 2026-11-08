# 混排编辑器离线安装材料

本工具为 Python 3.13 的 macOS Apple Silicon（macOS 14 起）和 Windows x64 分别准备依赖材料。包含工作区构建的 InkStruct wheel、固定版本运行依赖、校验清单、安装与启动脚本、公共模板示例和功能检查程序。**不包含 Python 安装程序，不是免安装应用，也不是已签名或公证的安装器。** Windows 实际安装及原生交互必须在 Windows 上验收。

## 安装

先安装与目标平台匹配的 Python 3.13，将对应材料完整复制到可写目录：

```sh
# macOS，在材料目录中执行
python3.13 install.py --verify-only
python3.13 install.py
runtime/bin/python -I -m inkstruct.editor.app
```

```powershell
# Windows，在材料目录中执行
py -3.13 install.py --verify-only
py -3.13 install.py
runtime\Scripts\python.exe -I -m inkstruct.editor.app
```

也可使用对应的“启动编辑器”脚本。安装会校验平台、文件哈希和依赖目录，创建新的 `runtime` 虚拟环境，并以 `--isolated --no-index --require-hashes` 从本地 wheels 安装，不查询网络索引。不会修改系统 Python、其他项目环境或已有 runtime。失败的 runtime 保留供排查；重试或升级请从原材料复制到新的目录安装，不自动删除旧环境。已安装虚拟环境不承诺移动后仍可使用。

包内没有个人字形、录制样本、检查记录或私有项目。可导入自己含嵌入资源的 `.inkdoc`，也可用内置数字检查基础布局。第三方许可证随原 wheel 保留。校验哈希用于发现材料损坏，不是可信来源的数字签名。

## 功能验证

使用安装后的解释器运行：

```sh
QT_QPA_PLATFORM=offscreen runtime/bin/python -I smoke.py --output /path/to/new-verification
```

Windows 可在 PowerShell 设置 `$env:QT_QPA_PLATFORM='offscreen'`，再以 `runtime\Scripts\python.exe -I smoke.py --output 新目录` 执行。真实界面测试时不要设置 offscreen。

检查程序拒绝从源码工作区导入 InkStruct，验证数字、表格、分数在实际混排窗口构建；保存原生项目、重开并比较优化机器 SVG 字节；调用已安装的 PDF 子进程；输出包版本、实际模块位置、机器文件哈希和 `verification.json`。检查进程禁止网络连接和域名查询；PDF 子进程继续使用同一已安装解释器。测试产物写到指定新目录，不写入用户项目。

这些结果只证明所测平台和工作负载。没有验证 Windows 原生输入法、DPI、字体缺失、文件选择对话框或写字机纸面效果。完整离线运行还要求目标设备已具备匹配 Python；未来独立运行时/冻结安装包仍需另行构建验收。

## 构建与复现

在独立构建环境安装项目声明的 hatchling 后，以当前工作区构建 wheel；不从 Git HEAD 代替本机未提交源码：

```sh
python -m pip wheel --no-deps --no-build-isolation --wheel-dir project-wheel .
```

联网准备依赖（下载阶段与离线安装阶段分开）：

```sh
# 在 macOS arm64 Python 3.13 上
python -m pip download --only-binary=:all: --dest macos-wheels \
  numpy==2.5.3 Pillow==12.3.0 markdown-it-py==4.0.0 mdurl==0.1.2 PySide6==6.9.2

# 可跨平台下载 Windows x64 Python 3.13 材料；不代表在本机执行过 Windows
python -m pip download --only-binary=:all: --platform win_amd64 \
  --python-version 313 --implementation cp --abi cp313 --dest windows-wheels \
  numpy==2.5.3 Pillow==12.3.0 markdown-it-py==4.0.0 mdurl==0.1.2 PySide6==6.9.2
```

组装脚本需要 pip 自带的 wheel 标签解析工具。使用新输出目录：

```sh
python packaging/build_editor_offline_kit.py --target macos-arm64 \
  --wheelhouse macos-wheels --project-wheel project-wheel/inkstruct-0.2.0-py3-none-any.whl \
  --output macos-kit
```

Windows 改用 `--target windows-x64` 及对应 wheelhouse。组装会核对预期九个包、身份、版本和目标 wheel 标签，拒绝漏包、重复包、其他架构或输出已存在；具体依赖约束还需通过安装器的完整 pip 解析和 `pip check` 验证。`requirements.lock` 固定每个版本和 wheel 哈希，`manifest.json` 记录全部材料。不同源码构建即使同为 0.2.0，也须按 wheel 哈希区分。

当前交付和验证证据见 [进度记录](MARKDOWN_MIXED_LAYOUT_PROGRESS_20261013.md)，不能仅凭组装成功将 `native_platform_verified` 标记为 true。


另已构建内含 Python 的 [macOS 独立测试应用](EDITOR_STANDALONE.md)。本文件介绍的 wheel 材料仍要求预装 Python，两种产物和验证范围分别记录，不相互替代。

## 2026-10-14 Windows 当前源码更新材料

当前 Windows ZIP：`artifacts/editor_windows_refresh_20261014/InkStruct-editor-windows-x64-py313-preview-update.zip`。大小 **254,970,709 字节**，SHA-256 `650f07ed0bd977715e667b527b3a7e28290976e17890f68ef2a27c325dca6ffa`。需要 Windows x64 与 Python 3.13，不含 Python 运行时；请解压到新目录安装。包内 `验收步骤.md` 提供自动检查命令、真实输入法/窗口/保存重开/模板操作及需保留的证据。

该包冻结当前工作区源码并保留包内字符清单资源，包含顶部控件换行、模板绑定前置提示、提前取消和首次预览加载修复。最终 wheel 与冻结包内全部源码/资源逐项一致；与此前 wheel 相比无文件丢失。构建时初次冻结只复制 Python 文件而遗漏字符清单，完整性检查拒绝后已补齐并重建；初次不完整材料保留在交付 ZIP 之外。

九个 Windows 依赖包全部沿用已下载材料，离线依赖解析通过，ZIP 内文件逐项符合校验清单。相同的纯 Python 应用 wheel 已在全新 macOS 环境以固定本地依赖安装并完成新版自检：编辑/IME 合成事件的提前取消、撤销身份恢复、1000 × 700 窗口、缩放、模板绑定、项目往返 SVG 与 PDF 子进程。该检查实际从新环境导入模块，不借用工作区源码。此前 macOS 独立应用中的 142 个产品模块与此次快照逐项相同，未更改产品代码或重复全量测试。

完整证据见 `artifacts/editor_windows_refresh_20261014/verification.json`。**Windows 安装、原生交互、Windows 独立 EXE 与纸面试写仍未验证**；清单维持 `native_platform_verified: false`。macOS 自检不能代替 Windows 结果。旧 Windows ZIP、旧 macOS wheel 材料和已有运行环境不会自动升级；当前 macOS 独立应用未重建。
