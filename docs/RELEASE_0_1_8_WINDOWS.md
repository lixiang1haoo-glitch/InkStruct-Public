# InkStruct 0.1.8 Windows 更新记录

日期：2026-10-15。路径：`C:\Users\lee\Documents\InkStructApp\InkStruct-Windows-Dev`。应用版本取自 `src/inkstruct/fonts/__init__.py` 的 `APP_VERSION`，Python 库仍为 0.2.0。沿用项目 Python 3.13.16 x64、PySide6 6.9.2、PyInstaller 6.22.3，未修改全局环境。Git 基点仍为 `af45b45f04f899fcaced43aa980b0508673ee6c0` 加当前完整未提交工作树；未提交、推送或恢复旧快照。

## 采集与共享规则

新增中文专用标点 `。、【】《》〈〉「」『』“”‘’—…`，18 字符默认各 5 份，共 90 份。英文直引号双引号、单引号新增至标点组。当前采集器支持 220 个 Unicode 字符，合并共用项后为 208 个采集字符；英文正体与斜体分别计数时，全选为 260 个字符/写法、1300 份样本。

12 对形状相同的全/半角标点仅采一次：逗号、分号、冒号、叹号、问号、左右圆括号、左右方括号、左右花括号、百分号。新任务及 TXT/CSV 导入使用 ASCII 代表字符，别名去重；份数冲突提示修正，旧任务不改写。采集提示说明共用关系。

制作字体时共享原始采集笔迹，为不同 Unicode 字符发布独立候选；坐标、压力、时间、笔状态及分笔逐点保持不变。中文全角形式至少一个 em 前进宽度，字形不拉伸。来源摘要记录共享规则、原字符、样本 ID、原始 SHA256，开发者版保留原始记录。共享候选不冒充额外的人类录制，审阅状态仍为未审阅；已有直接录制的全角样本保留，不混入替代候选。

没有广义 Unicode 归一化。句号与小数点、顿号与逗号、破折号与数学减号/连字符、书名号、引号及省略号保持各自字符。字体与样本格式版本不变，协议校验、来源提示不放宽。

旧 ZIP 可在新版制作字体时复用已有标点，原 ZIP、旧字体和冻结文档不自动改写。完整字体仍需同时指定汉字生成结果和符号样本。旧的直接导入原始符号 ZIP 排版入口仍按原始字符集合加载，共享候选在制作字体时发布。

## 验证

相关回归 **101 passed, 1 skipped**，命令及日志在本轮 `regression.command.json`、`regression.log`。覆盖采集去重、中文标点保存续采、份数冲突、样本保真、共享来源、已有专用字形优先、字体校验及用户版转换、资源缺口 CSV 去重、排版保存重开和 SVG。静态检查通过。唯一未验证为 Windows 账户缺少符号链接创建权限（WinError 1314），与标点功能无关，生产路径检查未放宽。

使用 `handoff/raw_archives/user_001符号录制.zip` 的真实 80 字符、405 份样本制作独立的**仅符号验收字体**：包含 92 个 Unicode 字符、465 个候选，其中 60 个为 12 对共享候选的适配，并非新增录制。逐候选坐标、压力、时间相同；保存重开快照一致并导出机器 SVG。原始 ZIP SHA256 保持 `dab29626b1ac59af195dafb1062e6d9695d82bae9e14e0dfeda05ec45f717d35`。

user_001 仍需录制中文专用 18 个标点；英文直引号 2 个为另增独立项。未伪造这些缺失样本。验收目录 `real-user-001/remaining-capture.csv` 列出这 20 个缺口、各 5 份；这不包含上轮已知的英文正斜体及希腊字母缺口。

Windows Qt 截图已检查中文类别、共用说明及导入去重，均在 `visuals/`。README、使用说明和 LaTeX 手册源码同步至 0.1.8；TeX Live 未安装，新版 PDF 未编译，历史 PDF 保留。数位板、设备驱动和写字机纸面效果仍待实物验证。

最终 Windows 包内自检通过，两方法各 11 字导入、建档、生成、字体发布、排版、冻结重开及 SVG 验证均完成，原有来源缺口提示保留。另在新 EXE 中实际使用原始 user_001 ZIP 制作“仅符号验收0.1.8”字体，确认处理时输入锁定，成功后自动选中 92 字、465 候选字体；随后输入中文全角共用标点，原生页面完成 17 个文本实例排版，SVG 按钮可用。原生记录为 `native-font-publication.txt` 和 `native-punctuation-layout.txt`，独立工作区 `workspaces/windows-0.1.8`。未改写用户原有工作区及完整字体。

## 位置与命令

- 应用：`artifacts/windows_build_0.1.8_20261015/dist/InkStruct/InkStruct.exe`，同目录 `InkStructTool.exe`。
- 归档：`artifacts/windows_release_0.1.8/InkStruct-0.1.8-Windows-x64.zip`；需保留完整 InkStruct 目录及 `_internal`。
- 本轮日志：`artifacts/windows_ui_0.1.8_20261015/`；真实标点验收、字体、原生项目和 SVG 位于其 `real-user-001/`。该字体仅含符号，不替换 user_001 完整字体。
- 包内统一流程：`artifacts/windows_bundle_check_0.1.8_20261015/verification.json`。

```powershell
.\.venv\Scripts\python.exe -m inkstruct.application --workspace workspaces/windows
.\.venv\Scripts\python.exe -m pytest tests/test_shared_punctuation.py tests/test_symbol_capture.py tests/test_symbol_capture_ui.py tests/test_font_packages.py tests/test_document_resources.py
.\.venv\Scripts\python.exe packaging/build_inkstruct_app.py --output artifacts/windows_build_next
```

构建、验收与交付使用新的输出目录，旧数据及包保留。下一次交付至少为 0.1.9。

两入口 PE 文件/产品版本均为 0.1.8，x64；源码哈希与构建一致，ZIP CRC 校验通过。ZIP SHA256 为 `63896520c78664a13c2c33b7ea0c672a2c0ba24eae277c22e0fd8ebf1f51db21`。本次可重建临时缓存、pytest 临时目录及 PyInstaller 中间文件已清理，详见 `cleanup.json`；真实标点验收产物、日志及交付保留。

可继续开发；本次中文标点采集与共享功能可交付。缺失标点仍需作者实际补录，硬件和权限验证限制如上。
