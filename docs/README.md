# InkStruct 文档中心

本目录汇总 InkStruct（墨构）的项目说明、操作手册、架构设计、实验记录与数据来源。本文档集面向三类读者：第一次运行项目的使用者、维护代码和数据流水线的开发者，以及需要复现实验的研究人员。

> 文档适用于 InkStruct `0.2.0`。项目状态数据核对日期为 **2026-08-24**。命令、参数和协议以当前仓库代码为准；历史报告中的指标只代表报告记录时的样本、档案和运行配置。

## 从这里开始

| 目标 | 建议阅读顺序 |
| --- | --- |
| 第一次安装并生成几个字 | [项目介绍](PROJECT_OVERVIEW.md) → [使用手册：安装](USER_GUIDE.md#安装与环境准备) → [CLI 快速开始](USER_GUIDE.md#cli-快速开始) |
| 使用图形界面采集和生成 | [使用手册：轨迹采集器](USER_GUIDE.md#轨迹采集器) → [风格生成器](USER_GUIDE.md#风格生成器) |
| 批量生成、补采和质量检查 | [完整 CLI 工作流](USER_GUIDE.md#完整-cli-工作流) → [产物目录](USER_GUIDE.md#产物目录与文件用途) |
| 维护或扩展代码 | [项目介绍：系统组成](PROJECT_OVERVIEW.md#系统组成) → [架构说明](ARCHITECTURE.md) → [协议参考](USER_GUIDE.md#数据协议参考) |
| 训练模型或复现实验 | [训练与模型检查点](USER_GUIDE.md#训练与模型检查点) → [可复现实验](USER_GUIDE.md#可复现实验) → [v5 实现与初步结果](V5_IMPLEMENTATION_AND_PRELIMINARY_RESULTS.md) |
| 了解数据来源和许可 | [项目介绍：许可](PROJECT_OVERVIEW.md#数据隐私与许可) → [第三方数据说明](../THIRD_PARTY_DATA.md) → [矢量字体研究溯源](VECTOR_FONT_RESEARCH_PROVENANCE.md) |

## 核心文档

- [Mac 安装与本地数据恢复](MAC_SETUP.md)：Python 环境、桌面启动、外部采集器与旧机器数据恢复。
- [项目介绍](PROJECT_OVERVIEW.md)：项目定位、核心思想、系统组成、数据流、当前状态、边界和许可。
- [完整使用手册](USER_GUIDE.md)：安装、桌面应用、所有 CLI 子命令、输入输出协议、训练、实验、打包、测试和故障排查。
- [架构说明](ARCHITECTURE.md)：结构图数据库、笔顺感知对齐、结构不变量、学习模型与部件风格层。
- [实现与验收记录](IMPLEMENTATION_REPORT.md)：各阶段已实现能力、历史评测和仍需人工完成的验收事项。

## 专题与研究文档

### 训练、评估与模型演进

- [v5 实现与初步结果](V5_IMPLEMENTATION_AND_PRELIMINARY_RESULTS.md)：v5 训练、渲染损失、因子化风格与固定实验结果。
- [笔顺对齐 v2](STROKE_ORDER_ALIGNMENT_V2.md)：错序检测、全局匹配、歧义隔离和质量审计。
- [矢量字体研究溯源](VECTOR_FONT_RESEARCH_PROVENANCE.md)：相关矢量字体和结构数据调研来源。

### 采集计划与覆盖率

- [目标覆盖采集分档](TARGET_COVERAGE_COLLECTION_TIERS.md)：90%、95%、99%、99.9% 和 100% 五档最小采集计划。
- [大陆标准简体采集分档](MAINLAND_SIMPLIFIED_COLLECTION_TIERS.md)：面向 GB2312 大陆标准简体字符包的分档结果。
- [user_001 部件采集说明](USER001_COMPONENT_COLLECTION.md)：部件覆盖型补采任务的历史说明。
- [user_001 频数采集 200 字说明](USER001_FREQUENCY_COLLECTION_200.md)：频数驱动补采任务的历史说明。

## 信息来源与优先级

当不同文档、配置或历史产物出现差异时，按以下顺序判断当前行为：

1. `src/inkstruct/` 中的实现与 `inkstruct ... --help` 输出；
2. `pyproject.toml`、`configs/` 和 `scripts/` 中的当前依赖、配置及可执行脚本；
3. 当前运行生成的 `manifest.json`、`profile.json`、评估报告和结构数据库元数据；
4. 根目录 `README.md` 与本目录的说明性文档；
5. 带明确日期的实现报告和实验记录。

这样排序是因为历史报告会保留当时的样本数、档案版本和实验结果，而当前代码或产物可能已经更新。例如，生成目录中的 `manifest.json` 会固定该次运行实际使用的档案版本，应优先于对“当前档案”的文字描述。

## 文档约定

- 所有未特别说明的命令都从项目根目录执行。
- Windows PowerShell 为原始开发环境；macOS 的 CPU 生成与桌面启动已验证，详见 Mac 安装说明。跨平台打包及真实采集设备仍需分别验收。
- 文档中的 `user_001` 是匿名示例书写者 ID；请在实际使用时替换为自己的稳定 ID。
- 路径中的 `<writer-id>`、`<run-id>`、`<path>` 是占位符，不应原样输入。
- 项目代码、结构数据、用户样本、CASIA 数据和模型权重具有不同的授权边界，不能只依据项目的 MIT License 推断其他数据可以分发。
