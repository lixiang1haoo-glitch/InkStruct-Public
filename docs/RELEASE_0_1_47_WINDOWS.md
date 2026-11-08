# InkStruct 0.1.47 Windows 交付记录

2026-11-05。实际项目 `C:/Users/lee/Documents/InkStructApp/InkStruct-Windows-Dev`；Git HEAD `af45b45f04f899fcaced43aa980b0508673ee6c0`。以含全部未提交工作的完整工作树构建，未通过 Git 历史恢复或覆盖源码。APP_VERSION 从 0.1.46 递增为 **0.1.47**；Python 库 0.2.0、字体格式和既有文档／模板协议保持。

**结论：本轮回归、Windows 构建、双 EXE 冻结检查、原生界面验收及最终 ZIP 解压运行验证完成，可交付。**

## 范围

- 主窗口采用左侧常驻“采集／生成／排版”，底部为“字体库／设置”。名称与版本位于系统标题栏，无重复顶部品牌栏。设置保持 Ctrl+,；Alt+1/2/3/4 切换模块，F1 或侧栏右键查看关于。
- 字体库使用简洁列表、右侧身份详情和真实汉字／公式／自定义试写，预设隐藏原文框，编辑试写及切换草稿保留；来源、缺字及完整验证状态不隐藏。字符、样本、来源版本和文件信息保留。
- 采集、生成、排版和模板页统一分区、标题、留白与线形图标。采集仅让当前子页决定所需高度，保留画布最小尺寸、点列和真实溢出滚动；模板空库不再误标为资源损坏，真实读取错误仍阻断应用。
- 保留任务管理与重录、生成方式和每字成品上限、字体完整校验、模板适配、文档撤销／保存重开／冻结选样及严格 SVG。未加入 v7 研究、神经网络或新生成方法，未改旧字体、作者样本或旧文档。

以上界面代码为已验收源码试点的正式纳入。本轮新改动是应用版本与文档同步，没有再扩展生成核心或修改协议。README、完整使用说明、统一应用说明、LaTeX 手册源码与分发文件名已同步；历史交付和历史特性版本记录保留。新版 PDF 手册未重编译，ZIP 提供当前无外部依赖的使用说明。

## 环境和回归

Windows 11 x64（10.0.26300）、Python 3.13.16 AMD64、PySide6 6.9.2、NumPy 2.5.4、Matplotlib 3.11.2、PyInstaller 6.22.3；沿用本项目 `.venv`，无新增全局依赖或训练环境。开工可用磁盘约126.4 GB。

- **117 个不同测试文件、1632 个唯一用例通过，0 失败、0 错误、0 跳过，402.88 秒。** XML 已核查无重复计数。覆盖数学、符号、资源、字体、模板、连续分页、脚注、保存重开、冻结与导出，并补入新侧栏、采集生命周期、生成数量／语义、主题和工作区等相关用例。100%、150%、200% 是本轮 Qt 自动化验证，不能冒充三种 DPI 的原生人工验收。
- 本轮相关界面源码和测试 Ruff 通过。
- 真实旧文档专项：原 `real-math.inkdoc` 保持 2 页、23 处冻结选样和源码身份；切换导航／浏览字体后保存重开，严格 SVG 逐页字节相同；6 条数学未校准提醒保持，原字体及文档 SHA256 不变。

日志为 `artifacts/release_0.1.47_20261105/regression.log`、`regression.xml`、`regression-summary.json`、`real-document-final/result.json`。

## Windows 构建与冻结运行

标准 `packaging/build_inkstruct_app.py` 完成新目录构建。329 份构建输入在构建前后哈希一致。双 EXE 均为 AMD64，FileVersion 和 ProductVersion 均为 **0.1.47**。

1. 正式 `InkStructTool.exe` 使用真实 user_001 档案，对“嘤喳啜哮”执行串行及双进程小字集生成；均为4字13候选，完整 payload、顺序与动态数据一致，无回退，原“喳”来源缺口保留。两次12.04／14.78秒，本轮后台还有回归等负载，不作为并行性能结论。制成新实验字体，96处冻结选择、保存重开与严格SVG一致。
2. 正式 `InkStruct.exe` 的离屏自检完整读取两份真实大字体：9780字／37500候选及7072字／29726候选，4个真实 spawn 工作进程，分别74.68／63.67秒完成完整逐候选验证；总检查179.47秒。来源提示3204／1887份、数学度量警告保留；3页187处中英／数学混排、首末页预览、保存重开、严格SVG通过；共同29726候选及同位置输出保持。未重跑全库生成。
3. 两份 EXE 的上述检查使用原正式分发目录，没有替换应用模块。`build-provenance.json` 保留构建时尚未运行验收的原记录；后续 `runtime-validation.json` 另行记录真实通过的运行证据，不倒改原记录。

## 原生冻结程序验收

真实冻结 `InkStruct.exe` 和打包应用模块在 Windows Qt 平台运行，1360×900逻辑尺寸、DPR1.5。使用正式目录完整真复制的私有副本，仅替换副本 `_internal/inkstruct-smoke.py` 自检数据入口，使 QSettings、采集配置、恢复目录和工作区隔离；双 EXE 和其余全部正式模块字节一致，正式目录未变。不是源码 GUI，也不宣称普通生产入口具有同一私有配置机制。

