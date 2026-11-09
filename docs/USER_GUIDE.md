# InkStruct（墨构）完整使用手册

0.1.66 在受支持的 Windows 11 环境加载 Qt 原生样式，侧栏和表单跟随系统深浅色。见 [Windows 交付记录](RELEASE_0_1_66_WINDOWS.md)。

0.1.48：主窗口改为左侧导航，采集／生成／排版在上方，字体库、模板库和设置在底部；系统标题栏显示名称与版本。Alt+1/2/3/4/5 切换模块，Ctrl+, 打开设置，F1 或侧栏右键查看关于。字体库与模板库独立打开，试写预设隐藏源码，点击“编辑试写…”后输入，切换预设保留草稿。见 [Windows 交付记录](RELEASE_0_1_48_WINDOWS.md)。

0.1.46：字体展开总量上限提高至4 GiB，保留单成员、点数和所有协议检查。v6.2生成页的“每字成品上限”可输入1–64份，默认4份；候选均衡覆盖完整部件和同一供体字的不同真实录制样本，有限尝试两个部件同时变化。见[Windows 交付说明](RELEASE_0_1_46_WINDOWS.md)。

0.1.45：排版工具栏可切换源码／并排／预览，Ctrl+1 返回源码，视图偏好随应用保存。属性栏显示对象与范围，重排时清理旧摘要。见 [Windows 交付说明](RELEASE_0_1_45_WINDOWS.md)。

数量包含原主字形；选1份时不搜索额外字形，v6.1/v4固定单份。额外候选来自真实供体部件，每个单部件或联合方案都重新检查最终整字，来源不足时保留实际合格份数。增加上限会增加计算时间和字体体积，改变上限可能改变额外候选组合，不保证旧候选列表是新列表的前缀。新字体按出现位置选择同字写法，相邻位置偶尔可能相同；旧字体、旧文档和冻结选择不自动更改。再次生成建立新批次，制作字体另存新包。

0.1.41：合入独立排版更新，修复 LaTeX 单参数、全角点、hbar 合成、横线与括号伸缩，新增换行、物理分页和正文换框。见 [Windows 合并交付说明](RELEASE_0_1_41_WINDOWS.md)。


0.1.40：内置可核实版本的完整命名字表、显式缺口确认、一简多繁与地区成员查询；保留完整供体池及按字多进程。见 [Windows 交付记录](RELEASE_0_1_40_WINDOWS.md)。

0.1.38：SVG 后台导出、多页进程并发及串行回退；保留冻结快照、全部导出设置和用户数据。见 [Windows 交付记录](RELEASE_0_1_38_WINDOWS.md)。

0.1.36：SVG 比例校正先严格校验原始排版，再同步缩放输出坐标、画布尺寸与 viewBox，笔宽不变；原文档与预览不变。见 [Windows 交付记录](RELEASE_0_1_36_WINDOWS.md)。

0.1.35：第三个标签页统一为“字体与模板”，提供真实笔迹预览、字符与样本检查、来源版本、模板缩略图与库内副本。“用于当前文档”先确认实际适配影响；新文档默认独立设置，移出资源可恢复。见 [Windows 交付记录](RELEASE_0_1_35_WINDOWS.md)。

0.1.34：六辐星号由录制减号合成，比号复用冒号，公式圆圈复用中文句号；新字体保留来源与动态数据。页码向上为上一页、向下为下一页。见 [交付记录](RELEASE_0_1_34_WINDOWS.md)。

0.1.33：CPU/GPU 预览优化、℃与符号扩展、统一 SVG 导出弹窗，详见 [Windows 交付](RELEASE_0_1_33_WINDOWS.md)。

0.1.32：新增 v6.2 exp，先检查竖弯钩与止部关键笔兼容性，再重试合格来源；保留 v6.1 exp 和 v4 adaptive。现有字体、样本及文档冻结资源不自动改写。user_001 验证合并字体仅更新“孔”“正”；“孔”末笔无合格作者来源，明确保留参考缺口。 见 [Windows 交付](RELEASE_0_1_32_WINDOWS.md)。

0.1.31：修复紧凑公式中数字“1”占位过窄的问题，参照表格数字规则保留最小占位并居中补白；不缩放字形、不改变表格普通数字规则及冻结选样。已有紧凑公式（数学样式 v2）重排或重开时会使用修复后的数字占位，不需要切换参数；旧版采集留白（v1/capture）规则保持。公式变宽时仍执行原有分页与尺寸检查。源码、字体、文档设置和样本不改写。见 [Windows 交付](RELEASE_0_1_31_WINDOWS.md)。

0.1.30：新文档公式按真实笔迹紧凑排列，减少运算符、分式与根式净距；根号和伸缩括号默认使用录制字形缩放。保留字号、上下标比例、数学轴与冻结选样，旧文档不自动重排。

齿轮 → 排版默认设置 → 公式 → 字号与字形，提供“公式字距”：按笔迹紧凑排列或保留旧版采集留白。分式、根式及括号的构件来源分别选择。首次升级只在内存更新新文档默认，明确应用后保存；旧文档保留原参数。应用到本文需明确勾选，并核对其余全局默认。紧凑策略消除横向采集留白并按实际笔迹布置结构，保留显式空格；根号分段延长横线，大括号按高度适配并限制宽度，避免横向过度拉宽。缺样或退化仍报错，不用替代字形静默放行。见 [Windows 交付](RELEASE_0_1_30_WINDOWS.md)。

0.1.29：新文档标点按实际笔迹宽度紧凑排列，中英文均不预留半字或整字空位；路径优化默认开启。旧文档保留已保存的间距和优化选项，公式、代码规则及冻结选样不变。

齿轮 → 排版 → 正文与段落 → 标点间距可选择“按笔迹紧凑排列”或保留旧版采集留白。首次升级只更新内存中的新文档默认，不自动写入设置或更改已有文档。将默认应用到当前文档须明确勾选，应用前核对其余默认参数。标点保留原大小、基线与笔迹，仅消除采集位置带来的横向空白，使用与字母相同的最小笔迹间隙。路径优化可在导出选项中关闭，新项目保存时记录其值；它只重排允许范围内的轨迹顺序及方向，不改变排版或笔迹。见 [Windows 交付](RELEASE_0_1_29_WINDOWS.md)。

0.1.28：若某个公式、代码行、图片或表格行组无法放入模板正文框，预览保留此前已排内容与已引用脚注，并提示“此处及后续正文尚未排版”。点击“查看问题”定位源码；调整正文框或手动拆分过长公式后重新排版。不会自动缩放、静默省略或放行导出。较大字体资源目录支持保存重开，原文档、校验和冻结选样保留。见 [Windows 交付](RELEASE_0_1_28_WINDOWS.md)。

0.1.27：新文档分数线默认使用字体减号 `−`（U+2212）横向拉伸；根号、括号来源不变。全局默认首次载入时升级分数线来源，只在明确应用时保存，之后明确选择的几何模式仍可保留。旧文档按原设置重开；需要时在齿轮 → 排版 → 公式 → 分式选择字体减号，并明确将默认参数应用到当前文档（会同时应用其他默认参数，请先核对）。ASCII 连字符不替代数学减号，缺样继续阻断导出。见 [Windows 交付](RELEASE_0_1_27_WINDOWS.md)。

0.1.26：已载入位图和缺失的本地 PNG/JPEG 引用均可在确认后跳过，分别显示数量和可展开的文件名；保留占位、图题、缺失诊断与冻结选样。缺失 SVG、未知类型、非法资源及其他错误仍阻断。见 [Windows 交付](RELEASE_0_1_26_WINDOWS.md)。

0.1.25：含非 SVG 参考图片时，点击导出会提示跳过图片本身；确认后保留占位与图题，导出其余内容，并在清单中记录跳过项。缺字、公式错误、缺失资源和越框仍须解决。见 [Windows 交付](RELEASE_0_1_25_WINDOWS.md)。

用户应用 **0.1.66** 请先阅读 [统一应用说明](INKSTRUCT_0_1.md)；默认 v6.2 exp，可选 v6.1 exp、v4 adaptive。本文后面的训练、检查点和消融参数属于独立研究 CLI，不是用户应用入口。

0.1.24：图片默认高度为 60 mm，宽度按原图比例计算，默认设置不再提供宽度输入。单张图片可在右侧独立选择按高度或按宽度等比调整，旧文档尺寸保留。公式可直接写 `$U_{模块}$`、`$U_{万}$`，汉字上下标与常用结构使用真实字体；缺字、语法与数学校准提示继续保留。详见 [本次 Windows 交付](RELEASE_0_1_24_WINDOWS.md)。

字符校正：点击排版预览中的字符，右侧“元素属性 → 字符校正”提供左右、上下位移及独立宽高缩放。位移以当前字高的百分比表示，向右、向下为正；缩放 100% 为原尺寸，以左侧基线为原点。灰色预览为字体原字形，蓝色为本次校正。点击“应用字符校正”后作用于页面预览、SVG 和写字路径，随 `.inkdoc` 保存，保留原字距与换行。

0.1.20 引入的字符校正范围为“仅此处”“本文同一样本”“本文同一字符的全部样本”。例如选中 A2，第一项只改此处；第二项改本文所有 A2，A1 不变；第三项改同一字体类别的 A1、A2 等全部样本。正体与斜体默认分开，需跨类别时明确勾选“同时包含正体与斜体”。界面显示当前样本、本文使用次数及将影响的样本和出现次数。批量应用会统一覆盖范围内已有校正，旧单字校正不会遮住批量结果；不叠加上一次文档校正数值。参数相对于当前字体字形生效。

“恢复所选范围”恢复为当前字体原字形，其他范围保留；右侧提供按操作撤销、重做及取消未应用草稿。不存在的字形仍报缺字，校正超出页面可用区域会阻止成品导出。重复表头或模板中的同一次源码出现仍同步校正。旧版全文校正可以按原效果重开，但不再提供新建全文校正入口。

后两种范围可勾选“同时保存到字体包的新版本”，默认不勾选。样本范围只写入 A2，全部样本范围写入同类 A1、A2 等，包含字体包内本文尚未用到的样本；跨正斜体需明确选择。选择不存在的新文件名，原包保留。成功后本文也应用相同校正，仍使用原字体快照，不自动换成新包、不重复叠加。新包可从字体库导入后供后续文档使用。取消选文件或字体校验失败时，文档保持原样；如果处理期间文档发生变化，新字体保留，旧操作不会写入已变化的文档，界面会明确提示。

字体保存完整校验原包和新包，生成新的发布、包及改动候选身份，保留原始轨迹、动态字段、正斜体与来源提示。原排版框和校正审计保留，位移不会被负边距归一化抵消。从已保存项目操作时，需选择该版本的原始完整字体包。“恢复”或“撤销”只调整本文，不删除已经另存的字体包。见 [字符校正范围交付记录](RELEASE_0_1_20_WINDOWS.md)。

完整字体导入会显示复制、索引和候选验证进度，完整验证通过后加入字体库。0.1.18 使用最多四个进程验证大字体，小字体串行，保留去除重复验证及中间排版对象的优化，保留全部协议检查；相同包 ID 但内容不同的文件不会覆盖原文件。实际全库耗时与验证边界见 [字体导入性能验收](RELEASE_0_1_18_WINDOWS.md)。

左下角设置保存本机全局默认，重启后保留，新文档自动使用。已有项目保留原参数；「存为默认」只更新新文档默认并关闭；「应用并保存」还更新当前文档，保留表格、图片独立属性，窗口保持打开；「取消」放弃尚未保存的修改。表格、图片的独立属性在右侧“元素属性”调整，点击“应用元素属性”后随项目保存，也可恢复“沿用文档默认”。修改全局默认不清除已有独立设置与字体。公式设置窗口最小宽度随内容确定，支持纵向滚动。

