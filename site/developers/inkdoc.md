# 项目文档 .inkdoc

<script setup>
import { withBase } from 'vitepress'
</script>

`.inkdoc` 将 Markdown、排版设置、已嵌入的字形和图片，以及每次字符出现的选样保存在同一个 ZIP。打开合成示例可以看到同一个 `A` 的两种笔迹。复制这个项目文件即可带走示例的笔迹。<a :href="withBase('/developer-examples/two-shapes.inkdoc')" download>合成项目示例</a>

## ZIP 成员

| 路径 | 作用 |
| --- | --- |
| `manifest.json` | 记录包协议、Markdown 方言、数学语法、选样种子、路径优化参数和成员哈希 |
| `source.md` | 权威 Markdown 原文，UTF-8 |
| `identity.json` | 保存文档与源码字符身份，为选样提供能跨编辑跟踪的锚点 |
| `styles.json` | `page`、`body`、`flow` 分别保存页面、正文和排版流程设置，包含适用的公式、表格、图片与模板参数 |
| `selections.json` | 按 `occurrence_id` 保存选用字形、度量与请求或解析后的正斜体 |
| `resources.json` 与 `assets/<sha256>.json` | 字形描述和对应的嵌入原始数据。描述通过 `source_file` 引用成员 |
| `reviews.json` | 保存评价。旧项目缺少该成员时按空列表读取 |
| `font-source.json` | 可选。保存当前关联字体的 `font_id`、`release_id` 与 `core_hash` |
| `images/<sha256>.original` 与 `images/<sha256>.png` | 按需保存图片原件与栅格化副本。线条 SVG 保存原件 |

## 两个相同字符怎样引用不同笔迹

示例的 `source.md` 为 `A A`，两个 `A` 有不同的 `occurrence_id`。每条选样记录通过 `character`、`asset_id`、`sample_id` 和 `metrics_key` 在嵌入资源中定位自己的候选。即使安装了更新的字体，已冻结的这两次出现也可以用项目内保存的资源重排。若选样引用找不到匹配资源，读入器会报错。

`font-source.json` 记录关联字体的精确发布身份，项目文件仍以自己的嵌入资源为准。需要添加新字时，可用 [CLI 资源检查](./cli#检查缺字) 查看可用范围。

## 表格总宽设置 {#table-total-width}

在 0.1.74 中，文档默认表格样式保存在 `styles.json` 的 `flow.table`，单张表格的覆盖设置保存在 `flow.table_overrides`。样式中的 `total_width_mode: "content"` 表示按内容确定总宽。省略这个字段时使用手动总宽 `width_mm`。

`width_mode` 继续决定各列如何分配宽度。`content`、`equal` 和 `ratio` 都可与自动总宽组合，固定列宽 `fixed` 需要手动总宽。表格总宽和[纸张行格](./layout-inputs#paper-grid)都使用现有包协议。读取使用这两个字段的项目时，请使用 0.1.74 或更新版。[表格样式定义](https://github.com/lixiang1haoo-glitch/InkStruct-Public/blob/app-v0.1.74/src/inkstruct/document/table_style.py)

## 包版本与校验

应用 **0.1.74** 读取以下 `schema_version`。同一应用会按文档内容写出不同的包版本。

| 版本 | 写入场景 |
| --- | --- |
| `inkstruct_document_package_v1` | 普通项目，且未嵌入来自 `.inkfont` 核心的候选 |
| `inkstruct_document_package_v2` | 普通项目，嵌入了来自 `.inkfont` 核心的候选 |
| `inkstruct_document_package_v3` | 启用模板命名字段的项目，清单同时声明 `inkstruct_named_fields_v1` |

读入器核对包版本、方言、数学语法、每个成员的原始字节 SHA-256、资源描述与原始几何的一致性，以及选样引用。压缩包大于 200 MB、展开总量超过 500 MB、成员数超过 30,000，或出现重复成员时会拒绝读取。单个成员通常限 16 MB，`resources.json` 上限 128 MB。版本和限制以 [0.1.74 项目读写器](https://github.com/lixiang1haoo-glitch/InkStruct-Public/blob/app-v0.1.74/src/inkstruct/document/package.py) 和 [元数据校验器](https://github.com/lixiang1haoo-glitch/InkStruct-Public/blob/app-v0.1.74/src/inkstruct/document/package_validation.py) 为准。

建议用对应版本的项目写入器改写副本。直接修改 ZIP 中的 Markdown 会涉及源码锚点、选样、资源引用和清单哈希的一致性。
