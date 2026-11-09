# CLI 与快速开始

以下命令针对 **0.1.69** 源码，在 PowerShell 中运行。示例只有两个字形，不需要采集笔迹或下载生成结构库。

## 环境

在新目录准备对应源码和独立 Python 环境。示例使用 Python 3.13。Qt 窗口预览需要 `desktop` 依赖。

```powershell
git clone --branch app-v0.1.69 --depth 1 https://github.com/lixiang1haoo-glitch/InkStruct-Public.git
cd InkStruct-Public
py -3.13 -m venv .venv
$python = ".\.venv\Scripts\python.exe"
& $python -m pip install -e .
```

从[开发者首页](./)下载两个合成文件，放到当前目录。也可以将[生成脚本](https://github.com/lixiang1haoo-glitch/InkStruct-Public/blob/main/examples/make_format_examples.py)保存到发行检出的 `examples/`，然后运行：

```powershell
& $python examples/make_format_examples.py .
```

脚本会拒绝覆盖同名示例。

## 检查缺字

```powershell
& $python -m inkstruct.cli document resources two-shapes.inkdoc
```

报告为 JSON，`gaps` 是缺口列表。示例已嵌入需要的两份笔迹，列表为空。发现缺口时可加 `--capture-csv new-capture.csv` 另存采集任务，已有目标文件会被拒绝。检查不会保存回原项目。命令成功返回 0，仍需读取 `gaps` 判断覆盖情况。

原始 Markdown 也可用于资源检查，可通过 `--run` 或 `--symbols` 提供对应资源。`.inkdoc` 使用自己的嵌入资源。

## 生成 SVG

```powershell
& $python -m inkstruct.cli document render two-shapes.inkdoc --output rendered --no-png
```

首次运行会在新目录 `rendered` 输出 `page-001.svg` 和 `layout.json`，终端打印 JSON 报告。检查 `pages`、`exportable` 和 `diagnostics`。渲染成功返回 0，包读取失败或遇到阻止导出的问题时返回 2。生成写字机所需的路径 SVG 时另用 `--plotter`，它有单独的资源与导出检查。

## 命令速查

| 命令 | 输入 | 输出 |
| --- | --- | --- |
| `document inspect notes.md` | UTF-8 Markdown | JSON，含语法结构和源位置；无需字形 |
| `document resources two-shapes.inkdoc` | 项目或 Markdown | JSON 缺口报告；可选另存采集 CSV |
| `document preview two-shapes.inkdoc` | 项目或文本 | Qt 分页预览窗口；需要桌面依赖 |
| `document render two-shapes.inkdoc --output rendered --no-png` | 项目或文本 | 页面文件与 JSON 报告 |
| `document template --help` | 子命令入口 | 查看模板检查、预览与绑定参数 |

纯 Markdown 用 `render` 或 `preview` 时需传 `--mode markdown`。`.inkdoc` 会启用 Markdown 模式并读取保存的方言与设置。桌面依赖可用 `& $python -m pip install -e ".[desktop]"` 安装。更多参数以[对应版本的命令实现](https://github.com/lixiang1haoo-glitch/InkStruct-Public/blob/app-v0.1.69/src/inkstruct/document/cli.py)和 `--help` 为准。
