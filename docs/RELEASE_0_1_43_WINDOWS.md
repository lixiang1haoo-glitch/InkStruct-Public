# InkStruct 0.1.43 Windows 预览更新合并

2026-10-30。将 `InkStruct-Layout-Dev` 当前完整排版增量合入主项目，构建标准 **InkStruct 0.1.43 Windows x64**。APP_VERSION 唯一来源为 `src/inkstruct/fonts/__init__.py`；Python 库仍为0.2.0。README、使用说明、LaTeX手册源码和发布文件名同步。未重编译手册PDF，不把旧PDF当作本版手册。

## 合并内容

- 正文两端对齐，段尾与手动换行靠左，英文单词和公式内部不拉伸。新文档默认两端对齐，旧项目保留原参数。
- 中文自然书写v2：笔画/倾斜、大小、字距、基线四项强度与固定种子，默认关闭。旧v1效果保留，明确切换后才采用v2；字体、采集样本、冻结选样不改写。见[自然书写说明](LAYOUT_JUSTIFY_HAN_VARIATION.md)。
- 排版问题面板：按原因归并、筛选、逐处定位、中文建议和完整报告，重排时禁用过期定位。原始诊断保留。见[问题面板](LAYOUT_PROBLEMS.md)。
- 显式“强制导出SVG…”：仅输出当前冻结快照的已有有效笔迹，缺字/错误占位留空，附issues.txt、issues.json、plotter.json；不补画、不重排、不宣称完整文档合格。常规导出严格检查继续保留，页码、表格内容、缩放、定位点和路径优化仍有效。
- 应用正文/公式等全局默认时保留当前文档模板、纸张及旧绑定；只有明确修改对应项并勾选应用到本文时才替换。

此前独立0.1.43 Layout Preview ZIP是在自然书写v2及问题面板新增之前构建，本次按用户指定版本合并**目录当前源码**，包括这两项后续增量。旧预览ZIP、旧0.1.41主应用和独立开发目录保留。主应用ProductName为InkStruct，默认工作区/设置沿用标准位置，不切换为preview-data；独立预览包是另外的隔离运行入口。

## 合并与保全依据

主目录 `C:/Users/lee/Documents/InkStructApp/InkStruct-Windows-Dev`，输入目录 `C:/Users/lee/Documents/InkStructApp/InkStruct-Layout-Dev`。Git HEAD为 `af45b45f04f899fcaced43aa980b0508673ee6c0`；输入是包含未提交修改的完整磁盘快照，没有从HEAD/bundle还原源码。

以上次0.1.41实际合入的incoming哈希为优先基线，其余沿用独立目录复制清单，识别51项增量。41项无内容冲突先逐字节核对再复制，10项文档/测试入口冲突人工合并，保留主项目标准产品说明、原有历史记录及私有QSettings/采集设置隔离。两个新增Qt测试的独立启动器调用适配到主项目私有入口，断言不减少。标准冻结自检复用新增功能检查，构建清单同时包含该检查脚本，默认应用启动方式不改。

合并前完整src压缩快照、逐文件原字节、两侧哈希、补丁和Git状态在 `artifacts/integration_0.1.43_20261030/`。研究目录1302个文件哈希保持；生成核心及其共享几何/档案/结构库代码未随预览增量修改。旧研究的应用/排版依赖身份仍属旧环境，可用合并前src快照显式复现；不将其历史结果冒充新版本研究验收。

外部目录Git状态返回“must be run in a work tree”，未假称其工作树干净；合并依据实际文件、复制清单和上次合并哈希。未写外部目录，不覆盖Windows工作区或用户资料，不执行reset、clean、提交或推送。

## 本机测试与构建

Windows x64、Python3.13.16、NumPy2.5.4、PySide6 6.9.2、Matplotlib3.11.2、PyInstaller6.22.3、pytest9.1.1，沿用项目.venv，无新依赖，不安装训练环境。

