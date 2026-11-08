# 同字候选数量与 user_001 全库验证记录

2026-11-04；项目 `C:/Users/lee/Documents/InkStructApp/InkStruct-Windows-Dev`，Git HEAD `af45b45f04f899fcaced43aa980b0508673ee6c0`，包含保留的未提交工作。**保留可选数量机制：9574字生成、来源回放、14份开发分片校验及小文档验收已完成。完整8上限用户字体超过原2GiB限制，不能作为一份可直接使用的完整字体交付；全库字形尚未人审。**

APP_VERSION 仍为 **0.1.45**，本轮不构建、不发布。冻结运行真实标记为 **v6.2 exp**，版本 `desktop-semantic-v62-20261020.1`；讨论中的后续名称 **v6.3 exp 尚未实施**，不能倒改已产生的协议或将本轮结果改称 v6.3。Python 库、字体和文档格式版本均未随之变更。

## 已实现的最小变化

- 生成页可直接输入每字成品上限 **1–64**，默认 **4**，数量包含原主字形；偏好单独保存。v6.1/v4 仍为单份，GUI 禁用多份控件，服务接口显式拒绝这两种方法传入大于 1 的数量。下层原接口默认单份保持兼容。
- 1 份不搜索额外字形；其余数量的尝试预算为 `max(16, 数量×4)`，因此 **4→16 次、8→32 次、64→256 次**。一次尝试指一个完整替换方案；两部件联合算一次，但仍分别执行两次最终上下文检查。失败、重复及被拒方案同样消耗预算。
- 沿用已实现的完整部件均衡遍历、同一来源字不同真实样本、有限双部件组合与最终整字检查，不引入随机扰动、网络或新生成方法。不足时保留真实合格份数，不补画或复制凑数。
- 制包导入全部合格候选；排版仍按出现位置选样并冻结，旧字体、旧文档及其选择不自动修改。字体成员、总量和点数上限保持原值。

生产改动限于 `src/inkstruct/generation_variants.py`、`generation_workflow.py`、`desktop.py`。开工状态、旧源码包、冻结源码及逐文件哈希保存在 `artifacts/candidate_count_full_20261104/`；没有 reset、clean、提交、推送或改动独立 Layout-Dev 目录。

## 输入和可确认的来源边界

最终输入为 `input_audit/all_user001_hanzi_425.jsonl`，SHA-256 `c866eaf3ddff36238128adadd533a3f4ba8d3e15c695a2303c35ccdd24f3cd93`。最终档案为 `input_audit/profiles_all_capture/user_001/b46b32ddfc6ef1b8.json`，SHA-256 `cebd00d9a4a90a9508c5907a5aff87280eee8aa6f2343014b47ba0361cc4e120`。

| 阶段 | 样本数 | 来源汉字数 |
|---|---:|---:|
| 完整归一化汉字采集 | 425 | 314 |
| 原笔顺/对齐检查后风格档案 | 376 | 281 |
| 原来源映射检查后有效真实供体 | 366 | 274 |

49 份笔顺含糊、8 份无法明确一对一映射、2 份映射低置信，均沿用原构建器排除并保留理由。目标集扩大或缩小时，始终使用同一份完整有效供体池；没有按目标字删减供体，也没有混用 user_002。

旧 409 索引仅含部分补录；同批原始补录中原作留出的 16 份另存加入后得到 425 份。故本轮是**开发全库验证，不能再称独立留出泛化评测**。原 338 研究档案、旧划分及409先行档案保留。691 份字母、数字、标点等符号另行识别，未混入汉字供体。

真实补录 40 份可以从原 ZIP 重算字节 SHA；历史基础 **385 份原文件在本机缺失**，只能核查其归一化点列、压力、时间和保留的原 SHA，不能声称独立复核了原文件字节。逐份清单、排除理由、ZIP 链条和1416个只读来源文件的保全核验见 [输入审计](../artifacts/candidate_count_full_20261104/input_audit/REPORT.md)。

