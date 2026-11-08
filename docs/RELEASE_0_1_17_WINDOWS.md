# InkStruct 0.1.17 Windows：字体包导入性能

日期：2026-10-18（Asia/Shanghai）。项目：`C:\Users\lee\Documents\InkStructApp\InkStruct-Windows-Dev`。Git 基点 `af45b45f04f899fcaced43aa980b0508673ee6c0`，沿用含既有未提交修改的完整工作树，没有 reset、clean、自动提交或推送。应用版本唯一来源 `src/inkstruct/fonts/__init__.py:APP_VERSION` 为 0.1.17，下次正式交付至少 0.1.18。Python 库仍为 0.2.0，字体及文档协议不变。

## 瓶颈与修改

使用 user_001 的 `user_001-v61-full-symbols-20261018.inkfont` 复现实际 Qt 字体库导入：173,885,565 字节，9771 个字符、10730 份候选。旧流程先完整验证原文件，再复制并完整验证临时文件，最后主线程三次解析新字体的索引及摘要。每次验证都构造每个排版字形，将完整轨迹重新编码，再解码以统计点数和来源。

旧版端到端耗时 **139.68 秒**，进程 CPU 时间 **139.47 秒**。本机 18 个逻辑核心，约等于单核 99.8%、整机 5.55%；低总 CPU 主要是 Python 单线程逐点校验，并非磁盘等待。两次完整候选验证分别为 66.56、68.15 秒，两个构造阶段约各 2 秒。三次主线程索引解析合计约 0.70 秒。这里的进程 CPU 比例由进程 CPU 时间/墙钟时间计算，不是任务管理器采样值。

本次修改：

- 先复制到目标字体库的独立临时区，以临时副本为准完成一次验证，再用不覆盖已有文件的链接加入字体库；避免重复验证原文件。复制损坏、验证失败或发布失败时不留下半成品。
- 字体验证与排版解析共用同一候选检查函数。验证时直接统计已检查的轨迹，不构造 `ResolvedGlyph`、几何元组和冻结 JSON，也不再次解码它们。
- 验证仍覆盖全部成员，包括未被候选引用的核心成员和开发记录；坐标、笔序、动态字段、来源分区、数学轴、度量、类别与全部内容哈希继续检查。整数/浮点身份与字体协议不变，没有隐藏来源警告、替换笔迹或跳过完整校验。
- 显示复制、读取索引、当前候选数、其余成员核对、加入字体库等进度；更新限频，避免每字信号拖慢界面。
- 后台同时返回简短的字体标题和说明。主线程填充列表时阻断中间选择信号，复用这些摘要；只缓存文字与文件指纹，不把全库点列放入长期缓存，也不把摘要缓存当作验证凭据。“验证字体”仍重新读取、验证文件。
- 已有完全相同的文件可重复导入；相同包 ID 但字节不同的文件明确报错并保留原文件，不再直接信任目标目录已有的同名文件。

该版本仍使用单个后台验证任务，不通过提高 CPU 占用掩盖冗余计算；完整大字体的首次校验仍需时间。

## 验证与边界

环境：Windows x64，项目 `.venv` Python 3.13.16、PySide6/Qt 6.9.2、PyInstaller 6.22.3、Matplotlib 3.11.2。没有修改全局 Python 或安装训练/CUDA 依赖。

实际耗时、CPU 时间、阶段记录、20 ms Qt 定时心跳间隔和文件哈希分别保存在 `artifacts/font_import_0.1.17_20261018/baseline/measurement.json` 与 `measured-final/measurement.json`，对照摘要见 `performance-comparison.json`。心跳间隔是测试事件循环响应指标，不等同硬件输入延迟或屏幕刷新率。完整字体导入副本逐字节 SHA-256 一致：`b114b9db538610176eaf4ca7ca6f5f177fd0319817599433dec274c50061c9c3`。

最终版在其他性能测量结束后单独复测：**47.75 秒**，相对旧版耗时减少 **65.82%**、约 **2.93 倍**。进程 CPU 时间从 139.47 降到 47.95 秒；20 ms Qt 心跳最大间隔由 750.48 ms 降为 36.29 ms。验证统计完全一致：9771 字、10730 候选、8,375,082 点、3350 份来源提示候选，核心与内容哈希相同。早期候选试跑记录也保留，但不作为最终对照数字。

专项测试覆盖完整验证统计、导入中不创建排版对象、九种重新签名但语义损坏的候选、未引用成员损坏、复制损坏、包 ID 冲突、发布失败、后台摘要交接和显式重新验证；不会用仅修改外层哈希失败来代替语义检查。

