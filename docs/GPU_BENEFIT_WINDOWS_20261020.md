# InkStruct Windows GPU 收益验证（2026-10-20）

本轮是隔离性能实验。应用仍为 **0.1.32**，没有正式应用构建、版本升级、提交或推送。默认预览与生成源码没有修改。结论只适用于本机和下述输入，不代表所有 GPU。

## 结论

- **预览栅格化值得继续受限接入实验**：密集页同分辨率 SVG 到缓存图像有明确收益；缩放和已有进程中的内容更新受益。首次打开受资源校验、解析及图形初始化限制，GPU 反而较慢；暖缓存滚动也未证实有稳定收益，因此本轮不建议改成默认 GPU。
- **仅改已有缓存画面的 OpenGL 合成，暂不接入**：实际 GPU 绘制已验证，但单帧工作节省很小，包含 Qt 合成与同步后的可见更新没有稳定改善，且增加图形上下文和资源管理。
- **全库候选计算暂不正式接入 GPU**：驻留数据上的 FP64 批量拟合确实更快；安全原型在加入传输、同步和全候选 CPU 复核后负收益，完整 11 字任务未提速。更细的、具有可靠误差界的选择性复核尚未验证，不能据此断言 GPU 永远无用。

## 环境、保全与既有瓶颈

项目：`C:\Users\lee\Documents\InkStructApp\InkStruct-Windows-Dev`。Git 基点 `af45b45f04f899fcaced43aa980b0508673ee6c0`，以当前完整未提交工作树为源码；基点不是完整源码替代。实际 AGENTS.md 与 APP_VERSION 均为 0.1.32。之前的 0.1.13 连续预览和 macOS 记录仅作架构参考，本报告数值均为本轮 Windows 新测。

CPU：Intel Core Ultra 5 250KF Plus，18 核/18 线程；物理内存约 23.72 GiB。GPU：NVIDIA GeForce RTX 5070 Ti，nvidia-smi 实报 16303 MiB 显存，驱动 617.14，CUDA 驱动接口 13.4。WMI 的约 4 GB AdapterRAM 为截断值，未采用。Vulkan 1.4.351 能枚举设备，本轮未实现 Vulkan 计算后端。Qt 实测 OpenGL 4.6，NVIDIA renderer。

Windows 11，平衡电源计划；未修改电源、驱动或其他程序。Mi Monitor 160 Hz，Windows DPR 1.5，Qt 逻辑 DPI 96。实验窗口 1400×900 逻辑像素，正式对照的预览 viewport 相同。滚动输入目标为 60 Hz，实际绘制、迟到和停顿均记录；这不是用理论帧率替代实测。

现场存在 Moonlight、BetterGI、QQ、桌面合成与其他用户程序，没有擅自关闭。GPU 全局负载和显存基线明显非零。使用交错顺序重复测试，仍不能消除所有外部负载影响。NVML 记录整卡显存与利用率，WDDM 下没有将整卡读数冒充实验进程的独占显存。

应用环境 `.venv`：Python 3.13.16 x64、NumPy 2.5.4、PySide6 6.9.2。独立 `.venv-gpu-experiment` 仅安装 CuPy CUDA13 14.2.0、相同 NumPy、psutil 7.2.2、nvidia-cuda-runtime/nvrtc 13.4.92 及 cuda-pathfinder。未安装训练环境，未安装 NVCC 或改动原应用依赖；Qt 与项目包通过只读路径复用。安装计划、安装日志和报告保存在实验目录。

默认预览原本就是 SVG 构建线程、独立 CPU QtSvg 栅格进程、96 MiB 页面/分块缓存及 QWidget 绘制。暖缓存显示已经避开重复 SVG 栅格化，Windows DWM 也已参与最终桌面合成。CPU 总占用低不能直接推出 GPU 有用。

本轮实测打开文档的资源读取、解压、解析与完整校验约 2.6 秒，Markdown/公式排版与分页约 1.1 秒。cProfile 辅助记录指向嵌入字形校验与哈希、JSON 解析、测量和排版；该归因运行受剖析与监测线程开销影响，不能当作正式总时长。正式数值取未剖析运行。

