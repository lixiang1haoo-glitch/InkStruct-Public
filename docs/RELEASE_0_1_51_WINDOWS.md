# InkStruct 0.1.51 Windows 交付记录

2026-11-07。主工作区为 `C:/Users/lee/Documents/InkStructApp/InkStruct-Windows-Dev`，Git HEAD 为 `af45b45f04f899fcaced43aa980b0508673ee6c0`。从含未提交工作的 0.1.50 工作树接续。应用版本来自 `APP_VERSION`，Python 库仍为 0.2.0。构建环境为 Windows 11 x64、Python 3.13.16、PySide6 6.9.2 和 PyInstaller 6.22.3。

## 模板工作台与排版预览

- 起始页组和循环页组中的引用各按组及组内位置选中、移动和移除。多个引用可共用一个页面版式，画布仍按版式 ID 显示。初次进入优先显示第一张起始页，没有起始页时显示第一张循环页。空组隐藏，备用版式默认折叠，可以加入页组或删除。
- 字段声明、为所选框新建并绑定字段、绘制新字段框分别操作。绘制时新增声明和新框一起提交，可用一次撤销恢复。取消新建保留原绑定。
- PDF 导入可追加或替换目标页组。确认前显示导入顺序、移出条目和整份模板的纸张尺寸变化。编辑已有模板时默认保留纸张尺寸。采用新尺寸时，原框沿用毫米坐标，原有几何检查继续执行。替换只会自动清理当前新建工作台能确认由程序创建且从未修改的初始空白版式，并要求替换后已无引用。历史白页和用户创建的备用白页均按普通版式保留。
- 换版确认列出起始及循环页组顺序、底图与整份模板横纵偏移。既有纸张、区域、字段、页数和溢出对比继续使用。
- 「编辑库内模板」的「保存修改」新增同一模板的修订。「复制为新模板」建立独立身份并入库。「导出 JSON」只写文件。原「重新定位最近文件」改称「从其他位置导入模板」，沿用普通导入行为。
- 预览中 Ctrl＋滚轮使用 75%、100%、150%、200% 四档，与倍率控件同步。缩放尽量保持鼠标下的页内位置，滚动到边界时受视口可滚动范围限制。

## 原生验收范围

- 正式构建在 150% 和 200% 缩放下各通过 11 项原生检查，最终 stderr 均为空。窗口级滚轮注入按 DPR 换算为设备坐标，再由 Qt 将事件路由到指针所在的控件。早期验收脚本误用逻辑坐标的失败日志另存。
- 0.1.50 基线重现起始组点击跳到循环组、移除错误引用，以及绘制新框导致新旧字段框同时改绑。基线输出位于 `artifacts/release_0.1.51_20261107/baseline-reproduction.txt`。
- 隔离工作区使用实际 `物理实验模板v3.json` 检查四张循环页和一个备用白页，进入工作台显示 PDF 第 1 页及底图。用 QtTest 点击跨组共用和组内重复的引用，验证两次移动及两次移除均修改预期条目。拖绘字段框并确认、取消和撤销，另验证两种字段声明操作。
- 使用独立四页 PDF 样例验证按 3、1 的顺序追加及替换。追加保留原尺寸及原顺序。替换采用 120 × 120 mm，清理符合条件的程序初始空白页，保留手工备用白页。两个操作均可撤销。等页数换版确认显示顺序、底图和双轴偏移，取消保留原版。
- 库内三种保存操作分别核对文件、库记录和修订关系。重开真实 0.1.48 `.inkdoc`，内嵌模板和冻结选样一致。验收输入文件的 SHA-256 在测试前后相同。
- 单页与六页测试分别验证 Ctrl＋滚轮缩放、普通滚动、倍率上下限和源码／属性区隔离。倍率 100% → 150% 的被测点，鼠标下页内归一化坐标最大误差约 0.00053。没有改变排版快照或冻结选样。
- 原生自动化在 Windows Qt 可见窗口中运行。文件对话框路径由脚本注入，鼠标、滚轮和按键由 Qt 测试事件产生。高 DPI 使用同一显示环境的 Qt 缩放。跨显示器切换和物理触控板手势未验收。

## 回归与产物

- 45 个相关测试文件共 **450 项**通过。最终构建源码的主选集首次得到 448 项通过和 1 项旧文案断言失败。更新断言后，同文件 9 项复测通过，其中 8 项与原通过项重叠。独立恢复测试 1 项通过。原始日志和 JUnit 位于 `artifacts/release_0.1.51_20261107`。
- `InkStruct.exe` 和 `InkStructTool.exe` 均为 Windows AMD64，FileVersion 和 ProductVersion 均为 **0.1.51**。正式包解压后的原版工具通过真实作者四字自检，串行和双进程均为 13 个候选，保留「喳」的来源提示。96 处冻结选样和重开后的严格 SVG 一致。331 项构建输入与源码匹配。
- 正式 ZIP 位于 `artifacts/windows_release_0.1.51_verified/InkStruct-0.1.51-Windows-x64.zip`，127,131,221 字节、1,675 个成员。CRC 与解压后的逐文件 SHA-256 通过。ZIP SHA-256 为 `f49588016c57327d9cfd5d02cb17a0262967b61b71248c83a1b4dd2b8ed9a341`。完整解压后运行 `InkStruct/InkStruct.exe`。
- 构建日志与双 EXE 在 `artifacts/windows_build_0.1.51_verified_20261107`。原生截图及记录在 `artifacts/release_0.1.51_20261107/native/final`，正式工具结果在 `extracted-tool-delivery/verification.json`。README、使用说明和 LaTeX 手册源码已同步，历史手册 PDF 未重编译。

## 复现

在主工作区的 PowerShell 执行。输出需使用新目录。

```powershell
.venv/Scripts/python.exe -B -X utf8 -m inkstruct.application
.venv/Scripts/python.exe -B -X utf8 packaging/build_inkstruct_app.py --output artifacts/windows_build_0.1.51-NEW

$e = (Resolve-Path 'artifacts/release_0.1.51_20261107').Path
$repo = (Get-Location).Path
& "$e/native/replay.ps1" -Dist 'artifacts/windows_build_0.1.51_verified_20261107/dist/InkStruct' `
    -Template 'C:/Users/lee/Downloads/IS模板/物理实验模板v3.json' `
    -Pdf 'artifacts/template_flow_0.1.21_20261019/native-reference-four-pages.pdf' `
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

保留用户模板、修订历史、内嵌快照及现有未提交工作。没有执行 reset、clean、提交或推送。