实际操作通过：四模块导航，左下设置打开及取消，生成页完整控件；原生文件框导入真实454351365字节简体＋扩展字体，4进程完整验证29726候选，源包与库内副本SHA相同；默认真实汉字混排和公式示例均形成可见笔迹，1887份来源提示及两项公式校准提示常驻。用于当前文档前经过原适配确认；Ctrl+1聚焦源码后输入中文、数字、公式与表格，1页96实例实际可见区域就绪；点击“沐”定位源码，显示样本1/8及周边字符校正预览。没有触碰生产字体库或旧文档。

导入过程按1秒采样边界约45.32秒；只是本次真实验收观察值，不是冷启动性能对照。原生未执行保存重开或SVG点击操作，相关正确性由上述真实冻结自检及旧文档专项分别证明。UIA焦点字段偶有滞后，以可见光标及实际控件记录确认，没有窗口激活失败。私有入口停止时显式清理预览进程后正常退出，不把此辅助关闭当作用户保存关闭交互验收。

原生记录：`native/native-result.json`、`native/run-01/events.jsonl`、`native/formula-native.png`、`native/final-native.png`。实际输入为 `native/actual-input.md`。副本差异核查见 `native/bundle-after-native.json`。

## 分发及完整性

- ZIP：`artifacts/windows_release_0.1.47/InkStruct-0.1.47-Windows-x64.zip`
- 体积：**127038697 字节**；1675个文件，含使用 README 和当前使用说明。
- SHA256：`a97f028e42160e787f12034600e1eb380fd39036acf75ca90818bd561a721819`
- CRC和逐文件SHA通过；全新解压后全部文件SHA与归档一致。
- 从 `verified-extraction/InkStruct` 作为工作目录，清除子进程 PYTHONPATH／PYTHONHOME，实际运行解压后的 Tool 做上述四字生成、制包、冻结、重开及SVG检查，exit0，30.87秒。输入档案为明确传入的真实数据，不依赖项目cwd提供应用代码。

运行只读结构库后产生32 KiB SHM与空WAL，329份构建输入及1673份原分发文件字节均不变。最终ZIP仅排除这两份已确认可重建运行副产物；没有删除数据库或修改结构内容。检查和排除记录在 `delivery-verification.json`、`bundle-after-runtime.json`。

完整解压后运行 `InkStruct/InkStruct.exe`，沿用原工作区及原自定义 `--workspace` 参数，不要求卸载或删除用户数据。个人字体不内置进应用ZIP。

## 准确命令与位置

项目根目录 PowerShell；带 NEW 的路径必须是新目录，避免覆盖本次及历史交付。

```powershell
.venv/Scripts/python.exe -B -X utf8 -m inkstruct.application
.venv/Scripts/python.exe -B -X utf8 scripts/run_layout_regression.py tests/test_app_shell_qt.py tests/test_capture_workflow_qt.py tests/test_capture_writer_guard_qt.py tests/test_candidate_count_qt.py tests/test_generation_candidate_limits.py tests/test_generation_resources.py tests/test_generation_variant_balance.py tests/test_v62_semantics.py tests/test_light_theme_qt.py tests/test_writing_workspace_qt.py tests/test_template_gui_qt.py --junitxml=artifacts/regression-0.1.47-NEW.xml --basetemp=artifacts/pytest-0.1.47-NEW
.venv/Scripts/python.exe -B -X utf8 packaging/build_inkstruct_app.py --output artifacts/windows_build_0.1.47-NEW
$env:INKSTRUCT_LAYOUT_PREVIEW_HOME = (Join-Path (Get-Location) 'artifacts/frozen-private-0.1.47-NEW')
& artifacts/windows_build_0.1.47_20261105/dist/InkStruct/InkStructTool.exe --inkstruct-check --generation-profile artifacts/candidate_count_full_20261104/input_audit/profiles_all_capture/user_001/b46b32ddfc6ef1b8.json --candidate-check --writer user_001 --output artifacts/frozen-check-0.1.47-NEW
```

大字体GUI命令和解压运行的完整参数分别记录在 `runtime-validation.json` 对应结果及 `extracted-command.json`；真实GUI大字体使用 `--inkstruct-check --large-font-check --large-font <全结构包> --large-font <简体包> --output <NEW>`。辅助复制和归档脚本留在本轮产物根目录，不应原样覆盖重跑。

构建：`artifacts/windows_build_0.1.47_20261105/dist/InkStruct`；所有源快照、Git状态、日志、验收、SHA和实验新字体：`artifacts/release_0.1.47_20261105`。开工533份文件中本轮仅11份版本／文档变化，其余522份保持；此前全部界面未提交修改纳入构建并保留。两个原大字体、作者档案和原文档哈希未变。没有reset、clean、提交、推送或修改独立排版开发目录，没有覆盖历史交付。

收尾保留源码、资源、日志及交付产物，仅清理本轮 PyInstaller work 下已列举核验的20个可重建中间文件及空目录，构建告警已另存；未清理用户或旧实验缓存。

未验证：实体数位板、驱动、写字机和纸面效果，跨显示器 DPI、Windows 独立文本放大、完整读屏／IME，以及最终冻结版的1000×720原生交互（本轮 Qt 自动测试覆盖，源码试点原生结果另有历史记录，未冒称为本次冻结验收）。未重新编译LaTeX PDF或进行Word级性能对照。
