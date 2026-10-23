# Windows GPU 栅格化补充实验（2026-10-20）

本轮继续验证 GPU 潜力，应用仍为 **0.1.32**。实验代码全部位于 `scripts/gpu_raster_followup/`，运行时替换实验进程与调度方法；没有修改生产源码、默认后端、模板协议、字体或用户文档，也没有正式构建或发布。此前实验 `docs/GPU_BENEFIT_WINDOWS_20261020.md` 和原始数据保留原样。

## 实测结论

GPU 栅格化值得继续做可选后端：本机密集页面冷缩放和实际编辑更新有稳定收益。更重要的新增发现是，**SVG 解析缓存、图形进程提前初始化和避免预取任务反复取消**，比继续压缩几毫秒 GPU 绘制提交更有价值。前两项包含 CPU 工作和启动调度，不能全部算作 GPU 算力收益；预取修正也适用于 CPU。

| 新增有效对照，单位 ms | CPU 对照中位数/P95 | GPU 实验中位数/P95 |
|---|---:|---:|
| 首次打开到完整页面可见 | 4188.90 / 4268.87 | 3835.18 / 3877.67 |
| 同样提前启动工作进程后的首开 | 4066.24 / 4077.84 | 3835.18 / 3877.67 |
| 冷页面图像缓存缩放，双方 4 页解析缓存 | 343.15 / 343.32 | 137.22 / 137.36 |
| 可见数字 0→1，包含重新排版和完整更新 | 952.55 / 978.64 | 779.43 / 794.47 |
| 同上，CPU 也启用 4 页解析缓存 | 933.56 / 956.94 | 779.43 / 794.47 |
| 暖页面图像缓存连续滚动，双方 4 页解析缓存 | 8.49 / 11.50 | 8.41 / 11.27 |

首开相对原 CPU 约缩短 8.4%，相对同样提前启动的 CPU 约缩短 5.7%。冷缩放约缩短 60%，实际编辑相对原 CPU 约缩短 18%，相对缓存 CPU 约缩短 16.5%。暖滚动没有证实 GPU 特有优势。以上是本轮配对数据；上一轮 CPU 首开 4.40 秒不能直接拿来计算本轮收益。

## 输入、环境和测量边界

项目绝对路径：`C:\Users\lee\Documents\InkStructApp\InkStruct-Windows-Dev`。Git 基点 `af45b45f04f899fcaced43aa980b0508673ee6c0`；源码为包含全部未提交修改的工作树。已阅读当前 AGENTS.md，APP_VERSION 为唯一应用版本来源。

RTX 5070 Ti，16303 MiB 显存，驱动 617.14；Core Ultra 5 250KF Plus，18 核/18 线程，约 23.72 GiB RAM；Windows 11 平衡电源计划。Mi Monitor 160 Hz，DPR 1.5，Qt 逻辑 DPI 96。窗口为 1400×900 逻辑像素，预览 viewport 1100×876，滚动输入目标 60 Hz。各后端图像分辨率、内容和可见范围相同，GPU 保持 8×MSAA。

复用独立 `.venv-gpu-experiment`，Python 3.13.16、NumPy 2.5.4；Qt 使用原应用 PySide6 6.9.2 的只读路径。本轮没有新增依赖，也没有改全局 Python 或应用环境。CuPy 仍只属于上一轮候选计算实验，本轮栅格化不使用 CUDA。

真实输入为 `artifacts/preview_performance_0.1.12_20261018/input.inkdoc`：11 页、4580 个文本实例、1501 个嵌入真实字形候选，保留 301 项原有诊断和 DEBUG 标记。另用真实 v6.2 小文档 `artifacts/v62_0.1.32_20261020/native-saved.inkdoc` 验证正式 SVG 与保存重开。没有重跑全库生成，也没有隐藏缺字或来源警告。

冷缓存表示新进程/页面缓存为空，没有清除 Windows 文件缓存。暖滚动先准备好完整可见范围；冷缩放表示目标缩放的页面图像尚未缓存，解析后的 SVG 可以命中。正式计时为 Qt 实际 paint 完成加 DwmFlush 的可见更新代理，**不是光电测量、扫描输出时间或理论 FPS**。栅格阶段必须完成同步像素读回，不能只测 GPU 提交。

