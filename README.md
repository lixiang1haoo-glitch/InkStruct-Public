# InkStruct 墨构

把自己的笔迹做成可复用的字体，再用它排出一页 Markdown。InkStruct 在本机完成采集、生成、制包和排版。

[获取源码](#获取源码) · [从笔迹到文档](#从笔迹到文档) · [源码构建](#源码构建) · [使用说明](docs/USER_GUIDE.md) · [反馈问题](CONTRIBUTING.md)

Windows x64 · 0.1.68 · Python / Qt

## 获取源码

从 [0.1.68 源码标签](https://github.com/lixiang1haoo-glitch/InkStruct-Public/tree/app-v0.1.68) 获取对应版本，或克隆本仓库的 `main` 分支查看最新说明。目前公开的是源码。Windows 安装程序和免安装 ZIP 可用下文步骤在本机构建。构建产物使用 Windows 的 UCRT 和系统安装的 Microsoft Visual C++ x64 运行库。 [Windows 分发说明](docs/WINDOWS_DISTRIBUTION.md) · [Microsoft 运行库](https://learn.microsoft.com/cpp/windows/latest-supported-vc-redist)

## 从笔迹到文档

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
& $python -B packaging/build_inkstruct_app.py --output build/0.1.68
& $python -B packaging/verify_public_windows.py --bundle build/0.1.68/dist/InkStruct --output build/verification
```

从源码启动可运行 `python -m inkstruct.application --workspace workspace`。构建安装程序时，从 [NSIS 锁](packaging/nsis-win.lock.json) 下载编译器 ZIP，保持原样，并执行：

```powershell
& $python -B packaging/build_windows_installer.py --verification build/verification/verification.json --nsis-zip nsis-3.13.zip --output build/installer
& $python -B packaging/verify_windows_installer.py --installer-build build/installer/installer-build.json --zip build/verification/InkStruct-0.1.68-Windows-x64.zip --output build/installer-check
```

## 许可与贡献

[源码许可](LICENSE) · [第三方许可与资源来源](THIRD_PARTY_NOTICES.md) · [贡献指南](CONTRIBUTING.md)

反馈请使用最小合成样例。真实笔迹、作者档案、私人字体和文档留在个人工作区。
