# InkStruct 0.1.26 Windows：明确跳过缺失位图引用

在 `C:\Users\lee\Documents\InkStructApp\InkStruct-Windows-Dev` 的完整未提交工作树上实施，起始应用 0.1.25，Git 基点 `af45b45f04f899fcaced43aa980b0508673ee6c0`。没有 reset、clean、自动提交或推送，没有覆盖历史交付。应用版本唯一来源是 `src/inkstruct/fonts/__init__.py` 的 `APP_VERSION=0.1.26`；Python 库、模板、文档和字体协议版本独立，未因补丁号修改。

## 问题依据与复现边界

只读核查 `C:/Users/lee/Downloads/模板适配报告.json`，SHA-256 为 `3d4bddb872358b8b26ebb90ba142924c466e1ce2fab3c5b90c5f47dea159394e`。报告有 4 项 `image-resource-missing` 错误，引用直流电压、直流电流、电阻、交流电压四张校准曲线 PNG，来源实际为 URL 编码中文。另有 88 项数学校准警告和 1 项模板纸面校准警告；报告记录 9 页。

本轮只提供了报告，没有提供对应的原 `.inkdoc`。因此验收使用包含同一组文件名的真实 user_001 字体等价小样，不声称复现原九页文档。报告摘要与来源哈希保存在 `provided-report-summary.json`，没有改动原报告。

## 最终行为与边界

已载入位图，以及能够明确识别的缺失本地 PNG/JPEG 引用，均可在用户确认后跳过。原生弹窗统一说明：

> 导出的 SVG 不包含非 SVG 图片，包括尚未载入的图片；保留当前预览中的图片占位与图题，导出其余可书写内容。

分别显示已载入、尚未载入的出现次数，可展开详情查看中文显示名称、原始编码引用和页码。默认取消；取消提示或输出位置选择均不产生文件。确认期间文档发生变化会终止这次导出；进入输出位置选择框之前冻结已确认的快照、优化选项及跳过清单，之后继续编辑不会改变本次输出。

没有删除 Markdown 图片节点，没有补图或创建假资源，没有重新排版。导出只使用当前快照的实际笔迹路径，保留占位、图题、正文坐标、页序与冻结选样。纯图片页保留为空白机器页；其 `strokes=[]` 与同页的跳过项、原因和占位相对应。

`image-resource-missing` 在预览和模板报告中仍为错误；`exportable`、`plotter_exportable` 继续表示完整文档能力，不因受限出口而变成 true。独立的 `can_export_with_image_omission` 逐个核对实际页面图片占位、支持类型、错误代码和源码范围。适配窗口可同时说明“完整写字机导出不可用”和“可确认跳过位图导出其余内容”，报告 JSON 协议及原错误保持不变。

缺失引用只允许 `.png`、`.jpg`、`.jpeg`，大小写不敏感；URL 编码严格解码一次，与现有导入路径语义保持一致，不按名称匹配或替换资源。缺失 SVG、未知格式、网络/绝对/越界/歧义路径、非法字节资源、缺字、公式错误、越框、超限及未配置的绘制能力仍阻断。已有资源按既有 PNG/JPEG 校验加载；资源包哈希、格式和像素检查保留。

`plotter.json` 沿用既有 `export_scope`，`omitted_images` 包含：`reason` 为 `loaded-raster` 或 `resource-not-loaded`，页索引、从 1 开始的页码、稳定节点与出现身份、源码范围、原始引用、解码显示名称及占位坐标。已载入图片记录真实 `original_sha256`；缺失图片为 null，不伪造哈希。没有图片二进制数据写入跳过清单。

CLI 默认不跳过内容，必须明确使用 `--plotter --omit-reference-images`。新 Markdown 的真实文件不存在时记录 `image-import-missing`，只有与实际 PNG/JPEG 占位及源码范围对应才可跳过；非法资源仍为 `image-import-failed`。受限导出成功时退出码为 0，报告中的完整文档 `exportable=false` 及错误继续保留，并提供 `export_scope`。

## Windows 验证

Windows 11 x64（build 26300），项目 `.venv` Python 3.13.16 AMD64，Qt/PySide6 6.9.2、PyInstaller 6.22.3。未修改全局 Python 或其他项目环境。

专项覆盖：仅缺失 PNG/JPEG、混合已载入位图、中文与编码名称、严格类型/路径边界、非法资源、未对应的缺失错误、取消与目的地取消、确认期间变化、文件选择框期间冻结快照、占位和图题、连续分页、纯图片页、模板报告、保存重开、冻结选样、实际清单与 SVG 路径一致性。