生成另用轻量计时器记录实际阶段，阶段为包含关系，不能相加。结构 SQL 读取/解码、视图准备、JSON 序列化和语义检查占主导；压缩与实际二进制写出很小。单笔拟合在 11 字完整任务仅约 6 ms。完整记录在 `pipeline-*-*.json` 的 `phases_inclusive_not_additive`。

补充在同一进程中三次未剖析的实际调用归因，中位数如下。它与原生新进程首开分别保存，不能混为同一组总时长。JSON 项仅为包元数据解析，字形内部解码与完整性校验包含在载入总计；公式项也包含在更大的解析/测量阶段，不能重复相加。

| CPU 阶段 | 中位数 ms |
|---|---:|
| 文件字节读取 | 4.83 |
| ZIP 成员读取/解压 | 117.25 |
| 包元数据 JSON 解析 | 215.79 |
| 文档载入含全部解码、哈希与校验 | 2735.08 |
| Markdown 解析（含公式） | 68.33 |
| 其中公式语法解析 | 5.59 |
| 排版测量与分页 | 919.18 |
| 其中公式几何测量 | 90.06 |
| 密集第 6 页 SVG 构建 | 30.38 |
| SVG 文件写入 | 1.51 |

原始记录：`baseline-parts.json`。文件物理读取和解压不是主导，GPU 也未加速权威资源校验、语义结构或分页计算。

## 预览实验

真实输入为 `artifacts/preview_performance_0.1.12_20261018/input.inkdoc`，11 页、4580 个文本实例、1501 个嵌入真实字形候选；当前实现仍有 301 项原有诊断。没有隐藏缺字或公式错误，预览继续带 DEBUG 标记，不能把这个不完整文档声称为可正式导出的成品。另用 0.1.32 真实 v6.2 小文档验证保存与正式 SVG。

CPU 为原 ContinuousPageCanvas 与原进程；GPU 合成原型以同一 QImage 缓存绘制到 QOpenGLWidget，保留布局、选字和缓存策略；GPU 栅格化原型仅替换私有栅格工作进程，使用 QtSvg→OpenGL FBO→读回 QImage，仍经原 CPU 画布显示。图像尺寸、DPR、页序、可见页面及全部内容不变。GPU 栅格使用 8×MSAA，没有降低分辨率或内容换速度。

原生正式滚动为第 8–10 轮，每后端 3 次进程、每场景 80 次真实画布更新，另有第 11 轮逐帧引擎核验。正式首开为 open-4–6；可见第 6 页将数字 0 改为 1 的内容编辑为 edit-1–3。首开计时是连续的“读文档→排版→完整首帧→DWM fence”，正确性哈希在首帧之后计算。编辑计时包含实际 SourceSession 编辑、排版和完整画面就绪。

冷缓存指新进程/新画布、页面缓存为空；没有清除 Windows 文件缓存。暖缓存先预热整个滚动范围并等待相关任务完成，正式暖滚动的可见缓存缺失为零。缩放按实际缓存是否就绪分冷暖。首批 1–7 轮保留为试跑：其中包含未预热范围或不同输入节奏，不能混入正式对照。初始 cpu-0 的实验子进程依赖路径错误已修正，仅终止了该自建测试进程。

端点分别记录 Qt 实际 paint 工作和输入到 DwmFlush 合成同步。GPU 合成还等待 Qt frameSwapped；两端包含各自 Qt 提交调度，不能把差值全部归为着色器速度。它们是已显示原生窗口中的可见更新代理，**不是光电测量或 PresentMon 扫描输出时间**。全部正式窗口前台比例为 100%，没有拿后台空循环次数当帧率。

下表单位为 ms，均为 **中位数 / P95**。滚动可见反馈可能是占位画面，因此另报内容最终就绪时间与未就绪计数。

