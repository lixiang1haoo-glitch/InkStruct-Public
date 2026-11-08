# InkStruct 0.1.33 原生 Windows 验收补充

2026-10-20。用户将已启动的 0.1.33 窗口置于前台后，继续使用 Computer Use 完成本次功能的原生交互验收。程序来自 `artifacts/windows_build_0.1.33_20261020_release/dist/InkStruct/InkStruct.exe`，实际窗口标题为“ InkStruct 墨构 · 0.1.33 ”。本次没有修改生产代码、重建应用或覆盖历史交付；应用仍为 0.1.33。

此前 `failed to activate captured window` 是自动化激活阶段的阻碍。本次窗口可读取、可输入、可点击，已补齐该构建的以下屏幕交互检查。系统文件对话框及部分 Qt 弹窗的辅助功能索引不可用，改用当次截图中的控件坐标和键盘完成，没有修改应用来绕过验收。

## 原生操作结果

| 操作 | 本次实际结果 |
|---|---|
| Ctrl+O 打开真实字体小样 | `native-input.inkdoc` 正常形成 2 页、185 个文本实例；℃、–、～、表格及分式显示正常 |
| SVG 弹窗默认项 | 表格内容、路径优化勾选；横纵比例 100%；定位点关闭；Esc 取消正常 |
| 实际导出 | 显式选择第 1 页、不导出表格内内容、路径优化开启、横向 101%、纵向 99%、定位点开启，选择新目录后成功 |
| 导出范围与坐标 | 仅生成 `page-001.svg` 和 `plotter.json`；完整文件字节/JSON 与同一冻结文档按上述选项计算的对照结果一致 |
| 表格与定位点 | 省略 11 条表格内容笔画；表格线与表外内容保留；两个定位短线记录在对应缩放后正文框边界 |
| Ctrl+Shift+S 另存、Ctrl+O 重开 | 新副本正常保存并重开，仍为 2 页、185 个文本实例；包内全部成员逐字节一致，源码身份、选样、样式、资源与原文档一致 |
| 保留诊断 | `math-calibration-unreviewed` 提示仍在；没有隐藏警告 |
| 齿轮设置 | “应用设置 → 预览绘制”可达，CPU 默认、GPU 可选、下次启动生效及错误回退说明清楚；查看后取消，未更改用户后端偏好 |
| 点击与连续滚动 | 点击 ℃ 显示 U+2103、样本 3/5 及周边字符；连续滚动进入第 2 页，页面正常绘制 |

本次是原生交互及产物正确性验收，不是新的前台性能测量。本次前台窗口使用 CPU；GPU 的真实打包工作进程及像素验证记录仍见原交付记录，不将 CPU 窗口操作称作 GPU 前台验收。

## 文件与复核

根目录为 `C:\Users\lee\Documents\InkStructApp\InkStruct-Windows-Dev`。

- 原生导出：`artifacts/integration_0.1.33_20261020/native-ui-svg-page1/`。
- 原生另存项目：`artifacts/integration_0.1.33_20261020/native-ui-saved.inkdoc`。
- 对照产物、真实结果及哈希：`artifacts/integration_0.1.33_20261020/native_followup_20261020/`。
- 核对脚本：`artifacts/integration_0.1.33_20261020/verify_native_followup.py`。实际执行 `.venv/Scripts/python.exe -B -X utf8 artifacts/integration_0.1.33_20261020/verify_native_followup.py`，退出码 0。脚本使用独占新输出目录，复跑需先将脚本中的 `FOLLOW` 改为新的验收目录，保留本次证据。
- 交付目录新增 `InkStruct-0.1.33-Windows-原生验收补充.md`、`native-acceptance-supplement.json` 和独立 `NATIVE_SHA256SUMS.txt`。

完整核对旧 `SHA256SUMS.txt` 中的五个交付文件，均未变化；290 个构建来源文件哈希仍与构建记录一致；原始验收输入未变化。此前发布的 `verification.json` 和 `delivery-seal.json` 中 `native_ui_acceptance_complete: false` 保留为初始历史，后续状态以此次独立补充记录为准。没有改写既有封存记录来掩盖当时的未验证项。

本轮补测用 `-B` 避免生成 Python 字节码；未新建需要删除的临时缓存。新项目、SVG、对照、核对脚本和记录均保留。

本次功能范围的原生交互验收已完成，可继续使用既有 0.1.33 Windows 交付。数位板、驱动、写字机、实体比例校准、外部工具裁切表现、其他厂商 GPU、驱动重置和长会话压力仍未验证。原回归的两项符号链接权限跳过及手册 PDF 未重新编译的限制保持。
