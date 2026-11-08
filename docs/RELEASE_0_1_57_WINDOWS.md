# InkStruct 0.1.57 · Windows 交付记录

2026-11-08。生成页的浅绿色进度和深绿色速度面积共用已处理边界。近期速度以字/秒显示，读数靠右并随横线升降。设置中的「汉字参考格比例」注明以画布短边为基准。

## 验收

- 88 项相关回归通过，包含生成工作流、并行与候选上限、采集、统一设置，以及进度图的像素边界、读数对齐、准备、取消和重新开始。
- Windows 原生实窗使用本次构建及隔离工作区，读取 scx 的 793 份既有采集样本。在默认 v6.2 exp 下生成「中国书法」，4 字完成、0 失败，进度到 100%。随后生成 55 字自定义字表，运行中观察到两层绿色边界对齐及右侧速度。点击取消后，保留已完成的 32 字，剩余 23 字，界面显示已取消及 58%。两次均由 1 个工作者计算。
- 在发布版实窗打开「设置 → 采集设置 → 书写显示」，确认显示「汉字参考格比例」和画布短边说明。取消对话框后退出验收窗口，未保存全局设置。
- ZIP 解包验证通过。解包后的 `InkStruct.exe` 与 `InkStructTool.exe` 的文件版本、产品版本和冻结自检均为 0.1.57。两份公式自检均覆盖 11 类、26 项实测尺寸。
- 0.1.56 发布 ZIP 的 SHA-256 与原交付记录一致。此次生成结果写入隔离工作区。README、使用说明和 LaTeX 手册源码已同步，未重编译手册 PDF。本次实窗验收限于小字集和相关界面。

## 构建与产物

```powershell
.venv/Scripts/python.exe -B -X utf8 packaging/build_inkstruct_app.py --output artifacts/release_0.1.57_20261108/windows-final
```

发布 ZIP 位于 `artifacts/release_0.1.57_20261108/release/InkStruct-0.1.57-Windows-x64.zip`，SHA-256 为 `51e6e26d79c536cba01c676a9cb3d69072da298d64f349a226b862065aab540b`。完整解压后运行 `InkStruct/InkStruct.exe`。

同目录树下保留 `windows-final/build.log`、`windows-final/build-provenance.json`、`regression.log`、`delivery.log`、实窗状态记录和 `native-workspace/generation/outputs/`。双 EXE 的冻结自检及归档哈希在 `release/` 下。