环境为 Windows 11 AMD64、Python 3.13.16、NumPy 2.5.4、PySide6 6.9.2，18逻辑处理器、平衡电源方案；未新增依赖。桌面后台负载未受控，部分原生补验与计算重叠；耗时仅为观察成本，不据此宣称受控加速比。完整环境见 `environment.json`。

## 已完成的验证

**134 项针对性回归通过，0失败、0跳过，8.77秒**；覆盖生成工作流、目标/资源、串并行、候选、字体导入、字符校正及Qt数量控件。日志 `test-limits-agent-review-02.xml`。其后只补充2/3/23份的预算和实际数量参数，**42项数量专项通过，1.65秒**，见 `coordinator-free-range-01.xml`；与134项重叠，仅新增6例，不能相加为176项。当前专项实际触及1/2/3/4/8/23/64，2、3份仍为16次预算，23份为92次，并验证32次全拒绝、最后一次联合、取消锁存、任务局部限额及原字体资源边界。另一组115项集成回归也通过，同样不能与上述重复计数。

`test-summary.json` 按JUnit的`(classname, name)`对134与42两次最终运行去重，共 **140个独立用例ID、0失败、0跳过**；这是跨两次运行的去重覆盖数，不是一次140项合跑结果。

首次专项有一例测试错误地假定v6.1会将显式8转换为1，按实际明确拒绝语义修正；后续取消夹具最初未锁存事件，在联合第二次检查时错误清除取消，修正为真实事件行为后通过。两次原失败记录保留，未据此修改生产校验。

Windows原生源代码窗口（1160×950逻辑像素、DPR1.5）实际验证默认4/16、输入8/32、切换v6.1和v4为禁用的1份、返回v6.2恢复8份，均通过。私有设置和工作区避免触碰生产数据。原生补验没有点击开始生成；忙锁、持久化与参数捕获由Qt回归覆盖，不能混称原生生成验证。记录与截图见 [native-ui/REPORT.md](../artifacts/candidate_count_full_20261104/native-ui/REPORT.md)。

固定11字“嘤喳啜哮构沐孔正果馈我”使用最终档案完成8份串行两重复、8份四进程及4份串行：

- 两次8份串行与四进程的全部逐字压缩payload、提交标记**原始字节完全一致**，无字段排除。各11完成、0失败、48候选。
- 4份得到28候选；4→8的原主payload（只剔除候选池及其尝试日志）和官方制包主CID全部相同。原4份算法与新4份的四组隔离fixture重放亦完全一致。
- 8上限实际结果：嘤、啜、哮、构、沐各8份，果3份，其他五字各1份。喳、孔、馈来源警告保留。**啜、哮的4份候选既不是8份前缀也不是子集**；稳定的是原主候选，不是数量不同任务间的所有额外候选。
- 全部候选经原来源变换、压力、笔内时间回放，4/8字体完整校验均通过；字体压缩965,943/1,677,221字节。8串行墙钟13.58/13.84秒，4串行12.85秒，四进程9.34秒；有后台负载且重复数有限，不作为正式性能结论。
- 从 `source-before.zip` 独立提取全部260份旧包源码，新进程确认原 **0.1.45 / MAX4**，所有inkstruct模块均来自旧根。该旧读者完整校验48候选字体，并对六字重复96处选样、保存重开、冻结和严格SVG通过。未直接测试打包EXE，也不能由“能读现成字体”推断“旧生成任务importer能制包8份”。

原始生成、两份实验字体、旧源码副本、文档、SVG和逐项比较见 [small-consistency/REPORT.md](../artifacts/candidate_count_full_20261104/small-consistency/REPORT.md) 与 `small-consistency/comparison.json`。这些字体只含小字集，不是用户原完整字体的替换包。视觉对照图 `eight-candidate-contact-sheet.png` 仅展示实际候选，数量或来源差异不能替代自然度人审。

## 全库执行与真实异常

完整目标来自实际结构库的9574个支持字符；保留简体《通用规范汉字表》2013交集及不支持项，不能把9574等同于9574个简体字。

