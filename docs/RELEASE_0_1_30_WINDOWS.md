# InkStruct 0.1.30 Windows：紧凑公式与录制根号、括号

2026-10-20。已完成实现、测试、原生 Windows 验收及构建；可以继续开发并交付本版本。

## 最终行为

新文档公式按实际笔迹宽度紧凑排列，消除字母、数字、运算符和标点的采集位置留白。保留原字形、字号、基线、数学轴和冻结校正参考框；汉字不套用拉丁字母宽度规则，显式空格命令仍按原稿保留。分式、根式和伸缩括号按实际笔迹的垂直范围布置，行间仍保留笔宽与几何保护；没有用缩小字号来使长公式通过尺寸检查。

| 默认参数 | 0.1.29 初始值 | 0.1.30 新默认 |
| --- | ---: | ---: |
| 二元运算符间距 | 0.18 em | 0.08 em |
| 关系符间距 | 0.28 em | 0.12 em |
| 函数与标点间距 | 0.12 em | 0.06 em |
| 分数线净距 | 0.12 em | 0.06 em |
| 根式内部净距 | 0.12 em | 0.06 em |
| 括号与内容净距 | 0.12 em | 0.06 em |

结构净距仍不小于 1.5 倍笔宽。上下标 0.7、分子分母 0.8 的缩放比例保持。紧凑公式中，两侧使用与手写正文一致的最小光学间隙；数学类别间距独立计算。公式标点没有半字或整字预留。

根号和伸缩括号默认使用录制字形：根号按 0.46 em 的钩部宽度分段适配，横线单独延长；括号按样本比例、内容高度和类型计算宽度，以设置值为基础上限并保留笔宽保护。花括号允许略宽，竖线限制横向抖动放大。分数线继续使用录制减号横向拉伸，重音线仍保留已有几何构件规则。缺样、退化和根号横线识别失败继续报告，不能静默替换字形后导出。

## 设置与协议

统一入口保持右上角齿轮 → 排版默认设置 → 公式。“字号与字形”新增公式字距，提供紧凑和旧版采集留白；根式与括号页保留独立构件来源选择，宽度参数提示明确新策略下的上限语义。恢复默认使用新推荐值，取消仍不改文档。

数学样式独立版本为 `inkstruct_math_style_v2`，保存 `spacing_policy` 为 `handwriting` 或 `capture`。旧数学样式 v1 仍按旧排版读取，保存时不注入新策略字段；显式改变策略后使用 v2。新文档初始使用紧凑样式；已有全局默认第一次升级只在内存更新新文档的间距和根号/括号来源，保留现有字号、轴线和比例；明确应用后写入一次性升级标记，之后用户主动选择旧版也会保留。原有明确分数线来源选择仍有效。

旧文档不自动套用全局新默认。需要改变旧稿时，明确勾选“同时将默认排版参数应用到当前文档”，并先核对其他全局默认。字体包、模板和 Python 库协议不随本次应用补丁号递增；原始字体及采集数据不改写。

## 环境和保留

- 项目：`C:/Users/lee/Documents/InkStructApp/InkStruct-Windows-Dev`。
- 基线 0.1.29；Git 基点 `af45b45f04f899fcaced43aa980b0508673ee6c0`，完整未提交工作树保留。改动前快照 `artifacts/compact_math_0.1.30_20261020/implementation-baseline.zip`。
- APP_VERSION 为唯一应用版本来源，已递增到 0.1.30；README、使用说明、Windows 入口、LaTeX 手册源码及发布文件名已同步。
- Windows 11 x64 26300；项目独立 `.venv` Python 3.13.16 AMD64、PySide6 6.9.2、PyInstaller 6.22.3、Matplotlib 3.11.2；依赖和源码摘要见 build-provenance.json。
- 2954 个既有可读文件逐一 SHA-256 核对不变；3 个原本无读取权限的历史字体只核对大小和修改时间，不改权限。保留任务、样本、作者、生成、字体、评价、模板、文档、旧产物及未提交工作。
- 原生验收使用新工作区 `workspaces/windows-compact-math-0.1.30`，原始全局默认及三个升级标记核对不变。未 reset、clean、提交或推送；历史交付包未覆盖。

## 实际结果

