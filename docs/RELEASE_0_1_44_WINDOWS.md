# InkStruct 0.1.44 Windows 交付记录

2026-11-04，标准 Windows x64 应用。项目位于 `C:/Users/lee/Documents/InkStructApp/InkStruct-Windows-Dev`，Git HEAD 为 `af45b45f04f899fcaced43aa980b0508673ee6c0`。工作基础为包含未提交修改的完整源码。应用版本唯一来源为 `src/inkstruct/fonts/__init__.py` 的 APP_VERSION，现为 0.1.44。Python 库仍为 0.2.0，字体和项目协议版本分别沿用现有版本。

## 本版行为

### 真实供体多候选

生成页的 v6.2 exp 自动尝试为同字保留最多四份几何不同的字形。先完成既有主字形，主字形作者来源完整时，再一次替换一个完整录制部件，保留其余笔迹。使用完整作者供体池和现有候选索引，按确定顺序尝试不同供体字，最多尝试十六次。不保证每个字都有四份，未找到合格替代时保留实际份数。来源有缺口的主字形继续记录原警告，额外候选只接受完整作者来源。

四份上限和十六次尝试上限是本轮为控制组合量、生成时间和字体体积作出的实现选择。现阶段只有完整部件替换产生变化，未加入随机扰动或神经网络修正，也未将隔离 v7 研究接入默认生成。v6.1、v4 生成方式沿用既有行为。

每份替代在实际主字形上下文中重新执行现有映射、语义准入、拆分限制、几何/接触检查，再做协议和逐笔来源完整性校验。原始点列通过记录的整体变换迁移，压力和时间沿用来源，不切改原迹。拒绝原因保存在逐字压缩结果的 `logs.variant_trials`。主字形及其来源保持原值，候选按确定顺序生成，串行和多进程结果一致。

生成协议增加显式可选扩展 `inkstruct-real-donor-candidates-v1`。任务协议记录 limit 和 attempt_limit，逐字行记录 candidate_count，原压缩结果保留旧主字段，并附 candidate_pool.alternatives。额外候选分别保存字形、逐笔来源、来源档案哈希、准入证据和检查结果。工作进程提交及制包导入均验证扩展版本、数量、身份、哈希、来源和几何去重，损坏结果不能进入正式字体。

制作字体将同字的全部合格候选一起纳入现有字体格式。原主候选身份保留，排版继续按源码出现位置稳定选样，保存 `.inkdoc` 冻结实际选择。旧生成任务、旧字体和旧文档继续读取，字体更新采用现有另存发布流程。

### 预览更新核对

用户指定的“报错处理”和“两端对齐”已存在于当前 0.1.43 主项目。开工时逐文件比较独立目录 `C:/Users/lee/Documents/InkStructApp/InkStruct-Layout-Dev`，258 个应用 Python 文件全部字节一致。两份 Qt 测试仅有独立启动器与主项目私有验收入口的适配差异，保留主项目入口和原断言。本版继续包含问题分组、定位、完整报告、显式强制 SVG 和正文两端对齐，并在冻结应用中重新测试。

中文自然书写 v2 已在 0.1.43 合入，默认关闭。本轮未从独立目录引入新的中文抖动增量。已有文档保存的自然书写设置继续读取，避免破坏原效果；开关及兼容代码保留。独立预览目录未写入。

## 实际验证

本机 Windows x64，Python 3.13.16、NumPy 2.5.4、PySide6 6.9.2、Matplotlib 3.11.2、PyInstaller 6.22.3。沿用项目 `.venv`，无新增依赖。

1. **1487 项综合回归通过，0 失败、0 错误、0 跳过**，102 个测试文件，265.07 秒。覆盖新增候选协议及损坏拒绝、生成并行/回退、字体、冻结选样、源码身份、模板、字段、分页、公式、表格、脚注、采集、问题处理和两端对齐等。JUnit 和原始日志保存在本轮验收目录。
2. **真实 scx 完整作者档案的十字验证**。固定目标 `嘤喳响噜啜哮孔正藻构`，分别运行旧单候选、四候选串行、四候选双进程，共三十次逐字生成。十字全部完成，主字形、逐笔来源、缺口和检查结果完全一致，串行与双进程额外候选完全一致，未触发回退。六字各有四份，合计 28 份候选。响、藻的原来源缺口继续保留。单次总耗时分别 8.983、9.643、9.093 秒，仅作为本次功能成本记录，未据此宣称性能收益。
3. **真实新字体与文档**。新建 scx 验收字体含 10 字、28 候选、9201 点。嘤、喳的重复出现均选到了四份样本，144 处实际选择保存重开一致。完整排版快照及两页严格 SVG 字节一致。新字体、文档和 SVG 保存在本轮目录，未替换用户现有字体。
4. **旧字体和文档兼容**。只读使用 user_001 现有字体，215 字、1207 候选、102559 点。旧 0.1.41 文档重开后选样和参数保留，严格 SVG 与历史 0.1.41 字节一致。两端对齐及已有自然书写 v1/v2 四组兼容测试均保存重开一致。缺字仍阻断常规严格导出，显式强制导出的空缺及问题报告保留。原字体和文档哈希不变。
5. **正式 Windows 构建通过**。最终构建在 `artifacts/windows_build_0.1.44_20261104_02`，40.58 秒，构建期间源哈希不变，`layout_preview=false`。两份 EXE 均为 AMD64，FileVersion/ProductVersion 均为 0.1.44，ProductName 为 InkStruct。
6. **双 EXE 实际冻结自检通过**。各自用 scx 完整档案运行四字串行与双进程，四字均保留四候选，共 16 份，结果一致且无回退；完成字体、96 处冻结选样、保存重开和严格 SVG 一致检查。各自再用旧 user_001 字体检查后台多页并发导出、缓存、取消、进程故障后串行回退、问题面板、两端对齐、模板设置保留及严格/强制 SVG，均无 notices。日志分别为 `frozen-tool-candidates-03-logs`、`frozen-app-candidates-03-logs`、`frozen-tool-export-logs`、`frozen-app-export-logs`。这是自动 Qt 处理器验收。
7. **原生窗口观察**。使用 computer-use 技能查看源码 Windows 窗口，1350×900、96 DPI，真实多候选字体两页连续预览、设置入口及两端对齐控件可见，取消设置返回文稿。最终截图及验收文档原哈希保留。可访问性焦点仍报告页码控件，未注入文字，因此中文粘贴、IME 和键盘撤销不能列为本次原生输入通过项。

