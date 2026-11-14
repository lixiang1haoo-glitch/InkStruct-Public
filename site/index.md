---
layout: home
title: 文档首页
hero:
  name: InkStruct 墨构
  text: 用自己的笔迹排一页
  tagline: 用现成的正文、模板和字体先排一页手写文档。
  image:
    src: /ink-on-paper.svg
    alt: 一张写有示例笔画的纸与一支蓝黑色笔
  actions:
    - theme: brand
      text: 做出第一份手写文档
      link: /guide/student-notes
    - theme: alt
      text: 下载 Windows 版
      link: https://github.com/lixiang1haoo-glitch/InkStruct-Public/releases/latest
features:
  - title: 从 A4 物理笔记起步
    details: 导入练习包里的正文、模板和字体，试排笔记并导出写字机路径。
    link: /guide/student-notes
    linkText: 阅读上手教程
  - title: 安装、补录与缺字
    details: 查找运行库下载入口，了解补录何时纳入档案，以及如何定位制包缺口。
    link: /guide/faq
    linkText: 查看常见问题
  - title: 查看操作速查
    details: 按采集、生成、制作字体和排版快速查阅步骤与构建入口。
    link: https://github.com/lixiang1haoo-glitch/InkStruct-Public/blob/main/docs/USER_GUIDE.md
    linkText: 打开仓库速查页
  - title: 开发者文档
    details: 查阅文件格式、命令行与源码构建，用合成示例验证一次集成。
    link: /developers/
    linkText: 查看开发者文档
---

## 0.1.87 字母与数字间距

正文数字可随英文字母按笔迹宽度排列。旧项目沿用原数字间距，可在「正文与段落」主动应用新规则。

## 0.1.86 样本库

在「采集 › 样本库」跨任务浏览汉字、标点与扩展，选取样本并导出为离线采集包。接收端先核对目标书写者及新增、重复、冲突，再确认导入。

Markdown 支持用 `\begin{paragraphalign}{center}` 和 `\end{paragraphalign}` 包围正文段落，区块可跨页和正文框。也可选左对齐、右对齐或两端对齐。

## 0.1.85 汉字间距

「设置 › 正文与段落」可在整字宽和按笔迹紧凑排列之间切换。旧文档保持整字宽，自然书写的字距变化可独立调节。

## 0.1.84 跨设备采集

「采集 › 书写者资料」支持离线导入和导出稳定书写者 ID，也可将外机样本导入已有书写者。制作字体时可核对并关联同一人的旧汉字批次与外机标点。

## 0.1.83 排版更新

普通正文按可容纳的纸张行格逐线排版。拖动正文框右下控柄缩短时，可预览剩余行数，保留的纸线保持原位置。

## 0.1.82 排版更新

Markdown 项目在后台保存。连续按 Ctrl+S 时，应用合并重复保存请求，并跳过无改动的写盘。

## 0.1.81 生成更新

「生成方式」新增 v6.3.1，可复用通过校验的 v6.3 作者档案，生成批次和字体记录实际使用的方法。默认仍为 v6.3。

## 0.1.80 排版更新

Markdown 图片和图题排完后，后续内容从图题下方接续，修复正文与图片重叠或图片下方空白过大的问题。

## 0.1.79 采集更新

汉字与标点采集现在增量绘制笔迹，减少长笔画书写时的重绘开销。录入的坐标、压感和时间戳照常保存。

## 0.1.78 采集更新

汉字采集的四个常用按钮已加大，名称和快捷键分两行显示，整列与画布纵向居中。按 Shift+Enter 可暂时跳过当前字。

## 0.1.76 生成更新

- **同字原稿优先。** v6.3 可直接使用通过整字校验的分笔或连笔原稿，保留同字的多种写法。[同字原稿设置](/guide/faq#connected-handwriting)
- **生成评分。** 可分别计算来源分和多样性分，并查看覆盖与轮换情况。[查看评分说明](/guide/faq#generation-scores)

[Windows 安装器、ZIP 和校验记录](https://github.com/lixiang1haoo-glitch/InkStruct-Public/releases/latest)

## 0.1.74 排版更新

- **按内容确定表格总宽。** 短表可随内容收窄，长表在正文框可用宽度内换行。普通排版和纸张行格排版都支持。[设置表格总宽](/guide/faq#table-total-width)
- **按纸张行格排版。** 自定义模板可用首末基线和行数对齐信纸。表格横边框沿纸面横线排列，较高的表格行可占多格。[设置信纸行格](/guide/faq#paper-grid)

## 平台

Windows 桌面版提供采集、生成、制包和排版。用于记录手写笔迹的 **Android 采集端正在开发中**。
