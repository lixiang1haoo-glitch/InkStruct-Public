# Markdown 混排交接说明

2026-10-14。权威范围为 [实施计划](MARKDOWN_MIXED_LAYOUT_PLAN_20261013.md)，当前能力见 [支持矩阵](MARKDOWN_SUPPORT_MATRIX.md)。这是工作区交接，另已准备 [按平台离线依赖材料](EDITOR_OFFLINE_KIT.md)：macOS 已在全新环境完成离线安装验证，Windows 仅完成材料与离线依赖解析；均需预装 Python 3.13，尚非独立运行时安装包。本轮未提交、推送或发布，也不保证当前共享分支已包含本机未提交文件。请以实际工作区文件和证据清单哈希核对版本，不能仅凭分支名或 HEAD 判断实现齐备。

## 启动

已有依赖的 macOS 工作区：

```sh
.venv/bin/python -m inkstruct.editor.app --source examples/markdown_tables_m3.md
.venv/bin/python -m inkstruct.editor.app --project artifacts/markdown_mixed_m5_20261013/acceptance/real/m5-combined.inkdoc
```

也可双击 `run_inkstruct_editor.command`。Windows 对应入口为 `run_inkstruct_editor.cmd`，或在项目目录运行：

```powershell
.venv\Scripts\python.exe -m inkstruct.editor.app --project path\to\report.inkdoc
```

环境要求以 `pyproject.toml` 为准：Python 3.12–3.13，桌面额外依赖 PySide6 6.9.2，解析器 markdown-it-py 4.0.0。新环境按平台建虚拟环境后安装 `.[desktop]`，开发验证安装 `.[desktop,dev]`；联网源码安装需要相应依赖可用；离线安装请使用独立材料及其安装说明，不把源码环境的安装命令用于离线包。

`inkstruct-editor` 是包声明的快捷命令；旧虚拟环境若未重新安装更新后的项目，可能尚未生成该命令。本机已发现此情况，以上模块入口与启动脚本无需依赖快捷命令重新注册。已核验模块 `--help` 和 macOS 脚本语法；Windows 命令列为待实机执行的入口。

## 导出与重现

从原生项目导出时继承方言、尺寸、字形和优化设置：

```sh
.venv/bin/inkstruct document render path/to/report.inkdoc --plotter --output artifacts/new-machine
```

输出目录必须不存在。显式开启优化加 `--optimize-paths`，关闭用 `--no-optimize-paths`。优化开启即允许反转。原始 Markdown 渲染须加 `--mode markdown`，否则 render 的旧默认模式是纯文本；Obsidian 原文还需 `--dialect obsidian`。字形来自 `--run`/`--symbols`；原生项目使用内嵌资源，不能同时指定外部资源覆盖。

复现本轮真实 M5 综合报告：

```sh
.venv/bin/python scripts/validate_m5_acceptance.py /path/to/user_001符号录制.zip --output artifacts/new-m5-acceptance
```

脚本输入公开合成 Markdown，使用私有录制轨迹生成四页项目、预览、严格 M/L SVG 和 `verification.json`。源内容是排版夹具，数字不是实验数据。ZIP 不随源码分发；所有私有产物放在忽略目录 `artifacts/`。固定原生项目包含源身份和选样，可逐字节复现机器 SVG；重新创建 SourceSession 会分配新身份，不应拿新建项目的随机选样与旧项目作逐字节比较。

自动验证：

```sh
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
.venv/bin/ruff check src/inkstruct/document/equations.py src/inkstruct/document/package.py src/inkstruct/math/handwritten.py src/inkstruct/math/sample_constructions.py tests/test_m5_acceptance.py scripts/validate_m5_acceptance.py
```

Windows 设置 `QT_QPA_PLATFORM` 应用 PowerShell 环境变量语法；离屏测试与原生交互测试分开记录。本机历史 25 项目/128 页冻结回放依赖私有 `artifacts/`，不是干净克隆中必然存在的公共 CI 输入。当前证据和文件哈希在 `artifacts/markdown_mixed_m5_20261013/acceptance/verification-manifest.json`。

## 实现位置与后续工作

| 领域 | 代码入口 | 继续工作的条件和验收 |
| --- | --- | --- |
| 语义、身份、项目 | `document/markdown.py`、`editing.py`、`equations.py`、`package.py` | 继续保护源范围、未改选样和草稿恢复；录制编号括号已修复稳定锚点及旧记录迁移 |
| 公式结构 | `math/handwritten.py`、`sample_constructions.py`、`editor/math_settings.py` | 项目结构模式资源扫描已接通，见 [资源检查](RESOURCE_INSPECTION.md)；真实英文/希腊仍需同步，随后做人工 baseline/math-axis 标定 |
| 正文与扩展 | `layout/blocks.py`、`footnotes.py`、`template_fields.py` | M5-04 受控扩展验收已汇总；复杂表格内部拆分仍未实现，维持明确诊断 |
| 页面模板 | `document/template.py`、`configs/templates/` | 按 [通用模板设计方案](TEMPLATE_AUTHORING_PLAN.md) 推进画布交互、插槽与 Agent 绑定；已接通数值/画布拖动绘制、多选对齐/等距、吸附、标尺/缩放/底图显示、PDF 页码导入和 JSON 校验，华科只作验证样例，纸面校准单独验收 |
| 编辑器与缓存 | `editor/mixed.py`、`build_cache.py`、`renderers/pages.py`、`layout/continuation.py` | 已提前取消旧计算；Cocoa 50 页编辑到确认 P95 7.62 ms。减少坐标格式化和页面键重复哈希后，综合混排首次翻页最大观测从 36.15 降至 30.10 ms；系统呈现和重排并发仍未验收。普通/模板/脚注续排不代表全篇不再解析度量 |
| 写字机出口 | `plotter/adapters.py`、`export.py`、`routing.py` | 机器试写长文本、小符号、多页和反转方向；保持 path/M/L 与优化前后轨迹保真 |
| 平台与交付 | `pyproject.toml`、启动脚本、`document/package_validation.py` | M6-01 原生输入法/DPI/文件对话框、M6-02 完整离线包/Windows迁移、M6-04 实机试写仍待完成 |

