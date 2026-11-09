# 字体包 .inkfont

<script setup>
import { withBase } from 'vitepress'
</script>

`.inkfont` 是供 InkStruct 选择和绘制的中心线字形资源。一个字符可以拥有多份不同笔迹，英文正体和斜体可以各有自己的候选。用 InkStruct 字体库导入即可使用，也可通过源码读入器检查。<a :href="withBase('/developer-examples/two-shapes.inkfont')" download>合成字体示例</a>

本页对应应用 **0.1.70** 和字体包 **1.0**。字体包的 `format_version`、`font_version` 和应用版本分别演进。

## ZIP 成员

| 路径 | 作用 |
| --- | --- |
| `manifest.json` | 声明格式、包类型、身份、支持特性、成员长度和哈希 |
| `index.json` | `candidates` 列出候选，`selection_policy` 为 `style-priority-uniform-v1` |
| `metrics.json` | 以 `candidate_id` 为键，存前进量、基线等排版度量 |
| `provenance.json` | 以 `candidate_id` 为键，存录制、生成、复用或合成的来源摘要及证据状态 |
| `glyphs/<trajectory_hash>.json` | 候选索引通过 `file` 引用的轨迹。同一条轨迹可以被多条候选引用 |
| `license.txt` | 写入器放入的字体使用与分享说明 |
| `development/` | 开发版可携带的补充记录。开发包仍可能需要外部原始样本才能复现 |
| `correction_sources/` | 有几何校正历史时可包含原候选快照，属于核心成员 |

清单中的 `format` 为 `inkstruct_font`，`package_kind` 为 `user` 或 `developer`。`required_features` 在 1.0 读入器中必须是 `["centerline-em-v1", "candidate-pools-v1", "latin-style-pools-v1"]`。

## 字符、候选与轨迹

索引记录以 `character` 区分字符，以 `candidate_id` 区分候选。记录还有 `letter_style`、`enabled`、`priority` 和轨迹、度量、来源摘要的引用。应用先按字形类别和候选状态筛选，再按优先级和出现位置选样。完整校验会检查停用候选。

轨迹的 `schema_version` 为 `inkfont_trajectory_v1`，`coordinate_space` 为 `em-y-down-baseline-0.88`，以 em 为单位，纵坐标向下，基线为 0.88。每笔依序保存 `order`、`stroke_ref` 和 `points`。点包含 `x`、`y`，可带 `pressure`、`t_ms` 和 `pen_state`。每笔还记录压力、时间和笔状态的来源，例如实测、继承、合成或缺失。读取时保留可选字段的有无。

## 身份与完整性

| 字段 | 标识范围 |
| --- | --- |
| `font_id` | 字体家族，可包含多个发布版本 |
| `release_id` | 某次核心字形发布 |
| `package_id` | 一份具体的发布包，用户版和开发版可各有自己的 ID |
| `members` | 除清单自身以外的成员，逐项记录展开字节数与原始字节的 SHA-256 |
| `core_hash` | 对字体身份、发布身份、必需特性和核心成员摘要计算的哈希。移除开发附录可保留该值 |
| `content_hash` | 清单移除此字段后的规范序列化摘要，涵盖包身份与全部成员声明 |

字体清单使用 UTF-8、键排序、紧凑 JSON。轨迹及部分关联字段另用保留整数、浮点数和字段存在性的类型化摘要。文件整体的 SHA-256 可用于核对下载，包内哈希用于校验内容完整性。身份与计算细节见 [0.1.70 字体读写器](https://github.com/lixiang1haoo-glitch/InkStruct-Public/blob/app-v0.1.70/src/inkstruct/fonts/core.py)。

## 读取与拒绝条件

从源码运行以下命令需要先配置 [Python 环境](./cli#环境)。

```powershell
python -c "from inkstruct.fonts.core import FontPackage; print(FontPackage('two-shapes.inkfont', verify_all=False).verify())"
```

`verify()` 校验所有成员和候选，包括轨迹字段、度量与来源摘要。读入器拒绝不支持的格式、重复或不安全路径、加密或符号链接成员、超限文件、哈希不符及失效引用。只打开 ZIP 或只构造元数据对象，仍需执行完整验证才可判断候选有效。