Moonlight、BetterGI、QQ、桌面合成等其他用户程序保留运行。采样器在独立进程中，减少监测线程对 GUI Python GIL 的影响；无法消除所有外部负载。CPU 时间是进程树累计观测值，显存与 GPU 利用率为整卡 NVML 数据，不能冒充本进程独占值。

## 实验拆分和有效样本

- `native`：第 3–5 轮，5 条路线各 3 次；每次包含冷遍历 80 次、暖局部滚动 80 次、冷暖缩放、空白源码编辑与真实选字回调。
- `open`：第 6–8 轮，5 条路线各 3 次；连续计时包含资源读入/校验、解析、排版、栅格和首个完整页面可见。
- 前台补测第 18–20 轮：CPU 4 页、GPU 2 页、GPU 4 页解析缓存，各 3 次完整原生场景。
- 前台补测第 21–23 轮：原 CPU、缓存 CPU、缓存 GPU 各 3 次实际数字修改；包括 SourceSession 修改、重新排版和完整画面就绪。
- 离屏阶段：6 种变体交错运行 5 轮，每轮 8 个页面/缩放序列，共 240 条完成态计时。

上述 48 次正式原生运行前台比例均为 100%。此前 17 个出现失焦或错误的原生试跑全部排除，文件仍保留，清单在 `summary.json/excluded_native_runs`。初期还有驱动脚本缺少 `json` 导入导致的实验中断，已最小修复并保留失败日志；随后使用全新轮号补测，没有覆盖原数据。没有将后台运行成绩混入可见流畅度结论。

## 栅格阶段：究竟省在哪里

所有计时含 SVG 处理、实际 GPU 完成、QImage 读回、文件 IPC 写入与接收复制。同一密集第 6 页，100%/150% 缩放、DPR 1.5。表中为中位数/P95，单位 ms；首次和缩放各 5 个样本，重复序列共 20 个样本。

| GPU 路线 | 首次密集页 | 重复密集页 | 150% 缩放 | 相对正确 MSAA8 控制图的失配次数 |
|---|---:|---:|---:|---:|
| 上轮原型，无深度模板附件 | 43.19 / 44.36 | 42.45 / 46.90 | 52.29 / 61.78 | 5 |
| 正确深度模板附件控制组 | 42.13 / 47.67 | 42.58 / 57.04 | 50.95 / 56.72 | 0 |
| FBO 复用，读回承担同步 | 40.38 / 43.79 | 40.75 / 43.67 | 51.77 / 52.79 | 0 |
| 加 2 页 QSvgRenderer 缓存 | 41.89 / 44.84 | 20.32 / 22.93 | 31.59 / 34.92 | 0 |
| 再显式复用单采样 resolve FBO | 40.73 / 44.62 | 19.77 / 22.17 | 28.62 / 31.93 | 0 |
| QPicture 录制与重放 | 60.30 / 61.25 | 23.71 / 70.45 | 69.63 / 80.47 | 5 |

密集页 SVG 重新解析约 19.8 ms；缓存命中后该项为零。缓存路线重复样本分项中位数：内容哈希约 0.51 ms、目标绑定 0.012 ms、绘制提交约 4.07 ms、完成态读回约 4.56 ms、写文件约 2.20 ms、接收并复制约 8.71 ms。各分项中位数不是同一次样本，不能机械相加为总计。

FBO 复用本身只省约 1–2 ms。显式 resolve 路线在此小样有几毫秒收益，但尚未做独立原生对照，不能据此决定正式采用。QPicture 首次与缩放更慢，且 5 次密集页 150% 缩放均有像素失配，当前原型排除；不是宣称所有 QPicture 用法都不可行。

文件 IPC 与复制已成为缓存命中后较大的剩余部分。共享内存、PBO 异步读回和直接纹理呈现尚未实现/测量；它们是下一轮可证伪假设，不能声称已有收益。异步流水线也必须把取消、快照身份、资源寿命和完成态同步一起纳入验证。

## 首开、缓存容量与滚动调度

