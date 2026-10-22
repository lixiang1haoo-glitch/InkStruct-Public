# InkStruct 0.1.11 Windows：字体公式数学轴修复

日期：2026-10-18（Asia/Shanghai）。项目 `C:\Users\lee\Documents\InkStructApp\InkStruct-Windows-Dev`，沿用完整、含未提交修改的工作树，未 reset、clean、提交或推送。
应用版本唯一来源 `src/inkstruct/fonts/__init__.py:APP_VERSION=0.1.11`，下一次正式应用交付至少 0.1.12。Python 库与字体格式版本独立，不机械递增。

## 根因与最小修复

录制的运算符原始 JSON 包含 `guides.math_axis_em`。旧 `make_symbol` 仅保留轨迹和四项通用度量，字体核心与用户版缺少数学轴；公式模块仍直接读取原始 JSON 顶层 guides。因此真实样本直接排公式可导出，制作成字体后同一字形报 `math-axis-missing`。

- `fonts/importer.py` 将实际存在的数学轴原值保存在来源摘要可选字段 `capture_guides.math_axis_em`，不填默认值。
- 字段纳入既有 `source_summary_hash`、字体核心哈希、用户版转换和冻结字形身份；不依赖仅开发者版保存的原始数据。
- `fonts/core.py` 校验字段只属于录制来源、结构正确、数值有限且为 0–2 的非布尔数字。非法轴值拒绝发布或装载。
- `ResolvedGlyph.math_axis_em` 统一读取原始样本与字体核心摘要；公式模块使用该接口。缺失信息继续报错阻止导出，布尔值、非有限值、越界等不再被当成有效数学轴。
- 字形点列、压力、时间、通用度量、生成核心及数学排版构造规则不改。来源缺口与 `math-calibration-unreviewed` 提示保留。

字体格式仍为 1.0，样本/任务 schema 不变；这是受保护来源摘要的可选元数据。旧包可以读取，但缺失轴信息的旧运算符仍会阻止公式导出。应从完整原始样本重新制作新字体，或选用本次数学轴修复版；无需重新采集。旧字体和已冻结项目不自动改写，应明确切换资源后另存项目。

## 验证

- 相关 Windows 回归 **148 passed，0 skipped**，退出码 0。包括非默认轴值的真实基线偏移、开发者转用户版核心一致、保存重开、源字体删除后的冻结恢复、公式 SVG、缺失轴严格阻断、非法值拒绝与哈希篡改拒绝，以及原有采集、重录、复用、字体、生成与排版检查。
- 初轮针对性测试有两项断言仅因 NaN/Infinity 被更早的严格 JSON 解码器拒绝而失败；保留失败日志，修正测试预期后 **33 passed**。没有放宽生产 JSON 检查。
- Ruff 检查通过；最终日志与命令 `artifacts/windows_ui_0.1.11_20261018/{regression_final,targeted_verified,lint}.log` 及 `.command.json`。
- PyInstaller 构建成功；`InkStruct.exe` 与 `InkStructTool.exe` 都是 x64，FileVersion/ProductVersion 为 0.1.11；构建期间源码未变化，发布前全部来源哈希匹配。
- 包内真实 scx 11 字小集合的 v6.1 exp、v4 adaptive 两条流程通过：导入、建档、生成、字体发布、排版保存重开、SVG。来源缺口提示保留，没有重跑全库生成。
- 包内新增“采集运算符 → 制作用户字体 → 含加号/等号公式 → 冻结重开 → SVG”检查，避免原先仅数字上下标的盲区。验证报告三项均为 true：`published_operator_font_math_axis`、`operator_frozen_document_exact`、`operator_formula_svg`。
- 应用 ZIP CRC 校验通过；SHA-256 `f932ec56ddb3eebaf28a1f9c3c693cf61bf64da7a2d9ea3722e0bd251325bd49`。

## user_001 新字体与数据保留

