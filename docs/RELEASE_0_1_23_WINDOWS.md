# InkStruct 0.1.23 Windows 交付记录

日期：2026-10-19。项目路径：`C:\Users\lee\Documents\InkStructApp\InkStruct-Windows-Dev`。Git 基底 `af45b45f04f899fcaced43aa980b0508673ee6c0`，继续使用完整未提交工作树。已检查 AGENTS.md、Git 状态、当前源码和上一版交付说明；修改前保存源码快照和既有数据摘要。没有 reset、clean、自动提交、推送或覆盖历史交付包。

`src/inkstruct/fonts/__init__.py::APP_VERSION` 从 0.1.22 递增为 **0.1.23**，为应用版本唯一来源。README、使用说明、LaTeX 手册源码和发布文件名同步；Python 库和字体协议版本独立。使用本项目 `.venv`：Windows 11 x64（26300），Python 3.13.16 AMD64，PySide6/Qt 6.9.2，PyInstaller 6.22.3；未修改全局 Python 或其他项目环境。

## 英文间距的原因与修正

旧版按照采集原点到笔迹右边界加留白计算前进宽度。单个字符在采集格内偏右，也会把这段横向位置计入每个字符间距。真实 user_001 样本的部分 `i` 笔迹仅约 0.07 字高，采集左留白却约 0.25 字高，造成英文单词疏散。

增加“按笔迹宽度（推荐）”：英文字母使用实际笔迹宽度，两侧各留 0.04 字高并计入物理笔宽。只调整横向排布，不缩放笔迹、不更改基线、采集坐标、字体成员或样本身份。使用冻结的 optical layout frame，避免字体另存校正被再次归一化或重复叠加。正文、标题、列表、命名字段、表格及图题共享该策略。汉字、数字、标点、公式、等宽代码使用原规则；纯文本检查模式保持原路径。单字样本不能提供真实连笔或每对字母的间距，本版不宣称自动还原这些信息。

真实 27 字符行 `minimum William iii ill WWW` 使用同一冻结选样，原宽 **87.901772 mm**，新宽 **66.849548 mm**，减少约 **23.95%**。完整对比见 `real-font-spacing.json` 和两份 SVG，原始字体 SHA-256 仍为 `b114b9db538610176eaf4ca7ca6f5f177fd0319817599433dec274c50061c9c3`。

## 使用与兼容

入口：齿轮 → 排版默认设置 → 正文与段落 → 英文字母间距。可选择“按笔迹宽度（推荐）”或“保留采集位置留白（旧版）”。无既有配置的新安装使用推荐策略。**已有全局默认和旧 `.inkdoc` 不自动重排**。

若要让当前旧文档使用新字距，选择推荐策略，并明确勾选窗口底部“同时将默认排版参数应用到当前文档”。此操作也会应用窗口内的其他默认排版参数，应核对后确认；独立表格、图片属性和冻结选样继续保留。关闭设置或取消不修改当前文档。

新间距由明确的 `inkstruct_flow_style_v3` 保存，字段为 `latin_spacing`（`handwriting` / `capture`）。旧 FlowStyle v1/v2 缺省保持 `capture`；写回旧协议时不夹带新字段。模板 v1/v2/v3、命名字段、字体及项目资源协议沿用原格式，不迁移原文件。采用新样式的项目应使用 0.1.23 或后续支持该协议的应用打开，旧应用不能静默忽略新样式。

## 字符校正预览

点击排版预览中的字符后，右侧显示同一物理行中左右各最多三个邻字，使用当前页面的实际坐标、字距、冻结选样和邻字已有校正。淡蓝底标记所选位置；深灰为周边已排字形，浅灰为调整前字体笔迹，蓝色为校正草稿。批量范围内的可见同样本／同字符也预示草稿效果，其他邻字维持当前状态。

不跨页、跨行或跨不同容器拼接邻字。上下文在选字或排版快照变化时更新，最多七个字符；拖动参数只重画局部，既不重新排全文，也不重新选样。预览与应用使用相同的毫米坐标变换。取消、恢复、三种范围、另存字体、撤销重做与保存重开继续保留；字符位移缩放仍保留前进宽度和换行。

## 验收结果

最终相关回归覆盖 85 个模块：**827 passed，2 skipped，321.83 秒**。两个跳过为本账户缺少 Windows 符号链接权限的真实图片链接和悬空项目链接检查，没有降低校验。21 个本轮变更 Python 文件 Ruff 通过。专项涵盖采集偏左／偏右的窄字母、笔宽间隙、换行、表格、公式／代码保持原规则、FlowStyle v3 保存重开、选样不变、预览与正式校正坐标一致、三种范围、极值与 100%/150%/200% DPI。

