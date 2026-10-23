# InkStruct 0.1.35 Windows：字体与模板管理

本次实现统一资源库、当前文档资源入口与新文档默认设置的分工。应用版本由 `src/inkstruct/fonts/__init__.py` 的 APP_VERSION 读取；字体格式、模板 v1/v2/v3、项目协议与 Python 库版本均未递增。

## 最终交互

- 主窗口四个标签为“采集 / 生成 / 字体与模板 / 排版”。资源管理内部为“字体 / 模板”，单击预览，双击查看详情，不直接应用。
- 字体库支持搜索、书写者筛选、历史版本、真实笔迹试写、逐字分类和多份样本、来源与版本、文件详情。缺字使用红框；合成/复用与独立录制分别说明。版本按相同 font_id 关联，不根据字体名称推断继承关系；文件时间仅用于展示最近项，不自动升级文档。
- “用于当前文档…”后台完整验证并试排，显示页数、诊断、来源及冻结选样保留/重新选择数量。存在影响时须勾选确认；取消保持文档不变，资源或文档变化则拒绝过期结果。兼容的核心记录、度量和来源完全相同才保留冻结样本；改变后的资源可通过编辑菜单撤销/重做。
- “设为新文档默认”不改变当前文档；字体导出可选用户版或保留原包类型的完整副本，使用新文件名。库内别名与移出/恢复只改管理记录，不改字体包，不删除文件。
- 模板库显示缩略图、全部布局、起始/循环顺序与字段声明，可按简单/自定义/旧版筛选。显式导入保存原文件的完整字节副本，含原有内嵌背景；外部文件移动不影响库内副本。外部文件更新后再次显式导入形成新条目，不修改旧条目或已保存文档。
- “编辑模板副本…”另存并入库；“用于当前文档…”先做真实适配确认；“设为新文档默认”单独操作。旧最近文件可明确加入，旧模板的显式迁移继续保留。
- 排版右侧“元素属性 → 文档资源”提供更换字体、编辑本文布局、更换模板、填写字段及适配报告。齿轮保留全局默认，模板管理只提供跳转按钮，不再隐藏本文布局编辑入口。

## 管理数据与兼容

管理信息独立于资源协议，位于当前工作区：

```text
fonts/management.json              inkstruct_font_management_v1
templates/catalog.json             inkstruct_template_catalog_v1
templates/items/<sha256>.json      原模板的不可变字节副本
```

字体摘要按文件身份与时间戳失效，在后台读取；完整验证状态与“索引可读取”区分。样本笔迹按需读取；模板缩略图在后台生成、按文件身份缓存。库写入使用文件锁和原子索引替换，损坏、未知索引不自动覆盖。模板读取核对完整内容哈希。新文档默认沿用原全局设置格式；`.inkdoc` 继续保存本份资源和冻结选样。不会自动扫描迁移外部模板，也不改写旧正文、绑定或字体。

## 测试与修复

本机 Windows/Python 3.13 x64 实测，项目环境和 Git 提交未更换。源码基点为 `af45b45f04f899fcaced43aa980b0508673ee6c0` 加既有未提交工作与本轮修改，不能把该提交视为完整交付源码。

- 相关回归：548 项通过，见 `corrected-regression.log/xml`。覆盖字体、模板、字段、文档、选样、字符校正、源身份、保存、撤销及 SVG。
- 最后显示比例修正及新增取消/资源变化用例：58 项通过，见 `preview-final-retest.log/xml`（包含重复回归，不相加为独立测试总数）。另有目录/取消测试 15 项通过。
- GUI 子进程覆盖 100%、150%、200% 缩放。旧测试中齿轮内“编辑当前文档布局”的预期改为新入口检查，原布局、字段和保存断言保留。
- 深目录下全哈希模板文件名触发 Windows MAX_PATH，已对内部长路径采用 Windows 扩展路径，不修改系统设置。对应失败与复测日志保留。
- 原生预验收发现 QSvgWidget 默认拉伸使窄高比区域中的笔迹变形；字体、模板及选择器预览现保持比例，并增加实际像素边界检查。
- 第一次真实小样过度比较了快照的任务/资源目录身份，已记录差异：冻结选样、页面和诊断相同，仅 snapshot_id/job_key/revision/resource_key 改变。随后比较全部页面、诊断、文档与设置，并单独逐页核对 SVG 字节；未放宽几何或导出检查。
- 测试隔离首次曾将一份测试模板写入默认模板目录。确认基线中该目录不存在、全部条目均为本轮测试后，备份并逐项移除本轮副本；随后 INI 设置范围自动使用私有工作区。证据为 `test-scope-repair.json` 和 `isolated-test-repair-backup.zip`。

