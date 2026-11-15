# 屏幕预览路径简化验证

渲染加速默认开启。屏幕预览组装 SVG 时，对每条笔段做 Ramer–Douglas–Peucker 简化，单点、首尾坐标和笔段顺序保留。阈值由整页逻辑尺寸、页面毫米尺寸和设备像素比换算，高倍率分块使用同一个整页比例。切换开关会复用排版快照，重绘可见页。画面缓存按页、缩放、设备像素比和开关状态区分，取消的请求不能更新缓存或画面。

## 未缓存混排页首帧

Windows 上使用 Qt 6.9.2 和 CPU 离屏绘制。正文、表格、分式和参考位图位于同一张 A4 页，共 128,469 个路径点。页面逻辑尺寸为 630 × 891，设备像素比为 1.5。每态轮换运行 5 次。每次用空白页预热绘制进程，然后将未缓存的混排页快照提交到画布，计时截止于实际绘制该页。首帧包含路径简化、SVG 组装、子进程传输和绘制。

| 中位数 | 原始路径 | 0.1 物理像素简化 |
| --- | ---: | ---: |
| 首帧 | 505.13 ms | 145.25 ms |
| SVG 准备阶段，含路径简化与写入 | 39.72 ms | 65.92 ms |
| 子进程栅格阶段 | 452.19 ms | 64.91 ms |

同一快照两态导出的写字机 SVG 逐字节一致。该混排页含参考位图，导出使用省略参考位图的正式路径。图像仍出现在两态的屏幕预览中。

## 复跑命令

从 InkStruct-Windows-Dev 根目录运行。

```powershell
$workspace = (Get-Location).Path
$checkout = "$workspace/artifacts/preview-path-acceleration/s"
$fixture = Join-Path (Split-Path -Parent $workspace) 'InkStruct-Layout-Dev/artifacts/a4-4k-sampling-20261115/input'
$python = "$workspace/.venv/Scripts/python.exe"
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
Set-Location $checkout
$env:PYTHONPATH = "$checkout/src;$checkout/artifacts/external/data_collection"
$env:QT_QPA_PLATFORM = 'offscreen'
$env:PYTHONUTF8 = '1'
$env:OPENBLAS_NUM_THREADS = '1'

& $python -B packaging/prepare_public_resources.py
& $python -B -m pytest -o addopts= -q -p no:cacheprovider tests/test_preview_acceleration.py tests/test_preview_process.py
& $python -B -m pytest -o addopts= -q -p no:cacheprovider

$env:QT_SCALE_FACTOR = '1.5'
& $python -B tests/benchmark_preview_acceleration.py "$workspace/artifacts/preview-path-acceleration/first-frame-$stamp.json" "$fixture/body.inkfont" "$fixture/source.md" --repeats 5
```

基准脚本把该次运行两态的 SVG 哈希与每轮首帧时间写入 JSON。回归也直接比较两态 SVG 文件的字节序列。
