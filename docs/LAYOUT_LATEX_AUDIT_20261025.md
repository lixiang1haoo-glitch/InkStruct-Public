# 独立排版目录：常用 LaTeX 语法审计

日期：2026-10-25。工作目录为 `C:\Users\lee\Documents\InkStructApp\InkStruct-Layout-Dev`。本轮仅修改独立目录，未合并、未构建发布包、未修改应用版本号。

本审计核对数学解析器及 Markdown 数学绑定。**常用 LaTeX 语法尚未全部支持**；当前仍是明确白名单的受控实现，不执行完整 TeX。解析通过不等于字体资源齐全，也不等于真实笔迹、写字机纸面、所有边界上下文或成品导出已经验收。

## 本轮修复

- `\sqrt6`、`\sqrt[3]8` 现在接受单个数学原子，不再强制根内花括号。
- `\frac12`、`\frac1x`、`\frac{1}2`、`\frac1{2}` 现在接受单原子与分组混用；`dfrac`、`tfrac` 使用相同规则。
- `\mathrm m` 接受单原子，并通过独立分组保留内部结构属性；例如 `\mathrm\dfrac12` 不覆盖 `dfrac` 的分数样式。
- 单原子读取不吞掉外层上下标：`\sqrt6^2` 的上标属于根式，`\frac12_3` 的下标属于分式。多个字符的参数仍需分组，例如 `\sqrt{12}`。
- 未加花括号的连续根式、分式和样式命令仍受 32 层递归预算限制，超限给出定位诊断。
- `\hbar` 及直输 `ℏ` 均解析为 U+210F；字符 `．` 在数学中复用英文句点 `.` 的语义，但保留原始源码区间。其真实字形资源与合成效果由排版/资源回归另行验证。
- 审计发现 `matrix` 的 `\\[2pt]` 和 `\\*` 原来会误作下一行可见字符。现在与 `aligned`、`array` 一样明确拒绝尚未实现的行距与星号换行选项。若下一行确需以字面方括号开头，可写 `\\{[2]}`。

### 为什么 `\frac1` 仍报错

分式需要分子和分母两个参数。`\frac1` 只有分子 `1`，没有分母，是未完成的输入；不会擅自补成某个数学值。现在诊断明确为 `Missing denominator argument for \frac`，定位到完整命令及已输入参数，原文保持不变。

可写 `\frac12`、`\frac1x` 或 `\frac{1}{x}`。`\frac{12}{x}` 表示整个 `12` 为分子；`\frac12` 则分别把 `1`、`2` 作为两个参数。

命令名按连续 ASCII 字母读取：`\sqrt6` 中数字会终止命令名，而 `\sqrtx` 是另一个完整控制词，不等于 `\sqrt x`。这与通常 LaTeX 的控制词边界一致。

## 已通过解析核对的常用范围

| 类别 | 代表写法 | 当前边界 |
| --- | --- | --- |
| 分组、上下标 | `{x+y}`、`x_1^2`、`x^{12}` | 重复同类上下标拒绝；多字符参数需分组 |
| 分式、根式 | `\frac12`、`\dfrac{a}{b}`、`\sqrt6`、`\sqrt[3]8` | 参数必须存在且非空；不自动补参数 |
| 希腊、运算、关系、箭头 | `\alpha`、`\times`、`\leq`、`\to`、`\forall`、`\partial` | 106 个符号命令逐项核对；不同希腊变体保持独立语义 |
| 函数与大运算符 | `\sin x`、`\log_2 x`、`\sum\limits_{i=1}^n`、`\int\nolimits_0^1` | 20 个函数命令；`limits` 仅作用于运算符 |
| 文字、单位、正体 | `\text{电压}`、`\mathrm m`、`\mathrm{m^2}`、`\operatorname{rank}` | `text`、`operatorname` 仍需花括号；文字不支持任意嵌套命令/嵌套组 |
| 伸缩括号 | `\left(\frac12\right)`、`\left\{x\right.` | 成对 `left/right`；圆、方、花、角括号、单/双竖线；`.` 隐去一侧 |
| 矩阵与分段 | `matrix`、`pmatrix`、`bmatrix`、`Bmatrix`、`vmatrix`、`Vmatrix`、`cases`、`smallmatrix` | 通常最多 8×8，行列数一致；`cases` 两列 |
| 多行对齐 | `aligned`、`gathered`、`split`、`align`、`gather` 及已有星号环境 | 有列数、行数及使用上下文限制；不支持逐行间距选项 |
| 数组 | `\begin{array}{r|c}...\end{array}`、`\hline`、`\cline{1-2}` | 受控 l/c/r 列及单双规则线；不执行完整 array 列宏 |
| 修饰符 | `\vec x`、`\overline{x+y}`、`\underline x`、`\widehat{x}`、`\dot x` | 13 种现有修饰符，单原子/分组均核对 |
| 编号与引用 | `equation`、`\tag`、`\label`、`\ref`、`\eqref`、`\notag` | 标签存在性、冲突和放置上下文仍由文档语义验证 |
| 间距与转义 | `\,`、`\:`、`\;`、`\quad`、`\qquad`、`\ `、`\{`、`\%`、`\_` | 只接受已列入白名单的控制词/控制符 |
| 中文、句点、物理符号 | `U_{模块}`、`1．5`、`\hbar`、`ℏ` | 字形资源与合成需另行齐备；不把命令名当作采集字符 |

公式仍受 4096 个解析视图字符、4096 个语法节点和 32 层递归预算约束。完整边界参见 [数学语法说明](MATH_SYNTAX.md)。

## 已明确诊断但尚未实现的常用扩展

