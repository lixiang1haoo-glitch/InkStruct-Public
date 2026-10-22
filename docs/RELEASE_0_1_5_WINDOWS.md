# InkStruct 0.1.5 Windows 更新记录

日期：2026-10-15。应用版本 0.1.5，Python 库仍为 0.2.0。保留 0.1.4 和更早的源码修改、数据、工作区及交付包，未提交或推送。

## 本次变化

- 公式设置分类行高按字体度量留出上下边距，分类栏宽度按最长标签调整，修复“上标与下标”被“分式”等下一项遮挡的问题。深色系统主题下，浅色设置区域的说明标签保持深色可读文字。
- 采集界面只保留“单字任务采集”和“字母与符号”。移除整行采集标签及其应用级键盘监听，不删除旧整行数据或底层读取能力。
- “创建任务 · 每字 5 份”改为“创建任务”，移除主页面“全部字符”和“英文：未分类”下拉框。弹窗支持任务名称、作者、每字符份数（默认 5，1–100），以及英文正体、英文斜体、数字、运算符、希腊字母/变体、括号、标点等类别。提供全选、全不选、样本数预览；空选禁止创建，取消不替换任务。
- 同一任务可包含同一英文字母的正体与斜体，当前字符会显示写法分类；保存、恢复进度和继续任务后分类不变。旧任务仍可读取。导入 TXT/CSV 可筛选类别，保留字表内份数，不用弹窗默认值覆盖 CSV 指定份数。
- 任务仍使用原 `handwriting_task_v1`，采集样本仍为 `inkstruct_symbol_sample_v1`。新任务在 source 字段保存类别信息，以任务项的 source_index 确定写法；不改字体协议或生成算法。

## 验证

相关测试 **40 passed**：`test_symbol_capture_ui.py`、`test_symbol_capture.py`、`test_math_settings_qt.py`、`test_integrated_window_qt.py`、`test_font_packages.py`、`test_symbol_provider.py`、`test_generation_workflow.py`。覆盖 9、14、20 磅字体的全部分类点击、不遮挡布局、混合正斜体、3 份自定义数量、保存续采、取消、空选与导入原份数保留。一个原测试的中文 Markdown 临时文件补充了 UTF-8 编码，避免 Windows GBK 测试夹具误写。

真实 Windows Qt 平台已渲染并检查截图；原生 EXE 中已点击确认采集仅两个标签、两个旧下拉框消失、“创建任务”打开详细配置窗、默认 5 份。原生配置测试已取消，没有向用户采集目录添加假样本。离屏平台缺少系统中文字体，其早期截图仅作诊断，不作为中文外观验收；有效截图在本轮 `visuals-native-final/`。

最终构建的 `InkStructTool.exe --inkstruct-check` 执行实际任务创建弹窗、合成采集、scx 两种方法各 11 字导入/建档/生成、字体发布、完整字体排版、冻结重开和 SVG 验证。最终结果以 `artifacts/windows_bundle_check_0.1.5_20261015_release/verification.json` 及本轮 `bundle_release.log` 为准；来源缺口提示与原协议检查保留。合成采集不等于实体数位板验收。

## 位置与命令

- 应用：`artifacts/windows_build_0.1.5_20261015_release/dist/InkStruct/InkStruct.exe`
- 工具：同目录 `InkStructTool.exe`。必须保留整个 `InkStruct` 目录及 `_internal`。
- 归档：`artifacts/windows_release_0.1.5/InkStruct-0.1.5-Windows-x64.zip`，同目录保存校验记录和 SHA256SUMS.txt。
- 日志：`artifacts/windows_ui_0.1.5_20261015/`，含测试、构建、原生可访问性记录与 Windows 截图。
- 完整包内验收：`artifacts/windows_bundle_check_0.1.5_20261015_release/`。
- 本次原生查看使用独立的 `workspaces/windows-0.1.5`；已有 `workspaces/windows` 保留，正常开发也可继续使用。

```powershell
.\.venv\Scripts\python.exe -m inkstruct.application --workspace workspaces\windows
.\.venv\Scripts\python.exe -m pytest tests\test_symbol_capture_ui.py tests\test_symbol_capture.py tests\test_math_settings_qt.py tests\test_integrated_window_qt.py tests\test_font_packages.py tests\test_symbol_provider.py tests\test_generation_workflow.py
.\.venv\Scripts\python.exe packaging\build_inkstruct_app.py --output artifacts\windows_build_next
```

构建输出须使用新目录。下一次新的应用交付至少为 0.1.6。README、使用说明及 LaTeX 手册源码已同步 0.1.5；本机仍无 TeX Live，新版 PDF 未重编译，历史 PDF 未覆盖。实体数位板、驱动及写字机验证边界沿用初始化记录，本次不声称新增硬件验收。