| 场景 | CPU 原实现 | GPU 合成 | GPU 栅格化＋CPU 合成 |
|---|---:|---:|---:|
| 暖缓存 paint 工作 | 2.23 / 3.66 | 1.29 / 2.70 | 2.26 / 35.14 |
| 暖缓存可见合成代理 | 10.09 / 19.17 | 12.74 / 24.26 | 12.01 / 56.51 |
| 冷滚动可见反馈代理 | 9.74 / 21.56 | 12.62 / 31.44 | 12.16 / 62.27 |
| 冷滚动结束后的内容就绪 | 279.61 / 317.88 | 267.66 / 282.77 | 56.69 / 68.33 |
| 冷缓存缩放 | 361.52 / 362.49 | 374.15 / 380.55 | 153.76 / 161.65 |
| 暖缓存缩放 | 12.41 / 44.54 | 23.78 / 25.10 | 12.68 / 37.19 |

| 连续端到端场景（ms） | CPU | GPU 栅格化＋CPU 合成 |
|---|---:|---:|
| 首次打开至完整可见页面 | 4402.96 / 4408.16 | 4861.31 / 4864.23 |
| 可见数字 0→1 后更新 | 974.01 / 1006.82 | 773.12 / 780.55 |

密集页独立栅格实验含相同 SVG 解析、分配、实际 GPU 完成、读回、像素写文件与接收复制。每档交错运行 7 次，单位 ms：

| 缩放 / DPR | CPU 总计中位数/P95 | GPU 总计中位数/P95 |
|---|---:|---:|
| 1.0× / 1.5 | 263.52 / 277.79 | 42.29 / 92.67 |
| 1.5× / 1.5 | 277.22 / 279.80 | 55.49 / 74.53 |
| 2.0× / 1.5 | 292.33 / 306.01 | 66.48 / 76.60 |

完整分项与首次样本见 `raster.json`：SVG 解析、分配、栅格同步、读回、写入、接收复制均独立计时。这里不把栅格提速说成 Markdown/公式排版提速。

CPU/GPU 栅格像素不是逐像素相同。三个缩放档平均 RGB 绝对差约 0.36–0.74/255，约 1.65%–3.24% 像素不同；双方暗色笔画均没有超出另一方 2 像素邻域的部分。差异主要是边缘抗锯齿，仍需更多细线、透明、图片和复杂 SVG 的视觉验收。GPU 合成在窗口抓图时会发生 Qt CPU 重绘；已单独排除抓图，187 次实际绘制引擎均为 `Type.OpenGL2`，不是仅创建了上下文。

### 资源与停顿

CPU 时间为 psutil 进程树采样的累计可观测值，包含监测开销；子进程退出前取可观测累计峰值，不能冒充精确硬件 CPU 计数器。CPU 百分比按一个逻辑核=100%；本机 18 核的整机占比约再除以 18。显存是整卡观测，存在其他程序负载。

| 后端 | CPU 秒范围 | 内存峰值 MiB 范围 | 整卡显存峰值 MiB 范围 | 暖滚动 >50ms 次数/240 |
|---|---:|---:|---:|---:|
| cpu | 10.5–11.5 | 833.3–839.9 | 5066.2–5079.6 | 6 |
| gpu | 13.0–14.0 | 954.2–961.2 | 5228.2–5234.8 | 7 |
| gpu-raster | 10.4–10.9 | 920.7–928.9 | 5200.7–5204.6 | 22 |

CPU/合成/GPU 栅格路线的平均单核等效占用范围分别为 91.5%–97.8%、103.5%–111.5%、88.9%–93.5%；折算整机占比约 5%–6%。整卡 GPU 利用率的各轮中位数为 38%–39%，不能将其中 Moonlight/DWM 等负载归给 InkStruct。暖滚动输入最大间隔分别为 56.47、68.68、68.36 ms。

正式滚动逐动作迟到、最大输入间隔、缓存未就绪、paint 原始样本和整卡 GPU 利用率/功率在原始 JSON；汇总在 summary.json。暖缓存尾部仍有明显停顿，GPU 栅格化没有解决全部滚动卡顿，不能据栅格微基准声称整段预览都更流畅。

## 候选批量计算

