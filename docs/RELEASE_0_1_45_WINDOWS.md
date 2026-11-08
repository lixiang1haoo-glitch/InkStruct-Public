# InkStruct 0.1.45 Windows 交付记录

2026-11-04，项目位于 `C:/Users/lee/Documents/InkStructApp/InkStruct-Windows-Dev`，HEAD 为 `af45b45f04f899fcaced43aa980b0508673ee6c0`。基于包含未提交修改的 0.1.44 完整源码推进。APP_VERSION 升为 0.1.45，Python 库仍为 0.2.0。本轮借鉴 OpenInk 的界面分工与反馈方式，使用现有 PySide6 独立实现，未引入其源码或转换依赖。

## 实际接入

- 统一浅色字体、控件间距、边框、选中、焦点和禁用样式。生成、制包、模板应用及字符/元素校正的主按钮使用强调色，标题采用一致层级，齿轮保留统一设置入口。
- 排版工具栏增加“源码／并排／预览”。复用原编辑器和连续滚动画布，通过显隐切换。应用偏好保存模式和并排宽度，默认并排；旧文档无需新字段。Ctrl+1、编辑菜单、显式源码定位会在必要时显示源码。
- 属性栏明确表格/图片编号、沿用本文默认或本文独立设置。字符校正顶部保留字符、Unicode、具体样本及本文使用次数，另显示当前作用范围与影响数量。重排时清除旧对象摘要并禁用旧表单，新预览完成后恢复；未应用草稿仍可取消或继续编辑。
- 文档资源面板增加与其他属性页一致的滚动容器，防止新控件尺寸把小屏窗口撑出屏幕。各设置项直接陈列，保留原菜单与快捷键。

生成、字体、模板和项目协议沿用 0.1.44。v6.2 的同字真实供体多候选、按出现位置选样、保存冻结、严格/强制 SVG 及原警告继续工作。此次正式范围是视觉层级、三种视图、对象摘要；字体/模板列表进一步改版、导入向导和路径对照的正式接入留待后续使用反馈。

## 本机验证

Windows x64、Python 3.13.16、PySide6 6.9.2、NumPy 2.5.4、Matplotlib 3.11.2、PyInstaller 6.22.3。沿用 `.venv`，未安装新依赖。

1. **1490 项综合回归通过，0 失败、0 错误、0 跳过**，104 个测试文件，262.95 秒。新增显示模式测试覆盖三种视图、新进程偏好恢复、宽度恢复、源码入口及完整快照/源码身份/冻结选样不变。新增属性测试在 100% 和 150% DPI 下检查对象/样本/范围、草稿、取消、过期禁用与保存重开。既有 100%/150%/200% 设置与滚轮保护检查通过。
2. 真实 user_001 字体含 215 字、1207 候选、102559 点。重开旧 0.1.41 文档后，严格 SVG 与历史 0.1.41 字节一致；两端对齐、自然书写 v1/v2 的四组兼容案例保存重开一致。原字体和原文档哈希保持，缺字、来源及数学度量提醒保留。产物为 `real-font-check`。
3. Windows 标准构建通过，43.73 秒，构建源哈希稳定。InkStruct.exe 和 InkStructTool.exe 均为 AMD64，FileVersion/ProductVersion 为 0.1.45，ProductName 为 InkStruct。
4. 两份 EXE 的实际冻结检查均通过。覆盖三种视图及快照/源码/选样不变、源码定位、对象摘要、后台多页进程导出、缓存、取消、故障串行回退、问题面板、两端对齐、模板保留及严格/强制 SVG。Tool 13.55 秒、GUI EXE 13.54 秒，均无 notices。
5. Tool 另用真实 scx 完整档案生成四字，串行和双进程各得到 16 候选，制包、96 处冻结选样、保存重开与严格 SVG 一致，22.45 秒，未触发回退。
6. 离屏实际窗口在 100% 和 150% DPI 留存三种模式和字符摘要截图。第一次离屏截图因平台未加载系统中文字体出现方框，验收脚本显式读取本机字体后重拍，旧图保留。字体文件只加载到验收进程，未复制到发布包。
7. 使用 computer-use 查看源码原生 Windows 窗口，1360×900、96 DPI、设备像素比 1.5。实际点击“预览”使源码区隐藏，Ctrl+1 返回并排。点击预览“孔”后显示具体样本及“仅此处 · 本文1处”。源文档、源码身份、快照和冻结选样保持。辅助功能焦点仍报告页码控件，未注入正文文字，不能将此视为中文输入法验收。

第一次相关测试发现窗口最低高度 805 超过离屏可用高度 800，根因是文档资源页未放入滚动容器。修复后 9 项针对性检查和最终综合回归通过。首次直接测试的子进程错误输出还出现编码解码异常，后续使用已有私有设置/UTF-8 综合入口取得完整错误并定位。失败日志保留。

## 隔离实验与决定

### 数值参数提交

从开工源码压缩快照提取 0.1.44 作为固定基线，使用真实字体比较正文数值、表格宽度和字符位移的原控件与内存中的 `setKeyboardTracking(False)`。共 36 次键盘序列，覆盖 30 ms 和 200 ms 键间隔，每组重复三次。源码身份、排版、冻结选样和字体哈希保持。

