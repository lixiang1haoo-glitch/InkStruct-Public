# Windows 初始化与基线验收记录（2026-10-15）

当前可以继续 Windows 桌面开发。已得到可运行的 **0.1.4 Windows x64 验收候选包**，源码测试、真实 scx 小集合流程及包内自检通过。尚不作为完成全部设备验收的正式交付：真实数位板/驱动、窗口外落笔、中文输入法组合输入、写字机纸面输出、干净 Windows 机器及签名发布未验收；0.1.4 LaTeX 手册源码已同步，PDF 尚未重编译。

## 项目与迁移完整性

- 实际目录：`C:\Users\lee\Documents\InkStructApp\InkStruct-Windows-Dev`。未使用相邻旧项目。
- 迁移基线：应用 0.1.3，Python 库 0.2.0。当前验收候选：应用 0.1.4；库版本保持 0.2.0，字体协议保持原状。应用版本唯一来源为 `src/inkstruct/fonts/__init__.py:APP_VERSION`。
- Git 历史基点：`af45b45f04f899fcaced43aa980b0508673ee6c0`，分支 `codex/v61-starter-collection`。首次检查时没有 `.git`，已从本地 `handoff/git-history.bundle` 导入历史至 `handoff/source`，建立 HEAD 和历史基线索引；没有 checkout、reset、clean、提交或推送，快照中的未提交实现保留。
- 首次检查时根目录仅有顶层文件和部分 artifacts，系统仍有 ZIP 解压任务。旁边存在同名 `InkStruct-Windows-Dev-0.1.3-20261014.zip`，其中包含完整工作树。仅以独占新建方式补齐缺失条目，遇到已有文件就跳过；优先补齐了 19,934 个源码、文档等条目，未用 bundle 中的已提交文件覆盖当前快照。另两个慢速重复扫描已停止，不代表迁移损坏。
- 修改迁移源码前，补充并行 SHA-256 校验 **175,991/175,991 一致**；随后官方 `handoff/verify_files.py` 也成功打印 `Verified 175991 files.`。原清单没有改写。修改前 Git 状态、环境、清单结果和最后的数据保留复核均另存到本次日志目录。
- 已阅读并核对 `AGENTS.md`、`WINDOWS_START_HERE.md`、`docs/WINDOWS_DEVELOPMENT_HANDOFF.md`、`docs/INKSTRUCT_0_1.md` 和相关手册、源码、测试。

资源核对：结构库只读 `PRAGMA integrity_check` 为 `ok`，`characters` 表为 9,574 行；外部采集内核 11 个文件，Makemeahanzi 19,169 个文件，configs 57 个文件。scx/mjb/wsq 原样本共 2,379 个文件，user_001 合并样本和原始 ZIP 一并在清单内；四位作者档案、四作者各 9,574 字的历史冻结全库结果、8 个用户版/开发者版完整字体、已有评价均保留。具体大小和路径见 `baseline.json`。没有重新生成全库或改写旧结果中的 macOS 路径、评分、字体身份或旧建档状态索引。

## 开发环境

| 项目 | 实际版本/状态 |
|---|---|
| Windows | Windows 11，10.0.26300，AMD64/x64 |
| Python | 3.13.16，64 位，MSC v.1944 |
| 基础解释器 | `C:\Users\lee\AppData\Local\Programs\Python\Python313\python.exe` |
| 项目环境 | 本项目 `.venv`，不继承系统 site-packages |
| 初次磁盘空间 | 总计约 930.6 GiB，剩余约 378.5 GiB；后续采样见 baseline.json |
| PySide6 / shiboken6 | 6.9.2 / 6.9.2 |
| NumPy / Pillow / Matplotlib | 2.5.4 / 12.3.0 / 3.11.2 |
| markdown-it-py / mdurl | 4.0.0 / 0.1.2 |
| pytest / ruff | 9.1.1 / 0.17.0 |
| PyInstaller / hooks-contrib | 6.22.3 / 2026.8 |

已执行 `pip install -e ".[desktop,dev]" "pyinstaller>=6,<7"`，`pip check` 通过，完整版本见 `pip_freeze.log`。没有使用旧 requirements 文件，没有安装 CUDA、PyTorch、h5py 或 lmdb。为只读定位本次包内自检等待点，另在项目环境安装了 py-spy 0.4.2；它不是应用运行依赖，也未加入 pyproject。

沙箱中的 `py --list-paths` 未找到已装解释器，而 `python` 实际可用；因此本次准确命令使用 `python` 和 `.venv\Scripts\python.exe`。首次 ensurepip 因沙箱临时目录权限失败，改用项目内 TEMP/TMP 后成功。首次联网安装因沙箱 DNS 无法解析 PyPI 失败，经允许在正常网络环境重试后成功。字体测试的 NTFS 硬链接被沙箱拒绝，正常 Windows 权限下重新测试通过。没有修改全局 Python、驱动、系统安全设置或其他项目环境。

