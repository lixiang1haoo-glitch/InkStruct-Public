# InkStruct 0.1.16 Windows：全局默认与元素属性

日期：2026-10-18（Asia/Shanghai）。项目：`C:\Users\lee\Documents\InkStructApp\InkStruct-Windows-Dev`。Git 基点 `af45b45f04f899fcaced43aa980b0508673ee6c0`，沿用完整的未提交工作树。没有 reset、clean、自动提交或推送。唯一应用版本来源 `src/inkstruct/fonts/__init__.py:APP_VERSION` 为 0.1.16，下次正式交付至少 0.1.17；Python 库仍为 0.2.0，字体及文档协议不变。

## 使用方式与修复

齿轮现在打开“全局默认设置”。点击应用或确定后，本机保存纸张、字体来源、正文、公式、表格、图片、代码块和脚注默认参数，重启后保留，新文档使用。已有项目继续载入自己的参数、冻结字形、评价和独立属性。若需要更新当前文档，明确勾选底部“同时将默认排版参数应用到当前文档”；默认不勾选。未应用的修改可取消。采集显示配置仍保存到原配置存储，不影响原始轨迹。

全局表格、图片页面只编辑默认参数，不出现文档元素选择器。排版右侧新增“元素属性”，点击预览中的元素、将源码光标放入元素，或使用列表选择表格或图片。可切换“沿用文档默认”与“独立设置”，修改先保留草稿，点击“应用元素属性”后生效并随 `.inkdoc` 保存。切换元素保留草稿，也可取消尚未应用的修改。该侧栏可从“视图”菜单重新显示。

右侧“将全局默认排版参数用于本文”是明确的复制操作，保留字体、图片资源以及表格/图片独立属性；有未应用的元素草稿时要求先处理草稿。全局配置不含元素覆盖、图片资源和模板填写绑定，不把某篇文档的对象写入其他文档。模板变化时保留原有按协议处理绑定的规则。

公式设置窗口此前允许缩窄到小于图示与控件的固有宽度。现在按公式页最小内容宽度加导航与边距计算窗口最小宽度，最低 980 个逻辑像素；大字号时自动增加。保留纵向滚动，没有通过隐藏横向滚动条裁切内容。

新增全局配置存储 `layout_defaults_v1`，使用既有 `InkStruct/UnifiedSettings` 的 QSettings 范围。旧版没有此记录时使用初始默认，旧项目不自动迁移。非法配置保留原记录并提示；不同窗口顺序保存发生冲突时拒绝覆盖。采集配置或全局配置保存失败时不提交文档参数，并恢复已写入的采集显示配置。

测试曾暴露 Windows 的 QSettings 构造重载问题：仅传组织名、应用名会固定使用原生配置，忽略测试指定的 INI 格式。已明确传入格式和用户范围，隔离测试配置。误写的本轮新增键已按完整内容校验后单独移除，备份保存在验收目录 `native-test-preference-backup.json`，其他既有偏好未清理。失败日志保留，没有降低参数校验。

## 实际验证

环境：Windows x64，项目 `.venv` Python 3.13.16、PySide6/Qt 6.9.2、PyInstaller 6.22.3、Matplotlib 3.11.2。没有安装训练或 CUDA 依赖，也未修改全局 Python。

