# macOS 安装与本地数据恢复

macOS 已验证 Python 3.13、CPU 确定性生成以及 PySide6 桌面启动。Windows 虚拟环境、CUDA 锁定依赖和 EXE 不能直接复用。Mac 训练和数位板真实笔事件尚未验收。

## 安装和启动

在项目根目录执行：

```bash
git submodule update --init --recursive
bash scripts/setup_macos.sh
.venv/bin/inkstruct structures info
```

默认使用 `python3.13`。若已有 Python 3.12，可执行 `INKSTRUCT_PYTHON=python3.12 bash scripts/setup_macos.sh`。已有 `.venv` 会复用。首次没有结构库时执行 `.venv/bin/inkstruct structures build`。

双击项目根目录的 `run_inkstruct_generator.command` 或 `run_inkstruct_collector.command`。也可在终端运行：

```bash
.venv/bin/inkstruct-generator
.venv/bin/inkstruct-collector
```

生成器直接读取 `profiles/<writer-id>/profile.json`。选择已有作者 ID 后，可以直接生成文本；无需重新导入或覆盖档案。

## 外部采集器

采集器依赖独立的 `handwriting_collector` 内核，源码不属于当前 Git 仓库。恢复目录为：

```text
artifacts/external/data_collection/handwriting_collector/ui.py
```

也可显式指定包含 `handwriting_collector` 子目录的路径：

```bash
INKSTRUCT_COLLECTOR_SOURCE="/path/to/data_collection" .venv/bin/inkstruct-collector
```

显式路径无效时会报错，不会静默使用其他内核。未设置环境变量时，依次检查上述本地恢复目录、`legacy/data_collection`、仓库同级的 `data_collection`。普通单字采集无需 PyTorch；外部内核的 HDF5 导出需要另装 `h5py`。

## 恢复数据的边界

源码以当前 Git 分支为准。旧机器的源码可能落后，不能把整个旧目录覆盖到新克隆中。仅将所需的 `artifacts/structures`、`artifacts/samples`、`artifacts/source_samples` 和 `profiles` 恢复到对应忽略目录；复制后对源文件和目标文件逐一核对 SHA-256。已有同名不同内容的文件应停止复制，使用独立目录保存。

`index.jsonl` 包含完整原始点、压力和时间，运行不依赖其中的旧 Windows `source_path`。保留旧索引可保持输入哈希；若要建立本机路径索引，向新的 `--destination` 导入本地原稿，再向新的 `--destination` 建档。不要用重新导入、重新建档的产物冒充旧实验输入。

历史 profile 和旧输出用于对照；新实验用独立目录和新的 run-id。CASIA 训练集、CUDA 模型、旧虚拟环境及 Windows 发布包不属于 CPU 生成的必需数据，按后续任务需要再迁移。所有个人笔迹和生成产物均保持 Git 忽略。

## 检查

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest
.venv/bin/ruff check src tests scripts packaging
QT_QPA_PLATFORM=offscreen .venv/bin/inkstruct-collector --smoke-test \
  --smoke-screenshot=artifacts/collector-macos.png
QT_QPA_PLATFORM=offscreen .venv/bin/inkstruct-generator --smoke-test \
  --smoke-screenshot=artifacts/generator-macos.png
```

没有安装可选 PyTorch 时，神经模型相关测试会跳过。离屏截图只验证窗口初始化和布局，不代表已验收真实数位板、高 DPI、笔离开窗口再进入等行为。