- 回归 **1205 passed，2 skipped，345.96 秒**；两项跳过为当前 Windows 用户无符号链接权限（真实图片链接和悬空项目链接），不计为通过。
- 新测试覆盖：采集位置偏移、字形/字号不变、长分式与多层根式、圆/方/花括号及矩阵、显式空格、缺样阻断、v1/v2 协议、普通和命名字段项目重开、校正参考框不变、默认迁移只读及持久化、设置取消/恢复/明确应用。
- 真实字体使用既有 user_001 全库及符号字体，9771 字符、10730 候选；未改原字体，未重跑全库生成。依据截图重建了三条等价小公式，没有把小样称为完整原文档复现。
- 固定小样的旧/新宽度分别为 48.86→35.47、142.67→105.14、160.25→115.29 mm；高度分别为 15.88→9.31、15.01→9.18、20.20→13.41 mm。字形和缩放比例不变，冻结选样一致；上述数值来自 feature-probe-verified，同内容综合自检会因新建文档的初次选样不同而略有差异。
- 原生 0.1.30：核对公式字距为紧凑，根号和括号来源为录制字形，相关默认净距为 6%；取消后默认原始记录未改。真实字体小样共 1 页、108 个文本实例，预览、SVG、另存及重开通过。三个数学校准警告保留；u 需要斜体但实际只有正体的既有类别提示明确显示，验收副本显式确认后才导出，确认状态按现有整批确认机制保存。候选身份、字形和源码均不变。
- 原生优化 SVG 与同一保存文档的预期 SVG 字节一致，plotter.json 的页面/笔迹清单一致。源码身份、样式、资源和评价核对保持。
- 原生操作初遇窗口焦点失败，用户将 InkStruct 置前后完成验收；没有关闭或修改遮挡窗口所属的用户程序。
- 包内综合自检通过，notices 为空；scx 11 字的 v6.1 exp / v4 adaptive 小流程通过。采集使用合成笔输入，不替代实体数位板验收。
- 旧 0.1.12 长文档 11 页/301 项诊断与历史 SVG 摘要一致；设置无修改应用不变。0.1.20 字符校正、0.1.21/22 模板、0.1.23 字距及 0.1.29 文档冻结 SVG 字节一致。
- 本轮 11 个修改 Python 文件 Ruff 通过；双 EXE 文件版本和产品版本均为 0.1.30 x64，当前源码与构建摘要一致；ZIP 使用新目录与新文件名。

保留了初次测试失败日志：策略变量初始化位置错误已修正；旧“恢复默认”测试按新推荐值更新；真实构件核对曾误将几何重音线当作采样结构，现仅核对根号/分数线/括号。原生验收校验脚本也按选样记录字典格式及已有整批确认语义修正。最终回归、真实字体、原生与发布检查均使用修正后的检查。

未验证：实体数位板、驱动、写字机纸面紧凑度及中文输入法组合输入重测。LaTeX 手册仅同步源码，本机无 XeLaTeX/latexmk，未重新生成手册 PDF。

## 命令与位置

在项目根目录执行。构建和包内自检重跑时须指定新的输出目录：

```powershell
.venv/Scripts/python.exe -m inkstruct.application --workspace workspaces/windows
.venv/Scripts/python.exe artifacts/compact_math_0.1.30_20261020/run_logged.py regression-repeat -- .venv/Scripts/python.exe artifacts/compact_math_0.1.30_20261020/run_regression.py
.venv/Scripts/python.exe packaging/build_inkstruct_app.py --output artifacts/windows_build_0.1.30_20261020_release
artifacts/windows_build_0.1.30_20261020_release/dist/InkStruct/InkStructTool.exe --inkstruct-check --samples artifacts/source_samples/scx_351bf154/samples/scx --writer scx --font artifacts/user_001_full_font_20261018_math_axis/user_001-v61-full-symbols-20261018.inkfont --output artifacts/windows_bundle_check_0.1.30_20261020_release
artifacts/windows_build_0.1.30_20261020_release/dist/InkStruct/InkStruct.exe --workspace workspaces/windows
```

- 可运行应用和工具：`artifacts/windows_build_0.1.30_20261020_release/dist/InkStruct/`，保留整个文件夹与 `_internal`。
- 发布包：`artifacts/windows_release_0.1.30/InkStruct-0.1.30-Windows-x64.zip`；同目录保存说明、verification.json、SHA256SUMS.txt。
- 构建日志、依赖和源码证据：`artifacts/windows_build_0.1.30_20261020_release/build.log`、`build-provenance.json`。
- 综合自检：`artifacts/windows_bundle_check_0.1.30_20261020_release/verification.json`、`compact-math.inkdoc`、`compact-math-svg/`。
- 本轮日志和证据：`artifacts/compact_math_0.1.30_20261020/`，含前后对照、原生截图、native-saved.inkdoc、native-optimized-svg/、测试日志、最终数据校验及交付 seal。

验收后正常关闭本轮应用，仅清理本轮 pytest、预览临时文件、构建 work/cache 与依赖缓存，结果另存 cleanup.json。保留源码、数据、测试日志、截图和全部验收及交付产物。
