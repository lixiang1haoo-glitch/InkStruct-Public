# 字体库：多行试写与精简列表

2026-11-05，沿用当前字体库试点，APP_VERSION保持0.1.46，不构建或发布新版。本轮不扩展到模板或其他页面。

## 修改

- 左侧每项仅显示库内别名或字体名称，以及必要的默认／移出／不可读状态。长名称单行省略，悬停仍可查看完整标题、版本和文件路径。作者、版本等索引仍参与搜索和历史筛选，没有按显示名称重新识别字体。右侧预览说明显示名称、书写者、内容版本、包类型、候选数量与来源提示；原字符、来源版本和文件信息页保留。
- 预览增加“汉字与英文／公式示例／自定义试写”。默认从本字体可用字中选8个汉字，与英文、数字和标点分行展示，不伪造字体不包含的汉字；其他示例字符缺失仍显示红框。用户编辑试写内容时切换为自定义，保留输入。
- 公式示例复用已有Markdown解析、数学排版、字体资源解析和SVG预览。只用该字体的字形，不启用内置数字补缺；上标、分式和录制减号分数线沿用现有规则。独立小页面与预览字号不修改实际文档设置。正常预览使用原渲染校验；有阻断诊断时使用原明确标识的诊断预览，不作为成品输出。
- 公式诊断按代码计数显示，完整消息保留在提示中；真实小字体的2项数学度量未校准提醒仍显示。此预览不能替代完整字体验证或当前文档适配。

源码改动为 `src/inkstruct/fonts/ui.py`、`management_ui.py`、`management.py` 和 `tests/test_font_library_pilot_qt.py`。没有修改字体／文档协议、生成、默认主题、导出门槛或文档冻结选样。

## 验证

最终33项测试通过，0失败、0跳过，57.83秒；Ruff通过。覆盖100%、150%、200%的列表简洁度、右侧详情、作者搜索、三种预览内容、自定义输入、缺少公式来源仍报告错误，以及既有清理失效／迟到结果／应用取消／保存重开／严格SVG等。前一轮运行也是33项，不相加。

真实旧文档专项最终输出为 `artifacts/font_library_preview_20261105/real-document-final/result.json`：在浏览公式及筛选后，原2页、23处冻结选样、源码身份保持；保存重开后的严格SVG逐页字节相同，6项数学提醒保持，原字体和文档SHA不变。

原生Windows源码窗口：1360×900逻辑尺寸、DPR1.5、96逻辑DPI。沿用只读真实user_001小字体的私有副本，215字／1207候选；实际查看精简列表、多行真实汉字预览，并实际切换公式示例，确认两条公式和2项数学提醒。私有副本未复制完整验证标记，界面如实说明“索引可读取 · 完整验证未运行”。不把此次浏览冒充重新完整校验或冻结EXE验收。

最终截图：

- `artifacts/font_library_preview_20261105/native-after-02/01-mixed.png`
- `artifacts/font_library_preview_20261105/native-after-02/02-formula.png`

初版公式示例字号较小且始终使用诊断模式；原生观察后，仅调整独立示例的预览纸面与字号，并改为按快照原可导出状态选择原渲染入口。随后重跑33项及真实文档专项，保留初版截图和日志。一次辅助脚本生成命令的PowerShell引号失败，没有改动应用或用户数据。

未验证：本轮未重测原生窄窗口、跨显示器、独立文本放大、完整读屏／IME、数位板／写字机及冻结EXE。自定义试写已由三个DPI的Qt测试验证，未另做原生文字录入验收。未进行性能对照，不宣称提速。

## 保全与复现

开工快照、原始日志、测试XML、原生记录、SVG、SHA及源文件变动清单位于 `artifacts/font_library_preview_20261105`。仅上述4个既有文件变化，其余既有源码／测试文件保持。全部验证使用私有设置、字体库和恢复目录，不修改生产工作区，不覆盖旧字体、文档或历史交付包；没有reset、clean、提交、推送或独立排版目录修改。

本轮准确命令（输出已存在，复测须另选新目录）：

```powershell
.venv/Scripts/python.exe -B -X utf8 artifacts/font_library_preview_20261105/check_final.py
.venv/Scripts/python.exe -B -X utf8 artifacts/font_library_preview_20261105/real_document_check.py
.venv/Scripts/python.exe -B -X utf8 artifacts/font_library_preview_20261105/native.py
.venv/Scripts/python.exe -B -X utf8 -m ruff check src/inkstruct/fonts/ui.py src/inkstruct/fonts/management_ui.py src/inkstruct/fonts/management.py tests/test_font_library_pilot_qt.py
```

普通应用源码入口保持不变；本轮仅保留字体库源码试点，不递增版本或制作正式包。
