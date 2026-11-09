# 开发者文档

<script setup>
import { withBase } from 'vitepress'
</script>

从命令行检查手写文档、读取交换文件，或从源码参与开发。这里的参考页以 InkStruct 桌面应用 **0.1.70** 为验证基线。应用、Python 项目和各文件格式有各自的版本。

| 我想做什么 | 从这里开始 |
| --- | --- |
| 看项目缺哪些字，或把文档渲染成 SVG | [CLI 与快速开始](./cli) |
| 读取字体的字符、候选、轨迹和来源 | [字体包 `.inkfont`](./inkfont) |
| 读取项目的 Markdown、嵌入资源和冻结选样 | [项目文档 `.inkdoc`](./inkdoc) |
| 从其他工具生成排版内容或模板 | [排版输入与模板](./layout-inputs) |
| 准备采集任务，追踪某个字形从哪里来 | [采集、生成与字形来源](./glyph-sources) |
| 找到相关模块、从源码构建或提交改动 | [架构与源码导航](./architecture) · [构建、验证与贡献](./contributing) |

## 最小交换示例

两个文件使用脚本构造的几何笔迹。同一个 `A` 有两份候选，文档里的两个 `A` 各自选中一份。把文档单独移到另一个目录，仍能使用其中的两份冻结笔迹。

- <a :href="withBase('/developer-examples/two-shapes.inkfont')" download>下载字体示例 <code>two-shapes.inkfont</code></a>
- <a :href="withBase('/developer-examples/two-shapes.inkdoc')" download>下载项目示例 <code>two-shapes.inkdoc</code></a>
- [查看生成脚本](https://github.com/lixiang1haoo-glitch/InkStruct-Public/blob/main/examples/make_format_examples.py)

Python 示例引用 0.1.70 源码中的实现入口。接入时请锁定源码标签，升级后重跑样例。对外交换优先使用已版本化的文件和已验证的 CLI 参数。
