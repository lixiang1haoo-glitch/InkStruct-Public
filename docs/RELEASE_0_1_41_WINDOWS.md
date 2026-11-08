# InkStruct 0.1.41 Windows 合并交付记录

2026-10-26。已把独立排版目录的 preview 更新合入主项目，并构建标准 InkStruct Windows x64 应用。应用版本唯一来源为 `src/inkstruct/fonts/__init__.py:APP_VERSION`，本次为 **0.1.41**；Python 库仍为 0.2.0。README、使用说明、LaTeX 手册源码与发布文件名同步。手册 PDF 未重新编译，历史 PDF 不代表本版本。

## 合并依据与边界

主项目：`C:/Users/lee/Documents/InkStructApp/InkStruct-Windows-Dev`；输入目录：`C:/Users/lee/Documents/InkStructApp/InkStruct-Layout-Dev`。HEAD 为 `af45b45f04f899fcaced43aa980b0508673ee6c0`，实际输入是其上的完整未提交快照，未从 Git 历史重建或替换源码。

先读取两侧约定和独立目录的隔离记录，再使用 `.isolation/copied-file-hashes.json` 中原始完整快照哈希做三方核对：检查范围为源码、打包、测试、脚本、配置与相关文档，60 处输入变化无双方内容冲突。外部 Git 状态读取被沙箱拒绝，未用“外部工作树干净”作为依据；采用实际文件、基线哈希与逐文件差异。合入 59 个文件，外部 `scripts/run_layout_regression.py` 依赖独立启动器，改用主项目私有设置测试入口。没有覆盖整个目录或复制用户工作区。

合并前字节保存在 `artifacts/integration_0.1.41_20261026/before/`，完整合并前 src 另存 `premerge-src-0.1.40.zip`，SHA-256 `fc0cf44d60f2025ab90a06aa1874715cc27baea3ebb27451070080dfaa1df948`。差异、输入哈希和合并清单在同目录。原有 15 个 tracked dirty 文件及所有 untracked 工作保留；部分文档按本次授权更新，旧字节留存。不执行 reset、clean、提交或推送。独立目录只读，独立 Preview 包及旧交付不覆盖。

合并内容包括：

- LaTeX 单 token 参数，例如 `\sqrt6`、`\frac12`，缺参数仍有明确诊断。
- 全角点 `．` 的明确复用，以及缺少独立目标时由同作者 h 与减号合成 `\hbar`；保留来源、动态数据和冻结选择，不做全局 Unicode 替换。
- 录制减号横线、横线装饰，以及以数学轴为中心、保留端部/腰部的括号伸缩。
- `\newline`、`\linebreak` 换行；`\newpage`、`\pagebreak`、`\clearpage` 跳物理页；`\framebreak` 在连续正文中换正文框。字段、表格、脚注等禁止上下文继续诊断。
- 显式区分旧 preview 换框别名语法与新版物理分页。只有对应旧 preview dialect 才提示迁移并要求另存；原件不改，标准旧项目继续按原路径读取。参见 [命令说明](TEXT_FLOW_BREAK_COMMANDS.md)。

标准构建 `layout_preview=false`，ProductName 为 InkStruct；不把主应用默认工作区改成 preview-data。独立 Preview 启动/构建入口保留为显式工具，未自动切换默认运行路径。v6.2、v6.1、v4 生成引擎没有因本次合并更改；v7 仍只在 research 内。

## 本机验证

Windows 11 x64，Python 3.13.16 x64、NumPy 2.5.4、PySide6 6.9.2、Matplotlib 3.11.2、PyInstaller 6.22.3、pytest 9.1.1，使用主项目既有 `.venv`，无新依赖。

1. **1,286 项回归全部通过，119.33 秒，无跳过。** 涵盖公式语法/几何、符号/字体、文档资源、冻结选样/身份、模板/字段/续排/脚注、采集任务、字表、生成、多进程与后台导出、资源管理及集成窗口。准确命令、stdout/stderr、退出码在 `test-logs-03/`，JUnit 为 `regression-03.xml`。
2. 新增功能 Qt 集成检查通过：同页双框、物理分页与普通页面、异步页面图像就绪、旧 preview 项目显式迁移/原件不变/另存、公式/派生符号、保存重开与严格 SVG。产物 `layout-source-check-02/`。这是源码 Qt 自动检查，样本为合成符号和内置数字，不冒称真实书写评价。
3. **真实 user_001 字体**：215 字符、1207 候选、102559 点，原包 SHA `94d87fb5f47c53725f73a4bdbe324301aa8337a9159723338156f28dbfe54f74`。新公式、全角点和物理分页形成两页文档，23 项选样；保存重开后完整快照、源码身份和冻结选样一致，严格机器 SVG 字节一致。原包哈希不变，6 项数学校准 warning 原样保留。见 `real-font-check/`，不是新字体发布或全库质量结论。
4. 冻结 **InkStruct.exe** 的真实档案回归：孔、正、址、兄、礼、烧、止、怔、歪、羊、群，串行/2/4 进程均完成，payload 一致、无隐式回退。完整 8105 字目录保留 1239 缺口，实际支持目标 6866；仅生成指定前 12 字附近便取消（实际提交 13 字），与独立串行子集 payload 一致。没有重跑全库。档案 SHA `31b9d65be17b5517bc9cc544bad8bd83af190bf01420b49ea7526c825608cf81`；见 `app-generation-check/`。
5. 冻结 **InkStructTool.exe** 使用真实字体验证 4 页后台 SVG：4 进程、缓存命中、取消以及模拟子进程故障后的串行回退，冻结快照与全部导出设置一致，无错误提示。见 `tool-export-check/`。双 EXE 的 PE Machine 均为 AMD64，FileVersion/ProductVersion 均为 0.1.41，ProductName 均为 InkStruct，见 `exe-versions.json`。
6. computer-use 实际观察私有工作区中的 **源码原生 Windows 窗口**：标题 0.1.41、四个模块、真实字体两页预览、新公式和 6 项提示可见。自动点击编辑区后可访问性焦点仍显示页码控件，未继续注入文字；不宣称完成本轮原生键盘/中文输入验收。树记录 `native-accessibility.json`，窗口图/最终状态在 `native-source-check/`。冻结自检入口固定 offscreen；尝试传入 windows 环境的那轮仍属离屏，未冒称原生验收。

