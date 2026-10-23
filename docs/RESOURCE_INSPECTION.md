# 文档字形与采集缺口检查

2026-10-13。`document resources` 可读取 Markdown、原生 `.inkdoc` 和旧 `.inktable`，列出当前资源中缺失的可见字符及录制公式构件，输出 Windows 采集器兼容 CSV，每个缺失字符 5 次。扫描不保存项目，也不改变内存中的原选样；已有 CSV 不覆盖。

## 原生项目

```sh
.venv/bin/inkstruct document resources path/to/report.inkdoc --capture-csv artifacts/new-capture.csv
```

继承项目中的 Obsidian/普通 Markdown 方言、三类公式构件来源、资源和选择记录。隐藏的双链目标不成为采集需求，任务方框/图片占位不被当成普通字符。只使用项目内嵌资源，不能同时指定 `--run` 或 `--symbols`；旧 `.inktable` 导入仍需它所引用的样本包存在且哈希一致。

已有资产/标定丢失时返回恢复资源诊断，不能自动换用另一个样本。扫描需要做出新选择时，只在临时副本中选择，结果列在 JSON 中，不写回 `.inkdoc`。原项目可以处于缺字草稿状态，但语法错误必须先处理，避免把未知语法误转为采集任务。

## Markdown 原文

```sh
.venv/bin/inkstruct document resources example.md --symbols /path/to/samples.zip --fraction-source sample --radical-source sample --delimiter-source sample --capture-csv artifacts/new-capture.csv
```

三项来源可分别设为 `geometric` 或 `sample`；原文默认几何模式，原生项目默认继承已保存的模式，也允许显式覆盖用于比较。原生覆盖仅影响这次报告，不改项目设置。原文中的汉字可加 `--run`，Obsidian 原文加 `--dialect obsidian`。

原文检查按明确提供的字库统计采集需求，不自动添加内置数字池；原生项目若已经内嵌内置数字，会视为可用。内置数字可用于布局验证，但不应被解释为作者已经采集过相应数字。

## 结构需求与报告

| 录制模式 | 字形需求 |
| --- | --- |
| 分数线 | 数学减号 `−`，不等同于 ASCII 连字符 `-` |
| 根号 | `√`；根指数依然使用普通数字/符号资源 |
| 定界符 | left/right 的对应字符、矩阵或分段括号、公式编号及 eqref 的圆括号；不可见一侧不采集 |

定界符和矩阵的对应关系与实际排版共用定义。array 规则线、向量修饰线、普通几何模式结构不额外请求字体。`‖` 与 `∥` 等不同字符不自动合并。脚注、表格及固定区源块中的公式同样纳入检查；重复展示同一实例不会增加 CSV 重复行。

JSON 的 `construction_requirements` 给出每个构件的字符、源区间和与排版一致的 occurrence ID，`math_sources` 记录实际采用的三项来源，`gaps` 合并同一字符的缺口及所有源区间。可采字符进入 CSV，汉字和不支持的字符集群保留在 JSON 供处理；同一字符缺少多处仍只采 5 次。

检查范围是资源存在及已有选样能否恢复，**不验证字形几何、根号分段识别、数学轴校准、分页尺寸或机器可写性**。因此即使缺口为空，`machine_export_ready` 仍为 false；正式排版和导出负责最终诊断。不能用空 CSV 证明一份报告已经可交给写字机。

## 证据

`tests/test_document_resources.py` 覆盖 11 类结构、独立模式、精确源范围与布局身份一致、只读选样、旧选样不可恢复、Obsidian 原生继承/覆盖、Unicode 区分、定义内公式、退化字形与就绪状态区分，以及两种旧表格资源模式。专项 19 项通过；全量 1293 passed、4 skipped（收集于最后两项旧表格专项加入前），后补两项已包含在专项通过记录中。

真实验证为 `artifacts/markdown_resource_scan_20261013/result/`：四页 M5 项目含 23 个录制结构需求，完整包零缺口；另建草稿去掉 `−√()` 后恰有四类缺口，CSV 各 5 次。扫描前后输入哈希一致，原真实项目和用户 ZIP 未改动。根目录的第一次试跑将需求数预期误记为 20，实际逐式核对为 23；仅 `result/` 是完成验证的产物，脚本 `verify_real.py` 保留复现过程。
