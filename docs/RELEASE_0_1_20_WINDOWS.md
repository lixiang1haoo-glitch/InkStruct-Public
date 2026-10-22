# InkStruct 0.1.20 Windows 交付记录

日期：2026-10-19。项目：`C:\Users\lee\Documents\InkStructApp\InkStruct-Windows-Dev`。源码基底为 `af45b45f04f899fcaced43aa980b0508673ee6c0`，实际构建使用完整的未提交工作树；精确源码摘要保存在 `artifacts/windows_build_0.1.20_20261019/build-provenance.json`，已确认构建期间及验收后源码一致。没有 reset、clean、自动提交或推送。

应用版本唯一来源 `src/inkstruct/fonts/__init__.py::APP_VERSION` 已递增为 0.1.20。Python 库版本和字体格式版本独立。环境：Windows 11 x64（26300），项目内 `.venv`，Python 3.13.16 AMD64、PySide6/Qt 6.9.2、PyInstaller 6.22.3、Matplotlib 3.11.2。未更改全局 Python 或其他项目环境。

## 本轮行为

在排版预览选择字符后，右侧“字符校正”提供左右位移、上下位移、宽度和高度缩放，并显示当前字符、正斜体、样本编号、候选 ID 和本文使用数量。以所选 A2 为例：

| 应用范围 | 实际作用 |
| --- | --- |
| 仅此处 | 只改所选这一次 A2；同一次源码出现的重复表头等副本同步 |
| 本文同一样本 | 改本文采用 A2 的所有位置，A1、A3 保留原样 |
| 本文同一字符的全部样本 | 改本文采用 A1、A2、A3 等该字符同类样本的所有位置 |

后两项单独提供默认不勾选的“同时保存到字体包的新版本”。正体、斜体默认分开；第三种范围在有其他字形类别时提供“同时包含正体与斜体”，须明确勾选。界面提前显示受影响的位置和样本数量。原来的“本文所有字符”以及独立的字体保存范围选项已移除。

批量应用把范围内的已有单字校正统一替换为本次参数，避免旧的单字校正遮住批量结果；整次操作可以一次撤销、重做。恢复所选范围回到字体原字形，其他范围保持原样。文档校正随 `.inkdoc` 保存，实际作用于预览、SVG 和写字路径，保留原字距、候选选择和换行。

勾选字体保存后，先完整校验原包并另存、完整校验新包，成功后应用本文校正。原包、本文冻结字体及原始轨迹保留；当前文档继续使用原字体快照和文档校正，避免重复叠加。新字体可在字体库导入，供后续文档使用。另存不覆盖已有文件，取消选择或保存失败时不部分修改本文；处理期间锁定校正输入。如果期间正文或文档上下文已改变，新字体保留，但过期的文档校正不再自动应用，并显示原因。

表格和图片页的内容仍全部陈列；全局默认与右侧元素属性、浅色界面、禁用参数滚轮、连续页面预览均保留。

## 实际验收

相关 Windows 回归 **493 passed，1 skipped**，239.57 秒；专项 **35 passed，0 skipped**，85.96 秒。两组有重叠，不相加宣称独立测试总数。Ruff 检查通过。覆盖三个范围、不同候选、正斜体、旧单字覆盖、恢复、保存重开、SVG、取消、失败不发布、异步上下文变化，以及 100%、150%、200% DPI。

唯一测试跳过为 `tests/test_images.py:141`：当前 Windows 账户没有创建文件符号链接的权限，真实符号链接检查未验证。没有降低协议检查或更改 Windows 权限来规避此项。

原生构建在新工作区 `workspaces/windows-glyph-scope-0.1.20` 验收：中文粘贴、预览点选、三个范围、影响计数、独立的字体保存复选框和项目保存均完成。选中的正体 A 为第 3/5 份样本，本文共使用 3 处。先作单字校正，再应用“本文同一样本”下移 8%，保存为 `native-sample.inkdoc`；之后应用同字符全部样本下移 10%，保存为 `native-character.inkdoc`。独立重开并逐点核对，分别只有 3 处、6 处发生指定校正，其他字符和公式中的斜体保持原样，均可导出 SVG。文件、导出和截图在 `artifacts/glyph_scope_0.1.20_20261019/`。

包内 `InkStructTool.exe` 自检通过：真实 scx 11 字“人物理羝羚而铜伯攣盼⺼”分别完成 v6.1 exp 和 v4 adaptive 的导入、建档、生成、字体制作、排版、保存重开和 SVG 导出。参考替代、来源未知及缺口提示均保留。新三个范围、批量替换旧单字、字体另存与本文校正、撤销后原 SVG 精确恢复也通过。

