# InkStruct 0.1.24 Windows 交付记录

日期：2026-10-19。项目：`C:\Users\lee\Documents\InkStructApp\InkStruct-Windows-Dev`。Git 基底 `af45b45f04f899fcaced43aa980b0508673ee6c0`，完整未提交工作树。已检查 AGENTS.md、Git 状态、图片与公式源码、相关说明及上一版交付；开始前保存源码 ZIP 和既有数据摘要。没有 Git reset、clean、自动提交、推送或覆盖历史交付。

应用唯一版本来源 `src/inkstruct/fonts/__init__.py::APP_VERSION` 从 0.1.23 递增为 **0.1.24**。README、使用说明、图片与数学文档、LaTeX 手册源码及发布文件名同步。Python 库版本和字体协议独立。使用本项目 `.venv`，Windows 11 x64（26300）、Python 3.13.16 AMD64、PySide6/Qt 6.9.2、PyInstaller 6.22.3、NumPy 2.5.4、Matplotlib 3.11.2；未修改全局 Python 或其他项目环境。

## 图片默认尺寸

图片默认改为高度 **60 mm**，宽度按原图长宽比计算。默认页移除宽度、最大高度及尺寸依据选择，只显示高度、图题间距、对齐和 SVG 容差。默认图题间距仍为 2 mm，默认居中。无图时也能设置默认；恢复初始默认同样回到 60 mm。

单张图片仍在排版右侧独立设置，可选“按高度，宽度按比例”或“按宽度，高度按比例”。按宽度时保留旧版最大高度限制。PNG/JPEG 和受控单线 SVG 共用物理尺寸规则。120×60 的横图默认排为 120×60 mm；60×120 的竖图排为 30×60 mm。过宽、过高仍明确诊断，不自动缩小、裁切或放宽导出。

新样式为 `inkstruct_image_style_v2`，增加 `height_mm`；按高度时忽略旧宽度及宽度模式的最大高度字段。旧 `inkstruct_image_style_v1` 继续按保存的宽度和最大高度计算，写回 v1 不塞入新字段。旧文档及单张独立设置保留原几何；只查看或取消是无改动操作。旧文档默认可明确使用“将本文旧版图片默认改为按高度 60 mm”转换，或者通过齿轮明确将全局默认应用到本文。

原全局默认若保存为旧宽度样式，加载时仅在内存中采用高度 60 mm，保留对齐、图题间距等其他参数；原配置记录在明确保存前不改写。已保存的新高度值保持原值，不强制每次重置为 60 mm。此更新不覆盖旧文档、图片原文件或元素独立设置。

## 公式中的汉字

原解析器的直接字符白名单不包含汉字，导致 `$U_{模块}$` 等写法失败，尽管 `\text{模块}` 原本可用。现直接接受现有汉字资源判定支持的 CJK 汉字及扩展区字符，仍建立普通数学 Symbol 节点并保留源码范围。支持直接汉字、单字或成组上下标、分式、根式、矩阵及其他既有结构，例如：

```markdown
$U_{模块}$ 与 $U_{万}$

$$
U_{万}=1.00297U_{模块}-0.38650
$$

$\frac{输入}{输出}$
```

不要求改写原 Markdown 或额外包裹 `\text{}`，后者继续支持。汉字使用当前加载字体的真实轨迹，字体缺失仍报错并定位；不使用屏幕字体填补，不替换字符。未知命令、未闭合分组、重复上下标、不支持的直接符号、深度及节点预算保持原检查。非 BMP 汉字保留 Unicode 标量源码范围。已有 AST、数学版本和字体协议不改，既有合法公式的排版不重设；旧文档中此前因直接汉字而无效的公式会按新支持正常解析，这是本次预期修复。

## 测试和 Windows 验收

最终相关回归覆盖 93 个模块：**1058 passed、2 skipped，316.59 秒**。跳过仍为本账户没有 Windows 符号链接权限的真实图片链接和悬空项目链接测试。17 个修改或新增 Python 文件 Ruff 通过。新增检查包括横图／竖图比例、过宽诊断、旧 v1 样式不改、新 v2 保存重开、默认宽度控件隐藏、默认恢复、独立宽高依据、继承和取消、100%/150%/200% DPI，以及汉字各类数学结构、非 BMP 源码位置、缺字阻断、冻结选样和 SVG。

旧测试中关于“默认图宽”的断言已改为本次明确要求的默认高度；单张图宽测试明确选择按宽度模式。原“直接汉字非法”的语法用例改为仍不支持的直接表情符号；新增汉字正向、缺字及错误协议用例。未删除其他检查或降低协议。初期新增验收用例存在图片父节点与实际图片节点混用，以及把所有数学警告误判为错误的问题，均修正后复测；图片坐标比较使用 1e-8 mm 浮点公差。失败日志保留。