前两轮回归失败均保留：首轮 1229 passed/34 failed/23 errors，为沙箱系统临时目录权限；调整到私有临时目录后 1237 passed/26 failed/23 errors，为沙箱禁止字体发布的原子 `os.link`。没有修改字体发布协议；相同回归在沙箱外全部通过。首轮页面检查也因沙箱中预览伴随进程未返回图像而超时；沙箱外同脚本 4.52 秒通过。错误日志和失败产物未删除。唯一主项目验收脚本补充是隔离 TEMP、Qt/采集设置和 spawn 子进程环境，默认用户应用设置不变。

封装核查发现首个未交付候选包仍含独立 Preview 的部分文档表述，两行新增中文说明经 shell 管道传输时退化为问号。已用原生文件补丁修正，逐个检查本轮合入文本无连续问号/替换字符；原候选完整保存在验收目录 `package-candidate-01/`，用相同已验收双 EXE 重新封装最终 ZIP。没有覆盖历史交付或重编出第二个同版本应用。

未验证：实体数位板/驱动、中文输入法组合输入、写字机纸面、全部字体/模板的人工视觉质量、冻结应用的人工原生交互和性能提升。没有用历史 macOS 或外部 Preview 的 1275 项记录替代上述本机结果。

## 运行、重现与交付位置

在项目根目录运行，所有 `NEW` 目录必须尚不存在；若系统沙箱阻止硬链接或伴随进程，应在有权限的普通终端运行，不修改校验逻辑：

```powershell
.venv/Scripts/python.exe -B -X utf8 -m inkstruct.application --workspace workspaces/windows-0.1.41-NEW
.venv/Scripts/python.exe -B -X utf8 scripts/run_layout_regression.py --junitxml=artifacts/regression-0.1.41-NEW.xml --basetemp=artifacts/pytest-0.1.41-NEW
$env:INKSTRUCT_LAYOUT_PREVIEW_HOME = "$PWD/artifacts/layout-private-NEW"
$env:QT_QPA_PLATFORM = 'offscreen'
.venv/Scripts/python.exe -B -X utf8 packaging/inkstruct_layout_launcher.py --inkstruct-layout-check --output artifacts/layout-check-NEW
.venv/Scripts/python.exe -B -X utf8 packaging/build_inkstruct_app.py --output artifacts/windows_build_0.1.41-NEW
artifacts/windows_build_0.1.41_20261026/dist/InkStruct/InkStructTool.exe --inkstruct-check --output artifacts/export-check-NEW --font artifacts/charsets_0.1.40_20261022/font-validation/user_001-v62-generation-0.1.40-validation.inkfont --samples artifacts/integration_0.1.41_20261026/layout-check-temp --export-only
artifacts/windows_build_0.1.41_20261026/dist/InkStruct/InkStruct.exe --inkstruct-check --output artifacts/generation-check-NEW --generation-profile artifacts/v61_collection_acceptance_20261013/run_v3_with_validation/source_archive.json
```

`--export-only` 不读取 samples；该参数是现有自检 CLI 的必填占位，路径使用隔离空目录。真实字体检查脚本为 `artifacts/integration_0.1.41_20261026/real_font_check.py`，固定输出保护不会覆盖，重跑时先复制脚本并改为新目录。原生窗口脚本为同目录 `native_source_check.py`，120 秒后自动退出，仅写私有设置与验收产物。

标准可运行目录：`artifacts/windows_build_0.1.41_20261026/dist/InkStruct/`。发布包：`artifacts/windows_release_0.1.41/InkStruct-0.1.41-Windows-x64.zip`，完整解压后启动 InkStruct.exe，保留 `_internal` 和 InkStructTool.exe。新包不附用户历史数据、不自动迁移工作区；旧默认位置不改。ZIP CRC、哈希、双 EXE 及资源保全核对见同目录 `delivery-verification.json`；构建源哈希与构建期间无变更证据见 build 目录 `build-provenance.json`。全套日志与验收输入输出位于 `artifacts/integration_0.1.41_20261026/`。

本轮 v7 研究独立结论见 [最小检索实验与暂缓决定](../research/v7_gap_minimal/REPORT.md)：没有为研究额外升级版本、接入默认生成或另发字体；原有包围分支继续暂缓。
