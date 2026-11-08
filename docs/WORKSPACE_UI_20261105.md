# 主窗口导航与界面规范扩展试点

2026-11-05。项目：`C:/Users/lee/Documents/InkStructApp/InkStruct-Windows-Dev`。以本轮开工的完整未提交工作树为基线，APP_VERSION 保持 0.1.46。本轮是可运行源码试点，没有制作应用构建或新发布包。

## 按附件落地的组织

- 顶部常驻 InkStruct、应用版本及带线形齿轮的“设置”。原设置回调和 Ctrl+, 保留。点击品牌可打开原“关于 InkStruct”，主窗口不再重复显示“关于”菜单栏。
- 左侧常驻“采集、生成、排版”，底部以分隔线放置“字体库”；右侧直接容纳原功能页。字体库内继续提供“字体／模板”子页，不丢失模板入口。
- 导航配文字与同一线宽的自绘矢量图标，支持 Alt+1/2/3/4；选中状态与原模块索引双向同步。原 `tabs` 仍负责持有原页面和 currentIndex API，因此设置跳转、生成结果带入制包、资源应用返回排版等流程沿用。
- 保留浅色界面。图标不依赖系统 emoji 或网络资源；主操作使用白色图标，普通操作使用深灰图标，文字保留。对原 QToolButton 显式保留“粘贴”文字。

## 各页范围

- 采集：新增标题、浅灰书写者／任务分区，以及导入、撤销、保存图标。书写者选择、导入确认、暂停取消、重录、笔画检查和边界检查沿用。没有变更采样点、压力、时间、数据协议或输入事件。
- 实测发现隐藏的符号页会参与 QStackedLayout 最小高度计算，把汉字页撑高。隔离测量中，1360×900 时多出 148 逻辑像素滚动；仅让非当前采集子页忽略高度提示后，汉字页滚动范围为 0，保存按钮在视口内。当前页仍保留全部最小尺寸，符号页与窄窗口的真实溢出由原滚动区处理。画布按可用空间自适应，最小尺寸和原点列均不缩放重写。
- 生成：保留“准备作者样本→生成汉字→生成结果”及所有参数，统一边距、分区标题、辅助信息层级和关键按钮图标。未运行生成或修改生成核心。
- 排版：保留源码／并排／预览、菜单、快捷键、连续预览、问题及属性栏；统一标题、属性栏边界与导出／粘贴入口。没有添加重复打开、保存或撤销按钮，也未改变文档布局计算。
- 字体库：保留已认可的精简列表、真实字形预览、试写草稿和全部来源／验证提示。
- 模板：沿用原管理工作流，统一侧栏及详情样式；空库改为新建／导入引导，隐藏无内容的布局选择与预览。真实选中资源读取失败仍显示原错误并禁用应用，没有把错误当作可用模板。

没有引入新框架、依赖、文档状态或协议。界面组装集中在新文件 `src/inkstruct/app_shell.py`；既有文件只改 `application.py`、`capture_workflow_ui.py`、`editor/template_library.py`；新增 `tests/test_app_shell_qt.py`。

## 验证

最终 **62 项通过，0 失败，0 跳过，120.10 秒**，覆盖 15 个相关测试文件；Ruff 通过。新增 3 个 DPI 用例在 100%、150%、200% 下覆盖两种窗口尺寸、鼠标与快捷键导航、程序跳转同步、固定设置位置、制包带入、模板空库与真实错误、当前采集页高度及真实溢出。既有用例覆盖采集生命周期、书写者保护、生成字集、字体导入与管理、设置取消／应用、原生坐标退役、工作区模式和保存语义。

中途一次完整运行有 1 项采集生命周期用例超时（60 秒），其余 61 项通过；另一次早期运行 59 项通过。保留失败原样日志，不相加为累计通过数。该采集程序随后两次隔离重放均退出 0，最终完整回归 62 项通过；未确定这次偶发超时的根因，不能声称已修复该超时，也没有增加超时预算或删减断言。诊断路径为 `capture-debug*.log`、原程序和临时任务目录。

真实旧文档专项使用原 `artifacts/integration_0.1.41_20261026/real-font-check/real-math.inkdoc` 与真实 user_001 字体。切换新导航、浏览字体和公式、筛选、保存重开后：**2 页、23 处冻结选样、源码身份保持，严格 SVG 逐页字节相同**；6 条数学未校准提醒保持，原字体和文档 SHA256 不变。结果位于 `artifacts/workspace_ui_20261105/real-document-final/result.json`。

