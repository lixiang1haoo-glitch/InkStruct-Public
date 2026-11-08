# InkStruct 0.1.56 · Windows 启动首页修复

附件中的 0.1.55 与原交付 EXE 的 SHA-256 一致，为 `b7ad797d53d97f99fccdd00779a669e2dede768bf839bbca201c04c205e54ede`（以附件实测 PowerShell 日志为准）。复测用当前 Windows 全局默认设置，GPU 预览、同一四页 PDF 模板和 user_001 的 454 MB 默认字体。各次仅使用独立工作区和临时目录。

原附件三次测得主窗口可见后 664–668 ms 绘出 PDF，且在绘出前能观察到 SVG 子进程请求和空白纸张。仅改变绘制方式的中间原型还遇到一次 6.48 秒的等待，画布没有显示提前首页。启动请求被重复排版替换时，原有的提前显示机会可能随旧请求丢失。

正式构建在提交默认字体排版前先准备一个已校验的空白 PDF 底图，直接送入首屏绘制。启动中等价的重新排版保留这张底图，正文或模板配置变更后按新修订处理。涉及真实笔迹、框线、图像或诊断覆盖的页面按原有完整绘制流程处理。默认字体校验和严格导出仍以完整当前快照为准。

## 验收

- 解包后的最终 `InkStruct.exe` 连续六次实际启动，主窗口可见到原 PDF 底图显示为 291–336 ms。每次开新进程，保留 Windows 文件缓存。用前台画面中的 PDF 实际印刷内容判断，灰色画布、白色纸张和弹窗不算完成。
- 独立故障探针省去旁边的 `InkStructTool.exe`，底图仍在主窗口出现后 294 ms 绘出。该探针仅验证启动底图的独立性，正常使用应解压完整包。
- 38 项回归通过，包含启动中主动重复提交排版、已显示底图保留、输入后过期底图清除、GPU 回退及后台 SVG 导出。两份 EXE 的文件版本、产品版本和解包后冻结自检均为 0.1.56。ZIP 完整性通过。
- README、使用说明和 LaTeX 手册源码已同步。未重编译 LaTeX 手册 PDF。

## 构建与产物

```powershell
.venv/Scripts/python.exe -B -X utf8 packaging/build_inkstruct_app.py --output artifacts/packed_startup_0.1.56_rebuild
```

最终发布包在 `artifacts/packed_startup_0.1.56_final/release/InkStruct-0.1.56-Windows-x64.zip`。SHA-256 为 `5c5582c4ef695ecc0b6118c8e5871a0b8ebccdb0db67809c962ec16bae3f14bc`。

原附件实测位于 `artifacts/packed_startup_gpu_0.1.55/attached-visual/`。最终 EXE 的实测、截图、故障探针和回归日志位于 `artifacts/packed_startup_0.1.56_final/`。中间原型数据保存在 `artifacts/packed_startup_0.1.56/packed-gpu/`。