本机 PowerShell 执行策略禁止直接运行 `.ps1`；本次使用 Python 命令完成启动/测试/构建，缓存清理使用直接的原生 PowerShell 命令，未调整执行策略。不要将交接脚本能在另一台机器运行当成本机已验证；优先使用本文列出的准确命令。

## 必要修复

1. **显式 UTF-8 文本 I/O**：Windows 默认 `cp936`，初始真实流程在结构修正 JSON 读取处抛出 `UnicodeDecodeError`。仅补充生成状态/协议 JSON、结构与审核修正配置/参考 JSONL、错误日志、包内自检报告和算法一致性测试源码读取的编码声明。最终源码流程在默认 GBK 文件编码下通过，未设置 `PYTHONUTF8` 或 `-X utf8` 作为修复。早期 `-X utf8` 诊断另有记录，不计作最终修复验收。
2. **SVG 新目录发布的短暂 Windows 拒绝访问**：一次完整流程导出 v4 时出现 WinError 5，同一冻结文档十次复测中再现一次。仅对 Windows 的 WinError 5/32 增加最多六次目录改名尝试，等待总和最多 0.62 秒；每次都重新拒绝已经出现的目标目录，最终仍失败则抛出原错误。没有改动轨迹、路由算法或协议检查。已加入短暂锁恢复、竞争写入者目录保留测试；失败日志与复测记录保留。尚未确认具体哪个外部进程持有瞬时目录句柄，不将其归因为某个驱动或安全产品。
3. **包内自检的合成输入适配**：旧自检使用固定像素点，调用栈显示停在边缘警告确认；测试点改为按实际画布宽高取比例，并断言状态为 clear。未自动确认、屏蔽或删除应用边缘警告。包内工具输出显式 UTF-8，支持 `⺼` 等字符。
4. **版本与本地工作区**：应用递增至 0.1.4；Windows 两个 EXE 的 FileVersion/ProductVersion 都从 APP_VERSION 生成。README、使用说明、LaTeX 手册源码和下一次交付约定已同步；`.gitignore` 加入 `workspaces/`，防止本地采集和生成产物误入源码提交。

未改变生成核心、字体协议、方法列表或界面设计。没有通过替换字形、降低验证要求或隐藏来源警告使测试通过。

## 实际验收结果

| 验收 | Windows 实测结果 |
|---|---|
| 初始指定测试（正常文件权限） | 11 passed，1 failed；失败为测试使用 GBK 读取 UTF-8 源码 |
| 编码修复后指定四个测试文件 | 12 passed |
| 最终指定测试 + `test_plotter.py` | **26 passed**，含两个 Windows 发布竞争/锁回归测试 |
| scx 实样本导入 | 两种方法分别导入 793 份；建档接纳 785 份/785 字；v6.1 完整来源轨迹 778 份 |
| 11 字集合 | `人物理羝羚而铜伯攣盼⺼`；v6.1、v4 各 **11 完成、0 失败** |
| 用户/开发者字体 | 两版核心一致；逐点坐标、压力和时间精确保留；v6.1 2,506 点，v4 4,552 点 |
| 冻结文档 | 两种方法均排版、保存 `.inkdoc`、重开，布局快照与候选选择完全相同 |
| 来源提示 | v6.1 保留 `攣`、`⺼` 缺口；v4 对 11 字保留来源不完整提示；确认状态随文档冻结 |
| SVG | 两种方法均导出；包内自检进一步检查 SVG 子元素仅 path，指令仅 M/L |
| 制作字体交接 | 两种真实生成结果自动带入作者和目录；处理时全部输入锁定；成功后关闭弹窗并选中新字体 |
| 界面约定 | 默认 v6.1 exp（推荐），另一选项仅 v4 adaptive；生成页三阶段；字体库管理已有字体；采集目录交接入口不存在；排版重复按钮不存在，菜单快捷键保留 |
| 包内自检 | 最终 `InkStructTool.exe --inkstruct-check` **exit 0**；合成采集保存、两方法 GUI worker、字体制作、完整 user_001 字体、输入/粘贴、冻结重开、SVG 均通过，notices 为空 |
| 原生交互 | 源码窗口和独立 EXE 实际启动；四页可切换；中文粘贴、Ctrl+Z、Ctrl+Y、Ctrl+S、Ctrl+O 已操作验证；原生保存 `native-input.inkdoc`，打开真实 v6.1 11 字冻结文档并看到实际手写排版及来源提示 |
| 原生采集 | 创建示例任务和控件点击有效；画布为 tablet-only，鼠标拖动未形成笔迹，不计作真实笔输入通过 |

