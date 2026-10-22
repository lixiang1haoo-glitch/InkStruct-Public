# InkStruct 0.1.29 Windows：紧凑标点与默认路径优化

2026-10-19。已修改、回归、原生验收及构建，可以继续开发并交付此版本。

## 行为与兼容

中文句读手写时不应保留半字或整字空位。本版正文标点按实际笔迹的光学宽度紧凑排列，中英文使用相同规则，消除采集格中的横向偏移；两侧只保留与手写字母相同的最小笔迹间隙（每侧 0.04 em 加物理笔宽半径）。不缩小标点，不改变其基线、笔迹和冻结选样。字符校正仍使用冻结的校正参考框，不重复归一化用户校正。Unicode 连接标点、公式、代码及表格数值对齐沿用原规则。

齿轮 → 排版默认设置 → 正文与段落 → 标点间距，提供“按笔迹紧凑排列（推荐）”和旧版采集留白。新文档默认紧凑；首次读取已有全局默认时仅在内存升级标点默认，原始记录在明确应用前保持不变。保存过主动选择后不再覆盖该选择。旧文档读取自己保存的间距，不自动重排；若需改变，明确勾选将默认参数用于本文，应用前核对其他默认设置。取消不改文档或用户原始默认记录。

排版样式使用独立的 `inkstruct_flow_style_v4` 保存 `punctuation_spacing`，可选 `capture` / `handwriting`，同时保留 v3 的 `latin_spacing`。旧 v1/v2/v3 默认 `capture`，写回旧样式不注入新字段；显式切换后才使用 v4。普通项目和命名字段项目均支持保存重开。模板、字体和 Python 库协议不随应用补丁号递增。

新应用/新文档的“优化路径（自动允许反转）”默认勾选，菜单与控件同步。保存或恢复项目时记录并读取原值，旧项目明确保存的 false 不会被默认值覆盖。优化仅调整已有执行域内的笔迹顺序及允许的方向，不移动字形、不改变排版坐标或笔迹集合。现有冻结后再选择输出位置的行为保留；没有降低任何缺字、公式、图片或越框校验。

## 环境与保留

- 路径：`C:/Users/lee/Documents/InkStructApp/InkStruct-Windows-Dev`。
- 基线 0.1.28；Git 基点 `af45b45f04f899fcaced43aa980b0508673ee6c0`，完整未提交工作树保留；本轮改动前源码快照 `artifacts/punctuation_0.1.29_20261019/implementation-baseline.zip`。
- `APP_VERSION` 为应用唯一版本来源，递增到 0.1.29；README、使用说明、Windows 入口、LaTeX 手册源码和发布文件名同步。
- Windows 11 x64 26300；独立 `.venv` Python 3.13.16 AMD64，PySide6 6.9.2，PyInstaller 6.22.3，Matplotlib 3.11.2。依赖、源码摘要与构建状态见 build-provenance.json。
- 2856 个既有可读数据及历史产物逐一 SHA-256 校验不变；3 个历史字体原本无读取权限，只核对原大小和修改时间，不改变权限。任务、样本、作者、生成、字体、评价、模板、文档及历史交付均保留。
- 原生验收使用独立 `workspaces/windows-punctuation-0.1.29`；原始全局默认记录及两项迁移标记核对不变。未 reset、clean、提交或推送。

## 验证结果

