# 跨字同部件：自然变化参考与完整实例抽样实验

2026-10-07。用户确认暂无同作者同字重复采样，并指定可用不同字中的相同部件判断变化是否自然。本轮已完成真实数据实验、图文对照、源码及完整性核验；不改生产默认，不接入 CLI/GUI 默认入口。

## 结论

不同字的同部件可以建立作者的**部件形状相容性参考**。它不能独自保证某个真实供体适合目标字：wsq 的 28 个未使用留出字中，26 个真实部件落在经验范围内；所有字都获得 3–5 种实际输出形状，但变化路径未通过开发阶段的质量门槛。

| 集合 | 路径 | 几何均差 | 末向均差 | 弧长绝对相对差 |
|---|---|---:|---:|---:|
| scx 开发 32 字 | 固定 A | 0.038638 | 19.69° | 15.51% |
| scx 开发 32 字 | 确定性完整源轨迹 D | 0.037645 | 17.32° | 15.26% |
| scx 开发 32 字 | V 精确期望 | 0.037924 | 17.80° | 15.58% |
| wsq 确认 28 字 | 固定 A | 0.035174 | 17.85° | 18.49% |
| wsq 确认 28 字 | D | 0.033930 | 19.29° | 17.91% |
| wsq 确认 28 字 | V 精确期望 | 0.034661 | 22.18° | 19.99% |
| wsq 确认 28 字 | V 五次实际输出均值 | 0.034387 | 22.86° | 20.35% |

确认集 V 精确期望相对 D：几何偏差增加 **2.16%**，末向增加 **2.89°**。开发允许的上限为 +1% 和 +0.5°，因此不推广随机变化。五次种子抽样按字汇总，不能解释为 140 个独立目标。弧长越接近原稿不等于质量越好。

本轮 28 字来自前轮 wsq 64 字之外的剩余相容留出目标；wsq 并非全新作者。6 组均为左右结构左侧部件：亻 11、口 7、女 3、阝 3、氵 2、讠 2。高频部件覆盖不能外推到全部汉字。

## 方法与数据隔离

- 固定既有 A 档案、训练划分、目标布局、最多 16 个结构相容候选，以及原完整轨迹 D 的共同等比变换和安全检查。V 只改变近优候选的选择。每个候选仍拟合自己的整体变换，不拆散部件，不逐笔缩放，不加坐标噪声。
- 按作者、canonical、variant、role、parent layout、笔数分组。部件仅整体平移和等比归一化。描述量包含 16 个等弧长匹配锚点、归一化笔长及 8%/20% 窗口末向；匹配锚点绝不写回输出。
- 目标字在参考计数、去重和阈值拟合前排除；当前运行只使用训练字。生成实例评分还排除供体的整个字符组及相同形状副本，防止“复制原稿得到零距离”。同字所有采样归同组，重复文件不增加参考证据。
- 每组至少 8 个不同字的独立形状。训练字留一后算最近异字距离，先按字取中位数，再取 95% 经验分位数。该分位数是几何参考范围，**不是 95% 自然概率**，也不是美学评分。
- V 从分数距最优不超过 margin、且符合经验范围的完整实例中按映射置信度和分数差加权抽样。少于两个合格独立形状则保留 D。种子、目标字符、出现位置和部件 ID 联合确定抽样，支持复现。
- margin 预设为 0、0.0025、0.005、0.01；只在 scx 32 字开发集选择，冻结为 0.01。scx 只有 10/32 字有足够参考，其他字保持确定性。确认集不调参数。
- 全部选择和输出先完成，之后才读取目标原稿进行评分和绘图。公开结构信息可参与选择；作者目标原稿不可参与建档、布局拟合或候选排序。

D/V 使用相同表示，所以本轮衡量的是候选变化贡献。A 与 D 同时改变了轨迹表示和来源策略，不能用这里的差值单独证明表示改进；原 A/B/C/M 表示对照见 [原始轨迹实验](RAW_TRAJECTORY_EXPERIMENT_20261007.md)。

