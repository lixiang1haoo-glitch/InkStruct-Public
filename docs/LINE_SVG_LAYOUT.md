# 单线 SVG 导入

M5-03，2026-10-13。独占一段的 Markdown 图片可以显式载入受控单线 SVG，与手写图题整体分页，并进入公共写字机导出及路径优化。普通 PNG/JPEG 仍只作参考页面。没有描图、字体轮廓转手写或通用浏览器 SVG 渲染。

## 使用

```markdown
![图一 测量示意](assets/markdown_line_drawing.svg)
```

编辑器“图片设置…”选择源码图片，再导入本地 `.svg`。宽度、最大高度及对齐沿用图片设置；“SVG 曲线容差”按最终纸面毫米计算，默认 0.05 mm，范围 0.001–1 mm。调整图宽后重新编译，误差上限不会随图宽同比放大。图题仍使用正文真实字形。

CLI 从 Markdown 所在目录导入相对 SVG，`--image-root` 可明确指定根目录；不会读取根目录以外的链接或联网。项目保存原 SVG 字节、哈希、物理尺寸及排版容差，离开原目录仍能重开。机器清单的 `source_stroke_id` 包含 SVG 原文件哈希、容差和子路径序号。

```sh
.venv/bin/inkstruct document render \
  artifacts/markdown_mixed_m5_20261013/line-svg/line-report.inkdoc \
  --plotter --optimize-paths --output artifacts/line-report-new-machine
```

这个本机样例项目已嵌入字形与 SVG。输出目录必须尚不存在。优化继续自动允许反转；只改变执行顺序/方向，不改原 SVG 或其离散点。图片选中时回选完整源码，单线图不参与字形评价。

## 受控范围

| 项目 | 当前行为 |
| --- | --- |
| 元素 | 根 `svg`、嵌套 `g`、`path`、`line`、`polyline`、`polygon`、无圆角 `rect`、`circle`、`ellipse`；简单 `title/desc` 仅作元数据 |
| 路径 | M/L/H/V/C/S/Q/T/A/Z 及小写相对形式，重复参数、独立子路径和闭合线 |
| 仿射变换 | matrix、translate、scale、rotate（可指定中心）、skewX、skewY；按分组及变换列表顺序展平 |
| 页面单位 | 根 width/height 必填，支持 mm/cm/in/pt/pc/px 和无单位 px；不接受百分数 |
| viewBox | 支持非零原点，保持默认 xMidYMid meet，或显式 none；其余对齐和 slice 暂不支持 |
| 线条声明 | 实际几何需有效 fill=none 和明确黑色 stroke，可从父级及受控 style 继承 |
| 笔宽 | 使用文档笔宽；源 stroke-width 必须为正，但不驱动多笔或变宽，原端帽/连接显示样式也不复刻；预览诊断明确提示 |
| 明确拒绝 | 填充图形、text、字体轮廓填充、image、use、defs、嵌套 svg、外链、CSS 类、脚本、事件、动画、滤镜、裁剪、透明度、虚线、marker、vector-effect、未知属性及元素 |

这是编译器接受的单线子集，不声称兼容任意 SVG。不会根据外形猜测一个描边轮廓是否代表手写笔画；输入须由作者确认为所需的中心线。弧标志须分隔为独立 0/1 参数，半径须非负。零半径按直线处理，过小半径按端点规则放大；孤立点、空图、退化路径和视口外内容拒绝，不静默裁切或删除。

资源限 UTF-8、1 MB、5000 个元素、32 层分组、50000 个离散点；坐标、变换和递归深度也有有限预算。超限给出诊断，不能生成部分机器文件。SVG 视口内要留出笔宽与容差余量，避免笔迹伸入图题或相邻块。

## 几何与验证依据

单位按 CSS 绝对长度比例换算，像素采用 96 px/in；根 viewBox 与祖先变换在曲线离散前合成为最终毫米映射。实现参考 [W3C 坐标和变换](https://www.w3.org/TR/SVG11/coords.html)、[CSS 绝对单位](https://www.w3.org/TR/css-values-4/#absolute-lengths)。

二次/三次 Bézier 使用 de Casteljau 细分，当控制点到端点线段的最大距离不超过容差时输出线段。弧先按 [W3C 椭圆弧端点转换](https://www.w3.org/TR/SVG11/implnote.html#ArcImplementationNotes) 计算中心参数，再用最终仿射映射后二阶导数范数上界选择分段数。普通路径命令语义参考 [W3C Paths](https://www.w3.org/TR/SVG11/paths.html)。上述限制和失败策略是 InkStruct 子集的选择，不是浏览器完整兼容承诺。

测试对变换后的 Bézier 和椭圆独立取 2001 个解析采样点，检查到折线的距离不超过指定容差；另验证反射控制点、弧方向、旋转弧、半径修正、单位、留白及变换顺序。这是有限测试证据，浮点运算有数值误差；机器 SVG 还会把毫米坐标保留六位小数，单点舍入位移最多约 0.00000071 mm。

## 实样证据

`examples/assets/markdown_line_drawing.svg` 是自绘几何验收图，含曲线、刻度、圆、椭圆和示意电路，不表示实验测量结果。`examples/markdown_line_svg_m5.md` 与本机 `artifacts/markdown_mixed_m5_20261013/line-svg/line-report.inkdoc` 含真实手写图题、四个固定字段、表格、公式和代码，共两页、481 个实例。

图形显式设为 **70 × 35 mm、容差 0.025 mm**，得到 **21 条子路径、217 个点**。整份机器文件 **1253 条路径**，严格只有 path 元素和绝对 M/L 指令。两页空行程估算分别 **9176.333 → 2249.339 mm**、**5466.358 → 1487.922 mm**；仅是几何距离，尚未做写字机时间或纸面质量验收。

同目录 `preview/`、`machine/`、`editor.png`、`settings.png`、`verification.json` 保存实际产物。上级 `verify_line_svg.py` 验证原 SVG 哈希、逐点放置、源码覆盖、项目重开、路径排序/反转保真和 CLI 冻结输出。目视检查第二页与实际 Qt 离屏界面，未观察到当前图、图题和表格碰撞或裁切；首页机器输出与已有四字段模板首页逐字节相同。

本轮全量 **685 passed、4 skipped，20.99 秒**，相关 Ruff 通过；此前 15 页冻结机器 SVG 逐字节一致，上一轮位图项目的预览和禁止机器导出门槛保持不变。物理纸面校准、Windows 新符号样本及 M6 跨平台验收仍未完成。
