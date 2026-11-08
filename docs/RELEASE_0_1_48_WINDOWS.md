# InkStruct 0.1.48 Windows 交付记录

2026-11-06。主工作区为 `C:/Users/lee/Documents/InkStructApp/InkStruct-Windows-Dev`，Git HEAD 为 `af45b45f04f899fcaced43aa980b0508673ee6c0`。基于现有工作树从 0.1.47 接续，应用版本取自 `APP_VERSION`。Python 库仍为 0.2.0。使用 Windows 11 x64、Python 3.13.16、PySide6 6.9.2、PyInstaller 6.22.3 构建。

## 交付内容

- 左侧底部依次为字体库、模板库和设置。两库独立打开，排版资源栏分别进入对应库，生成结果仍交接到字体库。Alt+4 和 Alt+5 分别打开字体库、模板库。
- 汉字画布高度滑块、字体试写居中加载提示及会话缓存纳入发布。字体切换保留缺字和来源提示。
- 模板按稳定布局 ID 预览，优先第一张起始页，其次第一张循环页。下拉列表标记起始、循环和未编入顺序的布局。有底图显示原图及配置区域，无底图显示纸张轮廓及区域。读取、渲染、加载及无布局状态在预览区显示。后台结果只可更新其对应的当前选择。
- 普通和流式模板停止生成 `template-calibration-unreviewed`。校准字段、平移偏移、越界、溢出及必填字段检查继续保留。
- `inkstruct_template_revision_v1` 是独立的修订封装，保存模板身份、修订身份、父修订、序号及内容哈希。内层 v1/v2/v3 布局协议继续读取。旧文件的相同字节按内容哈希识别，未标识模板从规范化内容取得确定性身份。编辑库内模板可另存修订，独立复制建立新身份，同名旧文件只有在用户明确确认后才建立修订关系。
- 文档使用内嵌快照。资源栏在确认有后续修订时提供查看新版，适配对比包含纸张、区域、字段、页数、溢出及失效绑定。已声明的同 ID 字段继续从原 Markdown 读取。显式换版可取消或撤销，保存后重开使用新快照。设为新文档默认独立操作。
- 字体原版连接以字体 ID、发布 ID、核心哈希同时相等为准，先完整验证字包。旧文档可从单一的内嵌字体身份恢复这一关联。无法唯一确定旧字体的历史文档继续使用内嵌字形，可手动更换。手动换版报告可保留的冻结选样、待重选位置及新增缺字。新文档所保存的原版关联由带版本的 `font-source.json` 记录，字体包协议保持原样。
- 新修订封装由 0.1.48 读取。早于 0.1.48 的程序读取含新封装的模板或文档不在本轮兼容范围。旧文档原件继续保留。

## 验证结果

- 43 个相关测试文件隔离运行，共 **434 项通过**，含 433 项主选集和 1 项独立恢复测试。另有 **23 项**最终重点重测与 **58 项**协议和模板专项通过，均与主选集有重叠。测试覆盖旧格式、内容哈希、独立复制、绑定保留和失效提示、取消、撤销与重开、字体精确匹配及仅新版时的换版影响。
- 首次直接回归记录保留，得到 429 通过、5 失败。其中四个 GUI 用例在非隔离环境中未通过，私有设置下通过。另一个适配报告测试原来借用已移除的校准提醒，现以真实必填缺失验证旧报告结果拒绝。
- 原生预检发现程序化换文档时光标可能短暂选中旧快照。已在替换源码期间屏蔽这类同步，最终冻结原生复测通过且 stderr 为空。
- Windows Qt 原生验收为 **1360 × 900，DPR 1.5**。使用截图中的真实四页模板，验证 0 起始、4 循环，默认 PDF 第 1 页且显示底图，逐页切换 2 至 4 页。另检查起始页优先、简单模板、未编排无底图布局、空库、注入渲染失败和损坏副本读取失败。
- 原生冻结版确认原模板移出后旧文档可开，换版可取消、撤销、重做并保存重开。真实旧排版项目 **23 处冻结选样**、两页严格 SVG 哈希及六条原数学提醒与历史记录一致。使用约 454 MB 的真实原版字体验证新增文字缺字、完整验证后恢复覆盖、原选样保留及保存重开。真实模板、字体、旧文档原件哈希一致。
- 原生验收在正式目录的隔离复制件中进行，仅用验收脚本替换自检数据入口，双 EXE 及应用模块来自正式构建。正式 ZIP 全新解压后的原版 `InkStructTool.exe` 另行通过真实作者四字生成、制包、冻结及严格 SVG 自检。串行和双进程均得到 4 字 13 候选，保留“喳”来源提示；96 处选样，重开前后 SVG 一致。离屏 Qt 字体目录和尺寸提示留在 stderr。
- 双 EXE 均为 AMD64，FileVersion 和 ProductVersion 均为 **0.1.48**。331 项构建输入在运行后仍与构建记录一致。真实数位板、驱动、写字机纸面及跨显示器 DPI 未在本轮验收。

