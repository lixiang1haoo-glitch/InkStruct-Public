# InkStruct 0.1.10 Windows：汉字样本与标点扩展

日期：2026-10-15。实际项目：`C:\Users\lee\Documents\InkStructApp\InkStruct-Windows-Dev`。
在原完整、含未提交修改的工作树继续开发，Git 基点 `af45b45f04f899fcaced43aa980b0508673ee6c0`。
应用唯一版本来源为 `src/inkstruct/fonts/__init__.py:APP_VERSION=0.1.10`；Python 库仍为 0.2.0，任务、样本和字体协议版本保持不变。下次正式应用交付至少为 0.1.11。

## 本次变更

- 采集内部固定两个标签“汉字样本”“标点与扩展”，默认进入汉字样本；不提供用户类型、快捷预设或额外采集标签。
- 标点、数字、英文正体、斜体、数学符号、希腊字母及变体自由组合；类别可展开逐字勾选，默认全部不选。斜体字形预览按斜体显示。TXT/CSV 导入按实际字表勾选字符，仍可筛选，保留目标份数。
- 每个字符目标份数默认 5；同作者、同字符、同写法的活动样本计入已有份数，仅创建补差额任务。中英共用标点使用现有明确共享规则，不重复录制。
- “查看笔迹并配置复用…”显示实际已录英文正体笔迹，支持查看每一份，逐项或批量勾选后明确确认。斜体可复用同字母正体；相似希腊大写字母提供 14 对建议（例如 Α ← A），不自动合并小写或变体。
- 未选录不表示复用；没有已录正体时须先采集来源。取消不提交，切换作者清除未提交关系。允许只保存复用配置而不创建录制份次。
- 新任务把逐项确认关系及来源样本 ID 嵌入 source 配置，沿用原任务 schema。旧 v1/v2 任务保持兼容，不迁移、不重建。
- 制作字体需选择含 tasks 和 samples 的完整 `symbol_collection` 根目录或 ZIP。确认复用保留原始点列、压力、时间、固定参考线度量与来源身份；不机械倾斜，不生成虚假采集样本。希腊字符保留自身 Unicode。独立录制的目标写法优先；来源缺失或被重录时要求重新确认，不能静默改用新样本。
- 新字体记录 `confirmed_reuse` 来源，仍为未审阅状态；旧字体、既有冻结排版文档不自动改写。生成核心与两种方法不变。

## 数据保留与原生验收

沿用 `workspaces/windows-0.1.8`，本次没有创建新的用户工作区或迁移旧任务。
`user_001` 补录任务 ID 为 `5d222672-07a7-4593-8d29-372cc206259d`，当前实际进度为 **691/900**，cursor 为 **530**，当前待采希腊大写 Γ，第 1/5 份。

升级前采集目录共 700 个文件；升级并载入任务、打开逐字配置、查看实际笔迹、确认临时复用预览后取消任务创建，再次逐文件 SHA-256 核对：700 个文件全部不变，无新增或删除，任务 ID、条目、样本 ID、进度及历史重录备份均保留。
审计见 `artifacts/windows_ui_0.1.10_20261015/capture-before.json` 和 `capture-preservation.json`。

新 EXE 已实际启动：两个标签可点击，现有任务可继续，斜体可单字勾选，已满足份数会提示无需重复创建，复用窗口可查看原始笔迹并勾选确认。验收配置最终取消，未给用户增加测试任务。应用停留在原任务待采状态。
原生可访问性证据 `native-loaded.txt`、`native-confirmed-preview.txt`；独立 Windows Qt 布局截图 `han-tab.png`、`extension-tab.png`、`create-task.png`、`individual-italic.png`、`confirm-reuse.png`。

## 测试、构建与限制

环境为 Windows x64、项目 `.venv` Python 3.13.16 x64、PySide6 6.9.2、PyInstaller 6.22.3、Matplotlib 3.11.2；没有修改全局 Python 或安装训练依赖。

- 正式回归：**115 passed、1 skipped**，退出码 0。覆盖逐字选择、取消与确认、作者隔离、补差额、复用配置单独保存、来源失效拒绝、独立字形优先、目录/ZIP 字体发布、样本字节保留、Unicode/正斜体身份、来源记录、排版冻结及保存重开，以及原有采集、重录、生成和排版回归。
- 唯一跳过项：当前 Windows 账户缺少创建符号链接权限（WinError 1314），真实符号链接检查未验证，没有放宽生产检查。最初普通沙箱执行字体原子发布硬链接失败（WinError 5），在获准的正常项目测试执行环境复测通过，未修改字体发布实现。
- Ruff 检查通过。全部最终日志和准确命令见 `artifacts/windows_ui_0.1.10_20261015/{regression_final,lint}.log` 及 `.command.json`。初次失败日志保留，最终结论以正式回归为准。
- 新目录 PyInstaller 构建成功；`InkStruct.exe` 和 `InkStructTool.exe` 均为 Windows x64，PE FileVersion/ProductVersion 均为 0.1.10。构建期间源码未变化，发布前逐文件源码哈希匹配。
- 包内真实 scx 的 11 字小集合通过 v6.1 exp、v4 adaptive 两条流程：导入、建档、生成、制作字体、排版、保存重开和 SVG。冻结结果完全一致、仅 M/L 路径检查通过，来源缺口警告保留；没有重跑全库。报告 `artifacts/windows_bundle_check_0.1.10_20261015/verification.json`。
- ZIP CRC 校验通过。SHA-256：`daf8d4d3e7aa95db574d86be96a3c7ab0229e06ebdef96d9d38d05925bb77c9c`。
- README、采集说明、集成说明、LaTeX 手册源码和发布包使用说明已同步。当前没有 XeLaTeX/latexmk，多文件手册 PDF 未重编译，历史 PDF 保留。
- 实体数位板、压感、驱动和写字机纸面结果仍未验证。可以继续开发并交付本次 Windows 软件更新，不能据此认定硬件已验收。

## 运行与产物

项目根目录 PowerShell：

```powershell
& 'artifacts/windows_build_0.1.10_20261015/dist/InkStruct/InkStruct.exe' --workspace workspaces/windows-0.1.8

.venv/Scripts/python.exe artifacts/windows_ui_0.1.10_20261015/run_logged.py regression_final .venv/Scripts/python.exe artifacts/windows_ui_0.1.10_20261015/run_regression.py

# 重建必须使用新的输出目录；正式新版先递增 APP_VERSION。
.venv/Scripts/python.exe packaging/build_inkstruct_app.py --output artifacts/windows_rebuild_0.1.10_new
```

- 可运行应用：`artifacts/windows_build_0.1.10_20261015/dist/InkStruct/InkStruct.exe`，须保留整个 InkStruct 目录。
- 交付 ZIP：`artifacts/windows_release_0.1.10/InkStruct-0.1.10-Windows-x64.zip`。
- 发布验证与校验和：同目录 `verification.json`、`SHA256SUMS.txt`。
- 构建来源：`artifacts/windows_build_0.1.10_20261015/build-provenance.json`；日志 `artifacts/windows_ui_0.1.10_20261015/`。

本轮只清理可重建的私有测试、绘图、临时缓存与 PyInstaller work；源码、原始数据、日志、截图、发布包、历史交付及所有用户修订备份保留。清理清单为日志目录的 `cleanup.json`。
