# InkStruct（墨构）完整使用手册

本文档覆盖 InkStruct `0.2.0` 的安装、轨迹采集、样本导入、风格建档、补采规划、个性化生成、评估、训练、实验、便携版打包、数据协议和故障排查。

除非特别说明，所有命令都在项目根目录执行。Windows PowerShell 是当前仓库已验证的主环境；Linux/macOS 仅给出通用 Python CLI 形式，不代表桌面应用和打包流程已经过同等验收。

## 目录

- [选择使用方式](#选择使用方式)
- [安装与环境准备](#安装与环境准备)
- [GUI 快速开始](#gui-快速开始)
- [CLI 快速开始](#cli-快速开始)
- [轨迹采集器](#轨迹采集器)
- [风格生成器](#风格生成器)
- [完整 CLI 工作流](#完整-cli-工作流)
- [训练与模型检查点](#训练与模型检查点)
- [可复现实验](#可复现实验)
- [Windows 便携采集器打包](#windows-便携采集器打包)
- [数据协议参考](#数据协议参考)
- [产物目录与文件用途](#产物目录与文件用途)
- [测试和代码检查](#测试和代码检查)
- [复现、备份与安全清理](#复现备份与安全清理)
- [故障排查](#故障排查)

## 选择使用方式

| 需求 | 推荐入口 | 所需依赖 |
| --- | --- | --- |
| 只生成轨迹，不使用图形界面 | `inkstruct generate` | 基础依赖，CPU 即可 |
| 从原始 JSON 建档并生成 | `samples import` → `profile build` → `generate` | 基础依赖，CPU 即可 |
| 使用图形界面导入和生成 | `run_inkstruct_generator.cmd` | `desktop` 可选依赖 |
| 在项目源码环境采集轨迹 | `run_inkstruct_collector.cmd` | `desktop` + 相邻 `data_collection` 内核 |
| 在另一台 Windows 机器采集 | `release/InkStructCollector/InkStructCollector.exe` | 使用完整便携目录，无需 Python |
| 训练实验模型 | `inkstruct train` | `train` 依赖、CUDA、NVIDIA GPU、CASIA LMDB |
| 复现预算、消融或盲评 | `inkstruct experiment ...` | 根据实验是否调用模型决定，通常需要开发依赖 |

最稳定的生产路径是不带 `--checkpoint` 的确定性生成。训练路径不是初次使用的前置条件。

## 安装与环境准备

### 系统要求

- Python 3.12 或 3.13；项目约束为 `>=3.12,<3.14`。
- Windows 10/11 是当前主要验证平台。
- 确定性生成、结构处理、采集、评估和大多数测试可使用 CPU。
- 桌面应用需要 PySide6 6.9.2。
- 训练以及带 `--checkpoint` 的学习模型推理必须使用支持 CUDA 的 NVIDIA GPU；确定性生成不需要 GPU。
- 完整结构构建需要仓库中的 `third_party/makemeahanzi/graphics.txt` 与 `dictionary.txt`。

### 依赖组合

`pyproject.toml` 定义了以下安装组合：

| 组合 | 内容 | 使用场景 |
| --- | --- | --- |
| 基础 | NumPy、Pillow | 结构、导入、建档、确定性生成、SVG/PNG、评估 |
| `desktop` | PySide6 6.9.2 | 采集器和生成器 GUI |
| `train` | PyTorch、h5py、lmdb | 模型训练、检查点推理、CASIA 数据 |
| `dev` | pytest、Ruff | 测试和代码检查 |

### Windows PowerShell 安装

创建独立虚拟环境并安装常用的桌面与开发能力：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[desktop,dev]"
```

只需要命令行和确定性生成时：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .
```

需要训练时，先按照本机显卡驱动和 CUDA 兼容情况安装合适的 PyTorch，再安装训练依赖：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[train,dev]"
```

仓库的 `requirements.lock` 记录了当前 Windows/CUDA 环境中的完整版本，但 CUDA 版 PyTorch 与显卡驱动强相关，不应在不同机器上盲目照搬。

### 通用 Python CLI 安装

在支持 Python 3.12/3.13 的类 Unix shell 中，可以使用：

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e .
```

之后可运行 `.venv/bin/inkstruct`。桌面端和 Windows 打包脚本没有在本文档中声明跨平台验收。

### `setup_windows.ps1` 的适用范围

`scripts/setup_windows.ps1` 是特定 Windows/CUDA 环境的重建脚本，会：

1. 使用 `venv --clear` 清空并重建 `.venv`；
2. 从 CUDA 12.8 索引安装 PyTorch；
3. 安装桌面、开发、h5py 和 lmdb 依赖；
4. 检查 CUDA；
5. 运行测试。

脚本默认 Python 路径是开发环境中的绝对路径。只有在确认要重建 `.venv` 后才使用，并显式传入本机 Python：

```powershell
.\scripts\setup_windows.ps1 -Python "C:\Path\To\python.exe"
```

### 环境验证

```powershell
.\.venv\Scripts\inkstruct.exe --version
.\.venv\Scripts\python.exe -c "import inkstruct, numpy, PIL; print('imports OK')"
.\.venv\Scripts\inkstruct.exe structures info
```

预期 CLI 版本为：

```text
InkStruct 0.2.0
```

`structures info` 成功时会输出结构 Schema、来源提交、字符数和部件回退数量。当前仓库的结构库包含 9,574 字。

检查桌面依赖：

```powershell
.\.venv\Scripts\python.exe -c "import PySide6; print(PySide6.__version__)"
```

检查训练环境：

```powershell
.\.venv\Scripts\python.exe -c "import torch; print(torch.__version__); print(torch.cuda.is_available()); print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CUDA unavailable')"
```

## GUI 快速开始

### 采集器

1. 确认 `artifacts/structures/characters.sqlite3` 存在。
2. 源码运行时确认以下任一采集器内核存在：
   - `legacy/data_collection/handwriting_collector/ui.py`；
   - 项目相邻的 `../data_collection/handwriting_collector/ui.py`。
3. 双击 `run_inkstruct_collector.cmd`。
4. 首次运行选择单独的数据输出目录。
5. 填写稳定的书写者 ID，例如 `user_001`。
6. 导入 TXT/CSV 字表，按提示书写并保存。

如果使用便携版，直接运行完整目录中的 `release/InkStructCollector/InkStructCollector.exe`，不要只复制 EXE。

### 生成器

1. 双击 `run_inkstruct_generator.cmd`。
2. 填写与采集时完全相同的用户 ID。
3. 选择采集输出目录下的 `samples/<writer-id>` 目录。
4. 依次点击“1. 导入”“2. 建档”“3. 生成”。
5. 默认保留“自适应融合（推荐）”和强度 `1.0`。

导入、建档和生成在后台线程执行；日志框会显示结果 JSON。全量生成可以取消，当前字符写完后停止。产物协议支持断点续跑；需要精确续接同一运行目录时，请使用 CLI 固定 `--run-id`。

## CLI 快速开始

以下示例假设原始单字 JSON 位于 `D:\Handwriting\samples\user_001`。

### 1. 检查结构库

```powershell
.\.venv\Scripts\inkstruct.exe structures info
```

如果数据库不存在，可重建：

```powershell
.\.venv\Scripts\inkstruct.exe structures build
```

### 2. 导入样本

```powershell
.\.venv\Scripts\inkstruct.exe samples import `
  "D:\Handwriting\samples\user_001" `
  --writer user_001
```

查看命令输出中的 `accepted_count`、`rejected_count` 和 `rejected`，不要在存在大量拒绝样本时直接建档。

### 3. 建立风格档案

```powershell
.\.venv\Scripts\inkstruct.exe profile build --writer user_001
```

默认读取：

```text
artifacts/samples/user_001/index.jsonl
```

默认生成：

```text
profiles/user_001/<profile-version>.json
profiles/user_001/profile.json
```

### 4. 生成文本

```powershell
.\.venv\Scripts\inkstruct.exe generate `
  --writer user_001 `
  --text "墨构手写" `
  --run-id quick_start
```

结果位于：

```text
outputs/user_001/quick_start/
```

### 5. 检查结果

```powershell
.\.venv\Scripts\inkstruct.exe evaluate `
  --run outputs\user_001\quick_start
```

成功生成目录仍应检查 `manifest.json` 中的 `failed_count`，评估目录还会新增 `evaluation.json`。

## 轨迹采集器

### 源码版和便携版区别

| 项目 | 源码版 | Windows 便携版 |
| --- | --- | --- |
| 启动 | `run_inkstruct_collector.cmd` 或 `inkstruct collector` | `InkStructCollector.exe` |
| Python/PySide6 | 需要 | 已打包 |
| `data_collection` 源码 | 需要 | 不需要 |
| 结构数据库 | 从项目 `artifacts/structures` 读取 | 使用打包的压缩笔数/笔顺参考 |
| PyTorch/CUDA | 不需要 | 不包含 |
| 生成器 | 另行启动 | 不包含 |
| 推荐用途 | 开发和联调 | 在采集机器上分发使用 |

便携版采用 PyInstaller `onedir`，`_internal` 和其他随附文件是运行所必需的。整体复制 `InkStructCollector` 文件夹，不要只发送 EXE。

### 字表格式

采集器的“单字任务采集”支持 UTF-8/UTF-8 BOM 的 TXT 和 CSV。

#### TXT

TXT 中每个非空白 CJK 统一汉字会成为一个任务项，重复字符只保留首次出现。示例：

```text
中国书法
墨构永和
```

标点、拉丁字母或其他非 CJK 字符会导致导入错误，不会被静默忽略。

#### CSV

CSV 必须包含 `character` 列，可选 `repeats` 列。额外列会被忽略，因此补采推荐 CSV 可以直接导入。

```csv
character,repeats,purpose,reason
永,3,anchor,稳定性锚点
构,2,coverage,补充部件覆盖
```

规则如下：

- `character` 必须恰好是一个 CJK 统一汉字；
- `repeats` 留空时使用导入对话框中的默认重复次数；
- `repeats` 必须是大于等于 1 的整数；
- 同一字符只接受 CSV 中第一次出现的记录。

### 书写和保存流程

1. 首次运行选择输出根目录。建议使用专用数据目录，不要选择程序目录或便携版 `_internal`。
2. 填写书写者 ID。ID 会写入任务和样本；任务开始后字段会锁定。
3. 点击“导入 TXT / CSV”，选择默认重复次数并填写任务名称。
4. 在田字格中按标准笔顺书写当前字。
5. 左侧参考图显示标准笔画：
   - 正在落笔时，绿色表示当前笔；
   - 抬笔等待时，绿色表示下一笔；
   - 已完成笔画为深灰色，后续笔画为浅灰色；
   - 绿色圆点表示参考起笔位置。
6. 确认“当前笔数 / 标准笔数”为正确状态。
7. 点击“保存并下一个”或按 Enter。

常用操作：

| 操作 | 按钮 | 快捷键 |
| --- | --- | --- |
| 撤销上一笔 | 撤销上一笔 | `Ctrl+Z` |
| 清空当前字符 | 重写当前字 | `Delete` |
| 保存并进入下一项 | 保存并下一个 | `Enter` |
| 暂不采集当前项 | 暂时跳过 | 无默认快捷键 |

笔画数不匹配、字符不在结构库或没有有效轨迹时，保存按钮不可用或保存操作会被拒绝。笔顺参考只提供视觉提示，不会修改坐标、压力或时间。

### 任务恢复

采集器将任务状态写入输出目录的 `tasks/<task-id>/state.json`。重新启动后可点击“继续未完成任务”。如果样本已完成原子写入但任务状态尚未更新，恢复过程会根据样本中的 `task_id` 和 `item_id` 调和进度。

请始终使用同一输出根目录恢复任务。换目录会看到另一组任务状态。

### 采集输出

单字 JSON 路径为：

```text
<输出目录>/samples/<writer-id>/U+XXXX/<sample-id>.json
```

采集内核还会生成兼容旧工具的 `legacy/` 产物。InkStruct 的 `samples import` 只需要 `handwriting_single_v1` JSON，不要求旧格式文件。

```text
<输出目录>/
├─ tasks/<task-id>/state.json
├─ samples/<writer-id>/U+XXXX/<sample-id>.json
├─ legacy/<writer-id>/<sample-id>.npy
└─ legacy/<writer-id>/<sample-id>/
   ├─ point_seq.txt
   ├─ line_text.txt
   ├─ char_points_idx.txt
   └─ writer_id.txt
```

### 关于整行采集标签页

底层 `data_collection` 内核还提供整行采集和 DiffInk HDF5 导出。整行原始协议是 `handwriting_line_raw_v1`，不是 InkStruct `samples import` 当前接受的 `handwriting_single_v1`。如果目标是建立 InkStruct 个人风格档案，请使用“单字任务采集”标签页。

## 风格生成器

### 启动

```powershell
.\run_inkstruct_generator.cmd
```

或：

```powershell
.\.venv\Scripts\inkstruct.exe generator
```

`inkstruct desktop` 是兼容旧调用的弃用别名，新的脚本和文档应使用 `generator`。

### 界面字段

| 字段 | 说明 |
| --- | --- |
| 用户 ID | 必须与样本 JSON 的 `writer_id` 完全一致 |
| 单字 JSON 目录 | 递归扫描其中所有 `.json` 文件 |
| 生成内容 | 未勾选全量模式时逐字符生成；重复字符会去重 |
| 生成全部支持字符 | 使用结构库中的全部 9,574 字，可断点续跑 |
| 部件生成 | `adaptive`、`off`、`stroke`、`layout`、`full` |
| 部件强度 | 0.0–1.5；常规默认 1.0 |

### 三步工作流

#### 1. 导入

读取选定目录中的原始 JSON，输出到：

```text
artifacts/samples/<writer-id>/index.jsonl
artifacts/samples/<writer-id>/import_report.json
```

原始 JSON 不会复制或修改。

#### 2. 建档

读取默认索引和结构库，生成：

```text
profiles/<writer-id>/<profile-version>.json
profiles/<writer-id>/profile.json
```

日志会显示样本数、字符数、传统原型数、部件布局、部件笔画、部件关系和整组部件轨迹数量。

#### 3. 生成

读取缓存档案，生成到 `outputs/<writer-id>/<run-id>/`。GUI 自动创建 run ID；指定文本为空且未选择全量时不会产生有意义的目标集合。

全量生成时“取消当前批量生成”会设置取消请求，当前字符写完后停止，并将 manifest 状态写为 `cancelled`。重新使用同一 run ID 才能严格续接原目录；GUI 当前未提供手动 run ID 字段，需精确控制续跑时建议使用 CLI。

### 部件模式建议

- 常规使用：`adaptive`，强度 `1.0`。
- 观察不启用部件层的基线：`off`。
- 调试部件笔画或布局贡献：`stroke` / `layout`。
- 固定消融：`full`，不要把结果默认解释为最佳生成质量。

GUI 底部的 CUDA 状态不影响确定性生成。显示“PyTorch 未安装”或“CUDA 不可用”时，仍可完成导入、建档和默认生成。

## 完整 CLI 工作流

### 调用方式和通用规则

Windows 安装入口：

```powershell
.\.venv\Scripts\inkstruct.exe --help
```

等价模块入口：

```powershell
.\.venv\Scripts\python.exe -m inkstruct.cli --help
```

常用规则：

- 相对路径按当前工作目录解析；建议始终从项目根目录运行。
- 包含空格或非 ASCII 字符的路径必须加引号。
- Windows PowerShell 使用反引号 `` ` `` 续行，反引号后不能再有空格。
- 所有主要命令把结果以 UTF-8 JSON 输出到终端。
- `generate` 有任何目标失败时返回退出码 2；`evaluate` 有结构失败时返回退出码 2。
- argparse 参数错误也返回 2；未捕获的文件、数据或运行时异常返回非零状态并显示错误。

### 结构库：`structures`

#### `structures build`

```powershell
.\.venv\Scripts\inkstruct.exe structures build
```

| 参数 | 必需 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `--graphics` | 否 | `third_party/makemeahanzi/graphics.txt` | 标准笔画中心线 JSONL |
| `--dictionary` | 否 | `third_party/makemeahanzi/dictionary.txt` | 字典和 IDS 信息 JSONL |
| `--database` | 否 | `artifacts/structures/characters.sqlite3` | 输出 SQLite 数据库 |
| `--simplified` | 否 | `data/CASIA_CHINESE/character_dict.pkl` | 可选简体字符集合；路径不存在时按空集合处理 |

构建采用 `.building` 临时数据库并在成功后原子替换目标。数据库同目录还会写入：

- `build_report.json`：接受/拒绝数量和来源许可；
- `component_fallback_report.json`：部件拆分不完整、需要回退的字符。

自定义输入示例：

```powershell
.\.venv\Scripts\inkstruct.exe structures build `
  --graphics "D:\Data\makemeahanzi\graphics.txt" `
  --dictionary "D:\Data\makemeahanzi\dictionary.txt" `
  --database artifacts\structures\custom.sqlite3
```

#### `structures info`

```powershell
.\.venv\Scripts\inkstruct.exe structures info
```

| 参数 | 必需 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `--database` | 否 | `artifacts/structures/characters.sqlite3` | 要检查的数据库 |

输出包括 Schema、创建时间、数据来源、来源版本、坐标系、完整/回退部件数量和字符总数。

#### `structures export-packages`

```powershell
.\.venv\Scripts\inkstruct.exe structures export-packages `
  --output-dir configs\character_packages
```

| 参数 | 必需 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `--database` | 否 | 默认结构数据库 | 输入数据库 |
| `--output-dir` | 是 | 无 | 输出目录 |

输出两份 UTF-8 BOM CSV 和一份报告：

- `mainland_standard_simplified_gb2312_characters.csv`；
- `non_mainland_standard_simplified_characters.csv`；
- `character_packages_report.json`。

CSV 字段包括 `character`、`codepoint`、`package`、`locale`、`stroke_count`、`component_status` 和 `decomposition`。

### 样本：`samples`

#### `samples import`

```powershell
.\.venv\Scripts\inkstruct.exe samples import `
  "D:\Handwriting\samples\user_001" `
  --writer user_001
```

| 参数 | 必需 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `source` | 是 | 无 | 递归扫描 `.json` 的目录 |
| `--writer` | 是 | 无 | 期望的书写者 ID |
| `--destination` | 否 | `artifacts/samples` | 索引根目录 |

输出位于 `<destination>/<writer-id>/index.jsonl` 和 `import_report.json`。导入器不复制源文件。拒绝原因可能包括 Schema 不支持、writer 不一致、字符不是单个 Unicode 字符、画布非法、空笔画、越界坐标、压力越界或时间戳不单调。

#### `samples merge`

```powershell
.\.venv\Scripts\inkstruct.exe samples merge `
  artifacts\samples_batch_1\user_001\index.jsonl `
  artifacts\samples_batch_2\user_001\index.jsonl `
  --writer user_001
```

| 参数 | 必需 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `indexes` | 是，至少两个 | 无 | 要合并的一个或多个索引参数；实现要求至少两个 |
| `--writer` | 是 | 无 | 所有样本必须匹配的 writer |
| `--destination` | 否 | `artifacts/samples_merged` | 新索引根目录 |

合并先按 `sample_id`，再按源文件 SHA-256 去重。同 ID 同内容记为重复；同 ID 不同内容记为冲突并省略后到样本，不会覆盖。输出 `index.jsonl` 和 `merge_report.json`，源索引保持不变。

#### `samples audit`

```powershell
.\.venv\Scripts\inkstruct.exe samples audit --writer user_001
```

| 参数 | 必需 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `--writer` | 是 | 无 | 书写者 ID |
| `--index` | 否 | `artifacts/samples/<writer>/index.jsonl` | 待检查索引 |
| `--database` | 否 | 默认结构数据库 | 标准结构来源 |
| `--confidence-threshold` | 否 | `0.5` | `[0,1]` 内的对齐置信阈值 |
| `--output` | 否 | `artifacts/collection/<writer>/rerecord_current.csv` | 重录 CSV |

审计识别：

- 结构库不支持的字符；
- 笔画数不匹配；
- 低置信对齐；
- 证据不足的疑似错序；
- 已被高置信纠正的笔顺排列。

输出 CSV 可直接导入采集器；同目录还会写同名 `.json` 报告。`corrected` 样本会单独列入报告，但不一定要求重录；`ambiguous` 样本会进入重录任务并从局部档案抽取中隔离。

#### `samples replace`

重录完成后，先将新 JSON 导入为一个独立替换索引，再根据旧审计报告创建新修订索引：

```powershell
.\.venv\Scripts\inkstruct.exe samples replace `
  artifacts\samples\user_001\index.jsonl `
  artifacts\replacement_samples\user_001\index.jsonl `
  --writer user_001 `
  --audit-report artifacts\collection\user_001\rerecord_current.json
```

| 参数 | 必需 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `index` | 是 | 无 | 原索引 |
| `replacement_index` | 是 | 无 | 已验证的新样本索引 |
| `--writer` | 是 | 无 | 书写者 ID |
| `--audit-report` | 是 | 无 | `samples audit` 生成的 JSON |
| `--destination` | 否 | `artifacts/samples_revised` | 新修订索引根目录 |

命令从审计报告的 `source_sample_ids` 得到被替换 ID，保留其他样本并加入替换索引。源索引不修改。ID 冲突、payload 重复或空替换集合会报错。

### 风格档案：`profile build`

```powershell
.\.venv\Scripts\inkstruct.exe profile build --writer user_001
```

| 参数 | 必需 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `--writer` | 是 | 无 | 书写者 ID |
| `--index` | 否 | `artifacts/samples/<writer>/index.jsonl` | 输入索引 |
| `--database` | 否 | 默认结构数据库 | 结构来源 |
| `--destination` | 否 | `profiles` | 档案根目录 |
| `--style-checkpoint` | 否 | 无 | 可选的因子化风格编码器检查点 |

默认输出：

```text
profiles/<writer-id>/<profile-version>.json
profiles/<writer-id>/profile.json
```

版本文件只在不存在时写入；`profile.json` 原子更新为当前档案。没有 `--style-checkpoint` 时为 `style_profile_v4`；成功加入因子化风格时为 `style_profile_v5`。终端摘要包含样本、字符、各类原型、排除样本和因子化风格状态。

使用合并索引：

```powershell
.\.venv\Scripts\inkstruct.exe profile build `
  --writer user_001 `
  --index artifacts\samples_merged\user_001\index.jsonl
```

每次换索引、结构库或风格检查点后都应重新建档，并为后续生成使用新的 run ID。

### 主动补采：`collect`

#### `collect recommend`

```powershell
.\.venv\Scripts\inkstruct.exe collect recommend `
  --writer user_001 `
  --count 200
```

| 参数 | 必需 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `--writer` | 是 | 无 | 书写者 ID |
| `--count` | 否 | `10` | 推荐新字符数 |
| `--anchors` | 否 | `20` | 现有稳定性锚点数量 |
| `--target-repeats` | 否 | `3` | 锚点目标重复次数 |
| `--index` | 否 | 默认样本索引 | 已采样字符来源 |
| `--profile` | 否 | `profiles/<writer>/profile.json` | 当前档案 |
| `--common-characters` | 否 | 包内常用字表 | 候选字符池 |
| `--database` | 否 | 默认结构数据库 | 部件频数和结构来源 |
| `--output` | 否 | `artifacts/collection/<writer>/recommendations.json` | JSON 报告路径 |
| `--strategy` | 否 | `coverage` | `coverage` 或 `information-gain` |

输出：

- `recommendations.json`：完整审计报告；
- `component_collection.csv`：可直接导入采集器；
- `component_characters.txt`：仅新字符文本。

`coverage` 主要补充部件身份、变体、角色和布局缺口；`information-gain` 适合可复现实验中的信息增益选择。推荐分数是假设新样本成功对齐并进入档案后的估计，实际采集后仍需重新导入、建档和评估。

#### `collect coverage-tiers`

```powershell
.\.venv\Scripts\inkstruct.exe collect coverage-tiers `
  --writer user_001 `
  --index artifacts\samples_merged\user_001\index.jsonl
```

| 参数 | 必需 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `--writer` | 是 | 无 | 书写者 ID |
| `--index` | 是 | 无 | 当前样本索引 |
| `--profile` | 否 | `profiles/<writer>/profile.json` | 当前档案 |
| `--target-characters` | 否 | 全部支持字符 | UTF-8 字符文本，空白忽略、按首次出现去重 |
| `--target-package` | 否 | 无 | `mainland_standard_simplified_gb2312` 或 `non_mainland_standard_simplified` |
| `--database` | 否 | 默认结构数据库 | 目标结构集合 |
| `--output` | 否 | 见下文 | JSON 报告路径 |

`--target-characters` 与 `--target-package` 互斥。未指定目标时针对全部支持字符。默认报告路径：

```text
artifacts/collection/<writer>/<target-package-or-all_supported>/target_coverage_tiers_report.json
```

命令生成：

- `target_coverage_tiers.csv`：包含所有档位归属的审计总表；
- `tier_1_to_90_0.csv`；
- `tier_2_to_95_0.csv`；
- `tier_3_to_99_0.csv`；
- `tier_4_to_99_9.csv`；
- `tier_5_to_100_0.csv`；
- `target_coverage_tiers_report.json`。

五份档位 CSV 是增量任务并兼容采集器。若只规划大陆标准简体，先导出字符包或直接使用：

```powershell
.\.venv\Scripts\inkstruct.exe collect coverage-tiers `
  --writer user_001 `
  --index artifacts\samples_merged\user_001\index.jsonl `
  --target-package mainland_standard_simplified_gb2312
```

### 生成：`generate`

指定文本和全部字符必须二选一：

```powershell
.\.venv\Scripts\inkstruct.exe generate --writer user_001 --text "中国书法"
.\.venv\Scripts\inkstruct.exe generate --writer user_001 --all-supported --run-id all_supported
```

| 参数 | 必需 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `--writer` | 是 | 无 | 书写者 ID |
| `--text` | 二选一 | 无 | 按 Unicode 字符逐个请求；重复项去重 |
| `--all-supported` | 二选一 | 关闭 | 生成结构库全部字符 |
| `--profile` | 否 | `profiles/<writer>/profile.json` | 档案文件 |
| `--database` | 否 | 默认结构数据库 | 结构来源 |
| `--output-root` | 否 | `outputs` | 生成根目录 |
| `--run-id` | 否 | UTC 时间戳加 8 位随机串 | 运行目录标识和续跑身份 |
| `--no-png` | 否 | 关闭 | 不输出 PNG；SVG 和轨迹 JSON 仍生成 |
| `--checkpoint` | 否 | 无 | v5 模型检查点，需要 `train` 依赖和 CUDA；不指定时使用确定性生成 |
| `--confidence-threshold` | 否 | 检查点校准值或安全默认 | 覆盖 writer-disjoint 校准阈值 |
| `--no-component-conditioning` | 否 | 关闭 | 兼容开关，等价于部件模式 `off` |
| `--component-mode` | 否 | `adaptive` | `off`、`stroke`、`layout`、`full`、`adaptive` |
| `--component-strength` | 否 | `1.0` | 部件影响强度；CLI 不额外限制范围 |

`--no-component-conditioning` 与 `--component-mode` 同时出现时，前者优先并强制使用 `off`。

推荐的文本生成：

```powershell
.\.venv\Scripts\inkstruct.exe generate `
  --writer user_001 `
  --text "墨构个性手写" `
  --component-mode adaptive `
  --component-strength 1.0 `
  --run-id document_demo
```

节省全量输出空间：

```powershell
.\.venv\Scripts\inkstruct.exe generate `
  --writer user_001 `
  --all-supported `
  --run-id all_supported_json_svg `
  --no-png
```

运行目录始终包含 `manifest.json`、`trajectories/` 和 `previews/`。未知字符记录在 manifest 的 `failed` 中，命令返回 2；不会替换为问号或形近字。

#### 取消和断点续跑

CLI 没有专用取消参数，可使用正常终止信号停止。再次以相同 `--writer`、`--output-root` 和 `--run-id` 运行时，已经存在的轨迹 JSON 会被跳过。

```powershell
.\.venv\Scripts\inkstruct.exe generate `
  --writer user_001 `
  --all-supported `
  --run-id all_supported
```

生成器会自动比较 `run_identity` 中的档案、结构库和模型 SHA-256，以及部件模式、强度、置信阈值、PNG 选项和边界策略。改变这些身份需要新 run ID；边界修复前的旧 manifest 也不能直接续跑。旧目录应保留用于对照。

#### 使用模型检查点

```powershell
.\.venv\Scripts\inkstruct.exe generate `
  --writer user_001 `
  --text "中国书法" `
  --checkpoint artifacts\models\v5_formal_seed2002.pt
```

检查每个轨迹的 `generator` 字段和 manifest。可能值包括模型生成、低置信确定性回退或未正式训练检查点回退。仅传入检查点不等于模型一定接管生成。

### 评估：`evaluate`

`--run` 与 `--writer` 必须二选一。

#### 结构评估

```powershell
.\.venv\Scripts\inkstruct.exe evaluate `
  --run outputs\user_001\document_demo
```

检查：

- 笔数和连续笔顺；
- 标准笔画 ID；
- 每笔最少点数；
- `[0,1]` 坐标和压力；
- 时间单调性；
- manifest 请求数、生成失败数和结构覆盖。

结果写入运行目录的 `evaluation.json`。`content_safety_passed=true` 要求无结构失败、无生成失败且检查数等于请求数。

#### 书写者留出评估

```powershell
.\.venv\Scripts\inkstruct.exe evaluate `
  --writer user_001 `
  --heldout-ratio 0.2
```

评估按字符留出，不会把同一字符的重复样本同时分到训练和隐藏集合。它临时构建训练索引、档案和隐藏字符生成，并比较标准骨架与个性化轨迹的几何距离。

| 参数 | 必需 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `--run` | 二选一 | 无 | 已生成运行目录 |
| `--writer` | 二选一 | 无 | 执行书写者评估或档案更新对比 |
| `--database` | 否 | 默认结构数据库 | 结构来源 |
| `--index` | 否 | 默认样本索引 | writer 模式输入 |
| `--heldout-ratio` | 否 | `0.2` | 允许范围 0.1–0.4 |
| `--checkpoint` | 否 | 无 | 查询生成使用的模型检查点 |
| `--style-checkpoint` | 否 | 无 | 可选 writer-disjoint 风格编码器，用于风格指标 |
| `--model-confidence-threshold` | 否 | 检查点校准值 | 模型门控阈值 |
| `--update-index` | 否 | 无 | 新增样本索引；必须和 `--reference-profile` 同时使用 |
| `--reference-profile` | 否 | 无 | 更新前档案；必须和 `--update-index` 同时使用 |
| `--heldout-count` | 否 | `12` | 档案更新对比的隐藏新字符数 |
| `--no-component-conditioning` | 否 | 关闭 | 等价部件模式 `off` |
| `--component-mode` | 否 | `adaptive` | 与生成相同的五种模式 |
| `--component-strength` | 否 | `1.0` | 部件影响强度 |
| `--output-root` | 否 | `artifacts/evaluation` | writer 评估输出根目录 |

默认 writer 评估输出：

```text
artifacts/evaluation/<writer-id>/
├─ train_index.jsonl
├─ profiles/<writer-id>/...
├─ outputs/<writer-id>/heldout/...
└─ evaluation.json
```

#### 档案更新对比

用于判断新采字符是否改善对未用于建档的新字符的迁移：

```powershell
.\.venv\Scripts\inkstruct.exe evaluate `
  --writer user_001 `
  --index artifacts\samples\user_001\index.jsonl `
  --update-index artifacts\samples_new\user_001\index.jsonl `
  --reference-profile profiles\user_001\profile.json `
  --heldout-count 12
```

`--update-index` 和 `--reference-profile` 必须一起出现。输出到 `artifacts/evaluation/<writer>/component_sample_update/`，包括旧/新生成结果、`comparison.json` 和 `comparison.png`。

### 桌面入口

| 命令 | 说明 |
| --- | --- |
| `inkstruct collector` | 启动独立采集器 |
| `inkstruct generator` | 启动独立风格生成器 |
| `inkstruct desktop` | 已弃用的生成器别名 |

这三个组把未知参数转发给对应桌面入口。`--smoke-test` 和 `--smoke-screenshot=<path>` 是开发测试参数，不属于普通用户操作界面。

## 训练与模型检查点

训练不是确定性生成的前置条件。只有在研究 v5 分层残差模型、需要验证检查点推理或复现实验时才安装训练依赖。

### 前置条件

1. NVIDIA CUDA 可用，`torch.cuda.is_available()` 返回 `True`；
2. `data/CASIA_CHINESE/train` 和 `data/CASIA_CHINESE/test` 是可读取的 CASIA LMDB；
3. `artifacts/structures/characters.sqlite3` 已构建；
4. 正式训练使用干净的 Git 工作树；
5. 训练与测试 LMDB 中不能出现相同 writer，否则程序会拒绝 writer 泄漏。

CASIA 数据不会随项目分发。请自行确认数据授权、预处理和 LMDB 内容。

### Smoke test

Smoke test 只运行一个优化步骤，用于验证数据、CUDA、前后向和保存链路：

```powershell
.\.venv\Scripts\inkstruct.exe train `
  --casia-lmdb data\CASIA_CHINESE\train `
  --test-lmdb data\CASIA_CHINESE\test `
  --database artifacts\structures\characters.sqlite3 `
  --output artifacts\models\hierarchical_residual_smoke.pt `
  --smoke
```

Smoke 检查点的 `training_status` 为 `smoke`。在正常置信阈值下，它会触发确定性回退，不能作为正式质量结论。

### 正式训练脚本

仓库提供固定三种子脚本：

```powershell
.\scripts\train_v5_formal.ps1
```

默认种子为 `1001`、`2002` 和 `3003`。指定部分种子：

```powershell
.\scripts\train_v5_formal.ps1 -Seeds 2002,3003
```

脚本的协议配置镜像位于 `configs/training/v5_formal.json`。正式脚本使用 10,000 步、batch size 8、每个 episode 8 个参考、固定 writer split、早停、置信校准、refiner、因子化风格和多尺度曲线/SDF 辅助损失。

### `train` 参数

```powershell
.\.venv\Scripts\inkstruct.exe train --help
```

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--casia-lmdb` | `data/CASIA_CHINESE/train` | 训练 LMDB |
| `--database` | `artifacts/structures/characters.sqlite3` | 结构数据库 |
| `--output` | `artifacts/models/hierarchical_residual.pt` | 最佳检查点 |
| `--steps` | `10000` | 目标训练步数；`--smoke` 时实际为 1 |
| `--batch-size` | `8` | episode batch size |
| `--max-records` | `50000` | 每个 CASIA corpus 最大读取记录数 |
| `--references` | `8` | 每个 writer episode 的参考数量 |
| `--learning-rate` | `0.0002` | AdamW 学习率 |
| `--seed` | `1001` | 训练和组批随机种子 |
| `--split-seed` | `1001` | writer 训练/验证划分种子 |
| `--resume` | 无 | 要恢复的检查点 |
| `--allow-resume-config-change` | 关闭 | 允许恢复时更改受保护配置，仅用于明确诊断 |
| `--allow-dirty` | 关闭 | 允许脏工作树上的非 smoke 训练；正式报告不得使用 |
| `--save-every` | `100` | 保存 last 检查点间隔 |
| `--validate-every` | `100` | 验证间隔，必须大于 0 |
| `--validation-episodes` | `128` | 每次验证 episode 数，必须大于 0 |
| `--early-stop-patience` | `10` | 无改善验证轮数容忍值 |
| `--early-stop-min-delta` | `0.0001` | 计为改善的最小差异 |
| `--last-output` | `<output-stem>.last<suffix>` | 最新状态检查点；不指定时从 `--output` 推导 |
| `--refiner` | 关闭 | 启用上下文 refinement |
| `--factorized-style` | 关闭 | 启用 writer-disjoint 因子化风格表示 |
| `--curve-loss-weight` | `0.0` | 曲线辅助损失权重 |
| `--sdf-loss-weight` | `0.0` | 多尺度 SDF 损失权重 |
| `--render-sizes` | `32,64` | 逗号分隔的软渲染尺寸 |
| `--validation-fraction` | `0.1` | 从训练 LMDB 按 writer 划分的验证比例 |
| `--calibrate-episodes` | `128` | 置信阈值校准 episode 数 |
| `--test-lmdb` | `data/CASIA_CHINESE/test` | 独立测试 LMDB |
| `--smoke` | 关闭 | 只运行一个优化步骤 |

### 恢复训练

```powershell
.\.venv\Scripts\inkstruct.exe train `
  --resume artifacts\models\v5_formal_seed2002.last.pt `
  --output artifacts\models\v5_formal_seed2002.pt `
  --steps 10000 `
  --seed 2002 `
  --split-seed 1001 `
  --refiner `
  --factorized-style
```

恢复会读取模型、优化器、步数、历史和随机状态。参数不兼容时默认拒绝；不要为了“让它跑起来”随意使用 `--allow-resume-config-change`，否则报告中的运行身份可能失去可比性。

### 训练输出

假设 `--output artifacts/models/model.pt`，训练会产生：

```text
artifacts/models/
├─ model.pt               最佳验证检查点
├─ model.last.pt          最新训练状态检查点
└─ model.training.json    训练报告
```

训练报告 `training_report_v1` 包含最佳/最终步数、验证值、早停状态、校准阈值、耗时、Git 信息、配置摘要、数据索引摘要、结构版本和完整历史。

### 检查点生产资格

检查点是否由模型接管生成由两个条件决定：

1. `training_status` 必须是 `formal`；
2. 推理平均置信度必须达到检查点校准阈值或显式覆盖阈值。

否则轨迹 `generator` 会标明：

- `deterministic_fallback_untrained_checkpoint`；或
- `deterministic_fallback_low_model_confidence`。

`--confidence-threshold 0` 适用于诊断完整模型推理链路，会削弱保护，不应作为生产资格证明。

## 可复现实验

实验入口：

```powershell
.\.venv\Scripts\inkstruct.exe experiment --help
```

`budget-sweep` 和 `ablate` 默认要求干净工作树，并把 Git、配置 SHA-256、索引 SHA-256、结构版本、Python、NumPy、PyTorch和 GPU 信息写入报告。`--allow-dirty` 只适合 smoke/诊断。

### 预算扫描：`budget-sweep`

```powershell
.\.venv\Scripts\inkstruct.exe experiment budget-sweep `
  --config configs\experiments\v5_budget_smoke_user001.json `
  --allow-dirty
```

| 参数 | 必需 | 说明 |
| --- | --- | --- |
| `--config` | 是 | JSON 实验配置 |
| `--allow-dirty` | 否 | 允许脏工作树，只用于 smoke |

典型配置：

```json
{
  "schema_version": "experiment_config_v1",
  "writer_id": "user_001",
  "index": "artifacts/samples_merged/user_001/index.jsonl",
  "database": "artifacts/structures/characters.sqlite3",
  "output_root": "artifacts/experiments/budget_demo",
  "seed": 1001,
  "folds": 5,
  "fold_indices": [0],
  "budgets": [8, 16, 32, "all_train"],
  "strategies": ["random", "coverage", "information-gain"],
  "random_seeds": [1001],
  "sweet_spot_strategy": "information-gain",
  "component_mode": "adaptive",
  "component_strength": 1.0
}
```

默认预算集合为 `8, 16, 24, 32, 48, 64, 96, 128, 192, all_train`，默认策略为 `random`、`coverage` 和 `information-gain`。fold 按字符分组并对布局、笔画数分层，重复字符不会跨训练/留出边界。

输出根目录包含各 fold/策略/种子/预算的临时索引和评估结果，以及 `budget_sweep_report.json`。`sweet_spot` 是配置指定策略的预算收益拐点摘要。

### 固定消融：`ablate`

```powershell
.\.venv\Scripts\inkstruct.exe experiment ablate `
  --config configs\experiments\v5_ablation_user001.json `
  --allow-dirty
```

| 参数 | 必需 | 说明 |
| --- | --- | --- |
| `--config` | 是 | 定义 writer、索引、结构库、输出和 variants |
| `--allow-dirty` | 否 | 允许脏工作树，只用于诊断 |

示例 variants：

```json
{
  "variants": [
    {"name": "skeleton", "generation": "skeleton", "component_mode": "off"},
    {"name": "v4_component_off", "component_mode": "off"},
    {"name": "v4_adaptive", "component_mode": "adaptive"},
    {"name": "v5_candidate", "component_mode": "adaptive", "checkpoint": "artifacts/models/v5.pt"}
  ]
}
```

`enabled: false` 可跳过某个 variant。输出 `ablation_report.json`，并为每个 variant 保存同一固定留出集合上的评估结果和分层摘要。

### 生成盲评包：`blind-pack`

先为同一 writer 和字符集合准备两个完整运行目录，再创建配置：

```json
{
  "schema_version": "experiment_config_v1",
  "index": "artifacts/samples_merged/user_001/index.jsonl",
  "database": "artifacts/structures/characters.sqlite3",
  "run_a": "outputs/user_001/v4_comparison",
  "run_b": "outputs/user_001/v5_comparison",
  "output_root": "artifacts/experiments/blind_pack",
  "count": 60,
  "seed": 1001,
  "method_a": "ComponentTrajectory v4 adaptive",
  "method_b": "InkStruct v5 candidate"
}
```

运行：

```powershell
.\.venv\Scripts\inkstruct.exe experiment blind-pack `
  --config configs\experiments\v5_blind_template.json
```

`blind-pack` 不接受 `--allow-dirty`。它从索引中选择同时存在于 A/B 运行的字符，按结构分层抽样，随机交换左右位置，输出：

```text
<output_root>/
├─ items/item_001.png ...
├─ blind_key.json
├─ ratings.csv
└─ manifest.json
```

每张图按“用户风格参考、左候选、右候选”排列。`blind_key.json` 含解盲信息，不应发给评分者；评分者只需要 `items/` 和自己的 `ratings.csv` 副本。

### 盲评填写和计分：`blind-score`

`ratings.csv` 列为：

```csv
rater_id,item_id,style_choice,overall_choice,notes
reviewer_01,item_001,L,R,
reviewer_01,item_002,TIE,L,
```

`style_choice` 和 `overall_choice` 接受 `L`、`R` 或 `TIE`，不区分大小写。每位评分者应使用稳定且唯一的 `rater_id`，不要共享同一 ID。

```powershell
.\.venv\Scripts\inkstruct.exe experiment blind-score `
  --pack artifacts\experiments\blind_pack `
  --ratings ratings\reviewer_01.csv ratings\reviewer_02.csv ratings\reviewer_03.csv `
  --seed 1001
```

| 参数 | 必需 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `--pack` | 是 | 无 | 含 `blind_key.json` 的盲评包目录 |
| `--ratings` | 是 | 无 | 一个或多个评分 CSV |
| `--seed` | 否 | `1001` | bootstrap 置信区间种子 |

每个条目至少需要 3 个独立 rater 才进入正式统计；不足时报告状态为探索性。结果写入 `rating_summary.json`，包括方法 B 偏好率、95% bootstrap 区间、选择计数和生产门槛状态。

## Windows 便携采集器打包

### 前置条件

- Windows x64；
- `.venv` 中已安装 PySide6 和 PyInstaller；
- 项目相邻目录 `../data_collection/handwriting_collector/ui.py` 存在；
- `artifacts/structures/characters.sqlite3` 已构建；
- 默认脚本还要求 `artifacts/collection/user_001/rerecord_current.csv` 存在；
- 当前 Python 基础环境提供脚本列出的 Conda `Library/bin` DLL。

`build_portable_collector.ps1` 包含具体 Conda DLL 名称，因此不是通用 Python/Windows 打包模板。在不同 Python 发行版上使用前应先审查脚本。

PyInstaller 不在项目的标准可选依赖中，需要单独安装：

```powershell
.\.venv\Scripts\python.exe -m pip install PyInstaller
```

### 构建目录版

```powershell
.\packaging\build_portable_collector.ps1
```

自定义输出根目录：

```powershell
.\packaging\build_portable_collector.ps1 -OutputRoot release_test
```

脚本会：

1. 从结构数据库导出压缩笔数/笔顺参考；
2. 用 PyInstaller `onedir`、`windowed` 构建；
3. 排除 torch、torchvision、h5py、matplotlib、pandas 和 scipy；
4. 复制重录任务为 `user_001_rerecord.csv`；
5. 复制便携版文字说明。

默认输出：

```text
release/InkStructCollector/
├─ InkStructCollector.exe
├─ _internal/
├─ user_001_rerecord.csv
└─ 使用说明.txt
```

### 生成 manifest 和 ZIP

```powershell
.\packaging\finalize_portable_collector.ps1
```

脚本在目录中写入 `portable_collector_manifest_v2`，计算 EXE SHA-256、payload 数量和大小，然后创建：

```text
release/InkStructCollector_portable.zip
```

终端会输出 ZIP 大小和 SHA-256。分发时同时提供哈希；接收者解压完整目录后运行 EXE。

## 数据协议参考

### `handwriting_single_v1`

这是采集器输出和 `samples import` 接受的原始单字协议。精简示例：

```json
{
  "schema_version": "handwriting_single_v1",
  "sample_id": "8a261f9b-example",
  "writer_id": "user_001",
  "character": "永",
  "codepoint": "U+6C38",
  "task": {
    "task_id": "task-example",
    "item_id": "item-example",
    "source": "characters.csv",
    "source_index": 0,
    "repeat_index": 1,
    "repeat_total": 3
  },
  "capture": {
    "created_at": "2026-08-24T10:00:00+00:00",
    "input_type": "tablet",
    "canvas_width": 640,
    "canvas_height": 640,
    "device_pixel_ratio": 1.0,
    "coordinate_space": "logical_px",
    "duration_ms": 820
  },
  "strokes": [
    {
      "stroke_index": 0,
      "points": [
        {"x": 220.0, "y": 110.0, "pressure": 0.42, "t_ms": 0},
        {"x": 410.0, "y": 118.0, "pressure": 0.61, "t_ms": 95}
      ]
    },
    {
      "stroke_index": 1,
      "points": [
        {"x": 318.0, "y": 90.0, "pressure": 0.48, "t_ms": 140},
        {"x": 320.0, "y": 500.0, "pressure": 0.67, "t_ms": 360}
      ]
    }
  ],
  "stats": {"stroke_count": 2, "point_count": 4}
}
```

上例只展示字段结构，不是“永”的完整合法标准笔画样本。采集器实际保存所有笔画，每笔通常有更多点。

导入校验规则：

- `schema_version` 必须为 `handwriting_single_v1`；
- `writer_id` 非空并等于命令的 `--writer`；
- `character` 必须恰好包含一个 Unicode 字符；
- 如果提供 `codepoint`，必须等于该字符的 `U+XXXX`；
- `capture.canvas_width` 和 `canvas_height` 是有限正数；
- `strokes` 是非空列表，每笔至少两个点；
- `x/y` 是有限数并位于画布范围内；
- `pressure` 缺省时按 `0.5`，提供时必须位于 `[0,1]`；
- `t_ms` 必须可转换为整数并在所有笔画间全局单调不减。

`task`、`stats` 和其他扩展字段可以存在；InkStruct 将整个 `capture` 字典保留在索引中。

### `sample_index_v1`

`index.jsonl` 每行是一个归一化后的 `RawSample` JSON 对象，不是包含数组的单个 JSON 文件。关键字段：

| 字段 | 含义 |
| --- | --- |
| `schema_version` | `handwriting_single_v1` |
| `sample_id` | 样本身份 |
| `writer_id` | 书写者身份 |
| `character` / `codepoint` | 单字符和规范码点 |
| `canvas_width` / `canvas_height` | 从 capture 提取的画布大小 |
| `strokes[].stroke_index` | 从 0 开始的采集笔画顺序 |
| `strokes[].points[]` | `x/y/pressure/t_ms` 原始值 |
| `source_path` | 原始 JSON 的绝对路径 |
| `source_sha256` | 原始 JSON 内容摘要 |
| `capture` | 原采集元数据 |

索引包含绝对路径，跨机器复制后需要重新导入或保证相同路径可用。不要手工编辑路径后继续把旧 SHA-256 当作有效来源证明。

### `style_profile_v4` / `style_profile_v5`

风格档案关键字段：

| 字段 | 含义 |
| --- | --- |
| `schema_version` | 无因子化模型时 v4，有因子化风格时 v5 |
| `profile_version` | 输入索引、结构和模型身份计算得到的短版本 |
| `writer_id` | 档案所属书写者 |
| `created_at` | UTC 创建时间 |
| `source_index_sha256` | 输入索引摘要 |
| `sample_count` / `character_count` | 接受进入档案的样本和字符数量 |
| `global_style` | 整体比例、偏移、倾斜、压力和时间统计 |
| `prototypes` | 传统条件化单笔原型 |
| `component_layouts` | 跨字符部件布局原型 |
| `character_layouts` | 字符专属部件布局 |
| `component_strokes` | 部件条件单笔原型 |
| `component_relations` | 兄弟部件联合布局关系 |
| `component_trajectories` | 跨字符整组部件轨迹 |
| `character_component_trajectories` | 字符直达整组部件轨迹 |
| `excluded_samples` | 因质量或歧义隔离的样本及原因 |
| `coverage` | 部件和结构证据覆盖统计 |
| `style_tokens` | 有界数量的神经风格 token |
| `factorized_style` | v5 可选 writer latent、方差和结构键 |

应用代码应使用 `profile.json` 作为“当前指针”，用 `profile_version` 固定一次运行的真实档案身份。不要仅按修改时间推断版本。

### `generation_manifest_v1`

精简示例：

```json
{
  "schema_version": "generation_manifest_v1",
  "run_id": "document_demo",
  "writer_id": "user_001",
  "status": "completed",
  "started_at": "2026-08-24T10:00:00+00:00",
  "updated_at": "2026-08-24T10:00:04+00:00",
  "elapsed_seconds": 4.231,
  "requested_count": 4,
  "completed_count": 4,
  "failed_count": 0,
  "completed_characters": "墨构手写",
  "failed": [],
  "profile_path": ".../profiles/user_001/profile.json",
  "profile_version": "example-version",
  "structure_database": ".../artifacts/structures/characters.sqlite3",
  "generator": "DeterministicGenerator",
  "component_mode": "adaptive",
  "component_strength": 1.0,
  "checkpoint": null,
  "confidence_threshold": null
}
```

`status` 可能是 `running`、`cancelled` 或 `completed`。运行过程中 manifest 会反复更新，因此外部监控应容忍读取时文件刚被替换，并以 `updated_at` 判断新旧。

### `personal_trajectory_v1`

每个字符一个 JSON：

```json
{
  "schema_version": "personal_trajectory_v1",
  "character": "构",
  "codepoint": "U+6784",
  "locale": "zh-Hans",
  "writer_id": "user_001",
  "structure_version": "bddc96d4...",
  "profile_version": "example-version",
  "generator": "deterministic_component_trajectory_v4",
  "confidence": 0.82,
  "strokes": [
    {
      "standard_stroke_id": "s1",
      "order": 1,
      "confidence": 0.87,
      "style_source": "component_trajectory_exact+layout_exact+layout_relation",
      "component_key": "木|木|left|⿰",
      "points": [
        {"x": 0.18, "y": 0.24, "t_ms": 0, "pressure": 0.43, "pen_state": "down"},
        {"x": 0.52, "y": 0.25, "t_ms": 115, "pressure": 0.61, "pen_state": "up"}
      ]
    }
  ]
}
```

为便于展示，上例只保留了第一笔；真实“构”轨迹必须包含结构库规定的全部 8 笔，才能通过结构评估。

字段说明：

- `x/y`：`[0,1]` 归一化，左上原点、Y 向下；
- `t_ms`：生成的相对时间，笔内单调不减；
- `pressure`：`[0,1]`；
- `pen_state`：`down`、`up` 或整字结束时的 `end`；
- `standard_stroke_id` 和 `order`：由结构库固定；
- `style_source`：该笔实际采用的风格来源，适合审计回退；
- `component_key`：使用部件原型时的上下文键，可能为空；
- `confidence`：几何/证据置信度，不是人类主观评分。

### 预览协议

每个轨迹都会生成 SVG；除非使用 `--no-png`，还会生成 PNG。预览用于快速检查，不是结构真值。后续程序应读取轨迹 JSON，而不是从 PNG 反推笔画。

## 产物目录与文件用途

### 常规流水线

```text
artifacts/
├─ structures/
│  ├─ characters.sqlite3
│  ├─ build_report.json
│  └─ component_fallback_report.json
├─ samples/<writer-id>/
│  ├─ index.jsonl
│  └─ import_report.json
├─ samples_merged/<writer-id>/
│  ├─ index.jsonl
│  └─ merge_report.json
├─ samples_revised/<writer-id>/
│  ├─ index.jsonl
│  └─ replacement_report.json
├─ collection/<writer-id>/
│  ├─ recommendations.json
│  ├─ component_collection.csv
│  ├─ component_characters.txt
│  ├─ rerecord_current.csv
│  ├─ rerecord_current.json
│  └─ <target>/target_coverage_tiers_*.{json,csv}
├─ evaluation/<writer-id>/...
├─ experiments/<experiment-id>/...
└─ models/
   ├─ <model>.pt
   ├─ <model>.last.pt
   └─ <model>.training.json

profiles/<writer-id>/
├─ <profile-version>.json
└─ profile.json

outputs/<writer-id>/<run-id>/
├─ manifest.json
├─ evaluation.json                 evaluate --run 后出现
├─ trajectories/
│  └─ U+XXXX.json
└─ previews/
   ├─ U+XXXX.svg
   └─ U+XXXX.png
```

### 哪些文件应备份

| 数据 | 是否可重建 | 建议 |
| --- | --- | --- |
| 原始采集 JSON | 通常不可重建 | 最高优先级，多副本备份 |
| 任务状态 | 可部分从样本调和 | 与原始样本一起备份 |
| 样本索引 | 可从原始 JSON 重建 | 备份便于复现，注意绝对路径 |
| 结构数据库 | 可从第三方固定版本重建 | 保留报告和来源提交 |
| 风格档案 | 可从索引和结构重建 | 发布结果时应固定版本文件 |
| 生成轨迹 | 可从固定档案和结构重建 | 对外发布或人工评审结果应备份 |
| PNG/SVG | 可从轨迹重建 | 空间不足时优先保留 JSON/SVG |
| 模型检查点 | 训练成本高，未必可完全复现硬件细节 | 与 training report 一起备份 |
| CASIA LMDB | 取决于数据来源 | 按数据许可独立管理 |

### Git 管理边界

`.gitignore` 默认排除：

```text
.venv/
data/
artifacts/
profiles/
outputs/
release/
*.pt
*.sqlite3
```

因此提交代码不会自动备份运行数据。反过来，也不要用 `git clean` 作为本地数据管理工具；在任何清理前先解析并确认目标目录。

## 测试和代码检查

### 全部测试

```powershell
.\.venv\Scripts\python.exe -m pytest
```

测试覆盖几何、结构、对齐、部件生成、推荐、流水线、指标、实验、因子化风格和软渲染等模块。涉及 PyTorch 的测试需要已安装训练依赖，但不一定要求执行完整训练。

### Ruff

```powershell
.\.venv\Scripts\ruff.exe check src tests scripts packaging
```

当前配置使用 Python 3.12 目标和 100 字符行宽。

### 桌面 smoke test

开发环境可使用 Qt offscreen 或桌面入口的 `--smoke-test` 做启动检查。例如：

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
.\.venv\Scripts\inkstruct.exe generator --smoke-test
.\.venv\Scripts\inkstruct.exe collector --smoke-test
Remove-Item Env:QT_QPA_PLATFORM
```

采集器 smoke test 仍要求结构数据库和 `data_collection` 内核。不要在便携版最终用户机器上把 smoke test 当作常规启动方式。

### 生成验收顺序

建议对新的档案或发布运行按以下顺序验收：

1. `structures info` 确认结构库身份；
2. 检查 `import_report.json` 的拒绝项；
3. `samples audit` 处理重录和歧义样本；
4. `profile build` 记录档案版本和排除数；
5. 小文本生成并人工查看 SVG/PNG；
6. `evaluate --run` 检查结构不变量；
7. 再开始全量生成；
8. 对质量结论使用按字符留出评估和独立盲评，而不是只看训练样本拟合。

## 复现、备份与安全清理

### 可复现运行清单

发布或记录一次生成时，至少保存：

- Git commit 和工作树状态；
- `pyproject.toml` / `requirements.lock`；
- 结构数据库元数据和 `build_report.json`；
- 样本索引 SHA-256；
- 不可变档案版本文件；
- 生成 `manifest.json`；
- 使用的模型检查点及 `.training.json`；
- 完整命令行、随机种子和实验配置；
- `evaluation.json` 或实验报告。

不要只保存 `profile.json`，因为它是可更新的当前指针。应同时保存 manifest 指向的 `<profile-version>.json`。

### 用户数据保护

- 原始样本包含书写节奏、压力和潜在设备信息，应按个人数据处理。
- `index.jsonl` 包含原始绝对路径，外发前检查用户名和目录泄露。
- 档案和生成结果可能保留可识别的个人书写风格。
- 不要把 `data/`、`artifacts/`、`profiles/` 或 `outputs/` 上传到公共仓库，除非已完成授权和脱敏审查。
- 共享盲评包时不要共享 `blind_key.json`。

### 安全清理原则

文档不提供递归删除整个工作区的命令。需要释放空间时，先逐个确认并备份具体运行目录：

- PNG 可在确认轨迹 JSON 和 SVG 完整后单独清理或在后续运行使用 `--no-png`；
- 旧输出应按明确的 `<writer-id>/<run-id>` 处理，不要对 `outputs/` 根目录使用宽泛通配；
- 旧档案版本是复现历史 manifest 的依据，不能只因为存在新的 `profile.json` 就删除；
- `.venv` 可以重建，但 `scripts/setup_windows.ps1` 会主动清空它；
- 原始采集 JSON 不应与可重建缓存放在同一清理策略中。

## 故障排查

### `Python 3.12/3.13` 找不到或版本不受支持

检查：

```powershell
py -0p
py -3.12 --version
```

项目拒绝 Python 3.11 及更早版本，也拒绝 3.14 及更新版本。使用受支持解释器重新创建 `.venv`。

### `inkstruct.exe` 不存在

通常表示尚未执行 editable install，或正在使用错误的虚拟环境：

```powershell
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m inkstruct.cli --version
```

第二条模块命令可用于区分“包未安装”和“console script 丢失”。

### `desktop application requires inkstruct[desktop]`

安装桌面依赖：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[desktop]"
```

如果 PySide6 已安装仍失败，确认启动脚本使用的是项目 `.venv`，而不是另一个 Python。

### `找不到采集器内核`

源码采集器会依次检查：

```text
InkStruct/legacy/data_collection/handwriting_collector/ui.py
InkStruct/../data_collection/handwriting_collector/ui.py
```

将完整 `data_collection` 项目放在其中一个位置，或改用已构建的便携版。只安装 PySide6 不能替代采集器内核。

### `structure database not found`

重建或显式指定数据库：

```powershell
.\.venv\Scripts\inkstruct.exe structures build
.\.venv\Scripts\inkstruct.exe structures info `
  --database artifacts\structures\characters.sqlite3
```

确认第三方 `graphics.txt` 和 `dictionary.txt` 已检出。如果 Git 子模块内容缺失，应先恢复项目的第三方数据，而不是创建空数据库文件。

### 导入报告出现 `writer mismatch`

命令的 `--writer` 必须与每个 JSON 内的 `writer_id` 完全一致，包括大小写和下划线。不要通过文本批量替换原始 JSON 来“修复”；应确认选择了正确目录和任务身份。需要合并不同 writer 时应分别导入和建档。

### 导入报告拒绝所有 JSON

依次检查：

1. `schema_version` 是否为 `handwriting_single_v1`；
2. 选择的是否是单字 `samples/<writer-id>` 目录，而不是整行 `line_samples`；
3. `capture.canvas_width/height` 是否存在；
4. 每笔是否至少两个点；
5. 时间戳是否全局单调；
6. 路径下是否混入其他应用的 JSON 配置。

导入器递归扫描所有 `.json`。如果样本目录同时包含任务状态或报告文件，应把 `source` 指向更精确的单字样本目录。

### 采集器不能保存当前字

确认：

- 当前字符在结构库中；
- 实际笔画数等于标准笔画数；
- 轨迹非空；
- 已选择可写输出目录；
- 任务 writer 与界面 writer 一致。

使用“撤销上一笔”修正多写，或“重写当前字”重新采集。不要为了保存而关闭笔画数校验。

### `samples audit` 产生大量低置信样本

- 先检查画布尺寸、坐标和字符是否正确；
- 查看是否存在系统性错序或错误笔数；
- 适度调整 `--confidence-threshold` 只改变审计门槛，不会让低质量样本变好；
- 对 `ambiguous` 样本优先按 CSV 重录；
- 重录后使用 `samples replace` 创建新索引，再重新建档。

不要直接从 `excluded_samples` 中删除记录或手改档案 JSON。

### `profile.json` 不存在

确认索引路径并重新建档：

```powershell
.\.venv\Scripts\inkstruct.exe profile build `
  --writer user_001 `
  --index artifacts\samples\user_001\index.jsonl
```

如果使用自定义 `--destination`，生成时也必须通过 `--profile` 指向对应文件。

### 生成报告未知字符或退出码 2

检查 `manifest.json` 的 `failed` 数组。常见原因是目标字符不在结构库、档案 writer 不匹配、结构数据缺失或写入失败。

```powershell
$manifest = Get-Content -Raw outputs\user_001\document_demo\manifest.json | ConvertFrom-Json
$manifest.failed | Format-Table
```

未知字符不会被替代。若业务必须支持该字符，应先扩展并重建结构库，而不是忽略失败项。

### 全量生成中断后没有续跑

续跑必须使用完全相同的 `--run-id`。未指定 run ID 时每次都会生成新的时间戳目录。

```powershell
.\.venv\Scripts\inkstruct.exe generate `
  --writer user_001 `
  --all-supported `
  --run-id original_run_id
```

如果 manifest 缺失或损坏，当前生成器无法证明已有轨迹的运行身份，会拒绝复用该目录。请保留旧目录，使用新 run ID 重新生成。不要手工给旧文件补上新版策略字段来绕过检查。

### 更换档案后续跑产生混合结果

当前版本会拒绝身份不一致的续跑。更换 `profile.json`、结构库、模型、部件模式或强度后必须使用新的 run ID。若旧版本已经产生混合结果，请保留旧目录用于审计，在新 run ID 下重新生成完整目标集合。

### 指定检查点后仍显示确定性生成器

检查轨迹 `generator` 字段、检查点 `training_status` 和置信阈值。常见原因：

- 检查点是 smoke 或旧版，非 `formal`；
- 平均置信度低于校准阈值；
- 档案缺少 `style_tokens`；
- 因子化模型对应的档案缺少 `factorized_style`；
- 强制使用模型的诊断阈值没有显式设置。

这是设计中的安全回退，不是检查点参数被忽略。只有在诊断场景才考虑覆盖阈值，并在结果中明确记录。

如果缺少 CUDA 或训练依赖，带 `--checkpoint` 的命令会直接报错而不是回退；移除 `--checkpoint` 即可继续使用 CPU 确定性生成。

### `inkstruct train requires a CUDA-capable NVIDIA GPU`

确认安装的是 CUDA 版 PyTorch、驱动可用且当前环境能看到 GPU：

```powershell
.\.venv\Scripts\python.exe -c "import torch; print(torch.__version__); print(torch.cuda.is_available())"
```

确定性生成不需要解决此问题。没有 GPU 时跳过训练，不要尝试用 `--smoke` 绕过硬件检查。

### 正式训练或实验拒绝脏工作树

先查看变更：

```powershell
git status --short
```

正式报告应在确认代码和配置后提交或使用干净工作树。`--allow-dirty` 仅用于 smoke 和诊断，它会让实验与未记录改动绑定，不适合正式比较。

### Windows 路径和 PowerShell 续行问题

- 路径有空格、中文或括号时使用双引号；
- PowerShell 续行反引号必须是该行最后一个字符；
- 不要把文档中的 `<writer-id>` 尖括号占位符原样输入；
- 从项目根目录运行，避免相对配置中的 `artifacts/...` 指向错误位置；
- 使用 `Resolve-Path` 检查现有路径：

```powershell
Resolve-Path artifacts\structures\characters.sqlite3
Resolve-Path profiles\user_001\profile.json
```

### PNG 生成失败但 SVG/JSON 已存在

Pillow 或文件权限问题可能使单字符记录为失败。确认基础依赖和输出目录可写。对不需要位图的批量任务使用 `--no-png`，然后重新使用新的 run ID 生成；不要假设部分目录中的所有字符都已完成。

### 评估结果不能证明主观质量

`evaluate --run` 主要验证结构安全，`evaluate --writer` 主要验证按字符留出后的几何距离。两者都不能替代独立评分者盲评。对“更像用户”“可以上线”等结论，应使用 `blind-pack` / `blind-score`，保证每个条目至少三位独立评分者，并同时报告置信区间。

## 相关文档

- [项目介绍](PROJECT_OVERVIEW.md)
- [架构说明](ARCHITECTURE.md)
- [实现与验收记录](IMPLEMENTATION_REPORT.md)
- [v5 实现与初步结果](V5_IMPLEMENTATION_AND_PRELIMINARY_RESULTS.md)
- [笔顺对齐 v2](STROKE_ORDER_ALIGNMENT_V2.md)
- [目标覆盖采集分档](TARGET_COVERAGE_COLLECTION_TIERS.md)
- [第三方数据说明](../THIRD_PARTY_DATA.md)