真实作者档案为 `artifacts/v61_collection_acceptance_20261013/run_v3_with_validation/source_archive.json`，使用当前 v6.2 语义实现、实际结构修正和所有合格供体。这份档案含历史验证样本，仅作开发性能/正确性输入，不是独立无泄漏的质量评测。全结构库 9574 字中等距抽样并显式加入孔、正等回归，共 522 字、5946 笔查询、98 种实际语义候选池、1,423,811 个候选/目标对。没有删候选、降精度、放宽映射和几何门槛。

CPU 基线逐查询沿用现有 BatchAuthorStrokeFallback 的 NumPy 候选向量化计算；不是低效逐笔 Python 拟合对照。GPU 用 FP64、关闭 FMA 合并，候选描述符驻留设备，查询分批最多 256 个，同步事件后取计时。原有同字排除、实际笔形语义、映射门槛、排序及完整顶点碰撞校验均留在原实现。

当前安全实验对全部候选重新做 CPU 数值复核并以 CPU 数值作为最终依据，覆盖临界门槛、近分、并列与拒绝项；没有用未经证明的 GPU 误差容限剪枝。这个策略保守且有明确成本。它不能代表未来选择性复核的最佳可能性能。

每项 5 轮，单位为秒，中位数 / P95：

| 5946 笔查询阶段 | 时间 |
|---|---:|
| 现有 NumPy 拟合与评分 | 0.73 / 0.74 |
| GPU 设备事件计算 | 0.06 / 0.09 |
| 候选/查询传输与分配 | 0.02 / 0.02 |
| 结果读回 | 0.04 / 0.05 |
| GPU 路线在 CPU 复核之前（含打包/传输/同步） | 0.34 / 0.37 |
| 完整 CPU 复核与比对 | 0.96 / 0.98 |
| GPU 路线含复核总计 | 1.30 / 1.32 |

CPU 档案读取 0.305s，候选池与描述符准备 3.067s，语义池/目标查询准备 4.199s，均未因 GPU 加速。设备事件时间不能单独用于宣称完整任务提速。

冷 GPU（3 个新进程、各自空内核缓存）分项，单位 ms：

| 分项 | 中位数 / P95 |
|---|---:|
| CuPy 导入及设备初始化 | 329.89 / 368.77 |
| 首个查询候选打包 | 0.14 / 0.16 |
| 候选 H2D | 1.36 / 1.49 |
| 查询 H2D/分配 | 0.11 / 0.11 |
| 首次 JIT/设备提交同步墙钟 | 140.80 / 146.50 |
| 结果 D2H | 0.12 / 0.15 |
| 首次计算链总计（不含初始化及复核） | 142.41 / 148.41 |
| 同进程暖查询总计 | 0.22 / 2.16 |

冷 JIT 时间不是纯内核执行。首次事件范围可能包含主机编译/等待，故单独报告墙钟；稳定运行的 device_s 计时已等待设备完成。初始 CuPy show_config 查询可选库的长等待只作为诊断，不计入任何正式计算结论。

同一真实最大池（399 候选）上的不同查询规模，数据驻留且不含 CPU 复核，单位 ms：

| 不同真实查询数 | NumPy | GPU 传输/计算/读回总计 |
|---|---:|---:|
| 1 | 0.21 / 0.30 | 0.32 / 1.50 |
| 8 | 1.37 / 2.05 | 0.44 / 1.95 |
| 32 | 5.43 / 6.45 | 0.98 / 2.12 |
| 128 | 24.32 / 34.80 | 1.77 / 2.03 |
| 256 | 50.18 / 58.43 | 3.85 / 5.50 |

单查询不适合 GPU；达到数十至数百个同池真实查询，原始设备路径更有潜力。但实际任务有多个不同大小的语义池，不能用最大池的数字外推整库。

另捕获真实 11 字中的 362 次完整组件拟合，按点数/轴模式分 8 组，与跨候选 NumPy 批量实现比较。NumPy 0.47 / 0.65 ms；驻留 GPU 含读回 0.63 / 1.77 ms；加 CPU 权威复算 1.27 / 2.56 ms，另有首次上传 2.30 ms。该规模不值得 GPU。组件的轴缩放后重采样评分、规则和碰撞仍在 CPU；没有声称已完成全库组件 GPU 加速。