本文档覆盖 InkStruct `0.2.0` 的安装、轨迹采集、样本导入、风格建档、补采规划、个性化生成、评估、训练、实验、便携版打包、数据协议和故障排查。

除非特别说明，所有命令都在项目根目录执行。Windows PowerShell 是当前仓库已验证的主环境；Linux/macOS 仅给出通用 Python CLI 形式，不代表桌面应用和打包流程已经过同等验收。

## 较大字体与候选数量（0.1.46）

字体库可导入展开总量不超过4 GiB的用户版或开发者版字体。“展开”是ZIP内所有成员的未压缩大小之和，不是磁盘上的压缩文件大小。32 MiB单成员、每候选100000点、100000成员及原协议/哈希/来源检查仍生效；写包时也会包含最终清单检查总量，超限不发布。不需要重新录制或自动改写旧字体；字体格式版本与应用版本独立。

实测user_001同字最多8份、包含相同英文/希腊/数学等字符的用户字体，全结构库范围约611 MB，简体支持范围约454 MB，磁盘体积减少约25.7%。简体指《通用规范汉字表》2013在当前结构库支持的6866字，不包含明确列出的1239个结构库缺字。两包均超过旧2 GiB展开限制，需要新程序；包变小不表示缺口警告已解除。具体数据与文件见[容量对照记录](FONT_CAPACITY_SIMPLIFIED_20261104.md)。

建议优先用“内置字表…”或“从文档提取汉字…”限制实际输出字集，供体池仍保持完整。导入字体后点击“用于当前文档…”检查实际影响，确认才替换本文资源；不自动更新旧文档的冻结选样。大字体能被读取不意味着任意大文档都可排版，项目和页面仍保留原有容量检查。

## 字体库与模板库

从主窗口左下分别打开“字体库”或“模板库”。单击查看，双击只查看详情；不会因浏览资源而更换本文。

字体页左侧可搜索、按书写者筛选和显示历史版本。右侧“预览”显示真实笔迹，缺字为红框；“字符”可按类别、字符或 `U+2218` 查找并逐份查看样本；“来源与版本”显示来源类别和具有相同字体身份的版本。最近文件只表示文件时间，不代表推荐版本。字体内容版本与应用版本独立。

点击“用于当前文档…”后检查试排页数、缺字、来源和需要重新选样的数量。确认才应用，之后可通过编辑菜单撤销或重做。保留核心记录、度量和来源相同的冻结样本；不兼容的样本会明确重新选择。检查期间文档或资源变化时，不应用旧结果。诊断不会因确认而消失，正式导出仍执行原检查。

“设为新文档默认”仅改变以后新建文档。“更多操作”可修改库内显示名称，或移出/恢复列表记录；不改字体文件，不删除现有文档的冻结资源。导出可选用户版或保留原包类型的完整副本，使用新的文件名；用户版保留核心笔迹与身份。

模板页提供缩略图、布局切换、起始/循环顺序和字段声明。导入时保存独立库内副本（含原模板内嵌背景），原文件保留；再次导入已变更的外部文件形成另一个条目，不自动更新已保存文档。旧的“最近文件”默认不混入模板库，可勾选“显示待入库的最近文件”，确认后加入；失效文件可重新定位。旧协议按原协议保存，迁移需使用明确的复制操作，不根据名称猜测字段。

“编辑模板…”打开工作台。“保存修改”更新所选模板，库内旧修订在“显示历史修订”中查看，待入库的最近文件则写回原 JSON。“另存为新模板”创建独立副本并加入模板库。“用于当前文档…”显示实际适配确认，并保留正文、字段原文和冻结选样。必填、未知字段、越框等问题继续显示。移出只隐藏库内条目，勾选“显示已移出模板”后可恢复。

排版右侧“元素属性 → 文档资源”负责本文：更换字体、编辑本文布局、更换本文模板、字段填写及适配报告。左下角设置仍是全局默认入口，其中模板库只提供跳转按钮；本文布局编辑不再藏在全局设置中。

## 目录

