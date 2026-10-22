# InkStruct 0.1.21 Windows 交付记录

日期：2026-10-19。实际项目路径为 `C:\Users\lee\Documents\InkStructApp\InkStruct-Windows-Dev`。源码基底 `af45b45f04f899fcaced43aa980b0508673ee6c0`，使用完整未提交工作树构建；没有 reset、clean、自动提交或推送。实施前检查了 AGENTS.md、Git 状态、当前模板、绑定、设计器及相关文档，拆分见 [实施记录](TEMPLATE_FLOW_IMPLEMENTATION_0_1_21.md)。实施前源码快照、用户数据清单和本轮日志位于 `artifacts/template_flow_0.1.21_20261019/`。

APP_VERSION 已从 0.1.20 递增为 **0.1.21**，唯一来源仍是 `src/inkstruct/fonts/__init__.py`；双 EXE 的 FileVersion、ProductVersion 均为 0.1.21。Python 库、字体协议版本独立。README、使用说明、LaTeX 手册源码与发布文件名已同步；本环境没有 XeLaTeX/latexmk，未重编译新版手册 PDF，历史 PDF 保留。

环境为 Windows 11 x64（26300），项目独立 `.venv`，Python 3.13.16 AMD64、PySide6/Qt 6.9.2、PyInstaller 6.22.3、NumPy 2.5.4、Matplotlib 3.11.2。不修改全局 Python，不安装训练、CUDA 或 PyTorch 环境。构建依赖与实际源码逐文件哈希记录于 `artifacts/windows_build_0.1.21_20261019_final/build-provenance.json`。

## 最终模型与操作

模板分为“简单模板”和“自定义模板”。简单模板用纸张与四向边距形成重复单页正文区，字号、行距与段距复用现有排版样式。自定义模板使用可选起始页组和必填循环页组，每组按明确顺序引用源布局；正文按页面顺序、正文框编号流动，支持同页多框与不同宽度重新断行。正文只解析一次，不截断 Markdown 重解析。

循环组可以引用 PDF 1、2、3、4 页，得到 1、2、3、4、1、2……；封面可以放在起始组。实际文档页码连续递增，预览显示来源布局，修改源布局统一影响其所有自动实例。“末尾补齐整个循环页组”默认关闭；开启只补齐已经进入的当前循环，不额外启动新循环。有正文时在最后使用页停止；空正文或仅字段时输出起始组一次，没有起始组则输出首循环页，勾选补齐才输出整个首循环。实际页面没有框承接的已定义字段内容明确报错。

正文框、字段框、自动页码分工独立。字段框固定尺寸，可重复引用同一字段，不触发续页；溢出、缺失必填、未声明字段、重复定义、语法错误均阻止正式导出。不可拆对象尝试后续正文框；完整循环仍无法取得进展则停止并定位，页数和资源预算继续生效，不自动缩字、截断或放宽原有成品校验。

右上角齿轮 → **纸张与模板**集中制作模板、导入 PDF/图片和保存新模板。**编辑并应用当前文档的模板布局**打开当前实际配置，独立确认后只更换本份模板，保留排版样式，可在右侧撤销；取消外层全局默认设置不会撤销已经独立确认的文档操作。排版右侧新增 **模板内容**，提供当前文档套用、撤销/重做、填写字段/编辑单份 Markdown、复制骨架及真实适配报告。旧固定区首次绑定也从此入口可达，不根据名称自动关联内容。

设计器提供源布局、起始/循环组排序、框角色与顺序、字段 ID/显示名/类型/必填规则、画布连接箭头、Markdown 骨架及高级 JSON。草稿修改先应用到当前对象，支持撤销、重做和取消；模板另存拒绝覆盖已有文件。

PDF 导入读取物理尺寸，支持一次指定多个页面，默认采用首个所选页尺寸，也可保留当前纸张。纸张尺寸变化时，背景分别沿宽高拉伸铺满，框保持毫米几何，出界拒绝应用。保留 PDF 哈希、原页码与原尺寸。背景仅用于参考，不描摹成轨迹；预印纸不重复绘制纸上背景，空白纸只输出明确配置的框线和内容。毫米平移校准保留，没有新增旋转、比例校准、OCR。

脚注只用于正文，在物理页面最后正文框底部安排。跨布局脚注使用各布局最后正文框的最小可用宽度，以保持续排测量一致；正文仍使用各自框宽。字段脚注、无法容纳的正文/脚注组合及字形校正越框均明确诊断。

## 单份 Markdown 与协议

