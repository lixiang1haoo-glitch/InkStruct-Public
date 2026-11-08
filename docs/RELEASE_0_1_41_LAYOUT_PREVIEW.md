# InkStruct 0.1.41 Layout Preview（Windows x64）

这是 `InkStruct-Layout-Dev` 的独立排版预览包，未修改或合并主研究目录。APP_VERSION 为 0.1.41；Python 库仍为 0.2.0，字体格式版本独立。

## 使用

完整解压 `InkStruct-Layout-Preview-0.1.41-Windows-x64.zip` 到新的可写目录，保留 `_internal`。双击 `InkStruct.exe`；`InkStructTool.exe` 是同版本控制台及预览/导出辅助程序，不要单独移动 EXE。

预览包默认将工作区和设置放在应用目录内的 `preview-data`，不读取正式版的本机默认设置。窗口标题含 `Layout Preview`。样本、字体和文档需要自行导入副本；不附用户历史工作区或自动替换原文件。内容工作流是 AI 读取 [Markdown 生成规范](AI_MARKDOWN_SPEC.md) 和用户要求，生成 Markdown 后复制或导入。

## 本轮变化

- 支持 `\sqrt6`、`\frac12` 等单 token 参数；缺分母的 `\frac1` 给出明确诊断。
- 全角 `．` 复用英文点；`\hbar` 可由同作者 h 和减号合成，保留来源与冻结选择。
- overline、underline 等横线复用拉长减号；伸缩括号以数学轴为中心，保留括号端部及大括号腰部结构。
- `\newline`、`\linebreak` 换行；`\newpage`、`\pagebreak`、`\clearpage` 跳下一物理页；`\framebreak` 仅在连续正文流中进入下一正文框。
- 旧版换框别名项目显式迁移，保留原件并另存；不增加插入控制符按钮。

当前无浮动图表队列，`\clearpage` 的可见效果等同强制物理分页。弱强度、字段/表格/脚注和数学环境边界见 [命令说明](TEXT_FLOW_BREAK_COMMANDS.md)。手写资源缺口仍按原规则诊断，不使用系统字体冒充笔迹。

## 构建与检查

使用独立虚拟环境和私有构建缓存：

```powershell
.\.venv\Scripts\python.exe -B packaging/build_inkstruct_app.py --layout-preview --output artifacts/layout_preview_0.1.41_20261025/build
```

包内工具可对新目录运行布局自检（仅合成符号和内置数字）：

```powershell
$env:INKSTRUCT_LAYOUT_PREVIEW_HOME = "$PWD\preview-data"
.\InkStructTool.exe --inkstruct-layout-check --output "$PWD\layout-check-NEW"
```

用户手册 LaTeX 源码和 Markdown 使用说明同步至此预览版本。当前环境无 XeLaTeX/latexmk，未将旧 PDF 作为新版手册。此预览不宣称已完成人工原生输入、数位板或写字机纸面验收。

构建、自检、ZIP 完整性及最终 SHA-256 在交付目录的验证记录中保存。历史构建和此前 0.1.40 开发验证记录保留原样。
