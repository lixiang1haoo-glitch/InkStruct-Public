# 编辑器独立应用

2026-10-14。已构建 macOS Apple Silicon 的 `InkStructEditor.app`，内含 Python、Qt 和排版依赖，使用时不要求预装 Python。应用声明最低 macOS 14；本次在 macOS 27.0.1 arm64 上验证，旧系统兼容性尚需实机检查。当前为本机测试版本，使用 ad-hoc 签名，未做 Developer ID 签名、公证或公开发布。

当前最新版本为 [自动上下标与统一设置版](MATH_GRAPHICAL_SETTINGS.md)：`artifacts/math_auto_scripts_20261014/InkStructEditor-macos-arm64-auto-scripts.zip`。包含此前系统焦点修复；下方旧包记录按历史版本保留。

## 使用与边界

解压 `InkStructEditor-macos-arm64-auto-scripts.zip`，将完整 `.app` 放到自己的应用或测试目录，打开后在界面导入源码/项目。不要单独拷贝包内某个可执行文件。若系统拒绝运行此未公证版本，应按本机安全策略处理；这里不提供关闭系统保护的做法。

应用不附个人字形和项目。内置数字可检查基础正文、表格和受控公式；汉字及其他样本需要自己的资源或包含内嵌资源的 `.inkdoc`。源码版、离线 wheel 材料和独立应用并存，早期离线包不会因为本次构建自动升级。

此前预览更新版为 `artifacts/editor_app_preview_20261014/InkStructEditor-macos-arm64-preview-update.zip`，已包含顶部控件自动换行、模板绑定前置提示、编辑时提前取消旧计算和首次预览加载优化。早期 response-update、ui-update 与初版包保留为历史快照；wheel 离线材料未自动更新。

独立应用的自动恢复副本使用 Qt 用户数据目录下的 `InkStruct/editor_recovery`。macOS 为 `~/Library/Application Support/InkStruct/editor_recovery`，每个会话仍使用独立文件，外部修改检查保持。源码/Python 安装版保留工作目录 `artifacts/editor_recovery`；旧恢复文件不自动搬迁，可通过“打开恢复副本…”手动选择。

## 包内工作程序

桌面主程序是 `Contents/MacOS/InkStructEditor`；配套 `InkStructTool` 是具有标准输入输出的工作程序。PDF 导入只调用同目录的此程序，不查找系统 Python 或 PATH；缺失时明确提示重新解压。原先 Python 运行方式继续使用模块入口。

可从包内工具执行文档命令或验证：

```sh
InkStructEditor.app/Contents/MacOS/InkStructTool --inkstruct-cli document render input.inkdoc --plotter --output new-output
QT_QPA_PLATFORM=offscreen InkStructEditor.app/Contents/MacOS/InkStructTool --inkstruct-check --output new-check
```

此工具只开放 `document` CLI；不宣称打包了训练等其他功能。检查包含实际混排窗口构建、原生保存重开和优化 SVG 字节一致、PDF 子进程。应用包内带有依赖元数据和许可证。仅这批固定负载通过，不代表任意复杂项目、Windows 或设备试写完成。

## 构建

使用目标平台的 Python 环境，安装桌面依赖和 PyInstaller 6.22.3、pyinstaller-hooks-contrib 2026.8，然后执行：

```sh
python packaging/build_editor_app.py --output artifacts/new-editor-build
```

