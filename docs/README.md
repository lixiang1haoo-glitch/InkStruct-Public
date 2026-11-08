# InkStruct 文档中心

当前主应用版本：[0.1.63](RELEASE_0_1_63_WINDOWS.md)，采用左侧导航、左下字体库、模板库及设置，保留4 GiB展开字体和可选同字成品数量。另见 [AI Markdown 生成规范](AI_MARKDOWN_SPEC.md) 与 [换行/分页/换框](TEXT_FLOW_BREAK_COMMANDS.md)。

历史交付：[0.1.45界面整理](RELEASE_0_1_45_WINDOWS.md)的验收与实验记录继续保留。

前置开发验证（记录保留当时时态）：[每字成品数量与 user_001 全库验证](GENERATION_CANDIDATE_COUNT_FULL_20261104.md)，包含1–64份选择、八份上限实测和真实来源缺口；功能纳入0.1.46。

前置容量对照：[字体4 GiB容量与简体字集体积对照](FONT_CAPACITY_SIMPLIFIED_20261104.md)，同源用户字体约611 MB降为454 MB，压缩体积减少约25.7%；超过旧2 GiB展开上限的新包需0.1.46或同策略源码读者。原实验报告不倒改为发布验收。

本次接入真实供体多候选生成及制包，沿用字体格式和排版冻结选样。已核对 [两端对齐](LAYOUT_JUSTIFY_HAN_VARIATION.md) 与 [排版问题面板](LAYOUT_PROBLEMS.md) 的预览实现。

0.1.40：内置可核实版本的完整命名字表、显式缺口确认、一简多繁与地区成员查询；保留完整供体池及按字多进程。见 [Windows 交付记录](RELEASE_0_1_40_WINDOWS.md)。

0.1.38：SVG 后台导出、多页进程并发及串行回退；保留冻结快照、全部导出设置和用户数据。见 [Windows 交付记录](RELEASE_0_1_38_WINDOWS.md)。

0.1.36：SVG 比例校正先严格校验原始排版，再同步缩放输出坐标、画布尺寸与 viewBox，笔宽不变；原文档与预览不变。见 [Windows 交付记录](RELEASE_0_1_36_WINDOWS.md)。

0.1.35：第三个标签页统一为“字体与模板”，提供真实笔迹预览、字符与样本检查、来源版本、模板缩略图与库内副本。“用于当前文档”先确认实际适配影响；新文档默认独立设置，移出资源可恢复。见 [Windows 交付记录](RELEASE_0_1_35_WINDOWS.md)。

0.1.34：六辐星号由录制减号合成，比号复用冒号，公式圆圈复用中文句号；新字体保留来源与动态数据。页码向上为上一页、向下为下一页。见 [交付记录](RELEASE_0_1_34_WINDOWS.md)。

0.1.33：预览 CPU 缓存与预取优化，可选 GPU 并自动回退；新增符号合成，SVG 导出支持页码、表格内内容、比例校正和定位短线。见 [交付记录](RELEASE_0_1_33_WINDOWS.md)。
本目录汇总 InkStruct（墨构）的项目说明、操作手册、架构设计、实验记录与数据来源。本文档集面向三类读者：第一次运行项目的使用者、维护代码和数据流水线的开发者，以及需要复现实验的研究人员。

> 文档适用于 InkStruct `0.2.0`。项目状态数据核对日期为 **2026-08-24**。命令、参数和协议以当前仓库代码为准；历史报告中的指标只代表报告记录时的样本、档案和运行配置。

## 从这里开始

编辑排版用户可先阅读 [用户手册 PDF](../output/pdf/InkStruct用户手册_编辑排版篇.pdf)，或查看 [LaTeX 源码与构建说明](user_manual/README.md)。手册按基础操作、编辑排版、字形生成、书写采集分部组织；当前完整编写编辑排版，后两部分保留集成结构与资源交接说明。

