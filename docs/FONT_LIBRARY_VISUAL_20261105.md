# 字体库视觉层级试点验收

2026-11-05。在 `C:/Users/lee/Documents/InkStructApp/InkStruct-Windows-Dev` 实施；APP_VERSION 保持 0.1.46。本轮仅字体库源码试点，不构建或发布应用，不扩展到模板、采集、生成、排版或主导航。

## 实际修改

- 右侧顶部集中显示当前字体名称、书写者、内容版本和包类型；左侧仍为精简的单行选择列表，搜索及历史筛选不变。
- “汉字与英文”“公式示例”预设隐藏文本编辑框，直接呈现真实笔迹。点击“编辑试写…”才进入自定义；切换预设后再回来，保留自定义草稿。字符浏览不覆盖该草稿。
- 以局部 Qt 样式形成浅灰侧栏、白色预览纸面及简洁标签层级，减少嵌套边框。底部操作按钮位置与现有工作流保持。
- 预览、缺字、来源提示、完整验证状态仍常驻。完整统计及诊断通过“查看提示…”的只读窗口访问；不隐藏错误、不降低验证门槛。
- 子代理审查发现摘要为空及失效时的显示边界：已补空统计回退，并在摘要不可用时清空旧标题，避免异常或显示上个字体的信息。最终截图复审未发现必须修复的遮挡或裁切。

本轮既有源码变动仅 `src/inkstruct/fonts/management_ui.py` 和 `tests/test_font_library_pilot_qt.py`。旧详情数据与字符、来源版本、文件信息页保留；字体、文档、生成及导出协议不变，无新增依赖或全局配置。

## 测试与真实数据

最终相关 8 个测试文件合计 **36 通过，0 失败，0 跳过，67.67 秒**。覆盖既有字体管理、导入、工作区、统一窗口、设置及属性栏回归；新增视觉交互用例在 100%、150%、200% Qt 缩放下验证标题、编辑入口、草稿保留、公式诊断、提示详情、空摘要及无结果状态。Ruff 通过。离屏测试不替代下述原生验收；重复运行不累加测试数量。

真实旧文档专项：使用已有 user_001 小字体及历史 `real-math.inkdoc`，在浏览、切换公式和筛选后，2 页、23 处冻结选样与源码身份保持；保存重开后的严格 SVG 逐页字节相同，6 项数学度量提醒保持，原字体和文档 SHA256 不变。结果为 `artifacts/font_library_visual_20261105/real-document-final-02/result.json`。这是独立正确性专项，不冒充原生鼠标保存/导出验收。

## 原生 Windows 验收

使用真实 PySide6 Windows 源码窗口、私有设置与工作区、真实 user_001 字体副本（215 字、1207 份候选）。逻辑 DPI 96、DPR 1.5，检查 1360×900 和 1000×720 两种逻辑窗口尺寸。

实际操作确认：预设下编辑框隐藏；“编辑试写…”打开输入框；输入 `Abc 123` 后形成真实笔迹；切到公式显示两条公式及原有两项数学提醒；“查看提示…”可打开完整只读诊断；切回自定义后 `Abc 123` 恢复。较窄窗口下标题、纸面、状态与底部操作均可见，无必须修复的遮挡。原生记录中的排版正文为空、冻结选样为空，浏览不写入文档；有内容旧文档的冻结语义由上一节专项另验。

私有字体副本不复制历史完整验证标记，因此如实显示“索引可读取 · 完整验证未运行”；没有把浏览当作完整字体验证。

展示截图：

- 默认汉字与英文完成态：`artifacts/font_library_visual_20261105/native-compact/01-compact-ready.png`
- 公式完成态：`artifacts/font_library_visual_20261105/native-after-final/04-formula.png`
- 自定义恢复完成态：`artifacts/font_library_visual_20261105/native-after-final/06-custom-restored-ready.png`
- 上轮修改前对照：`artifacts/font_library_preview_20261105/native-after-02/01-mixed.png`

注意：`native-after-final/01-mixed.png` 实际抓拍时已经进入自定义且在读取，不作为默认完成态展示；保留原始记录，不覆盖。一次辅助脚本重新启动因输出目录已存在而正常拒绝，保留 `native-final.log`；改用新目录重跑。自动化捕获曾显示被其他窗口遮挡，重新激活本实验窗口后确认；一次错误 API 调用未执行任何输入，随后按 API 文档纠正。这些不是应用崩溃。

未验证：跨显示器、独立系统文本放大、完整读屏及 IME、冻结 EXE、高 DPI 原生多显示器、数位板及写字机。原生实际缩放仅 150%，其他比例为 Qt 自动化测试。未做性能对照，不宣称提速。

## 保全与复现

本轮开工快照覆盖 499 个既有源码/测试文件，最终仅上述 2 个变化，其余 497 个一致、无缺失；清单为 `artifacts/font_library_visual_20261105/source-preservation-final.json`。Git 状态前后、开工源码压缩快照、原始日志、测试 XML、私有工作区、SVG 与截图均保留在该目录。生产工作区和独立排版开发目录未改动；没有 reset、clean、提交、推送或覆盖旧产物。

本轮执行命令（PowerShell，项目根目录）：

```powershell
.venv/Scripts/python.exe -B -X utf8 artifacts/font_library_visual_20261105/check_final.py
.venv/Scripts/python.exe -B -X utf8 artifacts/font_library_visual_20261105/real_document_check.py
.venv/Scripts/python.exe -B -X utf8 artifacts/font_library_visual_20261105/native.py
.venv/Scripts/python.exe -B -X utf8 artifacts/font_library_visual_20261105/native.py --compact
.venv/Scripts/python.exe -B -X utf8 -m ruff check src/inkstruct/fonts/management_ui.py tests/test_font_library_pilot_qt.py
```

这些一次性验收脚本主动拒绝复用既有输出目录。复测先将脚本中的输出叶名改为新名称，保留本次目录。原生脚本的 `finish` 文件仅用于关闭自己的实验窗口；所有本轮实验窗口已正常退出。测试日志 `tests-final.log`，XML `final-03.xml`，旧文档日志 `real-document-final.log`，原生最终日志 `native-final-02.log` 和 `native-compact.log`。
