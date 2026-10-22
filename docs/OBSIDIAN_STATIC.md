# Obsidian 静态排版扩展

日期：2026-10-13。该方言按混排计划的 M5 范围实现双链可见文字、Callout 和带显式标签的嵌入引用。它与普通 Markdown 分开启用，默认关闭；不读取或扫描 Obsidian 库，不执行链接、不递归展开引用，也不引入 Obsidian 插件或 CSS。

## 入口和项目兼容

混排编辑器“内容模式”旁新增方言下拉框，选择“Obsidian 静态扩展”。切换只影响解析和预览，不改写源码；切回“普通 Markdown”后按原规则处理。纯文本检查模式下方言控件禁用。

`FlowStyle.markdown_dialect` 取 `markdown` 或 `obsidian`。字段随 `.inkdoc`、恢复副本保存；旧项目缺少字段时为普通 Markdown。原生 manifest 同时保存对应方言版本，加载时校验与 flow 一致；不一致或未知值报错。旧版本应用不能把新方言项目悄悄按普通 Markdown 解释。语义 content key 含方言身份，异步结果与缓存随切换更新，原文字锚点和资源选样不重置。

命令行原文渲染需同时指定 Markdown 模式和方言；原生项目省略方言时继承已保存选择，可显式覆盖。

```sh
.venv/bin/inkstruct document inspect example.md --dialect obsidian
.venv/bin/inkstruct document resources example.md --dialect obsidian
.venv/bin/inkstruct document render example.md --mode markdown --dialect obsidian --plotter --output new-machine --save-project example.inkdoc
.venv/bin/inkstruct document render example.inkdoc --plotter --output reopened-machine
```

命令中的输出目录须为新目录。使用真实汉字、英文等仍需原有 `--run` / `--symbols` 资源；内置数字和小数点可直接测试。CLI 的 `edit` 仍用原入口，方言在窗口内选择或从项目读取。

## 双链与嵌入标签

Obsidian 使用 `[[目标|显示文字]]` 自定义双链文字，并允许目标带标题或块位置。这里保留目标作为语义属性，仅排版可见文字；无别名时显示原目标文字。语法依据见 [Obsidian 内部链接](https://obsidian.md/help/links)。

```markdown
[[资料/实验#结果|12.50]]
[[资料/实验#^记录|计算结果]]
![[附件/原始记录|13.25]]
```

别名按字面文字处理，别名中的星号等不再触发嵌套 Markdown；不读取 aliases 属性、不解析目标是否存在。每个可见字符映射到自己的源码区间，点击定位别名字符；修改隐藏目标路径不重选已有别名字形。目标路径不会进入字形采集缺口列表。

Obsidian 的 `![[...]]` 本来表示嵌入内容，见 [官方嵌入说明](https://obsidian.md/help/embeds)。本阶段仅接受带非空显式标签的静态引用，并始终给出 `obsidian-embed-label-only` 提示，说明目标没有展开。未提供标签的嵌入产生错误，阻止成品导出。图片/PDF 目标的纯数字或 `宽x高` 参数会诊断为尚未支持的尺寸语法，避免误当标签；实际图片继续使用已有 Markdown 图片与资源导入流程。

空目标、空标签和多个别名分隔符明确报错。跨行、嵌套方括号或尚未闭合的双链保持普通文本解析；不猜测作者意图。行内/围栏代码、转义的左方括号和数学内部不识别双链。HTML 表格内部仍按原有受控 HTML 规则处理，不新增 wiki 方言解析。

管道表格仍需要转义别名分隔符：

```markdown
|次数|计算值|
|---|---|
|1|[[资料/实验\|12.50]]|
|2|![[附件/原始记录\|13.25]]|
```

## Callout

仅当块引用的第一个直接段落首行符合 `[!类型]` 时识别 Callout。支持自定义标题、无正文标题、嵌套以及紧随类型后的 `+/-` 元数据；语法参考 [Obsidian Callout](https://obsidian.md/help/callouts)。

```markdown
> [!note]- 计算结果
> [[资料/实验|实验数据]]
>
> - [x] 12.50
> - [ ] 13.25
>
> > [!tip]+ 计算结果
> > $\frac{12.50+13.25}{2}=12.875$
```

纸面布局始终展开全部正文，包括标为折叠的 Callout。标题独占一块，并尽量与首个正文行同页；内容可正常续页。外观使用已有可书写引用线和缩进，不复制颜色、背景、图标或 CSS 主题。标题可包含公式、强调及双链；正文共享任务、表格、公式、脚注等已有布局能力。

无自定义标题时显示类型标识符的首字母大写形式，字符来源对应标识符本身。类型名限 1–64 个 ASCII 字母、数字、下划线或连字符且以字母开头；类型大小写不影响元数据。缺少标题所需英文样本会按正常缺字机制诊断，不用普通字体替代。代码或普通段落中的 `[!note]`、块引用后续段落中的同样文本都保持字面处理。

## 验证与边界

新增 `tests/test_obsidian.py` 26 项和实际 Qt 测试 1 项，覆盖方言隔离、CRLF/非 BMP 来源、标签显示、缺失/歧义嵌入诊断、代码/转义/数学边界、嵌套/默认标题、任务/表格/脚注组合、分页、编辑/撤销/选样、原生保存重开、manifest 不一致拒绝、旧项目默认值，以及 CLI 检查/资源/渲染与实际界面切换。

全量 **978 passed、4 skipped，32.90 秒**，相关 Ruff 通过。此前 **57 页机器 SVG** 按原配置回放逐字节一致。静态扩展不会修改表格默认 160 / 8 / 3.8 / 0.3 mm 或优化自动反转策略。

本机七页项目为 `artifacts/markdown_mixed_m5_20261013/obsidian/obsidian-report.inkdoc`，源码样例 `examples/markdown_obsidian_m5.md`。新内容包含 9 个 wiki 引用（其中 4 个显式嵌入标签）、3 个 Callout（含嵌套与脚注内 Callout），与既有模板、公式、图形及脚注混排。验证包括源实例覆盖、标签来源、导出门槛、严格 path/M/L、排序反转保真和 CLI/原生一致；实际页面及 Qt 源码定位/嵌入提示截图已查看。

本轮没有实现库导航、链接自动补全、回链、递归引用内容、动态嵌入、Obsidian 属性/CSS/插件兼容。Windows 输入法与缩放、纸面和写字机行为仍需对应实机验收。
