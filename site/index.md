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

## 0.1.74 排版更新

- **按内容确定表格总宽。** 短表可随内容收窄，长表在正文框可用宽度内换行。普通排版和纸张行格排版都支持。[设置表格总宽](/guide/faq#table-total-width)
- **按纸张行格排版。** 自定义模板可用首末基线和行数对齐信纸。表格横边框沿纸面横线排列，较高的表格行可占多格。[设置信纸行格](/guide/faq#paper-grid)

[0.1.74 安装器、ZIP 和校验记录](https://github.com/lixiang1haoo-glitch/InkStruct-Public/releases/tag/app-v0.1.74)

## 平台

Windows 桌面版提供采集、生成、制包和排版。用于记录手写笔迹的 **Android 采集端正在开发中**。