- [选择使用方式](#选择使用方式)
- [安装与环境准备](#安装与环境准备)
- [GUI 快速开始](#gui-快速开始)
- [CLI 快速开始](#cli-快速开始)
- [轨迹采集器](#轨迹采集器)
- [风格生成器](#风格生成器)
- [完整 CLI 工作流](#完整-cli-工作流)
- [训练与模型检查点](#训练与模型检查点)
- [可复现实验](#可复现实验)
- [Windows 便携采集器打包](#windows-便携采集器打包)
- [数据协议参考](#数据协议参考)
- [产物目录与文件用途](#产物目录与文件用途)
- [测试和代码检查](#测试和代码检查)
- [复现、备份与安全清理](#复现备份与安全清理)
- [故障排查](#故障排查)

## 选择使用方式

| 需求 | 推荐入口 | 所需依赖 |
| --- | --- | --- |
| 只生成轨迹，不使用图形界面 | `inkstruct generate` | 基础依赖，CPU 即可 |
| 从原始 JSON 建档并生成 | `samples import` → `profile build` → `generate` | 基础依赖，CPU 即可 |
| 使用图形界面导入和生成 | `run_inkstruct_generator.cmd` | `desktop` 可选依赖 |
| 在项目源码环境采集轨迹 | `run_inkstruct_collector.cmd` | `desktop` + 相邻 `data_collection` 内核 |
| 在另一台 Windows 机器采集 | `release/InkStructCollector/InkStructCollector.exe` | 使用完整便携目录，无需 Python |
| 训练实验模型 | `inkstruct train` | `train` 依赖、CUDA、NVIDIA GPU、CASIA LMDB |
| 复现预算、消融或盲评 | `inkstruct experiment ...` | 根据实验是否调用模型决定，通常需要开发依赖 |

最稳定的生产路径是不带 `--checkpoint` 的确定性生成。训练路径不是初次使用的前置条件。

## 安装与环境准备

### 系统要求

- Python 3.12 或 3.13；项目约束为 `>=3.12,<3.14`。
- Windows 10/11 是当前主要验证平台。
- 确定性生成、结构处理、采集、评估和大多数测试可使用 CPU。
- 源码桌面应用需要 PySide6 6.9.2 和 Matplotlib（v6.1 轮廓几何判断）；独立应用已包含依赖。
- 训练以及带 `--checkpoint` 的学习模型推理必须使用支持 CUDA 的 NVIDIA GPU；确定性生成不需要 GPU。
- 完整结构构建需要仓库中的 `third_party/makemeahanzi/graphics.txt` 与 `dictionary.txt`。

### 依赖组合

`pyproject.toml` 定义了以下安装组合：

| 组合 | 内容 | 使用场景 |
| --- | --- | --- |
| 基础 | NumPy、Pillow | 结构、导入、建档、确定性生成、SVG/PNG、评估 |
| `desktop` | PySide6 6.9.2、Matplotlib | 集成应用与生成参考修正 |
| `train` | PyTorch、h5py、lmdb | 模型训练、检查点推理、CASIA 数据 |
| `dev` | pytest、Ruff | 测试和代码检查 |

### Windows PowerShell 安装

创建独立虚拟环境并安装常用的桌面与开发能力：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[desktop,dev]"
```

只需要命令行和确定性生成时：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .
```

需要训练时，先按照本机显卡驱动和 CUDA 兼容情况安装合适的 PyTorch，再安装训练依赖：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[train,dev]"
```

仓库的 `requirements.lock` 记录了当前 Windows/CUDA 环境中的完整版本，但 CUDA 版 PyTorch 与显卡驱动强相关，不应在不同机器上盲目照搬。

### 通用 Python CLI 安装

在支持 Python 3.12/3.13 的类 Unix shell 中，可以使用：

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e .
```

之后可运行 `.venv/bin/inkstruct`。桌面端和 Windows 打包脚本没有在本文档中声明跨平台验收。

### `setup_windows.ps1` 的适用范围

`scripts/setup_windows.ps1` 是特定 Windows/CUDA 环境的重建脚本，会：

1. 使用 `venv --clear` 清空并重建 `.venv`；
2. 从 CUDA 12.8 索引安装 PyTorch；
3. 安装桌面、开发、h5py 和 lmdb 依赖；
4. 检查 CUDA；
5. 运行测试。

脚本默认 Python 路径是开发环境中的绝对路径。只有在确认要重建 `.venv` 后才使用，并显式传入本机 Python：

```powershell
.\scripts\setup_windows.ps1 -Python "C:\Path\To\python.exe"
```

### 环境验证

```powershell
.\.venv\Scripts\inkstruct.exe --version
.\.venv\Scripts\python.exe -c "import inkstruct, numpy, PIL; print('imports OK')"
.\.venv\Scripts\inkstruct.exe structures info
```

预期 CLI 版本为：

```text
InkStruct 0.2.0
```

`structures info` 成功时会输出结构 Schema、来源提交、字符数和部件回退数量。当前仓库的结构库包含 9,574 字。

检查桌面依赖：

```powershell
.\.venv\Scripts\python.exe -c "import PySide6; print(PySide6.__version__)"
```

检查训练环境：

```powershell
.\.venv\Scripts\python.exe -c "import torch; print(torch.__version__); print(torch.cuda.is_available()); print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CUDA unavailable')"
```

## GUI 快速开始

### 采集器

1. 确认 `artifacts/structures/characters.sqlite3` 存在。
2. 源码运行时确认以下任一采集器内核存在：
   - `legacy/data_collection/handwriting_collector/ui.py`；
   - 项目相邻的 `../data_collection/handwriting_collector/ui.py`。
3. 双击 `run_inkstruct_collector.cmd`。
4. 首次运行选择单独的数据输出目录。
5. 填写稳定的书写者 ID，例如 `user_001`。
6. 导入 TXT/CSV 字表，按提示书写并保存。

如果使用便携版，直接运行完整目录中的 `release/InkStructCollector/InkStructCollector.exe`，不要只复制 EXE。

### 生成器

1. 双击 `run_inkstruct_generator.cmd`。
2. 填写与采集时完全相同的用户 ID。
3. 选择采集输出目录下的 `samples/<writer-id>` 目录。
4. 依次点击“1. 导入”“2. 建档”“3. 生成”。
5. 默认选择“v6.2 exp（推荐）”，另可选择“v6.1 exp”或“v4 adaptive”；在v6.2下按需设置“每字成品上限”（1–64，默认4）。
6. 在统一应用的生成结果处点击“制作字体…”，另存字体并在“字体库”中用于当前文档。

导入、建档和生成在后台线程执行，日志显示完成数与记录位置。全库生成可以取消，当前字完成后停止；每次操作新建批次，保留旧数据。应用暂不提供断点续跑入口。

## CLI 快速开始

以下示例假设原始单字 JSON 位于 `D:\Handwriting\samples\user_001`。

### 1. 检查结构库

```powershell
.\.venv\Scripts\inkstruct.exe structures info
```

如果数据库不存在，可重建：

```powershell
.\.venv\Scripts\inkstruct.exe structures build
```

### 2. 导入样本

```powershell
.\.venv\Scripts\inkstruct.exe samples import `
  "D:\Handwriting\samples\user_001" `
  --writer user_001
```

查看命令输出中的 `accepted_count`、`rejected_count` 和 `rejected`，不要在存在大量拒绝样本时直接建档。

### 3. 建立风格档案

```powershell
.\.venv\Scripts\inkstruct.exe profile build --writer user_001
```

默认读取：

```text
artifacts/samples/user_001/index.jsonl
```

默认生成：

```text
profiles/user_001/<profile-version>.json
profiles/user_001/profile.json
```

### 4. 生成文本

```powershell
.\.venv\Scripts\inkstruct.exe generate `
  --writer user_001 `
  --text "墨构手写" `
  --run-id quick_start
```

结果位于：

```text
outputs/user_001/quick_start/
```

### 5. 检查结果

```powershell
.\.venv\Scripts\inkstruct.exe evaluate `
  --run outputs\user_001\quick_start
```

成功生成目录仍应检查 `manifest.json` 中的 `failed_count`，评估目录还会新增 `evaluation.json`。

## 轨迹采集器

### 源码版和便携版区别

| 项目 | 源码版 | Windows 便携版 |
| --- | --- | --- |
| 启动 | `run_inkstruct_collector.cmd` 或 `inkstruct collector` | `InkStructCollector.exe` |
| Python/PySide6 | 需要 | 已打包 |
| `data_collection` 源码 | 需要 | 不需要 |
| 结构数据库 | 从项目 `artifacts/structures` 读取 | 使用打包的压缩笔数/笔顺参考 |
| PyTorch/CUDA | 不需要 | 不包含 |
| 生成器 | 另行启动 | 不包含 |
| 推荐用途 | 开发和联调 | 在采集机器上分发使用 |

便携版采用 PyInstaller `onedir`，`_internal` 和其他随附文件是运行所必需的。整体复制 `InkStructCollector` 文件夹，不要只发送 EXE。

### 字表格式

采集器的“单字任务采集”支持 UTF-8/UTF-8 BOM 的 TXT 和 CSV。

#### TXT

TXT 中每个非空白 CJK 统一汉字会成为一个任务项，重复字符只保留首次出现。示例：

```text
中国书法
墨构永和
```

标点、拉丁字母或其他非 CJK 字符会导致导入错误，不会被静默忽略。

#### CSV

CSV 必须包含 `character` 列，可选 `repeats` 列。额外列会被忽略，因此补采推荐 CSV 可以直接导入。

```csv
character,repeats,purpose,reason
永,3,anchor,稳定性锚点
构,2,coverage,补充部件覆盖
```

规则如下：

- `character` 必须恰好是一个 CJK 统一汉字；
- `repeats` 留空时使用导入对话框中的默认重复次数；
- `repeats` 必须是大于等于 1 的整数；
- 同一字符只接受 CSV 中第一次出现的记录。

### 书写和保存流程

1. 首次运行选择输出根目录。建议使用专用数据目录，不要选择程序目录或便携版 `_internal`。
2. 选择或新建书写者；显示名称可修改，内部 ID 不随名称变化。旧书写者保持原 ID。零样本任务可明确确认更换书写者；有样本或复用关系时须暂停后新建，或复制未录部分。
3. 点击“导入 TXT / CSV”，在集中确认窗口检查作者、名称、字符、份数及目录，再创建。CSV 明确份数保留，空值默认五份；冲突重复行报错。
4. 在田字格中按标准笔顺书写当前字。
5. 左侧参考图显示标准笔画：
   - 正在落笔时，绿色表示当前笔；
   - 抬笔等待时，绿色表示下一笔；
   - 已完成笔画为深灰色，后续笔画为浅灰色；
   - 绿色圆点表示参考起笔位置。
6. 确认“当前笔数 / 标准笔数”为正确状态。
7. 点击“保存并下一个”或按 Enter。

常用操作：

| 操作 | 按钮 | 快捷键 |
| --- | --- | --- |
| 撤销上一笔 | 撤销上一笔 | `Ctrl+Z` |
| 清空当前字符 | 重写当前字 | `Delete` |
| 保存并进入下一项 | 保存并下一个 | `Enter` |
| 暂不采集当前项 | 暂时跳过 | 无默认快捷键 |

笔画数不匹配、字符不在结构库或没有有效轨迹时，保存按钮不可用或保存操作会被拒绝。笔顺参考只提供视觉提示，不会修改坐标、压力或时间。

### 任务恢复

采集器将任务状态写入输出目录的 `tasks/<task-id>/state.json`。重新启动后可点击“继续未完成任务”。如果样本已完成原子写入但任务状态尚未更新，恢复过程会根据样本中的 `task_id` 和 `item_id` 调和进度。

请始终使用同一输出根目录恢复任务。换目录会看到另一组任务状态。

### 采集输出

单字 JSON 路径为：

```text
<输出目录>/samples/<writer-id>/U+XXXX/<sample-id>.json
```

采集内核还会生成兼容旧工具的 `legacy/` 产物。InkStruct 的 `samples import` 只需要 `handwriting_single_v1` JSON，不要求旧格式文件。

```text
<输出目录>/
├─ tasks/<task-id>/state.json
├─ samples/<writer-id>/U+XXXX/<sample-id>.json
├─ legacy/<writer-id>/<sample-id>.npy
└─ legacy/<writer-id>/<sample-id>/
   ├─ point_seq.txt
   ├─ line_text.txt
   ├─ char_points_idx.txt
   └─ writer_id.txt
```

### 关于整行采集标签页

底层 `data_collection` 内核还提供整行采集和 DiffInk HDF5 导出。整行原始协议是 `handwriting_line_raw_v1`，不是 InkStruct `samples import` 当前接受的 `handwriting_single_v1`。如果目标是建立 InkStruct 个人风格档案，请使用“单字任务采集”标签页。

## 风格生成器

### 启动

```powershell
.\run_inkstruct_generator.cmd
```

或：

```powershell
.\.venv\Scripts\inkstruct.exe generator
```

`inkstruct desktop` 是兼容旧调用的弃用别名，新的脚本和文档应使用 `generator`。

### 界面字段与三步工作流

| 字段 | 说明 |
| --- | --- |
| 作者 | 与原始采集 JSON 的 writer_id 一致 |
| 样本目录 | 该作者的汉字采集目录，递归扫描 JSON |
| 生成方式 | v6.2 exp（推荐，默认）、v6.1 exp或v4 adaptive |
| 每字成品上限 | v6.2可选1–64份，默认4，包含原主字形；其他方法固定1份 |
| 生成内容 | 输入汉字，重复字符去重 |
| 内置字表 · 结构库全部汉字 | 使用当前库支持的完整范围，可取消并保留完成部分 |

依次点击“1. 导入”“2. 建档”“3. 生成”。前一步未准备好时按钮禁用，并提示下一步；切换方法后需要该方法对应的档案。“建档”统一准备档案，v6.1 自动保留完整来源点列与映射，无需另建副档案。新增采集后请重新导入和建档。

统一应用的数据位于用户工作区的 `generation/imports`、`generation/profiles`、`generation/outputs`；每次使用新批次。v6.1 采用已验证的修正参考、完整部件、禁止拆分、位置变体、受限羊关键笔替换和作者单笔回退，保留逐笔来源与缺口；沿用同字供体排除规则。v4 固定 adaptive、强度 1.0、legacy 路径，保留实际引擎记录，无法证明逐笔来源时按未知提示。

结果通过“最近生成 → 字体库”制作字体。含参考替代的有效字可使用，应用按实际使用字符汇总警告；非有限或损坏轨迹不能放行。错误区显示简短原因，异常诊断另存文件。界面没有神经生成、训练、CUDA 检测或 PyTorch 缺失提示；下面的研究 CLI 参数仍可在独立环境中使用。

## 完整 CLI 工作流

### 调用方式和通用规则

Windows 安装入口：

```powershell
.\.venv\Scripts\inkstruct.exe --help
```

等价模块入口：

```powershell
.\.venv\Scripts\python.exe -m inkstruct.cli --help
```

常用规则：

- 相对路径按当前工作目录解析；建议始终从项目根目录运行。
- 包含空格或非 ASCII 字符的路径必须加引号。
- Windows PowerShell 使用反引号 `` ` `` 续行，反引号后不能再有空格。
- 所有主要命令把结果以 UTF-8 JSON 输出到终端。
- `generate` 有任何目标失败时返回退出码 2；`evaluate` 有结构失败时返回退出码 2。
- argparse 参数错误也返回 2；未捕获的文件、数据或运行时异常返回非零状态并显示错误。

### 结构库：`structures`

#### `structures build`

```powershell
.\.venv\Scripts\inkstruct.exe structures build
```

| 参数 | 必需 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `--graphics` | 否 | `third_party/makemeahanzi/graphics.txt` | 标准笔画中心线 JSONL |
| `--dictionary` | 否 | `third_party/makemeahanzi/dictionary.txt` | 字典和 IDS 信息 JSONL |
| `--database` | 否 | `artifacts/structures/characters.sqlite3` | 输出 SQLite 数据库 |
| `--simplified` | 否 | `data/CASIA_CHINESE/character_dict.pkl` | 可选简体字符集合；路径不存在时按空集合处理 |

构建采用 `.building` 临时数据库并在成功后原子替换目标。数据库同目录还会写入：

- `build_report.json`：接受/拒绝数量和来源许可；
- `component_fallback_report.json`：部件拆分不完整、需要回退的字符。

自定义输入示例：

```powershell
.\.venv\Scripts\inkstruct.exe structures build `
  --graphics "D:\Data\makemeahanzi\graphics.txt" `
  --dictionary "D:\Data\makemeahanzi\dictionary.txt" `
  --database artifacts\structures\custom.sqlite3
```

#### `structures info`

```powershell
.\.venv\Scripts\inkstruct.exe structures info
```

| 参数 | 必需 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `--database` | 否 | `artifacts/structures/characters.sqlite3` | 要检查的数据库 |

输出包括 Schema、创建时间、数据来源、来源版本、坐标系、完整/回退部件数量和字符总数。

#### `structures export-packages`

```powershell
.\.venv\Scripts\inkstruct.exe structures export-packages `
  --output-dir configs\character_packages
```

| 参数 | 必需 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `--database` | 否 | 默认结构数据库 | 输入数据库 |
| `--output-dir` | 是 | 无 | 输出目录 |

输出两份 UTF-8 BOM CSV 和一份报告：

- `mainland_standard_simplified_gb2312_characters.csv`；
- `non_mainland_standard_simplified_characters.csv`；
- `character_packages_report.json`。

CSV 字段包括 `character`、`codepoint`、`package`、`locale`、`stroke_count`、`component_status` 和 `decomposition`。

### 样本：`samples`

#### `samples import`

```powershell
.\.venv\Scripts\inkstruct.exe samples import `
  "D:\Handwriting\samples\user_001" `
  --writer user_001
```

| 参数 | 必需 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `source` | 是 | 无 | 递归扫描 `.json` 的目录 |
| `--writer` | 是 | 无 | 期望的书写者 ID |
| `--destination` | 否 | `artifacts/samples` | 索引根目录 |

输出位于 `<destination>/<writer-id>/index.jsonl` 和 `import_report.json`。导入器不复制源文件。拒绝原因可能包括 Schema 不支持、writer 不一致、字符不是单个 Unicode 字符、画布非法、空笔画、越界坐标、压力越界或时间戳不单调。

#### `samples merge`

```powershell
.\.venv\Scripts\inkstruct.exe samples merge `
  artifacts\samples_batch_1\user_001\index.jsonl `
  artifacts\samples_batch_2\user_001\index.jsonl `
  --writer user_001
```

| 参数 | 必需 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `indexes` | 是，至少两个 | 无 | 要合并的一个或多个索引参数；实现要求至少两个 |
| `--writer` | 是 | 无 | 所有样本必须匹配的 writer |
| `--destination` | 否 | `artifacts/samples_merged` | 新索引根目录 |

合并先按 `sample_id`，再按源文件 SHA-256 去重。同 ID 同内容记为重复；同 ID 不同内容记为冲突并省略后到样本，不会覆盖。输出 `index.jsonl` 和 `merge_report.json`，源索引保持不变。

#### `samples audit`

```powershell
.\.venv\Scripts\inkstruct.exe samples audit --writer user_001
```

| 参数 | 必需 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `--writer` | 是 | 无 | 书写者 ID |
| `--index` | 否 | `artifacts/samples/<writer>/index.jsonl` | 待检查索引 |
| `--database` | 否 | 默认结构数据库 | 标准结构来源 |
| `--confidence-threshold` | 否 | `0.5` | `[0,1]` 内的对齐置信阈值 |
| `--output` | 否 | `artifacts/collection/<writer>/rerecord_current.csv` | 重录 CSV |

审计识别：

- 结构库不支持的字符；
- 笔画数不匹配；
- 低置信对齐；
- 证据不足的疑似错序；
- 已被高置信纠正的笔顺排列。

输出 CSV 可直接导入采集器；同目录还会写同名 `.json` 报告。`corrected` 样本会单独列入报告，但不一定要求重录；`ambiguous` 样本会进入重录任务并从局部档案抽取中隔离。

#### `samples replace`

重录完成后，先将新 JSON 导入为一个独立替换索引，再根据旧审计报告创建新修订索引：

```powershell
.\.venv\Scripts\inkstruct.exe samples replace `
  artifacts\samples\user_001\index.jsonl `
  artifacts\replacement_samples\user_001\index.jsonl `
  --writer user_001 `
  --audit-report artifacts\collection\user_001\rerecord_current.json
```

| 参数 | 必需 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `index` | 是 | 无 | 原索引 |
| `replacement_index` | 是 | 无 | 已验证的新样本索引 |
| `--writer` | 是 | 无 | 书写者 ID |
| `--audit-report` | 是 | 无 | `samples audit` 生成的 JSON |
| `--destination` | 否 | `artifacts/samples_revised` | 新修订索引根目录 |

命令从审计报告的 `source_sample_ids` 得到被替换 ID，保留其他样本并加入替换索引。源索引不修改。ID 冲突、payload 重复或空替换集合会报错。

### 风格档案：`profile build`

```powershell
.\.venv\Scripts\inkstruct.exe profile build --writer user_001
```

| 参数 | 必需 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `--writer` | 是 | 无 | 书写者 ID |
| `--index` | 否 | `artifacts/samples/<writer>/index.jsonl` | 输入索引 |
| `--database` | 否 | 默认结构数据库 | 结构来源 |
| `--destination` | 否 | `profiles` | 档案根目录 |
| `--style-checkpoint` | 否 | 无 | 可选的因子化风格编码器检查点 |

默认输出：

```text
profiles/<writer-id>/<profile-version>.json
profiles/<writer-id>/profile.json
```

版本文件只在不存在时写入；`profile.json` 原子更新为当前档案。没有 `--style-checkpoint` 时为 `style_profile_v4`；成功加入因子化风格时为 `style_profile_v5`。终端摘要包含样本、字符、各类原型、排除样本和因子化风格状态。

使用合并索引：

```powershell
.\.venv\Scripts\inkstruct.exe profile build `
  --writer user_001 `
  --index artifacts\samples_merged\user_001\index.jsonl
```

每次换索引、结构库或风格检查点后都应重新建档，并为后续生成使用新的 run ID。

### 主动补采：`collect`

#### `collect recommend`

```powershell
.\.venv\Scripts\inkstruct.exe collect recommend `
  --writer user_001 `
  --count 200
```

| 参数 | 必需 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `--writer` | 是 | 无 | 书写者 ID |
| `--count` | 否 | `10` | 推荐新字符数 |
| `--anchors` | 否 | `20` | 现有稳定性锚点数量 |
| `--target-repeats` | 否 | `3` | 锚点目标重复次数 |
| `--index` | 否 | 默认样本索引 | 已采样字符来源 |
| `--profile` | 否 | `profiles/<writer>/profile.json` | 当前档案 |
| `--common-characters` | 否 | 包内常用字表 | 候选字符池 |
| `--database` | 否 | 默认结构数据库 | 部件频数和结构来源 |
| `--output` | 否 | `artifacts/collection/<writer>/recommendations.json` | JSON 报告路径 |
| `--strategy` | 否 | `coverage` | `coverage` 或 `information-gain` |

输出：

- `recommendations.json`：完整审计报告；
- `component_collection.csv`：可直接导入采集器；
- `component_characters.txt`：仅新字符文本。

`coverage` 主要补充部件身份、变体、角色和布局缺口；`information-gain` 适合可复现实验中的信息增益选择。推荐分数是假设新样本成功对齐并进入档案后的估计，实际采集后仍需重新导入、建档和评估。

#### `collect coverage-tiers`

```powershell
.\.venv\Scripts\inkstruct.exe collect coverage-tiers `
  --writer user_001 `
  --index artifacts\samples_merged\user_001\index.jsonl
```

| 参数 | 必需 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `--writer` | 是 | 无 | 书写者 ID |
| `--index` | 是 | 无 | 当前样本索引 |
| `--profile` | 否 | `profiles/<writer>/profile.json` | 当前档案 |
| `--target-characters` | 否 | 全部支持字符 | UTF-8 字符文本，空白忽略、按首次出现去重 |
| `--target-package` | 否 | 无 | `mainland_standard_simplified_gb2312` 或 `non_mainland_standard_simplified` |
| `--database` | 否 | 默认结构数据库 | 目标结构集合 |
| `--output` | 否 | 见下文 | JSON 报告路径 |

`--target-characters` 与 `--target-package` 互斥。未指定目标时针对全部支持字符。默认报告路径：

```text
artifacts/collection/<writer>/<target-package-or-all_supported>/target_coverage_tiers_report.json
```

命令生成：

- `target_coverage_tiers.csv`：包含所有档位归属的审计总表；
- `tier_1_to_90_0.csv`；
- `tier_2_to_95_0.csv`；
- `tier_3_to_99_0.csv`；
- `tier_4_to_99_9.csv`；
- `tier_5_to_100_0.csv`；
- `target_coverage_tiers_report.json`。

五份档位 CSV 是增量任务并兼容采集器。若只规划大陆标准简体，先导出字符包或直接使用：

```powershell
.\.venv\Scripts\inkstruct.exe collect coverage-tiers `
  --writer user_001 `
  --index artifacts\samples_merged\user_001\index.jsonl `
  --target-package mainland_standard_simplified_gb2312
```

### 生成：`generate`

指定文本和全部字符必须二选一：

```powershell
.\.venv\Scripts\inkstruct.exe generate --writer user_001 --text "中国书法"
.\.venv\Scripts\inkstruct.exe generate --writer user_001 --all-supported --run-id all_supported
```

| 参数 | 必需 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `--writer` | 是 | 无 | 书写者 ID |
| `--text` | 二选一 | 无 | 按 Unicode 字符逐个请求；重复项去重 |
| `--all-supported` | 二选一 | 关闭 | 生成结构库全部字符 |
| `--profile` | 否 | `profiles/<writer>/profile.json` | 档案文件 |
| `--database` | 否 | 默认结构数据库 | 结构来源 |
| `--output-root` | 否 | `outputs` | 生成根目录 |
| `--run-id` | 否 | UTC 时间戳加 8 位随机串 | 运行目录标识和续跑身份 |
| `--no-png` | 否 | 关闭 | 不输出 PNG；SVG 和轨迹 JSON 仍生成 |
| `--checkpoint` | 否 | 无 | v5 模型检查点，需要 `train` 依赖和 CUDA；不指定时使用确定性生成 |
| `--confidence-threshold` | 否 | 检查点校准值或安全默认 | 覆盖 writer-disjoint 校准阈值 |
| `--no-component-conditioning` | 否 | 关闭 | 兼容开关，等价于部件模式 `off` |
| `--component-mode` | 否 | `adaptive` | `off`、`stroke`、`layout`、`full`、`adaptive` |
| `--component-strength` | 否 | `1.0` | 部件影响强度；CLI 不额外限制范围 |

`--no-component-conditioning` 与 `--component-mode` 同时出现时，前者优先并强制使用 `off`。

推荐的文本生成：

```powershell
.\.venv\Scripts\inkstruct.exe generate `
  --writer user_001 `
  --text "墨构个性手写" `
  --component-mode adaptive `
  --component-strength 1.0 `
  --run-id document_demo
```

节省全量输出空间：

```powershell
.\.venv\Scripts\inkstruct.exe generate `
  --writer user_001 `
  --all-supported `
  --run-id all_supported_json_svg `
  --no-png
```

运行目录始终包含 `manifest.json`、`trajectories/` 和 `previews/`。未知字符记录在 manifest 的 `failed` 中，命令返回 2；不会替换为问号或形近字。

#### 取消和断点续跑

CLI 没有专用取消参数，可使用正常终止信号停止。再次以相同 `--writer`、`--output-root` 和 `--run-id` 运行时，已经存在的轨迹 JSON 会被跳过。

```powershell
.\.venv\Scripts\inkstruct.exe generate `
  --writer user_001 `
  --all-supported `
  --run-id all_supported
```

生成器会自动比较 `run_identity` 中的档案、结构库和模型 SHA-256，以及部件模式、强度、置信阈值、PNG 选项和边界策略。改变这些身份需要新 run ID；边界修复前的旧 manifest 也不能直接续跑。旧目录应保留用于对照。

#### 使用模型检查点

```powershell
.\.venv\Scripts\inkstruct.exe generate `
  --writer user_001 `
  --text "中国书法" `
  --checkpoint artifacts\models\v5_formal_seed2002.pt
```

检查每个轨迹的 `generator` 字段和 manifest。可能值包括模型生成、低置信确定性回退或未正式训练检查点回退。仅传入检查点不等于模型一定接管生成。

### 评估：`evaluate`

`--run` 与 `--writer` 必须二选一。

#### 结构评估

```powershell
.\.venv\Scripts\inkstruct.exe evaluate `
  --run outputs\user_001\document_demo
```

检查：

- 笔数和连续笔顺；
- 标准笔画 ID；
- 每笔最少点数；
- `[0,1]` 坐标和压力；
- 时间单调性；
- manifest 请求数、生成失败数和结构覆盖。

结果写入运行目录的 `evaluation.json`。`content_safety_passed=true` 要求无结构失败、无生成失败且检查数等于请求数。

#### 书写者留出评估

```powershell
.\.venv\Scripts\inkstruct.exe evaluate `
  --writer user_001 `
  --heldout-ratio 0.2
```

评估按字符留出，不会把同一字符的重复样本同时分到训练和隐藏集合。它临时构建训练索引、档案和隐藏字符生成，并比较标准骨架与个性化轨迹的几何距离。

| 参数 | 必需 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `--run` | 二选一 | 无 | 已生成运行目录 |
| `--writer` | 二选一 | 无 | 执行书写者评估或档案更新对比 |
| `--database` | 否 | 默认结构数据库 | 结构来源 |
| `--index` | 否 | 默认样本索引 | writer 模式输入 |
| `--heldout-ratio` | 否 | `0.2` | 允许范围 0.1–0.4 |
| `--checkpoint` | 否 | 无 | 查询生成使用的模型检查点 |
| `--style-checkpoint` | 否 | 无 | 可选 writer-disjoint 风格编码器，用于风格指标 |
| `--model-confidence-threshold` | 否 | 检查点校准值 | 模型门控阈值 |
| `--update-index` | 否 | 无 | 新增样本索引；必须和 `--reference-profile` 同时使用 |
| `--reference-profile` | 否 | 无 | 更新前档案；必须和 `--update-index` 同时使用 |
| `--heldout-count` | 否 | `12` | 档案更新对比的隐藏新字符数 |
| `--no-component-conditioning` | 否 | 关闭 | 等价部件模式 `off` |
| `--component-mode` | 否 | `adaptive` | 与生成相同的五种模式 |
| `--component-strength` | 否 | `1.0` | 部件影响强度 |
| `--output-root` | 否 | `artifacts/evaluation` | writer 评估输出根目录 |

默认 writer 评估输出：

```text
artifacts/evaluation/<writer-id>/
├─ train_index.jsonl
├─ profiles/<writer-id>/...
├─ outputs/<writer-id>/heldout/...
└─ evaluation.json
```

#### 档案更新对比

用于判断新采字符是否改善对未用于建档的新字符的迁移：

```powershell
.\.venv\Scripts\inkstruct.exe evaluate `
  --writer user_001 `
  --index artifacts\samples\user_001\index.jsonl `
  --update-index artifacts\samples_new\user_001\index.jsonl `
  --reference-profile profiles\user_001\profile.json `
  --heldout-count 12
```

`--update-index` 和 `--reference-profile` 必须一起出现。输出到 `artifacts/evaluation/<writer>/component_sample_update/`，包括旧/新生成结果、`comparison.json` 和 `comparison.png`。

### 桌面入口

| 命令 | 说明 |
| --- | --- |
| `inkstruct collector` | 启动独立采集器 |
| `inkstruct generator` | 启动独立风格生成器 |
| `inkstruct desktop` | 已弃用的生成器别名 |

这三个组把未知参数转发给对应桌面入口。`--smoke-test` 和 `--smoke-screenshot=<path>` 是开发测试参数，不属于普通用户操作界面。

## 训练与模型检查点

训练不是确定性生成的前置条件。只有在研究 v5 分层残差模型、需要验证检查点推理或复现实验时才安装训练依赖。

### 前置条件

1. NVIDIA CUDA 可用，`torch.cuda.is_available()` 返回 `True`；
2. `data/CASIA_CHINESE/train` 和 `data/CASIA_CHINESE/test` 是可读取的 CASIA LMDB；
3. `artifacts/structures/characters.sqlite3` 已构建；
4. 正式训练使用干净的 Git 工作树；
5. 训练与测试 LMDB 中不能出现相同 writer，否则程序会拒绝 writer 泄漏。

CASIA 数据不会随项目分发。请自行确认数据授权、预处理和 LMDB 内容。

### Smoke test

Smoke test 只运行一个优化步骤，用于验证数据、CUDA、前后向和保存链路：

```powershell
.\.venv\Scripts\inkstruct.exe train `
  --casia-lmdb data\CASIA_CHINESE\train `
  --test-lmdb data\CASIA_CHINESE\test `
  --database artifacts\structures\characters.sqlite3 `
  --output artifacts\models\hierarchical_residual_smoke.pt `
  --smoke
```

Smoke 检查点的 `training_status` 为 `smoke`。在正常置信阈值下，它会触发确定性回退，不能作为正式质量结论。

### 正式训练脚本

仓库提供固定三种子脚本：

```powershell
.\scripts\train_v5_formal.ps1
```

默认种子为 `1001`、`2002` 和 `3003`。指定部分种子：

```powershell
.\scripts\train_v5_formal.ps1 -Seeds 2002,3003
```

脚本的协议配置镜像位于 `configs/training/v5_formal.json`。正式脚本使用 10,000 步、batch size 8、每个 episode 8 个参考、固定 writer split、早停、置信校准、refiner、因子化风格和多尺度曲线/SDF 辅助损失。

### `train` 参数

```powershell
.\.venv\Scripts\inkstruct.exe train --help
```

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--casia-lmdb` | `data/CASIA_CHINESE/train` | 训练 LMDB |
| `--database` | `artifacts/structures/characters.sqlite3` | 结构数据库 |
| `--output` | `artifacts/models/hierarchical_residual.pt` | 最佳检查点 |
| `--steps` | `10000` | 目标训练步数；`--smoke` 时实际为 1 |
| `--batch-size` | `8` | episode batch size |
| `--max-records` | `50000` | 每个 CASIA corpus 最大读取记录数 |
| `--references` | `8` | 每个 writer episode 的参考数量 |
| `--learning-rate` | `0.0002` | AdamW 学习率 |
| `--seed` | `1001` | 训练和组批随机种子 |
| `--split-seed` | `1001` | writer 训练/验证划分种子 |
| `--resume` | 无 | 要恢复的检查点 |
| `--allow-resume-config-change` | 关闭 | 允许恢复时更改受保护配置，仅用于明确诊断 |
| `--allow-dirty` | 关闭 | 允许脏工作树上的非 smoke 训练；正式报告不得使用 |
| `--save-every` | `100` | 保存 last 检查点间隔 |
| `--validate-every` | `100` | 验证间隔，必须大于 0 |
| `--validation-episodes` | `128` | 每次验证 episode 数，必须大于 0 |
| `--early-stop-patience` | `10` | 无改善验证轮数容忍值 |
| `--early-stop-min-delta` | `0.0001` | 计为改善的最小差异 |
| `--last-output` | `<output-stem>.last<suffix>` | 最新状态检查点；不指定时从 `--output` 推导 |
| `--refiner` | 关闭 | 启用上下文 refinement |
| `--factorized-style` | 关闭 | 启用 writer-disjoint 因子化风格表示 |
| `--curve-loss-weight` | `0.0` | 曲线辅助损失权重 |
| `--sdf-loss-weight` | `0.0` | 多尺度 SDF 损失权重 |
| `--render-sizes` | `32,64` | 逗号分隔的软渲染尺寸 |
| `--validation-fraction` | `0.1` | 从训练 LMDB 按 writer 划分的验证比例 |
| `--calibrate-episodes` | `128` | 置信阈值校准 episode 数 |
| `--test-lmdb` | `data/CASIA_CHINESE/test` | 独立测试 LMDB |
| `--smoke` | 关闭 | 只运行一个优化步骤 |

### 恢复训练

```powershell
.\.venv\Scripts\inkstruct.exe train `
  --resume artifacts\models\v5_formal_seed2002.last.pt `
  --output artifacts\models\v5_formal_seed2002.pt `
  --steps 10000 `
  --seed 2002 `
  --split-seed 1001 `
  --refiner `
  --factorized-style
```

恢复会读取模型、优化器、步数、历史和随机状态。参数不兼容时默认拒绝；不要为了“让它跑起来”随意使用 `--allow-resume-config-change`，否则报告中的运行身份可能失去可比性。

### 训练输出

假设 `--output artifacts/models/model.pt`，训练会产生：

```text
artifacts/models/
├─ model.pt               最佳验证检查点
├─ model.last.pt          最新训练状态检查点
└─ model.training.json    训练报告
```

训练报告 `training_report_v1` 包含最佳/最终步数、验证值、早停状态、校准阈值、耗时、Git 信息、配置摘要、数据索引摘要、结构版本和完整历史。

### 检查点生产资格

检查点是否由模型接管生成由两个条件决定：

1. `training_status` 必须是 `formal`；
2. 推理平均置信度必须达到检查点校准阈值或显式覆盖阈值。

否则轨迹 `generator` 会标明：

- `deterministic_fallback_untrained_checkpoint`；或
- `deterministic_fallback_low_model_confidence`。

`--confidence-threshold 0` 适用于诊断完整模型推理链路，会削弱保护，不应作为生产资格证明。

## 可复现实验

实验入口：

```powershell
.\.venv\Scripts\inkstruct.exe experiment --help
```

`budget-sweep` 和 `ablate` 默认要求干净工作树，并把 Git、配置 SHA-256、索引 SHA-256、结构版本、Python、NumPy、PyTorch和 GPU 信息写入报告。`--allow-dirty` 只适合 smoke/诊断。

### 预算扫描：`budget-sweep`

```powershell
.\.venv\Scripts\inkstruct.exe experiment budget-sweep `
  --config configs\experiments\v5_budget_smoke_user001.json `
  --allow-dirty
```

| 参数 | 必需 | 说明 |
| --- | --- | --- |
| `--config` | 是 | JSON 实验配置 |
| `--allow-dirty` | 否 | 允许脏工作树，只用于 smoke |

典型配置：

```json
{
  "schema_version": "experiment_config_v1",
  "writer_id": "user_001",
  "index": "artifacts/samples_merged/user_001/index.jsonl",
  "database": "artifacts/structures/characters.sqlite3",
  "output_root": "artifacts/experiments/budget_demo",
  "seed": 1001,
  "folds": 5,
  "fold_indices": [0],
  "budgets": [8, 16, 32, "all_train"],
  "strategies": ["random", "coverage", "information-gain"],
  "random_seeds": [1001],
  "sweet_spot_strategy": "information-gain",
  "component_mode": "adaptive",
  "component_strength": 1.0
}
```

默认预算集合为 `8, 16, 24, 32, 48, 64, 96, 128, 192, all_train`，默认策略为 `random`、`coverage` 和 `information-gain`。fold 按字符分组并对布局、笔画数分层，重复字符不会跨训练/留出边界。

输出根目录包含各 fold/策略/种子/预算的临时索引和评估结果，以及 `budget_sweep_report.json`。`sweet_spot` 是配置指定策略的预算收益拐点摘要。

### 固定消融：`ablate`

```powershell
.\.venv\Scripts\inkstruct.exe experiment ablate `
  --config configs\experiments\v5_ablation_user001.json `
  --allow-dirty
```

| 参数 | 必需 | 说明 |
| --- | --- | --- |
| `--config` | 是 | 定义 writer、索引、结构库、输出和 variants |
| `--allow-dirty` | 否 | 允许脏工作树，只用于诊断 |

示例 variants：

```json
{
  "variants": [
    {"name": "skeleton", "generation": "skeleton", "component_mode": "off"},
    {"name": "v4_component_off", "component_mode": "off"},
    {"name": "v4_adaptive", "component_mode": "adaptive"},
    {"name": "v5_candidate", "component_mode": "adaptive", "checkpoint": "artifacts/models/v5.pt"}
  ]
}
```

`enabled: false` 可跳过某个 variant。输出 `ablation_report.json`，并为每个 variant 保存同一固定留出集合上的评估结果和分层摘要。

### 生成盲评包：`blind-pack`

先为同一 writer 和字符集合准备两个完整运行目录，再创建配置：

```json
{
  "schema_version": "experiment_config_v1",
  "index": "artifacts/samples_merged/user_001/index.jsonl",
  "database": "artifacts/structures/characters.sqlite3",
  "run_a": "outputs/user_001/v4_comparison",
  "run_b": "outputs/user_001/v5_comparison",
  "output_root": "artifacts/experiments/blind_pack",
  "count": 60,
  "seed": 1001,
  "method_a": "ComponentTrajectory v4 adaptive",
  "method_b": "InkStruct v5 candidate"
}
```

运行：

```powershell
.\.venv\Scripts\inkstruct.exe experiment blind-pack `
  --config configs\experiments\v5_blind_template.json
```

`blind-pack` 不接受 `--allow-dirty`。它从索引中选择同时存在于 A/B 运行的字符，按结构分层抽样，随机交换左右位置，输出：

```text
<output_root>/
├─ items/item_001.png ...
├─ blind_key.json
├─ ratings.csv
└─ manifest.json
```

每张图按“用户风格参考、左候选、右候选”排列。`blind_key.json` 含解盲信息，不应发给评分者；评分者只需要 `items/` 和自己的 `ratings.csv` 副本。

### 盲评填写和计分：`blind-score`

`ratings.csv` 列为：

```csv
rater_id,item_id,style_choice,overall_choice,notes
reviewer_01,item_001,L,R,
reviewer_01,item_002,TIE,L,
```

`style_choice` 和 `overall_choice` 接受 `L`、`R` 或 `TIE`，不区分大小写。每位评分者应使用稳定且唯一的 `rater_id`，不要共享同一 ID。

```powershell
.\.venv\Scripts\inkstruct.exe experiment blind-score `
  --pack artifacts\experiments\blind_pack `
  --ratings ratings\reviewer_01.csv ratings\reviewer_02.csv ratings\reviewer_03.csv `
  --seed 1001
```

| 参数 | 必需 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `--pack` | 是 | 无 | 含 `blind_key.json` 的盲评包目录 |
| `--ratings` | 是 | 无 | 一个或多个评分 CSV |
| `--seed` | 否 | `1001` | bootstrap 置信区间种子 |

每个条目至少需要 3 个独立 rater 才进入正式统计；不足时报告状态为探索性。结果写入 `rating_summary.json`，包括方法 B 偏好率、95% bootstrap 区间、选择计数和生产门槛状态。

## Windows 便携采集器打包

### 前置条件

- Windows x64；
- `.venv` 中已安装 PySide6 和 PyInstaller；
- 项目相邻目录 `../data_collection/handwriting_collector/ui.py` 存在；
- `artifacts/structures/characters.sqlite3` 已构建；
- 默认脚本还要求 `artifacts/collection/user_001/rerecord_current.csv` 存在；
- 当前 Python 基础环境提供脚本列出的 Conda `Library/bin` DLL。

`build_portable_collector.ps1` 包含具体 Conda DLL 名称，因此不是通用 Python/Windows 打包模板。在不同 Python 发行版上使用前应先审查脚本。

PyInstaller 不在项目的标准可选依赖中，需要单独安装：

```powershell
.\.venv\Scripts\python.exe -m pip install PyInstaller
```

### 构建目录版

```powershell
.\packaging\build_portable_collector.ps1
```

自定义输出根目录：

```powershell
.\packaging\build_portable_collector.ps1 -OutputRoot release_test
```

脚本会：

1. 从结构数据库导出压缩笔数/笔顺参考；
2. 用 PyInstaller `onedir`、`windowed` 构建；
3. 排除 torch、torchvision、h5py、matplotlib、pandas 和 scipy；
4. 复制重录任务为 `user_001_rerecord.csv`；
5. 复制便携版文字说明。

默认输出：

```text
release/InkStructCollector/
├─ InkStructCollector.exe
├─ _internal/
├─ user_001_rerecord.csv
└─ 使用说明.txt
```

### 生成 manifest 和 ZIP

```powershell
.\packaging\finalize_portable_collector.ps1
```

脚本在目录中写入 `portable_collector_manifest_v2`，计算 EXE SHA-256、payload 数量和大小，然后创建：

```text
release/InkStructCollector_portable.zip
```

终端会输出 ZIP 大小和 SHA-256。分发时同时提供哈希；接收者解压完整目录后运行 EXE。

## 数据协议参考

### `handwriting_single_v1`

这是采集器输出和 `samples import` 接受的原始单字协议。精简示例：

```json
{
  "schema_version": "handwriting_single_v1",
  "sample_id": "8a261f9b-example",
  "writer_id": "user_001",
  "character": "永",
  "codepoint": "U+6C38",
  "task": {
    "task_id": "task-example",
    "item_id": "item-example",
    "source": "characters.csv",
    "source_index": 0,
    "repeat_index": 1,
    "repeat_total": 3
  },
  "capture": {
    "created_at": "2026-08-24T10:00:00+00:00",
    "input_type": "tablet",
    "canvas_width": 640,
    "canvas_height": 640,
    "device_pixel_ratio": 1.0,
    "coordinate_space": "logical_px",
    "duration_ms": 820
  },
  "strokes": [
    {
      "stroke_index": 0,
      "points": [
        {"x": 220.0, "y": 110.0, "pressure": 0.42, "t_ms": 0},
        {"x": 410.0, "y": 118.0, "pressure": 0.61, "t_ms": 95}
      ]
    },
    {
      "stroke_index": 1,
      "points": [
        {"x": 318.0, "y": 90.0, "pressure": 0.48, "t_ms": 140},
        {"x": 320.0, "y": 500.0, "pressure": 0.67, "t_ms": 360}
      ]
    }
  ],
  "stats": {"stroke_count": 2, "point_count": 4}
}
```

上例只展示字段结构，不是“永”的完整合法标准笔画样本。采集器实际保存所有笔画，每笔通常有更多点。

导入校验规则：

- `schema_version` 必须为 `handwriting_single_v1`；
- `writer_id` 非空并等于命令的 `--writer`；
- `character` 必须恰好包含一个 Unicode 字符；
- 如果提供 `codepoint`，必须等于该字符的 `U+XXXX`；
- `capture.canvas_width` 和 `canvas_height` 是有限正数；
- `strokes` 是非空列表，每笔至少两个点；
- `x/y` 是有限数并位于画布范围内；
- `pressure` 缺省时按 `0.5`，提供时必须位于 `[0,1]`；
- `t_ms` 必须可转换为整数并在所有笔画间全局单调不减。

`task`、`stats` 和其他扩展字段可以存在；InkStruct 将整个 `capture` 字典保留在索引中。

### `sample_index_v1`

`index.jsonl` 每行是一个归一化后的 `RawSample` JSON 对象，不是包含数组的单个 JSON 文件。关键字段：

| 字段 | 含义 |
| --- | --- |
| `schema_version` | `handwriting_single_v1` |
| `sample_id` | 样本身份 |
| `writer_id` | 书写者身份 |
| `character` / `codepoint` | 单字符和规范码点 |
| `canvas_width` / `canvas_height` | 从 capture 提取的画布大小 |
| `strokes[].stroke_index` | 从 0 开始的采集笔画顺序 |
| `strokes[].points[]` | `x/y/pressure/t_ms` 原始值 |
| `source_path` | 原始 JSON 的绝对路径 |
| `source_sha256` | 原始 JSON 内容摘要 |
| `capture` | 原采集元数据 |

索引包含绝对路径，跨机器复制后需要重新导入或保证相同路径可用。不要手工编辑路径后继续把旧 SHA-256 当作有效来源证明。

### `style_profile_v4` / `style_profile_v5`

风格档案关键字段：

| 字段 | 含义 |
| --- | --- |
| `schema_version` | 无因子化模型时 v4，有因子化风格时 v5 |
| `profile_version` | 输入索引、结构和模型身份计算得到的短版本 |
| `writer_id` | 档案所属书写者 |
| `created_at` | UTC 创建时间 |
| `source_index_sha256` | 输入索引摘要 |
| `sample_count` / `character_count` | 接受进入档案的样本和字符数量 |
| `global_style` | 整体比例、偏移、倾斜、压力和时间统计 |
| `prototypes` | 传统条件化单笔原型 |
| `component_layouts` | 跨字符部件布局原型 |
| `character_layouts` | 字符专属部件布局 |
| `component_strokes` | 部件条件单笔原型 |
| `component_relations` | 兄弟部件联合布局关系 |
| `component_trajectories` | 跨字符整组部件轨迹 |
| `character_component_trajectories` | 字符直达整组部件轨迹 |
| `excluded_samples` | 因质量或歧义隔离的样本及原因 |
| `coverage` | 部件和结构证据覆盖统计 |
| `style_tokens` | 有界数量的神经风格 token |
| `factorized_style` | v5 可选 writer latent、方差和结构键 |

应用代码应使用 `profile.json` 作为“当前指针”，用 `profile_version` 固定一次运行的真实档案身份。不要仅按修改时间推断版本。

### `generation_manifest_v1`

精简示例：

```json
{
  "schema_version": "generation_manifest_v1",
  "run_id": "document_demo",
  "writer_id": "user_001",
  "status": "completed",
  "started_at": "2026-08-24T10:00:00+00:00",
  "updated_at": "2026-08-24T10:00:04+00:00",
  "elapsed_seconds": 4.231,
  "requested_count": 4,
  "completed_count": 4,
  "failed_count": 0,
  "completed_characters": "墨构手写",
  "failed": [],
  "profile_path": ".../profiles/user_001/profile.json",
  "profile_version": "example-version",
  "structure_database": ".../artifacts/structures/characters.sqlite3",
  "generator": "DeterministicGenerator",
  "component_mode": "adaptive",
  "component_strength": 1.0,
  "checkpoint": null,
  "confidence_threshold": null
}
```

`status` 可能是 `running`、`cancelled` 或 `completed`。运行过程中 manifest 会反复更新，因此外部监控应容忍读取时文件刚被替换，并以 `updated_at` 判断新旧。

### `personal_trajectory_v1`

每个字符一个 JSON：

```json
{
  "schema_version": "personal_trajectory_v1",
  "character": "构",
  "codepoint": "U+6784",
  "locale": "zh-Hans",
  "writer_id": "user_001",
  "structure_version": "bddc96d4...",
  "profile_version": "example-version",
  "generator": "deterministic_component_trajectory_v4",
  "confidence": 0.82,
  "strokes": [
    {
      "standard_stroke_id": "s1",
      "order": 1,
      "confidence": 0.87,
      "style_source": "component_trajectory_exact+layout_exact+layout_relation",
      "component_key": "木|木|left|⿰",
      "points": [
        {"x": 0.18, "y": 0.24, "t_ms": 0, "pressure": 0.43, "pen_state": "down"},
        {"x": 0.52, "y": 0.25, "t_ms": 115, "pressure": 0.61, "pen_state": "up"}
      ]
    }
  ]
}
```

为便于展示，上例只保留了第一笔；真实“构”轨迹必须包含结构库规定的全部 8 笔，才能通过结构评估。

字段说明：

- `x/y`：`[0,1]` 归一化，左上原点、Y 向下；
- `t_ms`：生成的相对时间，笔内单调不减；
- `pressure`：`[0,1]`；
- `pen_state`：`down`、`up` 或整字结束时的 `end`；
- `standard_stroke_id` 和 `order`：由结构库固定；
- `style_source`：该笔实际采用的风格来源，适合审计回退；
- `component_key`：使用部件原型时的上下文键，可能为空；
- `confidence`：几何/证据置信度，不是人类主观评分。

### 预览协议

每个轨迹都会生成 SVG；除非使用 `--no-png`，还会生成 PNG。预览用于快速检查，不是结构真值。后续程序应读取轨迹 JSON，而不是从 PNG 反推笔画。

## 产物目录与文件用途

### 常规流水线

```text
artifacts/
├─ structures/
│  ├─ characters.sqlite3
│  ├─ build_report.json
│  └─ component_fallback_report.json
├─ samples/<writer-id>/
│  ├─ index.jsonl
│  └─ import_report.json
├─ samples_merged/<writer-id>/
│  ├─ index.jsonl
│  └─ merge_report.json
├─ samples_revised/<writer-id>/
│  ├─ index.jsonl
│  └─ replacement_report.json
├─ collection/<writer-id>/
│  ├─ recommendations.json
│  ├─ component_collection.csv
│  ├─ component_characters.txt
│  ├─ rerecord_current.csv
│  ├─ rerecord_current.json
│  └─ <target>/target_coverage_tiers_*.{json,csv}
├─ evaluation/<writer-id>/...
├─ experiments/<experiment-id>/...
└─ models/
   ├─ <model>.pt
   ├─ <model>.last.pt
   └─ <model>.training.json

profiles/<writer-id>/
├─ <profile-version>.json
└─ profile.json

outputs/<writer-id>/<run-id>/
├─ manifest.json
├─ evaluation.json                 evaluate --run 后出现
├─ trajectories/
│  └─ U+XXXX.json
└─ previews/
   ├─ U+XXXX.svg
   └─ U+XXXX.png
```

### 哪些文件应备份

| 数据 | 是否可重建 | 建议 |
| --- | --- | --- |
| 原始采集 JSON | 通常不可重建 | 最高优先级，多副本备份 |
| 任务状态 | 可部分从样本调和 | 与原始样本一起备份 |
| 样本索引 | 可从原始 JSON 重建 | 备份便于复现，注意绝对路径 |
| 结构数据库 | 可从第三方固定版本重建 | 保留报告和来源提交 |
| 风格档案 | 可从索引和结构重建 | 发布结果时应固定版本文件 |
| 生成轨迹 | 可从固定档案和结构重建 | 对外发布或人工评审结果应备份 |
| PNG/SVG | 可从轨迹重建 | 空间不足时优先保留 JSON/SVG |
| 模型检查点 | 训练成本高，未必可完全复现硬件细节 | 与 training report 一起备份 |
| CASIA LMDB | 取决于数据来源 | 按数据许可独立管理 |

### Git 管理边界

`.gitignore` 默认排除：

```text
.venv/
data/
artifacts/
profiles/
outputs/
release/
*.pt
*.sqlite3
```

因此提交代码不会自动备份运行数据。反过来，也不要用 `git clean` 作为本地数据管理工具；在任何清理前先解析并确认目标目录。

## 测试和代码检查

### 全部测试

```powershell
.\.venv\Scripts\python.exe -m pytest
```

测试覆盖几何、结构、对齐、部件生成、推荐、流水线、指标、实验、因子化风格和软渲染等模块。涉及 PyTorch 的测试需要已安装训练依赖，但不一定要求执行完整训练。

### Ruff

```powershell
.\.venv\Scripts\ruff.exe check src tests scripts packaging
```

当前配置使用 Python 3.12 目标和 100 字符行宽。

### 桌面 smoke test

开发环境可使用 Qt offscreen 或桌面入口的 `--smoke-test` 做启动检查。例如：

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
.\.venv\Scripts\inkstruct.exe generator --smoke-test
.\.venv\Scripts\inkstruct.exe collector --smoke-test
Remove-Item Env:QT_QPA_PLATFORM
```

采集器 smoke test 仍要求结构数据库和 `data_collection` 内核。不要在便携版最终用户机器上把 smoke test 当作常规启动方式。

### 生成验收顺序

建议对新的档案或发布运行按以下顺序验收：

1. `structures info` 确认结构库身份；
2. 检查 `import_report.json` 的拒绝项；
3. `samples audit` 处理重录和歧义样本；
4. `profile build` 记录档案版本和排除数；
5. 小文本生成并人工查看 SVG/PNG；
6. `evaluate --run` 检查结构不变量；
7. 再开始全量生成；
8. 对质量结论使用按字符留出评估和独立盲评，而不是只看训练样本拟合。

## 复现、备份与安全清理

### 可复现运行清单

发布或记录一次生成时，至少保存：

- Git commit 和工作树状态；
- `pyproject.toml` / `requirements.lock`；
- 结构数据库元数据和 `build_report.json`；
- 样本索引 SHA-256；
- 不可变档案版本文件；
- 生成 `manifest.json`；
- 使用的模型检查点及 `.training.json`；
- 完整命令行、随机种子和实验配置；
- `evaluation.json` 或实验报告。

不要只保存 `profile.json`，因为它是可更新的当前指针。应同时保存 manifest 指向的 `<profile-version>.json`。

### 用户数据保护

- 原始样本包含书写节奏、压力和潜在设备信息，应按个人数据处理。
- `index.jsonl` 包含原始绝对路径，外发前检查用户名和目录泄露。
- 档案和生成结果可能保留可识别的个人书写风格。
- 不要把 `data/`、`artifacts/`、`profiles/` 或 `outputs/` 上传到公共仓库，除非已完成授权和脱敏审查。
- 共享盲评包时不要共享 `blind_key.json`。

### 安全清理原则

文档不提供递归删除整个工作区的命令。需要释放空间时，先逐个确认并备份具体运行目录：

- PNG 可在确认轨迹 JSON 和 SVG 完整后单独清理或在后续运行使用 `--no-png`；
- 旧输出应按明确的 `<writer-id>/<run-id>` 处理，不要对 `outputs/` 根目录使用宽泛通配；
- 旧档案版本是复现历史 manifest 的依据，不能只因为存在新的 `profile.json` 就删除；
- `.venv` 可以重建，但 `scripts/setup_windows.ps1` 会主动清空它；
- 原始采集 JSON 不应与可重建缓存放在同一清理策略中。

## 故障排查

### `Python 3.12/3.13` 找不到或版本不受支持

检查：

```powershell
py -0p
py -3.12 --version
```

项目拒绝 Python 3.11 及更早版本，也拒绝 3.14 及更新版本。使用受支持解释器重新创建 `.venv`。

### `inkstruct.exe` 不存在

通常表示尚未执行 editable install，或正在使用错误的虚拟环境：

```powershell
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m inkstruct.cli --version
```

第二条模块命令可用于区分“包未安装”和“console script 丢失”。

### `desktop application requires inkstruct[desktop]`

安装桌面依赖：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[desktop]"
```

如果 PySide6 已安装仍失败，确认启动脚本使用的是项目 `.venv`，而不是另一个 Python。

### `找不到采集器内核`

源码采集器会依次检查：

```text
InkStruct/legacy/data_collection/handwriting_collector/ui.py
InkStruct/../data_collection/handwriting_collector/ui.py
```

将完整 `data_collection` 项目放在其中一个位置，或改用已构建的便携版。只安装 PySide6 不能替代采集器内核。

### `structure database not found`

重建或显式指定数据库：

```powershell
.\.venv\Scripts\inkstruct.exe structures build
.\.venv\Scripts\inkstruct.exe structures info `
  --database artifacts\structures\characters.sqlite3
```

确认第三方 `graphics.txt` 和 `dictionary.txt` 已检出。如果 Git 子模块内容缺失，应先恢复项目的第三方数据，而不是创建空数据库文件。

### 导入报告出现 `writer mismatch`

命令的 `--writer` 必须与每个 JSON 内的 `writer_id` 完全一致，包括大小写和下划线。不要通过文本批量替换原始 JSON 来“修复”；应确认选择了正确目录和任务身份。需要合并不同 writer 时应分别导入和建档。

### 导入报告拒绝所有 JSON

依次检查：

1. `schema_version` 是否为 `handwriting_single_v1`；
2. 选择的是否是单字 `samples/<writer-id>` 目录，而不是整行 `line_samples`；
3. `capture.canvas_width/height` 是否存在；
4. 每笔是否至少两个点；
5. 时间戳是否全局单调；
6. 路径下是否混入其他应用的 JSON 配置。

导入器递归扫描所有 `.json`。如果样本目录同时包含任务状态或报告文件，应把 `source` 指向更精确的单字样本目录。

### 采集器不能保存当前字

确认：

- 当前字符在结构库中；
- 实际笔画数等于标准笔画数；
- 轨迹非空；
- 已选择可写输出目录；
- 任务 writer 与界面 writer 一致。

使用“撤销上一笔”修正多写，或“重写当前字”重新采集。不要为了保存而关闭笔画数校验。

### `samples audit` 产生大量低置信样本

- 先检查画布尺寸、坐标和字符是否正确；
- 查看是否存在系统性错序或错误笔数；
- 适度调整 `--confidence-threshold` 只改变审计门槛，不会让低质量样本变好；
- 对 `ambiguous` 样本优先按 CSV 重录；
- 重录后使用 `samples replace` 创建新索引，再重新建档。

不要直接从 `excluded_samples` 中删除记录或手改档案 JSON。

### `profile.json` 不存在

确认索引路径并重新建档：

```powershell
.\.venv\Scripts\inkstruct.exe profile build `
  --writer user_001 `
  --index artifacts\samples\user_001\index.jsonl
```

如果使用自定义 `--destination`，生成时也必须通过 `--profile` 指向对应文件。

### 生成报告未知字符或退出码 2

检查 `manifest.json` 的 `failed` 数组。常见原因是目标字符不在结构库、档案 writer 不匹配、结构数据缺失或写入失败。

```powershell
$manifest = Get-Content -Raw outputs\user_001\document_demo\manifest.json | ConvertFrom-Json
$manifest.failed | Format-Table
```

未知字符不会被替代。若业务必须支持该字符，应先扩展并重建结构库，而不是忽略失败项。

### 全量生成中断后没有续跑

续跑必须使用完全相同的 `--run-id`。未指定 run ID 时每次都会生成新的时间戳目录。

```powershell
.\.venv\Scripts\inkstruct.exe generate `
  --writer user_001 `
  --all-supported `
  --run-id original_run_id
```

如果 manifest 缺失或损坏，当前生成器无法证明已有轨迹的运行身份，会拒绝复用该目录。请保留旧目录，使用新 run ID 重新生成。不要手工给旧文件补上新版策略字段来绕过检查。

### 更换档案后续跑产生混合结果

当前版本会拒绝身份不一致的续跑。更换 `profile.json`、结构库、模型、部件模式或强度后必须使用新的 run ID。若旧版本已经产生混合结果，请保留旧目录用于审计，在新 run ID 下重新生成完整目标集合。

### 指定检查点后仍显示确定性生成器

检查轨迹 `generator` 字段、检查点 `training_status` 和置信阈值。常见原因：

- 检查点是 smoke 或旧版，非 `formal`；
- 平均置信度低于校准阈值；
- 档案缺少 `style_tokens`；
- 因子化模型对应的档案缺少 `factorized_style`；
- 强制使用模型的诊断阈值没有显式设置。

这是设计中的安全回退，不是检查点参数被忽略。只有在诊断场景才考虑覆盖阈值，并在结果中明确记录。

如果缺少 CUDA 或训练依赖，带 `--checkpoint` 的命令会直接报错而不是回退；移除 `--checkpoint` 即可继续使用 CPU 确定性生成。

### `inkstruct train requires a CUDA-capable NVIDIA GPU`

确认安装的是 CUDA 版 PyTorch、驱动可用且当前环境能看到 GPU：

```powershell
.\.venv\Scripts\python.exe -c "import torch; print(torch.__version__); print(torch.cuda.is_available())"
```

确定性生成不需要解决此问题。没有 GPU 时跳过训练，不要尝试用 `--smoke` 绕过硬件检查。

### 正式训练或实验拒绝脏工作树

先查看变更：

```powershell
git status --short
```

正式报告应在确认代码和配置后提交或使用干净工作树。`--allow-dirty` 仅用于 smoke 和诊断，它会让实验与未记录改动绑定，不适合正式比较。

### Windows 路径和 PowerShell 续行问题

- 路径有空格、中文或括号时使用双引号；
- PowerShell 续行反引号必须是该行最后一个字符；
- 不要把文档中的 `<writer-id>` 尖括号占位符原样输入；
- 从项目根目录运行，避免相对配置中的 `artifacts/...` 指向错误位置；
- 使用 `Resolve-Path` 检查现有路径：

```powershell
Resolve-Path artifacts\structures\characters.sqlite3
Resolve-Path profiles\user_001\profile.json
```

### PNG 生成失败但 SVG/JSON 已存在

Pillow 或文件权限问题可能使单字符记录为失败。确认基础依赖和输出目录可写。对不需要位图的批量任务使用 `--no-png`，然后重新使用新的 run ID 生成；不要假设部分目录中的所有字符都已完成。

### 评估结果不能证明主观质量

`evaluate --run` 主要验证结构安全，`evaluate --writer` 主要验证按字符留出后的几何距离。两者都不能替代独立评分者盲评。对“更像用户”“可以上线”等结论，应使用 `blind-pack` / `blind-score`，保证每个条目至少三位独立评分者，并同时报告置信区间。

## 相关文档

- [项目介绍](PROJECT_OVERVIEW.md)
- [架构说明](ARCHITECTURE.md)
- [实现与验收记录](IMPLEMENTATION_REPORT.md)
- [v5 实现与初步结果](V5_IMPLEMENTATION_AND_PRELIMINARY_RESULTS.md)
- [笔顺对齐 v2](STROKE_ORDER_ALIGNMENT_V2.md)
- [目标覆盖采集分档](TARGET_COVERAGE_COLLECTION_TIERS.md)
- [第三方数据说明](../THIRD_PARTY_DATA.md)

0.1.18：参数输入框、下拉框和参数滑块不通过滚轮改值。需要调整时点击控件或使用键盘；滚轮仍可浏览设置页面。正文与段落设置全部陈列，公式实际字形预览默认显示辅助线，仅影响屏幕。


## 模板制作与单份 Markdown（0.1.21）

从左下“模板库”制作简单／自定义模板；右侧“模板内容”套用模板、填写字段、复制骨架和查看适配报告。新模型只提供一个连续正文流，正文框按编号排序，字段框独立重复。完整协议、边界、旧版迁移及操作见 [模板单正文说明](TEMPLATE_SINGLE_FLOW.md)；实际 Windows 结果见 [0.1.21 交付记录](RELEASE_0_1_21_WINDOWS.md)。


## 英文字距与字符校正参考（0.1.23）

齿轮 → 排版默认设置 → 正文与段落 → 英文字母间距，提供“按笔迹宽度（推荐）”和“保留采集位置留白（旧版）”。新安装的初始默认使用笔迹宽度；已保存的默认配置和旧 `.inkdoc` 保持原参数，不自动重排。若需让当前旧文档采用新字距，点击设置窗口底部「应用并保存」；这会同时应用窗口中的其他默认排版参数，请核对后确认。公式、等宽代码、汉字、数字及标点保留各自的原规则。独立采集无法确定真实词对连笔距离，本次修正不宣称还原连笔或自动字偶间距。

在页面预览点击字形，右侧字符校正预览会显示同一行左右各最多三个邻字，使用当前文档的真实冻结字形和间距。淡蓝底表示选中位置；深灰为周边已排字形，浅灰为本次调整前的字体笔迹，蓝色为校正草稿。选择“本文同一样本”或“本文同一字符的全部样本”时，预览内受影响的邻字也显示草稿。参数变化只更新局部预览，应用后才修改文档；原字体保持不变。换行、页边、字段和不同文本框不会被拼成一行。位移与缩放仍不改变前进宽度或换行。

## 模板界面整理（0.1.22）

齿轮 → 模板管理，用于制作可复用模板或独立编辑当前文档布局；排版默认设置只配置新文档。工作台左侧组织页组，中间画布选框、拖动移动和缩放，右侧编辑所选属性与字段声明。日常字段由排版右侧“模板”的表单填写，仍写回唯一 Markdown。更换模板、填写字段和真实适配检查在同一栏；模板与正文可通过编辑菜单撤销。详见 [模板使用说明](TEMPLATE_SINGLE_FLOW.md) 与 [Windows 验收记录](RELEASE_0_1_22_WINDOWS.md)。

## SVG 比例校正（0.1.36）

先校验未缩放排版的页面边界，再以左上角为原点缩放输出点坐标及 SVG 物理宽高、viewBox；笔宽保持毫米值。132.293% 会将输出宽高都乘以 1.32293，不改变预览、分页、冻结选样或项目纸张。选定页才变换，文件仍使用原页码。清单 coordinate_scale 记录策略、原始及输出尺寸。

原有越界、缺字等错误不能通过缩放规避。最终输出仍须满足边界、有效路径和单边不超过 2000 mm 的限制；缩小时笔宽不变，贴边笔迹仍可能越出新的画布，程序会拒绝。位图跳过仍需单独明确确认。

## 采集任务管理（0.1.37）

汉字样本与标点扩展使用相同书写者登记及任务列表。启动不自动恢复任务。在采集页选择书写者后创建任务，或在“任务列表”明确打开旧任务。显示名称可以用中文、可以重名；短身份码帮助区分，新 ID 使用完整 UUID，不使用默认 user_001。

“暂停并关闭”回到无任务状态；“取消任务”停止剩余采集，保留全部样本和进度；“恢复任务”可继续；“归档”只改变管理状态。列表包含两种采集类别及已完成、已取消、已归档、损坏记录，可搜索任务、作者、状态和 ID。取消任务不删除文件。可修改任务名称，或把未录份次复制为另一个作者的新任务，原任务不变，复用确认不跨作者继承。

“查看 / 重录已保存”可选单份或同字符/写法多份，原笔迹保留校验备份。汉字对应旧 NPY/TXT 活动导出副本也一起退役；失败可恢复，不把误录副本再次导入。已发布字体和冻结文档不自动更新。未保存笔迹提供保存并继续、放弃当前笔迹、返回采集；笔画数等原校验继续生效。

管理记录位于采集目录 capture-management.json（独立 inkstruct_capture_management_v1），不改旧任务/样本协议。不要手动改 ID 或批量搬动目录来改归属。另一窗口更新任务时拒绝过期写入并保留当前笔迹。Windows 目录过深时会在创建/保存前提示，请通过“数据 → 选择采集数据目录”改选较短目录。

## SVG 后台导出（0.1.38）

导出弹窗仍选择页码、表格内容、路径优化、横纵比例校正及定位点。确认排版在输出位置选择前冻结，后台使用同一份笔迹、选样和图片跳过清单；之后编辑正文不会改变本次输出。后台期间可继续编辑、滚动；同一窗口同时只运行一次 SVG 导出。

多页路径优化按 CPU、页数和可用内存限制并发，最多四个进程；单页、小任务、不优化或路线缓存命中时使用原串行/缓存路径，不新增单页候选并行。子进程不可用、崩溃或超时时，对未完成页串行重算，结果仍经过原几何检查。

进度窗口支持取消。关闭该窗口也请求取消，不会把未完成文件发布到目标目录。取消与最终发布以同一状态锁确定先后；已完成发布后不删除成功输出。应用关闭时先取消并清理导出，完成后可再次关闭。已有输出目录仍不能覆盖。导出完成提示明确说明使用冻结排版。

## 按字集生成与多核计算（0.1.40）

在生成页点击“内置字表…”可自由勾选完整命名字表：大陆《通用规范汉字表》2013 年版 8105 字、GB/T 12345-1990 繁体汉字 6866 字、台湾《常用國字標準字體表》1982 年版 4808 字。另提供基于 8105 字及 Unihan 17.0.0 全对应的 8593 字派生繁体扩展集，明确不等同于地区规范。每份字表显示版本、来源和范围；合并按目录顺序去重，共用字保留，不互相排除。

窗口完整显示结构库不支持的字符及编码，可复制全部报告。默认不能使用带缺口的字表；勾选“我已查看缺口，仅生成结构库支持的部分”后才允许使用支持部分，改变选择会撤销该确认。任务同时保存完整命名字表、实际目标、原始缺口、版本及哈希；不会通过其他字形替代缺字。字表身份或结构库成员改变时必须重新选择确认。

输入单字可查看简体、繁体、编码异体的全部定向关系及各地区字表成员。例如“发”同时对应“發、髮”，“说”同时对应“說、説”，“台、后”的自身对应也保留。这些关系来自 Unihan 17.0.0，只供查看与明确标注的派生集构造；不进行词义转换，不改 Markdown。同一 Unicode 的地区笔形仍取决于结构库，选择台湾字表不保证台湾笔形。本版没有香港规范完整字表；“完整”指所列明的有限字表，不指所有历史汉字。台湾原始 ODS 的 A02149 Unicode 栏与“汨”字符栏冲突已依据教育部同字号字典核对，原始冲突及依据保留。

自定义字表通过“导入字表…”选择 UTF-8 TXT / CSV。多列 CSV 必须有唯一的 character、汉字或字符列。程序保留首次出现顺序，去重但不做简繁转换或 Unicode 归一化；自定义输入中不支持的字符和变体序列仍明确阻止启动，不静默跳过。

“从文档提取汉字…”支持 Markdown 与 .inkdoc；“从当前排版提取”读取当前未保存源码及模板配置的快照，不改变正文、选样或设置。提取正文、公式、代码和图题中的汉字，排除 URL 与图片路径；当前模板只纳入活动布局引用的命名字段。无模板上下文的 Markdown 采用保守文本集合，原解析诊断仍显示。提取或内置字表结果均可编辑；编辑后作为新的自定义字表，不继续冒用原字表身份。

“计算方式”可选自动、串行、2 或 4 进程，v4 仍串行。自动模式少于 128 个目标使用串行；较大任务还受 CPU 和可用内存预算限制，上限四进程。此门槛是保守策略，不保证所有任务加速。进程复用完整档案与资源，每字仍执行全部语义、碰撞和来源检查。只缩小输出目标，不缩小供体池。

每次生成创建新结果目录。v6.1/v6.2 任务内 SQLite 一致性备份包含已提交 WAL 内容，逻辑身份只对该不可变视图计算一次；新任务重新读取和核验，不按路径或时间戳跨任务命中。目标清单、来源、规则和资源身份保存在 target-manifest.json、protocol.json 与 resources/identity.json。

取消后停止投递并回收本任务工作进程，已校验提交的字保留，未完成字列为 pending；串行取消在当前字结束后生效。进程启动、通信或超时失败时，记录原因，保留已提交结果，用相同冻结资源串行补齐剩余字符。损坏的暂存产物不会被当成完成；错误与失败 staging 保留供排查。尚无自动断点续跑或“只看字符存在便复用旧结果”的入口。制作字体仍另存新包，旧字体和文档冻结选样不自动更新。


### 两端对齐、自然书写与问题处理（0.1.43）

设置 → 正文与段落可选两端对齐（段尾靠左）。自然书写默认关闭，可分别调节笔画/倾斜、大小、字距、基线上下变化与种子；它可能改变断行分页，但不改写字体包、样本或冻结选样。旧 v1 项目保留原效果，仅明确选择新版或改变自然书写选项后采用 v2。详见 [自然书写说明](LAYOUT_JUSTIFY_HAN_VARIATION.md)。

“查看问题”按原因归并，可搜索、逐处定位、复制完整问题报告。重排期间禁止用旧结果定位新源码。导出下拉菜单中的“强制导出 SVG…”只导出当前快照已有的有效笔迹，缺口留空，并生成 issues.txt、issues.json 和 plotter.json；常规导出的严格检查不变。详见 [问题面板](LAYOUT_PROBLEMS.md) 和 [本轮交付](RELEASE_0_1_43_WINDOWS.md)。

应用全局正文/公式参数时保留当前文档的模板、纸张及旧绑定；只有明确修改对应模板或纸张并勾选应用到本文，才替换该项。

### 正文换行、分页与换框

内容预期由 AI 读取 [Markdown 生成规范](AI_MARKDOWN_SPEC.md) 和用户要求后生成，再复制粘贴或导入。`\newline`、`\linebreak` 强制换行；`\newpage`、`\pagebreak`、`\clearpage` 跳下一物理页；`\framebreak` 仅在连续正文流模板中跳下一个正文框，同页下一框不增加页码。固定字段、表格单元格和脚注等不执行分页/换框。用法、旧项目迁移及强度参数见 [命令说明](TEXT_FLOW_BREAK_COMMANDS.md)。不增加插入按钮。2026-10-26 已将独立排版更新合入主项目并构建 0.1.41；独立 Preview 包与研究历史记录保留。
