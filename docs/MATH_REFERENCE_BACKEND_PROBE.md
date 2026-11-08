# 外部数学后端离线试验

日期：2026-10-13。对应 M4-05。结论：**Mathtext 在本机可离线生成带可靠基线度量的独立参考 SVG，但不接入正式手写公式生成和写字机输出。** 本次仅评估一个已安装的候选，不宣称 MathJax、KaTeX 或其他后端已验收。

## 试验对象与固定条件

选择本机已有的 Matplotlib 3.11.2 Mathtext，避免为可选参考预览增加正式运行依赖。Mathtext 是独立的受限数学布局引擎，使用它无需外部 TeX 安装；本试验固定关闭 `text.usetex`。[官方说明](https://matplotlib.org/3.11.2/users/explain/text/mathtext.html)

脚本为 `scripts/experiments/mathtext_probe.py`，锁文件为 `configs/experiments/mathtext_probe.lock.json`。锁定 Python 3.13.8、Matplotlib 3.11.2、FreeType 2.14.3 和 NumPy 等依赖的实际版本，并校验随包分发的 40 个字体文件 SHA-256。使用固定版本默认 rc 配置，明确设为 DejaVu Sans 数学字族、默认数学样式 normal、不使用字体回退；伸缩字形还会用到包内的 STIX 尺寸字体，均在哈希清单内。

该锁文件描述实验环境，不修改项目主依赖或已有锁文件。版本或字体漂移时试验拒绝执行，需要有意识地重做验证；不会自动升级或下载。字体必须来自已锁定的包内目录，不能静默借用系统字体。

## 度量与输出

`MathTextParser("path")` 返回 VectorParse 的 width、height、depth、字形位置与规则矩形。72 dpi 下使用点作为几何单位；语义基线依据 height 与 depth 确定，字形的 y 是相对基线向上距离，再转换为 SVG 向下坐标。未通过最终图像包围盒居中推断基线。[API 文档](https://matplotlib.org/stable/api/mathtext_api.html)

输出逐字形字体文件名、字号、Unicode、glyph index、位置和规则线矩形；将本地字体轮廓嵌入 SVG，产物不依赖 SVG 外部字体、image、use 或 href。蓝线标出语义基线，每张图都有可见的“REFERENCE ONLY - NOT PLOTTER”字样。标题字样也转为轮廓；报告及 SVG 根节点明确标记 `reference-outline`、`plotter_ready=false`。

虽然轮廓也是 path，但包含闭合填充与曲线，不是采集的中心线笔画。试验既不折线化这些字体轮廓来冒充书写轨迹，也不把它们送入生产 PlotPlan。

## 结果

13 个固定用例中 10 个成功：单变量、上下标、分式/根式、根指数、求和、积分、伸缩括号、希腊符号、单位文字和 text。矩阵环境、显式 `limits` 和未知命令 3 个被拒绝。这个小样本清单不是完整 TeX 兼容性声明。

每个成功用例在同一进程中以新解析器重复构建，再用两个独立进程整体复现；所有 SVG 字节、度量及报告相同。渲染阶段拦截 socket、create_connection、getaddrinfo，记录的网络调用为 0。故意改写字体哈希后验证失败，且不会创建输出目录。该网络验证只针对试验渲染阶段，不等于任意环境的网络沙箱证明。

查看合成预览后发现语义差异：测试配置把 `epsilon` 与 `varepsilon` 都映射为 U+03B5，使用相同 glyph index；InkStruct 当前解析器分别保留 U+03F5 与 U+03B5。该差异已经与本机 InkStruct 解析结果逐项核对，未据此更改正式解析器。后端逐字形输出也不提供源码区间，求和等结构的绘制顺序不等于词法顺序，不能简单按列表次序绑定评价实例。

因此，宽高、基线与字体资源可解释，参考 SVG 可独立运行；但语义兼容、源码身份、采集笔迹能力未满足正式混排要求。当前保持独立实验，不作为缺字回退，不影响已经完成的 M4a–M4c 手写内核。未来若接入参考预览，需显式选择并保持不可写字机导出的状态。

## 复现与证据

```sh
MPLCONFIGDIR=/tmp/inkstruct-mathtext-cache .venv/bin/python \
  scripts/experiments/mathtext_probe.py \
  --output artifacts/mathtext-probe-new
```

目标目录必须不存在。最终本机证据位于 `artifacts/markdown_mixed_m4_20261013/mathtext-reference-final/`：10 张 SVG/PNG、`contact-sheet.png`、`verification.json`、`acceptance.json`；第二个进程的报告位于 `mathtext-repeat-final/`。较早的无 final 后缀目录是试验历史，不作为当前脚本哈希的证据。实际字形校准、英文/希腊新样本与写字机验收仍待完成。