所有场景整文档重排请求均为零。表格参数原本就是待应用草稿；正文只有局部防抖预览；字符位移只重绘局部周边字形。提交后才更新可以减少局部绘制次数，但现有事件处理已在毫秒量级，且会改变即时反馈。**否决本轮另建统一数值草稿机制，保留隔离原型供后续有具体问题时复查。** 前两次夹具失败分别为等待未释放 GIL、控件未获焦点，修正后第三次完成，原失败保留。

日志为 `numeric-experiment/run-03/results.json`，脚本为 `numeric-experiment/probe.py`。这些是离屏控件处理测量，未证明原生输入体验或整任务性能改善。

### 路径优化对照

复用现有 PageRouter、导出选项和路由缓存，使用真实两页文档，每个路由场景三重复。

| 场景 | 笔数 | 首次优化中位 | 缓存复用中位 | 指标及逐笔身份复核中位 |
| --- | ---: | ---: | ---: | ---: |
| user_001 数学文档 | 272 | 84.88 ms | 8.03 ms | 10.47 ms |
| 同文档，132.293%/过滤表格/定位点 | 276 | 86.17 ms | 8.05 ms | 10.55 ms |
| scx 多候选文档 | 1872 | 1133.65 ms | 27.37 ms | 33.13 ms |

从已有路由对象读取统计的 1000 次微基准中位约 0.0032 ms。逐笔检查点列仅整笔反向，笔宽、笔画/来源/出现身份及冻结选样保持；双进程中途取消约 0.784 秒结束，无输出发布或临时残留。完整选项或快照变化会拒绝旧对照结果的最小原型检查通过。

**保留只读原型，建议后续按需后台接入。** 首次优化不能放在弹窗同步初始化中，正式呈现的易用性尚待人审。未加入新增连笔、去重或其他优化器。scx 例子空移减少 50.18% 是已有算法行为，不计为本轮新算法收益。原生流畅度及机器时间未测量。

原始日志为 `route-experiment/run-01/results.json`，汇总及原型截图为 `route-experiment/supplement-02`，命令和边界为 `route-experiment/experiment-record.json`。

## 未验证项

未重跑全库，未人工评价全部字体/模板，不宣称达到其他成熟编辑器的交互或性能水平。实体数位板/驱动、写字机纸面、中文 IME、冻结应用的人工原生输入尚未验证。两条实验未进入默认应用行为。LaTeX 手册源码已同步，未重编译新版 PDF。

## 使用、复现与保全

完整解压 `InkStruct-0.1.45-Windows-x64.zip`，保留 InkStruct 目录内全部资源后运行 InkStruct.exe。标准工作区沿用应用设置，验收使用独立私有目录。

从项目根目录执行以下命令，带 NEW 的输出位置应尚不存在。

```powershell
.venv/Scripts/python.exe -B -X utf8 -m inkstruct.application --workspace workspaces/windows-0.1.45-NEW
.venv/Scripts/python.exe -B -X utf8 scripts/run_layout_regression.py --junitxml=artifacts/regression-0.1.45-NEW.xml --basetemp=artifacts/pytest-0.1.45-NEW
.venv/Scripts/python.exe -B -X utf8 packaging/build_inkstruct_app.py --output artifacts/windows_build_0.1.45-NEW
$env:QT_QPA_PLATFORM='offscreen'
$env:INKSTRUCT_LAYOUT_PREVIEW_HOME=(Join-Path (Get-Location) 'artifacts/check-private-0.1.45-NEW')
artifacts/windows_build_0.1.45_20261104/dist/InkStruct/InkStructTool.exe --inkstruct-check --export-only --font artifacts/charsets_0.1.40_20261022/font-validation/user_001-v62-generation-0.1.40-validation.inkfont --samples artifacts/unused-0.1.45-NEW --output artifacts/check-0.1.45-NEW
.venv/Scripts/python.exe -B -X utf8 artifacts/gui_0.1.45_20261104/route-experiment/probe.py --output artifacts/gui_0.1.45_20261104/route-experiment/run-NEW
.venv/Scripts/python.exe -B -X utf8 artifacts/gui_0.1.45_20261104/route-experiment/supplement.py --output artifacts/gui_0.1.45_20261104/route-experiment/supplement-NEW
```

数值实验的命令与固定基线规则见 probe.py，使用新的输出位置并保留 source-before.zip。SVG 自检中的 `--export-only` 不读取 samples，该参数仅满足现有入口约定。

- 应用目录为 `artifacts/windows_build_0.1.45_20261104/dist/InkStruct`。
- ZIP、SHA-256 和最终解压运行验证为 `artifacts/windows_release_0.1.45`。
- 源码与文档开工快照、Git 状态、测试、实验、原生截图和日志为 `artifacts/gui_0.1.45_20261104`。开工快照包含 891 个文件。

用户数据、旧字体/文档、冻结选样和未提交工作保留。没有执行 reset、clean、提交或推送，独立排版开发目录未写入。仅清理本轮明确可重建的 pytest 临时目录与 PyInstaller work/cache，保留源码、原始测量、日志、构建清单、验收和交付产物。