## 失败、边界与未验证项

首次打包候选自检因验收函数漏导入 AssetResolver 报 NameError；异常退出另产生 QProcess 清理报错。补齐验收导入后，在新目录重新构建并重跑两份 EXE，通过结果如上。失败构建和原始日志保留。一次并行启动验收早于构建文件就绪，产生 WinError 2，未进入应用，保留该次日志并在构建完成后重新执行。

没有重跑全库，也未人工逐份评价全部新增候选的字形质量。来源和原检查通过不等同于每份字形都优于主候选。新候选完整检查只在原来源充足的范围产生，自然变化随作者可用供体而异。实体数位板、驱动、写字机纸面、冻结应用的人工原生输入及全库耗时/包体增长尚未验证。

README、使用说明及 LaTeX 手册源码已同步。未重编译新版手册 PDF，交付包携带对应源码。

## 启动和复现

完整解压 `InkStruct-0.1.44-Windows-x64.zip`，保留 InkStruct 文件夹内全部伴随资源，双击 InkStruct.exe。标准工作区沿用应用设置，验收均使用本轮私有工作区。历史字体及文档由用户正常选择载入。

以下命令从项目根目录执行，所有带 NEW 的输出目录应尚不存在。

```powershell
.venv/Scripts/python.exe -B -X utf8 -m inkstruct.application --workspace workspaces/windows-0.1.44-NEW
.venv/Scripts/python.exe -B -X utf8 scripts/run_layout_regression.py --junitxml=artifacts/regression-0.1.44-NEW.xml --basetemp=artifacts/pytest-0.1.44-NEW
.venv/Scripts/python.exe -B -X utf8 packaging/build_inkstruct_app.py --output artifacts/windows_build_0.1.44-NEW
$env:QT_QPA_PLATFORM='offscreen'
$env:INKSTRUCT_LAYOUT_PREVIEW_HOME=(Join-Path (Get-Location) 'artifacts/check-private-0.1.44-NEW')
artifacts/windows_build_0.1.44_20261104_02/dist/InkStruct/InkStructTool.exe --inkstruct-check --generation-profile artifacts/v7_functional_20261023/development-pilot-01/resources/scx.json --writer scx --candidate-check --output artifacts/check-candidates-0.1.44-NEW
artifacts/windows_build_0.1.44_20261104_02/dist/InkStruct/InkStructTool.exe --inkstruct-check --font artifacts/charsets_0.1.40_20261022/font-validation/user_001-v62-generation-0.1.40-validation.inkfont --samples artifacts/unused-0.1.44-NEW --export-only --output artifacts/check-export-0.1.44-NEW
```

`--export-only` 不读取 samples，该参数满足现有自检命令行入口约定。生成十字对照脚本为 `artifacts/integration_0.1.44_20261104/real_generation_check.py`；复现应复制到 artifacts 下新的同级目录再运行，脚本按所在目录保存结果，拒绝覆盖既有生成目录。

## 产物和保全

- 应用目录为 `artifacts/windows_build_0.1.44_20261104_02/dist/InkStruct`。
- 交付 ZIP、SHA-256 和最终解压验证为 `artifacts/windows_release_0.1.44`。
- 日志、JUnit、真实生成对照、新字体、文档、SVG、截图及保全检查为 `artifacts/integration_0.1.44_20261104`。
- 开工前 258 个应用源码哈希及完整原字节快照为 `source-before.json`、`source-0.1.43-before.zip`。初始 Git 状态 15 项已有修改保留。构建源清单、EXE 版本和独立预览核对结果分别保存。

未执行 reset、clean、提交或推送，历史交付包保留。临时清理仅覆盖本轮 pytest 临时目录和 PyInstaller work/cache；源码、数据、原始日志、构建清单、可运行目录、验收与交付产物保留。