624 项真实选择的交错对照还包含语义筛选、排序和完整顶点碰撞：CPU 累计 3.118 s，GPU 加权威复核累计 3.966 s。它是同一批输入的单轮阶段隔离核验，不能代替上述多轮拟合计时或完整生成总时长；全部拒绝理由及 CPU/GPU 输出载荷保存在 `decision-payloads.jsonl`。

完整 v6.2 11 字小样：孔正址兄礼烧止怔歪羊群。每路线 3 轮，GPU 在每条实际回退查询使用计算原型，其余生成核心不变。单位秒：

| 路线 | 任务本体中位数/P95 | 加后端初始化中位数/P95 |
|---|---:|---:|
| CPU | 30.32 / 30.47 | 30.32 / 30.47 |
| GPU＋CPU 全复核 | 30.55 / 30.68 | 30.86 / 31.08 |

完整任务使用已存在的 CUDA 编译缓存；上表另加 CuPy/设备初始化，空缓存 JIT 代价见前表。这里只生成 11 字验证供体和写出，未重跑全库、未制作或发布新字体。完整任务未提速，且阶段差异接近环境波动，不能给出全库生成加速承诺。

## 正确性、回归与保全

- 9 次正式预览的全部页面 SVG 哈希、页序、文字坐标和冻结选样一致；编辑后的几何也一致。真实选字 handler 已测。可见数字编辑使用确定的新源码身份，CPU/GPU 字形选择和几何一致，未改用户原文档。
- 624 次完整选择/碰撞比较，566 次接受供体；全部接受/拒绝、供体、轨迹、压力、时间和诊断证据精确一致。是在真实修正参考上下文中隔离测选择，不能当作新生成的 59 字字体质量结论。
- 六轮完整 11 字任务共 66 个压缩载荷解包后与既有 0.1.32 release-run **全部字段精确一致**。孔第 4 笔参考缺口和羊的原有来源警告保留，正没有新增缺口。数值最大绝对误差 3.55e-15；CPU 权威复核使最终输出不受其影响。
- 0.1.32 真实 v6.2 字体小文档保存重开：源码身份、选样、文档设置、评价与 SVG 字节一致；字体来源警告仍可见。
- 原应用环境相关测试 **48 passed**：continuous preview、preview process/serialization、document package、plotter、v6.2 semantics。不是历史 macOS 记录。
- 本轮基线 1225 个文件和上一交付清单 3206 个文件校验均无变化/缺失。另有上一轮已列明的 3 个不可读字体路径未恢复、未覆盖。本轮保全不对这些原先不可读文件作内容完整性承诺。原 .venv 的包清单另行核对。

未验证：其他 GPU/驱动、AMD/Intel CUDA 替代后端、Vulkan/DirectML、无显卡机器、多个屏幕/DPI、长期显存压力、全库完整生成端到端耗时、具有可靠误差界的选择性 CPU 复核、光电/PresentMon 展示延迟、数位板/驱动与写字机。本轮没有把这些记为通过。

## 后续最小接入范围与成本

建议优先保留 CPU 默认路径，只在实验开关下接入 GPU SVG 栅格工作进程。复用现有 SVG、分块、像素传输和缓存，避免修改 Markdown、公式、模板、字形或导出协议。图形上下文创建失败、软件 renderer、渲染失败、超时或显存预算不足时回退原 CPU 进程；回退必须可诊断。考虑延迟/预热上下文、只对密集页和高 DPI 使用 GPU，并复测冷首开、暖滚动 P95 和功耗。8×MSAA 的实际显存远大于单张 ARGB 字节数，预算需包含多采样、resolve、读回及缓存。

