# InkStruct Windows 桌面开发交接

当前 Windows 发布为 [**0.1.64**](docs/RELEASE_0_1_64_WINDOWS.md)。可从 [Windows Git 发布基线](docs/WINDOWS_GIT_BASELINE.md) 复核构建。团队成员请先阅读 [GitHub 协作与环境准备](docs/COLLABORATION.md) 和 [贡献约定](CONTRIBUTING.md)，按其中的 CPU 桌面环境、资源获取与分支流程启动。以下 0.1.3 迁移包说明仅保留为历史来源；其中 handoff 文件不随团队源码仓库分发，旧宿主机路径与初始化命令不作为新成员入口。

日期：2026-10-14。迁移基线：桌面应用 0.1.3；Python 库 0.2.0。这是源码和数据迁移包，不是已经验收的 Windows 安装包；没有为迁移快照另发应用版本。下一次交付应用至少为 0.1.4。

## 开始位置

解压到本地短路径，例如 `D:\InkStruct`，不要覆盖 Windows 上已有的仓库、样本或结果。需要 Python 3.13 x64；桌面源码支持 Python 3.12–3.13。当前旧离线编辑器包不包含完整生成依赖，本迁移包的安装步骤需要联网安装依赖。

在解压后的项目根目录打开 PowerShell：

```powershell
py -3.13 handoff\verify_files.py
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[desktop,dev]" "pyinstaller>=6,<7"
.\.venv\Scripts\python.exe -m inkstruct.application --workspace workspaces\windows
```

也可右键运行 `handoff\setup_windows.ps1` 完成环境安装，再运行 `handoff\run_windows.ps1` 启动。脚本未在 Windows 执行，本机不具备 Windows 系统。历史 `requirements.lock` / `requirements.txt` 是研究环境，含 CUDA/PyTorch；桌面开发请用上面的 extras，不要照旧锁文件安装训练环境。

`workspaces\windows` 是新的运行工作区，不会覆盖旧 Windows 采集库。请在界面中重新选择本机目录。归档中 macOS 原始路径保留用于审计，不代表 Windows 可直接使用；不要批量替换生成结果和字体内部路径，以免破坏哈希。旧的建档状态索引不可直接复用，应从原样本重新导入、建档。

## 当前实现与职责

- `src/inkstruct/application.py`：统一窗口，采集、生成、字体库、排版四页。
- `src/inkstruct/collector.py`、`symbol_capture*.py`、`capture_boundary.py`：采集包装与符号支持。外部内核完整放在 `artifacts/external/data_collection/handwriting_collector/`，不是缺失的相邻仓库依赖。此前已合并的 Windows 差异记录在 `artifacts/inkstruct_0_1_20261014/*.windows.diff`；本次没有用共享盘旧检出覆盖 Mac 当前实现。
- `desktop.py`、`generation_workflow.py`、`generation_v61_helpers.py`：应用真实生成流程。默认 v6.1 exp（推荐），另选 v4 adaptive；不能改名 source-raw 冒充 v6.1。
- `fonts/`：完整字形的不可变字体发布、身份、来源警告及用户版/开发者版；字体库制作窗口不重新生成。
- `editor/`、`document/`、`layout/`、`math/`、`plotter/`：Markdown、公式、模板、冻结文档、仅 M/L path 的写字机输出。
- `packaging/inkstruct_app.spec`、`build_inkstruct_app.py`：统一应用构建。Windows 预期产物为 `dist\InkStruct\InkStruct.exe`，命令行自检入口为 `InkStructTool.exe`。

0.1.3 已去掉排版页重复的打开、保存、撤销、重做按钮，保留文件/编辑菜单及快捷键；采集页目录交接入口已删除。生成页分阶段显示，字体库以已有字体为中心，制作窗口按需打开。

应用中不提供训练、神经网络、CUDA 状态；相关历史代码保留在源码，不是桌面必装依赖。Matplotlib 的几何判断是 v6.1 参考修正的必要依赖，不能一并删除。

## 包内数据

