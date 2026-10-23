# InkStruct 0.1.36 Windows：SVG 比例校正画布修复

本次正式构建为 0.1.36，唯一版本来源是 `src/inkstruct/fonts/__init__.py` 的 APP_VERSION。Python 库、字体、模板及项目协议版本不变。工作目录为 `C:\Users\lee\Documents\InkStructApp\InkStruct-Windows-Dev`；源码为 Git HEAD `af45b45f04f899fcaced43aa980b0508673ee6c0`、原有未提交快照与本轮最小修改。不能仅根据该提交恢复完整工作树。

## 根因与修复

0.1.35 的比例校正仅缩放笔迹坐标，仍用原画布进行最后边界校验。实际文档中的第一个“1”原本在纸内，横纵放大为 132.293% 后底部到 275.480 mm，超过未同步调整的 270.044 mm 纸高，因此弹出 `ink exceeds plot page bounds`。

现在先从冻结快照生成并严格验证原始全部页面，再应用本次选页和表格过滤、定位点及缩放。选中页的点坐标、SVG 物理宽高和 viewBox 同步缩放，左上角为原点，笔宽仍使用原毫米值。最后继续通过 PlotStroke/PlotPage 的有效路径与画布边界检查；不裁切、不重排、不平移补偿，也不通过缩小规避原始越界。

`plotter.json` 的 `export_scope.coordinate_scale` 记录 `canvas_policy: scale-with-coordinates-v1`、`pen_width_unchanged: true`、各选定页的原始/输出宽高。原有误导性的“纸张和笔宽均不变”标记已更正为分别记录画布策略和笔宽。未选页不变，输出文件仍沿用原文档页码。没有修改 SVG 路径协议、冻结流程、位图跳过范围或错误严重程度。

所有选项仅影响本次输出。文档/模板纸张、源码、预览、分页、图题、占位、字符校正和冻结选样保持原值。进入输出位置选择框前仍完成冻结与校验。目的地取消不写出，后续编辑不会改变已冻结导出。

## 本机测试与验收

环境为 Windows x64、Python 3.13.16、PySide6 6.9.2、NumPy 2.5.4、PyInstaller 6.22.3。仅使用项目 `.venv`，无新增依赖；详细依赖版本及源码 SHA-256 位于构建 `build-provenance.json`。

- 首轮导出相关测试：72 项通过。最终相关回归：555 项通过，0 失败、0 跳过，248.86 秒。覆盖原始/最终边界、异向比例、100%、超大尺寸限制、贴边笔迹缩小时固定笔宽检查、空白页、选页、表格内容过滤、定位点、取消、提示/目的地期间文档变化、图片范围限制、模板/字段、字体/选样、字符校正、保存重开及 SVG。
- 新增核心回归：132.293% 越过旧画布而仍在新画布内时允许输出；原始真实越界即使缩小、过滤或未选该页也拒绝；输出尺寸仍受 2000 mm 单边上限约束；100% 保持原 SVG。
- 真实九页文档：只读使用 `C:\Users\lee\Downloads\黄钰翔液体粘滞系数.inkdoc` 的校验副本，SHA-256 为 `8dd565ba4d7e09ee0fdbb8388dd789ab655a8bf010e227f1694c956711326a93`。共 3,747 个文本实例、3,748 条冻结选样记录。100%、132.293% 不加定位点、132.293% 加定位点均成功输出全部九页；每点坐标、笔宽、实例及来源身份按预期核对。100% 九份 SVG 与修复前的原始合法输出逐字节一致。
- 原生最终构建：在独立工作区打开同份文档，弹窗输入横纵 132.293%、开启路径优化及定位点，明确确认跳过 2 张缺失 PNG，成功写出九页。输出画布为 `258.010581 × 357.249769 mm`，viewBox 与物理宽高一致。24 个配置框边界定位点保留在清单中。九份 SVG 与权威计算对照逐字节一致；路由身份和跳过清单一致。原生窗口已关闭。
- 文档原有 1 项模板校准、10 项表格来源样式、79 项数学校准警告及 2 项图片缺失错误全部保留。缺失图片哈希仍为 null，清单记录缩放后的占位；未伪造/替换资源。字体未重建、全库未重跑。
- 最终包内自检完成 v6.2/v6.1/v4 的 scx 11 字流程、真实 user_001 字体导入、冻结重开、输入/粘贴及严格路径输出，`notices=[]`。两个 EXE 的 FileVersion/ProductVersion 均为 0.1.36，PE 架构为 x64。

