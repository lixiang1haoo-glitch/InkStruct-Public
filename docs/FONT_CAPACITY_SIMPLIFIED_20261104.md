# 单包容量与简体字集字体空间对照

2026-11-04，Windows 开发源码验证。项目为 `C:/Users/lee/Documents/InkStructApp/InkStruct-Windows-Dev`。**实测支持保留本轮有限4 GiB容量调整：两包完整校验及小文档通过。简体支持字集＋相同其余字符，ZIP省25.7%、展开量省26.0%；简体包仍超旧2 GiB约102.2 MiB。没有正式发布，不能把本机两包通过扩展为所有4 GiB内容或大文档安全。**

APP_VERSION 保持 **0.1.45**，未构建或发布新应用；生成方法、原采集、旧字体、文档及冻结选样不自动修改。实验复用上一轮同一作者档案、完整生成结果与候选，未重跑全库生成。

## 最小源码改动和边界

只在 `src/inkstruct/fonts/core.py` 将总展开容量从 **2 GiB 调整为 4 GiB**，并在原写入循环累计成员字节，在加入最终manifest后再次核对；超过同一总量或100,000成员的结果不能通过最后的非覆盖链接发布。32 MiB单成员、100,000点/候选、路径/重复/加密/链接、哈希与来源检查保持。

4 GiB是本轮有限的工程策略，不是唯一或数学最小值。已测全包3,046,226,671字节低于3 GiB（3,221,225,472字节），3 GiB也能容纳这一个包，约有5.4%的阈值余量；这里仅比较已测字节，不另造3 GiB大型实验。4 GiB不是新格式或新生成方法，也不是“只需4 GiB内存”的承诺，更不证明任意4 GiB内容或全库大文档已安全。字体仍为原协议1.0。旧2 GiB读者能否读取本次包以实际展开大小及旧读者试验为准，不能因为语法未变就假定兼容。

字体metadata常驻，普通编辑器按文档涉及字符加载全部候选；默认`cached_font`仍会逐成员哈希，初次打开可能等待。最多4个验证进程各持有索引，也会增加内存。`.inkdoc`的200 MB压缩、500 MB展开、资源目录128 MB及布局点数等原限制不变。本轮不增加新的缓存框架、不放宽文档保护。

源码封存在 `artifacts/font_capacity_simplified_20261104/frozen-source/`，开工源码及Git状态在同名实验根。本文其余无前缀的实验路径均相对该根。

## 同一输入，只改变输出汉字范围

| 对照臂 | 汉字范围 | 相同的其余字符 | 已核验字符/候选数量 |
|---|---|---|---|
| 全结构库＋符号 | 上一轮9574个支持条目 | 固定206字符、1306候选 | 9780字符、37500候选 |
| 简体支持交集＋符号 | 《通用规范汉字表》2013与结构库交集6866字 | 同一份固定符号包 | 7072字符、29726候选 |

简体臂使用已有 `cn-tgh-2013` 版本化字表，保留共用字；8105字中当前结构库不支持的1239字明确另列，不转换正文、不猜字形、不补画。结构库中的部首/部件目标属于汉字生成臂，不能仅依“非汉字Unicode”混入符号臂。输出范围缩小不删作者供体，所有共有生成结果直接复用已验证记录。

汉字来自上一轮 `candidate_count_full_20261104/full_validation/full-combined-01-audit` 的14份已验证分片。当前符号输入详见[符号核查](../artifacts/font_capacity_simplified_20261104/input_audit/REPORT.md)：

- 691份当前补录加405份历史原始符号，共1096份、185个原录字符；排除已重录旧版本与重复工作区副本，未混入user_002。
- 现行共享/合成规则得到206字符、1306候选，包含英文正斜体、数字、希腊及变体、标点、数学运算符与既有℃、–、～、*、∗、∶、∘，以及现行ℏ和全角点规则。
- 未把209条skipped任务当作确认复用；斜体和希腊的真实来源不足保持。当前没有已确认复用声明，不能擅自把相似字符当作已录。
- 与最全旧包的1096个原录候选逐份核对，geometry、pressure、time、trajectory、metrics及summary一致。旧包没有当前规则的ℏ和全角点；这是既有规则差异，不是本轮新增合成。

两臂共用 `input_audit/user_001-symbols-fixed-full-validation-namespace.inkfont`，SHA256 `c00e0639aa0571fb9a76f8300933d60e6fe071bc32e9f15c41863fa3a76a8a12`。固定namespace避免重新命名导致星号确定性配对变化。比较复用原candidate_id、record、metrics、provenance及轨迹原字节，不以重新编码或减少每字候选数量换空间。两包的release/core_hash/asset_id不保证相同，删去字符后容器身份本就会变化；旧文档不自动改资源。

## 已完成的源码回归

