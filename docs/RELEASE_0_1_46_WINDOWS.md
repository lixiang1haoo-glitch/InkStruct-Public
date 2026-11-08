# InkStruct 0.1.46 Windows 交付记录

2026-11-04。项目 `C:/Users/lee/Documents/InkStructApp/InkStruct-Windows-Dev`，Git HEAD `af45b45f04f899fcaced43aa980b0508673ee6c0`，基于保留全部未提交工作的完整源码构建。APP_VERSION 从0.1.45递增为0.1.46；Python库0.2.0、字体格式1.0和现有文档协议不变。

当前状态：Windows构建、双EXE冻结验收、原生大字体导入/预览及最终ZIP解压运行检查完成，可交付。

## 本次交付范围

- 字体包总展开容量从2 GiB增到4 GiB。保留32 MiB单成员、10万成员、每候选10万点及路径、重复、加密、哈希、来源等检查。写入端在原循环累计成员与最终manifest，超限时不发布正式文件，不覆盖现有包。
- 生成页每字成品上限可输入1–64，默认4，含原主字形；8份最多32次提案。v6.1/v4仍为1份。偏好独立保存，处理期间锁定，任务使用提交时捕获的值。
- 新批次采用完整部件均衡遍历，允许同一来源字的不同真实录制样本，并有限尝试双部件组合；每份在最终整字上下文检查。保留原主字形及真实动态数据，不足时保存实际数量，不复制凑数。

生成方式继续显示实际的v6.2 exp、v6.1 exp及v4 adaptive；未将冻结的v6.2记录改名为v6.3，也未引入v7研究规则、随机扰动或神经网络。旧字体和文档不自动更新资源或重选样本，已有任务、进度、作者档案和生成结果保留。

## 大字体依据与使用边界

沿用同一份user_001全库八份上限结果及同一份206字符、1306候选的英文、希腊、数字、数学和标点等扩展。简体臂是《通用规范汉字表》2013与结构库的6866字交集；1239个不支持字明确列出，不转换原文、不补造字形，不减少供体池。

| 用户字体 | 字符/候选 | ZIP字节 | 展开字节 |
|---|---:|---:|---:|
| 全结构库＋扩展 | 9780/37500 | 611140081 | 3046226671 |
| 简体支持集＋扩展 | 7072/29726 | 454351365 | 2254681346 |

简体包ZIP省25.655%，展开量省25.984%。两包共同29726候选的记录、度量、来源和原轨迹字节保持；没有降低精度或删动态。两包都超过旧2 GiB策略，新版提供读取支持。原2 GiB源码读者已实测拒绝这两包；不把旧EXE兼容性写成已通过。

上述个人字体独立保存，不内置于应用ZIP，不自动写入生产字体库。路径及完整实验边界见 [容量与简体对照](FONT_CAPACITY_SIMPLIFIED_20261104.md)。

4 GiB为本轮有限容量策略，不意味着只需4 GiB RAM，也不证明任意4 GiB内容或全库文字同时排版的安全和流畅度。普通编辑按涉及字符准备候选，索引常驻；首次读取仍可能等待完整校验。文档200 MB压缩/500 MB展开、资源目录和布局点数保护不变。7.16 GB展开的全库开发者记录仍不能作为一份4 GiB字体加载。

## 验收记录

环境：Windows 11 x64、Python3.13.16、NumPy2.5.4、PySide6 6.9.2、Matplotlib3.11.2、PyInstaller6.22.3；沿用项目内.venv，没有安装训练或全局依赖。

1. 114文件综合回归1603项通过，0失败、0错误、0跳过，262.84秒；260份运行源码前后哈希一致。新增自检参数另有4项通过，非重复合计1607个用例。
2. 源码大字体自检通过：两包完整4进程校验、8/64份控件及锁定、3页187处中英/希腊/数学混排、保存重开、冻结选样和严格SVG一致；每包2条数学校准warning保留。此前自检错误给只读style属性赋值，仅修正测试编排为loaded_style，source-01失败保留，source-02重新通过。
3. 标准Windows构建52.05秒，328份输入哈希在构建前后保持一致。双EXE均为AMD64，FileVersion/ProductVersion为0.1.46。正式Tool/GUI各自完整读取两实际大包，4个真实spawn工作进程分别校验37500/29726候选，耗时108.09/105.16秒；来源警告3204/1887和每包2条数学校准warning保留。每包3页187处首末页预览就绪，保存重开、冻结、严格SVG字节相同，两包共有候选及输出几何相同。`use_font`首次同步调用约7.2/5.5秒，不能把该离屏检查称为原生冷打开流畅度认证。
4. 正式Tool另使用完整真实user_001档案，对“嘤喳啜哮”做串行与双进程默认4份小样。两次分别8.955/7.940秒，均4字13候选、完整payload一致，无回退；喳的原来源缺口保留，96处冻结、保存重开和严格SVG通过。本项不是冻结8份全库生成测试。
5. 原生Windows验收使用正式dist的完整真复制，仅在副本替换自检数据入口来隔离INI/collector配置，实际EXE和应用模块与正式版相同。1360×900逻辑像素、DPR1.5，实际操作四主标签、数量4→8→1→64→8及两旧方法锁1/返回恢复8。通过原生文件框导入454351365字节的简体大包，约34.22秒（1秒状态采样界限），4个工作进程完整验证29726候选，来源提示保留；用于本文、粘贴小Markdown和完整可见预览通过，实际点击沐显示样本2/8及周边校正预览。保存20张截图；正式1672文件及副本EXE/模块哈希未变。两次文件框UIA缓存失效改用新截图和键盘完成，没有激活失败。私有shim的app.quit后进程仍存活，核对路径后仅终止自己的私有PID；不将此宣称为普通关闭交互验收。原生未做保存重开/导出，相关能力由上面的实际冻结自检单独证明。
6. 最终ZIP包含1673文件（含使用README），CRC及解压后每文件SHA-256全部匹配。从全新解压目录、以该目录作为cwd，清除子进程PYTHONPATH/PYTHONHOME，实际运行Tool四字生成/制包/重开/SVG检查，exit0，20.54秒。解压运行不依赖项目cwd。