## 视觉证据与不变量

本地图文报告（Git 忽略）：

- `artifacts/exemplar_variation_20261007/wsq_confirmation_v1/report_final/InkStruct_跨字同部件变化报告.html`
- 同目录 `gallery.html`：28 字完整图集；每字含原稿、A、D、V1–V5 的同尺度整字和局部图。
- `figures/cohort-1.png` 至 `cohort-6.png`：6 类真实部件与生成部件整体归一化对齐图。展示候选中的最多 8 个不同来源字，不冒充完整参考分布。
- 同目录 `integrity_audit.json`：196 输出全部通过笔数、标准 ID、笔顺、坐标有限、坐标范围、压力范围和全局单调时间检查。
- D/V 共 **25,890 个源点**逐项验证：坐标是同一部件共同等比变换，压力及笔内相对时间保留。跨笔时间按输出笔顺重新安排。
- 无相对 A 新增严格笔间交叉。该检测不覆盖笔宽接触、自交，也不承诺清除 A 原有交叉。

“噢”的 V2/V4 保留了真实供体口旁末横的回钩，但目标原稿末端接近向右。真实且符合作者部件分布的动作，依然可能与目标的上下文不符。真实留出部件“渌、婀”超出参考范围，也不能据此称原稿不自然。

所有生成 V 均符合经验范围是筛选条件，不是独立验证；真正的留出检验是 26/28 个目标原稿落在范围内，以及对目标的几何、末向与布局评估。没有同字多次原稿，因此不声称验证了同字重复书写分布或用户阅读偏好。

## 实现、复现与接入建议

新模块：`component_variation_evidence.py`、`exemplar_variation.py`。既有 `SourceComponentGenerator` 仅增加默认行为相同的可覆盖选择方法；`VariedSourceComponentGenerator` 为实验子类，默认 `seed=None`、`margin=0`，关闭变化。`occurrence_id` 允许调用者区分出现位置；现有字典式 CLI 不因此获得逐次文本输出能力。本轮负结果不扩展正式入口。

```bash
.venv/bin/python scripts/experiment_exemplar_variation.py prepare-development \
  --output artifacts/exemplar_variation_20261007/development_NEW
.venv/bin/python scripts/experiment_exemplar_variation.py evaluate \
  --output artifacts/exemplar_variation_20261007/development_NEW
.venv/bin/python scripts/experiment_exemplar_variation.py prepare-confirmation \
  --development artifacts/exemplar_variation_20261007/development_NEW \
  --output artifacts/exemplar_variation_20261007/confirmation_NEW
.venv/bin/python scripts/experiment_exemplar_variation.py evaluate \
  --output artifacts/exemplar_variation_20261007/confirmation_NEW
.venv/bin/python scripts/report_exemplar_variation.py \
  --development artifacts/exemplar_variation_20261007/development_NEW \
  --input artifacts/exemplar_variation_20261007/confirmation_NEW \
  --output artifacts/exemplar_variation_20261007/confirmation_NEW/report
```

每次使用新目录；已有文件会拒绝覆盖。冻结计划记录输入、代码、协议 SHA-256；每例记录完整候选、来源哈希、共同变换、抽样概率、种子、位置、去重标识和回退原因。个人档案、坐标及图文均留在 Git 忽略目录。

直接变换适合完整真实部件形态、位置、笔数相容且能共同放置的场景，可保留源折钩和关系；不适合差异过大的结构、噪声或退化源稿，或必须逐笔变形才能适配的目标。当前继续保留确定性原轨迹及受限简化的实验开关，**不替代平滑默认**。下一阶段应在独立开发资料上加强上下文和末向约束，再用新的留出目标验证；这 28 字不能调参后继续冒充未观察留出集。

验证：全套 `pytest` 为 **97 passed, 4 skipped**；新增 5 项测试覆盖共同归一化、目标/供体/副本隔离、证据不足回退、关闭路径一致性、种子复现及整部件坐标/压力保真。相关文件 Ruff 检查通过。跳过项沿用环境可选依赖条件。
