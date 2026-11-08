# InkStruct 0.1.61 · Windows

2026-11-08。解压 [InkStruct-0.1.61-Windows-x64.zip](../artifacts/handoff_0.1.61_20261108/release/InkStruct-0.1.61-Windows-x64.zip) 后保留完整的 `InkStruct` 目录，运行 `InkStruct.exe`。

- 生成页以「内置字表」「导入字表」「从文档提取汉字」「从当前排版提取」选择目标。主页面只显示所选范围和字数，可打开只读清单。结构库全部汉字在内置字表弹窗中作为独立选项。
- 采集和待制包清单共用固定字符目录。制包按类别勾选，展开可查实际字符、编码、候选份数和来源。「复用与合成规则」逐条显示规则设置、所需来源和本次结果。规则沿用现有同形共用、确认复用与规则合成机制。
- 数学减号 `−` 与标点连接符 `-` 归入不同类别。合成 `ℏ` 时仍可使用合格的 `-`，它需通过本次标点选择进入候选池。旧采集任务按原类别索引解释，旧任务和确认配置继续读取。

具体字符划分及规则见 [符号目录与复用](SYMBOL_CATALOG.md)。

## Windows 实窗验收

- 在真实作者数据的隔离副本上，验证了按钮选择和只读目标清单。结构库全选项与命名字表互斥，导入 TXT 后替换目标并成功生成。复测一键建档、补录回滚、取消后的部分批次和上一批按钮。
- 采集目录区分连接符 `-`、数学减号 `−`、括号及单位。旧格式任务副本仍按原类别索引读取，文件哈希一致。规则表列出 87 个映射或合成目标。取消英文正体后，`℃` 显示已启用但缺少正体 `C`，已确认的希腊 `Α` 仍可入包。
- 模拟最终验证失败和发布失败后重试，入包 197 个字符、1,004 份候选，与当时的清单一致。原样本及旧字体哈希一致，旧文档 5,129 条冻结选样一致。[截图与实窗验收产物](../artifacts/handoff_0.1.61_20261108/native-verified) · [实窗日志](../artifacts/handoff_0.1.61_20261108/native-verified.log) · [制包日志](../artifacts/handoff_0.1.61_20261108/native-verified/workspace/publication-logs)

## 发布

从 `codex/windows-release-baseline` 的 0.1.60 干净检出开始。构建提交为 `0ac407defeb164d9aa633bef96a744f8bf671bb8`，注解标签为 `app-v0.1.61`。发布 ZIP 的 SHA-256 为 `748fafe96fe168daf6eabf55e6676d2fd030b00daa6938c3d5af3cf04045f324`。[交付日志](../artifacts/handoff_0.1.61_20261108/delivery.log)

源码回归 205 项通过，另 4 项模板管理测试与 0.1.60 已知失败一致。341 项构建输入和 10 项公开资源哈希复核通过。两个 EXE 的版本和公式自检均通过，包内多候选自检的串行及双进程均生成 4 字、16 份候选，重开冻结文档的 SVG 一致。0.1.60 发布 ZIP 哈希与原记录一致。[源码回归](../artifacts/handoff_0.1.61_20261108/regression-final.log) · [多候选自检](../artifacts/handoff_0.1.61_20261108/frozen-candidates/verification.json) · [Git 验证记录](releases/0.1.61-git-verification.json) · [构建输入清单](releases/0.1.61-build-provenance.json)

实窗验收选择并查看了结构库全量范围，生成采用小字集。本轮未运行全库生成，未验证 macOS 或采集硬件。LaTeX 手册源码已同步，PDF 未重新编译。