初始未发布的归档候选误含只读SQLite访问产生的SHM与空WAL；主数据库字节哈希与构建源一致，另对全部9574条目计算逻辑哈希一致。仅在最终归档排除这两份已核定运行副产物，不修改源数据库。原候选及其哈希在`archive-candidate-01/`保留，未覆盖旧版交付。最终正式ZIP为126997851字节，SHA-256：`73c0ea232353e940ab06a49e008602d10f41cf2e069b1fbc8d9a6faa8e94784c`。

自检的新`--large-font-check`分支使用真实大包，不走旧样本/生成/通用数学fixture，不重跑全库。原字体SHA前后核对，完整逐候选校验仍执行，实际冻结spawn及worker PID由新EXE记录。原校准、来源及尺寸诊断继续保留。

## 启动、测试与构建

在项目根目录执行，带NEW的输出必须是新目录，不能覆盖本次或历史交付。

```powershell
.venv/Scripts/python.exe -B -X utf8 -m inkstruct.application
.venv/Scripts/python.exe -B -X utf8 scripts/run_layout_regression.py tests/test_candidate_count_qt.py tests/test_component_generation.py tests/test_generation_candidate_limits.py tests/test_generation_resources.py tests/test_generation_targets_qt.py tests/test_generation_variant_balance.py tests/test_parallel_font_verify.py tests/test_source_generation_entry.py tests/test_v62_semantics.py --junitxml=artifacts/regression-0.1.46-NEW.xml --basetemp=artifacts/pytest-0.1.46-NEW
.venv/Scripts/python.exe -B -X utf8 packaging/build_inkstruct_app.py --output artifacts/windows_build_0.1.46-NEW
```

正式程序从新目录完整解压后运行`InkStruct.exe`；`InkStructTool.exe`为同构建的伴随自检程序。默认工作区沿用原应用路径，不要求卸载、删除工作区或重建原任务。可显式传入`--workspace`选择其他工作区。

本次产物根为`artifacts/release_0.1.46_20261104/`，包含701文件开工快照、Git状态、回归、失败日志、源码/冻结自检、原生验收与最终保全。构建为`artifacts/windows_build_0.1.46_20261104/dist/InkStruct/`，正式分发为`artifacts/windows_release_0.1.46/InkStruct-0.1.46-Windows-x64.zip`，SHA文件在旁。

双EXE实际命令、worker PID、耗时和警告见`frozen-check/README.md`和`final-summary.json`。实际新入口可复现为：

```powershell
$env:INKSTRUCT_LAYOUT_PREVIEW_HOME=(Join-Path (Get-Location) 'artifacts/frozen-private-0.1.46-NEW')
artifacts/windows_build_0.1.46_20261104/dist/InkStruct/InkStructTool.exe --inkstruct-check --large-font-check --large-font artifacts/font_capacity_simplified_20261104/package-experiment/run-01/user_001-all-supported-8-candidates-and-symbols.inkfont --large-font artifacts/font_capacity_simplified_20261104/package-experiment/run-01/user_001-simplified-supported-8-candidates-and-symbols.inkfont --output artifacts/frozen-check-0.1.46-NEW
```

图形EXE使用相同参数；命令行为离屏自检。原生记录为`native/REPORT.md`、`native-result.json`及`run-01/`截图；解压运行的完整命令和私有环境为`extracted-check-01/command.json`。数据库逻辑校验为`database-verification.json`，分发CRC/SHA清单为正式分发目录的`delivery-verification.json`。

README、统一使用说明和LaTeX手册源码已同步0.1.46；未重编手册PDF。未全库逐字人审，实体数位板/驱动、写字机与中文输入法未在本轮验收。保留未提交工作，不执行reset、git clean、提交或推送，不改独立Layout-Dev目录。

最终保全见`final-preservation.json`：328份构建输入仍与冻结一致，1387份符号输入和旧生成审计中的1415份数据文件哈希保持；旧审计另外包含的APP_VERSION文件按本轮授权升版，未伪称其未变。历史0.1.45 ZIP哈希保持原值。仅清理本轮PyInstaller work、pytest临时目录、私有回归临时缓存及已核定的构建/解压副本SQLite运行副产物，未删除源数据库或任何用户样本；精确路径见`cleanup.json`。源码、失败记录、原生私有实例证据、字体、生成结果和交付产物保留。