| 类别 | 本次核对并确认未支持的例子 |
| --- | --- |
| 额外字形样式 | `\mathbf{x}`、`\mathit{x}`、`\mathbb{R}`、`\mathcal{F}`、`\boldsymbol{x}` |
| 额外结构 | `\binom{n}{k}`、`\overbrace{x}`、`\underbrace{x}`、`\overset{a}{b}`、`\underset{a}{b}`、`\stackrel{a}{b}` |
| 额外符号与简写 | `\iint`、`\iiint`、`\dots`、`\vdots`、`\ddots`、`\not=`、`x'` |
| 额外括号与尺寸指令 | `\bigl`/`\bigr`、`\middle`、`\lceil`/`\rceil` |
| 额外间距 | `\!`；矩阵/对齐/数组的 `\\[2pt]` 及带星号换行 |
| 额外环境与表格控制 | `multline`、`\multicolumn`、`array` 的 `p{2cm}` 等未实现列格式 |
| 完整 TeX 执行 | `\newcommand`、`\input`、任意宏展开、宏包、完整文档 |

其中 `\ldots`、`\cdots`、`\prime` 已支持；这些并不表示上述其他省略号或单引号简写也已实现。未知控制词会给出 `math-command-unsupported` 及该命令的精确源码区间，不静默忽略。

## 审计证据与复现

[批量审计 JSON](../workspaces/layout/latex-fixes-20261025/parser-syntax-audit.json) 记录解析器 SHA-256、独立 Python 路径、每项输入、预期结果、实际诊断、示例文件哈希及逐公式来源。

- 234 项命令与代表结构：200 项成功解析、34 项按预期拒绝，0 项预期外结果。
- 106 个符号命令、20 个函数命令、13 种修饰符的单原子与分组形式均已核对。
- 7 个既有数学 Markdown 示例共 145 个公式：145 个公式语法树、0 个数学诊断。涵盖普通正文、表格、HTML 单元格、矩阵、对齐、数组、编号和引用示例。
- 新增回归集中在单原子参数的范围、样式属性保留、未知命令定位、缺参数边界、深度预算及矩阵行选项，见 `tests/test_math_single_token_arguments.py`；既有 `tests/test_math_parser.py` 继续覆盖全部符号白名单及原有语法诊断。

在本独立目录运行：

```powershell
.\.venv\Scripts\python.exe -B workspaces/layout/latex-fixes-20261025/audit_parser.py
.\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider --basetemp=.isolation/pytest-parser-audit tests/test_math_parser.py tests/test_math_single_token_arguments.py tests/test_math_constructions.py
```

本轮证据只对应上述受控语法和本地示例；不能由 145 个样例推断任意 LaTeX 文档均可解析，也不能由语法通过推断实样与物理输出已完成验收。

## 最终排版与资源验证

本轮五项需求已在独立目录接通：单 token 参数、全角句点复用、h 与减号合成 hbar、横线修饰符复用减号、围绕数学轴的括号分段伸长。`bar/overline/underline` 沿用分数线来源设置；其他修饰符保留原有构件来源。缺少实际 h 或减号资源时仍明确提示，不用字体轮廓替代轨迹。

hbar 的短横按 h 上部真实笔迹交点定位；正斜体和光学参考框继承 h。独立字形优先，旧的冻结选样在新增减号、独立字形或录制句点后仍可解析。全角点可复用录制句点或已显式启用的内置小数点。括号通过识别花括号的实际中腰对齐数学轴，保留端部和中腰，仅延长连接段；缺少装配元数据时使用手写轨迹分段近似。

- 最终综合回归：**693 passed，0 failed，0 skipped**，覆盖 40 个测试文件，包含公式、符号、字体、标点、表格、资源扫描、冻结选择、Qt 公式设置、缓存和保存重开。
- 本轮全部改动的 Python 文件 Ruff 检查通过。本地启动器 `launch_layout_dev.py --help` 可运行。
- 两种构件模式的测试页均通过保存重开精确一致、严格 M/L SVG 及路径路由不改变几何检查；已目视检查 PNG。测试页使用合成测试字形，不能代替真实手写字体和纸面效果验收。
- `APP_VERSION` 与隔离复制时的文件哈希一致，仍为 **0.1.40**。未生成应用发布包，未提交或合并；主研究目录未由本轮任务修改。

记录：[最终验证 JSON](../workspaces/layout/latex-fixes-20261025/verification-final.json)、[JUnit 回归记录](../workspaces/layout/latex-fixes-20261025/regression-final.xml)、[预览与导出验证](../workspaces/layout/latex-fixes-20261025/final-acceptance/preview-verification.json)。

验收项目：[几何括号模式](../workspaces/layout/latex-fixes-20261025/final-acceptance/synthetic-geometric/synthetic-geometric.inkdoc)、[录制括号模式](../workspaces/layout/latex-fixes-20261025/final-acceptance/synthetic-recorded/synthetic-recorded.inkdoc)。预览：[几何模式 PNG](../workspaces/layout/latex-fixes-20261025/final-acceptance/synthetic-geometric/preview/page-001.png)、[录制模式 PNG](../workspaces/layout/latex-fixes-20261025/final-acceptance/synthetic-recorded/preview/page-001.png)。

综合回归入口会调用独立启动器，并对所有 Python 子进程重定向 Qt/采集设置，兼容 Windows 多进程；未指定临时目录时自动在 `workspaces/layout` 创建新目录：

```powershell
.\.venv\Scripts\python.exe -B -X utf8 scripts/run_layout_regression.py
```

日常开发验收使用本目录 `run_layout_dev.cmd`，或 `.\.venv\Scripts\python.exe -B launch_layout_dev.py`。正式构建与合并前仍需协调唯一应用版本号。
