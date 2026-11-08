# InkStruct 0.1.53 Windows

设置窗口默认优先使用显示器工作区能容纳的大尺寸。间距与数学轴、矩阵和多行对齐的参数总览同时展示多行示例，聚焦输入框只改变标线高亮。其他示例可从下拉框手动选择。

模板工作台将“保存修改”和“另存为新模板”分开。保存库内模板时沿用原模板身份，当前列表显示最新修订，旧版本可在“显示历史修订”中查看。保存待入库的最近文件时写回原 JSON，遇到原文件已被修改时会提示。另存为新模板创建独立副本。已保存文档保留其内嵌模板。

构建和验证产物位于 `artifacts/settings_templates_0.1.53`。从项目根目录运行以下 PowerShell 命令可复现构建，输出目录需为空或使用新路径。

发布包为 `release/InkStruct-0.1.53-Windows-x64.zip`。解压后的两个 EXE 的文件版本和产品版本均为 0.1.53，且各通过 11 类公式设置自检。ZIP 的 1,675 个成员通过 CRC 检查，SHA-256 为 `484507773d8f268d8580ee8d1361a179dbe32487f636e49d813f8428d2aa8db1`。

```powershell
$e = (Resolve-Path 'artifacts/settings_templates_0.1.53').Path
.venv/Scripts/python.exe -B -X utf8 packaging/build_inkstruct_app.py --output "$e/windows-final"
& "$e/verify_delivery.ps1"
```

Windows 原生公式检查在 150% 和 200% 缩放下各通过 27 项。300% 缩放下模拟 1280 × 696 的逻辑工作区，设置窗口为 1240 × 632，独立公式窗口为 1220 × 632。模板原生检查验证了库内更新、历史修订、另存独立副本、外部文件写回，以及保存错误后重试。相关回归通过 745 项，窗口尺寸调整后另复测 27 项。

原生公式截图和检查日志分别位于 `native-150` 和 `native-200`。模板编辑截图位于 `template-native-light`。LaTeX 手册源码已同步，手册 PDF 沿用原版。