资源扫描已补齐；继续推进通用模板设计和绑定接口，离线依赖材料现已具备，继续推进 Windows 实际安装与原生平台验收。收到英文/希腊样本后按同一原始数据保留和实样验证流程接入。真实 Windows 和写字机验收必须记录设备/系统、输入文件哈希、设置与实际结果，不能从 macOS 离屏测试推定通过。整体目标继续 active。


## 2026-10-14 独立应用补充

已有不需预装 Python 的 [macOS 独立测试应用](EDITOR_STANDALONE.md)，包括 console PDF 配套程序；原生窗口检查发现的恢复目录只读问题已修复。包迁移、解压、自检、真实项目 SVG 一致与基础原生编辑/保存已验证，尚非 Developer ID 签名或公证发布版本。Windows 独立包、中文输入法/DPI 全项和设备纸面验收继续待办。

### 2026-10-14 当前 macOS 测试应用

最新冻结产物为 `artifacts/editor_app_preview_20261014/InkStructEditor-macos-arm64-preview-update.zip`，包含之前的小窗口/绑定/提前取消修复，以及首次页面 SVG 加载优化。原包/解压副本的包内编辑/撤销检查、项目往返、PDF 子进程均通过；真实四页综合报告优化 SVG 与原基准逐字节相等。对应源码全量 1453 passed / 4 skipped，原生性能测量的范围见 [性能记录](MARKDOWN_PERFORMANCE.md)。本轮未对新包另做手动原生窗口操作或计时，之前 response-update 的实际界面检查作为历史证据保留。旧包和 wheel 材料不自动升级。使用与证据边界见 [独立应用](EDITOR_STANDALONE.md)。Windows、英文/希腊样本、人工轴标定、完整可见帧和纸面/写字机验收仍未完成。

### 2026-10-14 字体回退与外部条件

用户确认 Windows 实机结果及英文/希腊样本仍未就绪，无需重复索取。本机新增 [字体回退验收](MACOS_FONT_FALLBACK_ACCEPTANCE.md)：实际 Cocoa 窗口指定不存在字体后中文显示正常，四页机器 SVG 哈希一致。当前 DPR 2 环境有记录，系统缩放切换/跨屏和真实输入法仍待验收；没有产品改动，现有最新测试包保持不变。

### 2026-10-14 原生拼音闭环

[macOS 原生输入法验收](MACOS_NATIVE_IME_ACCEPTANCE.md) 已补齐系统拼音短文档的组合、取消、提交、键盘撤销和重做证据。实际按键生成 7 次非空组合事件、1 次中文提交，源码和字符身份迁移正确，恢复原稿后机器 SVG 不变。修正仅涉及临时验证脚本的退出记录顺序，产品代码和独立测试包未改。此前“原生输入法待验证”的状态现缩小为其他输入法/复杂编辑情形及 Windows；不将此局部结果提升为 M6-01 全部通过。

### 2026-10-14 Windows 离线材料更新

已补齐此前 Windows wheel 材料落后于当前编辑器的交付缺口。最新文件为 `artifacts/editor_windows_refresh_20261014/InkStruct-editor-windows-x64-py313-preview-update.zip`，包含最新源码、固定依赖及 `验收步骤.md`，见 [离线材料更新说明](EDITOR_OFFLINE_KIT.md#2026-10-14-windows-当前源码更新材料)。材料完整性和 Windows 离线依赖解析通过；同一应用 wheel 在全新 macOS 环境的已安装自检通过。没有新 Windows 实机结果，不改变 M6-01/M6-02 未完成状态。源代码未改，macOS 独立包保持原版本。

### 2026-10-14 用户反馈后的界面与输入更新

当前 macOS 最新交付是 [界面与输入更新版](EDITOR_WORKSPACE_UPDATE.md)，顶部按钮改为主工具栏、右侧设置和按需展开的底部评价。新增空白启动焦点、原生编辑菜单及源码粘贴按钮。解压后的实际 `.app` 已验证直接键入、多行/中文粘贴、撤销重做与保存；旧版点击后完全无输入的状态未稳定复现，未声称找到唯一根因。全量 1461 passed / 4 skipped，包内与原生证据分开记录。Windows 材料本轮未更新。


## 2026-10-14 macOS 应用激活修复

旧 workspace-update 包错误带有 LSBackgroundOnly=true，源于 console 工具属性被 COLLECT/BUNDLE 继承。新 spec 显式声明普通应用，构建新增前台元数据与入口检查。最新包为 `artifacts/editor_activation_20261014/InkStructEditor-macos-arm64-focus-fix.zip`；详见 [界面与焦点修复](EDITOR_WORKSPACE_UPDATE.md)。16 项针对性测试、包内检查及原包/解压签名通过；Finder 首次双击及再次打开后，系统查询均确认 InkStruct 为前台活动应用。此前定向输入测试未覆盖系统焦点，不再据此宣称旧包焦点问题已解决。没有更新 Windows 包，也未提交或推送。