首次扩大回归有 8 项失败：五个旧 GUI 测试模块读取了机器上真实保存的 PDF 模板默认值，与测试普通页面前提冲突。已让其子进程使用私有 INI 设置目录，未修改用户设置、产品默认或测试断言；隔离后 12 项专项及整组回归均通过。包内自检脚本先后暴露两处测试准备错误：调用不存在的旧方法名，以及继承前一步“同字符全部样本”范围却断言只有一个草稿字形。已移除冗余调用，沿用真实文本变化信号，并在单字验收前明确选择“仅此处”；先独立验证该真实字体流程通过，再重建并执行整包验收。初次失败日志与内部候选保留，不作为通过记录。

旧 0.1.21、0.1.22 真实模板项目均维持 7 页，冻结选样与写字机 SVG 字节一致；旧 0.1.20 的同样本／同字符校正文档 SVG 一致。旧长文档仍为 11 页、301 条诊断，全部页面 SVG 与历史 Windows 基线一致。设置无改动应用和保存重开同样一致，原缺字、来源和协议诊断保留。

**2116 个可读既有文件哈希一致**，涵盖任务、采集、样本、字体、评价、生成、工作区、历史验收和交付包。另 3 个历史工作区字体在开始即权限不可读，仅核对大小与修改时间不变；未修改权限，不宣称已核对其内容。字体及采集库原件没有被本次 QA 字体或文档替换。

原生 Windows 验收使用真实 user_001 录制字母的小文档。在新工作区实际选中 `minimum` 中的 `n`，对照邻字将上下位移设为 +5%，应用并另存新文件；源码、稳定身份及全部选样不变。最终 EXE 重开后仍显示该校正及周边字形，且可导出 SVG。最终包内验收还检查相同预览几何、撤销、保存重开，并保留既有模板、字体导入和双方法 scx 真实 11 字流程；未重跑全库。详细结果见本轮包内 `verification.json`。

未验证：实体数位板、驱动、写字机和纸面书写效果；本轮没有重新验收中文输入法组合输入。LaTeX 手册源码已同步；环境没有 XeLaTeX/latexmk，未重编译新版手册 PDF。上述软件结果均来自当前 Windows 环境。

## 交付位置与准确命令

正式包：`artifacts/windows_release_0.1.23/InkStruct-0.1.23-Windows-x64.zip`。仅此 ZIP 为本轮正式交付；之前的同版本目录为内部验收候选，历史交付不覆盖。双 EXE 的 x64、FileVersion/ProductVersion、源码摘要、ZIP CRC、SHA-256 和文件摘要见同目录 `verification.json` 与 `SHA256SUMS.txt`。

可运行目录：`artifacts/windows_build_0.1.23_20261019_delivery/dist/InkStruct/`，保留整个目录及 `_internal`。源码前快照、脚本、日志、截图、文档和 SVG：`artifacts/letter_spacing_0.1.23_20261019/`。最终包内检查：`artifacts/windows_bundle_check_0.1.23_20261019_delivery/`。重点记录：`regression_final.log`、`settings_isolation.log`、`lint_final.log`、`compatibility.json`、`legacy-corrections.json`、`final-verification.json`、`real-font-spacing.json`、`native-verification.json` 和 `delivery-seal.json`。

```powershell
# 源码启动；沿用自己的既有工作区
.venv/Scripts/python.exe -m inkstruct.application --workspace workspaces/windows-0.1.8

# 启动本次正式 EXE；独立验收工作区与原工作区分开
& 'artifacts/windows_build_0.1.23_20261019_delivery/dist/InkStruct/InkStruct.exe' --workspace workspaces/windows-letter-spacing-0.1.23-final

# 相关专项；basetemp 应使用新的目录
.venv/Scripts/python.exe -m pytest tests/test_latin_spacing.py tests/test_correction_context_qt.py tests/test_glyph_corrections_qt.py tests/test_flow_style.py -ra --basetemp artifacts/qa23-repeat-new

# 完整本轮回归清单；重跑前将脚本中的 basetemp 改为新目录
.venv/Scripts/python.exe artifacts/letter_spacing_0.1.23_20261019/run_regression_final.py

# 最终 EXE 自检；output 指定不存在的新目录
& 'artifacts/windows_build_0.1.23_20261019_delivery/dist/InkStruct/InkStructTool.exe' --inkstruct-check --samples artifacts/source_samples/scx_351bf154/samples/scx --writer scx --font artifacts/user_001_full_font_20261018_math_axis/user_001-v61-full-symbols-20261018.inkfont --output artifacts/windows_bundle_check_repeat_new

# 下次正式交付先递增 APP_VERSION 至至少 0.1.24，再使用新目录构建
.venv/Scripts/python.exe packaging/build_inkstruct_app.py --output artifacts/windows_build_next_new
```

清理仅限本轮可重建的测试临时目录、私有 TEMP、构建 work/cache 和新增模块字节码，具体路径与结果保存在 `cleanup.json`。源码、用户数据、日志、验收和交付产物全部保留。当前可以继续开发；最终交付核验记录以 `delivery-seal.json` 为准。
