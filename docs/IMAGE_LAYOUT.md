# 图片块与图题

独占一段的 Markdown 图片可以与正文、表格、公式、代码共同分页，保存到可移植项目。普通 PNG/JPEG 属于参考页面内容；0.1.25 起可确认跳过这些图片，导出其他内容的写字机 SVG。

## 源码与设置

```markdown
![图一 测量示意](assets/chart.png)
```

当前受控语法把方括号中的替代文字作为图题，使用普通正文的手写字形、行内强调和受控公式排版。可选的 Markdown title 属性保留为元数据，不另作图题。图题不自动编号；空替代文字表示无图题。图片和图题作为整体分页，放不下时移到下一页；超过完整正文区域则定位报错，不裁切、自动缩小或丢弃。

0.1.24 起，齿轮中的图片默认设置为高度 60 mm、宽度按原图长宽比计算、图题间距 2 mm、居中；不再提供默认宽度输入。该默认用于沿用默认的图片及后续新增图片，不覆盖已有独立设置。选择具体图片后可显式导入 PNG/JPEG 或受控单线 SVG，并选择“按高度”或“按宽度”等比设置。按宽度时保留最大高度限制；按高度时使用指定高度。宽高均不因页面不足而自动缩小，超出区域继续报错。

新尺寸规则保存为 `inkstruct_image_style_v2` 的 `height_mm`。旧 v1 图片样式继续按保存的宽度和最大高度排版，不自动重写旧文档；查看或取消保持原值。旧文档默认尺寸可以明确点击“将本文旧版图片默认改为按高度 60 mm”。应用的旧全局图片默认在内存中采用 60 mm 新规则，原设置记录在明确保存之前保持不变；已经保存的新高度值会按原值保留。单张设置跟随源节点身份保存；替换整个节点可能需要重新设置。默认、独立设置和资源随项目保存，取消不改变项目。

点选预览中的图片回选整段图片源码，图片本身不参与字形质量评价；图题字符可以正常评价。缺失资源、过宽、过高以及暂不支持的嵌入位置都有诊断。

## 导入与保存

支持单帧 PNG/JPEG，原文件不超过 8,000,000 字节、像素数不超过 2,000,000。JPEG 按 EXIF 方向生成预览，原文件字节不改变。项目保存原图、规范化 PNG、各自 SHA-256、像素尺寸与源码来源；加载时核验哈希、尺寸及规范化像素一致性。原文件移走后，已保存项目仍可独立打开。

CLI 从新 Markdown 的目录导入相对图片路径，也可用 `--image-root` 明确指定根目录。路径不能逃出该根目录，不自动下载网络资源。编辑器使用“图片设置…”显式选择本地文件并绑定到源码图片；渲染器只读取已嵌入资源。每个文档最多 64 份图片资源，并有累计资源大小限制。

```sh
.venv/bin/inkstruct document render examples/markdown_images_m5.md \
  --mode markdown --run outputs/full_library_20261010/user_001/all_supported_v4_adaptive_20261010 \
  --symbols artifacts/markdown_mixed_m0_20261013/private_tables/user_001含小数点.zip \
  --output artifacts/image-reference-new --save-project artifacts/image-reference-new.inkdoc
```

以上示例需要本机已有字形及符号资源。重开 `.inkdoc` 使用项目内资源，不接受外部 `--image-root` 覆盖。

## 页面与机器导出

“导出页面…”和普通 CLI render 可以生成参考 SVG/PNG；含图页面顶部有 `RASTER REFERENCE PAGE - NOT PLOTTER READY` 标识，清单标为 `reference-pages`，`plotter_exportable` 为 false。此 SVG 包含嵌入图片，不能作为机器文件。

0.1.26 起，“导出 SVG…”可在仅含已载入位图、或可识别的缺失本地 PNG/JPEG 引用时使用。统一提示“导出的 SVG 不包含非 SVG 图片，包括尚未载入的图片；保留当前预览中的图片占位与图题，导出其余可书写内容。”分别显示两类数量，展开详情可查看解码后的文件名、原始引用及页码。取消不产生输出；确认后保留当前占位、图题、页序和其余路径，不重排、不补齐图片、不自动描图。

预览与模板适配报告中的 `image-resource-missing` 继续为错误，完整文档的 `exportable` 和 `plotter_exportable` 不会因此变为 true。单独的 `can_export_with_image_omission` 判断受限出口：实际页面存在对应占位，来源能明确识别为支持的本地 PNG/JPEG，且错误码及源码范围均对应，才允许确认跳过。资源不存在时使用已有占位，不伪造图片或尺寸信息；纯图片页保留为空白机器页。

`plotter.json` 的 `export_scope.omitted_images` 记录页索引（从 0 开始）、`page_number`（从 1 开始）、源码范围、稳定节点与出现身份、原始引用、解码显示名称、占位坐标及原因：`loaded-raster` 或 `resource-not-loaded`。缺失资源的 `original_sha256` 为 null；已载入资源保留真实哈希。不写入图片数据。图形版参考 SVG/PNG 仍显示已有图片；缺失资源须使用带诊断的调试参考出口。

CLI `--plotter` 默认保持完整导出检查；明确附加 `--omit-reference-images` 才会执行同样的跳过并输出清单。底层 `plan_from_snapshot(..., omit_reference_images=True)` 需要显式选择。源码新导入时，真实文件不存在的 PNG/JPEG 同时记录 `image-import-missing`；非法路径、解码失败或资源格式损坏仍为 `image-import-failed`，不能跳过。缺失 SVG、未知类型、非法资源、缺字、公式错误、越框及不可支持路径继续阻止导出。模板预印底图仍只作纸面参考。

进入图片确认前固定当前预览；确认期间文档变化会取消这次导出。进入输出位置选择框前，已确认的排版和图片清单一起冻结；选位置期间继续编辑不会改变这次已确认的输出。源码、原文件、资源、冻结选样及当前预览不被导出改写。

尚不支持行内嵌图、表格单元格中的图片、浮动环绕、动画、多页图像或任意 SVG 导入。受控 [单线 SVG](LINE_SVG_LAYOUT.md) 已由 M5-03 独立实现，可从同一设置窗口导入并生成机器路径；本页的参考页面限制针对普通位图。

## 验收样张

`examples/assets/markdown_reference_chart.png` 是项目自绘的示意数据图，不是实验测量结果。本机 `artifacts/markdown_mixed_m5_20261013/images/reference-report.inkdoc` 含四个固定字段、跨页表格、公式、代码和图片，共两页、481 个实例。图片为 720 × 360 px，在样张中显式设为 70 × 35 mm，图题使用真实手写资源。

同目录 `preview/`、`editor.png`、`settings.png` 和 `verification.json` 保存参考输出、界面和验证证据；上级 `verify_images.py` 可复核像素、源码覆盖、可移植重开和机器导出门槛。已查看两页和界面，没有观察到本样张的图题、表格或正文裁切重叠。此证据不替代实机书写或物理模板校准。