| 目标 | 建议阅读顺序 |
| --- | --- |
| 第一次安装并生成几个字 | [项目介绍](PROJECT_OVERVIEW.md) → [使用手册：安装](USER_GUIDE.md#安装与环境准备) → [CLI 快速开始](USER_GUIDE.md#cli-快速开始) |
| 使用图形界面采集和生成 | [使用手册：轨迹采集器](USER_GUIDE.md#轨迹采集器) → [风格生成器](USER_GUIDE.md#风格生成器) |
| 批量生成、补采和质量检查 | [完整 CLI 工作流](USER_GUIDE.md#完整-cli-工作流) → [产物目录](USER_GUIDE.md#产物目录与文件用途) |
| 维护或扩展代码 | [项目介绍：系统组成](PROJECT_OVERVIEW.md#系统组成) → [架构说明](ARCHITECTURE.md) → [协议参考](USER_GUIDE.md#数据协议参考) |
| 训练模型或复现实验 | [训练与模型检查点](USER_GUIDE.md#训练与模型检查点) → [可复现实验](USER_GUIDE.md#可复现实验) → [v5 实现与初步结果](V5_IMPLEMENTATION_AND_PRELIMINARY_RESULTS.md) |
| 了解数据来源和许可 | [项目介绍：许可](PROJECT_OVERVIEW.md#数据隐私与许可) → [第三方数据说明](../THIRD_PARTY_DATA.md) → [矢量字体研究溯源](VECTOR_FONT_RESEARCH_PROVENANCE.md) |

## 核心文档

- [Windows 0.1.33 与 v6.2 exp](RELEASE_0_1_32_WINDOWS.md)：语义准入、来源重试、真实字体验证；[v6.2 方案](V62_EXP_CONTENT_ADMISSION.md)。

- [Windows 0.1.31 窄数字占位修复](RELEASE_0_1_31_WINDOWS.md)：紧凑公式数字最小占位、居中补白，保留原笔迹与表格数字规则。
- [Windows 0.1.30 紧凑公式与录制构件](RELEASE_0_1_30_WINDOWS.md)：真实笔迹间距、录制根号和伸缩括号、独立样式版本与旧文档兼容。
- [Windows 0.1.29 标点间距和路径优化](RELEASE_0_1_29_WINDOWS.md)：按笔迹紧凑排列，优化默认开启，旧文档保持原值。
- [Windows 0.1.28 模板预览停止修复](RELEASE_0_1_28_WINDOWS.md)：保留已排正文及脚注，定位阻断对象，支持当前大资源目录文档重开。
- [Windows 0.1.27 默认手写分数线](RELEASE_0_1_27_WINDOWS.md)：字体减号横向拉伸，旧文档来源保留。
- [Windows 0.1.26 缺失位图引用导出](RELEASE_0_1_26_WINDOWS.md)：严格区分受限导出能力与完整文档状态，保留诊断和冻结排版。
- [Windows 0.1.25 跳过非 SVG 图片导出](RELEASE_0_1_25_WINDOWS.md)：提示确认、保留占位与图题、记录跳过清单。
- [Windows 0.1.24 图片高度与汉字公式](RELEASE_0_1_24_WINDOWS.md)：默认高度 60 mm、等比宽度及汉字上下标。
- [Windows 0.1.23 英文字距与校正预览](RELEASE_0_1_23_WINDOWS.md)：采集留白修正、真实邻字参考与旧文档兼容。
- [Windows 0.1.22 模板界面整理](RELEASE_0_1_22_WINDOWS.md)：工作台、字段表单、撤销及兼容性验收。
- [Windows 0.1.21 模板重构](RELEASE_0_1_21_WINDOWS.md)：单正文流、命名字段、起始／循环布局，兼容性与验收。
- [模板单正文协议与使用](TEMPLATE_SINGLE_FLOW.md)。

- [Windows 0.1.20 字符校正范围](RELEASE_0_1_20_WINDOWS.md)：区分单次出现、同一样本、同字符全部样本，可同时保存新字体版本。

- [Windows 0.1.19 字符校正与设置更新](RELEASE_0_1_19_WINDOWS.md)：单字、同字、全文校正与另存字体包，验收及产物位置。

- [InkStruct 0.1 集成应用](INKSTRUCT_0_1.md)：macOS 采集、生成、字体库、排版入口与验证边界。
- [统一字体包设计](FONT_PACKAGE_DESIGN.md)：`.inkfont` 核心已在 0.1 实现；完整作者工作区、依赖反查和增量生成仍为设计。

- [通用书写模板设计](TEMPLATE_AUTHORING_PLAN.md)：用户与 Agent 共用模板模型、数值设计入口、JSON 校验与后续画布/插槽方案。

- [文档采集缺口](RESOURCE_INSPECTION.md)：读取原生设置、可见字符与录制公式结构需求，导出每字 5 次的采集 CSV。

- [混排支持矩阵](MARKDOWN_SUPPORT_MATRIX.md)：元素、命令、资源与机器出口的当前支持范围。
- [混排交接说明](MARKDOWN_DELIVERY_HANDOFF.md)：Mac/Windows 源码启动、复现命令、证据位置与剩余验收。
- [编辑器离线安装材料](EDITOR_OFFLINE_KIT.md)：按平台准备固定依赖、哈希校验、独立安装及功能验证；需要已安装 Python 3.13。
- [编辑器独立应用](EDITOR_STANDALONE.md)：内嵌 Python/Qt 的 macOS 测试应用、PDF 配套进程及用户恢复目录；Windows 独立构建待验证。
- [M5 扩展验收单](MARKDOWN_M5_ACCEPTANCE.md)：四类扩展、组合实样及编号括号身份修复。

- [Markdown 混排编辑器](MARKDOWN_MIXED_EDITOR.md)：正文与表格双栏编辑、参数设置、旧表格导入及单表/全文导出。
- [混排性能验收](MARKDOWN_PERFORMANCE.md)：固定 1/10/50 页、内置及真实数字资源、冷/热完整排版、导出、峰值内存与解析取消响应。
- [文档总量限制](DOCUMENT_LIMITS.md)：统一节点、嵌套、页面与路径点限制，嵌套布局总工作量、超限草稿和导出门槛。
- [混排内容缓存](MARKDOWN_CACHE.md)：解析、资源解析、独立度量、完整布局、路由、页面 SVG 缓存及普通文档前后部续排，内容失效、请求隔离、容量控制与真实多页编辑测量。
- [项目迁移与恢复](PROJECT_RECOVERY.md)：原生项目校验、独立恢复会话、故障注入与已安装环境迁移验证。
- [复杂表格分页评估](COMPLEX_TABLE_PAGINATION.md)：rowspan 传递行组、超高单元格/脚注阻断、来源定位和后续内部拆分设计边界。
- [Obsidian 静态扩展](OBSIDIAN_STATIC.md)：独立方言开关、双链可见标签、展开的 Callout、显式嵌入标签与来源定位。
- [录制公式结构](MATH_SAMPLED_CONSTRUCTIONS.md)：录制减号分数线、分段适配根号和缩放括号，来源选择、原始轨迹保存与真实样张。
- [受控数学语法](MATH_SYNTAX.md)：命令白名单、源区间、数学资源扫描和 M4a–M4c 受控手写公式几何。
- [脚注状态](FOOTNOTES.md)：源码身份、上标编号、页底协同分页和长注释续页；已接通正文表格/图题引用；专用设置和定义内部表格/图形/分隔线已接通，固定区引用与结构块直接开头的定义已接通。
- [任务列表](TASK_LISTS.md)：源码勾选状态、预览点击、稳定身份和可书写方框。
- [图形化公式设置](MATH_GRAPHICAL_SETTINGS.md)：参考 AxMath 分类组织，手写实时预览、毫米/pt 和结构百分比参数，已接通多行对齐、编号、小矩阵/数组框线及修饰与向量参数。
- [页面模板](PAGE_TEMPLATES.md)：扫描模板数字测量、首页/续页区域、预印纸与空白纸及校准偏移。
- [图片块与图题](IMAGE_LAYOUT.md)：PNG/JPEG 尺寸、图题分页、项目内资源与参考页面导出门槛。
- [单线 SVG 导入](LINE_SVG_LAYOUT.md)：受控路径/图形、毫米变换、曲线容差、来源与严格 M/L 机器导出。
- [Markdown 混排实施记录](MARKDOWN_MIXED_LAYOUT_PROGRESS_20261013.md)：M0–M5 功能及 M6 迁移、恢复和性能记录；实际样本校准、交付整理和实机验收继续推进。
- [纯文本编辑与字形检查应用](TEXT_REVIEW_APP.md)：双栏编辑、点字评价、放大查看、筛选和检查项目保存。
- [排版计划评审及首批构建](PAGE_LAYOUT_PROGRESS_20261009.md)：纯文本页面预览、SVG/PNG、兼容契约、实测记录及编辑与数学的后续门槛。
- [Mac 安装与本地数据恢复](MAC_SETUP.md)：Python 环境、桌面启动、外部采集器与旧机器数据恢复。
- [项目介绍](PROJECT_OVERVIEW.md)：项目定位、核心思想、系统组成、数据流、当前状态、边界和许可。
- [完整使用手册](USER_GUIDE.md)：安装、桌面应用、所有 CLI 子命令、输入输出协议、训练、实验、打包、测试和故障排查。
- [架构说明](ARCHITECTURE.md)：结构图数据库、笔顺感知对齐、结构不变量、学习模型与部件风格层。
- [实现与验收记录](IMPLEMENTATION_REPORT.md)：各阶段已实现能力、历史评测和仍需人工完成的验收事项。

## 专题与研究文档

### 训练、评估与模型演进

- [结构修复传递与范围消融](STRUCTURE_DELTA_EXPERIMENT_20261007.md)：固定风格传递、缺笔恢复和负结果；区分结构修复与重新建档收益。

- [标准结构扩展审计与首批修复](STRUCTURE_AUDIT_REPAIR_20261007.md)：当前优先级，导入裁剪根因、三笔轮廓修复与固定档案 A/B/C 验证；生产默认关闭。

- [Mac 迁移与轨迹保真阶段记录](MAC_QUALITY_PROGRESS_20261007.md)：真实数据恢复、作者回归、高保真扩展和折钩诊断。
- [本轮改进效果对比报告](EFFECT_COMPARISON_20261007.md)：边界前后对比、高保真保存效果与七类问题的实际进度。
- [v5 实现与初步结果](V5_IMPLEMENTATION_AND_PRELIMINARY_RESULTS.md)：v5 训练、渲染损失、因子化风格与固定实验结果。
- [笔顺对齐 v2](STROKE_ORDER_ALIGNMENT_V2.md)：错序检测、全局匹配、歧义隔离和质量审计。
- [矢量字体研究溯源](VECTOR_FONT_RESEARCH_PROVENANCE.md)：相关矢量字体和结构数据调研来源。

### 采集计划与覆盖率

- [目标覆盖采集分档](TARGET_COVERAGE_COLLECTION_TIERS.md)：90%、95%、99%、99.9% 和 100% 五档最小采集计划。
- [大陆标准简体采集分档](MAINLAND_SIMPLIFIED_COLLECTION_TIERS.md)：面向 GB2312 大陆标准简体字符包的分档结果。
- [user_001 部件采集说明](USER001_COMPONENT_COLLECTION.md)：部件覆盖型补采任务的历史说明。
- [user_001 频数采集 200 字说明](USER001_FREQUENCY_COLLECTION_200.md)：频数驱动补采任务的历史说明。

## 信息来源与优先级

当不同文档、配置或历史产物出现差异时，按以下顺序判断当前行为：

1. `src/inkstruct/` 中的实现与 `inkstruct ... --help` 输出；
2. `pyproject.toml`、`configs/` 和 `scripts/` 中的当前依赖、配置及可执行脚本；
3. 当前运行生成的 `manifest.json`、`profile.json`、评估报告和结构数据库元数据；
4. 根目录 `README.md` 与本目录的说明性文档；
5. 带明确日期的实现报告和实验记录。

这样排序是因为历史报告会保留当时的样本数、档案版本和实验结果，而当前代码或产物可能已经更新。例如，生成目录中的 `manifest.json` 会固定该次运行实际使用的档案版本，应优先于对“当前档案”的文字描述。

## 文档约定

- 所有未特别说明的命令都从项目根目录执行。
- Windows PowerShell 为原始开发环境；macOS 的 CPU 生成与桌面启动已验证，详见 Mac 安装说明。跨平台打包及真实采集设备仍需分别验收。
- 文档中的 `user_001` 是匿名示例书写者 ID；请在实际使用时替换为自己的稳定 ID。
- 路径中的 `<writer-id>`、`<run-id>`、`<path>` 是占位符，不应原样输入。
- 项目代码、结构数据、用户样本、CASIA 数据和模型权重具有不同的授权边界，不能只依据项目的 MIT License 推断其他数据可以分发。

- [跨字同部件变化实验（2026-10-07）](EXEMPLAR_VARIATION_EXPERIMENT_20261007.md)：真实部件参考范围、可复现实例变化及 28 字留出负结果。
- [已采集整字原稿优先重建（2026-10-07）](OBSERVED_RECONSTRUCTION_20261007.md)：CLI/Mac 显式开关、岛/尴折钩保留和两作者 128 字核验。
- [已复核局部几何修正入口（2026-10-07）](REVIEWED_GEOMETRY_ENTRY_20261007.md)：黧/瀝源退化、丢/侈有限平移、三份档案与不变保护集。

- [新符号实样验证](SYMBOL_VALIDATION_20261013.md)：80 字符、405 份样本，完整对照、公式/表格混排、严格 SVG 和待采集清单。
- [字母与符号采集](SYMBOL_CAPTURE.md)：每字 5 份、变量笔数、排版度量及 Windows 构建说明。

- [数字表格排版工具](TABLE_EDITOR.md)：HTML 表格、内置单线数字、小数点与仅含 M/L 的 path SVG。

- [Markdown 多元素混排实施计划（2026-10-13）](MARKDOWN_MIXED_LAYOUT_PLAN_20261013.md)：基于表格实测的统一架构、元素支持矩阵、M0–M6 任务与验收出口。
- [Markdown 混排实施记录（2026-10-13）](MARKDOWN_MIXED_LAYOUT_PROGRESS_20261013.md)：目标模式阶段交付、公共机器导出与回归证据。

- [可复用模板内容字段](TEMPLATE_SLOTS.md)：模板 v2 字段声明、GUI 编辑、Agent 按字段编号绑定及迁移。
