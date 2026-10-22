# InkStruct 0.1.19 Windows：字符校正与设置展开

日期：2026-10-18。实际项目路径：`C:\Users\lee\Documents\InkStructApp\InkStruct-Windows-Dev`。Git 基础提交 `af45b45f04f899fcaced43aa980b0508673ee6c0`，在保留既有未提交快照的基础上修改；交付的完整源码摘要见构建目录 `build-provenance.json`，不能仅凭 Git HEAD 恢复当前应用。

环境：Windows 11 x64（10.0.26300）、项目 `.venv` Python 3.13.16 AMD64、PySide6/Qt 6.9.2、PyInstaller 6.22.3、Matplotlib 3.11.2。没有修改全局 Python、其他项目环境、生成方法或原始采集数据。应用唯一版本来源为 `src/inkstruct/fonts/__init__.py` 的 `APP_VERSION=0.1.19`；Python 库仍为 0.2.0，字体轨迹协议仍为 `inkfont_trajectory_v1`。

## 已交付行为

全局默认及文档右侧的表格、图片设置移除“更多设置”折叠开关，数字高度、行高、笔宽、四边留白、列对齐、列宽、重复表头与 SVG 容差等直接陈列。内容过长时纵向滚动，原参数与继承关系保留。

点击排版预览中有字形的字符，右侧“元素属性”自动进入“字符校正”。显示 Unicode、候选样本与正斜体类别，提供左右位移、上下位移、宽度缩放、高度缩放，以及灰色原字形／蓝色校正字形的对照。位移按当前字高百分比表示，向右、向下为正；缩放 100% 为原尺寸，以左侧基线为原点。未点击应用时只改变局部对照预览。

应用范围包括：

- 所选单个字符：按源码出现身份固定；重复表头、重复模板中同一次源码出现的副本同步。
- 本文相同字符：默认只改当前候选，可勾选该字符同类的其他样本；正体与斜体分开处理。
- 本文所有字符：对全文有字形的字符生效，包括正文、公式、表格、脚注和模板字段。
- 另存校正字体包：只改所选字符，可选同类全部候选。完整校验原包与新包，保留原包，选择不存在的新文件名；完成后在字体库导入新包，用于后续排版。当前文档保留冻结结果。从保存项目操作时，可能需要重新选择完全匹配的原始字体版本。

单字规则优先于同字，同字优先于全文。文档校正随 `.inkdoc` 保存，作用于页面、SVG 和写字路径；保留原字距、换行、候选选择、字体原字节和来源提示。支持取消未应用草稿、恢复所选范围、撤销与重做校正。“恢复所选范围”不会删除其他范围规则，因此其他规则可能继续生效。校正不能补足缺字；超出页面可用区域仍产生错误并阻止成品导出。

## 实现与最小修复

字符校正是有范围、有限数值、容量上限和精确候选身份的文档配置，统一在嵌套分页、脚注和模板字段完成后应用一次；不对预览贴图单独变换。校正后的墨迹范围参与点选，笔宽保持物理尺寸。无校正文档直接返回原结果，不额外遍历全部点。缓存与恢复使用既有 FlowStyle 序列化，显式应用全局默认仍保留文档校正。

字体另存按基线仿射变换逐点改变 x/y，保留压力、时间、笔状态、笔序、原始轨迹核心成员和来源分区。改动候选分配新 ID，发布和包分配新 ID，保留字体家族身份。原候选完整快照保存在核心 `correction_sources/`，`geometric_corrections` 记录审计。新增并严格验证 `optical_layout_frame` 原边界与度量，以保留原字距和原点；否则排版的负边距补偿可能抵消向左校正。字体包校正与同等文档校正的实际 SVG 一致，包括负位移。用户版转换保留上述核心审计。

字体处理在后台进行，期间锁定校正输入；退出前等待任务完成。新包先写隔离临时文件，完整校验通过后原子发布；错误、源版本不匹配和同名冲突均不覆盖原包，也不发布半成品。生成核心、字体选择策略、来源缺口判定和既有协议检查保留。

## 实际验证结果

相关 Windows 回归 **480 passed，0 skipped**，181.52 秒。最终专项 **28 passed，0 skipped**，33.01 秒，包括源码身份、重复表头、嵌套脚注与模板、严格排版框校验、负边距、字体另存失败不发布，以及 100%、150%、200% DPI 的属性操作。两组存在重叠，不相加宣称独立测试总数。Ruff 检查通过。首次专项曾因测试把向左校正放在页面最左边而触发真实越界错误，改为校正第二个字符；越界检查本身保留，并另有拒绝导出用例。

