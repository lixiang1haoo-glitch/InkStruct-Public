# InkStruct 0.1.40 Windows：完整命名字表与可追溯目标选择

本版为生成页增加“内置简繁字表…”。用户可自由合并完整命名字表，查看来源、版本、完整字符及结构库缺口；只有明确确认后才使用支持部分。完整供体池、同字排除、语义/映射门槛、几何、碰撞、来源审计、确定性选择和串行回退均沿用 0.1.39。未改采集、字体、模板或文档协议，不改写用户正文和冻结选样。

## 字表与范围

| 集合身份 | 明确版本及范围 | 全表汉字 | 本版结构库支持 | 不支持 |
|---|---|---:|---:|---:|
| cn-tgh-2013 | 大陆《通用规范汉字表》2013 年版 | 8105 | 6866 | 1239 |
| traditional-gb12345-1990 | GB/T 12345-1990 中的全部汉字 | 6866 | 6440 | 426 |
| tw-common-1982 | 台湾《常用國字標準字體表》1982 年版 | 4808 | 4695 | 113 |
| traditional-tgh-unihan17 | 8105 字按 Unihan 17.0.0 全部繁体对应展开，明确标注派生 | 8593 | 6919 | 1674 |

“完整”指以上有定义的有限字表，不声称覆盖一切繁体、次常用或历史异体。没有内置香港规范完整字表。GB/T 12345 是编码标准中的汉字集合，不被表述为覆盖所有地区的常用繁体规范。派生集不是地区规范，也不是基于上下文的简繁转换。

