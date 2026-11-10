# InkStruct Windows 使用说明

[文档站](https://lixiang1haoo-glitch.github.io/InkStruct-Public/)提供带截图的[上手教程](https://lixiang1haoo-glitch.github.io/InkStruct-Public/guide/first-document.html)和[常见问题](https://lixiang1haoo-glitch.github.io/InkStruct-Public/guide/faq.html)。本页供快速查阅。

安装版会检查 Microsoft Visual C++ x64 运行库（14.51 或更新版本）。若提示缺失，打开微软下载，安装运行库后重新运行安装程序。免安装版请完整解压 ZIP 后运行 `InkStruct.exe`。它使用相同的系统运行库。[发行页](https://github.com/lixiang1haoo-glitch/InkStruct-Public/releases/tag/app-v0.1.70) · [微软官方下载](https://aka.ms/vc14/vc_redist.x64.exe)

0.1.71 源码中的字体库预览和采集画布随深浅主题切换。深色采集画布为深灰底白色笔迹。公式设置的手写预览同时显示当前示例的各项实测毫米值，选中项高亮。

1. 打开「采集」并创建书写者，再创建任务。按提示用数位笔录制独立样本。
2. 在「生成」选择书写者、样本目录、目标字和方法。开始生成时会按当前样本准备档案。生成结果中可制作该批次的字体。
3. 制作字体时确认批次、类别和缺字，再等待完整验证与入库。用「字体库」可以管理已完成的字体包。
4. 在「排版」导入 Markdown，选择字体并试排。保存文档会保留关联的排版和字形选择。
5. 在「设置 › 应用设置 › 主题」可选择跟随系统、浅色和深色。

**录制连笔汉字**时，在「采集 › 汉字样本」勾选「允许汉字连笔」，然后在「生成」选择 **v6.3 exp**。当前只有 v6.3 使用连笔供体，v6.2 继续处理分笔样本。建档分别报告可用的整字和部件。默认可跨字复用合格部件，需要保留同字整段连写时再勾选「允许回放同字的完整连笔样本」。

0.1.68 移除了整行采集的旧入口及其运行组件。汉字单字任务和标点与扩展采集继续可用。旧整行任务与轨迹文件仍保存在原工作区。

反馈问题时使用新建测试工作区与合成输入。仓库提供两份公式 Markdown 示例。Windows 构建方法见 [README](../README.md)。