真实 user_001 字体验证汉字下标、分式、保存重开与机器 SVG；新增公式使用的来源提醒被显式记录并确认，数学校准未审核警告继续保留。图片参考页实测为 120×60 mm，含位图时依旧不能作为写字机 SVG 导出。最终 EXE 自检还通过既有字体完整校验、英文字距与邻字校正、模板七页循环及 v6.1 exp / v4 adaptive 两种 scx 真实 11 字流程，没有重跑全库。源字体 9771 字、10730 候选、8,375,082 点和 3350 份来源提醒均保留。

原生验收在新工作区打开真实字体的汉字公式和参考图，显示 `U_{模块}`、`U_{万}` 和“输入／输出”分式，无解析错误占位。齿轮图片默认页显示高度 60 mm，宽度输入已移除；查看并取消未改写用户全局默认参数记录。原生另存重开保持源码、稳定身份、冻结选样和图片资源。截图、项目、参考页与独立公式 SVG 位于本轮验收目录。

旧 0.1.21、0.1.22 模板项目仍为七页，0.1.23 校正项目仍为一页，冻结选样与逐页机器 SVG 字节一致。旧 0.1.20 同样本／同字符校正文档保持一致。旧长文档仍为 11 页、301 条诊断，全部页面 SVG、设置无改动应用及保存重开与原 Windows 基线一致。

**2260 个可读既有文件哈希一致**，涵盖保护清单中的任务、样本、作者、字体、生成、评价、工作区及历史验收和交付。原完整字体 SHA-256 仍为 `b114b9db538610176eaf4ca7ca6f5f177fd0319817599433dec274c50061c9c3`。另有三个历史工作区字体在开始即权限不可读，仅核对其大小及修改时间不变，不宣称核验内容，也未修改权限。

未验证：实体数位板、驱动、写字机和纸面效果；本轮没有重新验证中文输入法组合输入。数学作者校准提示继续保留。环境未安装 XeLaTeX/latexmk，手册源码已更新但新版 PDF 未重编译。以上软件结果来自当前 Windows 环境。

## 应用、日志与命令

正式交付包：`artifacts/windows_release_0.1.24/InkStruct-0.1.24-Windows-x64.zip`。可运行目录：`artifacts/windows_build_0.1.24_20261019_release/dist/InkStruct/`，须保留整个目录及 `_internal`。双 EXE 的 x64 架构、FileVersion/ProductVersion、源码摘要、ZIP CRC、大小与 SHA-256 见发布目录的 `verification.json`、`SHA256SUMS.txt`。

日志和验收：`artifacts/image_math_0.1.24_20261019/`，包括 `regression.log`、`lint_final.log`、`feature-probe-final/`、`compatibility.json`、`legacy-corrections.json`、`final-verification.json`、`native-verification.json` 和 `delivery-seal.json`。最终包内自检：`artifacts/windows_bundle_check_0.1.24_20261019_release/`。构建记录在构建目录。所有输出使用新目录；历史交付包不覆盖。

```powershell
# 源码启动；继续使用自己的既有工作区
.venv/Scripts/python.exe -m inkstruct.application --workspace workspaces/windows-0.1.8

# 启动本次 EXE；本轮验收工作区与用户原工作区分开
& 'artifacts/windows_build_0.1.24_20261019_release/dist/InkStruct/InkStruct.exe' --workspace workspaces/windows-image-math-0.1.24

# 相关专项；basetemp 使用不存在的新目录
.venv/Scripts/python.exe -m pytest tests/test_image_height.py tests/test_image_height_qt.py tests/test_math_han.py tests/test_math_parser.py tests/test_image_settings_qt.py -ra --basetemp artifacts/qa24-repeat-new

# 完整回归清单；重跑前修改脚本中的 basetemp 为新目录
.venv/Scripts/python.exe artifacts/image_math_0.1.24_20261019/run_regression.py

# 最终 EXE 自检；output 使用不存在的新目录
& 'artifacts/windows_build_0.1.24_20261019_release/dist/InkStruct/InkStructTool.exe' --inkstruct-check --samples artifacts/source_samples/scx_351bf154/samples/scx --writer scx --font artifacts/user_001_full_font_20261018_math_axis/user_001-v61-full-symbols-20261018.inkfont --output artifacts/windows_bundle_check_repeat_new

# 下次正式交付先将 APP_VERSION 至少递增为 0.1.25，再使用新构建目录
.venv/Scripts/python.exe packaging/build_inkstruct_app.py --output artifacts/windows_build_next_new
```

完成后仅清理本轮可重建测试目录、私有 TEMP/缓存、构建 work/cache 和新测试模块字节码，清单见 `cleanup.json`；保留源码、用户数据、日志、验收、可运行目录和交付包。可以继续开发并交付本次软件更新，最终封存结果见 `delivery-seal.json`。
