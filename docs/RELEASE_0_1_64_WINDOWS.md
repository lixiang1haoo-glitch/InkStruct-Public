# InkStruct 0.1.64 · Windows

2026-11-08。解压完整的 `InkStruct-0.1.64-Windows-x64.zip`，运行 `InkStruct.exe`。

- 设置和生成页的短数值框靠近标签，单位和步进按钮留在输入框内。固定选项的下拉框按内容取宽。
- 作者、字体和任务名称使用较短的编辑框。采集滑块的当前读数紧邻滑块，目录、搜索和其他长字段仍随窗口伸展。

## Windows 验证

- 源码提交 `d008fa517ea8a8bb7a5c2c0518aa07942f541119`，注解标签 `app-v0.1.64`。干净检出核对 343 项构建输入和 10 项锁定公开资源。
- 相关源码回归 78 项通过，1 项预览测试在 0.1.63 基线也失败。Windows 实窗在 150% 缩放下核对生成、正文与段落、采集显示。宽窗口里短字段保持宽度，目录和搜索框继续伸展。
- 两个 EXE 的版本检查和包内公式自检均通过。ZIP SHA-256 为 `bb992d8329ff543941d457b99f005b049a24669804aabdac6dbdb69a46a6fea3`。
- [构建溯源](releases/0.1.64-build-provenance.json) · [公开资源哈希](releases/0.1.64-windows-resources.json) · [Git 验证记录](releases/0.1.64-git-verification.json)
