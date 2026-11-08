# InkStruct 0.1.50 Windows 交付记录

2026-11-07。主工作区为 `C:/Users/lee/Documents/InkStructApp/InkStruct-Windows-Dev`。从含未提交工作的 0.1.49 源码继续开发，应用版本来自 `APP_VERSION`，Python 库仍为 0.2.0。构建使用 Windows 11 x64、Python 3.13.16、PySide6 6.9.2 和 PyInstaller 6.22.3。

## 改动

- 滚动条使用浅灰轨道和中性灰圆角滑块。视觉滑块收窄，拖动区域仍为 15 逻辑像素，悬停与拖动时颜色加深。全局表格设置只使用一层内容滚动，单元素属性继续使用原有入口。
- 「汉字样本」及「标点与扩展」的画布上方分别提供「笔迹粗细」。旧共用设置作为两页的初始值，调整后各自记忆。画布尺寸控件保留。显示粗细不改动采集坐标、压力、时间或任务进度。
- 从设置中移除「打开模板库」。主窗口左侧模板库和排版的文档资源入口继续可用。
- 排版菜单「文件 → 新建文档」支持 Ctrl+N。未保存项目可以先保存、放弃修改或取消操作。新文档从全局默认加载并取得新的文档身份。
- 从文件导入 Markdown 时，以源码文件夹为根，嵌入可读的 PNG、JPEG 与受支持的单线 SVG。支持中文路径、相对子目录和 URL 编码；含空格的路径可用尖括号。正文按原内容保留。缺失、外部或不合格资源列出具体问题。图片随 `.inkdoc` 保存，现有严格 SVG 导出检查继续适用。

## 实际验收

- 44 个相关测试文件，主选集 **437 项通过**，独立恢复测试 **1 项通过**。覆盖采集旧配置、独立调节、写入回退、设置事务、模板、Markdown 导入、图片撤销／重做、保存重开和导出校验。首次回归中三项旧断言仍期待「打开模板库」，一个新用例依赖离屏菜单对象的生命周期。修订验收脚本和断言后全选集通过，初次日志保留。
- Windows 原生冻结应用在 **150% 和 200%** 下各完成 9 项检查。拖动两个采集滑块，从旧共用值 220% 分别调为 242% 和 199%，持久化回读一致，符号点列保持一致。表格内容滚动条实际宽度 15 逻辑像素，检查截图实际绘制了中性灰轨道与滑块，拖动后滚动值从 0 到 145。
- 从实际「文件」菜单导入带 Windows CRLF 的小样，PNG 路径含中文和空格，JPEG 文件名使用 URL 编码。两张图均进入原生预览，源码保持原样。移动外部图片后重开项目，内嵌资源及选样一致。源文件由验收脚本通过文件对话框返回路径传入。使用的是等价小样，未使用截图对应的用户 Markdown 文件。
- 在原生文件菜单确认「新建文档」显示 Ctrl+N；验证取消保留草稿，确认放弃后用默认参数建立空白文档。另重开实际 0.1.48 文档，嵌入模板、冻结选样和原文件 SHA-256 一致。原生测试使用 QtTest 指针和键盘事件，文件对话框返回路径由脚本注入。高 DPI 使用 Qt 缩放因子，未验证跨显示器切换、数位板、驱动及写字机实物。
- 最终原生验收基于正式双 EXE 的私有复制件，仅替换自检数据入口。双 EXE 的 FileVersion 和 ProductVersion 均为 **0.1.50**，PE 为 AMD64；正式包 ZIP CRC 与新目录解压后的逐文件 SHA-256 均通过。使用说明、README 和 LaTeX 手册源码同步，历史手册 PDF 未重编译。
- 正式 ZIP 新解压后的原版 `InkStructTool.exe` 自检通过。真实作者小样串行和双进程均生成 4 字、13 候选，保留「喳」的来源提示及 96 处冻结选样，重开前后的严格 SVG 一致。331 项源码输入与构建记录匹配。工具离屏 Qt 字体目录和尺寸提示留在 stderr，原生验收 stderr 为空。

## 交付与复现

- 最终 ZIP 为 `artifacts/windows_release_0.1.50_verified/InkStruct-0.1.50-Windows-x64.zip`，127,112,088 字节、1,675 个成员。SHA-256 为 `0bc66bef2b8a89f4533cd7dc0186dd395fae37e5a73bf56a82acf3ce08fef5e3`。完整解压后运行 `InkStruct/InkStruct.exe`。
- 构建目录为 `artifacts/windows_build_0.1.50_verified_20261107`，两个 EXE 在 `dist/InkStruct`。构建日志和输入哈希位于构建目录。调整滚动条之前的试构建保留为内部记录，交付使用本节所列中性灰版本。
- 日志、JUnit 和自检记录位于 `artifacts/release_0.1.50_20261107`。原生截图及结果为其下 `native/final-neutral/native-150` 和 `native/final-neutral/native-200`。

从主工作区运行 PowerShell。复测用新输出目录。

```powershell
.venv/Scripts/python.exe -B -X utf8 -m inkstruct.application
.venv/Scripts/python.exe -B -X utf8 packaging/build_inkstruct_app.py --output artifacts/windows_build_0.1.50-NEW

$e = (Resolve-Path 'artifacts/release_0.1.50_20261107').Path
$repo = (Get-Location).Path
& "$e/native/replay.ps1" -Dist 'artifacts/windows_build_0.1.50_verified_20261107/dist/InkStruct' `
    -OldDocument 'artifacts/release_0.1.48_20261106/native-final/run-01/upgraded.inkdoc' `
    -Output "$e/native/replay-NEW"

$env:PYTHONPATH = "$e/regression-support;$repo;$repo/src;$repo/packaging"
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:QT_QPA_PLATFORM = 'offscreen'
$env:INKSTRUCT_LAYOUT_PREVIEW_HOME = "$e/regression-replay-NEW"
$files = Get-Content "$e/regression-files.txt" | Where-Object { $_ -notmatch 'test_package_recovery_qt.py$' }
.venv/Scripts/python.exe -B -X utf8 -m pytest -p no:cacheprovider -o addopts='' -q $files
$env:INKSTRUCT_TEST_RECOVERY_RELATIVE = '1'
.venv/Scripts/python.exe -B -X utf8 -m pytest -p no:cacheprovider -o addopts='' -q tests/test_package_recovery_qt.py
Remove-Item Env:INKSTRUCT_TEST_RECOVERY_RELATIVE
```

工具自检命令为 `InkStructTool.exe --inkstruct-check --candidate-check --generation-profile <作者档案绝对路径> --writer user_001 --output <新目录绝对路径>`。本轮读取 `artifacts/candidate_count_full_20261104/input_audit/profiles_all_capture/user_001/b46b32ddfc6ef1b8.json`。

保留用户任务、样本、字体、模板、文档、冻结选样、历史发布包及未提交工作。没有执行 reset、clean、提交或推送。