第一批 `full_validation/full-01` 在218.448秒时，实验runner发布 `progress-current.json` 的原子替换收到Windows `PermissionError`，进度回调异常触发了原标准串行回退。尚无证据将其归因于计算子进程、候选或用户数据错误。1020.44秒时通过取消文件安全停止，3552份逐字提交完整保留；其中“檑”在额外候选搜索中已取消，预算停于4次、仅2份，不能当作完整8上限搜索结果。

仅修实验runner可选current快照的发布：有限重试并把拒绝写入权威JSONL，不再向标准生成进度回调传播该 `PermissionError`。其他异常未笼统忽略。第一批runner事前没有记录自身SHA，后以反向应用已记录补丁重建并明确标注；第二批启动前封存runner和SHA，不能把重建件冒充第一批启动前的原字节捕获。

第二批以新目录 `full-02`、相同源码和输入SHA、4进程完成6023/6023项、0失败、无串行回退，runner墙钟862.851秒。目标为6022个原未完成字加“檑”，重算“檑”的5项主字段保持一致。原批次不改写；一次显式选择ledger选用第一批3551字、第二批6023字，已合为9574字验证视图。合并器核对源码、作者及五份任务资源快照身份一致，逐字记录来源和payload SHA；这不是跨运行自动续跑能力。

每15秒采集启动器、runner及当时存活子进程，第一/二批工作集峰值分别为2,205,941,760/2,378,575,872字节，private峰值为2,698,186,752/2,975,121,408字节。这些是采样峰值下界，不是OS绝对峰值。原始进程树JSONL与 `resource-summary.json` 保留；runner自身采样没有psutil，不能把其CPU时间当作全部工作进程成本。

| 全库核验项 | 当前状态 |
|---|---|
| 第二批完成数、失败数及总成本 | 6023/6023，0失败，4进程、无回退；墙钟862.851秒 |
| 合并9574字及逐字选择ledger | 3551旧＋6023新；来源与源码SHA一致，原批次保留 |
| 来源回放、数量/预算、候选唯一性 | 9574字、36194候选、29,471,335点；0审计错误，来源回放669.274秒 |
| 实际候选分布、来源完整/缺口 | 6370字来源完整、3204字保留原缺口；5072字多份，其中2645字达到8份 |
| 简体表支持交集 | `cn-tgh-2013`在结构库支持的6866字全部覆盖，28420候选，其中26533份来源完整；另1239字不受结构库支持，清单保留，未冒充已生成 |
| 分片校验 | **14/14完整校验通过**；合计9574字/36194候选/29,471,335点，3204份原来源警告保留，全部包SHA复核通过 |
| 完整用户字体单包 | **不可成立：轨迹本身2,971,481,083字节，保守总上界3,044,015,585字节，已超过2GiB** |
| 来源完整小文档 | 6字实际选8/8/8/8/8/3候选，288处冻结选样、3页；保存重开快照/选样精确一致，严格SVG逐页字节一致 |
| 来源警告回归文档 | 孔正果馈我，240处冻结选样、3页；保存重开一致，孔/馈原缺口保留；**本份诊断文档没有请求严格SVG，不能记为已导出** |

| 每字实际候选数 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 字数 | 4502 | 443 | 435 | 416 | 436 | 382 | 315 | 2645 |

全量停止原因另见 `candidate-stop-summary.json`：2645字达到8份；14字触及32次提案预算；3711字在**当前检索和准入机制**下无更多不同合格候选；3204字因主来源缺口不搜索额外候选。最终视图没有候选搜索被取消的行。3711不能解释为证明完整作者供体池中不存在任何潜在来源；本轮也未为14个预算耗尽字追加尝试或放宽规则。

后验使用原 `check_sources` 回放点列变换、压力和笔内相对时间，并沿用 `make_generated/build_font/FontPackage.verify`。全库来源回放无错误，不代表原有3204字的真实缺口消失，也不代表字形自然度合格。简体覆盖仅指表中结构库支持的6866字，不隐瞒不支持项。

