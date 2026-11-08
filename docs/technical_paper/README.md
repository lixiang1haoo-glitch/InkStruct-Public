# InkStruct 技术实现论文

基于 2026-10-10 当前工作区整理的中文技术实现论文，覆盖默认生成、神经模型、高保真源轨迹、结构修复、研究实验、页面排版与文本审校。包含未提交的文档/编辑器实现。

- [LaTeX 源码](inkstruct_technical_paper.tex)：单文件，可直接编辑。
- [编译后的 PDF](../../output/pdf/inkstruct_technical_paper.pdf)：39 页。
- [源码快照](source_snapshot.json)：Git 基线、已有修改、190 个相关文件的 SHA-256。
- [验证记录](verification.json)：编译、版面检查和本次测试结果。

正文约 1.9 万汉字，22 个正文章节、3 个附录，包含公式、架构图、参数表、实验结果和源码责任索引。历史实验数值引用仓库记录，本次没有重新训练或重跑私有数据实验。项目源码、原档案和个人采样未修改。

## 编译

需要支持中文的 XeLaTeX 环境，使用 TeX 自带 Fandol 字体；无外部图片、私人采样或独立 BibTeX 文件依赖。

在本目录执行：

```bash
xelatex -interaction=nonstopmode -halt-on-error inkstruct_technical_paper.tex
xelatex -interaction=nonstopmode -halt-on-error inkstruct_technical_paper.tex
```

也可使用 `latexmk -xelatex inkstruct_technical_paper.tex`。目录及交叉引用需要多轮编译。

## 核验口径

本次运行 `.venv/bin/python -m pytest`：**200 passed，4 skipped**，耗时 4.80 秒。跳过项不计作通过；当前环境未安装可选 PyTorch。

论文明确区分源码事实、本次检查、历史实验与分析推论。笔画数和标准身份正确、无新增严格交叉、源轨迹保真、几何拟合改善与人类自然性评价属于不同验收目标。

如更新实现，应重核相关公式、参数、默认分支和状态，再更新源码快照。仅保留 Git HEAD 不能重现这次包含未提交文件的工作区。