- 最终相关回归 **363 passed，0 skipped**，132.85 秒；Ruff 通过。覆盖跨进程默认保存、冲突与损坏配置保护、失败回滚、三个 DPI 下的设置导航，以及默认/独立属性、恢复沿用、保存重开和既有功能。
- 100%、150%、200% DPI，以及额外 13 pt 界面字体下，公式全部 11 类在最小窗口宽度时外层横向滚动范围为 0，视口宽度不小于内容最小宽度。
- Windows 构建输出到新的版本目录；源码冻结哈希、依赖版本见 `artifacts/windows_build_0.1.16_20261018/build-provenance.json`。
- 两个 EXE 均为 x64，文件和产品版本均为 0.1.16，ZIP CRC 校验通过。包内真实 scx 11 字的 v6.1 exp、v4 adaptive 导入、建档、生成、制作字体、排版、保存重开及 SVG 流程通过；来源缺口提示保留。公式轴、冻结项目、独立属性和连续预览进程检查通过。
- 原生最终 EXE 在独立 `workspaces/windows-defaults-0.1.16` 启动，打开验收副本后确认“元素属性”可选表格、切换独立设置并启用控件，取消草稿后恢复沿用。Ctrl+, 打开全局默认，公式页完整显示且无横向滚动，表格页只有全局参数。原生检查未保存演示参数或改写用户默认。截图为验收目录 `native-*.png`。
- 原始 **706 个用户文件哈希未变**，完整 user_001 字体保留；旧长文档的 11 页、4580 个文本实例及 301 条原诊断保留。打开所有设置并无修改应用后，参数、候选、字符身份、评价和脏状态不变，保存重开全部页面 SVG 与 0.1.13 基线一致。

包内流程、原生界面、完整旧文档与数据保留的最终验证结果见验收目录 `final-verification.json` 和发布目录 `verification.json`。实体数位板、驱动、写字机和纸面效果未在本轮验证；缺字、来源缺口与不支持公式仍按原规则提示和限制导出。LaTeX 手册源码已同步，环境没有 XeLaTeX/latexmk，新版 PDF 未重编译，历史 PDF 保留。

## 产物与后续命令

应用目录：`artifacts/windows_build_0.1.16_20261018/dist/InkStruct/`，保留整个目录，包含 `InkStruct.exe`、`InkStructTool.exe` 和 `_internal`。

发布包：`artifacts/windows_release_0.1.16/InkStruct-0.1.16-Windows-x64.zip`。同目录保存 `SHA256SUMS.txt` 和 `verification.json`，历史包不覆盖。

ZIP SHA-256：`f512364cc70ae772467587b7f3f7384d52b99fcd9a2c430ba83db437e0e1d4c3`。

可以继续开发，并可交付本次设置与元素属性更新；实体设备和纸面效果仍需实物验收。

验收日志、命令 JSON、用户文件哈希清单、文档副本、原生截图与清理记录：`artifacts/global_defaults_0.1.16_20261018/`。包内两种生成方法的真实 scx 11 字产物：`artifacts/windows_bundle_check_0.1.16_20261018/`。原用户工作区 `workspaces/windows-0.1.8` 保留。

项目根目录 PowerShell：

```powershell
# 启动新版并使用原工作区及完整字体
& 'artifacts/windows_build_0.1.16_20261018/dist/InkStruct/InkStruct.exe' --workspace workspaces/windows-0.1.8 --font artifacts/user_001_full_font_20261018_math_axis/user_001-v61-full-symbols-20261018.inkfont

# 针对性检查（请选择新的 basetemp）
.venv/Scripts/python.exe -m pytest tests/test_global_defaults.py tests/test_unified_settings_qt.py tests/test_writing_workspace_qt.py -ra --basetemp artifacts/qa16-repeat

# 完整相关回归和日志；验收脚本包含本次实际测试文件列表
.venv/Scripts/python.exe -X utf8 artifacts/global_defaults_0.1.16_20261018/run_logged.py regression_repeat .venv/Scripts/python.exe artifacts/global_defaults_0.1.16_20261018/run_regression.py

# 后续构建必须使用全新输出目录，正式交付先递增 APP_VERSION
.venv/Scripts/python.exe packaging/build_inkstruct_app.py --output artifacts/windows_rebuild_next_new
```

本次构建与包内检查的完整命令分别在验收目录 `build.command.json`、`bundle.command.json`。只清理本轮可重建测试目录、私有临时缓存和 PyInstaller work/cache；源码、数据、日志、验收产物及历史交付保留。
