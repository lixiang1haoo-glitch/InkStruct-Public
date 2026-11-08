# InkStruct 0.1.33 Windows

> 2026-10-20 原生补测：用户将窗口置前后，已完成本次功能的原生交互验收，真实导出及另存重开产物核对通过。详见 [原生验收补充](RELEASE_0_1_33_NATIVE_FOLLOWUP.md)。下文的激活失败和初始未完成状态保留为交付时历史；原 ZIP、字体与封存记录均未覆盖。

2026-10-20。项目路径 `C:\Users\lee\Documents\InkStructApp\InkStruct-Windows-Dev`。Git 基点 `af45b45f04f899fcaced43aa980b0508673ee6c0` 加完整未提交工作树，保留原有修改。APP_VERSION 唯一来源为 `src/inkstruct/fonts/__init__.py`，当前 0.1.33。Python 库、字体格式和字体内容版本独立。

## 本次实现

### CPU 与 GPU 预览

CPU 默认启用最多 4 页、32 MiB SVG 原文预算的解析缓存；按 SVG 内容哈希失效，缩放和分块可复用同一解析结果。修正相邻页预取被视口更新反复取消的问题；可见内容未就绪、任务已远离可见区或视口为空时仍取消。快照、缩放、关闭的取消保护与原有 96 MiB 页面图像缓存保留。

预览进程在应用初始化及载入项目之前异步启动，与资源校验和排版重叠。右上角齿轮新增“应用设置 → 预览绘制”，可选 CPU 或 GPU，默认 CPU，保存后下次启动应用生效。该设置不写入文档协议，也不重新选择字形。

GPU 使用 QtSvg → OpenGL2 → 8×MSAA FBO → 完成态读回 QImage，仍由原画布显示。采用 CombinedDepthStencil，有限解析缓存及估算 384 MiB FBO 缓存预算；超过单目标预算、设备限制、不支持要求的抗锯齿、图形异常时，对整份请求重新用 CPU 绘制，避免同一请求混用不同抗锯齿。进程启动失败/崩溃/超时也会用 CPU 重试同一请求一次。没有引入 CUDA、CuPy、训练依赖或降低分辨率。

接入的是上一轮已测可行范围，详见 `GPU_RASTER_FOLLOWUP_WINDOWS_20261020.md`；未接入存在像素差异的 QPicture、尚无独立原生收益验证的 resolve 优化、PBO、共享内存、直接纹理合成或负收益的候选 GPU 计算。本轮验证实现一致性，不把上一轮时延当成本版新测数据。

### 三项明确的字体派生规则

新字体制作在来源齐全且目标未提供时使用 `recorded-symbol-constructions-v1`；已有目标字形优先。

- `℃`：中文句号等比缩小并抬到大写正体 C 左上，保留 C 笔迹大小及基线。按来源顺序配对，不做无必要的全部交叉组合；记录两份来源身份、哈希、各自笔画及仿射变换。组合时间明确平移为单调，压力和笔状态保留，不冒充独立录制。
- `–`（U+2013）：完整复用 `−`（U+2212）全部笔画和度量，点列与动态值保持。
- `～`（U+FF5E）：从恰有两笔的 `≈` 中每笔各生成一份候选，保留形状、横坐标、动态值，并平移至来源数学轴。记录源候选和源笔序；不能明确拆成两笔时拒绝猜测。不是把两条波浪画成一个字形。

实际扩展 user_001 最新 v6.2 验证合并字体（其全库仍以历史生成结果为基础，仅孔/正是 v6.2 重生）：新增 **5 份 ℃、5 份 –、10 份 ～**。新包为 **9774 字、10750 候选、8376555 点**，字体内容版本 0.3、格式仍 1.0。旧包全部 **10730** 个候选的记录、轨迹字节、度量和来源摘要逐项完全相同；来源提示仍为 3351 个候选，孔的原有参考缺口保留。