```markdown
:::field name
张三
:::

:::field student_id
20260001
:::

:::field experiment_title
单摆周期测量
:::

# 实验目的

这里开始是连续正文。

# 实验原理

这里可以正常编写公式、表格等已支持的 Markdown。
```

字段块之外全部进入唯一正文。字段 ID、显示名和框名独立；改名或移动框不改变对应关系。字段块可以放在不同位置，建议集中开头。字段块不允许嵌套；缺少结束标记只报告错误开头，不吞掉后续正文；代码围栏内的标记按普通代码处理。字段内部保留已支持 Markdown，但必须容纳在自身框内；数值和 ISO 日期字段执行格式/日历检查。保留准确源码范围与稳定身份，内容填写为一个可撤销事务。

新模板 `inkstruct_page_template_v3`、FlowStyle v2、命名字段 `inkstruct_named_fields_v1`、项目 `inkstruct_document_package_v3`、适配报告 v2 明确分派，不往旧 schema 塞新字段，不静默丢弃未知字段。项目嵌入本份 Markdown、布局、资源、源码身份与冻结选样，外部模板更新不会修改已保存项目。

旧 v1/v2 模板、固定区绑定及旧项目继续走原路径。显式迁移只复制几何、背景、校准与来源，并记录旧 schema 和内容哈希；原绑定、锚点、倍率/页面策略需人工核对，不自动生成字段或改写正文。仍有旧绑定的项目不能直接切换到新字段模型；请先保留原项目，在新项目明确配置字段。完整操作见 [模板使用说明](TEMPLATE_SINGLE_FLOW.md)。ZIP 内附同一说明与简单模板、四布局循环模板和 Markdown 示例。

## 实际 Windows 验证

| 检查 | 真实结果 |
| --- | --- |
| 82 个相关测试模块回归 | **797 passed，2 skipped**，279.45 秒 |
| 最后模板、预览专项 | **53 passed**，33.94 秒 |
| 最后当前布局/设置入口专项 | **28 passed**，31.48 秒 |
| 所有 40 个改动 Python 文件 Ruff | 通过 |
| 最终包内自检 | 通过；两种生成方法、模板 v3、冻结重开与 SVG |
| 原生窗口与真实字体小文档 | 7 页，字段填写、齿轮实际布局、取消、保存重开通过 |

测试组有重叠，不相加宣称独立测试总数。专项包含最终入口与预览修正。覆盖简单模板分页、起始/多布局循环、实际四页 PDF 导入、末尾停止/补齐、多框不同宽度、字段重复/必填/未知/溢出、嵌套/缺结束/代码围栏/CRLF 与源码定位、无进展保护、列表/代码/公式/表格/图片/脚注、预印与空白纸、取消/撤销/重做、100%/150%/200% DPI、保存重开及 SVG、旧协议兼容。

两个跳过均因当前 Windows 账户没有创建符号链接的权限：`test_images.py` 的真实文件符号链接检查、`test_template_binding_cli.py` 的真实悬空项目链接检查。没有更改系统权限，也没有降低生产校验。部分旧测试的读写显式指定 UTF-8，避免 Windows GBK 默认编码造成假失败。

最终 `InkStructTool.exe` 使用包内 scx 真实 11 字“人物理羝羚而铜伯攣盼⺼”，分别通过 v6.1 exp 与 v4 adaptive 的导入、建档、生成、制作字体、排版、保存重开和 SVG；没有重跑全库。来源缺口、参考替代和未知来源提示仍完整保存。

真实 user_001 全字体完整校验导入为约 **13.64 秒**，四进程；该次与其他验收并行，不作为独立性能基准。QA 衍生字体仍为 9771 字、10730 候选、8,375,082 点，3350 份来源提示保留，只存在验收目录，未替换用户字体。

原生验收使用新工作区 `workspaces/windows-template-flow-0.1.21-final`，载入真实已有字体组成的小规模文档：封面、PDF 1、2、3、4、1、2，共 7 页。将字段 `A123` 修改为 `A321`，正文六段 `A 123` 保持不变，保存并在原生窗口重开；独立核验正文身份、冻结选样、布局与 SVG。真实适配报告 0 错误、1 条未校准提醒，保留该提醒。齿轮打开的布局正确包含封面与四页循环，取消草稿不改文档。截图、PDF、`.inkdoc`、适配报告和 SVG 均在验收目录。首次原生验收发现来源布局首行被裁，最小修复为增加模板预览顶部标注空间，不改毫米输出。

