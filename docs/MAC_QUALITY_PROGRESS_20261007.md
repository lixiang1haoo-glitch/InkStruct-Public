# Mac 迁移与轨迹保真阶段记录

后续状态已更新：见 [2026-10-12 原计划对照与下一阶段优先级](QUALITY_STATUS_AND_NEXT_STEPS_20261012.md)。本页描述 Mac 迁移首轮结果，文中尚未实现的 T2/T3/T4 后来已有实现或实验，不应从此页重新开始开发。

日期：2026-10-07。源码起点 `2b4f681`，工作分支 `codex/mac-quality-foundation`。本轮完成 Mac 运行环境、真实作者抽样回归、高保真原稿通道及压缩诊断。问题 2 的新曲线解码、问题 3 的上下文部件检索、问题 4 的实例变体尚未实现；生产生成仍为原有 v4 adaptive。

## 数据恢复

参照用户提供的《问题说明_图文整理版.docx》及讨论截图，继续沿用 9 月 12 日计划。网络原目录的 Git 提交为 `458e508`，早于当前源码，因此未覆盖代码。

恢复并逐文件验证 SHA-256：结构数据库、样本索引、原始 JSON、历史 profiles、外部采集器内核，共 2,411 个文件、469,357,578 字节。私人清单位于 `artifacts/migration/assets.json`，包含来源路径、目标路径、大小与哈希。迁移脚本位于同目录 `restore_assets.py`，遇到同名不同内容会拒绝覆盖。

| 作者 | 索引样本数 | 原始文件哈希缺失 | 旧档案接纳数 | 新通道保留数 |
| --- | ---: | ---: | ---: | ---: |
| mjb | 772 | 0 | 456 | 436 |
| scx | 793 | 0 | 785 | 778 |
| wsq | 793 | 0 | 本轮未重建 | 本轮未重建 |

mjb 原有 316 个排除样本、scx 原有 8 个排除样本，重建后数量保持一致。新通道另外拒绝不完整一对一或低置信映射的 20 / 7 个样本，不改变它们在旧建档逻辑中的处理方式。

旧 `profiles/<writer>/profile.json` 未覆盖。新扩展档案单独保存在 `profiles/source_v1_20261007/`：mjb 为 `90e8fb249bedef2c`，scx 为 `c5cfd48ab0fea9c5`。早期诊断版本保留在本地，当前版本以该目录下 `profile.json` 为准。

CASIA 训练数据、神经模型权重、旧 Windows 虚拟环境与完整历史输出没有全量迁移。旧输出仅复制固定回归字集及原 manifest；原网络目录保持不变。`user_001` 的历史 profile 随 profiles 目录保留，其原始索引未包含在本次三作者数据恢复范围内。

## 真实作者回归

`scripts/check_writer_regression.py` 对每位作者固定 256 字，包含附件案例，并按旧 profile 实际接纳的样本字符划分 128 已见 / 128 未见。排除样本不计入已见；同字重复样本不会跨组。该字集是工程回归集，尚未由人类指定为“原来好看的保护集”。

三方比较为原 Windows 存档、固定旧提交 `c2c180d` 在 Mac 重算、当前边界修复输出。先核对 profile、索引及旧 manifest 身份，再运行。输入哈希、固定字表、A/B 对应关系、逐字边界信息和协议验证均保存到报告。

| 作者 | 检查字数 | 存档与重算差异 | 边界修复改变 | 未适配却改变 | 协议失败 |
| --- | ---: | --- | --- | ---: | ---: |
| mjb | 256 | 逐点一致 | 囊、純 | 0 | 0 |
| scx | 256 | 18 字仅压力末位相差不超过 0.000001；几何、时间和其他字段一致 | 勾、匈、囊、翱、軾、緘 | 0 | 0 |

最终有效报告及匿名 A/B 页面：

- `artifacts/mac_quality_20261007/baseline_mjb/report.json` 与 `comparison.html`。
- `artifacts/mac_quality_20261007/baseline_scx/report.json` 与 `comparison.html`。

同目录早期的 `mjb`、`scx`、`scx_verified` 是排查阶段产物，最终统计只使用 `baseline_*`。初筛按索引是否存在分组；最终更正为按旧 profile 是否接纳分组，因此 mjb 最终适配字从初筛的 3 个变成 2 个。

所有改变字的整体对照图已检查，未见边界截平继续存在；这不代表全库风格质量、人类偏好或交叉问题已验收。默认算法未做新的几何替换。