新包使用新的 package/release 身份，记录父包，并以新身份导入 `C:\Users\lee\AppData\Local\InkStruct\workspace\fonts`。旧字体与已保存文档不自动切换。可在字体库选择“user_001 · v6.2 exp 验证合并版 · ℃与符号扩展 · 20261020”用于新排版。

### SVG 导出弹窗

点击“导出 SVG…”先打开统一弹窗：

- 页码留空导出全部；支持 `1-3,5`、中文逗号、去重，拒绝非法/越界/倒序范围。导出保留原文档页码，例如只选第 1、3 页，文件为 `page-001.svg` 和 `page-003.svg`。
- 默认导出表格内内容；取消后去掉单元格中的字形、公式线和下划线等内容，保留表格线及表外正文、图题等。使用语义节点和稳定身份判断，不根据位置或颜色猜测。
- 路径优化移入弹窗，保留文档原选择，新文档默认开启；成功导出后记录该偏好。取消不改偏好、不生成目录。
- 横纵比例默认 100%，范围 10%–1000%；以纸张左上角为原点，仅缩放 SVG 点坐标，纸张物理尺寸及笔宽保持。校正后墨迹超出纸面会明确拒绝，不自动裁切或缩回。
- “添加定位点”默认关闭。在每个内容文本框左上角和右下角的边界上添加长 0.1 mm、笔宽 0.01 mm 的横短线；模板 v3 包含正文框和字段框，旧模板使用明确的正文/固定区，普通页面使用页边距定义的正文区。比例也作用于短线坐标，中心线严格在转换后的边界上。纸边的短线允许中心线落在纸边，其余内容仍检查完整笔宽边界。

选择设置后，现有位图跳过确认继续有效，仅提示选中页涉及的已载入/缺失位图。缺失 SVG、未知图片、非法资源、缺字、公式错误、越框等仍阻断；本轮没有新增按导出范围放行其他错误的例外。

确认与校验后，在进入输出位置选择框**之前**冻结计划、筛选、比例及省略清单；输出位置选择期间即使编辑正文，仍导出已确认快照。选项或位图确认期间正文变化则取消。导出不重新排版、不改变 Markdown、页面顺序、正文坐标或冻结选样。

`plotter.json/export_scope` 记录源快照、所选页码、被排除的表格笔画身份、比例、定位点所属框和前后坐标、位图原占位及输出坐标；缺失位图哈希仍为空。输出仍为机器用绝对 M/L 路径，没有用 SVG transform 隐藏比例变换。原 CLI 导出默认行为保留，本轮新增选项通过桌面弹窗提供。

## 真实测试与限制

| 检查 | 结果 |
|---|---|
| 综合相关回归 | 初次 **1283 passed、2 skipped、5 failed，574.57 秒**；5 项为旧 GUI/派生字形断言，适配后 **5 passed，11.11 秒**。最终去重为 **1288 项通过、2 项跳过**；未把失败日志删除或冒充整套一次全绿 |
| 针对性集成 | 32 项通过；新增页码、比例、边界定位、表格正文/公式省略、取消、提示期间变化、目的地冻结等通过 |
| CPU/GPU | CPU 缓存与原 QtSvg 像素一致；模拟 GPU 请求中途失败时整批 CPU 重绘；模拟 GPU 子进程崩溃，同标识/同尺寸 CPU 重试成功；打包后的 CPU/GPU 全页和部分边缘块与源码结果逐像素一致，重复请求仍拒绝 |
| 实验控制对照 | 真实新字体 2 页、185 个文本实例；GPU 两个尺寸与上一轮正确 MSAA8 控制逐像素一致 |
| 字体 | 源包、新包完整校验通过，全部旧候选逐项保持；新增 20 份候选原型图 `symbol-contact-sheet.png` 已检查 |
| 保存、重开与导出 | 真实新字体文档的选样及各页 SVG 一致；选页、表内内容省略、比例、定位短线共同验证；数学未校准警告保留 |
| 包内自检 | 实际 InkStructTool.exe 的 v62/v61/v4 各完成 scx 小集导入、建档、生成、制作字体、排版、保存重开与 SVG；notices 为空，既有来源提示保留 |
| 构建 | 新目录 PyInstaller 构建成功；InkStruct.exe 与 InkStructTool.exe 文件/产品版本均 0.1.33；构建后生产源码哈希一致 |
| 静态检查 | 本轮修改的 Python 文件 Ruff 通过 |

