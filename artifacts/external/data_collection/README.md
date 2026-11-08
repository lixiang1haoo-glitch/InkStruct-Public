# 手写轨迹数据采集器

基于 PySide6 的数位笔轨迹采集工具，支持单字任务和兼容旧数据协议的整行采集。

当前版本：**v1.2.0**

## 启动

```bash
python3 -m pip install -r requirements.txt
python3 app.py
```

Windows 可直接双击 `run_windows.cmd`。它会优先使用
`%USERPROFILE%\anaconda3\python.exe`；本机该环境已经包含所需依赖。

首次启动选择输出目录。单字任务可导入 UTF-8 TXT 或 CSV：

```csv
character,repeats
永,3
中,2
```

TXT 中每个非空白字符会被读取，重复汉字按首次出现位置去重。正式轨迹只接受数位笔事件，不接收鼠标书写。

## 输出

- `samples/<writer_id>/<codepoint>/<sample_id>.json`：原始单字轨迹。
- `legacy/<writer_id>/`：兼容 DiffInk `(N, 5)` 协议的 NPY/TXT。
- `tasks/<task_id>/state.json`：可恢复的任务进度。

单字 JSON 保留逻辑像素坐标、压力、相对时间、画布尺寸和逐笔结构；归一化应在训练数据预处理阶段完成。

## 界面设置

程序强制采用高对比浅色界面，不跟随 Windows 深色主题，避免标签和浅色采集背景混在一起。

“设置 → 书写界面设置”提供笔画粗细和田字格尺寸滑块。滑块放在独立模态对话框中，采集时不会因触碰画布附近的控件而误调参数。默认笔画比例为 200%，田字格占画布短边的 72%。

设置保存在系统应用配置目录下的独立 `ui_settings.json` 中；对话框底部会显示完整路径。显示设置不会改变轨迹 JSON 中的原始坐标、压力或时间。

## DiffInk 个人整行数据集

个人风格训练应使用“整行采集”页。任务文件要求：

- 推荐直接点击“创建内置 DiffInk 220 行任务（15–20 字）”；内置文本直接筛选自
  官方 HDF5，已按当前字表、15–20 字长度和 200+20 分区完成校验，运行时不依赖原始 HDF5。
- TXT：每个非空行是一条任务。
- CSV：必须有 `text` 列，可选 `task_id` 与 `split`；`split` 取 `train` 或 `val`。
- 每行 15–20 个字符，且每个字符都必须存在于 DiffInk 的 `All_zi.json`。
- 没有 `split` 时，前 200 行分到训练集、后 20 行分到验证集；至少需要 220 条互不重复的有效文本。

任务开始时选择实际采集链路：

- `Surface / 本机数位笔`
- `Sunshine / Moonlight 数位笔`

正式轨迹仍只接受数位笔事件。每写完一个字符并抬笔后，按一下 `Shift`
或点击“标记当前字符结束”；最后一个字符可在保存时自动补齐。`Shift`
与其他按键组合时仍作为普通修饰键，不会误加字符边界。前 20 条训练任务是试采，
必须先运行检查并查看 SVG 预览，才能继续其余任务。

整行原始数据写入：

```text
line_samples/<writer_id>/<task_id>/<sample_id>.json
line_tasks/<task_id>/state.json
```

原始 JSON 保存逻辑像素坐标、压力、时间、DPI、采集链路、笔划和字符边界。重录不会覆盖旧样本，任务状态只指向最新通过版本。

任务完成后点击“导出 DiffInk HDF5”。导出器会执行坐标居中、Qt Y 轴翻转、按纵向标准差等比缩放、逐笔 RDP 简化和结构质检，并生成：

```text
exports/<task_id>/<version>/
  personal_train.h5
  personal_val.h5
  personal_writer.json
  export_report.json
  rejected.csv
  previews/*.svg
```

训练集必须正好有 200 条、验证集必须正好有 20 条，且每条简化后点数在 200–2000 之间；否则只生成检查报告，不发布 HDF5。

本机 Anaconda 基础环境已经包含 PySide6、NumPy 和 h5py，无需联网安装。若使用其他 Python 环境，可从已有离线 wheel 安装依赖。
