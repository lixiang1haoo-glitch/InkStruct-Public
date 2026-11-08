# Windows 应用 Git 基线

本分支从现有研究与生成内核历史接续，将 Windows 0.1.59 的应用源码、采集内核、测试、配置、构建入口和手册纳入 Git。应用版本仍由 `src/inkstruct/fonts/__init__.py` 的 `APP_VERSION` 定义。原 Windows 交付包的版本和 SHA-256 见 [0.1.59 发布记录](RELEASE_0_1_59_WINDOWS.md)。

当前 Windows 发布为 [0.1.64](RELEASE_0_1_64_WINDOWS.md)。从对应发布源码检出核验时，可将下方命令的版本和 ZIP 换成 0.1.64。为更新的源码检出准备已锁定公开资源时，可加 `--resources-only`，核验原发布 ZIP 和公开资源哈希。

## 从干净检出核对并构建

使用 Windows x64 和 Python 3.13。准备原始的 `InkStruct-0.1.59-Windows-x64.zip`。仓库中的资源清单记录发布 ZIP 和各资源的 SHA-256。准备命令只提取列明的公开结构库、参考字形及许可文件，有冲突时保留现有文件并报错。需要完整 Makemeahanzi 数据的研究任务另行初始化子模块。

```powershell
py -3.13 -m venv .venv
.venv/Scripts/python.exe -m pip install -e '.[desktop,dev]' PyInstaller==6.22.3 pyinstaller-hooks-contrib==2026.8 numpy==2.5.4 Pillow==12.3.0 matplotlib==3.11.2
.venv/Scripts/python.exe -B -X utf8 packaging/prepare_windows_baseline.py 0.1.59 '<原始发布 ZIP 路径>'
$env:PYTHONPATH = (Join-Path $PWD 'src') + ';' + (Join-Path $PWD 'artifacts/external/data_collection')
.venv/Scripts/python.exe -B -X utf8 packaging/build_inkstruct_app.py --output '<新验证目录>'
```

准备命令省略 ZIP 参数时只核对已经准备好的资源和工作树。核对以发布构建清单为准，包含文件原始字节。部分 Windows 发布源文件保留原换行，规则记录在 `.gitattributes`。原始构建的工具版本和 340 个输入哈希保存在 [构建溯源](releases/0.1.59-build-provenance.json)。

此基线的 0.1.59 构建用于验证 Git 检出，正式交付仍以已发布 ZIP 为准。 提交、发布包哈希、171 项通过和 4 项已知失败的对应关系见 [Git 验证记录](releases/0.1.59-git-verification.json)。样本、作者档案、字体、生成结果、排版文档与测试产物保存在仓库外或被忽略的工作区。保留原有研究提交，未审查的研究工作树增量继续留在原目录。

## 后续发布

- 将应用改动和回归测试提交到发布分支。依据交付约定递增应用版本，并同步说明和发布文件名。
- 在干净检出准备锁定的输入，运行回归、构建和发布自检。记录提交 ID、构建输入哈希、测试结果和发布 ZIP 的 SHA-256。
- 通过后为已验证提交添加 `app-v<版本>` 注解标签。交付包与溯源文件应随版本归档，以便下一次验证检出时使用。

## 历史恢复

现有 Git bundle 保留原始提交历史。旧发布可从构建记录、源码 ZIP、补丁和本地检查点恢复。只有全部必需输入匹配正式构建记录后，才为旧版本创建重建提交，并在标签中注明重建来源。部分恢复的版本记录已确认文件及缺口。详见 [历史恢复核对](releases/HISTORY_RECOVERY.md)。
