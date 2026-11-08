# InkStruct 0.1.52 Windows

公式设置的 11 个分类统一使用尺寸标线和双栏预览。宽窗口可在印刷标线旁直接输入。空间不足时，输入框按编号放到图下。手写栏只在所选标线旁显示实际毫米值。内置示例覆盖 26 项尺寸。手写构件来源和其他非尺寸选项放在图下。

统一设置与文档公式设置沿用各自的应用范围。回归验证了取消、应用后保存重开、严格 SVG 和冻结选样。Windows 原生 Qt 窗口使用真实 `user_001` 字体，在 150% 和 200% 缩放下各通过 26 项检查。源码回归通过 546 项。LaTeX 手册源码已同步，本轮未生成手册 PDF。

Windows x64 包位于 `artifacts/formula_settings_0.1.52/release/InkStruct-0.1.52-Windows-x64.zip`。解压整个 `InkStruct` 目录，运行 `InkStruct.exe`。从 ZIP 解压后，两个 EXE 的文件版本和产品版本均核对为 0.1.52，且各自通过冻结环境下的 11 类公式设置自检。ZIP 的 1,675 个成员通过 CRC 检查，SHA-256 为 `eb1fd9b4a77f2016cf28c8333aead71dc8b1d4ef961ac37fcd6585b083bebfdf`。

在主工作区运行下列 PowerShell 命令可构建或复验。构建与验收脚本的输出目录需为新目录，已有结果可先另存。

```powershell
$e = (Resolve-Path 'artifacts/formula_settings_0.1.52').Path
$font = (Resolve-Path 'artifacts/font_capacity_simplified_20261104/input_audit/user_001-symbols-current-rules.inkfont').Path
.venv/Scripts/python.exe -B -X utf8 packaging/build_inkstruct_app.py --output "$e/windows-verified"
& "$e/verify_delivery.ps1"

$env:QT_QPA_PLATFORM = 'windows'
$env:QT_SCALE_FACTOR = '1'
$env:PYTHONPATH = (Resolve-Path src).Path
.venv/Scripts/python.exe -B -X utf8 "$e/native_check.py" "$e/replay-150" $font 1.5
$env:QT_SCALE_FACTOR = '1.333333333'
.venv/Scripts/python.exe -B -X utf8 "$e/native_check.py" "$e/replay-200" $font 2.0
```

截图、原生窗口测试结果和回归日志位于 `artifacts/formula_settings_0.1.52`。原生检查在 Windows Qt 窗口中通过 Qt 测试事件完成。倍率通过同一显示环境的 Qt 缩放设置验证。
