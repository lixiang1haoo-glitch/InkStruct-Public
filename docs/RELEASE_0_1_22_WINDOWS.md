# InkStruct 0.1.22 Windows 交付记录

日期：2026-10-19。项目：`C:\Users\lee\Documents\InkStructApp\InkStruct-Windows-Dev`。Git 基底 `af45b45f04f899fcaced43aa980b0508673ee6c0`，使用完整未提交工作树。开始前核对了 AGENTS.md、Git 状态、模板相关源码和文档，并保存实施前源码 ZIP 与用户数据摘要。没有 reset、clean、自动提交、推送或覆盖历史交付。

应用版本唯一来源 `src/inkstruct/fonts/__init__.py::APP_VERSION` 从 0.1.21 递增为 **0.1.22**，Python 库和字体格式版本独立。README、当前说明、LaTeX 手册源码及发布文件名已同步。环境仍为 Windows 11 x64（26300），项目 `.venv`，Python 3.13.16 AMD64、PySide6/Qt 6.9.2、PyInstaller 6.22.3、NumPy 2.5.4、Matplotlib 3.11.2。未修改全局 Python 或其他项目环境。

## 最终界面组织

齿轮打开“设置”，分为采集设置、排版默认设置和模板管理。新文档默认只在“纸张与默认模板”等默认页面配置，不再混入立即修改当前文档的按钮。模板管理直接作为一级入口，分开显示“当前文档布局”和“可复用模板”。后者记录显式导入或另存的最近模板，不扫描或改写用户文件。

新建只保留一个入口，选择简单或自定义类型。简单模板只显示纸张、四向边距与预览。自定义工作台左侧组织起始、循环及未使用布局，中间显示背景和正文编号连接，右侧随选择显示纸张、布局、文本框属性或字段声明。支持画布选择、拖动移动和右下角缩放，毫米值仍可精确输入；共用引用和独立副本分开操作。

工作台统一维护一份草稿，取消不修改外部文档；移除普通界面的逐页“应用草稿”和 JSON 标签。无效属性保留并提示，确认前需修正。最终按钮明确为“应用到当前文档”或“保存为新模板”。另存拒绝覆盖原文件。进入工作台前，尚未保存的默认设置明确选择保存、放弃或取消；设置与工作台分开确认。高级 JSON 和显式旧布局迁移保留在高级操作。

当前文档右侧改为“模板”栏：模板摘要、更换、字段状态与填写、实际适配问题及定位。不再常驻排列模板撤销/重做按钮；模板与正文按操作顺序使用编辑菜单及标准快捷键撤销、重做。实际报告先显示问题，再列字段明细。

字段填写采用表单，仍写回本份唯一 Markdown，没有第二份可见正文编辑器。保留原换行、未编辑正文与字段、稳定源码身份。字段显示名与稳定 ID 独立，改名不猜测对应关系。重复定义或语法错误时禁止表单写回，回主编辑器修正；未填写的可选字段不自动插入。查看源码定位当前字段，即使主列表未预先选择；若表单有未应用修改，先明确选择是否放弃。无字段的新模板不显示可用的填写动作。

试排使用当前真实内容与冻结资源的独立快照，异步完成，可取消，不修改当前文档和选样。布局结构有效与实际内容通过分别说明；没有文档上下文时明确标记示例预览。缺字、来源、字段溢出与纸面校准提示继续保留。

## 保留的能力与数据

模板 v1/v2/v3、项目 v1/v2/v3、命名字段协议、FlowStyle、字体协议、排版和导出能力均未升级或改写。**77 个 document/layout/assets/scene/math/renderers 核心 Python 文件与本轮开始逐字节一致**。起始及多布局循环、不同宽度跨框、公式、表格、图片、脚注、PDF 背景、校准与严格导出检查继续复用原实现。