## 产物和复现

- 正式 ZIP 为 `artifacts/windows_release_0.1.48/InkStruct-0.1.48-Windows-x64.zip`，127,094,196 字节，1,675 项成员。CRC 与新目录解压逐文件 SHA-256 核验通过。ZIP SHA-256 为 `1c0b60ba3be9014df0be184cccddce97b59b03ef34431a06e5e63b5ad67b174e`。
- 正式双 EXE 在 `artifacts/windows_build_0.1.48_verified_20261106/dist/InkStruct`，构建日志和输入哈希位于其构建根。README、使用说明和 LaTeX 手册源码同步，既有手册 PDF 未重新编译。
- 验收根为 `artifacts/release_0.1.48_20261106`。保留回归文件清单、原始日志、JUnit、双 EXE 版本、归档脚本、真实原生截图及 `native-final/run-01/result.json`。解压工具结果位于 `extracted-tool/verification.json`。试跑包与其记录另存，正式包不包含个人字体。

在项目根目录运行以下 PowerShell 命令。复跑构建和自检时使用未占用的输出路径。

```powershell
.venv/Scripts/python.exe -B -X utf8 -m inkstruct.application
.venv/Scripts/python.exe -B -X utf8 packaging/build_inkstruct_app.py --output artifacts/windows_build_0.1.48-NEW

$e = (Resolve-Path 'artifacts/release_0.1.48_20261106').Path
$repo = (Get-Location).Path
$env:PYTHONPATH = "$e/regression-support;$repo;$repo/src;$repo/packaging"
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:INKSTRUCT_LAYOUT_PREVIEW_HOME = "$e/regression-replay-NEW"
$env:QT_QPA_PLATFORM = 'offscreen'
$files = Get-Content "$e/regression-files.txt" | Where-Object {$_ -notmatch 'test_package_recovery_qt.py$'}
.venv/Scripts/python.exe -B -X utf8 -m pytest -p no:cacheprovider -o addopts='' -q $files
$env:INKSTRUCT_TEST_RECOVERY_RELATIVE = '1'
.venv/Scripts/python.exe -B -X utf8 -m pytest -p no:cacheprovider -o addopts='' -q tests/test_package_recovery_qt.py
Remove-Item Env:INKSTRUCT_TEST_RECOVERY_RELATIVE
```

从正式 ZIP 解压的 `InkStruct` 目录运行 `InkStruct.exe`。工具自检使用 `InkStructTool.exe --inkstruct-check --candidate-check --generation-profile <作者档案路径> --writer user_001 --output <新目录>`。本轮使用的真实档案是 `artifacts/candidate_count_full_20261104/input_audit/profiles_all_capture/user_001/b46b32ddfc6ef1b8.json`。原生脚本 `native-final/run.ps1` 接收构建目录、四页模板、原版字体、旧文档及历史 SVG 结果，详见其参数。

没有执行 reset、clean、提交或推送。没有改动独立排版开发目录，没有覆盖历史交付包。仅清理了两份原生试跑的可重建字体副本，原字体、用户数据、快照及验证产物保留。
