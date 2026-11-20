# InkStruct 墨构

把自己的笔迹做成可复用的字体，再用它排出一页 Markdown。InkStruct 在本机完成采集、生成、制包和排版。

[项目特色](#项目特色) · [下载](#下载) · [文档站](https://lixiang1haoo-glitch.github.io/InkStruct-Public/) · [开发者文档](https://lixiang1haoo-glitch.github.io/InkStruct-Public/developers/) · [源码构建](#源码构建) · [使用速查](docs/USER_GUIDE.md) · [反馈问题](CONTRIBUTING.md)

Windows x64 · 0.1.119 本机测试版 · Python / Qt

左下角「设置」集中提供当前文档、新建文档默认与应用偏好。Windows 排版页右侧的「写字机」标签可控制炽写 N1。

0.1.119 修复排版页关闭软件工作范围时，N1 抬笔点动遇到单帧轴限位误报会断开的问题。

0.1.118 可确认制作或导入本机大容量字体。需要分享时，可选择候选另存为通用 v1 副本。生成后的来源分和多样性分跟随「计算方式」并行统计。

0.1.117 可从字体库直接导入 InkStruct / OpenInk 通用 v1 字库。导入旧字体包时，程序会在后台转换，并保留原版供已有文档使用。

0.1.116 支持在「书写原点与对位」中直接抬笔点动，放大预览后可就地记录 A、B 点。

0.1.114 将每台 N1 的所有 XY 移动统一到「运动速度」。新建设备默认 2500 mm/min，已有设备沿用原先保存的书写速度。抬笔点动的步长可选 0.1 至 100 mm。新建设备可按需启用软件工作范围，已有范围的设备档案升级后保留范围保护。

0.1.110 增加独立的写字机设备管理、按模板源页的纸面对位和可选的抬笔试走。样本库可直接导入并按来源登记书写者。N1 的书写默认进给为 2500 mm/min。

0.1.113 支持登记纸张限位处的纸角。N1 重启后，将抬起的笔尖对准已登记的纸角即可找回笔位。同规格工作纸按原方向靠齐挡边，可沿用已保存的纸面对位。设备管理中的点动与试画会根据固件和已确认的安全范围复核短暂的 X/Y 限位信号。[下载 0.1.113 测试版](https://github.com/lixiang1haoo-glitch/InkStruct-Public/releases/tag/app-v0.1.113)

0.1.100 在「采集 → 汉字样本」提供三档推荐录制任务，累计目标为 32、100、400 字。打开任务时按当前书写者的已有合格样本计算剩余字数。

0.1.99 的排版工具栏显示「导出…」文字，写字机 SVG 直接显示高级设置。样本库中的同字样本按可用宽度自动换行。

0.1.98 统一排版导出入口，支持写字机 SVG、整页排版图与整篇 PDF。保存前可检查选定页。

0.1.97 修复历史生成结果中的来源字过小和笔迹折角。汉字来源按整字取景，生成字形与来源笔迹在预览时平滑绘制。

0.1.96 的历史生成结果采用三栏显示。选择批次和字符后，可同时查看生成字形和多个来源字。点击生成笔段可高亮对应原笔迹，Ctrl + 滚轮和拖动可同步调整预览视野。

0.1.95 的样本库按采集比例显示原始笔迹。Ctrl + 滚轮可在鼠标指向处缩放，放大后可拖动。并排比较同步倍率和位置，点击倍率可恢复默认视野。

0.1.82 修复排版页连续按 Ctrl+S 时界面长时间无响应的问题。Markdown 项目在后台保存，重复请求会合并。

0.1.81 在生成页新增独立的 v6.3.1，可沿用通过校验的 v6.3 作者档案。默认仍为 v6.3。

0.1.80 修复 Markdown 图片带图题时，后续正文可能与图片重叠或留下过大空白的问题。

0.1.78 加大汉字采集按钮，名称和快捷键各占一行，整列与画布纵向居中。按 Shift+Enter 可暂时跳过当前字。

0.1.76 在 v6.3 中默认优先使用通过校验的同字分笔或连笔原稿。生成时可独立选择计算来源分和多样性分。

0.1.75 支持图片标注。可在图上放置单行文字和行内公式，沿用文档字体，拖动定位并单独调整字号。

Android 采集端正在开发中，用于记录手写笔迹。

## 项目特色

从手头的一份讲义、习题或公式笔记开始，按这篇文档的实际需要录字。

- **按文档补充字库。** 从 Markdown 或当前排版提取目标汉字，先用已有样本生成，再查看还缺哪些字。做下一篇文档时，可以继续用已有字体，遇到缺字再补充。
- **同一个字可以有不同写法。** 有多份合格候选时，同一页的几个「的」可以使用不同字形，减少整页反复出现相同笔迹的机械感。保存文档时可以保留各处的字形选择。

## 下载

Windows x64 提供安装程序和免安装 ZIP。安装程序会检查系统里的 Microsoft Visual C++ x64 运行库。若提示缺少运行库，按提示从微软下载并安装，再打开 InkStruct 安装程序。使用 ZIP 时，先解压完整目录，再运行 `InkStruct.exe`。两种方式都需要 14.51 或更新版本的运行库。[下载 InkStruct](https://github.com/lixiang1haoo-glitch/InkStruct-Public/releases/latest) · [Microsoft 运行库](https://aka.ms/vc14/vc_redist.x64.exe)

源码、Qt 对应源码及校验清单也在发行页提供。[Windows 分发说明](docs/WINDOWS_DISTRIBUTION.md)

## 从笔迹到文档

第一次使用可以跟着[《从录字到排版：做出你的第一份手写文档》](https://lixiang1haoo-glitch.github.io/InkStruct-Public/guide/first-document.html)操作。教程用三份笔迹排出一段短文，并说明如何处理缺字。

1. **采集。** 创建书写者和任务，在「录制输入」中选择设备，录制汉字、标点与扩展字符。
2. **生成。** 选作者、样本目录和目标字。开始生成时会按样本状态自动准备作者档案。
3. **制作字体。** 核对生成批次、纳入类别和缺字。完整验证通过后，字体进入字体库。
4. **排版。** 导入 Markdown，用自己的字体预览正文、公式和表格。文档可保存字形选择，供之后重开继续编辑。

可先打开仓库中的 [合成公式示例](examples/markdown_math_constructions_m5.md) 熟悉排版界面。深浅主题可在「设置 › 应用偏好 › 主题」切换。

## 使用边界

| 范围 | 当前行为 |
| --- | --- |
| 个人数据 | 样本、作者档案、生成结果、字体和文档在工作区管理。安装目录和工作区分开，卸载只移除安装文件 |
| 采集 | 0.1.68 移除整行采集的旧组件，汉字单字任务及标点与扩展采集继续可用 |
| 字表 | 内置字表来自 Unicode Unihan 17.0.0。目标字仍需结构库支持 |
| 平台 | Windows 11 x64 是本轮安装和构建验证范围 |

## 源码构建

使用 CPython 3.13.16 x64。下面的 PowerShell 命令在仓库根目录运行。依赖来自公开 PyPI，结构库从锁定上游输入重建。

```powershell
py -3.13 -m venv .venv
$python = ".\.venv\Scripts\python.exe"
& $python -m pip --isolated install --index-url https://pypi.org/simple --only-binary=:all: --require-hashes -r packaging/windows-x64-py313.lock
$env:PYTHONPATH = "$PWD/src;$PWD/artifacts/external/data_collection"
& $python -B packaging/prepare_public_resources.py
& $python -B -m pytest -p no:cacheprovider
& $python -B packaging/build_inkstruct_app.py --output build/0.1.119
& $python -B packaging/verify_public_windows.py --bundle build/0.1.119/dist/InkStruct --output build/verification
```

从源码启动可运行 `python -m inkstruct.application --workspace workspace`。构建安装程序时，从 [NSIS 锁](packaging/nsis-win.lock.json) 下载编译器 ZIP，保持原样，并执行：

```powershell
& $python -B packaging/build_windows_installer.py --verification build/verification/verification.json --nsis-zip nsis-3.13.zip --output build/installer
& $python -B packaging/verify_windows_installer.py --installer-build build/installer/installer-build.json --zip build/verification/InkStruct-0.1.119-Windows-x64.zip --output build/installer-check
```

## 许可与贡献

[源码许可](LICENSE) · [第三方许可与资源来源](THIRD_PARTY_NOTICES.md) · [贡献指南](CONTRIBUTING.md)

反馈请使用最小合成样例。真实笔迹、作者档案、私人字体和文档留在个人工作区。