验收脚本最初对 GUI 百分数除以 100 的浮点值采用完全相等比较，因此清单比较失败；实际九个 SVG 始终逐字节一致。已记录清单的末位差异，最大约 `5.46e-12`，仅验证脚本采用明确浮点容差，不改变任何生产校验。另修正验证脚本将实际模板框数量误认成每页一框的断言，实际为 24 个定位点。记录见 `verification-notes.txt` 和 `native-numeric-comparison.json`。原生模态框的 UIA 索引不可用时，通过当前截图与键盘完成操作。

交付前逐项核对 3,219 个既有用户文件，SHA-256 全部不变，Git HEAD 不变。没有 reset、clean、提交或推送；构建工具的 PyInstaller `--clean` 仅作用于本轮独立构建缓存，不是 Git clean。历史产物未覆盖。

## 准确命令与产物

在项目根目录执行 PowerShell 命令：

```powershell
.venv/Scripts/python.exe -B -X utf8 -m inkstruct.application --workspace workspaces/windows-svg-canvas-0.1.36
.venv/Scripts/python.exe -B -X utf8 artifacts/svg_canvas_0.1.36_20261021/run_tests.py --label repeat-01
.venv/Scripts/python.exe -B -X utf8 packaging/build_inkstruct_app.py --output artifacts/windows_build_0.1.37_new
```

测试标签及构建目录必须换新。未来正式构建须先按 AGENTS 递增版本；本次实际构建使用 `--output artifacts/windows_build_0.1.36_20261021_delivery`。真实文档验证脚本 `verify_document.py` 使用独占新输出目录；再次执行须将 OUT 及输出名称改为新目录，不能覆盖当前证据。包内自检的精确命令保存在 `bundle-command.json`。

- 交付包：`artifacts/windows_release_0.1.36/InkStruct-0.1.36-Windows-x64.zip`，完整解压后运行 InkStruct/InkStruct.exe，保留 `_internal`。
- 可运行程序：`artifacts/windows_build_0.1.36_20261021_delivery/dist/InkStruct/InkStruct.exe`，同目录含 InkStructTool.exe。
- 本次原生九页输出：`artifacts/svg_canvas_0.1.36_20261021/native-scaled-registration/`，含 plotter.json。
- 真实文档、边界回归、来源和原始几何对照：`artifacts/svg_canvas_0.1.36_20261021/document-verification.json`、`scaled/`、`scaled-registration/`、`unscaled/`。
- 原始测试日志、XML、命令、原生状态、数据核对、源码变更审计和快照：`artifacts/svg_canvas_0.1.36_20261021/`。
- 包内自检：`artifacts/windows_bundle_check_0.1.36_20261021_delivery/verification.json`。
- 新验收工作区：`workspaces/windows-svg-canvas-0.1.36/`。

仅清理本轮测试临时目录、构建 work/cache；保留构建诊断、源码备份、全部数据、日志及输出。

## 未验证项与使用边界

软件修复可继续开发及交付。实体写字机、导入工具是否再次自动缩放、实际笔宽与纸面校准仍需实物验证；132.293% 会改变 SVG 物理画布尺寸。原始两张 PNG 仍缺失，只有用户明确跳过后才输出其余可书写内容，不能称为包含图片的完整成品。单边 2000 mm 限制保留；缩小时固定笔宽可能使贴边笔迹超出新边界并被拒绝。

LaTeX 手册源码已同步 0.1.36；本机未安装 XeLaTeX/latexmk，未重编新版 PDF，历史 PDF 不作为新版。数位板、驱动及其他显示器组合本轮未测试。