专项 **34 passed**；最终相关回归 **378 passed，0 skipped**，134.28 秒；Ruff 通过。Windows 构建源码哈希与实际发布源码一致。706 个既有用户文件哈希未变；旧长文档 11 页、4580 个文本实例与 301 条诊断保留，设置无修改应用、保存重开后的全部页面 SVG 与旧基线一致。

原生最终 EXE 在新工作区使用真实文件选择器导入同一完整字体，确认候选计数持续更新、导入期间可以切换排版页，完成后自动选中 9771 字/10730 候选的新字体。导入结果与原文件字节一致，来源提示 3350 份仍可见。证据为 `native-import-progress.png`、`native-responsive-during-import.png`、`native-import-complete.png`；只关闭独立验收窗口，没有操作用户正在运行的 0.1.16。

包内自检使用本次完整 user_001 字体通过实际字体库导入，字节一致且逐字进度可见；真实 scx 11 字的 v6.1 exp、v4 adaptive 导入、建档、生成、制作字体、排版、保存重开和 SVG 流程均通过。公式轴、冻结文档、全局默认、独立元素属性、固定浅色与连续预览检查保留。两个 EXE 架构为 x64，文件版本与产品版本均为 0.1.17。

最终回归、包内流程、原生导入与旧文档核对见验收目录的 `final-verification.json` 以及发布目录的 `verification.json`。字体源文件、现有任务、样本、作者档案、字体、评价和文档均保留。实体数位板、驱动、写字机及纸面效果未在本轮验证。LaTeX 手册源码已同步；环境没有 XeLaTeX/latexmk，新版 PDF 未重编译，历史 PDF 保留。

## 应用与复测

可运行应用：`artifacts/windows_build_0.1.17_20261018/dist/InkStruct/InkStruct.exe`，诊断入口 `InkStructTool.exe`。保留整个目录及 `_internal`。

发布包：`artifacts/windows_release_0.1.17/InkStruct-0.1.17-Windows-x64.zip`，同目录保留 `SHA256SUMS.txt`、ZIP CRC 与 EXE 版本校验结果 `verification.json`，历史包不覆盖。

ZIP SHA-256：`74135d86f5ffa37f50ab7a03cd74c92cb9b0437d1a004785ef522ca991bfe031`。

本次原生界面使用独立 `workspaces/windows-font-import-0.1.17`，不使用原工作区验收；原用户工作区仍为 `workspaces/windows-0.1.8`。日志、执行命令和用户文件保留清单位于 `artifacts/font_import_0.1.17_20261018/`，包内真实 scx 11 字流程产物位于 `artifacts/windows_bundle_check_0.1.17_20261018/`。

项目根目录 PowerShell：

```powershell
# 使用新版及原工作区
& 'artifacts/windows_build_0.1.17_20261018/dist/InkStruct/InkStruct.exe' --workspace workspaces/windows-0.1.8 --font artifacts/user_001_full_font_20261018_math_axis/user_001-v61-full-symbols-20261018.inkfont

# 性能复测使用新的输出目录，避免其他耗 CPU 任务同时运行
.venv/Scripts/python.exe scripts/benchmark_font_import.py --font artifacts/user_001_full_font_20261018_math_axis/user_001-v61-full-symbols-20261018.inkfont --output artifacts/font_import_repeat_new

# 专项检查使用新的 basetemp
.venv/Scripts/python.exe -m pytest tests/test_font_import.py tests/test_font_import_qt.py tests/test_font_packages.py tests/test_preview_performance.py tests/test_font_math_axis.py -ra --basetemp artifacts/qa17-repeat

# 完整相关回归与日志
.venv/Scripts/python.exe -X utf8 artifacts/font_import_0.1.17_20261018/run_logged.py regression_repeat .venv/Scripts/python.exe artifacts/font_import_0.1.17_20261018/run_regression.py

# 后续构建使用新目录，正式交付先递增 APP_VERSION
.venv/Scripts/python.exe packaging/build_inkstruct_app.py --output artifacts/windows_rebuild_next_new
```

实际构建与包内检查命令见验收目录 `build.command.json`、`bundle.command.json`。仅清理本轮测试临时目录、私有临时缓存及 PyInstaller work/cache，保留源码、数据、日志、测量、验收产物和交付包。

可以继续开发，并可交付本次字体导入性能更新。保留完整验证意味着这份 837 万点的字体首次导入仍约需 48 秒，界面可操作且可查看当前进度。