旧模板仍可读写副本、编辑原几何与源码块绑定；首次绑定、缺失绑定的报告定位继续进入原绑定编辑器。旧布局迁移为显式复制操作，记录原来源，不根据字段名称猜测，不改写原文或旧绑定。`.inkdoc` 继续冻结本份模板、资源、身份和选样，外部模板更新不改变已保存文档。

**1942 个可读既有文件哈希一致**，覆盖既有任务、采集样本、作者档案、进度、字体、生成结果、评价、设置、0.1.21 验收与历史交付包。原 user_001 完整字体 SHA-256 仍为 `b114b9db538610176eaf4ca7ca6f5f177fd0319817599433dec274c50061c9c3`。

另有 3 个历史工作区字体文件在本轮开始即因现有权限不可读，未修改内容或权限；路径见 `baseline-unreadable.json`，大小与修改时间核对未变，内容哈希明确为未验证，不计入上述 1942 个文件。

## 实际 Windows 验收

相关回归覆盖 83 个测试模块，最终为 **818 passed、2 skipped**；最后 GUI/设置/旧报告专项 **44 passed**。测试组有重叠，不相加宣称独立总数。15 个本轮改动 Python 文件 Ruff 检查通过。精确耗时与执行参数见对应 UTF-8 日志和 `.command.json`。

两个跳过仍为当前账户没有 Windows 符号链接创建权限：真实图片文件链接、真实悬空项目链接检查。没有更改权限或降低协议检查。覆盖 100%、150%、200% DPI、画布移动/缩放、布局排序、字段改名、取消、无效草稿、默认设置保存/放弃/取消、模板/正文撤销顺序、字段 CRLF 与源码定位、重复字段保护、另存不覆盖、隔离试排、旧文档保存重开和 SVG。

原生验收使用真实已有字体的小文档和新工作区。模板为封面加 PDF 1、2、3、4 循环，共 7 页。实际检查模板管理底部操作可见、独立工作台、画布拖动与毫米属性同步；正文框从 `(15, 40)` 移到 `(17.381, 42.381)`，撤销精确恢复，随后取消草稿。字段表单将 `A123` 改为 `A456`，标准 Ctrl+Z/Ctrl+Y 可撤销重做，另存并原生重开后六段正文 `A 123` 保持不变。独立重开核对正文身份、冻结选样与模板配置，并成功导出 SVG。唯一诊断为未完成纸面校准，提醒未隐藏。截图、项目和 SVG 位于本轮验收目录。

0.1.21 的真实 v3 模板项目仍为 7 页，冻结选样和逐页写字机 SVG 字节完全一致。0.1.20 的同样本、同字符校正文档选样与 SVG 同样精确一致。旧长文档仍为 11 页、4580 个文本实例、301 条诊断，全部页面 SVG 与原 Windows 基线相同；全局设置无改动应用、保存重开亦相同。

最终包内自检使用 scx 真实 11 字“人物理羝羚而铜伯攣盼⺼”，分别完成 v6.1 exp 和 v4 adaptive 的导入、建档、生成、字体制作、排版、保存重开与 SVG；没有重跑全库。新工作台、字段表单取消不改原文、独立试排 SVG 与正式文档精确一致也在 EXE 内验证。完整字体检查继续为 9771 字、10730 候选、8,375,082 点，3350 份来源提醒保留。QA 衍生字体只保存在验收目录，未替换用户字体。

修复与复测记录：旧版报告定位一度误入新入口，已恢复原绑定路径；试排取消令牌按原接口修正；最近模板存储显式使用当前 QSettings 格式，测试保存在私有 INI 中，防止写入用户最近列表。仅清除本轮误注册的 24 个 QA 路径，其他路径保留，详情见 `test-catalog-repair.json`。调整设置最小高度、列表收缩和一级导航，保证主要操作可达。补齐表单返回源码的定位、未应用修改保护及紧凑布局。早期失败日志与内部候选保留，不当作通过记录。

