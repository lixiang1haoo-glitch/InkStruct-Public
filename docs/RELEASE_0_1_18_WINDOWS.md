# InkStruct 0.1.18 Windows：并行字体导入与设置防误调

日期：2026-10-18（Asia/Shanghai）。项目：`C:\Users\lee\Documents\InkStructApp\InkStruct-Windows-Dev`。Git 基点 `af45b45f04f899fcaced43aa980b0508673ee6c0`，沿用完整未提交工作树。没有 reset、clean、自动提交或推送。唯一应用版本来源 `src/inkstruct/fonts/__init__.py:APP_VERSION` 为 0.1.18，下次正式交付至少 0.1.19；Python 库仍为 0.2.0，字体和文档协议不变。

## 修改与使用

大字体导入使用最多 **4 个独立进程**，按最多 128 候选一批验证。默认少于 512 候选或可用核心不足时串行，避免启动开销。每个工作进程独立打开临时字体并核对清单身份，共用原来的候选验证函数，检查轨迹、笔序、动态信息、来源、数学轴、度量、类别及哈希。主进程核对每批范围与总数，补查所有未引用核心成员和开发记录，全部成功后才加入字体库。没有通过减少点数、替换字形或跳过检查提速。

进程数受可用 CPU 限制，保留一个可用逻辑核心余量，最高四个；并行任务仅传候选区间和统计结果，不在进程间复制整库点列。任一候选失败、工作进程崩溃或启动失败都会取消尚未运行的批次，等待运行中的批次结束后清理临时副本，不发布半成品，也不通过静默降级掩盖错误。Windows 冻结启动器在创建 Qt 窗口之前分流 multiprocessing 子进程，避免重复打开应用窗口。导入仍显示进程数、当前候选计数和阶段。

参数输入框、参数滑块及收起状态的下拉框不再通过滚轮改变值，即使当前有输入焦点。鼠标经过这些控件时，滚轮转交最近的滚动页面；点击、文本输入和键盘上下键保留。滚动条、已展开下拉列表、页面预览的原有滚动/缩放行为不改变。规则统一作用于应用中新建的控件与设置弹窗，不修改用户参数。

“正文与段落”的段距、首行、标题段距、列表/引用缩进、H1—H6 标题字号和效果预览全部陈列，移除该页“更多设置”“标题字号”“效果预览”的折叠开关。超出窗口高度时纵向滚动。

公式设置多余箭头来自退出布局但尚未延迟销毁的旧滚动容器。模态窗口会延迟处理外层的销毁事件，因此现在移除时立即隐藏旧容器和滚动条，再等待销毁。保留有效的公式结构下拉、滚动条和参数调整控件。实际字形预览默认开启“显示辅助线”，用户仍可取消勾选；这只影响屏幕预览，不写入公式协议或 SVG。

## 性能与验证

环境：Windows x64，项目 `.venv` Python 3.13.16、PySide6/Qt 6.9.2、PyInstaller 6.22.3、Matplotlib 3.11.2。没有修改全局 Python、其他项目环境或安装训练依赖。

同一真实 user_001 字体，173,885,565 字节、9771 字、10730 候选、8,375,082 点：0.1.17 串行实测 **47.75 秒**，本次最终版单独复测 **12.62 秒**，约 **3.78 倍**、耗时减少 **73.58%**。确认四个不同进程参与。主进程 CPU 时间 0.47 秒，工作进程累计约 47.28 秒；共约 3.8 个逻辑核心持续工作。本机 18 个逻辑核心，整机占用不需要达到 100%。Qt 20 ms 心跳最大间隔约 30.52 ms，此指标不等同硬件输入延迟或屏幕刷新率。

源字体、导入副本字节与全部验证统计完全一致，包括 3350 份来源提示候选、核心和内容哈希。源字体 SHA-256：`b114b9db538610176eaf4ca7ca6f5f177fd0319817599433dec274c50061c9c3`。数据与结果在 `artifacts/parallel_import_0.1.18_20261018/performance-comparison.json`、`measured-final/measurement.json`；首轮试跑 14.45 秒也保留，不与最终结果混用。

专项覆盖：真实 spawn 进程统计与串行一致；九种重新签名但语义损坏候选在串行/并行均拒绝；未引用成员、复制损坏、同包 ID 冲突、发布失败、进程启动失败和工作进程异常；100%、150%、200% DPI 下滚轮经过已聚焦/未聚焦参数及内部文本框不改值、页面只滚动一次、键盘调节仍可用、正文无折叠、公式旧容器隐藏和辅助线默认开启。初次专项 55 项通过，补测实际崩溃与滚动行为 7 项通过。

最终修正后相关回归 **394 passed，0 skipped**，143.12 秒；首轮为 144.25 秒，两次日志均保留，Ruff 通过。706 个既有用户文件哈希未变，完整字体保留；旧长文档 11 页、4580 个文本实例及 301 条诊断不变。无修改应用设置、保存重开后，全部页面 SVG 与旧基线一致，冻结字形、候选、字符身份和评价保留。

