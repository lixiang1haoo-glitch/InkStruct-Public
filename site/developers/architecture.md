# 架构与源码导航

以下路径对应桌面应用 **0.1.69**。处理某个文件或界面问题时，先找它所属的阶段，再查看对应测试。[0.1.69 源码](https://github.com/lixiang1haoo-glitch/InkStruct-Public/tree/app-v0.1.69/src/inkstruct)

## 两条数据路径

```text
笔迹采集 → 样本校验与索引 → 作者档案 → 生成批次
生成批次与扩展样本 → 字形选择与规则 → 完整验证 → .inkfont

Markdown 与排版设置 → 语义节点与字符出现位置
字符出现位置与字形资源 → 选样 → 布局 → 预览或导出
Markdown、排版设置、资源与选样 → .inkdoc
```

项目重开时由 `.inkdoc` 恢复源码、样式和嵌入资源。页面预览由这些输入重新布局。字体库的新版本可供后续使用，文档中已保存的选样由资源快照支持。[项目文件格式](./inkdoc)

## 按问题找代码

下列路径相对于 `src/inkstruct/`。

| 问题 | 入口 |
| --- | --- |
| 桌面应用怎样启动 | `application.py` 和 `app_shell.py` |
| 样本怎样归属作者，何时更新档案 | `capture_management.py`、`samples.py`、`generation_workflow.py` |
| 字体包如何核对与发布 | `fonts/publication.py`、`fonts/importer.py`、`fonts/core.py`、`fonts/library.py` |
| Markdown 如何解析，如何报告源码位置 | `document/markdown.py`、`document/editing.py`、`document/source_map.py`、`math/` |
| 字形候选怎样对应到文中的一次出现 | `assets/resolver.py` 与 `assets/symbol_provider.py` |
| 页面如何重排、预览和导出 | `layout/blocks.py`、`renderers/`、`plotter/` |
| 项目如何保存与重开 | `document/package.py` 和 `document/package_validation.py` |
| 命令行怎样调用排版 | `cli.py` 和 `document/cli.py` |

0.1.69 的 Windows 打包与校验脚本在 `packaging/`，示例在 `examples/`，测试在 `tests/`。文档站源码集中在 `site/`。[构建、验证与贡献](./contributing)
