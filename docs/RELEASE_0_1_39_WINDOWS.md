# InkStruct 0.1.39 Windows：按字集与按字多进程生成

交付日期：2026-10-22。项目：`C:\Users\lee\Documents\InkStructApp\InkStruct-Windows-Dev`。Git 基点 `af45b45f04f899fcaced43aa980b0508673ee6c0` 加完整未提交工作树与本轮修改。APP_VERSION 是唯一应用版本来源；Python 库、字体、模板和文档协议均未随补丁号递增。没有 reset、clean、提交、推送或覆盖历史包。

## 用户可用行为

生成页保留“准备作者样本 → 生成汉字 → 生成结果”，新增“导入字表…”、“从文档提取汉字…”、“从当前排版提取”及“计算方式”。直接输入仍可用，全结构库目标入口保留。

自定义字表为 UTF-8（可带 BOM）TXT / CSV。多列 CSV 需唯一的 character、汉字或字符列，不猜测其他列；最多 4 MB。目标按 Unicode 字素去重，保留首次出现顺序，不做简繁转换、Unicode 归一化或变体截断。空表及不支持项明确阻止启动；不会默默丢掉 A、表情或不支持的变体序列。输入控件不再使用 QLineEdit 默认的 32,767 字符截断限制。

文档入口支持 Markdown 和完整校验的 `.inkdoc`，提取印刷文本、数学汉字、代码和图题，排除 URL、图片路径；当前排版入口先在 GUI 线程捕获未保存源码、版本和不可变 FlowStyle，再后台解析。活动起始/循环布局未引用的命名字段不纳入目标，未知字段和语法错误仍记录诊断。没有模板上下文的 Markdown 采用保守文本集合，界面及清单明确此边界；不承诺等同于成功排版后的最终字形用量。现有图题设置没有额外的隐藏开关。本轮不引入未经完整核实的简体/繁体分类。

提取后可编辑，编辑即转为自定义字表。字表只限定输出目标，始终使用完整有效作者档案；不改变同字排除、候选池、语义准入、映射、排序、碰撞或来源检查。`target-manifest.json` 保存实际目标、来源文件/源码身份、目标哈希、源码范围和诊断；不是仅保存一个“简体”标签。

## 不可变资源与身份复用

v6.1/v6.2 每次任务创建新的 `resources/`，SQLite backup 得到包含已提交 WAL 数据的一致性备份；档案、graphics、dictionary、修正配置逐一复制并核对前后完整哈希。进程启动时重新核对冻结文件哈希。

`FrozenStructureRepository` 在单个 SQLite 事务中读入私有不可变 JSON 行与元数据，按旧算法计算完整逻辑 SHA 一次。后续 get/iteration 都从同一不可变行解码新图，身份核验仍逐次比较预期哈希，只复用该资源视图中已完成的逻辑摘要。不缓存活数据库的路径/mtime，不跨任务复用，不用主 DB 文件哈希替代 WAL 内容。新任务重新读取与核验；配置或档案不匹配仍失败。未删除或降低任何校验。

这减少了主引擎、作者单笔回退及羊部件旧规则引擎的重复整库遍历。代价是任务内保留全库原始行，串行峰值 RSS 相比旧路径增加；自动并发仍受内存预算限制。

## 调度、取消和失败

串行和多进程共用静态提取出的同一份 `prepare_generation` / 逐字计算代码，没有在正式运行中使用 AST 编译。生成方法及语义版本不变。初始化规则日志明确保存为 protocol 的 initialization_rule_log，不丢失，也不让工作分配决定它落在哪个字符。

v6.1/v6.2 可选自动、串行、2 或 4 进程；v4 继续原串行实现。自动模式少于 128 个目标使用串行，大任务上限四进程，同时预留两个逻辑 CPU、约 1 GiB 可用内存，每工作者至少预算 512 MiB。此为保守启发式，不保证所有 128 字以上任务更快，也不是内存硬上限。手动并发仍受 CPU/内存预算约束。

使用 Windows spawn，每个进程复用完整引擎，一次只接收一个汉字；只传摘要和控制信息，轨迹写入本次任务独立 staging。子进程启动环境限制数值库为一线程，父进程环境在成功/失败后恢复，避免嵌套 BLAS 过度竞争。进程结果经父进程核对提交侧记录、文件哈希、协议、来源分区和档案身份后才复制到正式结果区。候选计算中的完整几何、语义和来源校验仍在原计算代码中执行。按请求顺序写最终清单，完成顺序不参与选择。

启动、通信、退出或单任务 300 秒无响应触发回收，记录原因，并使用同一冻结资源串行补齐未提交字；原有成功字不重算。真实字符生成失败仍保留失败记录，不靠重试无限掩盖错误。损坏/未提交 staging 不纳入字体。取消停止投递、回收本任务进程，保留已提交字并明确 pending；串行在当前字结束后停止。初始化各阶段设取消检查，但不可中断的单次解析/引擎调用仍可能延迟返回。没有新增自动断点续跑入口。