真实字体使用历史已交付 user_001 字体的只读来源，在新工作区完整导入：9,778 字、10,770 份候选、8,377,832 点，来源提示候选 3,351 份仍保留。一次四进程导入耗时 17.799 秒，仅为本次校验耗时，不作为性能对比结论。四页小样包含命名字段、两张不同宽度的循环布局、正文、公式与表格；取消、字体应用/撤销/重做、保存重开后页面、诊断、源码、冻结选样及逐页严格 SVG 一致。模板原文件移动后仍可读取库内副本。

原生最终构建通过：真实笔迹与多样本浏览、模板缩略图与两张布局切换、字体影响取消/明确确认、撤销重做、本文布局工作台取消、齿轮跳转、保存重开及四页严格 SVG。455/455 处冻结选样保留，36 项校准提示继续显示；四个输出 SVG 与权威对照逐字节相同。首次保存的全部选样记录相同；随后明确点击来源警告的“继续使用”并保存后，仅 warning_accepted 从 false 改为 true，选样身份、度量与几何不变，诊断仍保留。该差异单独核对，见 `native-choices-trace.json` 和 `native-verification.json`。

最终包内自检完成 v6.2/v6.1/v4 的 scx 11 字流程、真实字体导入、冻结重开、输入/粘贴、严格路径输出，`notices=[]`。InkStruct.exe、InkStructTool.exe 的 FileVersion/ProductVersion 均为 0.1.35，PE 架构均为 x64。原生窗口无新增标准错误日志。原始失败日志也保留，不用历史结果替代本轮检查。

## 启动、测试与构建

在项目根目录执行 PowerShell 命令：

```powershell
.venv/Scripts/python.exe -B -X utf8 -m inkstruct.application --workspace workspaces/windows-resource-management-0.1.35
.venv/Scripts/python.exe -B -X utf8 artifacts/resource_management_0.1.35_20261021/run_tests.py --label new-check-01
.venv/Scripts/python.exe -B -X utf8 packaging/build_inkstruct_app.py --output artifacts/windows_build_0.1.36_new
```

测试标签、构建目录须换新，保留旧日志。上面的未来构建示例需先按 AGENTS 递增 APP_VERSION；本次实际构建命令为 `--output artifacts/windows_build_0.1.35_20261021_delivery`。

包内自检命令存于 `artifacts/resource_management_0.1.35_20261021/delivery-native/bundle-command.json`，使用 scx 11 字小集合，覆盖 v6.2、v6.1 和 v4，未重跑全库生成。

## 产物与边界

交付前逐项核对本轮基线中的 3,213 个既有用户文件，SHA-256 全部保持相同。Git HEAD 未改变，没有提交或推送。只清理本轮测试临时目录和构建 work/cache；保留源码快照、原始失败/通过日志、真实小样和全部交付产物。

- 交付 ZIP：`artifacts/windows_release_0.1.35/InkStruct-0.1.35-Windows-x64.zip`，须完整解压，保留 `_internal`。
- 可运行 EXE：`artifacts/windows_build_0.1.35_20261021_delivery/dist/InkStruct/InkStruct.exe`；同目录含 InkStructTool.exe。
- 原始记录：`artifacts/resource_management_0.1.35_20261021/`。
- 新验收工作区：`workspaces/windows-resource-management-0.1.35/`。
- 四页文档：`artifacts/resource_management_0.1.35_20261021/native-input.inkdoc`；权威 SVG 对照在 `strict-svg/`。
- 最终构建元数据与源码摘要：构建目录的 `build-provenance.json`；包内验证在 `artifacts/windows_bundle_check_0.1.35_20261021_delivery/verification.json`。

本轮不重建/升级用户字体，不自动修改旧模板与文档，不迁移采集任务。实体数位板、驱动、写字机、纸面校准、中文输入法组合输入和其他显示器组合未作实物验收。LaTeX 手册源码已同步 0.1.35，未重新编译 PDF；旧 PDF 不作为新版手册。旧原生设置中的窗口位置/最近入口可能随打开窗口正常记忆，全局排版默认未在验收中应用修改。