从原 v6.1 exp 完整生成结果及真实符号样本制作新包，不重新运行汉字生成。旧字体仍保留在 `artifacts/user_001_full_font_20261015/`。
新字体目录：`artifacts/user_001_full_font_20261018_math_axis/`，文件 `user_001-v61-full-symbols-20261018.inkfont`。
核心来源摘要包含实际采集的数学轴，完整验证和数据来源见同目录 `verification.json`、`input-snapshot.json`。

新旧字形几何、压力、时间、轨迹和度量哈希对比，以及加法等式、希腊公式、关系、乘法、求和、分式、根式、普通混排八例的保存重开和 SVG 结果，见新字体目录的 `math-axis-verification.json`。缺字清单和来源提示在使用说明及 `source-warnings.json` 保留。
实际结果：新旧 10730 份候选全部上述哈希一致，1156 份录制或共享候选带有来自样本的数学轴；八例全部通过。新字体仍为 9771 字符，3350 份来源提示保留。
0.1.11 原生窗口已打开新字体冻结的希腊公式项目 `greek.inkdoc`，预览完成后实际点击导出 SVG 成功；产物在新字体目录 `native-greek-svg/`，包括 `page-001.svg` 和 `plotter.json`。原生验收记录 `artifacts/windows_ui_0.1.11_20261018/native-formula-export.txt`。应用打开的是本次验收项目，不影响用户旧项目。
原 `user_001` 任务总量 900，已完成 691，cursor 530；任务与样本逐文件哈希核对，不迁移或覆盖旧数据。旧档案、生成结果、字体和评价均保留。

原生字体库已完成新包校验并选中数学轴修复版，显示 9771 字、10730 份候选、3350 份来源提示、英文正体 52/52、斜体 42/52；截图为 `artifacts/windows_ui_0.1.11_20261018/native-library-selected.png`。UIA 文本缓存仍含旧列表，同名 `.txt` 已备注这一辅助工具限制，界面结果以实际截图为准。最终复核 249 个构建来源文件全部匹配，采集与归档输入哈希未变，应用 ZIP 与字体 SHA-256 匹配；原生 SVG 含 7 条仅使用 M/L 指令的路径。详见同目录 `final-verification.json`。

## 产物与命令

- 应用：`artifacts/windows_build_0.1.11_20261018/dist/InkStruct/InkStruct.exe`（保留整个 InkStruct 目录）。
- 应用 ZIP：`artifacts/windows_release_0.1.11/InkStruct-0.1.11-Windows-x64.zip`，同目录有使用说明、验证报告与 SHA256SUMS。
- 新字体、公式项目和 SVG：`artifacts/user_001_full_font_20261018_math_axis/`。
- 构建证据：`artifacts/windows_build_0.1.11_20261018/build-provenance.json`。
- 测试、构建与字体制作日志：`artifacts/windows_ui_0.1.11_20261018/`。

项目根目录 PowerShell：

```powershell
& 'artifacts/windows_build_0.1.11_20261018/dist/InkStruct/InkStruct.exe' --workspace workspaces/windows-0.1.8
.venv/Scripts/python.exe -m pytest tests/test_font_math_axis.py tests/test_math_layout.py tests/test_font_packages.py -ra
.venv/Scripts/python.exe artifacts/windows_ui_0.1.11_20261018/run_logged.py regression_final .venv/Scripts/python.exe artifacts/windows_ui_0.1.11_20261018/run_regression.py
# 后续重建选择全新目录；正式新版须先递增 APP_VERSION。
.venv/Scripts/python.exe packaging/build_inkstruct_app.py --output artifacts/windows_rebuild_0.1.11_new
```

可继续开发并交付本次软件修复。实体数位板、驱动、数学轴人工校准和写字机纸面效果仍未验收。README、使用说明、LaTeX 手册源码已同步；未安装 XeLaTeX/latexmk，新手册 PDF 未重编译，历史 PDF 保留。
本轮只清理私有测试、绘图、临时缓存和 PyInstaller work，保留源码、原数据、日志、截图、验收项目、字体和交付包；清理清单见 `cleanup.json`。