GPU 图形进程及着色器预热约 0.75 秒，提前与约 2.6 秒的文档载入/校验并行，能够隐藏大部分图形启动成本。这不加速 Markdown、公式解析或分页计算。首开 GPU 无解析缓存为 3844.86/3898.11 ms，加 2 页缓存为 3835.18/3877.67 ms，首次页面缓存不会凭空命中。

主场景的 2 页解析 LRU 会在遍历后淘汰即将缩放的页面，因此即使离屏缓存命中能省约 20 ms，原生冷缩放仍约 155 ms。补测扩大到 4 页后，GPU 冷缩放从 150.03/154.61 降到 137.22/137.36 ms；同批 CPU 4 页为 343.15/343.32 ms。容量必须按真实导航序列验证，不能从单页循环外推。

调度根因是：启动逻辑允许相邻页预取，但 viewport_changed 会把仍在可见区外的相邻任务取消；随后又重新构建 SVG。一次诊断轨迹出现暖局部滚动新增 14 个任务并取消 14 次，额外构建约 0.64 秒 SVG。该轨迹只用于根因分析，不作为正式可见时延数据。

隔离运行时修正：可见内容已准备好时保留相邻预取；缺少可见内容、任务已远离视口、空视口等仍按条件取消。原有快照变更、关闭、调整尺寸的取消机制保留。配对 CPU 实测暖滚动新增/取消任务由每轮 2/2 变为 0/0，>50 ms 可见更新由 4/240 次变为 0/240；P95 从 12.37 降到 11.59 ms。缓存 GPU 为 11.94 ms，不能称 GPU 解决了暖滚动。

GC 回调没有与所查慢帧一致重合，当前没有证据支持关闭 GC。原先进程内监测采样可占用 30–60 ms，但移到外部进程也不能单独消除所有尾部停顿；不能把采样器或其他用户软件武断认定为唯一根因。

## 资源成本和正确性

主场景每路线 3 轮，进程树 RSS 峰值：原 CPU 828–831 MiB，调度修正 CPU 819–837 MiB，缓存 CPU 835–840 MiB，正确附件 GPU 892–909 MiB，2 页缓存 GPU 906–911 MiB。对应 CPU 累计秒范围约为 9.56–10.09、8.31–8.83、8.16–8.36、7.58–7.84、7.22–7.55。运行时长不同，应与原始 wall_s 一起解释。

4 页补测 RSS 峰值 CPU 840–859 MiB、GPU 914–929 MiB；整卡显存峰值约 CPU 5195–5196 MiB、GPU 5514–5521 MiB。主场景整卡 GPU 利用率各轮中位数约 13%–27%，没有独占负载归因。更大缓存增加资源成本，不能无界保留整份文档。

实验 FBO 缓存按保守估算设 384 MiB 淘汰预算，SVG 原文上限 32 MiB、最多 2/4 页。该预算不是硬显存峰值上限：单个较大临时 FBO、驱动开销和 Qt 解析对象另有成本。正式实现仍需内存压力和设备丢失回退。

