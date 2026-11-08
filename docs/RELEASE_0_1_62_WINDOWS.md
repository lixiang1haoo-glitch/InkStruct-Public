# InkStruct 0.1.62 · Windows

2026-11-08。完整解压 [InkStruct-0.1.62-Windows-x64.zip](../artifacts/handoff_0.1.62_20261108/release/InkStruct-0.1.62-Windows-x64.zip)，运行 `InkStruct.exe`。

- 制作字体包时，打开「复用与合成规则」可逐项决定本次是否启用。「本次启用」「供体确认」和「已核对结果」分别显示。关闭同形共用或规则合成只取消该规则生成的候选，独立录制仍按类别选用。
- 原「确认复用」改称「借用已有笔迹」。可沿用采集任务中已确认的供体，也可直接在制包窗口预览并选用一份具体供体。应用后自动刷新覆盖，刷新期间不可制包。所选供体绑定当前样本内容。
- 规则设置只用于本次制包窗口。换作者或扩展来源时重新读取默认规则和采集任务确认。制包仍在完整验证后原子入库。

参见 [符号目录与复用规则](SYMBOL_CATALOG.md)。

## Windows 实窗

在真实作者样本的隔离副本中，取消规则编辑后覆盖保持一致。应用停用设置后，同形逗号、合成 `℃` 和已确认借用的希腊 `Α` 从覆盖中移除，独立录制的半角逗号仍在。随后重新启用 `℃`，覆盖恢复。预览并选用一份正体 `m` 供斜体栏借用，入包来源与所选样本及 SHA-256 一致。最终完整验证并入库 205 个字符、1,302 份候选，与清单一致。采集任务、样本、旧字体和文档的哈希一致，文档 5,129 条冻结选样一致。[实窗截图和验收结果](../artifacts/handoff_0.1.62_20261108/native-verified) · [实窗日志](../artifacts/handoff_0.1.62_20261108/native-verified.log) · [制包日志](../artifacts/handoff_0.1.62_20261108/native-verified/workspace/publication-logs)

## 构建与回归

从 0.1.61 发布基线的独立干净检出实施，从提交 `380201ff0c77dca9d0eaed3fa49ef90b96d0893f` 的干净检出构建。注解标签为 `app-v0.1.62`。发布 ZIP 的 SHA-256 为 `19984b3ee244ea1c0f8b79baa64a73ff5e39a515ae6ee911a7eca1f7c2ea0266`。[发布自检日志](../artifacts/handoff_0.1.62_20261108/delivery.log)

源码回归 207 项通过，4 项模板用例与 0.1.61 已知失败一致。新增回归核对目录和 ZIP 的开关、供体内容变化和实际入包来源。两个 EXE 的版本及公式自检通过，多候选自检重开冻结文档的 SVG 一致。343 项构建输入和 10 项公开资源通过复核，0.1.61 发布 ZIP 哈希与原记录一致。[回归日志](../artifacts/handoff_0.1.62_20261108/regression.log) · [包内多候选自检](../artifacts/handoff_0.1.62_20261108/frozen-candidates/verification.json) · [Git 验证记录](releases/0.1.62-git-verification.json)

本轮未验证 macOS、采集硬件或全库生成。LaTeX 手册源码已同步，PDF 未重新编译。
