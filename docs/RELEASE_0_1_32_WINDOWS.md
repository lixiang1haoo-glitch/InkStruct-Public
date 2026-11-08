# InkStruct 0.1.32 Windows 与 v6.2 exp

2026-10-20。项目路径 `C:\Users\lee\Documents\InkStructApp\InkStruct-Windows-Dev`，Git 基点 `af45b45f04f899fcaced43aa980b0508673ee6c0` 加完整未提交源码快照。环境：Windows 11 x64 10.0.26300、项目 `.venv` Python 3.13.16 AMD64。应用唯一版本来源 `src/inkstruct/fonts/__init__.py::APP_VERSION` 为 0.1.32。README、使用说明、LaTeX 手册源码及发布文件名同步；Python 库与格式版本独立。

## 实现与范围

新增 v6.2 exp（推荐），保留 v6.1 exp 和 v4 adaptive。新增内容准入层检查竖弯钩、止部关键笔，覆盖完整、父级、嵌套部件及单笔回退。撤销已确认不兼容的继承来源，再按原约束重试；保留正确部件及实际原笔迹、压力、时间和来源检查。v6.1 使用原规则函数，已有方法档案不强制迁移。新方法独立建档和记录规则版本。

规则与阈值详见 [v6.2 方案](V62_EXP_CONTENT_ADMISSION.md)。修复是有界实验，不代表通用语义识别已解决，也没有新留出泛化结论。原结构数据库、旧生成文件、样本、字体及文档均不改写。

## user_001 实际字体验证

使用与历史全库相同的来源档案，在全新目录实际生成孔、正、址、兄、礼、烧、止、怔、歪、羊、群共 11 字，0 失败。该历史档案含验证用途样本，本批是开发回归，不称独立无泄漏验证。

- **正**：走底的撇捺来源被拒绝。址的完整止部语义合格，但会引入新的跨部件碰撞，原有检查继续拒绝。最终下部第 2、3、5 笔使用上的完整对应部分，第 4 笔来自直；顶横仍来自原脚样本。没有参考缺口。未强制闭合作者原有笔间空隙。
- **孔**：孩部前三笔与旧结果完整相同。错误斜钩和竖提均排除；20 个语义合格候选中，19 个因边界或端点、1 个因长度被拒绝。因此第 4 笔保留明确参考缺口。其内容形态恢复，但不宣称作者来源完整或风格完全修复；需要后续补录/更合适来源才能消除缺口。
- 制作真实新字体 `user_001-v62-validation-full-symbols-20261020.inkfont`：**9771 字、10730 候选、8374827 点**。仅更换两个生成候选，其余 **10728** 个候选的记录、轨迹字节、度量、来源摘要逐项相同，字母正斜体、标点、数学符号及数学轴均保留。来源提示候选由 3350 变为 3351，新增的是孔。
- 字体名明确注明“v6.2 exp 验证合并版 · 孔正重生”，不是全库 v6.2 重生成。新字体内容版本 0.2、格式仍 1.0，采用新 package/release/candidate 身份，记录父字体与替换范围；原包保留且不自动切换用户文档字体。

首次试跑仍混入竖提，检查对照图后补上参考终端上钩角色约束并重新验证；早期结果保留供追溯，不作最终交付。最终生成运行 `release-run` 保留生成时源文件哈希；生成之后相关源码仅进行了 import 排版整理，算法未变，应用构建源哈希另行冻结。

## 实际测试和构建