`protocol.json`、`summary.json`、`resources/identity.json` 记录实际规则、资源、并发、失败/回退及未完成目标；旧结果、字体和文档均不自动迁移。仅补缺字仍需完整方法/参数/规则/档案/资源兼容证明，本版不按“字符已存在”直接复用历史结果。

## 正确性验证

- 最终原生权限回归：**129 passed，0 failed，0 skipped**，23.739 秒。包含字表、字段协议、WAL、不可变资源、spawn、崩溃 staging、取消、串行恢复、线程环境恢复、生成、v6.2、字体、文档、循环模板、源码身份、采集管理、符号重录、资源管理及既有后台 SVG。原始 XML / 日志为 `regression-final.xml` / `.log`。
- 同一真实 `user_001` 档案、同一完整供体池、32 字含“孔”“正”“羊”“群”，旧串行、新串行、2/4 进程各两个独立解释器任务：**256 份逐字 payload 与侧记录完全一致**，包括供体、候选证据、拒绝、轨迹、压力、时间、来源缺口、规则日志与全部检查。“孔”“羊”各自的参考替代警告保留。未做独立生成质量评估，源档案含历史验证样本。
- 真实生产工厂连续 110 次计算（11 个不同字符重复十轮），验证第 100 次清缓存发生一次，全部 payload 与串行权威结果一致。不是 110 个不同字符或全库长任务。
- 真实 IPC 不可用后，11 字串行恢复全部一致；真实进程运行中取消保留已提交的 1 字，剩余 10 字明确 pending，无残留本任务子进程。单元故障注入另验证工作进程在 gzip 写出后、提交侧记录前退出：该 staging 不被承认，保留已提交字符并串行补齐。
- 真实旧多页 `.inkdoc` 提取 **345** 个汉字，全部结构库支持；真实纯符号文档提取 0 字，原文件 SHA 均未变化。没有生成全部 345 字。
- 源码应用和正式构建的 **InkStruct.exe / InkStructTool.exe** 都跑了真实 11 字串行、2/4 进程、当前文档提取及源码身份不变核对；各自三路 payload 一致，进程路径没有隐式回退。双 EXE FileVersion/ProductVersion 均 **0.1.39**，x64，构建源码 305 文件最终哈希仍一致。
- 新小规模验证字体：11 个新汉字加旧包 1,196 个未改非汉字候选，共 **215 字符 / 1,207 候选 / 102,559 点**。源包 10,770 候选先做完整验证，新包再完整验证；旧候选 ID、轨迹、度量和来源保留。三页正文/公式预览、272 项冻结选样及完整布局保存重开一致；三份严格 SVG 字节哈希一致。8 项数学度量校准警告和 2 个来源缺口候选保留。未安装为默认字体，也不能替代用户原全库字体。

初次受限回归有 WinError 5（字体原子发布、沙箱临时目录清理），原日志保留；原生权限重跑通过，没有改原子发布协议。初版新 UI 测试误指定不存在的测试结构库，已修正测试输入。较大字集还暴露了侧记录中 tuple 经 JSON 成为 array 的比较差异；改为按原 JSON 协议规范化比较，未放宽任何实际字段检查。早期原型路径类型错误、Windows 分隔符错误和旧函数复现缺少 __file__ 的失败日志均保留，未算作通过。

## 性能

本轮重新顺序测量，不使用上一轮数据冒充。Python 3.13.16 x64、Intel Core Ultra 5 250KF Plus、18 逻辑 CPU、Windows 11 build 26300、平衡电源方案。每种方式两次独立解释器、相同 32 字与真实档案；数值库统一一线程，不与本轮测试/构建并行。未清 Windows 文件缓存，未宣称严格空载；原始进程组 CPU/RSS 采样保留。计时含任务资源准备、初始化、完整检查、压缩写出、父进程复核、汇总和回收；不含应用启动或建档。

| 实现 | 整体中位数 | 最短—最长 | 峰值组 RSS 中位数 |
|---|---:|---:|---:|
| 旧串行 | 37.338 s | 37.294—37.382 s | 309 MiB |
| 身份复用后串行 | 14.039 s | 13.993—14.084 s | 498 MiB |
| 身份复用 + 2 进程 | 10.177 s | 10.172—10.181 s | 1,023 MiB |
| 身份复用 + 4 进程 | 9.346 s | 9.336—9.357 s | 2,017 MiB |

本样本身份复用串行约 **2.66 倍**；在已优化串行之上，二进程约 **1.38 倍**、四进程约 **1.50 倍**；组合相对旧串行约 **3.99 倍**。组 RSS 重复计入共享 DLL 页，不是物理内存净增。两次样本量不支持尾延迟保证，不外推全 9,574 字速度，也不把减少输出目标的工作量下降混入同任务并行倍数。本轮性能与来源/确定性验证不等于人工质量合格。

