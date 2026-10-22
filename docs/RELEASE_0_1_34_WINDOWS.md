# InkStruct 0.1.34 Windows 交付记录

2026-10-20。实际项目：`C:\Users\lee\Documents\InkStructApp\InkStruct-Windows-Dev`。源码为 Git 基点 `af45b45f04f899fcaced43aa980b0508673ee6c0` 加完整未提交工作树，没有 reset、clean、提交或推送。应用版本唯一来源 `src/inkstruct/fonts/__init__.py:APP_VERSION` 为 **0.1.34**；Python 库 0.2.0、字体格式 1.0 独立。上一轮编辑器性能原型继续隔离，未混入本轮生产路径。

## 本轮行为

制作新字体时自动接入 `recorded-math-symbols-v1`。已有启用目标候选优先，不改写原候选；仅从合格录制笔迹构造缺失目标。

- **六辐星号**：一笔 U+2212 减号按稳定候选 ID 排序，循环选相邻三份，优先不同样本；不足三份时记录重复数。缩至来源最短横向跨度的 65%（上限 0.42 em），分别旋转 0°、60°、120°，以来源包围盒中心对齐。每个目标生成 N 份候选，避免组合爆炸。U+002A `*` 与 U+2217 `∗` 保留不同候选/字符身份，明确共享构造几何。公式里的 `*` 继续解析为数学星号 `∗`。
- **数学比号 U+2236 `∶`**：优先全角冒号 U+FF1A `：`，无合格来源时才用半角冒号 U+003A `:`；保留全部笔画和点，仅作整体等比缩放和平移。最大跨度 0.36 em，中心置于默认数学轴。比号使用关系类间距；冒号身份、正文及 Markdown 不替换。
- **数学圆圈 U+2218 `∘`**：复用中文句号 U+3002 `。` 的完整笔迹，整体等比缩至最大跨度 0.18 em，并按当前数学轴放置。`\circ` 保留原 `ord` 类别，不替换为度数。只有合成圆圈使用新增对齐；独立录制圆圈保留旧放置行为，避免影响旧文档。
- **页码方向**：排版页向上按钮为上一页、向下为下一页；键盘 Up/Down 同步。输入页码和连续滚动同步行为保留，第一页/最后一页的按钮状态也反向对应。

新结果明确为 `source_kind=composed`，不是独立采集。来源记录包含候选、轨迹/度量/来源摘要哈希、原笔序与笔画身份、组件六参数仿射矩阵、时间平移和确定性构造身份。两种星号可具有相同构造身份而保留独立字符身份。压力、笔状态及时间字段存在性保留；三笔组合只平移组件时间并标记 `inherited_retimed`，单来源复用时间不变。来源分区、缺口和警告传递，单点笔迹仍要求明确机器适配。构造数学轴与采集参考线分开，核心校验检查轴的类型、范围和有限性。

未录制、拒绝、非录制或退化来源不制造假候选；扩展结果返回 `construction_diagnostics`，未获得目标时排版仍报真实缺字。未移除来源警告或放宽 SVG 条件。

## user_001 字体

来源为本机字体库的 `0fff3823-4eeb-46ae-a73f-852f4463015d.inkfont`，即上轮“v6.2 exp 验证合并版 · ℃与符号扩展”。这是既有全库加孔、正 v6.2 验证结果的合并包，本轮没有重跑全库生成，也不声称全部汉字重新按 v6.2 生成。

新包：`artifacts/integration_0.1.34_20261020/user_001-v62-validation-recorded-math-symbols-20261020.inkfont`。

| 内容 | 实际结果 |
|---|---:|
| 新增 `*` / `∗` / `∶` / `∘` | 各 5 份，共 20 份 |
| 总字符 | 9,778 |
| 总候选 | 10,770 |
| 总轨迹点 | 8,377,832 |
| 原候选身份、轨迹、度量、来源逐项不变 | 10,750 份 |
| 来源不完整候选提示 | 3,351 份，保持原有提示 |

字体内容版本为 0.4，不改变字体格式。新 package/release 身份，原 font_id 保留且记录父包身份。原字体、文档及冻结选样不自动迁移。已完整校验并另存加入默认字体库：

`C:\Users\lee\AppData\Local\InkStruct\workspace\fonts\5649da0a-e653-4269-926b-260a4346a0b4.inkfont`

新字体名称：“user_001 · v6.2 exp 验证合并版 · 六辐星号比号圆圈 · 20261020”。**已有文档要使用新字符时，应显式选择新字体并检查选样；不能靠升级应用自动改变旧文档。** 新旧包完整校验通过，导入副本与交付字体哈希一致。全部 20 份构造已按最终源码重新计算，轨迹、度量与来源完全一致。原型图为验收目录中的 `symbol-contact-sheet.png`。

## 真实测试

