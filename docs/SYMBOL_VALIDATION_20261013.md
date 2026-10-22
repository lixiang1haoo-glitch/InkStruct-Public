# user_001 新符号实样验证

2026-10-13。输入为 `/Volumes/A/AGENT/InkStruct/20261013/user_001符号录制.zip`，SHA-256 为 `dab29626b1ac59af195dafb1062e6d9695d82bae9e14e0dfeda05ec45f717d35`。本次验证使用原始采集轨迹，未修改 ZIP，也未覆盖历史项目。

## 结果与入口

有效交付目录为 `artifacts/symbol_validation_20261013/result/`。此前同级试跑目录保留排查过程；以 `result/verification.json` 为本次实样结论。

- [混排原生项目](../artifacts/symbol_validation_20261013/result/mixed/mixed.inkdoc)：在 Markdown 混排工具中打开，已内嵌所需汉字和本批符号资源，无需重新指定原 ZIP。
- [混排预览第一页](../artifacts/symbol_validation_20261013/result/mixed/preview/page-001.png)与[第二页](../artifacts/symbol_validation_20261013/result/mixed/preview/page-002.png)：13 个公式，含普通/伸缩括号、分式、根式、上下限、矩阵、分段、对齐与表格。
- [混排机器 SVG 第一页](../artifacts/symbol_validation_20261013/result/mixed/machine/page-001.svg)与[第二页](../artifacts/symbol_validation_20261013/result/mixed/machine/page-002.svg)：仅 path 元素，只有绝对 M/L 指令，已优化并允许反转。
- [全部样本对照](../artifacts/symbol_validation_20261013/result/atlas.html)：每字所有样本、笔数与样本 ID，统一 em 比例展示，附参考线。
- [全部样本原生项目](../artifacts/symbol_validation_20261013/result/specimens/specimens.inkdoc)：两页，逐一固定选中全部 405 份样本；对应 `specimens/machine/` 中也有严格 SVG。这里使用代码块的字面网格，以便独立陈列标点，不套用正文行首/行尾禁则。
- [缺字采集清单](../artifacts/symbol_validation_20261013/result/missing-letter-capture.csv)：当前采集字表中的英文大小写、希腊大小写及变体，共 108 类，每类 5 份。它是后续采集任务，不表示所有这些变体已支持公式命令。

## 样本清点

共 80 个字符、405 份样本。79 字符各 5 份，小数点 10 份；其中数字 50 份、数学及标点 355 份。没有英文或希腊字母，不能据包名推定已经齐备。

全部经生产 `SymbolProvider.from_zip` 导入，坐标、压力、时间序列及资源身份通过校验；保存的笔画/点数与轨迹一致。405 份均为可绘制中心线，没有需要单点转线的样本。∇ 存在 2/3 笔写法，∏ 存在 4/5 笔写法，均原样保留。

全批使用同一采集坐标系：420×240 逻辑像素，em 为 150 px，基线 y=187.5 px，数学轴为基线上方 0.25 em。原始记录全部为 `guide_based_unreviewed` 和 `review_status=unreviewed`；导入、自动校验及查看预览没有改成人工“合格”标签。

## 验证范围

逐样本项目用固定选择覆盖 405 个不同资产；混排项目按稳定实例身份从各字样本池选取。保存重开后，快照、选样记录与所有内嵌原始 JSON 完全相同。数学部分逐点检查了 14,284 个点，确认字形只做统一比例缩放和平移；分数线、根式横线与伸缩定界符是独立结构构件，不冒充采集笔画。

54 个已有资源的公式命令逐一通过实样布局。此次发现空集等符号有资源却缺命令映射，已补上 `\emptyset`、`\ni`、`\uparrow`、`\downarrow`、`\perp`、`\parallel`、`\angle`、`\prime`。保持 ∥ 与 ‖ 不同身份；不将 `\varnothing` 偷换成现有空集字形。

混排两页空行程总和由 7553.19 mm 降至 3027.99 mm，减少 **59.9%**；逐样本两页由 6799.04 mm 降至 2495.04 mm，减少 **63.3%**。从每页原点出发，按现有路由距离模型统计；不是书写耗时测量。核对每条输出路径，优化只改变排序或逐点反转，笔画未缺失、增加、平滑或简化。

已查看两页混排预览和四张全部样本对照图。未见样张中公式与表格裁切；普通括号保留采集大小，较高分式的伸缩括号由结构构件生成。小数点包含微小斜划写法，后续纸面应重点确认小数点与逗号的辨识、细小笔迹和环路积分的可读性。此项是观察与试写建议，不是自动质量判定。

表格继续使用宽 160 mm、最小行高 8 mm、数字高度参数 3.8 mm、四边留白 0.3 mm。高分式自动撑开所在行；3.8 mm 是数字字库标定框的目标高度，并不把每个不同写法拉伸到相同墨迹高度。

全量回归 **1219 passed、4 skipped**，相关 Ruff 检查通过，日志为 `artifacts/symbol_validation_20261013/full-tests.log`。同期模板正文续排的专项 100 项通过，详见 [缓存说明](MARKDOWN_CACHE.md)。未执行新的性能基准。

## 后续边界

M4-02 的“实际符号导入和验证”已有新证据；英文/希腊实样、人工 baseline/math-axis 标定和纸面/写字机验收仍待完成。当前能导出不等于已证明硬件书写效果。整体 Markdown 混排目标继续进行，未提交、推送或切换分支。

以上数值对应 `result/` 的固定原生项目；打开该项目可重现已存选样。以下命令会创建新的源码实例身份，因而允许选到同一字符的其他样本，统计可能不同。复现流程时使用新目录：

```sh
.venv/bin/python scripts/validate_symbol_samples.py \
  '/Volumes/A/AGENT/InkStruct/20261013/user_001符号录制.zip' \
  --run outputs/full_library_20261010/user_001/all_supported_v4_adaptive_20261010 \
  --output artifacts/symbol_validation_rerun
```

`inventory.json`、`capture-audit.json`、`command-probes.json` 与 `verification.json` 分别保留样本清单、采集核查、命令实样覆盖和排版/路由结果。