## 原生界面与限制

新工作区 `workspaces/windows-generation-0.1.39` 启动正式 EXE，实际 Windows 窗口显示 0.1.39、四标签、浅色界面和新字集/并发入口；已到达生成页，打开并取消原生文件选择框，目标文本未改变，验收窗口已关闭。Computer Use 初次 element click 返回 coordinate input geometry is unavailable，刷新/激活后到达生成页；文件名 set_value 又返回 element 251 is not available in cached app state，后续焦点未能可靠确认。因此**不声称完成原生文件导入、中文粘贴或全程人工式导入/建档验收**。文件解析、控制器和当前文档提取另由源码及双 EXE 的真实 Qt 控件自动检查通过；这些检查明确使用 offscreen，不冒充原生光学交互。原生可访问树及限制保存在 native-accessibility.json。

未验证：全 9,574 字新生成、长时间内存增长、其他硬件/电源条件、完整简繁与地区规范字表、实际输入法组合输入、数位板/驱动及写字机。没有重跑全库、隐藏警告、降低协议检查或改动字体/模板/文档的默认语义。

## 产物与环境

使用已有 `.venv`，无新增全局或应用依赖。监测仅复用既有独立实验环境的 psutil。README、使用说明、集成应用文档、LaTeX 手册源码及发布名同步 0.1.39；本机未安装 XeLaTeX/latexmk，未重编手册 PDF，不将历史 PDF 当作新版。

- 交付 ZIP：`artifacts/windows_release_0.1.39/InkStruct-0.1.39-Windows-x64.zip`，完整解压后启动，保留 `_internal`。
- 应用：`artifacts/windows_build_0.1.39_20261022/dist/InkStruct/InkStruct.exe`；同目录 `InkStructTool.exe`。
- 小规模验证字体：`artifacts/generation_0.1.39_20261022/font-validation/user_001-v62-generation-0.1.39-validation.inkfont`；不是全库替换包。
- 全部命令、前后源码、Git 状态、原始测量、失败和通过日志、生成结果、字体、文档与 SVG：`artifacts/generation_0.1.39_20261022/`。
- 双 EXE 记录：`frozen-InkStruct/verification.json`、`frozen-InkStructTool/verification.json`；源码为 `source-application-check/verification.json`。
- 构建日志、环境与源身份：构建目录的 `build.log` / `build-provenance.json`；ZIP 哈希见发布目录 CHECKSUMS.sha256。

保全记录为 preservation.json：23,693 个既有用户文件元数据核对；其中 23,689 个与上次交付内容 SHA 对照，4 个无历史 SHA，仅核对元数据。Git HEAD 不变，既有未提交工作保留；本轮修改前源码另有完整备份。最终校验结果见 final-verification.json。仅清理本轮私有测试临时目录与 build work/cache；保留日志、数据、验收、字体、应用及交付包。

## 复现命令

在项目根目录执行，输出路径必须使用新的名称：

```powershell
.venv/Scripts/python.exe -B -X utf8 -m inkstruct.application --workspace workspaces/windows-generation-0.1.39-NEW
.venv/Scripts/python.exe -B -X utf8 -m pytest tests/test_generation_targets.py tests/test_generation_resources.py tests/test_generation_parallel.py tests/test_generation_targets_qt.py tests/test_generation_workflow.py tests/test_v62_semantics.py -q -p no:cacheprovider --basetemp artifacts/check139-NEW
.venv/Scripts/python.exe -B -X utf8 packaging/build_inkstruct_app.py --output artifacts/windows_build_0.1.39_NEW
artifacts/windows_build_0.1.39_20261022/dist/InkStruct/InkStructTool.exe --inkstruct-check --output artifacts/check139-tool-NEW --generation-profile artifacts/v61_collection_acceptance_20261013/run_v3_with_validation/source_archive.json
```

双 EXE 完整实测命令在各自 `*-command.json`。完整最终 129 项测试清单见 regression-final.xml（包含所有实际测试名），相关测试文件见本轮 source-before/ 与源码 tests；不要覆盖已有 basetemp/验收目录。性能入口 `check_generation.py`（mode 为 baseline、serial、2、4，label 必须新建）及 performance.py，旧函数从本轮源码备份加载；复制实验脚本时保留其输入/备份依赖，避免再次执行已有 performance 标签。`check_boundaries.py`、`font_check.py` 和 `check_frozen.py` 已有产物不重复写入；修改输出目录后再运行。

本版可以继续开发并交付此范围的 Windows 应用。完整字表、全库性能、跨硬件与原生输入法/实体硬件验收继续作为独立事项，不以本轮小样结果替代。
