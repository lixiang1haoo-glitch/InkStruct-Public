# InkStruct 0.1.15 Windows：固定浅色界面

日期：2026-10-18（Asia/Shanghai）。项目：`C:\Users\lee\Documents\InkStructApp\InkStruct-Windows-Dev`。继续沿用含既有未提交修改的完整工作树，Git 基点 `af45b45f04f899fcaced43aa980b0508673ee6c0`；没有 reset、clean、自动提交或推送。应用版本唯一来源 `src/inkstruct/fonts/__init__.py:APP_VERSION` 为 0.1.15，下次正式交付至少 0.1.16。Python 库仍为 0.2.0，字体、文档协议和数据格式不变。

## 原因与修复

集成应用此前仅指定 Fusion 控件样式，没有指定颜色方案和完整调色板。Fusion 不等于浅色主题：本机 Windows 深色环境下，Qt 仍继承深色背景、菜单和输入框，而公式示意图等区域使用固定浅色背景，形成混色和对比度问题。旧独立排版入口也只替换少数颜色角色，不能保证按钮、禁用状态等一致。

本次集中增加 `src/inkstruct/theme.py`：

- 明确请求 Qt 浅色颜色方案，固定使用 Fusion，并为激活、非激活、禁用三组提供完整浅色调色板。
- 统一窗口、正文输入、列表、菜单、按钮、提示、选中项、占位文字、边框及禁用控件颜色。
- 集成窗口在创建子模块之前初始化主题；独立排版入口复用相同逻辑。设置弹窗和后续创建的控件继承应用调色板。
- 不提供深色切换，不跟随系统深色模式；深色兼容留待后续版本。没有修改 Windows 系统主题、注册表或其他应用的外观。

只调整屏幕显示。统一齿轮设置、连续页面预览、采集流程、字体和排版参数均保留；SVG 页面和笔迹不按界面配色重写。

## 实际验收

环境：Windows x64，项目 `.venv` Python 3.13.16、PySide6/Qt 6.9.2、PyInstaller 6.22.3、Matplotlib 3.11.2。运行时检查确认本机初始 Qt 颜色方案为 Dark，明确请求后为 Light；未修改系统主题。构建的依赖和源码哈希见 `artifacts/windows_build_0.1.15_20261018/build-provenance.json`。

- 新增 3 项 Qt 子进程测试，覆盖 100%、150%、200% DPI。先注入深色调色板，再启动集成应用，检查四模块、九类设置、数值框、菜单、消息框、Qt 文件选择框以及禁用状态的有效颜色；原有文档参数和采集显示配置不变。重复主题初始化保持稳定。
- 最终相关回归 **353 passed，0 skipped**，126.61 秒，包括原有统一设置事务、采集、字体、公式、保存恢复、连续预览和 SVG 检查。Ruff 通过。
- Windows 两个 EXE 构建成功，PE 架构 x64，产品版本与文件版本均为 0.1.15；构建前后与发布时源码哈希一致。
- 包内检查确认固定浅色方案。真实 scx 11 字小集合的 v6.1 exp、v4 adaptive 两条导入、建档、生成、制作字体、排版、保存重开与 SVG 流程通过；来源缺口提示保留。数学轴、公式冻结、统一设置无修改应用及连续预览绘图进程检查通过。
- 原生最终 EXE 在独立 `workspaces/windows-light-0.1.15` 中启动，实际确认主窗口、标题栏、设置导航、公式与采集设置均为浅色。截图为验收目录内 `native-main.png`、`native-math.png`、`native-capture-settings.png`。没有改写用户原工作区。
- 原始记录的 **706 个用户文件哈希未变**。原 11 页长文档在浅色环境下打开全部设置并无修改应用，参数、选样、字符身份和评价不变；保存重开后全部页面 SVG 与此前基线一致，301 条原有诊断保留。记录见 `final-verification.json` 和 `settings-noop-full.inkdoc`。

实体数位板、驱动、写字机和纸面效果未在本轮验证。既有缺字与公式语法限制仍按原规则处理。README、使用说明、LaTeX 手册源码已同步；环境无 XeLaTeX/latexmk，新版手册 PDF 未重编译，历史文件保留。

可以继续开发并交付本次外观修复，无需重新采集或制作字体。原 Windows 工作区仍为 `workspaces/windows-0.1.8`。

## 应用、日志与命令

可运行目录：`artifacts/windows_build_0.1.15_20261018/dist/InkStruct/`。保留 `InkStruct.exe`、`InkStructTool.exe` 和 `_internal` 整个目录。

发布包：`artifacts/windows_release_0.1.15/InkStruct-0.1.15-Windows-x64.zip`。SHA-256 与 ZIP CRC、文件清单在同目录 `SHA256SUMS.txt` 和 `verification.json`；最终验收摘要在其中 `light_theme_acceptance` 字段。

ZIP SHA-256：`9573be67a921a3928a612c08e7e87ceaa884e15713ced1c1927c0669bd96740a`。

日志、准确命令、数据保留清单、文档验收副本及原生截图位于 `artifacts/light_theme_0.1.15_20261018/`，包内两方法流程产物位于 `artifacts/windows_bundle_check_0.1.15_20261018/`。历史应用包保留。

项目根目录 PowerShell：

```powershell
# 使用既有工作区与完整字体启动新版
& 'artifacts/windows_build_0.1.15_20261018/dist/InkStruct/InkStruct.exe' --workspace workspaces/windows-0.1.8 --font artifacts/user_001_full_font_20261018_math_axis/user_001-v61-full-symbols-20261018.inkfont

# 浅色主题针对性测试
.venv/Scripts/python.exe -m pytest tests/test_light_theme_qt.py -ra --basetemp artifacts/qa15-repeat

# 相关回归，私有临时目录与完整日志
.venv/Scripts/python.exe -X utf8 artifacts/light_theme_0.1.15_20261018/run_logged.py regression_repeat .venv/Scripts/python.exe artifacts/light_theme_0.1.15_20261018/run_regression.py

# 后续构建选全新目录；正式交付新构建先递增 APP_VERSION
.venv/Scripts/python.exe packaging/build_inkstruct_app.py --output artifacts/windows_rebuild_next_new
```

本次实际构建命令为 `packaging/build_inkstruct_app.py --output artifacts/windows_build_0.1.15_20261018`；包内检查的完整命令记录于验收目录 `bundle.command.json`。

仅清理本轮可重建测试目录、私有临时缓存、PyInstaller work/cache；源码、任务、样本、字体、评价、文档、日志、验收和交付产物保留。清理结果记录于验收目录 `cleanup.json`。