Qt 路线可复用现有 PySide6 模块，但正式冻结包需纳入 QtOpenGL 依赖、驱动故障回退和跨设备图像回归；不能直接把实验 worker 当生产交付。候选 GPU 路线则额外维护 CuPy/CUDA wheel、设备缓存、同步、FP64 数值与临界排序复核；本机实际收益不足以支持当前维护成本。若继续研究，先证明误差界并与更好的 CPU 批量/缓存方案一起比较，再决定是否接入。

## 复现与产物

原始目录：`C:\Users\lee\Documents\InkStructApp\InkStruct-Windows-Dev\artifacts\gpu_benefit_20261020`。实验源码：`scripts/gpu_experiment/`。`summary.json` 为汇总；`preview-*-8/9/10.json` 为正式滚动，`preview-*-open-4/5/6.json` 为首开，`preview-*-edit-1/2/3.json` 为可见内容编辑；对应 PNG 为画面证据。`raster.json`、`raster-worker-*.jsonl`、`candidate-stage.json`、`component-stage.json`、`cold-fit-*.json`、`decisions.json`、`decision-payloads.jsonl`、`pipeline-*` 及 profiler 文件保留原始分项与正确性载荷。`verification.json` 和 `regression.log` 记录保全/回归。

在项目根目录执行。先选择一个全新输出目录，避免覆盖本轮结果；保持窗口前台，不同时运行其他实验。以下为 PowerShell：

```powershell
$env:INKSTRUCT_GPU_EXPERIMENT_OUT = 'artifacts/gpu_benefit_NEW_RUN'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
# 首次建立环境；已存在时不要重新创建或覆盖
.venv/Scripts/python.exe -m venv .venv-gpu-experiment
.venv-gpu-experiment/Scripts/python.exe -m pip install cupy-cuda13x==14.2.0 numpy==2.5.4 psutil==7.2.2 nvidia-cuda-runtime==13.4.92 nvidia-cuda-nvrtc==13.4.92
.venv/Scripts/python.exe scripts/gpu_experiment/initialize.py
.venv-gpu-experiment/Scripts/python.exe scripts/gpu_experiment/run_suite.py preview
.venv-gpu-experiment/Scripts/python.exe scripts/gpu_experiment/run_suite.py engine
.venv-gpu-experiment/Scripts/python.exe scripts/gpu_experiment/run_suite.py open
.venv-gpu-experiment/Scripts/python.exe scripts/gpu_experiment/run_suite.py edit
.venv-gpu-experiment/Scripts/python.exe scripts/gpu_experiment/raster.py
.venv-gpu-experiment/Scripts/python.exe scripts/gpu_experiment/baseline_parts.py
.venv-gpu-experiment/Scripts/python.exe scripts/gpu_experiment/candidates.py stage
.venv-gpu-experiment/Scripts/python.exe scripts/gpu_experiment/run_suite.py cold
.venv-gpu-experiment/Scripts/python.exe scripts/gpu_experiment/run_suite.py pipeline
.venv-gpu-experiment/Scripts/python.exe scripts/gpu_experiment/components.py
.venv-gpu-experiment/Scripts/python.exe scripts/gpu_experiment/decisions.py
.venv-gpu-experiment/Scripts/python.exe scripts/gpu_experiment/verify.py
.venv-gpu-experiment/Scripts/python.exe scripts/gpu_experiment/checks.py
.venv-gpu-experiment/Scripts/python.exe scripts/gpu_experiment/analyze.py
```

实验脚本只应由这些独立入口运行，默认应用没有导入它们。run_suite 会拒绝覆盖已有日志；其他脚本也应只在新目录执行。保留独立环境便于复测，仅清除本轮明确可重建的项目临时目录、绘图配置和 CUDA 编译缓存；原始测量、输入校验值、SVG、文档、日志和代码快照保留。之后若正式交付，再依据当时 APP_VERSION 递增并做 Windows 双 EXE 构建验收。

技术依据：[CuPy 官方安装说明](https://docs.cupy.dev/en/stable/install.html)、[Qt QOpenGLWidget 绘制与 frameSwapped 说明](https://doc.qt.io/qt-6/qopenglwidget.html)。它们只用于后端选择和计时语义，性能结论来自本地实际测量。
