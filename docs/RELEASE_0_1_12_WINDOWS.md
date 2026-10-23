# InkStruct 0.1.12 Windows：长文稿预览优化

日期：2026-10-18（Asia/Shanghai）。项目：`C:\Users\lee\Documents\InkStructApp\InkStruct-Windows-Dev`。应用版本唯一来源为 `src/inkstruct/fonts/__init__.py:APP_VERSION`，本轮为 0.1.12，下一次正式应用交付至少 0.1.13。Python 库仍为 0.2.0，字体协议版本不变。沿用完整、含未提交修改的工作树，没有 reset、clean、提交或推送。

## 实际原因和改动

使用当前长文稿的自动恢复副本作为只读输入，保留原始来源路径和 SHA-256；预览包含 11 页、4580 个文本实例、301 条原有诊断。

- 全库字体下，每次更新重复解析约 1500 份候选，并重复计算完整轨迹身份。现在仍读取并校验实际字体成员字节，只在全部规范输入完全一致且已有工厂校验标记时复用不可变描述符。记录、来源、数学轴、压力、时间、数值类型及轨迹变化都会阻止复用；修改或损坏字体仍被拒绝。替换构造的描述符不继承校验标记。
- 字形边界反复扫描点列、缓存容量估算递归访问每个坐标。现在缓存不可变字形的边界和保守容量估算，现有缓存上限不增大；新字形或替换构造的几何会重新计算。
- 自动恢复副本原先在界面线程序列化和压缩。定时保存现在使用后台任务，输入、字形选择和评价使用独立的请求快照；完成后仅更新所属编辑会话的恢复哈希。保存期间的新修改保留待保存状态并安排后续保存。旧任务不接管新项目，外部改动仍触发冲突错误。显式正式保存仍同步执行并保留原有冲突保护。

不修改生成核心、排版规则、字体协议、用户原文、笔迹、字体内容或来源提示；不隐藏缺字和未支持公式诊断。

## 本机性能对比

环境：Windows x64，项目 `.venv` Python 3.13.16、PySide6 6.9.2、PyInstaller 6.22.3。完整依赖和构建来源哈希记录于 `artifacts/windows_build_0.1.12_20261018/build-provenance.json`。性能数值是本机该文稿测量，不能保证所有文稿相同比例。

| 场景 | 优化前 | 优化后 |
| --- | ---: | ---: |
| 完整字体，末尾局部编辑重排 | 3.18 秒 | 1.31 秒 |
| 内嵌资源，末尾局部编辑重排 | 0.99 秒 | 0.52 秒 |
| 完整字体，重复更新的 cProfile 时间 | 13.19 秒 | 1.94 秒 |
| 自动恢复保存的界面调用返回 | 1.05 秒 | 0.005 秒 |
| 自动恢复期间 Qt 心跳最大间隔 | 1.05 秒 | 0.33 秒 |

重复更新使用 cProfile，会显著放大绝对耗时，不能将该行当作实际交互秒数。页面重复绘制仍约 7 毫秒；主要收益在资源处理和后台保存。初次加载完整字体仍需要校验，本机冷启动重排约 5 秒；长文稿的全量重排与显式正式保存仍有耗时，后台 JSON 编码也可能短暂停顿，本轮不宣称零延迟。

`before_verified.json` / `after_verified.json` 使用相同原文、同一组编辑后字符身份及页面设置。两个资源场景的原始和编辑后页面 SVG、字形选择记录、快照 ID 和诊断数量完全一致。旧实现只存在隔离的 `baseline-src` 取证副本，没有在工作树中回滚代码。

自动恢复性能采用真实 `QEventLoop.exec()` 测量：后台总保存约 1.54 秒，期间界面继续处理事件。另保留 `after` / `after_idle` 两次循环 QTest.qWait 驱动的实验记录（总计 18.3 / 52.1 秒）；这种驱动方式会使 Python 后台任务等待 GIL，不作为原生应用保存耗时基准。两次日志均保留，没有隐藏。

## 验收与已知边界