- `artifacts/structures/characters.sqlite3` 及 `third_party/makemeahanzi/`、`configs/`：启动和生成所需结构库、原始参考与修正规则；第三方授权文件一并保留。
- `artifacts/source_samples/`：scx、mjb、wsq 的原始采集样本；`artifacts/samples/` 是已有导入记录。
- `artifacts/v61_collection_acceptance_20261013/run_v3_with_validation/`：user_001 的合并样本、档案与验证记录。该历史目录含验证用途样本，不能将其历史覆盖率当作无泄漏验证结论。
- `handoff/raw_archives/`：user_001 原始符号与补录 ZIP，保留原文件，不默认将验证用样本混入新建档。
- `artifacts/v61_corrected_library_20261014/full_v1/`：四位作者各 9,574 字的已冻结修正全库结果，轨迹、来源、变换、缺口记录一并保留；其 protocol 中直接列出的输入文件也已收齐。它是历史人工审核/跨字生成产物，不等同当前应用重新建档后一定逐字复现的结果。
- `artifacts/inkstruct_0_1_20261014/fonts/`：四位作者的用户版和原始开发者版完整字体，共 8 个；另保留完整点列往返验证记录。略去内容重复的脱敏 share-developer 副本。
- `profiles/{user_001,scx,mjb,wsq}/`：已有作者档案；不要直接复用其宿主机路径状态。
- `检查项目/`：已有评价项目和分析。`.inkreview` 如含旧目录引用，请重新定位资源，不修改评分数据。
- `handoff/desktop_workspace_snapshot/`：本机统一应用已有工作区的只读迁移快照。可以导入其中字体或选择生成结果；不要原样覆盖 Windows 新工作区的状态文件。
- `artifacts/release_0_1_2/`、`artifacts/release_0_1_3/` 中筛选的报告、字体/文档小样和验证记录：判断已验证内容及边界。旧 macOS `.app`、全部打包缓存、虚拟环境、早期重复全库和无关研究中间产物未打包。

包中保留用于本人接续开发的作者原始样本与来源细节；这不是面向公众分享的脱敏发布包。文件范围以 `handoff/manifest.jsonl` 为准。缺少某个历史实验的其他间接数据不应通过替换数据默默绕过；桌面标准流程不依赖那些历史实验。

## Windows 验收顺序

先校验压缩包和文件清单，再安装依赖。启动并检查四页切换、采集画布与输入焦点、菜单/快捷键、中文粘贴、真实数位板笔压及窗口外落笔。Windows 的原生事件和驱动不可由 macOS 检查替代。

小集合真实生成检查：

```powershell
.\.venv\Scripts\python.exe scripts\verify_application_generation.py --samples artifacts\source_samples\scx_351bf154\samples\scx --writer scx --text 人物理羝羚而铜伯攣盼⺼ --output artifacts\windows_e2e_01
.\.venv\Scripts\python.exe -m pytest tests\test_generation_workflow.py tests\test_integrated_window_qt.py tests\test_writing_workspace_qt.py tests\test_font_packages.py
```

输出目录必须是新目录。两种方法都应完成：导入 → 建档 → 生成 → 用户/开发者字体 → 排版与冻结文档。`攣`、`⺼` 的参考回退提示不能丢；来源不完整但协议有效可确认继续使用，损坏轨迹不能警告放行。

构建当前基线用于 Windows 验证：

```powershell
.\.venv\Scripts\python.exe packaging\build_inkstruct_app.py --output artifacts\windows_build_01
.\artifacts\windows_build_01\dist\InkStruct\InkStructTool.exe --inkstruct-check --samples artifacts\source_samples\scx_351bf154\samples\scx --writer scx --font artifacts\inkstruct_0_1_20261014\fonts\user_001-0.1.inkfont --output artifacts\windows_bundle_check_01
```

正式向用户交付前递增 `APP_VERSION`、同步文档及发布名并重新构建；构建验证目录必须新建。若窗口版启动失败，先用 `InkStructTool.exe` 查看终端错误。包内不附 Windows EXE，不宣称已完成 Windows 构建或驱动验收。

## Git 与接续注意事项

压缩包是当前磁盘快照，包含尚未提交的桌面应用代码。`git-history.bundle` 只保存提交历史，不包含这些未提交文件；不要只 clone bundle 就当作完整迁移。`handoff/git-status.txt` 和补丁记录原状态，不自动提交或推送。

如需恢复 Git 历史，可在另一空目录 clone `handoff/git-history.bundle` 的 `codex/v61-starter-collection` 分支，然后把本包工作树覆盖到那个新目录；保留新目录的 `.git`，不要覆盖已有 Windows 工作仓库。第三方 Makemeahanzi 已按实际内容打包，不需为了启动重复拉取；其历史子模块状态与当前快照要分别看待。

优先阅读根目录 AGENTS.md、本文件、docs/INKSTRUCT_0_1.md 与 docs/user_manual/。早期研究交接文档的「缺数据」「生产默认」描述有历史时效，不能覆盖当前应用实现和最新验收记录。
