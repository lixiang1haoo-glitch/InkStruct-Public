# InkStruct 0.1.49 Windows 交付记录

2026-11-06。主工作区为 `C:/Users/lee/Documents/InkStructApp/InkStruct-Windows-Dev`，Git HEAD 为 `af45b45f04f899fcaced43aa980b0508673ee6c0`。基于含未提交工作的 0.1.48 源码构建。应用版本取自 `APP_VERSION`，Python 库版本仍为 0.2.0。构建环境为 Windows 11 x64、Python 3.13.16、PySide6 6.9.2、PyInstaller 6.22.3。

## 模板工作流

- 模板库 SVG 随视口等比缩放，详情独立滚动，底部操作区固定。更换当前文档模板、选择新文档默认模板及试排共用等比预览控件，纸张仍按模板原尺寸排版。
- 库内「保存修改」创建并选中同一模板的新修订。旧修订继续可用。写入失败时保留草稿供重试。独立复制、导出 JSON 和设为新文档默认仍可单独操作。保存修订后，旧项目继续读各自内嵌快照。
- 模板库和工作台按稳定布局 ID 打开第一张起始页，没有起始页时打开第一张循环页。未编排布局仍可手动选择，工作台刷新保留仍有效的当前布局。
- 筛选隐藏当前项后选中可见项，零匹配显示空态并禁用关联操作。选择器读取或渲染失败时清空旧预览、显示错误并禁用确认。导入成功后列表、标题、预览和确认对象指向同一项。
- 清理试排、旧设计器与设置中的纸面校准文案。旧格式和偏移仍可读取，保留越界、内容溢出和必填字段检查。

## 实际验收

- 43 个相关测试文件，主选集 **436 项通过**，独立恢复测试 **1 项通过**。回归包含目录写入失败回滚、旧修订保留、旧协议读取、模板换版取消／撤销／保存重开，以及冻结选样。日志和 JUnit 位于 `artifacts/release_0.1.49_20261106`。
- Windows 原生 Qt 窗口在 **150% 和 200%** 各通过 15 个检查、记录 14 次 QtTest 指针点击。常规窗口请求 1360 × 900，矮窗口请求 1000 × 480，实际约束为 **1000 × 488** 逻辑像素，SVG 视口为 580 × 85。两档都在矮窗口点击「用于当前文档」「编辑模板」「设为新文档默认」「更多操作」。选择器及试排使用 760 × 420 逻辑像素。
- 使用截图对应的 `物理实验模板v3.json`，它含 0 起始、4 循环和未编排的「布局 1」。模板库与工作台直接显示 PDF 第 1 页及原底图。另验证 70 × 1800 mm 合法高窄无底图模板的纸张比例、选择器和试排，以及零匹配空态。
- 点击「保存修改」直接入库。注入目录锁冲突后检查草稿仍在，解锁后重试并选中修订 2。取消编辑未产生修订，库内修订保存后当前文档和新文档默认仍保持各自状态。重开 0.1.48 的实际 `.inkdoc`，内嵌模板及选样记录一致，原模板和项目文件的 SHA-256 均一致。
- 选择器读取失败使用损坏的私有模板副本，渲染失败使用注入的无效 SVG，均确认清空旧标题及预览并禁用确认。导入验证由 QtTest 点击按钮，向文件对话框注入真实路径，未手动操作 Windows 文件对话框。高 DPI 使用同一显示环境的 Qt 缩放因子，未测试跨显示器 DPI 切换。首轮原生脚本假定高度必须为 480，实际被 Qt 限制到 488，因此调整验收断言检查真实尺寸和按钮可达性，首轮记录保留。
- 原生验收在正式构建的私有副本中运行，只有自检脚本入口换成原生验收脚本。发布 ZIP 新解压后的原版工具也通过真实作者小样自检。串行和双进程各完成 4 字、13 候选，保留「喳」的来源提示，96 处选样及重开前后的严格 SVG 一致。工具离屏运行的字体目录和尺寸提示见 stderr。数位板、驱动及写字机实物未验收。
- 两个 EXE 均为 AMD64，FileVersion、ProductVersion 都为 **0.1.49**。构建后复核 **331 项**输入哈希一致。README、使用说明、LaTeX 手册源码已同步，历史手册 PDF 未重编译。

## 产物和复现

- Windows 包为 `artifacts/windows_release_0.1.49/InkStruct-0.1.49-Windows-x64.zip`，127,103,204 字节，1,675 项成员，已通过 ZIP CRC 和解压后逐文件 SHA-256 校验。ZIP SHA-256 为 `5132308be447b5797dd5bf37a6dbb4d260c7cedf0792dadb3200385c6522e601`。
- 双 EXE 位于 `artifacts/windows_build_0.1.49_20261106/dist/InkStruct`。构建日志、输入哈希在同一构建根。正式 ZIP 的解压校验副本位于发布目录的 `verified-extraction/InkStruct`。完整解压后运行其中的 `InkStruct.exe`。
- 回归、双 EXE 版本和工具自检位于 `artifacts/release_0.1.49_20261106`。原生截图与结构化结果在该目录的 `native/native-150-r2` 和 `native/native-200-r2`。

在项目根目录用 PowerShell 运行。输出目录需另取新名。

```powershell
.venv/Scripts/python.exe -B -X utf8 -m inkstruct.application
.venv/Scripts/python.exe -B -X utf8 packaging/build_inkstruct_app.py --output artifacts/windows_build_0.1.49-NEW

$e = (Resolve-Path 'artifacts/release_0.1.49_20261106').Path
$repo = (Get-Location).Path
& "$e/native/replay.ps1" -Dist 'artifacts/windows_build_0.1.49_20261106/dist/InkStruct' `
    -Template 'C:/Users/lee/Downloads/IS模板/物理实验模板v3.json' `
    -OldDocument 'artifacts/release_0.1.48_20261106/native-final/run-01/upgraded.inkdoc' `
    -Output "$e/native/replay-NEW"

$env:PYTHONPATH = "$e/regression-support;$repo;$repo/src;$repo/packaging"
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:INKSTRUCT_LAYOUT_PREVIEW_HOME = "$e/regression-replay-NEW"
$env:QT_QPA_PLATFORM = 'offscreen'
$files = Get-Content "$e/regression-files.txt" | Where-Object { $_ -notmatch 'test_package_recovery_qt.py$' }
.venv/Scripts/python.exe -B -X utf8 -m pytest -p no:cacheprovider -o addopts='' -q $files
$env:INKSTRUCT_TEST_RECOVERY_RELATIVE = '1'
.venv/Scripts/python.exe -B -X utf8 -m pytest -p no:cacheprovider -o addopts='' -q tests/test_package_recovery_qt.py
Remove-Item Env:INKSTRUCT_TEST_RECOVERY_RELATIVE
```

工具自检命令为 `InkStructTool.exe --inkstruct-check --candidate-check --generation-profile <作者档案绝对路径> --writer user_001 --output <新目录绝对路径>`。本轮使用的档案为 `artifacts/candidate_count_full_20261104/input_audit/profiles_all_capture/user_001/b46b32ddfc6ef1b8.json`。

保留用户数据、旧发布包及现有未提交工作。未提交或推送，没有改动独立排版开发目录。
