# InkStruct 0.1.58 · Windows 资源工作流

2026-11-08。样本选择器读取采集页当前目录，优先使用已选书写者的汉字目录，保留有效手选位置。制作字体包按书写者列出汉字批次及标点与扩展来源，核对后可按类别勾选。正式制包重新校验输入并完整验证新字体。

模板库内置「普通页面」，可编辑纸张和四边边距。普通页面与自定义模板都能设为新文档默认。字体库负责设置默认字体。全局设置移除了两项资源分类。排版文件菜单的高级资源仅用于当前文档的外部生成目录与刷新。符号 ZIP 从制作字体包入口加入。

## 本机样本复制

应用实际采集根为 `C:\Users\lee\AppData\Local\InkStruct\workspace\capture`。复制前检查每份 JSON 的协议与书写者，按原相对路径写入。旧任务与进度未迁入。

| 作者 | 已确认来源 | 汉字 | 标点与扩展 | 目标同内容跳过 / 冲突 |
| --- | --- | ---: | ---: | ---: |
| scx | `artifacts/source_samples/scx_351bf154/samples/scx` | 793 | 未找到 | 0 / 0 |
| mjb | `artifacts/source_samples/mjb_42ed98c1/samples/mjb` | 793 | 未找到 | 0 / 0 |
| wsq | `artifacts/source_samples/wsq_169e6209/samples/wsq` | 793 | 未找到 | 0 / 0 |
| user_001 | `handoff/raw_archives/user_001含验证.zip`；既有审计确认的 `artifacts/font_capacity_simplified_20261104/input_audit/symbols-current-complete` | 40 | 1,096 | 0 / 0 |

`user_001汉字补录.zip` 的 24 份记录属于 40 份归档的重叠部分，未作为第二来源复制。另 385 份历史汉字只找到保留轨迹和来源哈希的归一化索引，尚未找到原始采集 JSON。检查当前采集根及已知历史符号任务来源，均无 `user_001` 已确认复用声明。现有软件支持从含任务配置且能核对来源身份的目录或 ZIP 使用已有确认。只复制样本不附带任务确认。

## 验收

- Windows 源码实窗重新展开书写者列表，识别四位新增作者及原有 `user_002`。通过拦截原生目录选择器调用核对空路径、选中作者、已有有效外部目录，以及更换采集根后无样本目录和有作者目录的起点。
- 在隔离工作区由实际界面导入 `user_001` 样本、建档、生成「中国书法」、预选同作者扩展目录、核对清单并勾选制作。新字体经完整校验，含 4 个汉字、16 个中文标点、52 个英文正体，与选中项的清单计数一致。界面选中新包。
- 在模板库编辑普通页面为宽 205 mm、左边距 15 mm。确认与自定义模板之间切换新文档默认、字体库设置新文档默认及旧设置分类和搜索入口移除。普通页面连续正文补测实际排出 7 页，通过严格 SVG 就绪检查。
- 只读审计 65 份现有 `.inkdoc`，全部内嵌模板。Windows 实窗在修改默认资源前后重开同一份既有报告，模板、资源池与 5,129 条冻结选样一致，原文件哈希一致。另用真实历史符号 ZIP 制作旧式空模板文档样本，重开保留原始符号笔迹和冻结选择，重排结果完全一致。
- 171 项相关回归通过。解包后的两个 EXE 均为 0.1.58，通过冻结公式自检。冻结工具用真实 scx 档案串行和双进程各生成 4 字，均得到相同的 16 份候选，制包后重开 SVG 一致。
- 0.1.57 发布 ZIP 哈希与上一份交付记录一致。LaTeX 手册源码已同步，未重编译 PDF。

## 构建与记录

```powershell
.venv/Scripts/python.exe -B -X utf8 packaging/build_inkstruct_app.py --output artifacts/release_0.1.58_20261108_final/windows-final
```

发布包为 `artifacts/release_0.1.58_20261108_final/release/InkStruct-0.1.58-Windows-x64.zip`。SHA-256 为 `b7c633b2de347d5252e3ceb987cc19b56909da0f3f5f384209c73374b51bc8ae`。完整解压后运行 `InkStruct/InkStruct.exe`。

复制记录、文档审计、回归、Windows 实窗截图和验证字体位于 `artifacts/resource_workflow_20261108/`。最终构建溯源和 ZIP 自检位于发布目录树。实窗验证脚本可用 Windows Qt 在新目录重放，需保留所引用的采集样本及报告原文件。
