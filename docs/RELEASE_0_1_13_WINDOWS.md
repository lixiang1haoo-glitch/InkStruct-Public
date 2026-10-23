# InkStruct 0.1.13 Windows：连续页面预览与滚动优化

日期：2026-10-18（Asia/Shanghai）。实际项目：`C:\Users\lee\Documents\InkStructApp\InkStruct-Windows-Dev`。Git 基点 `af45b45f04f899fcaced43aa980b0508673ee6c0`，继续使用含既有未提交修改的完整工作树。没有 reset、clean、自动提交或推送，没有覆盖历史交付。应用版本唯一来源为 `src/inkstruct/fonts/__init__.py:APP_VERSION`，本次为 0.1.13，下次正式交付至少 0.1.14；Python 库仍为 0.2.0，字体协议不变。

## 已完成的行为

排版预览现在采用纵向连续纸张：页面之间有间距和阴影，可以直接滚轮跨页。右上页码随视口中心所在页更新，也可以输入页码跳转；缩放保持原页面中的相对位置。跨页字形点击、原文定位、字形评价和选中框继续工作。文档保存和 SVG 导出仍使用原始矢量笔迹。

原生 Windows 0.1.13 应用在独立 `workspaces/windows-preview-0.1.13` 中验收，没有接管或修改 user_001 原采集任务。实际打开长文档，滚过第 1/2 页边界、确认页码跟随、点击第 2 页字形定位原文、切换到 150% 缩放，另存为新的 `native-continuous.inkdoc` 并在原生窗口重开。截图和项目均保留在本轮验收目录。

## 卡顿瓶颈及已落实的优化方案

旧实现缓存了 `QSvgRenderer`，但滚动露出新区域时仍会重新对整页笔迹进行矢量描边。密集手写页面在较大缩放或高 DPI 下，一次绘制可占用约 0.2 秒，阻塞界面事件。0.1.12 的约 7 毫秒重复绘制结果没有覆盖该密集页、高 DPI 和缩放组合，不能代表用户遇到的滚动场景。本次使用原长文档的同一密集页和真实 QScrollArea 移动重新测量。

落实方案：

1. 只遍历视口内页面与附近区域，按滚动方向预取一个相邻页，不一次绘制整本书。
2. 屏幕显示改用有界像素缓存：LRU 上限 96 MiB，单张图不超过 40 MiB；更大的页面按 512×512 设备像素分块。缓存按页面内容、缩放和设备像素比区分，标记与选中框单独叠加。未变化的不可变页面复用已有图像，文稿其他位置的编辑不会让整本闪白。
3. 页面 SVG 准备放入后台任务；原生 QtSvg 绘图放入持久的独立进程，由包内 `InkStructTool.exe --inkstruct-preview-worker` 承担。主界面仅接收完成的图像并合成。试验过只用后台线程，密集页预取期间仍有约 377 毫秒绘制和 383 毫秒事件间隔尖峰，故没有停留在线程方案。该现象说明同进程运行仍有争用；本轮没有对 Qt C++ 内部或绑定的 GIL 行为作进一步归因。
4. 限制并发和预取预算，取消过期任务并丢弃旧快照结果。跨进程图像通过私有临时文件传递，检查尺寸、步长、完整性及容量，结束后清理；绘图失败会显示错误，不放宽导出检查。

没有降低笔迹精度，没有替换字体、隐藏警告或修改生成核心、排版规则与字体协议。像素缓存只用于屏幕，SVG 导出仍走原有矢量路径。

## 本机性能实测

环境：Windows x64，项目独立 `.venv` Python 3.13.16、PySide6 6.9.2、PyInstaller 6.22.3、Matplotlib 3.11.2。完整依赖和源码哈希见构建 `build-provenance.json`。

使用原文档只读副本：11 页、4580 个文本实例、301 条原有诊断；取第 6 页密集笔迹，在真实 Qt 事件循环中执行 96 步滚动。下面是屏幕绘制 P95，不是全量排版或加载耗时。数值仅代表本机和该文档。

| 设备像素比 | 应用缩放 | 原实现绘制 P95 | 0.1.13 绘制 P95 |
| --- | --- | ---: | ---: |
| 1 | 100% | 3.06 ms | 0.55 ms |
| 1 | 200% | 195.05 ms | 0.69 ms |
| 2 | 100% | 195.81 ms | 0.57 ms |
| 2 | 200% | 164.51 ms | 0.70 ms |

像素比 2、100% 缩放时，事件循环最大间隔从约 199 ms 降到 53 ms，单次绘制最大值约 27 ms；200% 时单次绘制最大值约 0.95 ms。首次可见页尚未缓存时，完成屏幕图像约需 0.47～0.51 秒；此时可以继续滚动，页面完成后填入。相同高 DPI 场景缓存占用约 26～69 MiB，低于 96 MiB 上限。

常规 DPI、100% 的旧实现首次显示更快（约 0.06 秒，新方案约 0.28 秒）；这是启动伴随绘图进程的代价，随后进程持续复用。不能把热缓存滚动数据当作冷页加载或全量重排数据。仍可能出现几十毫秒的图像交接停顿，本次不宣称零延迟。