复跑示例（输出目录必须是新的）：

```bash
.venv/bin/python scripts/check_writer_regression.py \
  --writer scx \
  --old-run "/path/to/old/InkStruct/outputs/scx/all_supported_component_trajectory_v4" \
  --profile profiles/scx/profile.json \
  --index artifacts/samples/scx/index.jsonl \
  --output artifacts/writer_regression_scx_new
```

## 高保真通道与版本身份

`AlignedGlyph.source_normalized_strokes` 保留同一次等比归一化后、未经 16 点降采样的轨迹，按捕获笔顺排列。匹配算法、16 点数组、8 点原型、40 维模型 token 保持原有行为。

`source_trajectory_v1` 是 StyleProfile 的独立可选扩展。每份样本保存 source sample_id、字符、原始 SHA-256、笔顺状态；各笔保存标准 stroke_id、原稿 user_order、完整坐标、逐点压力、原始时间和弧长参数。几何、压力和时间使用同一标准到原稿映射。错序修正后跨笔原始时间不保证全局递增，后续解码器需要重新分配输出时间，不能直接拼接。

歧义、拆合笔或任一笔映射置信度低于 0.30 的样本不进入新通道。缺少原稿通道时明确返回缺失，不从旧控制点伪造原稿。旧 JSON 可直接读取，新 JSON 可以往返保存；未知扩展版本被拒绝。

开启方式：

```bash
.venv/bin/inkstruct profile build --writer scx \
  --destination profiles/source_v1_new \
  --retain-source-trajectories
```

生成器暂不消费该扩展，因此开关不会改变既有轨迹算法。它会增大 profile 文件；关闭时不会保存完整源轨迹。

新 profile_version 哈希包含建档器版本、作者、索引、结构逻辑内容、模型身份、扩展版本和关键参数。结构身份通过 SQLite 同一快照读取语义元数据和字符图，覆盖已提交但仍在 WAL 中的变更；排除机器路径和构建时间。建档期间仍应冻结索引和结构库，不支持边建档边修改输入。

## 折钩压缩诊断

`scripts/diagnose_source_trajectory.py` 保存源轨迹、16 点、8 点、平滑重采样四阶段，另存实际生成的画布适配前后轨迹及 style_source / component_key。该压缩探针隔离采样损失，不包含生产路径中的原型平均、布局和混合，不能把探针的百分比称为最终生成误差。

对 scx 附件案例的真实样本：

- “岛”第 4 笔，源轨迹到探针平滑阶段的弧长缩短约 21.1%，最大原始顶点到重建折线距离约 0.0717。
- “尴”第 3 笔，对应约 9.4% 和 0.0627。

坐标为统一归一化字框。最大偏差是一侧的原始顶点到目标线段距离，不是对称 Hausdorff 距离。诊断图与数据在 `artifacts/mac_quality_20261007/diagnostics_scx/`；所选其他案例在该作者索引中没有原稿，报告明确列出缺失字符。

```bash
.venv/bin/python scripts/diagnose_source_trajectory.py \
  --writer scx --index artifacts/samples/scx/index.jsonl \
  --profile profiles/scx/profile.json --characters 岛尴 \
  --output artifacts/source_diagnostics_scx_new
```

## 验证与下一步

Mac 环境为 Python 3.13、NumPy 2.5.3、Pillow 12.3.0、PySide6 6.9.2。准确依赖快照在私人文件 `artifacts/migration/requirements-macos.txt`。60 项测试通过，4 项可选 PyTorch 检查跳过；Ruff 和 shell 语法检查通过。采集器与生成器离屏启动、截图检查通过；未验收真实数位板或 Mac 应用打包。

测试覆盖矩形画布比例、纠正笔顺下的几何/压力/时间一致性、歧义和低置信隔离、旧档案兼容、新档案往返、开关前后生成笔画一致、结构 WAL 变更引起版本变化、外部内核路径，以及旧存档压力容差不得放宽到几何。

下一步沿既有计划推进 T2：锁定端点、稳定折点与短钩，以误差上限重建，先仅用于合格的同字复杂笔，再进行开发/留出集及人工对照。T1 尚缺完整的逐候选来源、融合权重、剔除链和生产布局中间点追踪；当前诊断不得冒称已经覆盖这些阶段。之后再做 T3 的攵嵌套部件视图和 T4 的真实实例变体。未达到人工质量门槛前继续保持现有默认生成路径。
