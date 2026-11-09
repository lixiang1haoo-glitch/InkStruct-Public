# InkStruct 墨构

把自己的笔迹做成可复用的字体，再用它排出一页 Markdown。InkStruct 在本机完成采集、生成、制包和排版。

[项目特色](#项目特色) · [下载](#下载) · [文档站](https://lixiang1haoo-glitch.github.io/InkStruct-Public/) · [开发者文档](https://lixiang1haoo-glitch.github.io/InkStruct-Public/developers/) · [源码构建](#源码构建) · [使用速查](docs/USER_GUIDE.md) · [反馈问题](CONTRIBUTING.md)

Windows x64 · 0.1.70 · Python / Qt

0.1.70 在采集和生成流程中加入 v6.3 汉字连笔支持，安装和卸载界面使用简体中文。

Android 采集端正在开发中，用于记录手写笔迹。

## 项目特色

从手头的一份讲义、习题或公式笔记开始，按这篇文档的实际需要录字。

- **按文档补充字库。** 从 Markdown 或当前排版提取目标汉字，先用已有样本生成，再查看还缺哪些字。做下一篇文档时，可以继续用已有字体，遇到缺字再补充。
- **同一个字可以有不同写法。** 有多份合格候选时，同一页的几个「的」可以使用不同字形，减少整页反复出现相同笔迹的机械感。保存文档时可以保留各处的字形选择。

## 下载

0.1.70 提供 Windows x64 安装程序和免安装 ZIP。安装程序会检查系统里的 Microsoft Visual C++ x64 运行库。若提示缺少运行库，按提示从微软下载并安装，再打开 InkStruct 安装程序。使用 ZIP 时，先解压完整目录，再运行 `InkStruct.exe`。两种方式都需要 14.51 或更新版本的运行库。[下载 InkStruct 0.1.70](https://github.com/lixiang1haoo-glitch/InkStruct-Public/releases/tag/app-v0.1.70) · [Microsoft 运行库](https://aka.ms/vc14/vc_redist.x64.exe)

源码、Qt 对应源码及校验清单也在发行页提供。[源码标签](https://github.com/lixiang1haoo-glitch/InkStruct-Public/tree/app-v0.1.70) · [Windows 分发说明](docs/WINDOWS_DISTRIBUTION.md)

## 从笔迹到文档

第一次使用可以跟着[《从录字到排版：做出你的第一份手写文档》](https://lixiang1haoo-glitch.github.io/InkStruct-Public/guide/first-document.html)操作。教程用三份笔迹排出一段短文，并说明如何处理缺字。

1. **采集。** 创建书写者和任务，用数位笔录制汉字、标点与扩展字符。
2. **生成。** 选作者、样本目录和目标字。开始生成时会按样本状态自动准备作者档案。
3. **制作字体。** 核对生成批次、纳入类别和缺字。完整验证通过后，字体进入字体库。
4. **排版。** 导入 Markdown，用自己的字体预览正文、公式和表格。文档可保存字形选择，供之后重开继续编辑。

可先打开仓库中的 [合成公式示例](examples/markdown_math_constructions_m5.md) 熟悉排版界面。深浅主题可在「设置 › 应用设置 › 主题」切换。

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
& $python -B packaging/build_inkstruct_app.py --output build/0.1.70
& $python -B packaging/verify_public_windows.py --bundle build/0.1.70/dist/InkStruct --output build/verification
```

从源码启动可运行 `python -m inkstruct.application --workspace workspace`。构建安装程序时，从 [NSIS 锁](packaging/nsis-win.lock.json) 下载编译器 ZIP，保持原样，并执行：

```powershell
& $python -B packaging/build_windows_installer.py --verification build/verification/verification.json --nsis-zip nsis-3.13.zip --output build/installer
& $python -B packaging/verify_windows_installer.py --installer-build build/installer/installer-build.json --zip build/verification/InkStruct-0.1.70-Windows-x64.zip --output build/installer-check
```

## 许可与贡献

[源码许可](LICENSE) · [第三方许可与资源来源](THIRD_PARTY_NOTICES.md) · [贡献指南](CONTRIBUTING.md)

反馈请使用最小合成样例。真实笔迹、作者档案、私人字体和文档留在个人工作区。