3 项旧断言原来固定设置分类数量为 10，新增预览分类后更新为 11；1 项字体测试未考虑明确复用的新短横线，改为核对其减号来源与规则；1 项缓存测试需接受新导出弹窗。没有删除几何、来源、数学轴、取消或协议断言。

最初真实小样使用窄纸张却沿用 160 mm 默认表宽，校验按预期拒绝。随后仅将该验收小样的表宽显式设为 80 mm，原失败日志保留，生产越框检查未放宽。

两项跳过仍因账户缺少符号链接权限。原生新构建已启动，但自动化连续两次返回 `failed to activate captured window`，窗口焦点及屏幕交互验收暂未完成；已向用户请求将新窗口置前。自动化测试与包内真实 GPU 工作进程的通过不替代该项。数位板、驱动、写字机实物、实体比例/定位效果、其他厂商 GPU、驱动重置和长会话压力未验证。LaTeX 手册源码已同步，未重新编译 PDF。

## 位置与准确命令

- 应用：`artifacts/windows_build_0.1.33_20261020_release/dist/InkStruct/InkStruct.exe`；工具在同目录，必须保留整个目录和 `_internal`。
- 独立交付目录：`artifacts/windows_release_0.1.33/`，包含版本化应用 ZIP、新字体、使用说明和 SHA256/验收清单。
- 本轮输入、测试日志、失败及修正后的复测、字体报告、控制图、SVG、项目和源码快照：`artifacts/integration_0.1.33_20261020/`。
- 包内自检：`artifacts/windows_bundle_check_0.1.33_20261020_release/verification.json`。
- 仅本次新建验收工作区：`workspaces/windows-integration-0.1.33`。默认字体库新增包位置见 `font-library-import.json`。

项目根目录 PowerShell：

```powershell
& .\artifacts\windows_build_0.1.33_20261020_release\dist\InkStruct\InkStruct.exe --workspace .\workspaces\windows-integration-0.1.33
& .\.venv\Scripts\python.exe -m inkstruct.application --workspace .\workspaces\windows-integration-0.1.33
& .\.venv\Scripts\python.exe -X utf8 -m pytest tests/test_svg_export_options.py tests/test_svg_export_dialog_qt.py tests/test_symbol_constructions.py tests/test_preview_acceleration.py tests/test_preview_gpu_recovery_qt.py -ra
& .\.venv\Scripts\python.exe -X utf8 artifacts/integration_0.1.33_20261020/run_checks.py
& .\.venv\Scripts\python.exe packaging/build_inkstruct_app.py --output artifacts/windows_build_0.1.33_20261020_release
& .\artifacts\windows_build_0.1.33_20261020_release\dist\InkStruct\InkStructTool.exe --inkstruct-check --samples artifacts/source_samples/scx_351bf154/samples/scx --writer scx --font artifacts/integration_0.1.33_20261020/user_001-v62-validation-symbol-extensions-20261020.inkfont --output artifacts/windows_bundle_check_0.1.33_20261020_release
```

上述构建、自检及日志路径为本次实际运行路径；重跑须换新输出目录/日志名，正式再次交付还须递增 APP_VERSION。字体扩展 API 为 `inkstruct.fonts.symbol_rules.extend_font(source, output, name=..., font_version=...)`，实际制包脚本 `build_font.py` 与导入脚本 `import_user_font.py` 保存在本轮目录，均经完整校验并不覆盖原包。

本版可继续开发，已提供可运行 Windows 构建及新字体。当前界面焦点自动化验收及实体设备效果仍有上述限制。保留所有原任务、采集样本、作者档案、生成、字体、评价、模板、冻结项目和未提交工作；数据核验和清理结果见本轮 `delivery-seal.json`。没有 reset、clean、提交或推送，没有覆盖历史交付。
