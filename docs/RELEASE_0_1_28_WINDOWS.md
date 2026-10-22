# InkStruct 0.1.28 Windows：模板预览停止后保留已排内容

2026-10-19。已完成真实现场复现、最小修复、回归与 Windows 构建；可以继续开发和交付修复版。当前用户文档中的过宽公式仍需用户手动拆分或调整正文框，修复不会篡改原稿。

## 现场、原因与修复

用户从下载目录运行 0.1.27，粘贴 Markdown 后窗口仍可响应，预览只显示模板底图。已观察主进程及独立预览进程，未强制终止用户程序。

复制最新自动恢复包到本轮验收目录保留现场，原文件不改。5742 字符的源码在范围 `[4724,4851)` 有一条完整不可拆公式，实际宽约 189.1664 mm，而四张循环布局的正文框均宽 176 mm。无进展保护正常触发；错误在于 `layout_flow_template` 捕获异常后把此前页面全部替换成一张空页面，连已产生的诊断也丢失，造成空白预览。

本轮通过有界停止异常携带已经完成的页面、笔迹、图片占位和诊断；外层继续组合原模板背景、固定字段和框线。已经引用的脚注通过原脚注引擎完成，未排正文中的未来脚注不会被制造为孤立页面。无进展、页数、几何和导出检查保留，不自动缩字、删除节点或跳过问题对象续排。

状态栏明确提示“已保留已排内容，此处及后续正文尚未排版”，诊断含对象需要的毫米宽高，并可定位原 Markdown。内部模板排版缓存版本加上 `partial-preview-v1`；模板/文档协议不变，正常文档的排版输出保持一致。

同时发现当前有效恢复包的 `resources.json` 为 17,616,048 字节、1649 条资源记录，超过原来的统一 16 MB 单成员限制，使程序自己保存的文件无法读取。为资源聚合目录设置独立 128,000,000 字节上限；其他成员仍为 16,000,000 字节，压缩包 200 MB、解压总量 500 MB、30,000 条资源记录等限制及重复键、资源、字形、哈希、选样一致性检查保持。没有修改原包、伪造资源或绕过校验。

修复后，完整真实恢复包（非裁剪资源版本）保留 **5 页、2816 个字符实例**。源码、源码身份、全部资源、字体、文档设置、评价与冻结选样保持；保存重开后的调试预览 SVG 精确一致。过宽公式和缺失图片等诊断如实保留，正式导出仍被阻断。

## 环境与数据保留

- 项目：`C:/Users/lee/Documents/InkStructApp/InkStruct-Windows-Dev`。
- 基线 0.1.27；Git 基点 `af45b45f04f899fcaced43aa980b0508673ee6c0`，完整未提交工作树保留，改动前快照在 `implementation-baseline.zip`，不把 Git 历史视为完整源码。
- APP_VERSION 唯一应用版本来源，已递增到 0.1.28；README、使用说明、Windows 入口及 LaTeX 手册源码已同步。库和字体协议版本独立。
- Windows 11 x64 26300，项目 `.venv` Python 3.13.16 AMD64、PySide6 6.9.2、PyInstaller 6.22.3、Matplotlib 3.11.2；完整依赖和源码摘要见构建 provenance。
- 既有 2724 个可读数据/历史产物文件逐一 SHA-256 核对；3 个原本无读取权限的历史字体仅核对大小及时间，不改权限。原用户窗口保留，新版在独立工作区验证，未改全局默认原始记录。
- 未 reset、clean、提交或推送，未覆盖历史交付。仅清理本轮可重建缓存；数据、日志、原始恢复包和验收产物保留。

## 实际验证

- 回归 **1158 passed、2 skipped**，约 325 秒。两项跳过均因当前 Windows 用户无符号链接权限：真实图片链接和悬空项目链接；不计为通过。
- 新测试覆盖：过宽公式、代码行和表格行组保留已排前缀；多页及循环来源布局；已引用与未来脚注；正式导出阻断；源码定位；保存重开/选样/调试 SVG；Qt 编辑器粘贴、手动修复与撤销；大资源目录、哈希篡改、目录与普通成员独立容量上限。
- 真实现场：完整当前恢复文档直接载入；5 页/2816 个实例；过宽公式 189.1664 mm > 176 mm；完整资源、源码身份和选样不变。最初只为定位创建过裁剪未用资源的诊断副本，最终验证及原生验收均使用完整未裁剪恢复包。
- 原生 Windows 0.1.28：打开完整恢复副本，连续页面显示正文；“查看问题”选中过宽公式的准确源码；另存 `native-recovered.inkdoc` 并重开，保持全部资源和设置。原来的 0.1.27 用户窗口不关闭、不改稿。
- 包内综合自检通过，notices 为空；真实字体、分数线默认来源、模板部分预览及现有采集/生成/字体/导出功能通过。scx 11 字的 v6.1 exp 和 v4 adaptive 小流程通过，未重跑全库。
- 历史兼容：0.1.12 的 11 页/301 项诊断长文档与历史 SVG 摘要一致，设置无修改应用不改文档；0.1.21/22 模板、0.1.23 英文间距及 0.1.20 字符校正的冻结输出一致。
- 本轮 12 个修改 Python 文件 Ruff 通过；双 EXE x64 的文件版本和产品版本均核对为 0.1.28，构建源码与当前源码一致。

未验证：实体数位板、驱动、写字机纸面效果和中文输入法组合输入重测。LaTeX 手册仅同步源码，本机未安装 XeLaTeX/latexmk，未声称重编译 PDF。用户当前文档还有真实排版阻断，不能把已恢复的部分预览称为完整成品。

## 命令与产物

在项目根目录执行；重跑构建/自检使用新的输出目录：

```powershell
.venv/Scripts/python.exe -m inkstruct.application --workspace workspaces/windows-template-preview-new
.venv/Scripts/python.exe artifacts/template_preview_0.1.28_20261019/run_logged.py regression-recheck -- .venv/Scripts/python.exe artifacts/template_preview_0.1.28_20261019/run_regression.py
.venv/Scripts/python.exe packaging/build_inkstruct_app.py --output artifacts/windows_build_0.1.28_new
artifacts/windows_build_0.1.28_new/dist/InkStruct/InkStructTool.exe --inkstruct-check --samples artifacts/source_samples/scx_351bf154/samples/scx --writer scx --font artifacts/user_001_full_font_20261018_math_axis/user_001-v61-full-symbols-20261018.inkfont --output artifacts/windows_bundle_check_0.1.28_new
```

- 运行目录：`artifacts/windows_build_0.1.28_20261019_release/dist/InkStruct/`，保留两个 EXE 和 `_internal`。
- 交付：`artifacts/windows_release_0.1.28/InkStruct-0.1.28-Windows-x64.zip`，同目录含使用说明、SHA256SUMS、PE/ZIP 核验记录。
- 全部本轮现场、复现输入、源码快照、命令与日志：`artifacts/template_preview_0.1.28_20261019/`。重要文件：`recovery-origin.json`、`user-recovery-before.inkdoc`、`input-summary.json`、`reproduction-verified.json`、`native-recovered.inkdoc`、`native-*.png`、`native-verification.json`、`regression.log`、`windows-build.log`、`bundle-self-check.log`、`delivery-seal.json`、`cleanup.json`。
- 标明非成品的预览：`retained-preview-verified/`，只用于排查；不是放宽检查后的写字机输出。
- 包内检查：`artifacts/windows_bundle_check_0.1.28_20261019_release/verification.json`。
- 新工作区：`workspaces/windows-template-preview-0.1.28`。当前已恢复文档副本留在新版窗口供用户继续处理。