最终原生 EXE 在独立工作区完成完整字体的四进程导入，进度计数正常，没有额外应用窗口。导入期间可打开设置；滚轮经过参数框滚动页面，正文设置与预览无折叠，公式顶部旧箭头不再显示，“显示辅助线”默认勾选且实际预览可见。原生验收仅取消草稿，不保存演示参数。证据位于验收目录 `native-*.png`。

最终包内自检全部通过，四个工作进程完成完整 user_001 字体导入，实测约 **14.39 秒**（与其他验收并行运行，单独性能复测为 12.62 秒）。两种真实 scx 11 字的导入、建档、生成、制作字体、排版、保存重开及 SVG 流程通过；来源缺口提示保留。包内设置防误调、正文展开、公式辅助线、Esc 取消与重新显示、固定浅色及连续预览检查通过。两个 EXE 均为 x64，文件版本和产品版本均为 0.1.18，源码哈希与构建冻结记录一致。

最终回归、包内并行导入、原生界面、旧长文档和数据哈希的最终结果保存在验收目录 `final-verification.json` 以及发布目录 `verification.json`。实体数位板、驱动、写字机和纸面效果未在本轮验证。既有缺字和来源提示保留。LaTeX 手册源码已同步；环境没有 XeLaTeX/latexmk，新版 PDF 未重编译，历史 PDF 保留。

## 应用、产物与命令

应用目录：`artifacts/windows_build_0.1.18_20261018_verified/dist/InkStruct/`，运行 `InkStruct.exe`，保留 `InkStructTool.exe` 与 `_internal` 整个目录。

发布包：`artifacts/windows_release_0.1.18/InkStruct-0.1.18-Windows-x64.zip`，同目录包含 `SHA256SUMS.txt`、文件清单、ZIP CRC 和两个 EXE 产品版本验证 `verification.json`。历史交付不覆盖。

ZIP SHA-256：`d557a9185a4ea6029d5a6e6ee1e9712f77de62d7d39b5a7c290bd342ab5bb1a1`。

可以继续开发并正式交付本次更新；硬件书写与纸面效果仍需实物验证。

验收日志、准确命令、字体副本、用户数据哈希、截图和清理记录：`artifacts/parallel_import_0.1.18_20261018/`。包内真实 scx 两方法 11 字流程及完整 user_001 字体导入位于 `artifacts/windows_bundle_check_0.1.18_20261018_verified/`。原生界面使用新的 `workspaces/windows-parallel-0.1.18-verified`，原用户工作区仍为 `workspaces/windows-0.1.8`。

项目根目录 PowerShell：

```powershell
# 使用原工作区与完整字体启动新版
& 'artifacts/windows_build_0.1.18_20261018_verified/dist/InkStruct/InkStruct.exe' --workspace workspaces/windows-0.1.8 --font artifacts/user_001_full_font_20261018_math_axis/user_001-v61-full-symbols-20261018.inkfont

# 使用新输出目录复测，避免其他性能任务同时运行
.venv/Scripts/python.exe scripts/benchmark_font_import.py --font artifacts/user_001_full_font_20261018_math_axis/user_001-v61-full-symbols-20261018.inkfont --output artifacts/font_parallel_repeat_new

# 也可显式 --workers 1 作串行对照，生产默认自行选择有上限的进程数
# 专项测试使用新的 basetemp
.venv/Scripts/python.exe -m pytest tests/test_font_import.py tests/test_parallel_font_verify.py tests/test_settings_usability_qt.py tests/test_unified_settings_qt.py tests/test_math_settings_qt.py -ra --basetemp artifacts/qa18-repeat

# 本轮完整相关回归列表
.venv/Scripts/python.exe -X utf8 artifacts/parallel_import_0.1.18_20261018/run_logged.py regression_repeat .venv/Scripts/python.exe artifacts/parallel_import_0.1.18_20261018/run_regression.py

# 后续构建用新目录，正式交付前递增 APP_VERSION
.venv/Scripts/python.exe packaging/build_inkstruct_app.py --output artifacts/windows_rebuild_next_new
```

本次实际构建、包内验证命令分别记录于验收目录 `build_final.command.json`、`bundle_final.command.json`。仅清理本轮测试、私有临时缓存及 PyInstaller work/cache，保留源码、数据、日志、验收产物与交付包。

首轮包内自检发现自检结果探针的回调顺序竞态（不是字体校验失败），改为从已完成的字体操作读取结果；同时修复内嵌 QDialog 截获 Esc 隐藏自身页面的问题，让 Esc 取消外层设置，重新打开内容完整。专项 22 项通过后在全新 verified 目录重建、重测。首轮失败日志和候选构建保留，没有将它们当作交付包；正式交付仍只有一个 0.1.18 ZIP。
