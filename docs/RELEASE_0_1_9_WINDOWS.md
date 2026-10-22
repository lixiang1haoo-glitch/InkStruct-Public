# InkStruct 0.1.9 Windows：字符预览与误录重采

日期：2026-10-15。项目：`C:\Users\lee\Documents\InkStructApp\InkStruct-Windows-Dev`。
基于原有完整、含未提交修改的工作树继续开发；Git 基点 `af45b45f04f899fcaced43aa980b0508673ee6c0`。
应用版本唯一来源 `src/inkstruct/fonts/__init__.py:APP_VERSION=0.1.9`；Python 库 0.2.0，样本、任务与字体协议版本未变。下次应用交付至少 0.1.10。

## 修复与使用

- 字母与符号目标预览改为 88 px、160 × 150 区域；斜体任务按斜体显示。集成采集窗口走 `create_only` 路径，提前返回，原来的采集全局样式没有应用，导致目标标签退回普通字号；现由标签自身明确设置字号。
- 新增“重录已保存…”：显示原始笔迹预览，可 Ctrl/Shift 多选，或选同字符、同写法的全部已保存份次。确认后退回待采，再次保存生成新样本。
- 原来的“重写”改为“清空当前笔迹”，避免与已保存重录混淆。“继续／打开任务”可以重新打开已完成任务纠错。
- 重录前原始字节和任务快照写入 `symbol_collection/revisions/<修订ID>/`；原文件为 `.json.bak`，不再参与活动样本对账和字体导入。已有字体、冻结排版文档保持原样，后续需重新制作字体才会使用新笔迹。
- 保存失败回滚、提交前后中断恢复、任务过期拒绝均有测试。初版备份目录层级触发 Windows MAX_PATH，已改为扁平修订目录；没有更改系统长路径设置。

## user_001 实际纠错

沿用用户已有工作区 `workspaces/windows-0.1.8`，不迁移或重新创建任务。
任务 ID：`5d222672-07a7-4593-8d29-372cc206259d`，总量仍为 900 份。
旧应用正常保存排版文档后退出，再通过本次同一重录服务退回已核实的 B 第 1–3 份，随后启动新应用载入任务。

- 进度从 8/900 回到 5/900，当前为英文正体 B，第 1/5 份，画布空白。
- 五份正确的 A 保留，逐文件 SHA-256 一致；其余任务条目逐字段核对不变。
- 三份旧 B 样本完整备份，逐字节核对；不伪造补录样本、不把旧 A 改标签为 B。
- 备份目录：`workspaces/windows-0.1.8/capture/symbol_collection/revisions/b3442d50f95c49ae8f1b9a8ed0f390e3/`。
- 审计：`artifacts/windows_ui_0.1.9_20261015/user_001-correction.json`，包含三个样本 ID、原始哈希与验证结果。
- 升级前排版文档保存在 `artifacts/windows_ui_0.1.9_20261015/document-before-upgrade.inkdoc`。
- 新版原生界面实际确认大号 B、5/900、第 1/5 份，以及已保存窗口中仅有五份 A；查看后取消，不修改 A。证据 `native-loaded.txt`；只读渲染图在 `visuals/`。

## 验证结果与限制

环境：Windows x64，项目 `.venv` Python 3.13.16 x64，PySide6 6.9.2，PyInstaller 6.22.3，Matplotlib 3.11.2。

- 相关回归 108 passed、1 skipped，退出码 0；跳过项是实际符号链接检查，当前 Windows 账户缺少创建符号链接权限（WinError 1314），未降低生产检查。
- Ruff 检查通过。日志 `regression_final.log`、`lint.log`；失败尝试日志保留，最终结果以这两份为准。
- PyInstaller 构建成功；`InkStruct.exe` 与 `InkStructTool.exe` 都为 x64，PE FileVersion/ProductVersion 均为 0.1.9；构建源码哈希与当前源码一致。
- 包内使用 scx 实际样本，v6.1 exp 与 v4 adaptive 的 11 字小集合两条生成流程、制字体、排版保存重开、冻结结果、SVG 路径检查通过；原有来源缺口提示保留。报告 `artifacts/windows_bundle_check_0.1.9_20261015/verification.json`。
- 新 ZIP 完整 CRC 校验通过，SHA-256 `bf43daf07547fc29aa2721471e7d0beb0f35ef9156069cc346c76358fb3e2dd1`。
- README、说明与 LaTeX 手册源码已同步；未安装 TeX 编译器，新版 PDF 未重编译，原 PDF 保留。
- 实体数位板、压感、驱动与写字机仍未验证；可以继续开发并交付本次软件修复，不能据此宣称硬件验收完成。

## 启动、测试与构建

以下命令在项目根目录 PowerShell 执行。原生应用已启动并停留在待补录的 B。

```powershell
& 'artifacts/windows_build_0.1.9_20261015/dist/InkStruct/InkStruct.exe' --workspace workspaces/windows-0.1.8

.venv/Scripts/python.exe -m pytest tests/test_symbol_revisions.py tests/test_shared_punctuation.py tests/test_symbol_capture.py tests/test_symbol_capture_ui.py tests/test_symbol_provider.py tests/test_document_resources.py tests/test_font_packages.py tests/test_element_settings_qt.py tests/test_image_settings_qt.py tests/test_table_settings_qt.py tests/test_writing_workspace_qt.py tests/test_preview_cache_qt.py tests/test_line_svg_qt.py tests/test_images.py tests/test_flow_style.py tests/test_document_package.py tests/test_math_settings_qt.py tests/test_integrated_window_qt.py tests/test_generation_workflow.py -ra

# 后续重建选新的目录，保留本次交付；正式新版须先递增 APP_VERSION。
.venv/Scripts/python.exe packaging/build_inkstruct_app.py --output artifacts/windows_rebuild_0.1.9_new
```

准确已执行命令、时间与退出码见 `artifacts/windows_ui_0.1.9_20261015/*.command.json`。
应用：`artifacts/windows_build_0.1.9_20261015/dist/InkStruct/InkStruct.exe`。
交付包：`artifacts/windows_release_0.1.9/InkStruct-0.1.9-Windows-x64.zip`；同目录有 `verification.json` 和使用说明。
日志：`artifacts/windows_ui_0.1.9_20261015/`；构建证据：`artifacts/windows_build_0.1.9_20261015/build-provenance.json`。

保留源码、日志、真实数据、修订备份、排版文档、发布包及历史交付；只清理本轮可重建的 PyInstaller 工作目录和私有测试/绘图/下载临时缓存。