大陆字表从固定 Unicode 17.0.0 的 `kTGH` 提取，检查 2013:1–8105 连续无缺号，保留原序。繁体国标从同版本 `kGB1` 的完整映射提取，保留区位号和顺序。参见[大陆教育部字表说明](https://www.moe.gov.cn/jyb_xwfb/xw_fbh/moe_2069/s7135/s7562/s7569/201308/t20130827_156353.html)、[GB/T 12345 官方标准记录](https://openstd.samr.gov.cn/bzgk/std/newGbInfo?hcno=90394D2B4115D9291C825A7651AEFE4B)和[固定版 Unihan 17.0.0 数据说明（UAX38 rev39）](https://www.unicode.org/reports/tr38/tr38-39.html)。没有误用字典检字属性 `kTGHZ2013`。

台湾数据使用[教育部原始 ODS 附件](https://language.moe.gov.tw/uploads/files/17694982751710.ods)，其[官方说明页](https://language.moe.gov.tw/material/info?m=9fe3ff5a-5a8c-4817-9e60-6337dd55a509)明确全表 4808 字，检查 A00001–A04808 连续无缺号。原始表 A02149 字符栏为“汨”U+6C68，Unicode 栏误写 6C69（汩）；按[同部字典 2024 正式七版 A02149](https://dict.variants.moe.edu.tw/dictView.jsp?ID=23423)核实后采用明确字符栏，完整记录冲突及依据，不默默归一化。该字典网页经 web 工具读取核实，curl 下载返回 404；保存核对事实回执，没有伪造网页原文哈希。

固定上游下载身份：

- Unihan-17.0.0.zip：`f7a48b2b545acfaa77b2d607ae28747404ce02baefee16396c5d2d7a8ef34b5e`。
- 台湾 ODS：`e97e29ed2aa222bbfc12c18a6d96f0270440b1d73f64366d9ad22d7fe9012408`。
- 运行时目录 SHA-256：`ea9da019cedf283f40d94a6d4759fafa2459f8b41d770ef111b9efd9988dea8a`。

原始下载、TLS/下载失败记录、字典核对回执在 `artifacts/charsets_0.1.40_20261022/sources/`。运行时事实数据、逐字序号、来源、勘误、Unicode License V3 和 NOTICE 位于 `configs/character_sets/`，打包随应用提供。只分发字符与序号事实，不分发教育部字体、字典释义或扫描图。离线重建所得全部文件与运行时数据逐字节一致，记录见 `catalog-reproduction.json`；不依赖网络或训练环境。

## 身份、关系与缺口

集合成员与对应关系分离。保存 Unihan 17.0.0 全部 `kSimplifiedVariant`（6929 条）、`kTraditionalVariant`（6475 条）、`kZVariant`（149 条），保留方向、自身对应、全部一对多目标与原始 token。它们反映 Unicode 的实际用法关系，不被冒称为政府规范简繁对照表。

“发”同时保留發/髮，“说”同时保留說/説，“为”同时保留為/爲，“台/后”保留自身对应；苧的简体和繁体关系也不被错误当成互斥分类。合并按目录顺序去重，共用字在每份所属表内仍保留。查询展示单字的全部关系及各表成员，不根据名称猜地域、不改 Markdown、不全局字符替换。同一 Unicode 的地区笔形差异仍需合适结构数据，本轮不重绘或替换结构库。

窗口显示完整缺口和 U+ 编码，可复制报告。默认不能使用有缺口的字表，确认框不预选；改变任一字表选择会撤销旧确认。确认后只把支持部分列为实际输出目标，同时在 `target-manifest.json` 与生成协议中保存：完整原表成员、所选表声明、实际目标、未支持字符、目录及结构库成员哈希、显式排除方式和诊断。开始任务前再次从已校验目录重算验证；结构库或清单身份改变必须重选，不接受篡改缺口记录。文本被手动编辑后明确转成自定义字表，原规范身份不再沿用。自定义字表原有严格缺字阻断不变。

运行时同时校验目录固定 SHA 和所有数据/许可成员的完整哈希，损坏会阻断操作。低层生成入口也验证确认清单与实际目标一致，先验证再创建输出目录。只改变输出目标；作者完整来源档案不被字集筛选。

## 本轮 Windows 验证

项目路径 `C:\Users\lee\Documents\InkStructApp\InkStruct-Windows-Dev`，HEAD `af45b45f04f899fcaced43aa980b0508673ee6c0`，其上保留完整未提交快照。Python 3.13.16 x64、NumPy 2.5.4、PySide6 6.9.2、Matplotlib 3.11.2、PyInstaller 6.22.3、pytest 9.1.1，Windows 11 build 26300；继续使用项目 `.venv`，无新增依赖。

相关回归 **136 项通过**，24.36 秒。覆盖完整成员/序号/哈希、源表冲突、共用字/一简多繁/自身及地区编码关系、不归一化、集合稳定合并、空集、显式排除/篡改/结构库变化、取消、控件状态，及既有生成、多进程崩溃与回退、v6.2、采集任务、字体、文档、模板、源码身份、符号、SVG 并行/后台导出与资源管理。无跳过项；XML 和真实命令见 `pytest-regression.xml`、`regression-command.json`。

用现有 user_001 真实档案 SHA `31b9d65be17b5517bc9cc544bad8bd83af190bf01420b49ea7526c825608cf81` 做有限验证，没有重跑全库：

- 完整 8105 字选择，明确保留 1239 缺口并取 6866 个支持目标；2 进程生成指定前 12 字后取消，保留实际完成与 pending。与单独串行生成这 12 字相比，供体/候选、接受决定、几何、笔画、压力、时间及来源诊断 payload 完全一致。
- 孔、正、址、兄、礼、烧、止、怔、歪、羊、群，串行与 2/4 进程全部完成，payload 相同，无隐式串行回退。
- 共用/简繁/地区回归请求 17 字，15 字受支持，串行和 2 进程全部完成且 payload 相同。説、爲不受结构库支持，保留缺口，未替换为說、為。来源警告完整保存在 `regional-verification.json` 和逐字结果。
- 源码实际 Qt 控件与最终双 EXE 均验证内置目录完整性、缺口确认、有限取消、子集一致性、真实 spawn、当前文档提取和源码身份不变。Qt 自动检查使用 offscreen，不冒称人工原生输入。
- 用真实完整字体的 10770 个候选做完整校验，从新 11 字结果和原字体 1196 个录制/合成候选另制验证小包；旧候选身份、度量、来源相同。三页/272 选样文档保存重开后快照和冻结选样一致，严格 SVG 前后字节相同；旧字体 SHA 未变。不是全库替换包或新的独立书写质量评价。

原生窗口使用 computer-use 技能实际启动到独立工作区 `workspaces/windows-charsets-0.1.40`，确认 0.1.40、生成页新入口，打开弹窗，选择 GB/T 12345，实际显示 6866/6440/426 且未确认时“使用所选字表”禁用；Escape 取消后仍为原目标“中国书法”。可访问性点击复选框曾返回缓存元素不可用，刷新截图后坐标输入成功；模态窗口未单独列出。**未声称完成原生缺口确认或全库生成**；确认处理器另有源码及双 EXE 自动检查。可访问树与限制在 `native-accessibility.json`。数位板、驱动、写字机、全部规范字的地区笔形/生成质量及全库耗时未作本轮验收。

首轮冻结验收失败不是生成错误：测试以“任意 12 字完成”提前取消，却假定“指定前 12 字都已完成”，较慢的“儿”仍在 pending。修正验收脚本为检查指定 12 字提交标记，保留首轮候选目录、错误日志和失败回执，改用新的 `_verified` 输出目录构建。异常退出附带 Qt QProcess 清理警告保留；正常路径没有以此放宽生成检查。

## 交付与复现

APP_VERSION 为唯一版本源，正式交付版本 0.1.40；README、使用说明、集成说明、LaTeX 手册源码和发布文件名同步，Python 库仍 0.2.0。手册未重编 PDF，本机无 XeLaTeX/latexmk，不将旧 PDF 当新版。

准确命令（在项目根目录；所有输出必须换成尚不存在的新目录）：

```powershell
.venv/Scripts/python.exe -B -X utf8 -m inkstruct.application --workspace workspaces/windows-charsets-0.1.40-NEW
.venv/Scripts/python.exe -B -X utf8 scripts/vendor_character_sets.py --sources artifacts/charsets_0.1.40_20261022/sources --output artifacts/reproduced-charsets-NEW
.venv/Scripts/python.exe -B -X utf8 -m pytest tests/test_character_sets.py tests/test_character_sets_qt.py tests/test_generation_targets.py tests/test_generation_resources.py tests/test_generation_parallel.py tests/test_generation_targets_qt.py tests/test_generation_workflow.py tests/test_v62_semantics.py tests/test_font_revisions.py tests/test_parallel_font_verify.py tests/test_integrated_window_qt.py tests/test_capture_management.py tests/test_document_package.py tests/test_flow_templates.py tests/test_source_identity.py tests/test_symbol_revisions.py tests/test_parallel_export.py tests/test_background_export_qt.py tests/test_resource_management_qt.py -p no:cacheprovider --basetemp artifacts/pytest-0.1.40-NEW
.venv/Scripts/python.exe -B -X utf8 packaging/build_inkstruct_app.py --output artifacts/windows_build_0.1.40-NEW
artifacts/windows_build_0.1.40_20261022_verified/dist/InkStruct/InkStructTool.exe --inkstruct-check --output artifacts/check-0.1.40-NEW --generation-profile artifacts/v61_collection_acceptance_20261013/run_v3_with_validation/source_archive.json
```

复现真实回归脚本在 `artifacts/charsets_0.1.40_20261022/`。脚本有明确的新输出目录保护，重跑需先复制到新目录并按记录修改输出；不要覆盖本轮产物。

- 发布包：`artifacts/windows_release_0.1.40/InkStruct-0.1.40-Windows-x64.zip`，完整解压并保留 `_internal`。
- 最终应用：`artifacts/windows_build_0.1.40_20261022_verified/dist/InkStruct/InkStruct.exe`；同目录 `InkStructTool.exe`。
- 构建、源身份及打包记录在上述构建目录；最终运行验收在 `frozen-InkStruct-final/`、`frozen-InkStructTool-final/`。
- 来源下载、生成结果、覆盖清单、完整报告、测试/失败日志、文档和 SVG 位于 `artifacts/charsets_0.1.40_20261022/`。
- 新验证小字体：该目录 `font-validation/user_001-v62-generation-0.1.40-validation.inkfont`；不自动导入或改写旧字体。

23693 项既有用户文件元数据与开始前相同；其中 23689 项同时与已有内容哈希一致，其余 4 项只有历史元数据基线，明确不宣称内容哈希验证。HEAD 不变，无 reset/clean/提交/推送；历史发布包与初轮失败构建保留。仅清理本轮可重建缓存，原始来源、测量、日志、生成结果及验收/发布产物保留。当前可继续开发，命名字表功能可交付；结构库覆盖缺口和地区笔形适配仍明确受限。