容量专项 **30项通过**（`tests/agent-capacity-03.xml`，0.983秒）；包含该专项的相关选集 **106项通过**（`tests/agent-capacity-regression-01.xml`，5.332秒），有重叠，不能相加。覆盖总量包含最终manifest、恰等边界、字节/磁盘成员、原单成员/点数/路径/加密/哈希等保护、旧小包兼容及非覆盖发布。边界由隔离的小阈值夹具验证，真实包测量至3,046,226,671字节；没有额外制造完整4 GiB边界包。

前两轮原始日志保留：首次pytest临时目录设置失败；随后Windows zipfile先规范化反斜杠，路径夹具未触发预期守卫，改为直接隔离原元数据守卫后通过。没有删除危险路径检查来通过测试。

## 两包实际测量

两包均已写成并经4进程完整校验。数据见 `package-experiment/run-01/result.json`，共同身份及输入来源见 `selection-ledger.json`。以下为同种user包、相同其余字符、同字最多8份的直接对照；不能与上一轮包含development的14片体积混比。

| 指标 | 全结构库＋相同符号 | 简体支持交集＋相同符号 | 实际节省 |
|---|---:|---:|---:|
| 字符 | 9,780 | 7,072 | 2,708 |
| 候选 | 37,500 | 29,726 | 7,774 |
| 点 | 29,577,993 | 21,871,273 | 7,706,720 |
| 压缩文件字节 | 611,140,081 | 454,351,365 | **156,788,716（25.655%）** |
| 展开总字节 | 3,046,226,671 | 2,254,681,346 | **791,545,325（25.984%）** |
| 轨迹JSON字节 | 2,979,550,032 | 2,201,975,462 | 777,574,570 |
| index.json | 27,975,548 | 22,176,144 | 5,799,404 |
| metrics.json | 3,766,008 | 2,988,608 | 777,400 |
| provenance.json | 23,038,126 | 18,112,273 | 4,925,853 |
| manifest.json | 11,896,899 | 9,428,801 | 2,468,098 |
| license.txt | 58 | 58 | 0 |
| 来源提醒候选 | 3,204 | 1,887 | 限定输出范围后少引用1,317份，未重分类 |
| 完整校验 | 37,500份通过 | 29,726份通过 | 两臂均4个进程 |
| 旧2 GiB源码读者 | 拒绝“字体展开大小超限” | 同样拒绝 | 不是旧EXE实测 |

**仅简体节省约四分之一，但没有降到原2 GiB保护以内。** 简体包仍超出2 GiB **107,197,698字节，约102.2 MiB**；该限制按成员展开量计算，不按约433.3 MiB的压缩文件计算。两个包都低于本轮4 GiB，并保持单成员32 MiB等原保护。本次实际包未触发ZIP64成员，不把Python的理论支持称作ZIP64实测。

写包观察耗时全包43.680秒、简体包32.097秒；首次metadata-only对象构造0.975/0.688秒（未清空操作系统文件缓存），完整校验阶段44.429/32.966秒（该阶段计时包含metadata构造），四个验证进程。脚本总167.417秒，原轨迹字节提取8.811秒。metadata-only数字不能当作GUI默认`cached_font`端到端打开速度；这些是单次、当前桌面负载下的成本，不是重复受控性能结论。

包SHA256：

- 全结构库：`f5f31eab653c6fd79144a16f09c8d27a55943653ad03cd26ad18542a51a07605`。
- 简体支持交集：`2be8d239326f3a1a62dc21455c2b822be48abc11e6d23d1407fe2008ccc047e5`。

制包实验一次缓存已知的原轨迹字节供两臂共享，开跑要求至少8 GiB可用内存；这是本次比较脚本的明确前提，不是普通排版读取全部点列的实现，也不是正式新增缓存组件。完整校验前释放这份临时字节缓存。metadata-only构造和四进程校验的耗时见上表。15秒进程树采样的11份记录中，观察到最大工作集3,384,905,728字节、private 3,381,587,968字节，系统最少可用11,093,299,200字节，最多5个存活进程；这是有限间隔的观察峰值，可能漏掉短峰，不是OS连续峰值，也不是GUI整体体验测量。原始采样与汇总在 `package-experiment/run-01/resource-summary.json`。

## 从真实大包读取与文档验证

两包共有的29,726份candidate record、metrics、provenance精确相同，原轨迹字节直接复制。不同容器身份不作为字形差异；同一SourceSession身份和seed下，原出现位置所选sample一致。

最终 `package-experiment/document-check-03/result.json` 直接读取两份大包，以中英、数字、希腊正文αβγ及数学`\alpha+\beta=\gamma`、℃、～、∶、∗、ℏ、全角点和短公式验证：

| 项目 | 全结构库包 | 简体支持包 |
|---|---:|---:|
| 按需准备候选 | 234 | 234 |
| 候选准备耗时 | 0.382秒 | 0.283秒 |
| 页数/冻结选择 | 3页/187处 | 3页/187处 |
| 实际选到“嘤/沐/果”写法 | 8/8/3份 | 8/8/3份 |
| 保存重开快照与选择 | 精确一致 | 精确一致 |
| 本包SVG保存重开前后字节 | 精确一致 | 精确一致 |