1. **主项目1478项回归通过，0失败、0错误、0跳过**，101个测试文件，pytest261.64秒。包含自然书写、两端对齐、问题面板、强制SVG、模板保留，以及既有字体、源码身份/冻结选样、模板/字段/续排、公式、脚注、采集、生成与多进程/后台导出。日志 `regression-01-logs`、JUnit `regression-01.xml`。这是本次主项目实测，未借用独立目录1501项历史记录。
2. **已有真实user_001字体与旧文档**：字体215字符/1207候选/102559点，原字体SHA `94d87fb5f47c53725f73a4bdbe324301aa8337a9159723338156f28dbfe54f74`。旧0.1.41项目未隐式启用对齐/自然书写，重开导出SVG与历史0.1.41**字节一致**。两端对齐、自然v2、v2高强度与旧v1四组均两页，保存重开后完整快照、源码身份、冻结选样和严格SVG一致。含缺字的小样常规导出继续阻断，显式强制导出保留页码/表格筛选/132.293%缩放/定位点并生成问题报告。原字体与旧项目哈希不变，诊断保留。产物 `real-font-check`，外层10.23秒。
3. **Windows标准构建通过**，52.74秒，`layout_preview=false`，构建期间源哈希不变。InkStruct.exe与InkStructTool.exe均AMD64、FileVersion/ProductVersion0.1.43、ProductName InkStruct；见 `exe-versions.json` 和构建 `build-provenance.json`。
4. **两份EXE实际冻结自检通过**：后台多页/进程导出、缓存、取消和模拟工作进程故障后的串行回退；同时运行新增两端对齐、自然书写种子/重开、模板保留/显式替换、强制SVG实际GUI处理器、缺口报告、选样不变与常规导出仍阻断的检查。均无notices错误。Tool14.16秒、GUI EXE11.12秒。产物 `frozen-tool-check`、`frozen-app-check`。这些是offscreen自动Qt检查，不是人工原生焦点或写字机验收。
5. computer-use查看了**源码原生Windows窗口**：1350×900、96 DPI、四模块、真实字体两页连续预览、统一设置、两端对齐及自然书写四项控件可见；取消设置返回文稿。可访问性焦点两次仍报告页码控件，因此没有注入文字，不宣称完成中文粘贴/IME/键盘撤销验收。弹窗索引取消不可用后用Escape成功返回；最后窗口按计时关闭，旧句柄未重用。见 `computer-use-observations.json`、`native-check`。

原生验收辅助日志器读取了不存在的IssueGroup.code，导致周期事件采集失败；该脚本错误和stderr完整保留，未算作应用功能通过。窗口实际查看、最终截图与源文档未改的记录仍保留；不能把辅助进程exit0解读为全部原生输入验收通过。

未验证：实体数位板/驱动、写字机纸面、中文输入法组合输入、冻结应用人工原生交互、全部字体/模板人工视觉质量及性能收益。自然书写为实验选项，不是新的生成方法；v7研究没有接入本次默认应用或正式发布。没有重跑全库汉字生成。

## 使用、日志与复现

完整解压 `InkStruct-0.1.43-Windows-x64.zip`，保留_internal和InkStructTool.exe，双击InkStruct.exe。已有默认工作区位置不改，历史字体/文档不自动更新，不附用户历史数据。源码也可继续开发：

```powershell
.venv/Scripts/python.exe -B -X utf8 -m inkstruct.application --workspace workspaces/windows-0.1.43-NEW
.venv/Scripts/python.exe -B -X utf8 scripts/run_layout_regression.py --junitxml=artifacts/regression-0.1.43-NEW.xml --basetemp=artifacts/pytest-0.1.43-NEW
.venv/Scripts/python.exe -B -X utf8 packaging/build_inkstruct_app.py --output artifacts/windows_build_0.1.43-NEW
artifacts/windows_build_0.1.43_20261030/dist/InkStruct/InkStructTool.exe --inkstruct-check --output artifacts/check-0.1.43-NEW --font artifacts/charsets_0.1.40_20261022/font-validation/user_001-v62-generation-0.1.40-validation.inkfont --samples artifacts/empty-samples-NEW --export-only
```

所有NEW输出应尚不存在，原子字体发布与Qt伴随进程需要正常Windows权限；本次使用私有TEMP/设置运行，不修改校验来绕过沙箱限制。`--export-only`不读取samples，参数仅满足既有自检CLI必填要求；可额外将INKSTRUCT_LAYOUT_PREVIEW_HOME设为新验收私有目录以隔离恢复文件。真实字体与原生脚本位于本轮验收目录，固定输出保护拒绝覆盖，复现先复制并改用新输出位置。

可运行目录：`artifacts/windows_build_0.1.43_20261030/dist/InkStruct/`。发布包与SHA位于 `artifacts/windows_release_0.1.43/`；归档CRC、解压完整性、解压后Tool运行与用户/研究保全结果见同目录 `delivery-verification.json`。完整日志和验收产物位于 `artifacts/integration_0.1.43_20261030/`，清理只针对本轮明确可重建的pytest临时目录及PyInstaller work/cache，保留源码、原数据、日志、验收和交付产物。
