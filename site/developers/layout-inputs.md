# 排版输入与模板

本文描述 InkStruct **0.1.69** 的排版输入。用 UTF-8 Markdown 交换正文，用 [`.inkdoc`](./inkdoc) 一起保存页面设置、嵌入资源和冻结选样。接入时先检查结构，再检查资源，最后渲染。[CLI 与快速开始](./cli)

## Markdown 与公式

| 内容 | 写法与边界 |
| --- | --- |
| 段落与结构 | 支持标题、列表、引用、行内代码、围栏代码、链接、脚注和任务列表。普通链接排版时使用显示文字 |
| 公式 | 行内用 `$...$`，独立公式用另起行的 `$$` 围栏。公式采用 InkStruct 支持的 LaTeX 子集，例如分式、根式、上下标和矩阵 |
| 表格 | 使用管道表格，单元格可包含行内公式。显式换行可用 `\newline` |
| 图片 | 用 Markdown 图片引用本地资源，先用小样检查版面及资源是否成功载入。原图导出和写字机路径导出有各自的图片处理规则 |
| Obsidian 方言 | 显式指定 `--dialect obsidian`。双链如 `[[target\|显示名]]` 使用显示文字，带显示名的嵌入作静态标签处理 |

下面的输入可保存为 `notes.md`。公式、脚注和链接分别保留自己的语义节点。资源检查会按实际可见字符和公式构件报告缺口。

```markdown
# 示例

公式 $\frac{1}{2}$ 和[参考资料](https://example.org/)。[^method]

[^method]: 这里记录计算方法。

| 次数 | 结果 |
| --- | --- |
| 1 | $x^2$ |
```

```powershell
& $python -m inkstruct.cli document inspect notes.md
& $python -m inkstruct.cli document resources notes.md
```

## 换行、换页与换框

- `\newline` 或 `\linebreak` 在段内强制换行。
- `\newpage` 或 `\pagebreak` 在正文中推进到下一页。`\clearpage` 在当前没有浮动队列时也推进到下一页。
- `\framebreak` 用于模板正文流，推进到下一正文框。自动续排足够时，可以直接写连续正文。

## 页面模板

模板 JSON 描述页面布局、正文框及可选的固定字段。项目保存使用的模板和正文。先生成一份中性 A4 模板，再检查几何和可用字段：

```powershell
& $python -m inkstruct.cli document template new --format v3 --output template.json
& $python -m inkstruct.cli document template validate template.json
& $python -m inkstruct.cli document template inspect-slots template.json
```

### 命名字段

上述简单模板只有正文框。有自定义命名字段时，用 `inspect-slots` 报告中的 `fields` 与 `markdown_skeleton` 获取真实字段名，再在源文档中填入：

```markdown
:::field title
实验记录
:::

正文继续正常书写。
```

这里假设模板声明了 `title`。字段块以单独一行 `:::` 结束。模板 v3 使用正文里的字段块。旧模板若使用节点绑定，可通过 `template inspect-content` 获取项目摘要和节点，再用 `template bind --bindings ... --output ...` 另存。两种入口的参数见 `document template --help`。

对已有项目用 `document template validate-document file.inkdoc` 核对实际内容能否排进页面，检查报告的 `exportable`、`plotter_exportable` 和 `diagnostics`。模板几何有效只是其中一步，实体写字机还需要单独对位。[模板命令实现](https://github.com/lixiang1haoo-glitch/InkStruct-Public/blob/app-v0.1.69/src/inkstruct/document/template_authoring.py)