- 初次相关回归覆盖 80 个测试文件、943 项：**938 passed、4 failed、1 skipped**。保留 `regression.log` 与完整收集结果。
- 3 项失败是原有 CPU 精确像素对照受本机已选择 GPU 后端影响；1 项 PDF CLI 失败涉及子进程输出编码。以独立 INI 的 CPU 测试设置、显式继承 UTF-8 子进程环境复测，**43 passed**。没有修改用户全局 GPU 设置，也没有改动 PDF/渲染生产代码来绕过测试。
- 增加来源回退、单点机器适配、仅补缺失星号身份及独立圆圈旧放置回归；最终针对性复测 **47 passed**。结合原回归去重为 **946 项通过、1 项跳过**，不是声称整套初次全绿。最终日志在 `delivery-final-checks/`。
- 新增规则测试覆盖：有限确定性配对、1/2/3/5 份减号、优先不同样本、显式重复、完整笔画/动态值、均匀缩放、中心和数学轴、来源哈希与笔画身份、时间重排、目标优先、拒绝/退化/缺失来源、全角优先与半角回退、点适配仍阻断、公式 `*`/`\circ` 原语义、独立圆圈原位置、页码鼠标/键盘/端点和直接输入。
- 真实 user_001 新字体四页小样，815 个实例，**46 项数学未校准警告全部保留**。正文及公式预览、保存重开、源文/选样/页面设置/完整快照/每页 SVG 一致，严格 SVG 成功。
- 原生 Windows 实际打开本轮构建：显示新符号；鼠标下箭头 1→2、上箭头 2→1；从导出弹窗输出四页 SVG，另存 `native-ui-saved.inkdoc` 后重开成功。原生保存结果与输入的源文、冻结选样、设置和快照相同；原生 SVG 与同一严格计划逐页字节相同。文字观察、输出和复核分别见 `native-observations.json`、`native-ui-svg/`、`native-verification.json`。
- 最终重建 EXE 又实际打开上述已保存文档，重复核对四页/815 实例/46 警告、上下按钮并再次从弹窗输出四页 SVG，与严格计划逐页字节一致。最终 EXE 观察与输出在 `delivery-native/`，双 EXE 版本记录和包内自检日志也单独保留在此目录，未拿内部初版代替最终包验收。
- InkStructTool.exe 包内自检：v62/v61/v4 分别完成 scx 11 字导入、建档、生成、字体、排版、保存重开和 SVG，`notices=[]`；原来源提示保留。没有重跑全库。
- 修改的生产与测试 Python 文件 Ruff 通过。
- 保全基线 3,212 份既有用户/历史文件：可读文件内容哈希一致，3 份此前无读取权限的旧工作区字体只核对大小和修改时间，保持不变；不能声称已读过其内容。日志与 `user-data-after.json` 保留。

初次页码控件测试用固定像素坐标，命中了平台样式的另一按钮；改为 QStyle 返回的真实子控件区域测试后通过，生产行为又经原生按钮验证。两项旧字体轴测试更新为分别核对旧录制字形和新增合成星号，没有取消旧轴校验。初次真实小样只有两页，不满足本轮四页验收目标，扩展为 45 行后得到四页；未降低排版检查。

## Windows 构建与产物

最终构建目录：`artifacts/windows_build_0.1.34_20261020_final/`。早期 `..._release/` 是本轮内部验收构建，随后为独立圆圈兼容保护重建；不作为交付 ZIP 来源，原目录保留。没有覆盖历史交付或用文件名后缀代替正式版本递增。

- `dist/InkStruct/InkStruct.exe`、`InkStructTool.exe` 均为 x64，文件及产品版本 **0.1.34**；必须保留同目录 `_internal`。
- 构建前后及最终交付前源码哈希核对一致；版本数据来自 APP_VERSION。
- Python **3.13.16 x64**；PySide6 **6.9.2**；NumPy **2.5.4**；Matplotlib **3.11.2**；Pillow **12.3.0**；PyInstaller **6.22.3**，依赖未新增或全局安装。
- 正式交付目录：`artifacts/windows_release_0.1.34/`，含版本化应用 ZIP、新字体、使用说明、验收记录、SHA256 清单。
- 本轮脚本、原始失败/通过日志、字体报告、源快照、SVG 和 `.inkdoc`：`artifacts/integration_0.1.34_20261020/`。
- 新建验收工作区：`workspaces/windows-integration-0.1.34`。没有复用或改写原工作区。

## 准确命令

在项目根目录 PowerShell 中：

```powershell
& .\artifacts\windows_build_0.1.34_20261020_final\dist\InkStruct\InkStruct.exe --workspace .\workspaces\windows-integration-0.1.34
& .\.venv\Scripts\python.exe -B -X utf8 -m inkstruct.application --workspace .\workspaces\windows-integration-0.1.34
& .\.venv\Scripts\python.exe -B -X utf8 artifacts/integration_0.1.34_20261020/run_checks.py
& .\.venv\Scripts\python.exe -B -X utf8 artifacts/integration_0.1.34_20261020/verify_native.py
& .\.venv\Scripts\python.exe -B -X utf8 packaging/build_inkstruct_app.py --output artifacts/windows_build_0.1.34_reproduction_new
& .\artifacts\windows_build_0.1.34_20261020_final\dist\InkStruct\InkStructTool.exe --inkstruct-check --samples artifacts/source_samples/scx_351bf154/samples/scx --writer scx --font artifacts/integration_0.1.34_20261020/user_001-v62-validation-recorded-math-symbols-20261020.inkfont --output artifacts/windows_bundle_check_0.1.34_reproduction_new
```

字体扩展复现使用 `build_font.py` 中的真实父包，改为新的输出路径后运行；导入使用 `import_user_font.py`。构建和字体扩展采用独占新路径，验收脚本复跑前应将脚本中的输出改为新目录，保留本次证据。回归复测的私有设置、UTF-8 环境和准确参数记录在 `retest-command.json` 及 `delivery-final-checks/final-tests-command.json`。

## 限制与结论

可继续开发，本轮录制符号和页码方向范围可交付。跳过项是 Windows 账户无符号链接权限时的真实悬空链接测试。实体数位板、驱动、写字机和纸面数学轴/尺寸效果未验证；本轮没有声称完成这些硬件验收。XeLaTeX/latexmk 不可用，手册源码已同步 0.1.34，未生成新版手册 PDF，旧 PDF 保留。

只清理本轮新建、可重建的测试临时文件、Matplotlib 缓存和两个构建的私有 work/cache；保留源码、字体、用户工作区、测试/构建日志、失败记录、验收及交付产物。不会清理项目既有缓存或其他工作区。