实际 paint engine 为 OpenGL2，实际 renderer 为 NVIDIA RTX 5070 Ti，完成后读取 QImage；并非仅创建上下文。上轮原型缺少 CombinedDepthStencil，在带孔的 even-odd 填充压力图中把孔填实；本轮正确附件及复用/缓存/resolve 路线相对正确 MSAA8 控制图均逐像素相同。[Qt FBO 文档](https://doc.qt.io/qt-6/qopenglframebufferobject.html)明确要求用该附件保证 QPainter 正确绘制。[QPicture 文档](https://doc.qt.io/qt-6/qpicture.html)说明它是绘制命令记录重放，不能假设等同于已缓存 GPU 几何。

压力 SVG 含 clipPath、变换、细线和 even-odd 路径；当前 QtSvg 对输入中圆形 clipPath 的表现不等同于完整浏览器 SVG，CPU 控制图也相同，因此本轮**不把它称为 SVG 全规范裁剪通过**。确认的是保持现有 QtSvg 语义及修复 GPU 附件造成的填充差异。

CPU 与 MSAA8 GPU 的边缘抗锯齿有差别：4 个图像场景平均 RGB 绝对差约 0.094–0.993/255；双方暗色墨迹均没有超出另一方 2 像素邻域的部分。不是逐像素相同的跨后端宣称。

验证记录：

- 7 个调度边界用例通过；10 个 GPU 全页/512 像素分块/边缘块/交错复用序列均与正确控制逐像素一致，覆盖缓存 2/4 页；缓存 CPU 与原 CPU QtSvg 像素一致。
- 7 个工作进程协议边界通过，包括非法尺寸、重复/越界分块和全页/分块混用拒绝；不放宽生产协议。
- 正式原生主场景与容量补测的页面 SVG、几何、冻结选样、诊断哈希一致；真实选字回调通过。实际修改后的几何哈希在各后端一致，空白编辑几何不变。
- 真实 v6.2 文档保存重开后源码身份、冻结选样、样式、评价一致，正式 SVG 字节完全相同；“孔”的参考替代笔画及 no admitted author stroke 来源提示保留。
- 本轮 Windows 新跑 48 项相关应用回归通过（11.05 秒），覆盖连续预览、进程与序列化、文档包、plotter、v6.2 语义；静态关键错误检查通过。
- 未验证：AMD/Intel/集显/软件 OpenGL、远程会话切换、驱动重置、长时间大文档内存压力、原生共享内存/PBO/直接纹理路线、独立 resolve 原生收益及光学呈现延迟。本轮没有继续候选计算实验。

## 复现命令与产物

在项目根目录的 PowerShell 执行，先指定一个**全新目录**，防止覆盖本轮记录：

```powershell
$env:INKSTRUCT_GPU_EXPERIMENT_OUT = 'artifacts/gpu_raster_followup_reproduction_01'
.venv-gpu-experiment/Scripts/python.exe scripts/gpu_raster_followup/initialize.py
.venv-gpu-experiment/Scripts/python.exe scripts/gpu_raster_followup/stages.py
.venv-gpu-experiment/Scripts/python.exe scripts/gpu_raster_followup/run.py native
.venv-gpu-experiment/Scripts/python.exe scripts/gpu_raster_followup/run.py open
.venv-gpu-experiment/Scripts/python.exe scripts/gpu_raster_followup/run.py foreground-followup
.venv-gpu-experiment/Scripts/python.exe scripts/gpu_raster_followup/validate.py
.venv-gpu-experiment/Scripts/python.exe scripts/gpu_raster_followup/protocol.py
.venv-gpu-experiment/Scripts/python.exe scripts/gpu_raster_followup/verify_real.py
.venv-gpu-experiment/Scripts/python.exe scripts/gpu_raster_followup/checks.py
.venv-gpu-experiment/Scripts/python.exe scripts/gpu_raster_followup/analyze.py
.venv/Scripts/python.exe -m ruff check scripts/gpu_raster_followup --select E9,F63,F7,F82
```

原生三组命令运行时保持实验窗口前台，勿并行运行其他性能实验。首次 initialize 和所有数据处理不应计入原生场景耗时。`run.py` 拒绝覆盖同名日志，并在失焦后中止；要补测须使用新目录/新轮号，不应重置原记录。

本轮实际输出：`C:\Users\lee\Documents\InkStructApp\InkStruct-Windows-Dev\artifacts\gpu_raster_followup_20261020`。`summary.json` 为汇总，`preview-*.json` 为每动作/每帧原始时序，`worker-*.jsonl` 为分阶段与引擎证据，`stages.json` 为独立阶段数据；PNG 为质量及失配样本；`real-v62-roundtrip.inkdoc`、`real-svg-*` 为保存导出验收。测试、环境、Git、输入哈希及失败试跑日志均保留。最终 `preservation-after.json` 与 `seal.json` 记录数据核验和代码归档。

## 建议的最小后续接入范围

优先独立交付通用预取取消修正，再把 GPU 栅格作为显式可选能力接入现有私有工作进程，保留 CPU 自动回退。采用正确深度模板附件、完成态读回、进程预热和有限解析/FBO 缓存；继续沿用权威排版、选样、诊断和导出路径。

维护成本集中在图形驱动与设备丢失、工作进程启动失败、显存预算、缓存失效/快照身份、DPI 与分块、抗锯齿质量、取消及资源释放。先补跨设备和长会话测试，不能仅凭本机速度把默认实现切到 GPU。本轮仅提供可运行实验与可复核数据，没有发布新版本。
