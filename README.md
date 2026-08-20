# InkStruct（墨构）

InkStruct 是一个以汉字结构先验驱动的个性化在线手写轨迹生成项目。名称中的 **Ink** 表示用户墨迹与书写风格，**Struct** 表示项目用标准结构约束内容正确性。

核心生成层级为：

```text
整字布局 → 部件整体轨迹 → 部件内部笔画 → 在线采样点
```

标准结构库固定目标字的笔数、笔顺和关键拓扑；用户风格档案学习整字比例、部件布局、部件整体轨迹以及条件化笔画形变。当前主实现是确定性的 `ComponentTrajectory v4`，不要求逐用户训练或 GPU。

## 当前状态

- 结构库包含 9,574 个有效简繁字符。
- `user_001` 当前档案版本为 `d270c610fd4ca3c7`，由 385 份样本、294 个唯一字符建立。
- 已完成 9,574 / 9,574 字全量生成，失败数为 0，结构不变量通过率为 100%。
- 默认生成采用 `adaptive` 部件模式：优先使用整组 `ComponentTrajectoryPrototype`，证据不足时逐级退回部件布局、条件化笔画和标准中心线。
- 项目只关注几何字形与在线轨迹；当前不优化连笔，不导出 TTF/OTF。

现成的全量结果位于 `outputs/user_001/all_supported_component_trajectory_v4/`，本轮实现报告位于 `artifacts/component_trajectory_v4/REPORT.md`。

## 环境

项目要求 Python 3.12 或 3.13。确定性生成、采集、结构检查和测试可在 CPU 上运行；只有实验性的分层残差模型训练需要 NVIDIA GPU。

Windows PowerShell：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[desktop,dev]"
```

若需要训练功能，再安装带 CUDA 的 PyTorch，并执行：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[train]"
```

仓库内的 `requirements.lock` 记录了当前 Windows/CUDA 环境的完整版本。CUDA 版本的 PyTorch 应按本机驱动和官方安装说明选择，不建议盲目跨机器复用。

## 快速使用

查看或重建结构库：

```powershell
.\.venv\Scripts\inkstruct.exe structures info
.\.venv\Scripts\inkstruct.exe structures build
```

导入兼容 `handwriting_single_v1` 的单字 JSON，并建立一次性缓存风格档案：

```powershell
.\.venv\Scripts\inkstruct.exe samples import "C:\path\to\user_001" --writer user_001
.\.venv\Scripts\inkstruct.exe profile build --writer user_001
```

指定内容或所有支持字符生成：

```powershell
.\.venv\Scripts\inkstruct.exe generate --writer user_001 --text "墨构手写"
.\.venv\Scripts\inkstruct.exe generate --writer user_001 --all-supported --run-id all_supported
```

生成阶段只读取已缓存的 `profiles/<writer-id>/profile.json`，不会为每个目标字重复读取原始 JSON 或风格图片。

## 采集器与生成器

两个桌面应用已经分离：

- 双击 `run_inkstruct_collector.cmd` 启动采集器；它负责书写、标准笔画数校验和重录提示。
- 双击 `run_inkstruct_generator.cmd` 启动风格生成器；它负责样本导入、建档、文本生成和结果预览。
- `release/InkStructCollector/` 是不含 PyTorch/CUDA 的轻量 Windows 采集包。

命令行等价入口：

```powershell
.\.venv\Scripts\inkstruct.exe collector
.\.venv\Scripts\inkstruct.exe generator
```

## 推荐、检查与评测

根据 9,574 字中的部件频数和当前档案覆盖缺口推荐补采字符：

```powershell
.\.venv\Scripts\inkstruct.exe collect recommend --writer user_001 --count 200
```

检查错误笔画数、低置信对齐和待重录样本，并验证生成结果：

```powershell
.\.venv\Scripts\inkstruct.exe samples audit --writer user_001
.\.venv\Scripts\inkstruct.exe evaluate --run outputs\user_001\all_supported_component_trajectory_v4
```

## 输出协议

默认生成目录为：

```text
outputs/<writer-id>/<run-id>/
├─ manifest.json
├─ trajectories/U+XXXX.json
└─ previews/
   ├─ U+XXXX.svg
   └─ U+XXXX.png
```

每个 `personal_trajectory_v1` JSON 包含字符、结构库版本、风格档案版本、生成置信度，以及各笔的标准笔画 ID、笔顺和 `x/y/t_ms/pressure/pen_state` 点序列。内部几何坐标统一为 `[0,1]`、左上角原点、Y 轴向下。

## 项目结构

```text
InkStruct/
├─ src/inkstruct/                   核心包、CLI 与桌面应用
├─ tests/                           单元与集成测试
├─ docs/                            架构和采集说明
├─ scripts/                         环境、评测和批处理脚本
├─ packaging/                       轻量采集器打包脚本
├─ third_party/makemeahanzi/        标准中心线与拆字数据
├─ artifacts/
│  ├─ structures/                   9,574 字结构数据库
│  ├─ samples_merged_202608201606/  当前 user_001 合并样本索引
│  ├─ collection/                   推荐与待重录任务
│  └─ component_trajectory_v4/      当前实验与报告
├─ profiles/user_001/               当前版本化风格档案
├─ outputs/user_001/                当前全量生成结果
├─ data/CASIA_CHINESE/              可选训练数据，不参与确定性生成
└─ release/InkStructCollector/       轻量采集应用
```

## 测试与代码检查

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\ruff.exe check src tests scripts packaging
```

强制生成不变量包括：输出笔数与标准结构一致、笔顺连续、坐标有限、部件引用有效，以及未知字符不得静默替代。

## 数据与许可

项目代码采用 MIT License。汉字结构数据来自 Make Me a Hanzi，具体来源和许可说明见 `THIRD_PARTY_DATA.md`。CASIA 与用户手写样本不是项目代码的一部分，使用、分发和商业化前需分别确认数据授权；项目不会修改外部原始样本。

原 SDT 仅作为项目演进来源和效果对照，不再参与 InkStruct 当前运行路径。
