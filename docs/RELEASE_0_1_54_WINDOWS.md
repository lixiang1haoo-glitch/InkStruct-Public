# InkStruct 0.1.54 · Windows 交付记录

Windows x64，Python 3.13.16，PySide6 6.9.2，PyInstaller 6.22.3。应用版本源为 `src/inkstruct/fonts/__init__.py`；Python 库和字体协议版本未变。验收使用独立工作区和现有 user_001 符号字体的只读输入或副本。保留用户数据、冻结选样、未提交工作及历史发布包。

- 正文与段落保留设置控件，移除局部效果预览。公式「间距与数学轴」两栏按 1、2、3、4 从上到下排列，保留多行示例和实测标线。
- 「存为默认」保存后关闭；「应用并保存」还更新当前文档，保留表格与图片的独立设置，保持窗口打开；「取消」仅放弃尚未保存的草稿。无当前文档时隐藏「应用并保存」。
- 两个资源库的「更多操作」可打开所选资源的实际所在文件夹。两个采集页以同一布局呈现「画布大小」和「笔迹粗细」，保留独立设置和原有采集坐标语义。
- 主窗口、Windows GUI 程序文件使用新图标。Qt 启动后、主窗口初始化前显示「正在启动…」，主窗口显示后结束。未更改初始化成本，未测量用户机器上的 Windows 冷启动。

## 验证

- 600 项相关回归通过；覆盖设置按钮、表格和图片独立属性、采集、资源管理、公式、排版和 SVG。首次运行暴露一处旧测试还按旧复选框的持续状态恢复当前文档；改用明确的应用动作后完整重跑。
- 150% 和 200% Windows 原生 Qt 窗口通过 11 个公式分类、标线顺序、实时更新、取消、应用、保存重开、冻结选样及 SVG 一致性检查。150% 主窗口检查通过启动提示生命周期、正文预览移除、无文档时隐藏按钮、两套滑块及独立值；两库菜单触发验证了传给 Windows 的正确本地目录 URL，验收脚本拦截系统打开调用，未检查资源管理器实际弹窗。
- ZIP 通过 CRC，解包后双 EXE 的文件版本、产品版本和运行自检均为 0.1.54；双 EXE 的公式自检覆盖 11 类和 26 项实测尺寸。GUI 的 PE 资源含一个图标组、七种尺寸；SVG 和 ICO 随包。未重编译 LaTeX 手册 PDF，未验证实体数位板和真实 Windows 冷启动耗时。

## 复现与产物

以下在项目根目录执行。构建和验收目录应使用未占用的新目录。

```powershell
.venv/Scripts/python.exe -B -X utf8 packaging/build_inkstruct_app.py --output artifacts/settings_startup_0.1.54/rebuild
$e = (Resolve-Path artifacts/settings_startup_0.1.54).Path
$env:PYTHONPATH = (Resolve-Path src).Path
$env:QT_QPA_PLATFORM = 'windows'
$font = (Resolve-Path artifacts/font_capacity_simplified_20261104/input_audit/user_001-symbols-current-rules.inkfont).Path
.venv/Scripts/python.exe -B -X utf8 "$e/native_shell.py" "$e/native-shell-recheck" "$font"
# 在主机 150% 显示缩放上，分别使用 1 和 1.333333333 作为 QT_SCALE_FACTOR 重跑原生公式验收。
$env:QT_SCALE_FACTOR = '1'
.venv/Scripts/python.exe -B -X utf8 "$e/native_math.py" "$e/native-math-recheck" "$font" 1.5
```

发布包：`artifacts/settings_startup_0.1.54/release/InkStruct-0.1.54-Windows-x64.zip`。完整文件、SHA-256 和双 EXE 自检见同一目录。构建日志 `build.log`，回归日志 `regression-final.log`，截图及原生检查记录在 `native-150/`、`native-200/`、`native-shell/`。
