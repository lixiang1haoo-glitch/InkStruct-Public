# 设置移至左下角

2026-11-05，在当前未提交工作树上继续界面试点，APP_VERSION 保持 0.1.46，不制作发布构建。

- 移除自绘的顶部品牌／版本／设置横栏；原系统标题栏继续显示 `InkStruct 墨构 · APP_VERSION`，不自绘窗口边框。
- 设置按钮移至左侧“字体库”下方，保持齿轮和文字，与各模块导航独立；点击不会改变当前模块选中状态。原设置回调和 Ctrl+, 保持。
- Tab 顺序依次经过采集、生成、排版、字体库、设置。关于功能保留在侧栏右键菜单及 F1，不添加额外按钮或设置下拉箭头。

只修改 `src/inkstruct/app_shell.py` 与 `tests/test_app_shell_qt.py`。本轮开工快照 501 个既有源码／测试文件中其余 499 个未变。用户数据、文档设置、字体、冻结选样及上一轮界面修改保持；未改独立排版目录，没有 reset、clean、提交或推送。

最终相关测试 **41 通过、0 失败、0 跳过，67.07 秒**；Ruff 通过。覆盖 100%、150%、200% Qt 缩放下的模块切换、设置固定位置／父控件／相对顺序、系统标题、无顶部横栏、F1、设置事务及字体库。另一次早期运行 41 通过，不累计为 82。

原生 Windows 源码验收：DPR1.5、逻辑 DPI96，观察 1360×900 的初版布局和最终 1000×720 布局。最终实际点击左下设置进入采集设置，Esc 取消；Alt+4 回字体库，底部设置常驻。最终字体库截图包含实际系统标题栏：`artifacts/sidebar_settings_20261105/native-compact/03-library-native-frame.png`。验收窗口标题额外标注“界面验收”，普通应用没有该后缀。

原生浏览前后，真实旧文档仍为 2 页、23 处冻结选样，源码身份和选样记录相同。此轮没有重做原生保存／SVG操作；相关完整语义专项保留上一轮记录，不冒充本轮新测。原生完整缩放切换、读屏、数位板、写字机及冻结EXE未验证。

初版把“关于”动作挂在 QToolButton 上时出现不必要的菜单指示箭头；最终改挂侧栏上下文菜单并重跑上述 41 项，初版截图保留在 `native-final`。最终日志、XML、原生记录及前后源码快照在 `artifacts/sidebar_settings_20261105`。实验窗口已正常关闭。

本轮准确命令（项目根目录 PowerShell）：

```powershell
.venv/Scripts/python.exe -B -X utf8 artifacts/sidebar_settings_20261105/check_final.py
.venv/Scripts/python.exe -B -X utf8 artifacts/sidebar_settings_20261105/native.py --compact
.venv/Scripts/python.exe -B -X utf8 -m ruff check src/inkstruct/app_shell.py tests/test_app_shell_qt.py
```

辅助脚本的设置和工作区全部隔离，复测须换新输出目录以保留本轮产物。最终测试日志 `tests-final-02.log`，XML `tests-final-02.xml`，原生日志 `native-compact.log`，源码比较 `source-preservation-final.json`。