最终完整回归 **1096 项通过、2 项跳过**，覆盖 97 个测试模块，用时 310.23 秒。跳过项仅为本 Windows 账户缺少符号链接权限的真实图片链接和悬空项目链接检查；原始结果见 `regression.log`。11 个本轮 Python 变更文件 Ruff 检查通过。初期测试曾误把 Markdown 自动编码后的合法百分号文件名视为非法 URL，并用会清空撤销栈的 setPlainText 测撤销，均修正测试后通过。真实字体验收最初把显式来源确认标记也作为确认前后选样比较；已分开核对候选身份不变、显式记录来源提醒及确认后的保存重开，未隐藏警告。失败日志保留。

原生 EXE 使用独立新工作区 `workspaces/windows-missing-raster-0.1.26`。真实字体小样一页，四个缺失图片错误、一个数学校准警告和一个模板纸面校准警告完整保留。核对导出按钮可用、0 处已载入与 4 处未载入计数、四个中文文件名及原始编码引用、取消返回和实际确认导出。实际 SVG 的 40 条手写路径与同一快照预期字节一致，原 `.inkdoc` 和全局默认参数记录不变，见 `native-verification.json`。

最终包内自检包括同样的缺失位图小样，以及既有真实字体完整验证、图高、汉字公式、英文间距、字符校正、模板七页循环和两种生成方法的 scx 真实 11 字流程。来源缺口、数学校准和纸面校准警告均保留，没有重跑全库。

旧长文档仍为 11 页、301 条诊断，全部页面 SVG、无改动设置应用和保存重开保持一致。旧 0.1.21/0.1.22 模板项目、0.1.23 字距及 0.1.20 字符校正文档的选样和机器 SVG 字节一致。保护清单中 2496 个可读既有文件哈希核对不变；另 3 个开始即权限不可读的历史字体只核对大小和修改时间，没有改权限。

未验证：用户原九页 `.inkdoc`、实体数位板、驱动、写字机和纸面效果，本轮未重验中文输入法组合输入。LaTeX 手册源码已同步，本机没有 XeLaTeX/latexmk，新版 PDF 未编译。可以继续开发并交付本次软件更新；硬件和原文档仍按这些限制验收。

## 产物与准确命令

- 正式包：`artifacts/windows_release_0.1.26/InkStruct-0.1.26-Windows-x64.zip`；哈希见同目录 `SHA256SUMS.txt`。
- 可运行目录：`artifacts/windows_build_0.1.26_20261019_release/dist/InkStruct/`，保留整个目录和 `_internal`；双 EXE 均为 0.1.26。
- 构建记录：上述构建目录的 `build.log`、`build-provenance.json`。
- 测试日志与原生验收：`artifacts/missing_raster_0.1.26_20261019/`，含源码基线、环境、输入报告摘要、`regression.log`、`native-verification.json`、截图、`native-fit-report.json`、`native-export-svg/`、`cleanup.json`、`delivery-seal.json`。
- 最终包内自检：`artifacts/windows_bundle_check_0.1.26_20261019_release/`。

```powershell
# 源码启动，继续使用自己的既有工作区
.venv/Scripts/python.exe -m inkstruct.application --workspace workspaces/windows-0.1.8

# 本轮 EXE 和独立验收工作区
& 'artifacts/windows_build_0.1.26_20261019_release/dist/InkStruct/InkStruct.exe' --workspace workspaces/windows-missing-raster-0.1.26

# 专项：basetemp 使用新的目录
.venv/Scripts/python.exe -m pytest tests/test_missing_raster_export.py tests/test_missing_raster_export_qt.py tests/test_raster_export.py tests/test_raster_export_qt.py tests/test_images.py -ra --basetemp artifacts/qa26-repeat-new

# 显式范围导出：输出使用不存在的新目录
.venv/Scripts/python.exe -m inkstruct.cli document render artifacts/missing_raster_0.1.26_20261019/native-input.inkdoc --plotter --omit-reference-images --output artifacts/missing-raster-repeat-new

# 全部回归清单：run_regression.py，重跑前更换 basetemp
# 最终 EXE 自检：output 使用新的目录
& 'artifacts/windows_build_0.1.26_20261019_release/dist/InkStruct/InkStructTool.exe' --inkstruct-check --samples artifacts/source_samples/scx_351bf154/samples/scx --writer scx --font artifacts/user_001_full_font_20261018_math_axis/user_001-v61-full-symbols-20261018.inkfont --output artifacts/missing-raster-bundle-repeat-new

# 下次正式交付先将 APP_VERSION 至少递增为 0.1.27，再选新目录
.venv/Scripts/python.exe packaging/build_inkstruct_app.py --output artifacts/windows_build_next_new
```

仅清理本轮可重建测试目录、私有 TEMP/缓存、构建 work/cache 和新增测试字节码，保留源码、数据、日志、原生验收、可运行应用与交付包。清理清单和最终数据/版本/ZIP 校验见封存记录。
