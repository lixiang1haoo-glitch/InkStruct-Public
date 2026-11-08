# InkStruct 0.1.55 · Windows 交付

0.1.55 将启动首页与默认字体校验分开。空白文档可先显示纸张和模板底图。字体在后台执行原有完整成员校验，含自动页码的模板在拿到真实字体资源后绘出页码。启动提示在首页完成绘制后关闭，最多等待主窗口显示阶段约 500 毫秒。等待期间主窗口可处理输入。

启动时首次空白 Markdown 排版立即提交，连续编辑沿用原防抖。提前显示的页面只进入预览画布，当前修订的完整快照发布后才可校正或严格导出。字体读取失败仍在问题面板报告。该版本也首次发布了上轮实测的长文档按需读取与稳定首页提前显示，排版预算仍会阻断不符合条件的 SVG。

## 构建及验证

- Windows x64，Python 3.13.16、PySide6 6.9.2、PyInstaller 6.22.3。版本由 `src/inkstruct/fonts/__init__.py` 提供，README、使用说明和 LaTeX 手册源码已同步。
- 119 项相关回归通过，覆盖字体包、模板、预览进程、文档预算、续排、字形校正和后台 SVG 导出。
- 两个 EXE 的产品版本、文件版本与解包后自检均为 0.1.55。各通过 11 个公式类别和 26 项实测尺寸的冻结环境自检。ZIP 校验通过，SHA-256 为 `b262f0314a05c4eb55e18116bef1a43ea1914ef3d7c40152f0b181aa05d1f0c4`。
- 六种原生启动场景通过。简单模板 2.27 秒绘出，无字体的 PDF 模板 2.34 秒绘出。真实默认配置 2.51 秒绘出首页并关闭弹窗，8.54 秒完成字体准备。带页码时，底图 2.50 秒绘出，弹窗 2.75 秒关闭，真实页码 8.59 秒绘出。校验中输入“12”及缺失字体的底图与错误回退均通过。
- 长文档原生复核通过暂定页的导出限制、计算中编辑、撤销、连续粘贴、过期页面拒绝和最终页数。
- 初次验收脚本的页码断言要求底图必须赶在弹窗超时前绘完，编辑注入也依赖提前绘制事件。已按实际契约调整观察点，保留初次日志。最终同一构建源码六组完整复测通过。
- 原生验收使用源码启动入口与独立 INI 设置，Windows 显示缩放 150%，预览 100%。沿用真实四页 PDF 默认模板和 user_001 的 454 MB 字体。安装包验证覆盖冻结自检，首屏耗时由原生源码启动测量。LaTeX PDF 未重新编译。

## 复现与产物

在项目根目录执行，输出目录使用新路径。

```powershell
.venv/Scripts/python.exe -B -X utf8 packaging/build_inkstruct_app.py --output artifacts/startup_preview_0.1.55/rebuild
$env:PYTHONPATH = (Resolve-Path src).Path
$e = 'artifacts/startup_preview_0.1.55'
.venv/Scripts/python.exe -B -X utf8 "$e/native_startup.py" "$e/native-recheck" --runs 1
```

发布包在 `artifacts/startup_preview_0.1.55/release/InkStruct-0.1.55-Windows-x64.zip`。原生窗口记录与截图在 `native-final/`，双 EXE 核验日志为 `delivery.log`，回归记录为 `regression.log`。

实验依据见 [启动首页实验](STARTUP_PREVIEW_EXPERIMENT_WINDOWS_0_1_54.md) 和 [大量粘贴实测](LARGE_PASTE_PREVIEW_WINDOWS_0_1_54.md)。