脚本要求新的构建目录，缓存保存在目录内部，不清理系统 PyInstaller 缓存。构建前后核对源码哈希，记录实际 Python/工具/依赖版本；若构建期间源码变化，则拒绝将产物标为冻结构建。`.spec` 生成 GUI 主程序和 console 工作程序，二者共享同一依赖集合；macOS 使用 app bundle。组织方式依据 [PyInstaller 官方 spec 文档](https://pyinstaller.org/en/stable/spec-files.html)，实际可运行性以本机产物验证为准。

Windows 分支仅准备了同平台构建入口和 `.exe` 配套程序路径规则，尚未实际构建 Windows 独立包；不能把 macOS 构建或此前 Windows wheel 解析称为 Windows 运行通过。

## 本次证据

`artifacts/editor_app_20261014/final-build/` 保存源码/版本来源与最终应用；根目录 ZIP 是最终可拷贝产物。最终应用、含中文空格路径下解压的副本均完成内置检查；真实 user_001 项目机器 SVG 与冻结旧结果逐字节相同。原生 macOS 窗口已实际粘贴数字/表格/分式源码并查看预览，使用系统保存对话框保存测试项目；这一检查发现并修复了从桌面启动时恢复副本写入只读工作目录的问题，修复后在用户数据目录读回了有效副本。

Shell 沙箱不能连接原生显示服务，因此原生窗口通过桌面自动化入口启动检查，离屏检查使用包内工具。原生粘贴不等于中文输入法组合事件验收；屏幕缩放、字体缺失、更多对话框与 Windows 仍需按原计划分别测试。纸面校准和写字机实写没有完成。

## 2026-10-14：界面修复更新版

新版 ZIP 为 54,294,926 字节，SHA-256 `49449615802c9b7557a5bb42aa480eaac84efed4692c744573cd03148359c80c`。构建前后全部跟踪源码哈希一致。包内检查现在实际操作 1000 × 700 窗口、四档缩放、模板源码块选择/绑定/清除，防止只验证布局内核而漏掉旧界面。原包与中文空格路径下解压副本均通过该检查，以及项目往返 SVG 一致和 PDF 子进程验证；记录的模块路径确实来自对应应用内部。

退出旧测试应用后，实际打开解压后的新版，在 macOS 原生窗口输入数字和表格，预览为 1 页、12 实例，已查看截图。真实 user_001 项目由新版工具导出，优化 SVG 与原冻结文件逐字节一致。源码全量回归 `1444 passed, 4 skipped in 95.41s`。原包与解压副本的 ad-hoc 签名完整性检查通过，仍未做 Developer ID 签名、公证、Windows 或设备实写验收。完整记录在 `artifacts/editor_app_refresh_20261014/verification.json`；先前所有证据和包均保留。

## 源码后续修复提示（2026-10-14）

`editor_app_refresh_20261014` 冻结包之后，源码新增“普通编辑/输入法正式提交在源码映射前取消旧计算”的响应改进，现已进入下述 response-update 包；旧 ui-update ZIP 不包含此修复。原生 Cocoa 性能证据见 [性能记录](MARKDOWN_PERFORMANCE.md)，其计时来自源码运行时，不作为冻结应用的独立计时成绩。

## 2026-10-14：编辑响应更新版

最新 ZIP 为 **54,297,119 字节**，SHA-256 `2be2e1dd81b73723e2bf3b8717317251380b22094694b98226069ef2d7bc1edb`，位于 `artifacts/editor_app_responsive_20261014/`。`final-build/` 为格式整理后的最终构建，`build/` 是保留的初次构建，交付 ZIP 仅来自 final-build。构建前后源码快照一致；原包与中文空格目录下解压副本均通过 ad-hoc 签名完整性核验。

增强包内自检实际验证普通编辑和 IME 提交在身份映射前取消旧任务、IME 预编辑不修改身份、撤销恢复源身份与页面几何；自检不写用户恢复目录。同时保留 1000 × 700、缩放、模板绑定、项目往返机器 SVG 和 PDF 子进程检查。原包及解压副本均通过，模块来源确实位于对应 `.app`。另在解压应用原生窗口粘贴数字/表格/分式，操作撤销和重做并查看截图，最终 1 页、14 实例，只有预期的未人工标定提示；这不等于真实中文输入法验收。

解压副本导出的真实 user_001 模板项目 SVG 与冻结基准逐字节一致，含 20 个 path，仅 M/L，无 transform。对应 SVG SHA-256 为 `3f95306397f21259be9609f771b484d6dde9e50dc8fe1325ffe479b546f5a649`。本轮 16 项相关回归及修改文件 Ruff/格式检查通过。包内产品源码与上一轮全量 1445 passed / 2 skipped 及 Cocoa 测量版本逐项相同，因此没有重复全量运行；本轮另改的是包内自检。两个并行变化的 v61 实验模块不在 PyInstaller 实际模块清单中，未纳入此应用，也未修改这些文件。

完整证据为 `verification.json`、`bundled-source-parity.json`、`bundle-smoke/`、`unzipped-smoke/` 和 `real-machine/`。仍是 macOS 本机测试应用；Windows、可见帧延迟、人工字形标定和设备试写分别保留待验，不将打包成功记为整体目标完成。

## 2026-10-14：首次预览加载更新版

当前 ZIP 大小 **54,297,479 字节**，SHA-256 `6f978c448b408d0bb8210e4670362f6a3c92ee2cb17ef5b4d6d64eb948150b28`，位于 `artifacts/editor_app_preview_20261014/`。减少坐标格式化开销和同一页面键的重复哈希，完整内容判等、六位小数精度及全部校验保留。对应源码的 Cocoa/Fusion 实样首次翻页测量见 [性能记录](MARKDOWN_PERFORMANCE.md)。

构建前后源码哈希一致，包内模块清单与当前对应源码相符；原包、中文空格路径下解压副本均通过增强自检及 ad-hoc 签名完整性检查。四页真实 M5 项目由包内工具导出的优化 SVG 与原基准逐字节相等，并核对仅 path 与 M/L、无 transform。全量回归 1453 passed / 4 skipped，普通及调试预览 108 份 SVG 保持原字节。完整证据为根目录 `verification.json`、`build/`、两组 smoke 和 `mixed-machine/`。

本轮没有再次手动操作新包原生窗口，原生性能来自对应源码运行时；此前 response-update 的人工操作记录仍按其原版本保留。未进行 Developer ID/公证、Windows 或纸面设备验收，仍为本机测试交付。没有改变用户确认的排版默认尺寸或优化自动反转策略。


## 2026-10-14：公式设置重设计版

依据用户提供的 AxMath 设置界面，将 11 类公式参数放在对应结构图旁，箭头与焦点高亮建立尺寸对应关系；实际笔迹预览单独位于下方。提供单项恢复、分类恢复、预置试排公式、分类输入保留及小窗口滚动。排版内核、样本与默认值不变。

最新 ZIP 大小 54,337,214 字节，SHA-256 `2fff77e0e49dfcf5567b65ee785886a4e1a86fb57adcf9c34ac6494c6862dcd7`。源码全量回归 1482 passed、4 skipped；构建哈希一致、新模块确实入包，原包与解压包签名检查通过，解压包内自检通过。11 类离屏截图及 960 × 700 布局已检查。新版原生窗口启动被自动审批拦截，需用户确认后再检查；不得将离屏结果表述为原生操作验收。证据位于 `artifacts/math_settings_redesign_20261014/verification.json`。

用户手册同步更新为 38 页，包含新版操作流程和实际字形截图；LaTeX 编译与修改页视觉检查通过。Windows 与设备实写仍未验证。

## 2026-10-14：公式设置紧凑版

按后续反馈取消大参数卡片与长引线，公式示意和控件固定比例居中，紧凑输入框靠近尺寸，解释和估算移至 i 提示。19 项针对性回归、11 类离屏视觉检查、构建源码一致性、签名核验及解压包自检通过；未重跑上一版全量回归，也未重试被审批拦截的原生窗口启动。交付包与完整证据位于 `artifacts/math_settings_compact_20261014/`。手册已同步更新。

## 2026-10-14：公式实时预览修正

有效键入触发预览、固定倍率防止自动适配抵消尺寸变化、超范围输入明确诊断，示意字形改为正体。20 项相关回归及解压包自检、签名、构建源码一致性通过，未再次启动原生窗口。`artifacts/math_settings_live_20261014/verification.json` 与同目录键入截图保存证据。手册同步更新。

## 2026-10-14：独立上下限字号、自动避让与统一设置

新增大运算符上下限独立比例，普通上下标使用轨迹边界和笔宽自动留白，主工具栏合并为“设置”。1521 passed、4 skipped，全量回归通过；构建哈希一致、原包与解压包签名及解压包自检通过，真实 user_001 样本生成严格 path/M/L SVG，样本 ZIP 不变。证据与交付包位于 `artifacts/math_auto_scripts_20261014/`。旧项目兼容读取，但普通上下标按新规则重排；未重试原生窗口启动，未进行设备实写。