14份开发包总压缩1,372,349,578字节、解压7,159,916,555字节。来源回放669.274秒、制包及完整校验1365.181秒，后验总2034.479秒；**这是后验阶段成本，不是生成总时间**，生成两个批次另分别为1020.439和862.851秒。实际后台负载及阶段边界见各原始记录。

从合并全库结果另制的验收字体包含10字、47候选、34,648点，完整校验通过，其中孔、馈两份来源警告保留。来源完整文档使用“嘤啜哮构沐果”，其43个真实候选均实际被选中；来源回归文档使用“孔正果馈我”，仅验证保存重开并保留诊断。完整结果见 `full_validation/full-combined-01-document/document-check.json`，没有把可导出标记冒充已执行严格导出。

**实际容量是当前交付阻碍。** 即使去掉development成员，用户版轨迹就已超过2GiB；index/metrics/provenance分别另需27,000,787/3,619,401/22,334,410字节。未制造超限包，也未提高限制。开发包按完整的单字候选池和保守512MiB预算划分为14份，并继续执行单成员32MiB、总量2GiB等原检查；分片使用相同font_id不同release，应用当前不会将它们同时作为一套字体选样。不能将“14份验证包”描述为“全库8份已能在当前应用中直接使用”。本轮11字已通过独立子集包流程，其他目标集仍须按实际体量和原限制校验；全库单包或跨包统一使用能力尚未实现。

**全库未逐字人审，来源完整、规则通过及包完整均不等于全库自然度合格。**

## 准确命令与产物

以下在项目根目录PowerShell执行；保留原始目录，所有输出必须另选不存在的名称。完整实际命令及恢复边界另见 [full_validation/README.md](../artifacts/candidate_count_full_20261104/full_validation/README.md)。

```powershell
# 源码应用入口；不指定workspace时沿用应用原默认工作区
.venv/Scripts/python.exe -B -X utf8 -m inkstruct.application

# 新的一次全库8上限验证；不运行已存在的full-01目录
.venv/Scripts/python.exe -B -X utf8 artifacts/candidate_count_full_20261104/full_validation/run_full_full02_snapshot.py --source-root artifacts/candidate_count_full_20261104/frozen-source --profile artifacts/candidate_count_full_20261104/input_audit/profiles_all_capture/user_001/b46b32ddfc6ef1b8.json --database artifacts/structures/characters.sqlite3 --references third_party/makemeahanzi/graphics.txt third_party/makemeahanzi/dictionary.txt configs/structure_overrides/unclipped_reference_v1.json --output artifacts/candidate_count_full_20261104/full_validation/replay-full-01 --workers 4 --candidate-limit 8 --cancel-file artifacts/candidate_count_full_20261104/full_validation/replay-full-01.cancel

# 本轮实际第二批使用封存runner、明确剩余字表及独立full-02目录；原命令留档，不覆盖执行
.venv/Scripts/python.exe -B -X utf8 artifacts/candidate_count_full_20261104/full_validation/run_full_full02_snapshot.py --source-root artifacts/candidate_count_full_20261104/frozen-source --profile artifacts/candidate_count_full_20261104/input_audit/profiles_all_capture/user_001/b46b32ddfc6ef1b8.json --database artifacts/structures/characters.sqlite3 --references third_party/makemeahanzi/graphics.txt third_party/makemeahanzi/dictionary.txt configs/structure_overrides/unclipped_reference_v1.json --output artifacts/candidate_count_full_20261104/full_validation/full-02 --workers 4 --candidate-limit 8 --characters-file artifacts/candidate_count_full_20261104/full_validation/remaining-targets.txt --cancel-file artifacts/candidate_count_full_20261104/full_validation/full-02.cancel

# 相关选集复现；历史134通过后另有数量专项新增6例通过，选择新的日志/临时目录
.venv/Scripts/python.exe -B -X utf8 -m pytest tests/test_generation_candidate_limits.py tests/test_generation_variants.py tests/test_generation_variant_balance.py tests/test_generation_parallel.py tests/test_generation_workflow.py tests/test_generation_targets.py tests/test_generation_resources.py tests/test_font_packages.py tests/test_font_import.py tests/test_glyph_corrections.py tests/test_candidate_count_qt.py tests/test_generation_targets_qt.py -p no:cacheprovider --junitxml=artifacts/candidate_count_full_20261104/replay-tests-01.xml --basetemp=artifacts/candidate_count_full_20261104/replay-tests-temp-01

# 本轮已执行的合并与后验命令留档；产物已存在，复现必须另存驱动/输出位置
.venv/Scripts/python.exe -B -X utf8 artifacts/candidate_count_full_20261104/full_validation/merge_batches.py
.venv/Scripts/python.exe -B -X utf8 artifacts/candidate_count_full_20261104/full_validation/audit_full.py --source-root artifacts/candidate_count_full_20261104/frozen-source --run artifacts/candidate_count_full_20261104/full_validation/full-combined-01/generation --output artifacts/candidate_count_full_20261104/full_validation/full-combined-01-audit
.venv/Scripts/python.exe -B -X utf8 artifacts/candidate_count_full_20261104/full_validation/document_check.py --source-root artifacts/candidate_count_full_20261104/frozen-source --run artifacts/candidate_count_full_20261104/full_validation/full-combined-01/generation --output artifacts/candidate_count_full_20261104/full_validation/full-combined-01-document
```

