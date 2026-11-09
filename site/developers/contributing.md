# 构建、验证与贡献

应用、安装包和文档站各有自己的构建入口。排版脚本可先用 [CLI 快速开始](./cli) 的轻量环境。桌面应用与 Windows 发布按仓库 README 的锁定流程准备。

## 从源码构建 Windows 应用

1. 在独立检出中选择要验证的发布标签或提交，并确认工作区状态。
2. 按 README 准备 CPython 3.13.16 x64，使用 `packaging/windows-x64-py313.lock` 安装带哈希的依赖。运行 `packaging/prepare_public_resources.py`，从锁定来源准备采集器、结构库等输入。
3. 运行 `python -m inkstruct.application --workspace <测试工作区>` 验证界面。使用独立工作区和合成数据复现。
4. 运行源码回归，再构建便携包与安装器。精确参数集中在 README。[0.1.69 源码构建](https://github.com/lixiang1haoo-glitch/InkStruct-Public/tree/app-v0.1.69#源码构建)

## 选择回归范围

安装测试依赖并配置好 README 中的 `PYTHONPATH` 后，可在仓库根目录运行：

```powershell
& $python -B -m pytest -p no:cacheprovider tests/test_font_packages.py tests/test_document_layout.py tests/test_symbol_provider.py
```

格式改动用实际读写器检查正向样例、旧版本和损坏文件。涉及排版时比较重开前后的选样与输出。涉及桌面界面时记录 Windows 版本、缩放、主题与复现步骤。

## Windows 发布与分发

发布从拟发布提交的干净检出开始，记录提交 ID、锁定输入哈希、回归结果和产物 SHA-256。构建后验证 ZIP 和安装版，包含运行库缺失、恢复运行库后安装、启动、卸载与用户文件保留。发布新应用构建时递增应用版本，验证通过后为对应提交创建 `app-v<版本>` 注解标签。

0.1.69 的安装器和 ZIP 依赖系统 Microsoft Visual C++ x64 运行库。随包动态库、许可、替换说明和对应源码见分发说明。[Windows 分发说明](https://github.com/lixiang1haoo-glitch/InkStruct-Public/blob/app-v0.1.69/docs/WINDOWS_DISTRIBUTION.md) · [Windows 验证工作流](https://github.com/lixiang1haoo-glitch/InkStruct-Public/blob/app-v0.1.69/.github/workflows/windows-release-check.yml)

## 预览和维护文档站

使用 Node.js 24 和 `site/package.json` 指定的 pnpm 版本。在仓库根目录运行：

```powershell
pnpm -C site install --frozen-lockfile --ignore-scripts
pnpm -C site dev
pnpm -C site build
```

文档页的顶部导航和分组侧栏定义在 `site/.vitepress/config.mts`。修改格式页时记录适用版本，用发布标签链接读写器或测试。修改示例时先跑读写回归，再检查网页上的下载与命令。文档工作流构建 VitePress 并部署到 GitHub Pages。[部署工作流](https://github.com/lixiang1haoo-glitch/InkStruct-Public/blob/main/.github/workflows/docs-pages.yml)

提交问题或改动时附上最小合成样例、应用版本和验证结果。公开样例只包含可公开分享的材料，真实笔迹和文档留在个人工作区。[仓库贡献指南](https://github.com/lixiang1haoo-glitch/InkStruct-Public/blob/main/CONTRIBUTING.md)