原始记录：`artifacts/continuous_preview_0.1.13_20261018/before-dpi-{1,2}.json` 与 `final_process-dpi-{1,2}.json`。线程原型的 `after-dpi-2.json` 和中间过程日志也保留。

后续若更大文稿的首次显页仍有问题，先分别测量 SVG 序列化、子进程绘图、图像交接和缓存命中，再针对最长阶段改进：例如减少图像交接拷贝、按可见区域细化分块优先级。本轮先保留一个绘图进程和有界预取，避免增加并发后争用与内存上涨；尚未实施或宣称这些进一步优化的收益。

## 测试、构建与边界

- 最终相关回归 **335 passed，0 skipped**，112.50 秒；Ruff 通过。覆盖连续滚动、页码跳转、跨页点击、缩放定位、1/1.5/2 倍 DPI、像素分块接缝与原 QtSvg 图像一致、LRU 容量、取消旧结果、复用未变化页、绘图进程缺失和退出清理，以及原有采集、重录、确认复用、字体、公式、保存恢复和分页检查。
- Windows x64 的 `InkStruct.exe` 和 `InkStructTool.exe` 构建成功，两者 PE 版本均为 0.1.13；构建前后及交付时源码哈希一致。
- 包内真实 scx 11 字小集合的 v6.1 exp 与 v4 adaptive 两条导入、建档、生成、制作字体、排版、保存重开、SVG 流程通过。运算符数学轴、公式冻结和 SVG 导出通过；独立绘图进程、屏幕缓存预算与可见页完成检查通过。采集自动测试为合成输入，未冒充实体数位板验收。
- 原生另存后独立加载，原文、字符身份、字形选择、评价及全部 11 页 SVG 与原输入一致。优化前后所有页面 SVG 哈希一致，301 条诊断保留。本轮没有修复另行存在的缺字、未支持公式和校准提示，也没有使该有阻断问题的长文稿变为可正式导出。
- 实体数位板、驱动、写字机及纸面效果未验证。README、使用说明与 LaTeX 手册源码已同步；环境缺少 XeLaTeX/latexmk，新版手册 PDF 未重编译，历史 PDF 保留。

可以继续开发并交付本次连续预览更新。首次冷页仍有等待，高 DPI 图像交接仍有小尖峰；这些是后续性能观察项，不要求重新采集或制作字体。

## 产物与准确命令

项目根目录 PowerShell：

```powershell
# 日常使用原工作区；独立验收工作区不替代原采集任务。
& 'artifacts/windows_build_0.1.13_20261018/dist/InkStruct/InkStruct.exe' --workspace workspaces/windows-0.1.8 --font artifacts/user_001_full_font_20261018_math_axis/user_001-v61-full-symbols-20261018.inkfont

# 相关回归（私有临时目录与完整 UTF-8 日志）
.venv/Scripts/python.exe -X utf8 artifacts/continuous_preview_0.1.13_20261018/run_logged.py regression_repeat .venv/Scripts/python.exe artifacts/continuous_preview_0.1.13_20261018/run_regression.py

# 高 DPI 滚动复测；恢复当前 shell 设置即可。
$env:QT_SCALE_FACTOR='2'
.venv/Scripts/python.exe -X utf8 artifacts/continuous_preview_0.1.13_20261018/run_logged.py benchmark_repeat .venv/Scripts/python.exe artifacts/continuous_preview_0.1.13_20261018/scroll_benchmark.py repeat_process
Remove-Item Env:QT_SCALE_FACTOR

# 本次已执行构建；后续使用全新输出目录，正式交付新构建先递增 APP_VERSION。
.venv/Scripts/python.exe packaging/build_inkstruct_app.py --output artifacts/windows_rebuild_next_new
```

本次实际构建命令是 `packaging/build_inkstruct_app.py --output artifacts/windows_build_0.1.13_20261018`，完整日志位于该构建目录及本轮验收目录。包内检查命令见 `bundle.command.json`，最终完整性检查见 `final_audit.py` / `final-verification.json`。

可运行目录：`artifacts/windows_build_0.1.13_20261018/dist/InkStruct/`，必须保留两个 EXE 和 `_internal`。发布包：`artifacts/windows_release_0.1.13/InkStruct-0.1.13-Windows-x64.zip`。

ZIP SHA-256：`4ec4725d4b06e0b8f99560094b234fae225abbfb98a24cabd5d56595cd144202`。发布目录含使用说明、SHA256SUMS 与文件级校验，ZIP CRC 通过。

日志、命令、取证源码副本、性能 JSON、原生截图、另存项目在 `artifacts/continuous_preview_0.1.13_20261018/`，两方法验收产物在 `artifacts/windows_bundle_check_0.1.13_20261018/`。原始自动恢复文件与既有完整字体哈希未变；任务、样本、档案、生成、评价和历史包保留。已有数学轴修复字体 SHA-256 仍为 `b114b9db538610176eaf4ca7ca6f5f177fd0319817599433dec274c50061c9c3`。

仅清理本轮可重建的测试临时目录、私有缓存及 PyInstaller 工作目录，清理结果写入本轮验收目录 `cleanup.json`；源码、数据、日志、构建溯源、验收文档和交付产物保留。
