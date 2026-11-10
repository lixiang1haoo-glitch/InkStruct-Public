# InkStruct（墨构）

团队成员先阅读 [GitHub 协作与环境准备](docs/COLLABORATION.md)；两组任务书和公共接口在 [团队任务目录](docs/team_tasks_20261022/组长准备与协作清单.md)。Android 在独立私有仓库 [InkStruct-Android](https://github.com/lixiang1haoo-glitch/InkStruct-Android) 开发。

当前版本为 **0.1.73**，支持在自定义模板正文框中设置纸张行格。[Windows 安装器与 ZIP](https://github.com/lixiang1haoo-glitch/InkStruct-Public/releases/tag/app-v0.1.73)

0.1.70 将 v6.3 连笔支持接入桌面采集、生成与制包，Windows 安装和卸载界面使用简体中文。[发行记录](docs/RELEASE_0_1_70_WINDOWS.md) · [在线文档](https://lixiang1haoo-glitch.github.io/InkStruct-Public/)

0.1.64 收紧设置、生成和采集页的短字段与滑块，长路径和搜索框随窗口伸展。见 [Windows 交付记录](docs/RELEASE_0_1_64_WINDOWS.md)。

0.1.67 在「设置 › 应用设置 › 主题」提供跟随系统、浅色和深色，保存后立即切换。公式设置及印刷参考、手写预览使用当前主题配色。见 [Windows 交付记录](docs/RELEASE_0_1_67_WINDOWS.md)。

0.1.48：左侧常驻采集／生成／排版，底部依次为字体库、模板库及设置；名称与版本显示在系统标题栏。字体库提供精简列表、真实汉字／公式预览及保留草稿的试写，其他页面统一视觉层级，完整校验和旧文档冻结选样保持。见 [Windows 交付说明](docs/RELEASE_0_1_48_WINDOWS.md)。

0.1.46：支持展开总量最多4 GiB的字体，保留单成员、点数及完整校验限制；生成页每字成品上限可选1–64份，默认4份，均衡使用不同完整部件和真实录制样本。生成方法仍为v6.2 exp，旧字体、文档与冻结选样不自动改变。见 [Windows 交付说明](docs/RELEASE_0_1_46_WINDOWS.md)。

0.1.45：统一浅色控件和主操作，排版支持源码／并排／预览三种显示模式，属性栏明确对象、样本与作用范围。见 [Windows 交付记录](docs/RELEASE_0_1_45_WINDOWS.md)。

0.1.41：合入独立排版更新，修复 LaTeX 单参数、全角点、hbar 合成、横线与括号伸缩，新增换行、物理分页和正文换框。见 [Windows 合并交付说明](docs/RELEASE_0_1_41_WINDOWS.md)。


0.1.40：内置可核实版本的完整命名字表、显式缺口确认、一简多繁与地区成员查询；保留完整供体池及按字多进程。见 [Windows 交付记录](docs/RELEASE_0_1_40_WINDOWS.md)。

0.1.38：SVG 后台导出、多页进程并发及串行回退；保留冻结快照、全部导出设置和用户数据。见 [Windows 交付记录](docs/RELEASE_0_1_38_WINDOWS.md)。

0.1.36：SVG 比例校正先严格校验原始排版，再同步缩放输出坐标、画布尺寸与 viewBox，笔宽不变；原文档与预览不变。见 [Windows 交付记录](docs/RELEASE_0_1_36_WINDOWS.md)。

0.1.35：第三个标签页统一为“字体与模板”，提供真实笔迹预览、字符与样本检查、来源版本、模板缩略图与库内副本。“用于当前文档”先确认实际适配影响；新文档默认独立设置，移出资源可恢复。见 [Windows 交付记录](docs/RELEASE_0_1_35_WINDOWS.md)。

InkStruct 是一个以汉字结构先验驱动的个性化在线手写轨迹生成项目。名称中的 **Ink** 表示用户墨迹与书写风格，**Struct** 表示项目用标准结构约束内容正确性。

核心生成层级为：

```text
整字布局 → 部件整体轨迹 → 部件内部笔画 → 在线采样点
```

标准结构库固定目标字的笔数、笔顺和关键拓扑；作者采集提供个人轨迹。当前桌面推荐 `v6.2 exp`，保留 v6.1 与 v4 adaptive；旧 CLI 和研究入口有各自默认值，实验必须记录真实方法。不要求逐用户训练或 GPU。

完整文档请从 [`docs/README.md`](docs/README.md) 开始：

- [`docs/PROJECT_OVERVIEW.md`](docs/PROJECT_OVERVIEW.md)：项目定位、核心原理、系统组成与适用边界。
- [`docs/USER_GUIDE.md`](docs/USER_GUIDE.md)：安装、桌面应用、完整 CLI、数据协议、训练与故障排查。
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)：结构数据库、轨迹生成、笔顺对齐和模型架构。

## InkStruct 0.1.67 集成应用

0.1.34：六辐星号由录制减号合成，比号复用冒号，公式圆圈复用中文句号；新字体保留来源与动态数据。页码向上为上一页、向下为下一页。见 [Windows 交付记录](docs/RELEASE_0_1_34_WINDOWS.md)。

0.1.33：CPU 预览缓存与预取优化；齿轮“预览绘制”可选 GPU，失败自动回退 CPU，下次启动生效。新增 ℃／–／～ 的明确字形合成规则。SVG 导出弹窗统一页码、表格内容、路径优化、横纵比例校正及文本框边界定位短线。见 [Windows 交付记录](docs/RELEASE_0_1_33_WINDOWS.md)。

0.1.32：新增 v6.2 exp，先检查竖弯钩与止部关键笔兼容性，再重试合格来源；保留 v6.1 exp 和 v4 adaptive。现有字体、样本及文档冻结资源不自动改写。user_001 验证合并字体仅更新“孔”“正”；“孔”末笔无合格作者来源，明确保留参考缺口。 见 [Windows 交付记录](docs/RELEASE_0_1_32_WINDOWS.md)。

0.1.31：修复紧凑公式中数字“1”占位过窄的问题，参照表格数字规则保留最小占位并居中补白；不缩放字形、不改变表格普通数字规则及冻结选样。见 [Windows 交付记录](docs/RELEASE_0_1_31_WINDOWS.md)。

0.1.30：新文档公式按真实笔迹紧凑排列，减少运算符、分式与根式净距；根号和伸缩括号默认使用录制字形缩放。保留字号、上下标比例、数学轴与冻结选样，旧文档不自动重排。见 [Windows 交付记录](docs/RELEASE_0_1_30_WINDOWS.md)。

0.1.29：新文档标点按实际笔迹宽度紧凑排列，中英文均不预留半字或整字空位；路径优化默认开启。旧文档保留已保存的间距和优化选项，公式、代码规则及冻结选样不变。见 [Windows 交付记录](docs/RELEASE_0_1_29_WINDOWS.md)。

0.1.28：修复模板中不可容纳对象清空整份预览的问题，保留已排正文和脚注，明确提示停止及未排范围；资源目录采用独立有界容量以支持较大字体文档重开，保留全部校验。见 [Windows 交付记录](docs/RELEASE_0_1_28_WINDOWS.md)。

0.1.27：新文档分数线默认使用字体中的数学减号 `−` 横向拉伸，保留笔迹纵向起伏。旧文档保持原来源；缺少减号仍报错。见 [Windows 交付记录](docs/RELEASE_0_1_27_WINDOWS.md)。

0.1.26 扩展 SVG 的明确跳过范围：已载入位图和缺失的本地 PNG/JPEG 引用均可在确认后跳过，分别显示数量并提供文件名详情。缺失错误保留，未知类型、缺失 SVG、非法资源及其他错误仍阻断。见 [Windows 交付记录](docs/RELEASE_0_1_26_WINDOWS.md)。

0.1.25 含非 SVG 参考图片时可在提示后导出其余内容，保留图片占位和图题，并记录跳过清单；缺字、公式错误及越框仍阻止导出。见 [Windows 交付记录](docs/RELEASE_0_1_25_WINDOWS.md)。

0.1.24 将图片默认改为高 60 mm、宽度按原图比例计算，默认页移除宽度设置；支持公式直接包含汉字及汉字上下标。见 [Windows 交付记录](docs/RELEASE_0_1_24_WINDOWS.md)。

0.1.23 修正英文采集留白造成的疏散字距，字符校正预览显示真实邻字；旧文档保持原字距，可明确切换。见 [Windows 交付记录](docs/RELEASE_0_1_23_WINDOWS.md)。

模板现分为简单模板与自定义模板，支持起始页组、多个循环布局、有序正文框和单份 Markdown 命名字段。制作与管理从左下“字体库 → 模板”进入，当前文档套用与表单填写在右侧“文档资源”。见 [模板使用说明](docs/TEMPLATE_SINGLE_FLOW.md) 和 [Windows 验收](docs/RELEASE_0_1_22_WINDOWS.md)。

表格、图片设置全部陈列。排版预览点击字符，可在右侧“字符校正”调整位移和宽高，范围分为“仅此处”“本文同一样本”“本文同一字符的全部样本”；后两项可同时保存到字体包的新版本。见 [字符校正更新与验收](docs/RELEASE_0_1_20_WINDOWS.md)。

完整字体导入使用最多四个进程完整校验，保留阶段进度；参数禁用滚轮改值，正文设置全部展开，公式预览默认开启辅助线；见 [字体导入性能验收](docs/RELEASE_0_1_18_WINDOWS.md)。

齿轮保存本机全局默认，重启后保留并供新文档使用；已有项目保留原参数。排版右侧“元素属性”用于表格和图片的独立设置，可恢复沿用本文默认。公式设置按内容限定窗口最小宽度，无需横向滚动。详见 [0.1.16 Windows 验收](docs/RELEASE_0_1_16_WINDOWS.md)。

统一应用将采集、生成、字体与模板和 Markdown 排版放在同一窗口，支持完整 `.inkfont` 的发布、导入与文档冻结。使用说明和验证边界见 [0.1.67 集成应用](docs/INKSTRUCT_0_1.md)。源码入口为 `inkstruct-app`，独立应用构建入口为 `packaging/build_inkstruct_app.py`。应用版本 0.1.67 与 Python 库版本 0.2.0 独立。生成页默认 **v6.2 exp（推荐）**，另可选 **v6.1 exp**、**v4 adaptive**；从采集样本统一导入、建档、生成并发布字体。独立 CLI 的默认仍为 v4 adaptive，研究训练入口不随用户应用提供。Windows 初始化、命令和实际验收结果见 [Windows 初始化记录](docs/WINDOWS_INITIALIZATION_20261015.md)。

新版4 GiB限制按ZIP成员展开总量计算，不按压缩文件大小计算；32 MiB单成员、每候选点数、来源和哈希等原检查保留，超限结果不会发布。字体格式不变，但旧2 GiB读者不能读取超过旧上限的包。同源user_001八份上限字体实测：全结构库＋其余字符约611 MB，简体支持字集＋相同其余字符约454 MB，压缩空间减少约25.7%；简体包展开量仍超过2 GiB，需新程序读取。详见[容量与简体对照](docs/FONT_CAPACITY_SIMPLIFIED_20261104.md)。这些为字体文件体积，不是应用安装包体积。

## 当前状态

- 结构库包含 9,574 个有效简繁字符。
- 风格档案和生成任务按书写者 ID 隔离，运行产物保存在本地且不纳入源码仓库。
- 全量生成支持结构库中的 9,574 个字符，并通过 manifest 实现断点续跑。
- 默认生成采用平滑的 `adaptive` 部件模式：优先使用整组 `ComponentTrajectoryPrototype`，证据不足时逐级退回部件布局、条件化笔画和标准中心线；每笔通过开放 B-Spline 与弧长重采样输出 24–128 个节点。
- v5 已完成三个固定种子的正式训练和固定折消融；强制 v5 的 DTW/SDF 均弱于 v4，校准安全模式会回退到 v4，因此生产默认保持 `ComponentTrajectory v4 adaptive`。
- 样本对齐支持笔数相同但笔顺错误的全局匹配：高置信错序自动纠正，歧义错序隔离并进入质量审计，不再污染部件轨迹原型。
- 项目只关注几何字形与在线轨迹；当前不优化连笔，不导出 TTF/OTF。

## 环境

macOS 可执行 `bash scripts/setup_macos.sh` 安装 CPU、桌面和开发环境，然后双击根目录的 `run_inkstruct_generator.command` / `run_inkstruct_collector.command`。旧机器数据恢复、外部采集器路径和验证范围见 [Mac 安装说明](docs/MAC_SETUP.md)。

项目要求 Python 3.12 或 3.13。确定性生成、采集、结构检查和测试可在 CPU 上运行；只有实验性的分层残差模型训练需要 NVIDIA GPU。正式三种子训练协议见 `scripts/train_v5_formal.ps1` 和 `configs/training/v5_formal.json`。

Windows PowerShell：

```powershell
python -m venv .venv  # 先确认 python 为 Python 3.13 x64
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[desktop,dev]" "pyinstaller>=6,<7"
.\.venv\Scripts\python.exe -m inkstruct.application --workspace workspaces\windows
```

如果需要运行测试和代码检查，可改为安装开发依赖：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[desktop,dev]"
```

若需要训练功能，再安装带 CUDA 的 PyTorch，并执行：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[train]"
```

仓库内的 `requirements.lock` 和 `requirements.txt` 属于历史研究环境；桌面启动不要用它们安装整套环境。桌面 extras 包含生成必需的 Matplotlib，不需要 CUDA 或 PyTorch。

## 快速使用

查看或重建结构库：

```powershell
.\.venv\Scripts\inkstruct.exe structures info
.\.venv\Scripts\inkstruct.exe structures build
```

导入兼容 `handwriting_single_v1` 的单字 JSON，并建立一次性缓存风格档案：

```powershell
.\.venv\Scripts\inkstruct.exe samples import "C:\path\to\user_001" --writer user_001
.\.venv\Scripts\inkstruct.exe profile build --writer user_001
```

指定内容或所有支持字符生成：

```powershell
.\.venv\Scripts\inkstruct.exe generate --writer user_001 --text "墨构手写"
.\.venv\Scripts\inkstruct.exe generate --writer user_001 --all-supported --run-id all_supported
```

生成阶段只读取已缓存的 `profiles/<writer-id>/profile.json`，不会为每个目标字重复读取原始 JSON 或风格图片。

## 采集器与生成器

采集界面提供“单字任务采集”和“字母与符号”两页。点击“创建任务”，勾选英文正体、英文斜体、数字、运算符、希腊字母等类别并设置份数（默认 5）。允许不同笔数，保存原始轨迹和混排参考度量。[使用与构建说明](docs/SYMBOL_CAPTURE.md)。

两个桌面应用已经分离：

- 双击 `run_inkstruct_collector.cmd` 启动采集器；它负责书写、标准笔画数校验、重录提示，
  并在书写田字格左侧以绿色显示当前笔或下一笔的标准笔顺参考。
- 双击 `run_inkstruct_generator.cmd` 启动风格生成器；它负责样本导入、建档、文本生成和结果预览。
- `release/InkStructCollector/` 是不含 PyTorch/CUDA 的轻量 Windows 采集包。

命令行等价入口：

```powershell
.\.venv\Scripts\inkstruct.exe collector
.\.venv\Scripts\inkstruct.exe generator
```

## 数字表格排版

双击 `run_inkstruct_table.command`（Windows 为 `.cmd`）启动 HTML 数字表格排版，支持合并单元格与物理尺寸设置，导出子元素仅为 path、路径指令仅 M/L 的写字机 SVG。[使用说明](docs/TABLE_EDITOR.md)。

## Markdown 混排与字形检查

双击 `run_inkstruct_editor.command`（Windows 为 `.cmd`），进入左侧 Markdown 编辑、右侧分页预览。当前支持正文、标题、列表、引用、基本强调和一般表格，表格与图片可设置文档默认及每个元素的个性化参数，导入旧 `.inktable`、保存可移植 `.inkdoc`，并导出全文写字机 SVG。详见 [Markdown 混排编辑器](docs/MARKDOWN_MIXED_EDITOR.md)。

窗口可切回纯文本模式，支持点字放大、好/不好/待复核标记、备注、筛选、检查项目保存及评价 CSV 导出。同一字形的重复字共享评价，新版本字形不会误套旧评价。旧 `.inkreview` 打开后自动使用纯文本模式。详见 [纯文本检查应用](docs/TEXT_REVIEW_APP.md)。

生成器的“页面预览…”入口仍只读查看纯文本页面并导出 SVG/PNG。重复字、空白和原始换行保留；缺字或溢出阻止正式导出。公式、模板和页面拖拽尚未接入混排编辑器，阶段范围见 [混排实施记录](docs/MARKDOWN_MIXED_LAYOUT_PROGRESS_20261013.md)。初始方案评审见 [排版计划评审及构建记录](docs/PAGE_LAYOUT_PROGRESS_20261009.md)。

## 推荐、检查与评测

边界修复采用 `whole_glyph_fit_v1`：仅对实际越界的整字统一等比适配，避免逐点裁切造成末端压平；正常边界接触保持原样。轨迹附带 `canvas_fit`，评估报告包含适配数量及需复核字符。旧生成目录需要新 `--run-id` 重新生成，不能直接续跑得到修复结果。采集器新增留白参考框和触边保存确认。实施状态与剩余质量改进任务见 [交接文档](docs/HANDOFF_CANVAS_AND_QUALITY.md)。

根据 9,574 字中的部件频数和当前档案覆盖缺口推荐补采字符：

```powershell
.\.venv\Scripts\inkstruct.exe collect recommend --writer user_001 --count 200
```

针对指定生成字符集生成 90/95/99/99.9/100 分五档最少字符采集计划：

```powershell
.\.venv\Scripts\inkstruct.exe collect coverage-tiers --writer user_001 `
  --index artifacts\samples_merged_202608201606\user_001\index.jsonl
```

该命令输出一份带档位的审计 CSV 和五份增量、可直接导入采集器的 CSV。预计分数假设新增
样本通过对齐与档案抽取，采集后仍需重新建档验证。

将结构库导出为 GB2312 大陆标准简体包与非大陆标准简体包，并只针对简体包规划：

```powershell
.\.venv\Scripts\inkstruct.exe structures export-packages `
  --output-dir configs\character_packages
.\.venv\Scripts\inkstruct.exe collect coverage-tiers --writer user_001 `
  --index artifacts\samples_merged_202608201606\user_001\index.jsonl `
  --target-package mainland_standard_simplified_gb2312
```

检查错误笔画数、低置信对齐和待重录样本，并验证生成结果：

```powershell
.\.venv\Scripts\inkstruct.exe samples audit --writer user_001
.\.venv\Scripts\inkstruct.exe evaluate --run outputs\user_001\all_supported_component_trajectory_v4
```

## 输出协议

默认生成目录为：

```text
outputs/<writer-id>/<run-id>/
├─ manifest.json
├─ trajectories/U+XXXX.json
└─ previews/
   ├─ U+XXXX.svg
   └─ U+XXXX.png
```

每个 `personal_trajectory_v1` JSON 包含字符、结构库版本、风格档案版本、生成置信度，以及各笔的标准笔画 ID、笔顺和 `x/y/t_ms/pressure/pen_state` 点序列。内部几何坐标统一为 `[0,1]`、左上角原点、Y 轴向下。

## 项目结构

```text
InkStruct/
├─ src/inkstruct/                   核心包、CLI 与桌面应用
├─ tests/                           单元与集成测试
├─ docs/                            项目介绍、完整手册、架构和研究说明
├─ scripts/                         环境、评测和批处理脚本
├─ packaging/                       轻量采集器打包脚本
├─ third_party/makemeahanzi/        标准中心线与拆字数据
├─ configs/                         训练、实验、字符包和采集计划配置
├─ artifacts/                       本地数据库、样本索引和报告（Git 忽略）
├─ profiles/                        本地版本化风格档案（Git 忽略）
├─ outputs/                         本地生成轨迹与预览（Git 忽略）
├─ data/                            可选训练数据（Git 忽略）
└─ release/                         本地打包结果（Git 忽略）
```

## 测试与代码检查

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\ruff.exe check src tests scripts packaging
```

强制生成不变量包括：输出笔数与标准结构一致、笔顺连续、坐标有限、部件引用有效，以及未知字符不得静默替代。

## 数据与许可

项目代码采用 MIT License。汉字结构数据来自 Make Me a Hanzi，具体来源和许可说明见 `THIRD_PARTY_DATA.md`。CASIA 与用户手写样本不是项目代码的一部分，使用、分发和商业化前需分别确认数据授权；项目不会修改外部原始样本。

`.venv/`、`data/`、`artifacts/`、`profiles/`、`outputs/`、`release/`、模型权重、缓存和本地 `.env` 文件均由 `.gitignore` 排除，不应提交到远程仓库。克隆源码时使用 `git clone --recurse-submodules` 获取 Make Me a Hanzi 子模块；子模块只记录上游提交引用，不在本仓库中复制第三方依赖源码。

原 SDT 仅作为项目演进来源和效果对照，不再参与 InkStruct 当前运行路径。

## 完整源轨迹实验入口（默认关闭）

Mac 生成器的“轨迹路径”可选“完整原始部件”或“保护折钩的轻量简化”，并选择同一作者的高保真副档案。“高保真副档案”按钮将档案保存到独立的 `profiles/source_runs/` 子目录，不覆盖既有风格档案；实验界面输出位于 `outputs/source_experiments/`。默认仍为 v4 adaptive 平滑生成。

CLI 示例（Mac，仓库根目录）：

```bash
.venv/bin/inkstruct generate --writer scx --text '侈徼劓岛' \
  --profile profiles/scx/profile.json \
  --source-profile profiles/source_v1_20261007/scx/profile.json \
  --trajectory-mode source-raw --source-nested-views \
  --output-root outputs/source_experiments
```

将 `source-raw` 换成 `source-simplified` 即使用输出坐标误差上限 0.004 的保护性简化。两条路径先确定同一套完整部件供体和共同等比变换；不逐笔拟合，不在简化后重新选供体。实验入口固定原 A 的 `adaptive`、强度 1，不与神经检查点混用。

评测时用 `--source-characters train_characters.txt` 显式限定允许提供部件的训练字符，文件为 UTF-8 字符列表，忽略空白；同字全部重复样本共同纳入/排除，目标同字始终不能提供跨字候选。A 的 `--profile` 也必须独立由训练集建立。未指定训练字符表的普通生成使用源档案中所有非目标字实例，不能据此宣称留出效果。

每个实验轨迹 JSON 增加 `source_components`，保存候选、共同变换、源点索引、输入哈希、简化/部件回退及逐笔几何审计。原有置信度沿用 A，尚未校准为新轨迹质量；源映射支持分数单独记录。运行身份变化会拒绝续跑，需新建 run-id。[接入验证和限制](docs/SOURCE_GENERATION_ENTRY_20261007.md)。