实际 user_001 完整字体的四进程导入约 14.36 秒，该次与其他验收并行，不作为独立性能基准。完整字体另存校正后仍为 9771 字、10730 候选、8,375,082 点，3350 份来源提示保留。测试新包位于 `artifacts/windows_bundle_check_0.1.20_20261019/glyph-corrected.inkfont`，未替换用户字体。新包核心摘要 `2014cf841205d57d82bef4ee7260ebfe31add05fefac843adea32b3864cbc14e`，内容摘要 `84ab486d745791dbd6e4f447f13a63202a536125a1d02234b08d34d3f8e26f9f`。

706 个既有用户文件与本轮开始的哈希一致，任务、样本、进度、字体、作者档案、评价、设置和原恢复记录保留。原 user_001 完整字体 SHA-256 仍为 `b114b9db538610176eaf4ca7ca6f5f177fd0319817599433dec274c50061c9c3`。旧长文档仍为 11 页、4580 个文本实例、301 条诊断，所有页面 SVG 与原基线相同；全局设置无改动应用也与原输出相同。

实际 0.1.19 校正文档可重开、布局并导出；重新核对其冻结字体原点与保存的 5% 下移规则，受影响点满足指定变换，其他笔迹完全一致。该文档历史 `native-svg` 目录当前返回 PermissionError，无法完成新旧 SVG 字节比对，此项明确为未验证；保留历史文件和权限。首次比对失败日志 `finish.log` 保留，修正验收程序后结果在 `finish_verified.log`，没有把不可读目录当作空目录判定通过。

实体数位板、驱动、写字机和纸面效果仍未验证。README、使用说明和 LaTeX 手册源码已同步至 0.1.20；环境没有 XeLaTeX/latexmk，未生成新版手册 PDF，历史 PDF 保留。

## 产物与运行

可运行应用：`artifacts/windows_build_0.1.20_20261019/dist/InkStruct/`，包含已核对版本的 x64 `InkStruct.exe` 和 `InkStructTool.exe`。启动时须保留整个目录及 `_internal`。

交付 ZIP：`artifacts/windows_release_0.1.20/InkStruct-0.1.20-Windows-x64.zip`。准确字节大小、SHA-256、PE 版本、ZIP CRC 和逐文件摘要见同目录的 `verification.json`、`SHA256SUMS.txt`。本版本在正式交付前完成说明文档核对；历史交付包没有覆盖。

ZIP 大小 123,516,638 字节；SHA-256：`189a30197e68d5073e0cc4c2687dbcfe3a31b4e123026b9adde0939c2091b41a`。

源码、数据摘要、原生截图、验收脚本与 UTF-8 日志：`artifacts/glyph_scope_0.1.20_20261019/`。两种生成流程、完整字体校正和 SVG：`artifacts/windows_bundle_check_0.1.20_20261019/`。构建日志、源码摘要与 PyInstaller 告警保存在构建目录。完成后仅清理本轮可重建测试、构建和临时缓存，保留源码、用户数据、日志、应用与验收产物，清理结果记录在 `cleanup.json`。

在上述项目根目录 PowerShell 中执行：

```powershell
# 启动本次应用，载入既有工作区与完整字体
& 'artifacts/windows_build_0.1.20_20261019/dist/InkStruct/InkStruct.exe' --workspace workspaces/windows-0.1.8 --font artifacts/user_001_full_font_20261018_math_axis/user_001-v61-full-symbols-20261018.inkfont

# 源码启动；独立验收改用新的 workspace 目录
.venv/Scripts/python.exe -m inkstruct.application --workspace workspaces/windows-0.1.8

# 专项测试，重跑时使用新的 basetemp
.venv/Scripts/python.exe -m pytest tests/test_glyph_corrections.py tests/test_glyph_corrections_qt.py -ra --basetemp artifacts/qa20-repeat-new

# 本轮回归清单；重跑前将脚本中的 basetemp 改为新的测试目录
.venv/Scripts/python.exe artifacts/glyph_scope_0.1.20_20261019/run_regression.py

# 包内自检；output 使用不存在的新目录
& 'artifacts/windows_build_0.1.20_20261019/dist/InkStruct/InkStructTool.exe' --inkstruct-check --samples artifacts/source_samples/scx_351bf154/samples/scx --writer scx --font artifacts/user_001_full_font_20261018_math_axis/user_001-v61-full-symbols-20261018.inkfont --output artifacts/windows_bundle_check_repeat_new

# 下一次正式交付先递增 APP_VERSION；输出目录须为新目录
.venv/Scripts/python.exe packaging/build_inkstruct_app.py --output artifacts/windows_build_next_new
```

当前可以继续开发并交付本次 Windows 更新；上述权限相关检查、硬件与新版手册 PDF 的未验证项已保留记录。
