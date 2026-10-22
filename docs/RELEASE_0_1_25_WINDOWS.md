# InkStruct 0.1.25 Windows：非 SVG 参考图片的提示与跳过导出

本次在 `C:\Users\lee\Documents\InkStructApp\InkStruct-Windows-Dev` 的完整未提交工作树上完成。起始应用 0.1.24，Git 基点 `af45b45f04f899fcaced43aa980b0508673ee6c0`；未使用 reset、clean、自动提交、推送或覆盖历史交付。应用版本唯一来源为 `src/inkstruct/fonts/__init__.py` 的 `APP_VERSION=0.1.25`，Python 库与字体协议版本独立。

## 最终行为

仅因页面包含 PNG/JPEG 等非 SVG 参考图片，不再禁用顶部“导出 SVG…”。点击后说明有多少处图片不会写入 SVG，保留排版占位和图题，并询问是否继续。取消直接返回；确认后选择全新输出目录。导出结果包含其余文字、公式、表格及受支持的单线 SVG 路径，原图片仍保留在预览和 `.inkdoc` 中。

图片占位、分页和其他内容坐标不重排；纯图片页可以保留为空白机器页。图题作为已有手写路径正常输出。`plotter.json` 使用既有 `export_scope`，记录 `image_policy=omit-raster-preserve-layout-and-captions` 与 `omitted_images`，包含页索引、源码范围、节点与出现身份、来源、原图 SHA-256 和占位坐标，不嵌入图片数据。模板预印底图继续只作参考。

底层 `plan_from_snapshot` 默认仍要求完整可导出内容，只有显式 `omit_reference_images=True` 才跳过实际 RasterOp。原 `plotter_exportable=false` 继续表示不能把全部内容完整写出；GUI 在没有真正阻断错误时允许进入提示流程。CLI 为 `--plotter --omit-reference-images`，未附加时仍拒绝含位图的完整机器导出。这个改变不涉及模板、字体或文档协议迁移。

缺字、公式错误、图片资源缺失、越框、超限、非法笔画和未配置的多笔颜色继续阻止导出，不会因为选择跳过图片而放行。用户截图中的缺字或排版问题需要按诊断另行解决。本轮不自动描图、不替换字形、不修改图片资源，不更改用户字号、图高或模板。

## Windows 验收

环境：Windows 11 x64（build 26300），项目独立 Python 3.13.16 AMD64；PySide6/Qt 6.9.2、PyInstaller 6.22.3。使用本项目 `.venv`，未改动全局 Python 或其他环境。

专项检查覆盖提示与取消、目的地取消、确认导出、提示期间源码变化、没有图片时原出口、同图多次出现、位图与单线 SVG 混排、纯图片页、缺失资源及真实公式错误阻断、来源清单、原图预览不变、保存重开与冻结选样。

最终完整回归 **1064 项通过、2 项跳过**，覆盖 95 个测试模块；跳过项仅为本 Windows 账户没有符号链接权限的真实图片链接与悬空项目链接检查。最终九个修改的 Python 文件 Ruff 检查通过。原生日志、包内自检与封存记录见 `regression_final.log`、`bundle_final.log`、`native-final-verification.json`、`verification.json` 与 `delivery-seal.json`。

首次专项测试因新增测试脚本内的反斜杠转义错误失败，修正后复测通过。初次完整回归发现，新增的文件选择框后状态检查破坏既有“进入文件选择框前冻结排版”的语义；已移除该处检查，保留图片确认结束时的检查，并新增带图片的冻结快照与清单一致性用例。确认后即使选目录期间正文变化，也导出已确认的快照；相关 7 项复测与完整回归均通过，初次失败及后续复测日志保留。

最终原生 EXE 使用新工作区 `workspaces/windows-raster-export-0.1.25-final` 打开真实 user_001 字体和参考图的小文档，确认 SVG 按钮可用、跳过说明可见、取消返回预览，确认后实际导出。78 条手写路径与预期逐页 SVG 完全一致，清单记录一处被跳过的位图；预览仍显示原图片，原项目字节和全局默认参数记录不变。保留两条数学校准警告及一条参考图片警告。截图与原生导出均保留在验收目录。首次候选未交付，见 `superseded-build.json`；正式包仅使用 final 目录中的修正构建。

最终双 EXE 检查还执行既有完整字体校验、汉字公式、图片 60 mm 默认、英文间距、字符校正、模板七页循环与两种生成方法的 scx 真实 11 字流程，来源缺口提示保留；没有重跑全库生成。

旧长文档仍为 11 页、301 条诊断，全部页面 SVG、设置无改动应用与保存重开一致。保护清单中的 2375 个可读既有文件逐个核对哈希；另三个历史字体开始即权限不可读，仅核对大小和修改时间，未修改权限。最终保护与缓存清理结果见封存记录。

未验证：实体数位板、驱动、写字机和纸面效果；本轮未重验中文输入法组合输入。LaTeX 手册源码已同步，环境没有 XeLaTeX/latexmk，新版 PDF 未重编译。软件可以继续开发与交付，本记录不宣称完成硬件验收。

## 输出与复现

- 正式包：`artifacts/windows_release_0.1.25/InkStruct-0.1.25-Windows-x64.zip`，SHA-256 见同目录 `SHA256SUMS.txt`。
- 运行目录：`artifacts/windows_build_0.1.25_20261019_final/dist/InkStruct/`，保留整个目录和 `_internal`；双 EXE 版本均为 0.1.25。
- 日志和验收：`artifacts/raster_export_0.1.25_20261019/`。
- 最终 EXE 自检：`artifacts/windows_bundle_check_0.1.25_20261019_final/`。
- 原生实际 SVG：`artifacts/raster_export_0.1.25_20261019/native-final-export-svg/`。

```powershell
# 源码启动；使用自己的现有工作区
.venv/Scripts/python.exe -m inkstruct.application --workspace workspaces/windows-0.1.8

# 本轮原生应用和独立验收工作区
& 'artifacts/windows_build_0.1.25_20261019_final/dist/InkStruct/InkStruct.exe' --workspace workspaces/windows-raster-export-0.1.25-final

# 专项重跑：basetemp 必须选择新的目录
.venv/Scripts/python.exe -m pytest tests/test_raster_export.py tests/test_raster_export_qt.py tests/test_images.py tests/test_image_settings_qt.py tests/test_plotter.py -ra --basetemp artifacts/qa25-repeat-new

# CLI 显式跳过参考图片，输出必须为新目录
.venv/Scripts/python.exe -m inkstruct.cli document render artifacts/raster_export_0.1.25_20261019/native-input.inkdoc --plotter --omit-reference-images --output artifacts/omitted-svg-repeat-new

# 完整回归清单见 run_regression.py；重跑须更换其中的 basetemp
# 下次正式交付先将 APP_VERSION 至少递增至 0.1.26，再选新构建目录
.venv/Scripts/python.exe packaging/build_inkstruct_app.py --output artifacts/windows_build_next_new
```

仅清理本轮可重建临时目录、构建 work/cache 与新增测试字节码，保留源码、所有用户数据、日志、截图、验收与交付产物；具体清单见 `cleanup.json`。