- 针对性检查 **72 passed**。新增测试覆盖完整输入一致时复用、实际字体成员损坏、元数据变化、非法数学轴、替换几何失效，以及后台保存时继续输入、最新版本补存、外部冲突和旧会话结果隔离。
- 最终完整相关回归 **319 passed，0 skipped**，102.76 秒。包括原有采集、重录、确认复用、字体发布、数学轴、公式、排版、保存恢复、缓存和分页连续性。Ruff 通过。
- 初始受限运行被沙箱的临时目录或硬链接权限阻止；使用项目私有临时目录并在授权的普通本地环境重跑。一次完整检查因较长测试目录触发 Windows 路径长度限制，导致采集重录备份失败；隔离确认后改用较短的 `artifacts/qa12`，最终全部通过。失败与中断日志保留，本次没有借机修改采集备份实现或降低测试检查。
- Windows 应用与 `InkStructTool.exe` 均构建成功，PE 架构 x64，版本 0.1.12。包内真实 scx 11 字集合的 v6.1 exp、v4 adaptive 两条流程通过；已录运算符制作字体、公式冻结重开与 SVG 导出通过。来源缺口提示保留，没有重跑全库生成。
- 原生 0.1.12 窗口在独立 `workspaces/windows-preview-0.1.12` 中打开验收副本，完成第 6 页预览、末尾输入 `12345`、撤销并另存。另存的源码与原始输入一致；独立加载重排后，全部页面 SVG 与优化前一致。证据：`native-preview.png`、`native-preview.inkdoc`、`final-verification.json`。
- 当前文稿的 301 条诊断保留，包括 27 处字符缺失、未支持公式及校准提示。性能更新没有扩充公式语法，也不自动替换字形。
- 实体数位板、驱动、写字机及纸面效果未在本轮验证。README、应用使用说明和 LaTeX 手册源码已同步；缺少 XeLaTeX/latexmk，新版手册 PDF 未重编译，历史 PDF 保留。

## 交付与保留

应用目录：`artifacts/windows_build_0.1.12_20261018/dist/InkStruct/`，必须保留 `_internal`。

发布包：`artifacts/windows_release_0.1.12/InkStruct-0.1.12-Windows-x64.zip`，SHA-256：

`30f9cf953c10144d2557d72dbbc84de8e993bd894a5ae9aebffb9f9da88718a1`

同目录提供使用说明、ZIP CRC 及全部发布文件校验记录。测试、性能原始数据、命令、构建和验收产物在 `artifacts/preview_performance_0.1.12_20261018/`；最终构建来源哈希全部匹配。

可继续使用既有 `20261018 数学轴修复` 字体，不需要重新制作字体或补录。其 SHA-256 仍为 `b114b9db538610176eaf4ca7ca6f5f177fd0319817599433dec274c50061c9c3`。原始自动恢复文件哈希未变；任务、样本、档案、生成、评价及历史应用均保留。

项目根目录 PowerShell 准确命令：

```powershell
# 日常使用原 Windows 工作区；独立验收工作区不替代原采集任务。
& 'artifacts/windows_build_0.1.12_20261018/dist/InkStruct/InkStruct.exe' --workspace workspaces/windows-0.1.8 --font artifacts/user_001_full_font_20261018_math_axis/user_001-v61-full-symbols-20261018.inkfont
.venv/Scripts/python.exe artifacts/preview_performance_0.1.12_20261018/run_logged.py regression_repeat .venv/Scripts/python.exe artifacts/preview_performance_0.1.12_20261018/run_regression.py
.venv/Scripts/python.exe -X utf8 artifacts/preview_performance_0.1.12_20261018/benchmark.py after_repeat
# 后续构建必须选全新目录，正式交付新构建先递增 APP_VERSION。
.venv/Scripts/python.exe packaging/build_inkstruct_app.py --output artifacts/windows_rebuild_0.1.12_new
```

可交付本次性能更新。清理仅涉及本轮可重建测试目录、私有临时缓存和 PyInstaller work/cache；源码、取证基线、原始数据、日志、验收项目和发布包保留。清理清单在性能验收目录 `cleanup.json`。