包内 EXE 自检通过：真实 scx 11 字“人物理羝羚而铜伯攣盼⺼”的导入、建档、v6.1 exp／v4 adaptive 生成、字体制作、排版、冻结重开和 SVG 流程完成。v6.1 的参考替代、v4 的来源未知提示均保留。全库字体仍通过四进程完整导入，实测约 14.42 秒；该次与其他验收并行，不作为新的独立性能基准。

实际 user_001 全库另存校正字体验收通过：9771 字、10730 候选、8,375,082 点、3350 份来源提示保留。原包与已导入副本字节相同，新包单独保存在 `artifacts/windows_bundle_check_0.1.19_20261018/glyph-corrected.inkfont`，属于测试产物，没有替换用户字体。包内单字校正、输入锁定、保存重开、SVG、撤销后完全恢复原输出均通过。

旧长文档 11 页、4580 个文本实例、301 条诊断及所有页面 SVG 与原基线一致；设置无修改应用、保存重开、评价和冻结选样保留。706 个既有用户文件与本轮开始的哈希一致，完整 user_001 字体、原工作区和原恢复文件保留。既有数据没有自动恢复、提交或推送。

原生 `InkStruct.exe` 在新的 `workspaces/windows-glyph-correction-0.1.19` 中完成中文粘贴、预览选中 A、下移 5%、确认 5 份同类候选选项、保存项目和表格／图片直接展开检查。只取消设置草稿，未保存演示全局默认。原生文档、截图位于本轮验收目录，`native-corrected.inkdoc` 可直接重开。Qt 的 UIA 焦点文本有时滞后，原生输入按截图中的实际光标位置操作，保存文件已独立核对。

实体数位板、驱动、写字机和纸面效果仍未验证；已有公式支持范围、缺字和来源提示保留。LaTeX 手册源码已同步至 0.1.19；环境没有 XeLaTeX/latexmk，未生成新版 PDF，历史 PDF 保留。

## 产物与准确命令

可运行应用目录：`artifacts/windows_build_0.1.19_20261018/dist/InkStruct/`。两个 x64 可执行文件均为 0.1.19：`InkStruct.exe` 和 `InkStructTool.exe`；须保留整个目录及 `_internal`。

发布 ZIP：`artifacts/windows_release_0.1.19/InkStruct-0.1.19-Windows-x64.zip`。同目录有使用说明、SHA256SUMS 与含 PE 版本、文件摘要和 ZIP CRC 的 `verification.json`。未覆盖任何历史交付。

ZIP 大小 123,507,077 字节；SHA-256：`3381a5bdc8d245ddb94e5e2c8de4d7252eee7c0c3b2c84b32e2c92f8426b8335`。

本轮日志、准确命令、数据哈希、截图和验收脚本：`artifacts/glyph_correction_0.1.19_20261018/`。包内真实两方法流程、校正字体与 SVG：`artifacts/windows_bundle_check_0.1.19_20261018/`。构建源码摘要和 PyInstaller 日志在构建目录。完成后仅清理本轮可重建测试、临时和构建缓存，保留所有日志、源数据、应用和交付产物。

在项目根目录 PowerShell 中运行：

```powershell
# 启动已交付应用，使用既有用户工作区与未修改的完整字体
& 'artifacts/windows_build_0.1.19_20261018/dist/InkStruct/InkStruct.exe' --workspace workspaces/windows-0.1.8 --font artifacts/user_001_full_font_20261018_math_axis/user_001-v61-full-symbols-20261018.inkfont

# 源码启动（独立验收时换成新的工作区目录）
.venv/Scripts/python.exe -m inkstruct.application --workspace workspaces/windows-0.1.8

# 当前功能专项：每次用新的 basetemp
.venv/Scripts/python.exe -m pytest tests/test_glyph_corrections.py tests/test_glyph_corrections_qt.py -ra --basetemp artifacts/qa19-repeat-new

# 本轮相关回归列表，runner 中 basetemp 已记录，重跑时改为新目录
.venv/Scripts/python.exe artifacts/glyph_correction_0.1.19_20261018/run_regression.py

# 包内自检：output 必须是不存在的新目录
& 'artifacts/windows_build_0.1.19_20261018/dist/InkStruct/InkStructTool.exe' --inkstruct-check --samples artifacts/source_samples/scx_351bf154/samples/scx --writer scx --font artifacts/user_001_full_font_20261018_math_axis/user_001-v61-full-symbols-20261018.inkfont --output artifacts/windows_bundle_check_repeat_new

# 下一次正式交付先递增 APP_VERSION，构建到新目录
.venv/Scripts/python.exe packaging/build_inkstruct_app.py --output artifacts/windows_build_next_new
```

当前可以继续开发并交付本次 Windows 更新。硬件书写与纸面效果仍需后续实物验收。
