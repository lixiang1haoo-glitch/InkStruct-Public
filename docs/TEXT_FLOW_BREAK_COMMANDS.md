# 换行、分页与正文换框

2026-10-26 已合入主应用 InkStruct 0.1.41。独立 Layout Preview 包作为历史产物保留；本文描述当前物理分页与正文换框规则。本机合并和 Windows 验收见 [交付记录](RELEASE_0_1_41_WINDOWS.md)。

内容工作流是：AI 读取 [Markdown 生成规范](AI_MARKDOWN_SPEC.md) 和用户要求，生成 Markdown；用户复制粘贴或导入，再预览、检查资源并导出。命令直接写在 Markdown 中，不增加插入分页符或换框符的界面操作。

## 命令与范围

| 命令 | 当前行为 |
| --- | --- |
| `\newline` | 强制换行。 |
| `\linebreak`、`\linebreak[4]` | 强制换行，不拉伸现有字形和字间距。 |
| `\newpage` | 跳到下一物理页；模板正文流中跳过当前页剩余正文框。 |
| `\pagebreak`、`\pagebreak[4]` | 强制跳到下一物理页，同上。 |
| `\clearpage` | 下一物理页；当前没有浮动图表队列，因此与 `\newpage` 的可见效果相同。 |
| `\framebreak` | **仅连续正文流模板**：跳到下一个编号正文文本框；可能仍在同一物理页。 |

分页在普通 Markdown 页面和模板正文流中生效。换框只在模板 v3 的连续正文流中生效；普通页面和旧版固定区域绑定提示 `frame-break-inactive`，继续排正文。

分页与换框均不推进表格单元格、脚注、图片说明或固定字段：在这些位置给出非阻断的 `page-break-context` / `frame-break-context` 提示，不把命令名当作待采集字符。字段内容不能改变正文游标。代码区及纯文本模式保持字面文本。

## 例子

假设每页有 A、B 两个正文框，按 A → B 顺序续流：

```markdown
第一张纸的 A 框。\newline{}
仍在 A 框，另起一行。

\framebreak

从同一张纸的 B 框开始。

\newpage

第二张纸的 A 框。

\pagebreak

第三张纸的 A 框。
```

若在第一张纸的 A 框使用 `\newpage`，同页 B 框留空，后文从第二张纸的第一个正文框开始；使用 `\framebreak` 则进入同页 B 框。从最后一个正文框换框时，后文进入后续页第一个可用正文框。没有正文框的模板布局按既有起始/循环页组顺序跳过，仍保留物理页序。

命令可独占一行，也可位于段内、强调或列表中。后文按新框宽度重新断行；段内续文不重复首行缩进或列表标记。列表开头先换框时，标记随正文进入新框。

分页命令在空白页开头不额外制造空页，连续分页不会产生夹空页。文首 `\framebreak` 可跳过首框，连续换框逐个推进。所有尾随控制在没有后续内容时均不额外创建输出页；模板的“补齐循环页组”规则独立生效。

## 参数与边界

`\linebreak[n]`、`\pagebreak[n]` 接受 0–4 的整数，默认 4。4 强制执行；0–3 是非强制提示，不保证在该处换行/分页。低强度换行提示允许原本连续的文字或数字在该处断行。现有排版器不实现完整 TeX 的全局罚分、不同弱强度优先级和段落拉伸；需要确定位置时使用默认强度或 `[4]`。非法值和未闭合参数定位报错。

`\newline`、`\newpage`、`\clearpage`、`\framebreak` 没有强度参数。使用空组终止控制词，例如 `\framebreak{}Next`；连续 ASCII 字母属于同一个命令名，`\framebreakNext` 无效。代码之外若需字面反斜杠，按 Markdown 规则转义。

## 公式、表格与脚注

现有 `aligned`、`gathered`、`split`、`align`、`gather`、矩阵、`cases`、`array` 多行环境接受 `\newline`、`\linebreak` 作为 `\\` 的别名。例如：

```latex
\begin{aligned}
1&=2\newline
3&=4\linebreak
5&=6
\end{aligned}
```

普通公式需要显式多行环境才能折行；分页和换框命令须放在 `$...$` / `$$...$$` 之外。单个数学盒不在内部跨页或跨框。表格单元格、脚注及固定字段可用换行命令，但受各自空间和表格行组分页约束；它们不响应分页和换框。

## 旧项目迁移

此前独立开发语法 `/break-commands-v1` 将三种分页命令解释成换框。加载带该语法版本的 `.inkdoc` 时，已识别的强制分页别名在内存中显式转换为 `\framebreak{}`，保留原换框排版，并显示迁移提示。保留其他字符身份、冻结选样、资源和评价；原 `.inkdoc` 文件不写回，编辑器进入待另存状态。代码、转义、未知命令及弱分页提示不改写。新项目保存为 `/break-commands-v2`，再打开不重复迁移；应用版本和字体格式版本不随语法修订变化。

普通 `.md` 没有语法版本，始终使用当前语义，不能猜测旧命令意图。若旧 Markdown 原本需要“下一框”，请让生成内容的 AI 将对应正文命令改成 `\framebreak`；不要全局替换代码或公式中的文字。

## 验证

专项回归 `tests/test_break_commands.py` 覆盖普通页面与模板物理分页、同页换框、混合命令、空页和尾随控制、来源范围/CRLF、列表、公式别名、表格/脚注/字段边界、缓存编辑/撤销、严格 SVG、保存重开与历史语法迁移。隔离测试入口：

```powershell
.\.venv\Scripts\python.exe -B -X utf8 scripts/run_layout_regression.py
```

本轮记录在 [验证目录](../workspaces/layout/page-frame-breaks-20261025/)。此前将分页解释为换框的历史验收保留在原目录，仅作为旧语义和迁移输入，不代表当前命令行为。

LaTeX 分页和浮动队列语义参照 [LaTeX 官方源代码文档](https://latex-project.org/help/documentation/source2e.pdf)；InkStruct 的物理页/文本框区分及上面的适用范围以本文为准。


最终验证：**1208 passed，0 failed，0 skipped**，共 67 个测试文件，其中控制符专项 89 项；本轮修改的 Python 文件全部 Ruff 通过。真实 Qt 编辑器已等待异步预览就绪，验证四页混合分页/换框、普通页面分页、项目精确重开、旧项目显式提示与另存、选样和原件保留，以及严格机器 SVG。四页输出 PNG 已逐页检查。独立离屏验收不等同于新的发布构建或实机纸面验收。

[验证及源码哈希](../workspaces/layout/page-frame-breaks-20261025/verification-final.json)、[JUnit](../workspaces/layout/page-frame-breaks-20261025/regression-complete.xml)、[可重开项目](../workspaces/layout/page-frame-breaks-20261025/acceptance-rendered/page-and-frame-breaks.inkdoc)、[编辑器与迁移验收](../workspaces/layout/page-frame-breaks-20261025/acceptance-rendered/verification.json)。以上为打包前 0.1.40 开发快照的验证；此次预览交付单独将 APP_VERSION 递增至 0.1.41。
