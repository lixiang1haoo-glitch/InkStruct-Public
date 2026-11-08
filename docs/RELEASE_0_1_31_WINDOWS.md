# InkStruct 0.1.31 Windows：公式窄数字占位修复

交付日期：2026-10-20。项目路径：`C:\Users\lee\Documents\InkStructApp\InkStruct-Windows-Dev`。源码基点 `af45b45f04f899fcaced43aa980b0508673ee6c0` 加完整未提交工作树；不是从 Git 历史单独恢复。应用唯一版本来源为 `src/inkstruct/fonts/__init__.py::APP_VERSION`，本轮为 0.1.31。Python 库、字体及文档协议不递增。

## 原因与修复

0.1.30 的紧凑公式按照可见笔迹宽度加两侧留白、笔宽计算字符推进量。录制的数字 1 近似一条竖线，笔迹很窄，因此连续 1、小数和科学计数法中过于拥挤。表格普通数字另有最小占位保护，表现较好；两条排版路径并不相同。

本轮仅为紧凑公式中的 ASCII 数字增加最小推进量：当前公式字高的 `0.45 × 0.7 = 0.315`。原推进量较大时不变；小于下限时补足并将增加的空白均分到两侧。上下标及分式按各自实际字号计算。真实字体在 6 mm 字高下，1 的推进量由约 0.887–1.046 mm 调整为 1.89 mm。

不拉宽笔迹，不改变笔迹尺寸、基线、数学轴、字体资源或选样身份；非数字推进量保持原样。表格普通数字规则不变，表格内显式公式使用同一公式修复。测量缓存标记加入 `compact-digit-floor-v1`，避免复用旧宽度。

旧 v1/capture 公式几何保持原样。已有 v2 紧凑公式在重新排版或重开时应用本次修复，宽度、换行或分页可能相应变化；这不是保持 0.1.30 v2 的旧坐标。原 Markdown、冻结字形、样本和用户设置不被改写。无新 schema，无文档自动迁移。

## 真实验证

环境为 Windows 11 x64（10.0.26300）、项目 `.venv` Python 3.13.16 AMD64。没有安装研究/训练依赖，没有重跑全库生成。

| 验证 | 实际结果 |
| --- | --- |
| 专项及测量/数学相关测试 | 67 passed |
| 完整相关回归 | 1225 passed，2 skipped，345.75 秒 |
| 新增窄数字测试 | 20 项；多字号/笔宽、连续 1、小数、上下标、分式、比值、校正与保存重开 |
| Ruff | 本轮 5 个 Python 文件通过 |
| 真实字体 .30 源码对照 | 同字形、同选样；非数字推进量精确相同；capture 几何相同 |
| 旧模板与旧文档 | .21/.22 模板、.23 拉丁字距、.20 两种校正文档重开 SVG 字节一致 |
| 历史恢复文档 | 11 页、301 项原诊断保留；全部页面 SVG 一致；设置无操作往返一致 |
| 打包程序自检 | 实际 InkStructTool.exe 通过；两种方法 scx 11 字导入→建档→生成→字体→排版→重开→SVG 通过 |
| 大字体完整校验 | 9771 字、10730 候选、8375082 点；4 进程完整导入校验约 17.17 秒（本机本次） |
| 原生 Windows GUI | InkStruct.exe 0.1.31：打开真实字体小样，公式与表格预览、SVG 导出、另存、重开通过 |
| 原生导出精确核对 | 1 页、53 文本实例；源码身份、资源、冻结选样、页面 SVG、优化后机器 SVG 一致；全局默认未改 |
| 构建 | 新目录 Windows x64 构建成功，双 EXE FileVersion/ProductVersion 均为 0.1.31 |

两项跳过源于本机账户缺少符号链接权限：真实图片符号链接与悬空项目链接；没有降低安全检查。原生小样保留 2 项数学校准提示。打包自检中的参考来源/作者来源提示保留，不以隐藏警告通过验收。

这里只取得截图，未取得截图对应原始物理实验文档；使用真实已有字体和等价小样验证，不能声称复现了原文档。数位板、驱动、实体写字机及纸面效果未验证。LaTeX 手册源码已同步，未重新编译手册 PDF。

## 产物与数据保护

- 可运行程序：`artifacts/windows_build_0.1.31_20261020_release/dist/InkStruct/InkStruct.exe`；工具为同目录 `InkStructTool.exe`，保留整个目录及 `_internal`。
- 发布包：`artifacts/windows_release_0.1.31/InkStruct-0.1.31-Windows-x64.zip`；同目录 `verification.json`、`SHA256SUMS.txt` 记录双 EXE 与 ZIP 校验。
- 专项日志、实施前快照、旧源码对照、保存文档、SVG、原生截图：`artifacts/math_digits_0.1.31_20261020/`。
- 打包自检报告：`artifacts/windows_bundle_check_0.1.31_20261020_release/verification.json`。
- 原生验收工作区：`workspaces/windows-math-digits-0.1.31`，与用户工作区隔离。
- 最终封存核对：专项目录的 `delivery-seal.json`；本轮可重建缓存清单：`cleanup.json`。

实施前记录 3099 个可读用户文件 SHA256，交付前再次核对不变；另有 3 个历史字体文件读取权限受限，仅比较大小及修改时间，不修改权限、不宣称内容哈希验证。用户现有任务、样本、作者档案、生成、字体、评价、模板、文档及历史交付保留。没有 reset、clean、自动提交或推送。仅移除本轮有明确路径的可重建缓存，保留日志、源码与验收产物。

## 后续准确命令

以下 PowerShell 命令在项目根目录运行。正式新构建仍须递增 APP_VERSION，并使用尚不存在的输出目录。

```powershell
& .\artifacts\windows_build_0.1.31_20261020_release\dist\InkStruct\InkStruct.exe --workspace .\workspaces\windows-math-digits-0.1.31
& .\.venv\Scripts\python.exe -m inkstruct.application --workspace .\workspaces\windows-math-digits-0.1.31
& .\.venv\Scripts\python.exe -m pytest tests/test_math_digit_spacing.py tests/test_compact_math.py tests/test_math_layout.py tests/test_measurement_cache.py -q
& .\.venv\Scripts\python.exe artifacts/math_digits_0.1.31_20261020/run_logged.py regression -- .venv/Scripts/python.exe artifacts/math_digits_0.1.31_20261020/run_regression.py
& .\.venv\Scripts\python.exe packaging/build_inkstruct_app.py --output artifacts/windows_build_0.1.31_20261020_release
& .\artifacts\windows_build_0.1.31_20261020_release\dist\InkStruct\InkStructTool.exe --inkstruct-check --samples artifacts/source_samples/scx_351bf154/samples/scx --writer scx --font artifacts/user_001_full_font_20261018_math_axis/user_001-v61-full-symbols-20261018.inkfont --output artifacts/windows_bundle_check_0.1.31_20261020_release
```

上面的构建与自检输出路径为本次已执行路径，仅供追溯，重跑应选新目录。历史交付不得覆盖。本版本可继续开发并交付桌面应用；硬件验证限制如上。
