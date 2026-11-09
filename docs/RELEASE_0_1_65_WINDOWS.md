# InkStruct 0.1.65 · Windows

2026-11-09。解压完整的 `InkStruct-0.1.65-Windows-x64.zip`，运行 `InkStruct.exe`。

- 采集、生成、排版、字体库、模板库及设置共用浅色控件样式。主按钮的键盘焦点和按下状态更清楚，数值框的步进箭头更易辨认和点击。
- 生成页窄窗保留内置字表入口，其余来源收进「更多来源」。打开其他模块时，隐藏的排版页不再撑宽窗口。
- 正文设置把字高、笔宽、行高和段距放在实验性的自然书写参数之前，同层字段对齐。设置窗口再次打开时恢复上次尺寸。
- 制包窗口可收起来源和包设置，把空间留给类别清单。核对状态和阻塞原因靠近制包按钮。

界面按 [pyside6-fluent-ui 的迁移流程](https://github.com/ejacques11/pyside6-fluent-ui/blob/main/.agents/skills/pyside6-fluent-ui/SKILL.md)修订，保留 Qt Widgets 和系统标题栏。深色及系统高对比度外观尚未完成适配。

## Windows 验证

- 干净检出源码提交 `cf4b71799510e78cf5569e82eacc056a20c759c9`，核对 345 项构建输入和 10 项锁定公开资源。相关源码回归 100 项通过。
- 150% 缩放的 Windows 实窗确认，生成页在 650 个逻辑像素宽时使用「更多来源」收纳入口，未出现横向滚动或控件重叠。数值框通过鼠标步进和键盘调整。制包窗口收起来源后可见 12 个类别，完整验证后实际入包 207 字、1,311 份，符合核对清单。样本、旧字体及文档副本哈希一致，5,129 条冻结选样相同。
- 两个 EXE 的版本检查和包内自检通过。ZIP SHA-256 为 `c08e7d6313a241d9f1b604ec4d0458c613396e51570305b90355d5618d240fbe`。
- [构建溯源](releases/0.1.65-build-provenance.json) · [公开资源哈希](releases/0.1.65-windows-resources.json) · [Git 验证记录](releases/0.1.65-git-verification.json)
