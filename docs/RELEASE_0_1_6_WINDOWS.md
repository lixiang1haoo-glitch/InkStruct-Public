# InkStruct 0.1.6 Windows 更新记录

日期：2026-10-15。项目：`C:\Users\lee\Documents\InkStructApp\InkStruct-Windows-Dev`。应用版本由 `src/inkstruct/fonts/__init__.py` 的 `APP_VERSION` 定义为 0.1.6，Python 库仍为 0.2.0。原有数据、工作区、未提交修改及历史交付均保留，无提交或推送。

## 修复

Windows 深色样式将任务创建窗口的未选中复选框也绘制为蓝底，区分不清。本次仅对该窗口的 `QCheckBox::indicator:unchecked` 设置透明背景及灰色边框；已选中的强调色底和对勾继续由系统绘制。任务数据、类别、份数、生成与字体协议均不变。

## 验证

- 40 项既有相关回归测试通过，日志：`artifacts/windows_ui_0.1.6_20261015/tests.log`。
- 使用真实 Windows Qt 平台分别渲染系统、深色、浅色主题，确认未选中为空心灰框、选中有底色和对勾。鼠标点击选中、空格取消勾选均通过。截图与记录：`artifacts/windows_ui_0.1.6_20261015/visuals/`。
- 新构建与包内流程通过：scx 两种方法各 11 字导入、建档、生成、字体制作、排版、冻结保存重开和 SVG 检查。来源缺口汇总保持可见。结果见同目录 `build.log`、`bundle.log` 和 `artifacts/windows_bundle_check_0.1.6_20261015/verification.json`。
- 已在新 EXE 的任务弹窗实际点击取消“英文正体”，确认变为空心框，邻近已选项仍为蓝底白勾，汇总同步由 1200 变为 940 份。验收配置已取消，未创建用户采集任务。可访问性记录见同目录 `native-task-dialog.txt`；原生查看使用独立的 `workspaces/windows-0.1.6`。
- README、使用说明和 LaTeX 手册源码已同步 0.1.6。本机未安装 TeX Live，新版手册 PDF 未编译；历史 PDF 保留。设备验收范围沿用初始化记录，不新增数位板、驱动或写字机验收结论。

## 产物与命令

应用：`artifacts/windows_build_0.1.6_20261015/dist/InkStruct/InkStruct.exe`；诊断入口同目录 `InkStructTool.exe`。保留整个 `InkStruct` 目录及 `_internal`。

交付归档：`artifacts/windows_release_0.1.6/InkStruct-0.1.6-Windows-x64.zip`，同目录保存 SHA256SUMS.txt、使用说明及校验记录。

两入口 PE 版本均为 0.1.6，x64，构建源码一致性与 ZIP CRC 已验证。归档 SHA256：`7e4ac95aab4b5b2750b5e7af78441c0afbefa5ea8ca9601af8f3fb56697635e1`。本次临时目录、pytest 与安装/绘图缓存及 PyInstaller 中间目录已清理，清单见本轮 `cleanup.json`；构建警告已另存日志目录，交付产物保留。

```powershell
.\.venv\Scripts\python.exe -m inkstruct.application --workspace workspaces\windows
.\.venv\Scripts\python.exe -m pytest tests/test_symbol_capture_ui.py tests/test_symbol_capture.py tests/test_math_settings_qt.py tests/test_integrated_window_qt.py tests/test_font_packages.py tests/test_symbol_provider.py tests/test_generation_workflow.py
.\.venv\Scripts\python.exe packaging/build_inkstruct_app.py --output artifacts/windows_build_next
```

构建使用全新目录，后续正式交付递增至至少 0.1.7。可继续开发；本补丁可作为界面修复交付，完整硬件验收的限制沿用 Windows 初始化记录。