两臂SVG页面几何一致，实际出现位置的candidate选择一致。**2条`math-calibration-unreviewed`警告保留**，未将待审校准改为通过。小文档读资源、排版、保存重开和SVG的总脚本耗时3.884秒；这不是原生应用启动或交互延迟测量。

此前 `document-check-02` 的无希腊小样也独立保留：219候选、3页179处，两包保存重开和严格SVG通过，1条同类校准警告。最终03仅补入实际包已有的αβγ及其短公式，没有修改字体、原检查或新增生成案例。

首次将多种标点直接连排的fixture被现有`forbidden-line-boundary`检查阻断，原runner、原文和诊断保留在 `package-experiment/document-check-01/`。随后使用独立短段落复核包读取与几何，不能宣称原连续标点排版问题已修复。该失败没有引起规则或诊断改动。

希腊字母的来源与候选都在完整包校验内，所列αβγ已做实际文档检查；没有逐个希腊字符、全部符号或全库字形的人工自然度评审，也没有原生应用冷打开测试。

## 复现和证据

从项目根目录执行，所有输出目录必须不存在；不覆盖本轮字体或历史资源。

```powershell
.venv/Scripts/python.exe -B -X utf8 artifacts/font_capacity_simplified_20261104/package-experiment/compare_packages.py --source-root artifacts/font_capacity_simplified_20261104/frozen-source --symbols artifacts/font_capacity_simplified_20261104/input_audit/user_001-symbols-fixed-full-validation-namespace.inkfont --output artifacts/font_capacity_simplified_20261104/package-experiment/replay-01

# 该脚本当前使用包含希腊的最终fixture，输出必须为新目录
.venv/Scripts/python.exe -B -X utf8 artifacts/font_capacity_simplified_20261104/package-experiment/check_documents.py --source-root artifacts/font_capacity_simplified_20261104/frozen-source --run artifacts/font_capacity_simplified_20261104/package-experiment/run-01 --output artifacts/font_capacity_simplified_20261104/package-experiment/replay-document-01
```

- 容量实现依据：[只读审查](../artifacts/font_capacity_simplified_20261104/capacity-review/REPORT.md)。
- 符号原始快照、录制修订、共有字节身份及1387输入保全见 `input_audit/`。
- 两包选择ledger、实际大小、最终SHA和完整校验结果已在 `package-experiment/run-01/` 记录。
- 实际字体：[简体支持集＋其余字符](../artifacts/font_capacity_simplified_20261104/package-experiment/run-01/user_001-simplified-supported-8-candidates-and-symbols.inkfont)、[全结构库＋相同其余字符对照](../artifacts/font_capacity_simplified_20261104/package-experiment/run-01/user_001-all-supported-8-candidates-and-symbols.inkfont)。均是本轮独立新包，不是旧字体的就地更新。
- 完整结果：[两包结果](../artifacts/font_capacity_simplified_20261104/package-experiment/run-01/result.json)、[含希腊的文档验证](../artifacts/font_capacity_simplified_20261104/package-experiment/document-check-03/result.json)、`run-01/resource-summary.json`。
- 本轮仍未证明低内存机器、全库文字同时排版或旧冻结EXE的兼容；不将源码实验称为正式交付。

## 保全与当前决定

`preservation-verification.json`最终核验：开工263份文件中，仅授权的 `src/inkstruct/fonts/core.py` 和文档索引有修改；260份应用运行源码与本轮冻结副本一致，1387个只读符号输入未变，历史0.1.45 ZIP的SHA仍为 `f663047b09db7322c0f57748151129b8009e4a6804118e3e2130ec7ea9370fe4`。本次两个新包的最终SHA也重核一致。只保留本轮最小core差异为 `capacity-core.patch`，便于后续共享文件协调；未改独立Layout-Dev、生成规则或作者档案。

仅清理3个已核实的新pytest临时目录及 `package-experiment/__pycache__`，见 `cleanup.json`。原始日志、首轮失败fixture、输入快照、源码副本、新两包、文档、SVG和旧字体均保留；没有自动导入生产字体库或更换旧文档资源。


**保留本轮4 GiB有界容量策略及发布前保护。仅简体输出确实节省约四分之一空间，共有候选和原迹不变，所列中英/希腊/数学小文档可用。** 简体包仍需新上限读者；既有2 GiB源码读者对两个真实包均明确拒绝。没有新EXE，不自动替换当前用户字体或旧文档，不将本轮源码验证称为正式发布。使用这两个包需本轮4 GiB策略的源码读者；现有2 GiB策略不支持，不能仅看ZIP低于2 GiB就判断可读。优先使用有明确来源的简体支持集配相同符号库，可节省本次磁盘文件约149.5 MiB；需要其他结构库汉字时保留全库对照包供明确选择。本轮不追加生成规则、随机扰动、神经网络或新的跨包协议，不扩大到未经验证的完整开发者大包。
