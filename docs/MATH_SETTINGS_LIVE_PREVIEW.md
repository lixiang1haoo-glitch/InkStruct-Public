# 公式设置双预览验证 · 2026-11-07

本轮从 Windows 主工作区的 0.1.51 源码运行，保留原有文档、字体、冻结选样和设置作用域，未提高应用版本或制作发布包。Git 基线 `af45b45f04f899fcaced43aa980b0508673ee6c0`，在原有未提交工作树上修改。

统一设置的「排版默认设置 → 公式」与排版菜单中的「公式字体与样式」使用同一个参数面板。中间列表可点击或用方向键切换；切换时保留草稿。左为印刷参考，右为手写，同一公式、模式、参数及固定倍率。选中参数时显示实际尺寸和设定值；百分比相对当前层公式字号。手写缺字仍保留红框，设定试调不改变文档。公式字号与等效字号单位为 mm 和 pt。积分和求和用不同示例试调共用参数。

印刷参考使用未修改的 [Latin Modern Math 1.959](https://ctan.org/pkg/lm-math) 上游分发包，内含 [GUST Font License](https://ctan.org/license/gfl)、版权声明和原始文档，见 [资源说明](../src/inkstruct/editor/resources/README.md)。应用从本地包读取 OpenType 字形轮廓、度量和 `MATH` 数学轴基准，无需安装系统字体。结构仍由 InkStruct 测量并布置，未实现 TeX 引擎的全部 MATH 规则或伸缩字形拼装；录制减号、根号和括号的来源选项只作用于手写栏。参考字形不进入文档或正式导出。

Windows 11，Python 3.13.16 x64，PySide6 6.9.2。使用项目已有的 `user_001-symbols-current-rules.inkfont`（SHA-256 `7985baefd37fc69c64e00febb396b680b60be787cdc4058556ffcaf6da396eee`），在隔离的设置与文档目录运行。Windows Qt 后端、DPR 1.5 和 2.0 各通过 12 项，覆盖列表键盘切换、900×510 紧凑窗口、两栏实测值、正斜体、手写缺字、根式与运算符示例、矩阵、全局默认和当前文档作用域、取消及应用后保存重开。取消前后同一文档严格 SVG 哈希与冻结选样相同；应用后保存重开仍保持当时的严格 SVG 和选样。自动回归 546 项通过。

| 150% 原生试样 | 印刷参考 | 手写 |
| --- | --- | --- |
| 二元运算符间距从 8% 改为 30% | 0.48 → 1.80 mm | 0.48 → 1.80 mm |
| 上标最小上移设为 0% | 实际 1.86 mm | 实际 2.06 mm |
| 连分式分数线净间距设为 0% | 实际 0.45 mm | 实际 0.45–0.78 mm |

其他分类的示例和控件由 Qt 回归覆盖，没有逐参数做 Windows 人工视觉验收。原生运行使用 Qt 测试事件和控件截图；未用物理外设逐项操作，也没有跨物理显示器切换或冻结发布包验收。

在项目根目录用 PowerShell 复现。原生脚本的第三个参数是预期实际 DPR；若系统基础缩放不是 150%，相应调整 `QT_SCALE_FACTOR`。

```powershell
$repo = (Get-Location).Path
$e = (Resolve-Path artifacts/math_settings_preview_20261107).Path
$font = (Resolve-Path artifacts/font_capacity_simplified_20261104/input_audit/user_001-symbols-current-rules.inkfont).Path
$env:PYTHONPATH = "$repo/src"
$env:QT_QPA_PLATFORM = 'windows'
$env:QT_SCALE_FACTOR = '1'
.venv/Scripts/python.exe -B -X utf8 "$e/native_check.py" "$e/repro-150" $font 1.5
$env:QT_SCALE_FACTOR = '1.333333333'
.venv/Scripts/python.exe -B -X utf8 "$e/native_check.py" "$e/repro-200" $font 2.0
Remove-Item Env:QT_QPA_PLATFORM, Env:QT_SCALE_FACTOR

$env:PYTHONPATH = "$repo/artifacts/release_0.1.51_20261107/regression-support;$repo;$repo/src;$repo/packaging"
$env:INKSTRUCT_LAYOUT_PREVIEW_HOME = "$e/repro-regression-private"
$env:PYTHONUTF8 = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'
$files = rg --files tests | Where-Object { $_ -match 'test_math|test_compact_math|test_recorded_math|test_font_math_axis|test_machine_svg|test_svg_export|test_plotter|test_unified_settings_qt|test_settings_usability_qt' }
.venv/Scripts/python.exe -B -X utf8 -m pytest -p no:cacheprovider -o addopts='' -q $files --junitxml="$e/repro-regression.xml"
```

原始记录在 `artifacts/math_settings_preview_20261107/`：`native-acceptance-150` 和 `native-acceptance-200` 含截图、测量值、哈希及验收文档；`linked-regression.log` 和 `linked-regression.xml` 记录最终源码的回归结果。
