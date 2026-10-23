# InkStruct 0.1.7 Windows 更新记录

日期：2026-10-15。项目路径：`C:\Users\lee\Documents\InkStructApp\InkStruct-Windows-Dev`。基于当前含未提交修改的完整工作树，Git 基点 `af45b45f04f899fcaced43aa980b0508673ee6c0`。应用版本由 `src/inkstruct/fonts/__init__.py` 的 `APP_VERSION` 提供，Python 库仍为 0.2.0。开发环境沿用项目 `.venv`，Python 3.13.16 x64、PySide6 6.9.2、PyInstaller 6.22.3。原始样本、作者档案、字体、生成结果、评价、已有工作区及历史交付包保留，未执行提交、推送或工作树恢复。

## 变化

- 排版设置中删除“导出此表…”、“单表仅保留数值格”和原引导文案，同时移除编辑器的单表导出调用。正文块选择器保留为一般定位用途。当前使用说明及手册移除对应操作内容。
- 表格设置的“应用范围”提供文档默认和正文中全部表格，可直接选择某张表，无需先定位源码。选择正文中的表格再打开时仍可定位该表。已有独立设置不被默认值覆盖，具体表格可恢复沿用默认。确定后应用于所选范围，切换范围重新载入该范围已保存的设置。
- 图片设置的“应用范围”提供文档默认和正文中全部图片。尚无图片时也能调整默认尺寸、对齐、图题间距及 SVG 容差。具体图片可保存独立设置或恢复默认。未修改继承项时不建立无意义的独立覆盖。文件导入绑定具体图片，取消不改变文档。
- 默认配置影响沿用默认的现有元素及后续新增元素。继续使用已有 `FlowStyle` 默认值和节点覆盖字段，保存/恢复协议不变，未改生成或字体协议。图片仍保留位图参考页与单线 SVG 机器路径的能力区分。
- 表格设置长参数区域可滚动；恢复默认勾选后停用个性化参数，避免输入被忽略。两个窗口未选中方框均为空心边框。

## 验证与限制

相关回归最终 **74 passed, 1 skipped**。涵盖表格/图片默认与覆盖、恢复默认、不同列数表格选择、空文档预配置、未修改继承项、取消事务、保存重开、后续新增元素、PNG 和单线 SVG 导入、文档导出及缓存、符号采集、公式设置和集成应用。静态检查通过。测试列表及准确参数保存在 `regression_verified.command.json`。

首轮测试发现旧 SVG 导入夹具需要先选择具体图片；另有测试未以 UTF-8 读取 UTF-8 导出 JSON，均已修正。真实符号链接越界检查因当前 Windows 账户无创建符号链接权限（WinError 1314）未验证，单独标记 skipped；网络路径及普通越界路径测试仍通过，生产路径检查没有放宽，也未更改 Windows 权限或安全设置。早期失败日志保留。

真实 Windows Qt 截图覆盖默认、个性化、恢复状态及元素面板。新版窗口及包内流程验收记录与截图存于本轮日志目录。实体数位板、设备驱动、中文输入法组合输入和写字机纸面效果仍沿用初始化记录的未验收边界。

最终 Windows 构建与包内自检通过：两方法各 11 字的真实 scx 导入、建档、生成、制作字体、排版、冻结保存重开和 SVG 检查，来源缺口提示保留。原生 EXE 实际点击确认元素面板无单表导出内容，空文档可打开两个默认设置窗口；配置查看已取消，未改文档。记录见 `native-elements.txt`、`native-table-default.txt`、`native-image-default.txt`。设置保存/恢复验收项目保存在本轮 `acceptance/scopes.inkdoc` 和 `acceptance/restored.inkdoc`，这是含未导入示例图片的设置测试文档，不是可直接导出的用户成品。

README、使用说明及 LaTeX 手册源码同步 0.1.7；本机未安装 TeX Live，未编译新版手册 PDF，历史 PDF 保留。

## 位置与命令

- 应用：`artifacts/windows_build_0.1.7_20261015/dist/InkStruct/InkStruct.exe`。
- 诊断：同目录 `InkStructTool.exe`，须保留整个 InkStruct 目录及 `_internal`。
- 归档：`artifacts/windows_release_0.1.7/InkStruct-0.1.7-Windows-x64.zip`，同目录校验记录、使用说明和 SHA256SUMS.txt。
- 日志、截图与测试产物：`artifacts/windows_ui_0.1.7_20261015/`。
- 包内流程：`artifacts/windows_bundle_check_0.1.7_20261015/verification.json`。
- 原生查看使用独立 `workspaces/windows-0.1.7`，已有工作区保留。

```powershell
.\.venv\Scripts\python.exe -m inkstruct.application --workspace workspaces/windows
.\.venv\Scripts\python.exe -m pytest tests/test_element_settings_qt.py tests/test_image_settings_qt.py tests/test_table_settings_qt.py tests/test_line_svg_qt.py tests/test_writing_workspace_qt.py tests/test_preview_cache_qt.py
.\.venv\Scripts\python.exe packaging/build_inkstruct_app.py --output artifacts/windows_build_next
artifacts/windows_build_0.1.7_20261015/dist/InkStruct/InkStructTool.exe --inkstruct-check --samples artifacts/source_samples/scx_351bf154/samples/scx --writer scx --font artifacts/inkstruct_0_1_20261014/fonts/user_001-0.1.inkfont --output artifacts/windows_bundle_check_next
```

构建与验收输出必须使用新目录；后续正式交付至少为 0.1.8。

两个 EXE 的 PE 产品及文件版本均为 0.1.7、架构 x64；构建源码哈希一致，ZIP CRC 通过。ZIP SHA256：`7c2dbf7b599a01b192554d9134183b68e0703c9d7dc88e82edc4e052d7a08257`。本次重建缓存、pytest 临时目录及 PyInstaller 中间目录已清理，清单见本轮 `cleanup.json`；设置验收项目、包内验收产物、日志与交付包保留。

可继续开发，本轮界面与设置功能可交付；符号链接权限检查及硬件验收的限制如上。