本轮实际核验入口另有 `input_audit/verify_preserved.py`、`small-consistency/run_serial.py`、`small-consistency/compare.py`、`small-consistency/extract_old_reader.py`、`small-consistency/old_reader.py`；后三类驱动的原输出已存在，重放前另存目录，不能覆盖旧证据。

最终机器汇总：[final-validation-summary.json](../artifacts/candidate_count_full_20261104/full_validation/final-validation-summary.json)。逐字/逐候选回放、14包路径、大小和SHA见 `full_validation/full-combined-01-audit/audit.json` 与 `characters.jsonl`；逐字批次来源见 `full_validation/full-combined-01/selection-ledger.json`；验收字体、两份文档和实际导出SVG位于 `full_validation/full-combined-01-document/`，结果为 `document-check.json`。这些都是本轮独立产物，没有替换用户原完整字体。

源码快照、原始测量、失败日志、采集审计、生成批次、字体、文档和SVG均保留；未将实验字体写入生产字体库，未自动重选旧文档。没有本轮新EXE或安装包；正式交付时仍需按当时APP_VERSION递增并做Windows构建验收。

最终保全核验见 `input_audit/preservation_verify_20261104T051147820889Z.json`：1416个只读输入文件全部未变。`preservation-verification.json` 核对开工269份源码/测试文件，仅3份授权应用源码有修改；当前260份运行源码与冻结副本完全一致。历史 `artifacts/windows_release_0.1.45/` ZIP的SHA-256仍为 `f663047b09db7322c0f57748151129b8009e4a6804118e3e2130ec7ea9370fe4`。其余仓库新增为两份测试、本记录及文档索引链接，原索引已备份为本轮产物目录中的 `docs-readme-before.md`。

仅清理已核实位于本轮产物目录下的9个pytest可重建临时目录及 `full_validation/__pycache__`，逐项操作记录见 `cleanup.json`。14份真实字体、输入、源码副本、全部日志、原生截图、文档与SVG均保留。

## 决定与最小下一步

最终状态：**全库机器/协议验证完成，数量机制保留；完整8份单包当前容量受阻，未全库人审，不发布。** 保留默认4份和有界尝试机制；14份开发分片不具有同时作为一套字体使用的能力，本轮不交付完整8份单包，不构建。

下一步直接使用现有“自定义字表/从文档提取汉字”能力，只为实际排版需要的字集生成并制成经过原限制校验的小包，保留完整供体池、来源警告、选样和冻结语义，再根据真实使用反馈决定正式交付范围。本轮不再追加规则、协议、跨包框架或实验。