## 原生 Windows 观察

使用 computer-use 技能检查真实 Qt Windows 源码窗口，逻辑 DPI 96、DPR 1.5；窗口分别为 1360×900 与 1000×720。设置、恢复、字体库、采集根目录全部隔离，真实小字体仅复制到私有库。

实际操作已确认：鼠标切换导航；Alt+2/3/4；采集、生成、排版、字体及模板入口；齿轮打开原设置并取消；窄窗口采集页滚动到保存按钮；窄窗口生成、排版与字体库的主要控件可达。导航和设置不随页面滚动。正常窗口中汉字采集保存按钮可见；窄窗口不强行压缩全部内容，保留滚动。采集无实体板输入，不把按钮可达冒充数位板实测。

在两种原生尺寸的 5 份页面记录中，真实旧文档均保持 2 页和 23 处冻结选择，源码身份一致。`native-preservation.json` 与 `native-compact-preservation.json` 保存比较。这里不是原生保存／SVG点击测试；该部分由独立真实文档专项完成。

最终截图：

- `artifacts/workspace_ui_20261105/native-final-04/01-capture.png`
- `artifacts/workspace_ui_20261105/native-final-04/02-generation.png`
- `artifacts/workspace_ui_20261105/native-final-04/03-layout.png`
- `artifacts/workspace_ui_20261105/native-final-04/04-library.png`
- `artifacts/workspace_ui_20261105/native-final-04/05-templates.png`
- 窄窗口 `artifacts/workspace_ui_20261105/native-compact/01-capture-top.png` 至 `05-library.png`；`02-capture-bottom.png` 显示滚动后的保存按钮。
- 开工采集页对照 `artifacts/workspace_ui_20261105/native-before/00-capture.png`。

辅助脚本曾使用无效编码名 `utf8-sig` 导致记录计时器异常；改为 `utf-8-sig` 并在新目录重启，旧日志保留。基线脚本最初未显式设置 QApplication 版本，记录中 version 取到 Python 元数据；真实应用基线以开工源码 APP_VERSION 0.1.46 为准，后续脚本明确从它设置。一次 UIA 点击报告无法获取坐标，刷新状态后以可见坐标和快捷键完成。均未改生产数据或应用校验。

未验证：冻结 EXE、跨显示器 DPI、系统独立文本放大、完整读屏和全部 IME、真实数位板和写字机；只实际观察了原生 150% DPI，100%／200% 是 Qt 自动测试。没有性能对照，不宣称提速。模板本轮未重设计工作台，也未做全部模板编辑动作的原生验收。

## 保全与复现

开工 499 个既有源码／测试文件中，仅上述 3 个既有文件变化，其余 496 个相同，无缺失；另新增 app_shell 和对应测试。快照、Git 状态前后和 `source-preservation-final.json` 位于 `artifacts/workspace_ui_20261105`。原有字体库试点、研究、用户数据、字体和文档均保留；没有 reset、clean、提交、推送、覆盖交付包或修改独立排版开发目录。实验窗口均正常关闭。收尾仅清理本轮三个 test-support 目录中已列举核验的 sitecustomize 字节码及空缓存目录，保留测试私有任务、原始日志、源码快照、图片和 SVG。

最终执行命令（PowerShell，项目根目录）：

```powershell
.venv/Scripts/python.exe -B -X utf8 artifacts/workspace_ui_20261105/check_final_03.py
.venv/Scripts/python.exe -B -X utf8 artifacts/workspace_ui_20261105/real_document_check.py
.venv/Scripts/python.exe -B -X utf8 artifacts/workspace_ui_20261105/native.py
.venv/Scripts/python.exe -B -X utf8 artifacts/workspace_ui_20261105/native.py --compact
.venv/Scripts/python.exe -B -X utf8 -m ruff check src/inkstruct/app_shell.py src/inkstruct/application.py src/inkstruct/capture_workflow_ui.py src/inkstruct/editor/template_library.py tests/test_app_shell_qt.py
```

日志：`tests-final-03.log`、`tests-final-03.xml`、`real-document.log`、`native-final-04.log`、`native-compact.log`。辅助脚本使用一次性目录，复测须选新输出名称，不能覆盖本次产物。普通应用入口仍为 `.venv/Scripts/python.exe -B -X utf8 -m inkstruct.application --workspace <明确的开发工作区>`，该普通入口不会自动隔离全部应用设置；本轮验收使用上述隔离启动器。