旧长文档仍为 11 页、4580 个文本实例、301 条诊断，所有页面 SVG 与原 Windows 基线逐字节一致；全局设置无改动应用、保存重开也完全一致。实际 0.1.20 的同样本与同字符校正文档冻结选样与 SVG 均精确一致，详见 `legacy-corrections.json`。

本轮开始清单中的 **1826 个既有文件哈希一致**，包括任务、样本、作者档案、进度、字体、评价、设置和历史交付；原恢复记录未改。原 user_001 全字体 SHA-256 仍为 `b114b9db538610176eaf4ca7ca6f5f177fd0319817599433dec274c50061c9c3`。字体、稳定源码身份、冻结选样、诊断和正式导出限制保留。

未验证：实体数位板、驱动、写字机、纸面校准、实际硬件书写效果；本轮原生小文档使用已有拉丁字符，中文输入法输入未重新验收。新版 LaTeX PDF 未编译。所有自动化与原生结果均来自本 Windows 工作树，不引用历史 macOS 通过记录代替。

## 交付、日志与准确命令

可运行目录：`artifacts/windows_build_0.1.21_20261019_final/dist/InkStruct/`。保留整个目录及 `_internal`。主窗口与伴随工具都是 x64，版本 0.1.21。较早内部候选仍保留，仅以下最终包正式交付，不覆盖任何历史交付。

正式 ZIP：`artifacts/windows_release_0.1.21/InkStruct-0.1.21-Windows-x64.zip`，**123,685,131 字节**；SHA-256：`3bd48b064b3d1884b9ad47b6bdb720e82d3d322cb1f4f6c08789209891f9aacc`。ZIP CRC、双 EXE 版本、逐文件摘要与说明/示例摘要见同目录 `verification.json`，校验和见 `SHA256SUMS.txt`。

源代码、执行脚本、原生截图、保护清单与 UTF-8 日志：`artifacts/template_flow_0.1.21_20261019/`。重点为 `regression_final.log`、`scope_final.log`、`current_layout_verified.log`、`lint_final.log`、`native-verification.json`、`final-verification.json`。最终构建日志 `build_final.log`、构建源码摘要、PyInstaller 告警在构建及验收目录。包内两方法结果、完整字体 QA 衍生包、模板项目与 SVG 在 `artifacts/windows_bundle_check_0.1.21_20261019_final/`。

本轮只清理明确列出的可重建测试临时目录、构建 work/cache 及本轮私有临时/绘图缓存；保留源码、全部既有数据、日志、验收文件、可运行目录与 ZIP。详见 `cleanup.json` 和清理后封存检查 `delivery-seal.json`。

在上述项目根目录 PowerShell 中执行：

```powershell
# 启动本次应用，继续使用现有工作区与字体
& 'artifacts/windows_build_0.1.21_20261019_final/dist/InkStruct/InkStruct.exe' --workspace workspaces/windows-0.1.8 --font artifacts/user_001_full_font_20261018_math_axis/user_001-v61-full-symbols-20261018.inkfont

# 源码启动；独立验收时使用新的 workspace
.venv/Scripts/python.exe -m inkstruct.application --workspace workspaces/windows-0.1.8

# 模板专项，重跑请使用不存在的新 basetemp
.venv/Scripts/python.exe -m pytest tests/test_flow_templates.py tests/test_flow_template_qt.py -ra --basetemp artifacts/qa21-repeat-new

# 本轮完整相关回归清单；重跑先将脚本里的 basetemp 改为新目录
.venv/Scripts/python.exe artifacts/template_flow_0.1.21_20261019/run_regression_final.py

# 包内自检，output 使用不存在的新目录
& 'artifacts/windows_build_0.1.21_20261019_final/dist/InkStruct/InkStructTool.exe' --inkstruct-check --samples artifacts/source_samples/scx_351bf154/samples/scx --writer scx --font artifacts/user_001_full_font_20261018_math_axis/user_001-v61-full-symbols-20261018.inkfont --output artifacts/windows_bundle_check_repeat_new

# 新模板；另存不覆盖已有文件
.venv/Scripts/inkstruct.exe document template new --format v3 --kind custom --output artifacts/my-new-template.json

# 显式复制旧布局；原文件与原正文保留，绑定需人工核对
.venv/Scripts/inkstruct.exe document template upgrade old-template.json --version 3 --output new-template-v3.json

# 下次正式交付先将 APP_VERSION 至少递增至 0.1.22，输出必须为新目录
.venv/Scripts/python.exe packaging/build_inkstruct_app.py --output artifacts/windows_build_next_new
```

当前可以继续开发并正式交付本次 Windows 软件更新；硬件、两项权限相关检查和新版手册 PDF 的边界如上。
