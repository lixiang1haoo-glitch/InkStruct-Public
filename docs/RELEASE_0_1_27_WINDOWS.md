# InkStruct 0.1.27 Windows：默认字体减号分数线

日期：2026-10-19。可以继续开发并交付本次 Windows 构建；数位板、驱动和写字机纸面效果仍未验证。

## 源码与环境

- 实际项目：`C:/Users/lee/Documents/InkStructApp/InkStruct-Windows-Dev`。
- 接手基线 0.1.26；Git 基点 `af45b45f04f899fcaced43aa980b0508673ee6c0`，完整未提交工作树保留。改动前源码快照、环境和最终 Git 状态在本轮验收目录，不将 Git 基点视为完整源码。
- 应用唯一版本来源 `src/inkstruct/fonts/__init__.py: APP_VERSION = "0.1.27"`；Python 库、字体、模板和项目协议版本不变。
- Windows 11 x64 26300；项目 `.venv` Python 3.13.16 AMD64、PySide6 6.9.2、PyInstaller 6.22.3、Matplotlib 3.11.2。完整依赖与源码摘要在构建目录 `build-provenance.json`。
- 修改前记录 2607 个可读取的既有数据/历史交付文件 SHA-256；3 个历史字体文件原先不可读取，仅核对大小和修改时间，未更改其权限。

## 行为与兼容性

新建文档的 `MathStyle.fraction_source` 默认 `sample`，设置中显示“字体减号 −（横向拉伸，默认）”；恢复分式分类初始值也使用该来源。继续复用已有 `sample-minus-length-v1` 变换：用数学减号 U+2212 的真实中心线覆盖所需分数线宽度，保持纵向笔迹起伏、笔画顺序、来源身份和选样记录，不修改原始字体。

根号、括号仍默认几何构件；用户可显式选择几何分数线。缺失/退化减号仍给出阻断诊断，不使用 ASCII 连字符代替，不静默回退。公式、越框、来源与校准检查保留。

旧 `.inkdoc` 已保存的 `sample` / `geometric` 来源保持原值；缺少来源字段或整个数学设置的旧文档明确按几何来源读取。打开不改原文件，不重新选择已有样本。旧全局默认在首次加载时仅内存升级分数线来源，原记录直到明确应用/保存才写入；同时记录独立的 `fraction_sample_default_v1` 标记。用户在升级后明确保存的几何选择可跨启动保留。未引入新协议或自动改写文档。

旧文档要使用新来源，可在齿轮 → 排版默认设置 → 公式 → 分式设置来源，并明确应用到当前文档；该操作会同时应用其他全局默认，应用前核对参数。未应用前原文档保持原值。

## 实际验证

- 最终相关回归：**1148 passed、2 skipped**。涵盖数学结构、资源检查、缓存/续排、脚注、模板、字符校正、图像、导出、字体、统一设置、采集和生成。
- 两项跳过是当前 Windows 账户缺少符号链接权限：真实图片链接与悬空项目链接检查，未计为通过。
- 首轮完整回归 17 failed、1129 passed、2 skipped：旧测试只提供内置数字、未准备新增默认所需的减号，或断言默认不需要减号。补齐测试采集资源，并对保留几何模式的测试显式指定几何；更新 CLI 资源缺口预期。未降低运行时校验。首轮与修正后的日志分别保留。
- 真实字体 `artifacts/user_001_full_font_20261018_math_axis/user_001-v61-full-symbols-20261018.inkfont`：短/长分式逐一核对其所选减号原样本的纵向坐标；允许不同分式冻结不同样本；保存重开 SVG 字节及选样精确一致。原字体不变。
- 包内 EXE 综合自检：`verification.json` 无异常 notices；真实 scx 11 字、v6.1 exp / v4 adaptive 两条小流程通过，未重跑全库。记录实际字体来源提示；不隐藏警告。
- 原生 Windows 0.1.27 GUI：在本轮新工作区打开真实字体小样，查看设置中新的默认来源并取消，导出 SVG，另存和重开。实际 SVG 与冻结小样逐字节一致。原输入包、源码身份、冻结选样和全局默认原始记录及升级标记不变。
- 历史兼容：0.1.12 长文档 11 页/301 项诊断与历史冻结 SVG 摘要一致；0.1.21/22 模板、0.1.23 英文间距及 0.1.20 样本/字符校正文档输出一致；设置无修改应用及保存重开不改现有文档。
- 本轮 21 个修改的 Python 文件 Ruff 通过；双 EXE x64 文件版本/产品版本均为 0.1.27，构建源码摘要与当前源码一致。

原生验收不包含实体数位板、驱动、中文输入法组合输入重新验收或写字机纸面测试。LaTeX 手册源码已同步；本机无 XeLaTeX/latexmk，未声称重新生成手册 PDF。

## 命令与产物

以下命令在上述项目根目录执行，重新构建与自检应使用新的输出目录：

```powershell
.venv/Scripts/python.exe -m inkstruct.application --workspace workspaces/windows-fraction-default-0.1.27-new
.venv/Scripts/python.exe artifacts/fraction_default_0.1.27_20261019/run_logged.py regression-recheck -- .venv/Scripts/python.exe artifacts/fraction_default_0.1.27_20261019/run_regression_final.py
.venv/Scripts/python.exe packaging/build_inkstruct_app.py --output artifacts/windows_build_0.1.27_new
artifacts/windows_build_0.1.27_new/dist/InkStruct/InkStructTool.exe --inkstruct-check --samples artifacts/source_samples/scx_351bf154/samples/scx --writer scx --font artifacts/user_001_full_font_20261018_math_axis/user_001-v61-full-symbols-20261018.inkfont --output artifacts/windows_bundle_check_0.1.27_new
```

源码入口已核对 `pyproject.toml` 的 `inkstruct-app = "inkstruct.application:main"`。也可直接运行已构建的 `artifacts/windows_build_0.1.27_20261019_release/dist/InkStruct/InkStruct.exe`。

- 可运行应用：`artifacts/windows_build_0.1.27_20261019_release/dist/InkStruct/`，包含两个 EXE 与 `_internal`，需保留整个目录。
- 交付 ZIP：`artifacts/windows_release_0.1.27/InkStruct-0.1.27-Windows-x64.zip`；同目录有使用说明、SHA256SUMS 和核验记录，历史版本未覆盖。
- 验收与日志：`artifacts/fraction_default_0.1.27_20261019/`：baseline、focused、regression、regression-final、lint-verified、windows-build、bundle-self-check、audit、native-verify 等日志及命令记录；`native-*.png` 原生截图、`native-checked.inkdoc`、`native-export-svg/`。
- 包内验收：`artifacts/windows_bundle_check_0.1.27_20261019_release/`，有分数线/公式/模板/两方法流程的文档、SVG、截图和 `verification.json`。
- 原生新工作区：`workspaces/windows-fraction-default-0.1.27`，用户原工作区未用于验收。
- 最终 `delivery-seal.json` 记录文件保留核验、ZIP 与 EXE 核验；`cleanup.json` 记录仅本轮临时/构建缓存的清理。源码、数据、日志和交付产物保留，未 reset、clean、提交或推送。