- Windows 回归 **1185 passed，2 skipped，319.44 秒**。两项因当前用户无 Windows 符号链接权限跳过（真实图片链接、悬空项目链接），没有计作通过。
- 新测试覆盖中英文标点、左右采集偏移、无半/全字预留、公式/代码/空格/汉字/数字未改变、测量缓存隔离、v4 普通及命名字段项目保存重开、源码及原始字形不变、旧版字段省略、默认迁移只读及显式选择持久化；Qt 覆盖取消、明确应用、路径优化新默认及旧 false 的重开。
- 包内综合自检 notices 为空；scx 11 字的 v6.1 exp 和 v4 adaptive 真实样本小流程通过，未重跑全库。采集输入为合成笔迹，不能替代数位板实物验收。
- 真实现有字体 `artifacts/user_001_full_font_20261018_math_axis/user_001-v61-full-symbols-20261018.inkfont` 保留原文件，完整校验通过。含 9771 字符、10730 候选，现有来源警告保留。
- 真实标点小样 `123，456。123（456）ABC,DEF.(ABC)`：整行宽 114.781732 → 86.461836 mm；冻结样本一致，保存重开 SVG 精确一致。优化前后每条完整笔迹（允许反向）完全保留；空行程 181.034724 → 117.537064 mm，仅说明此小样结果。
- 原生 0.1.29：新建空文档菜单中路径优化已勾选；齿轮中标点默认为紧凑，取消后原默认未写入；真实字体小样预览、另存、重开与 SVG 导出通过。原生 SVG 与同一冻结文档的优化导出字节精确一致；源码身份、资源、样式、评价及选样不变。截图位于本轮 native-*.png。
- 旧 0.1.12 长文档 11 页、301 项诊断与历史 SVG 摘要一致；全分类设置无修改应用不改变文档。0.1.21/22 模板、0.1.23 英文间距及 0.1.20 三范围字符校正输出与历史 SVG 字节一致。
- 本轮 16 个修改 Python 文件 Ruff 通过；构建源码摘要与当前源码一致；InkStruct.exe / InkStructTool.exe 均为 x64，文件及产品版本均为 0.1.29。发布目录与 ZIP 全新创建。

未验证：数位板、驱动和写字机实物书写间距；本轮未重测中文输入法组合输入。LaTeX 手册只同步源码，本机缺少 XeLaTeX/latexmk，未重新生成手册 PDF。没有把这些项目计为通过。

## 准确命令与产物

在项目根目录运行。构建和自检重跑时必须更换新的输出目录：

```powershell
.venv/Scripts/python.exe -m inkstruct.application --workspace workspaces/windows
.venv/Scripts/python.exe artifacts/punctuation_0.1.29_20261019/run_logged.py regression-repeat -- .venv/Scripts/python.exe artifacts/punctuation_0.1.29_20261019/run_regression.py
.venv/Scripts/python.exe packaging/build_inkstruct_app.py --output artifacts/windows_build_0.1.29_20261019_release
artifacts/windows_build_0.1.29_20261019_release/dist/InkStruct/InkStructTool.exe --inkstruct-check --samples artifacts/source_samples/scx_351bf154/samples/scx --writer scx --font artifacts/user_001_full_font_20261018_math_axis/user_001-v61-full-symbols-20261018.inkfont --output artifacts/windows_bundle_check_0.1.29_20261019_release
artifacts/windows_build_0.1.29_20261019_release/dist/InkStruct/InkStruct.exe --workspace workspaces/windows
```

- 可运行应用与工具：`artifacts/windows_build_0.1.29_20261019_release/dist/InkStruct/`，保留整个目录及 `_internal`。
- 发布包：`artifacts/windows_release_0.1.29/InkStruct-0.1.29-Windows-x64.zip`；同目录含使用说明、verification.json 和 SHA256SUMS.txt。
- 构建日志与源码/依赖证据：`artifacts/windows_build_0.1.29_20261019_release/build.log`、`build-provenance.json`。
- 综合验收及示例文档：`artifacts/windows_bundle_check_0.1.29_20261019_release/verification.json`、`punctuation-spacing.inkdoc`、`punctuation-optimized-svg/`。
- 本轮记录：`artifacts/punctuation_0.1.29_20261019/`，含回归/命令日志、兼容性、原生截图、native-saved.inkdoc、native-optimized-svg、最终数据校验与交付 seal。

验收后关闭本轮测试应用，仅清理本轮 pytest、预览临时文件、依赖缓存及 PyInstaller work/cache；保留源码、数据、日志、截图、验收与交付产物。清理结果另存 cleanup.json。