| 检查 | 结果 |
| --- | --- |
| 完整相关回归 | **1271 passed、2 skipped，347.50 秒** |
| v6.2/字体专项 | 角色区分、平移缩放不变性、自然斜度、嵌套绕过、串行批量一致、同字排除、缺口、修订原包保持与失败不发布通过 |
| Ruff | 本轮 11 个 Python 文件通过 |
| 完整新字体验证 | 源字体和新字体全部 10730 候选完整校验通过；逐项核对其余候选保持 |
| 三种打包方法 | 实际 InkStructTool.exe：v62/v61/v4 各完成 scx 11 字导入、建档、生成、制作字体、排版、保存重开、SVG |
| 原生 Windows | 实际 InkStruct.exe 0.1.32 打开新字体冻结小样，1 页、6 实例；来源明细显示孔第 4 笔，确认后 SVG 成功；另存、重开通过 |
| 原生精确比对 | 源码身份、选样身份、字形字节/度量、页面 SVG 与优化后机器 SVG 一致；原生确认仅改变 warning_accepted，编辑器补入 11 个标准内置数字资源逐项核对一致；全局默认未变 |
| 旧文档/模板 | .20 校正、.21/.22 模板、.23 字距 SVG 精确相同；历史恢复文档 11 页、301 项原诊断保留，设置无操作往返与 SVG 一致 |
| 数据保护 | 3206 个可读历史用户/交付文件哈希保持；3 个历史不可读字体仅核对大小及修改时间，不修改权限、不声称内容哈希验证 |
| Windows 构建 | 新目录 PyInstaller 构建通过；InkStruct.exe 与 InkStructTool.exe 均为 x64，文件及产品版本 0.1.32；源码与构建一致 |

两项跳过因账户缺少符号链接权限：真实图片链接与悬空项目链接。没有放宽协议或隐藏来源警告。数位板、驱动、写字机实物与纸面书写未验证。LaTeX 手册源码同步，未重编译 PDF。未执行 reset、clean、提交或推送，没有覆盖历史交付。

## 产物和命令

- 应用：`artifacts/windows_build_0.1.32_20261020_release/dist/InkStruct/InkStruct.exe`，工具位于同目录；保留整个目录及 `_internal`。
- 正式独立交付目录：`artifacts/windows_release_0.1.32/`，包含应用 ZIP、独立验证字体、使用说明及 SHA256/版本核对。
- 运行、日志、字体报告、真实前后图 `comparison.png`、原生截图、SVG、冻结文档及源码快照：`artifacts/v62_0.1.32_20261020/`。最终核对 `delivery-seal.json`，临时缓存清单 `cleanup.json`。
- 包内完整自检：`artifacts/windows_bundle_check_0.1.32_20261020_release/verification.json`。
- 原生独立验收工作区：`workspaces/windows-v62-0.1.32`。没有写入现有用户字体库或替换正在使用的旧字体。

以下在项目根目录使用 PowerShell 运行。构建、自检和字体脚本中所示目录为本次已执行路径；重跑必须选尚不存在的新输出路径，正式再次交付须递增 APP_VERSION。

```powershell
& .\artifacts\windows_build_0.1.32_20261020_release\dist\InkStruct\InkStruct.exe --workspace .\workspaces\windows-v62-0.1.32
& .\.venv\Scripts\python.exe -m inkstruct.application --workspace .\workspaces\windows-v62-0.1.32
& .\.venv\Scripts\python.exe -m pytest tests/test_v62_semantics.py tests/test_font_revisions.py tests/test_generation_workflow.py -ra
& .\.venv\Scripts\python.exe artifacts/v62_0.1.32_20261020/run_logged.py regression -- .venv/Scripts/python.exe artifacts/v62_0.1.32_20261020/run_regression.py
& .\.venv\Scripts\python.exe artifacts/v62_0.1.32_20261020/build_validation_font.py
& .\.venv\Scripts\python.exe packaging/build_inkstruct_app.py --output artifacts/windows_build_0.1.32_20261020_release
& .\artifacts\windows_build_0.1.32_20261020_release\dist\InkStruct\InkStructTool.exe --inkstruct-check --samples artifacts/source_samples/scx_351bf154/samples/scx --writer scx --font artifacts/v62_0.1.32_20261020/user_001-v62-validation-full-symbols-20261020.inkfont --output artifacts/windows_bundle_check_0.1.32_20261020_release
```

本版可继续开发并交付实验应用与验证字体。孔末笔作者来源不足、未注册语义类型、独立留出与设备效果仍需后续验证；不得将验证字体描述为全库语义验收通过。