未验证：实体数位板、驱动、写字机和纸面效果；本轮未重新验收中文输入法组合输入。LaTeX 手册源码已同步，环境没有 XeLaTeX/latexmk，未生成新版手册 PDF。上述结果均来自当前 Windows 环境。

## 应用、日志与命令

正式交付：`artifacts/windows_release_0.1.22/InkStruct-0.1.22-Windows-x64.zip`，包含双 EXE、使用说明、模板说明和示例。精确大小、SHA-256、双 EXE 版本、ZIP CRC 与逐文件摘要见同目录 `verification.json`、`SHA256SUMS.txt`。只交付此包；其他同版本目录均为未对外发布的内部候选，历史交付没有覆盖。

ZIP 为 **123,797,767 字节**，SHA-256：`bfc73724b1a0b33eca056dc0b05b2bc5db377d95087b8fd003eba9b6f7564f08`。最终回归 302.53 秒；最后专项 57.90 秒。完整字体包内校验导入约 14.37 秒，与其他验收并行，不作为独立性能基准。

可运行目录：`artifacts/windows_build_0.1.22_20261019_release/dist/InkStruct/`，须保留整个目录及 `_internal`。`InkStruct.exe` 与 `InkStructTool.exe` 均核对为 x64、FileVersion/ProductVersion 0.1.22。

源码前快照、保护清单、脚本、原生截图、`.inkdoc`、SVG 和日志：`artifacts/template_gui_0.1.22_20261019/`。主要记录为 `regression_release.log`、`form_final.log`、`lint_release.log`、`compatibility.json`、`legacy-corrections.json`、`native-verification.json`、`final-verification.json`、`delivery-seal.json`。包内结果在 `artifacts/windows_bundle_check_0.1.22_20261019_release/`。构建日志、源码摘要与 PyInstaller 告警在构建目录。

本轮仅清理明确列出的可重建测试临时目录、私有构建 work/cache 和本轮临时缓存；保留所有源码、既有数据、日志、验收文件、可运行目录和 ZIP，详见 `cleanup.json`。清理后重新核对数据、源码、双 EXE 和 ZIP。

在项目根目录 PowerShell 中执行：

```powershell
# 启动本次应用，继续使用既有工作区与字体
& 'artifacts/windows_build_0.1.22_20261019_release/dist/InkStruct/InkStruct.exe' --workspace workspaces/windows-0.1.8 --font artifacts/user_001_full_font_20261018_math_axis/user_001-v61-full-symbols-20261018.inkfont

# 源码启动；独立验收请使用新工作区
.venv/Scripts/python.exe -m inkstruct.application --workspace workspaces/windows-0.1.8

# 新 GUI 与旧模板报告专项；basetemp 使用不存在的新目录
.venv/Scripts/python.exe -m pytest tests/test_template_gui_qt.py tests/test_flow_template_qt.py tests/test_unified_settings_qt.py tests/test_template_fit.py -ra --basetemp artifacts/qa22-repeat-new

# 本轮相关回归清单；重跑前将脚本中的 basetemp 改为新目录
.venv/Scripts/python.exe artifacts/template_gui_0.1.22_20261019/run_regression_release.py

# 最终包内自检，output 指定不存在的新目录
& 'artifacts/windows_build_0.1.22_20261019_release/dist/InkStruct/InkStructTool.exe' --inkstruct-check --samples artifacts/source_samples/scx_351bf154/samples/scx --writer scx --font artifacts/user_001_full_font_20261018_math_axis/user_001-v61-full-symbols-20261018.inkfont --output artifacts/windows_bundle_check_repeat_new

# 下次正式交付先将 APP_VERSION 至少递增至 0.1.23；构建必须使用新目录
.venv/Scripts/python.exe packaging/build_inkstruct_app.py --output artifacts/windows_build_next_new
```

当前可以继续开发并正式交付本次 Windows 软件更新；权限相关、硬件及新版手册 PDF 的边界如上。