最终自检结果：`artifacts/windows_bundle_check_0.1.4_20261015_final/verification.json`；截图为该目录 `capture.png`、`generate.png`、`fonts.png`、`layout.png`。该记录明确写明 offscreen，原生交互证据另见本次日志目录的 `native-*.txt` 和 `native-input.inkdoc`，两者不能混称。

## 后续准确命令

以下均在项目根目录的 PowerShell 中执行，不需要激活环境。输出目录必须换成从未存在的新路径。

```powershell
Set-Location 'C:\Users\lee\Documents\InkStructApp\InkStruct-Windows-Dev'
.\.venv\Scripts\python.exe -m inkstruct.application --workspace workspaces\windows
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m pytest tests\test_generation_workflow.py tests\test_integrated_window_qt.py tests\test_writing_workspace_qt.py tests\test_font_packages.py tests\test_plotter.py
.\.venv\Scripts\python.exe scripts\verify_application_generation.py --samples artifacts\source_samples\scx_351bf154\samples\scx --writer scx --text '人物理羝羚而铜伯攣盼⺼' --output artifacts\windows_e2e_next
.\.venv\Scripts\python.exe packaging\build_inkstruct_app.py --output artifacts\windows_build_next
.\artifacts\windows_build_next\dist\InkStruct\InkStructTool.exe --inkstruct-check --samples artifacts\source_samples\scx_351bf154\samples\scx --writer scx --font artifacts\inkstruct_0_1_20261014\fonts\user_001-0.1.inkfont --output artifacts\windows_bundle_check_next
```

本次命令及退出码还逐项保存在 `artifacts/windows_initialization_20261015_01/*.json`。如仍在受限沙箱运行且临时目录不可写，可用本次 `run_logged.py` 包装命令；它仅把 TEMP/TMP、pip 和 Matplotlib 缓存指向项目内，设置 UTF-8 日志输出，不启用 UTF-8 文件模式。后续正式交付新的应用构建应至少为 **0.1.5**，从 APP_VERSION 修改，同步文档并用新目录构建，不覆盖现有候选或历史交付。

## 应用与产物位置

- 可运行目录：`artifacts/windows_build_0.1.4_20261015_final/dist/InkStruct/`；`InkStruct.exe` 为 GUI，`InkStructTool.exe` 为诊断工具。保留整个目录及 `_internal`，不能只复制 EXE。
- 验收候选归档：`artifacts/windows_release_0.1.4/InkStruct-0.1.4-Windows-x64.zip`；归档哈希、文件清单及最终源码一致性见同目录 `verification.json`。这是供本机继续开发/设备验收的候选，不宣称全部设备和正式发布验收完成。
- 构建日志、依赖与源码摘要：`artifacts/windows_build_0.1.4_20261015_final/{build.log,build-provenance.json,source-before.json}`。构建脚本的 `runtime_verified` 字段默认仍为 false，实际运行结果另见本次自检和发布验证记录。
- 最终源码实样本全流程：`artifacts/windows_e2e_0.1.4_20261015_03/`，含两种方法的开发者字体、用户字体、冻结文档、SVG、工作区及 verification.json。
- 包内全流程：`artifacts/windows_bundle_check_0.1.4_20261015_final/`。
- 新运行工作区：`workspaces/windows/`；未复用旧 `handoff/desktop_workspace_snapshot` 状态。
- 本次日志与辅助验收：`artifacts/windows_initialization_20261015_01/`。基线失败、诊断、初始构建及中间验收结果均保留为审计记录，不作为最终交付入口。
- 保留原 ZIP、原清单、历史字体/全库/样本/档案/评价。清理仅针对本次可重建缓存；清理清单和最终保留校验见日志目录的 `cleanup.json` 与 `preservation.json`。

## 剩余边界

真实数位板品牌/连接、驱动、笔压、抬笔、窗口外落笔、整行输入和 Moonlight 等远程笔链路均未验收；不能用鼠标、合成点或 macOS 记录代替。写字机连接、落笔/抬笔和纸面尺寸未验收。没有进行中文输入法候选/组合输入测试，只验证了中文粘贴。没有重新做四位作者全库生成、全部历史研究测试、全字体视觉复核或声称本次重建逐字复现历史人工冻结全库。尚未做独立干净 Windows 虚拟机、签名/安装器、SmartScreen 发布体验验收。未安装 TeX Live，0.1.4 手册 PDF 未重编译；历史 0.1.3 PDF 未覆盖。上述事项不阻止本机继续开发，但应在正式用户交付前完成对应范围的验收。
