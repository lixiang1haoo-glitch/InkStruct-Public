# 字体库界面试点：2026-11-05

基于当前包含未提交修改的完整源码，APP_VERSION 保持 0.1.46。本轮为源码试点，不制作发布包，不改模板页、设置页、生成、排版或字体协议，不写入全局 Codex 配置、不增加依赖。

## 实际改动

仅修改 `src/inkstruct/fonts/ui.py` 与 `src/inkstruct/fonts/management_ui.py`，新增 `tests/test_font_library_pilot_qt.py`。

- 保留标题、导入／制作、搜索筛选、列表和详情、所选字体操作的原工作流。空选择突出导入，选中可用字体后突出“用于当前文档”；制作、默认设置、导出及完整验证仍是独立操作。
- 空库、筛选无结果、未选择和资源不可读取分别使用简明说明。没有选择时不显示无效试写和详情页，不把无结果写成损坏。
- 显示当前筛选项数；长字体名称换行，不依赖列表横向滚动才能读完。
- 在切换、清空和失效时清理两处笔迹预览、字符和样本说明、版本及文件信息。停止旧防抖并递增现有 epoch；旧预览成功和失败结果均不能回填新选择。
- 使用已有 `inkRole`，不修改全局主题。补充控件可访问名称和局部 Tab 顺序，保留原参数滚轮保护。

没有另建状态框架，没有修改完整校验、适配确认、撤销、字体核心、候选身份或冻结选样逻辑。主字体库与字体选择弹窗继续复用同一浏览器，选择弹窗隐藏的制作／默认／其他动作仍保持隐藏。

## 测试

最终运行 **30 项通过，0 失败，0 跳过，43.12 秒**：12 项新用例及18项既有用例。覆盖100%、150%、200%离屏缩放，空库／无结果／失效／迟到结果、焦点顺序、选择弹窗取消，以及既有字体应用取消／资源变化／默认和本文区分／撤销／保存重开／严格 SVG。两次测试运行有重复，不能相加为60项。Ruff检查通过。

另使用真实旧文件 `artifacts/integration_0.1.41_20261026/real-font-check/real-math.inkdoc`，在私有工作区导入真实 user_001 字体并浏览／筛选：2页、23处冻结选样、源码身份不变；保存重开后严格SVG逐页字节相同，6项数学未校准提醒原样保留。原文档及字体SHA-256不变。详见 `artifacts/font_library_pilot_20261105/real-document-02/result.json`。

## 原生 Windows 观察

使用 computer-use 技能和真实 Windows Qt 平台，QSettings、采集设置、恢复目录及字体库均隔离到本轮 artifacts。修改前模块来自本轮开工源码ZIP；修改后来自当前源码。是源码应用的原生验收，不冒称冻结EXE验收。

- 同一字体、1360×900逻辑尺寸、DPR1.5、96逻辑DPI，修改前后分别通过原生文件框导入，原完整校验通过：215字／1207候选，2份来源提示保留，三份私有副本与原包SHA-256一致。
- 修改后实际操作搜索中文、无结果、清空筛选、重新选择、字符查找及A的样本1/10→2/10；看见对应候选身份和独立录制来源。搜索Tab转书写者、Shift+Tab返回搜索的可见焦点通过。
- 另启动1000×720逻辑尺寸的同版窗口，实际查看标题、筛选、换行名称、预览及操作栏可达，没有内容遮挡。此窗口只复制同一字体以观察布局，因此正确显示“索引可读取 · 完整验证未运行”，不沿用其他窗口的验证标记。
- 两窗口的原生源文档为空，浏览前后仍为空且冻结选择为空；保存重开与SVG的真实旧文档验证另在上述专项检查完成，不能混称为原生导出操作。

截图：

- 修改前空库：`artifacts/font_library_pilot_20261105/native-before/00-empty.png`
- 修改后空库：`artifacts/font_library_pilot_20261105/native-after/00-empty.png`
- 修改前／后选中字：两目录各自的 `01-selected.png`
- 修改后无结果：`native-after/02-no-results.png`
- 字符／样本：`native-after/05-character-A.png`、`06-next-sample.png`
- 窄窗口：`native-compact/01-compact-ready.png`

未验证：跨显示器DPI切换、Windows独立文本大小、完整读屏和全部键盘路径、真实数位板、写字机、冻结EXE。未做大字体导入性能对照，本轮不声称提速。模板空库现有不当错误文案按范围留到后续处理。

## 失败记录与保全

首次真实文档辅助脚本已完成几何／选样比较，但在末尾对字符串调用要求Path的SHA函数时失败；异常退出还产生预览QProcess清理警告。仅修正辅助脚本的路径类型及关闭处理，在新的 `real-document-02` 完成复测，原脚本、日志和产物保留。未改预览实现。中间一次PowerShell转义导致辅助脚本修改命令语法失败，未改应用或数据。

原生文件框一次UIA索引过期；刷新截图后改用可见文件名区域和快捷键完成。辅助功能焦点文本偶有滞后，以可见焦点和私有进程实际控件记录核对。尝试拖动／系统菜单缩窗没有得到实际尺寸变化，未据此声称通过；窄窗口证据来自随后独立启动并实际观测到的1000×720窗口。

开工499个既有源码／测试文件中，只有上述2个字体界面文件变化，其余497个不变。原始Git状态、源码ZIP、测试、失败日志、截图及SHA核对位于 `artifacts/font_library_pilot_20261105`。没有执行reset、clean、提交或推送，没有改动独立排版目录或生产工作区；旧任务、样本、字体和文档未迁移或改写。

## 准确命令

本轮已执行（输出目录已存在，不要直接覆盖重跑）：

```powershell
.venv/Scripts/python.exe -B -X utf8 artifacts/font_library_pilot_20261105/check_final.py
.venv/Scripts/python.exe -B -X utf8 -m ruff check src/inkstruct/fonts/ui.py src/inkstruct/fonts/management_ui.py tests/test_font_library_pilot_qt.py
.venv/Scripts/python.exe -B -X utf8 artifacts/font_library_pilot_20261105/real_document_check.py
.venv/Scripts/python.exe -B -X utf8 artifacts/font_library_pilot_20261105/native.py --baseline
.venv/Scripts/python.exe -B -X utf8 artifacts/font_library_pilot_20261105/native.py
.venv/Scripts/python.exe -B -X utf8 artifacts/font_library_pilot_20261105/native.py --compact
```

复测时为辅助脚本选择新的BASE／OUT／私有设置与测试临时目录；脚本会拒绝复用现有输出。普通开发入口仍为 `.venv/Scripts/python.exe -B -X utf8 -m inkstruct.application --workspace <明确的开发工作区>`；普通入口的应用设置并不自动隔离，本轮原生试点使用的是上述私有启动器。

结论：保留此最小试点，等待用户评价展示效果；不自动扩展到模板或其他页面，不作为正式新版交付。
