---
description: 在 Windows 版 InkStruct 0.1.74 中导入一页纸样 PDF，设置 A4 正文框，并另存为可复用的模板 JSON。
---

<script setup>
import { withBase } from 'vitepress'
</script>

# 从 PDF 制作 A4 笔记模板

用 Windows 版 InkStruct **0.1.74**，把一张带有标题和分隔线的 A4 纸样做成 `physics-a4-template.json`。应用模板后，每一页笔记都使用这张纸样，正文从分隔线下方开始排。

点任意截图可查看原图。

## 1. 下载纸样并新建模板

<p><a :href="withBase('/downloads/physics-a4-source.pdf')" download="墨构牌物理笔记专用纸-A4.pdf"><strong>下载原始纸样《墨构牌物理笔记专用纸-A4.pdf》</strong></a></p>

在浏览器的下载记录里找到这份 PDF，点 **在文件夹中显示**。记下它所在的文件夹，导入时会用到。

1. 打开 InkStruct。在窗口左下角点 **模板库**，再点右上角的 **新建模板…**。需要安装软件时，先从 [Windows 版 0.1.74 发布页](https://github.com/lixiang1haoo-glitch/InkStruct-Public/releases/tag/app-v0.1.74)下载安装包。
2. 在弹窗的下拉框中选 **自定义模板**，点 **OK**。打开「模板工作台」后，左侧的 **循环页组 · 顺序循环** 下应有一条 **初始空白版式**。循环页组里的版式会在文档分页时依次重复。

[![新建模板弹窗，已选中自定义模板](/screenshots/physics-a4-template/01-custom-template.jpg)](/screenshots/physics-a4-template/01-custom-template.jpg)

## 2. 导入 PDF 的第 1 页

1. 点工作台左下角的 **添加页面版式… › 导入 PDF 页面…**。在文件选择窗口中打开刚才的下载文件夹，选中纸样 PDF，点 **打开**。
2. 在 **导入 PDF 页面版式** 窗口中，将 **页码与顺序** 填为 **1**，取消勾选 **采用首个所选 PDF 页的物理纸张尺寸**。纸样的 PDF 页面尺寸和标准 A4 略有差异，这一步保留模板的 **210 × 297 mm**。
3. **目标页组** 选 **循环页组**，**导入方式** 选 **替换整个页组**。这里替换的是第 1 步新建的空白版式。
4. 点 **读取所选页面**。看到 **页面已读取**，并确认纸张尺寸在箭头两边都是 **210 × 297 mm**，再点 **OK**。

[![在添加页面版式菜单中选择导入 PDF 页面](/screenshots/physics-a4-template/02-import-pdf-menu.jpg)](/screenshots/physics-a4-template/02-import-pdf-menu.jpg)

[![PDF 导入窗口，读取第 1 页，替换循环页组并保留 210 × 297 mm](/screenshots/physics-a4-template/03-pdf-options.jpg)](/screenshots/physics-a4-template/03-pdf-options.jpg)

## 3. 设置纸张和正文框

导入完成后，左侧循环页组只剩 **PDF 第 1 页**，中间预览能看到纸张标题和横向分隔线。右侧的 **纸张与页面版式** 应显示宽度 **210 mm**、高度 **297 mm**，**用纸方式** 为 **预印纸**。预印纸的底图供排版预览使用，写字机 SVG 会输出要写的路径。

1. 把工作台上方的 **模板名称** 改为 **墨构牌物理笔记专用纸**。在右侧 **当前页面版式** 的输入框中，把 **PDF 第 1 页** 改为 **物理笔记 A4**。
2. 在右侧列表点 **1. 正文 · 正文框 1**，打开 **内容框** 属性。正文框是软件可以排字的区域。导入时已建好一个框，接下来调整它的位置。
3. 按表中顺序填写数值，每填完一项按 **Tab** 确认。先改高度，移动正文框时下边就能留在纸内。将 **框名称** 改为 **正文**，**正文顺序** 保持 **1**，**排版方式** 保持 **按内容排版（默认）**。

| 内容框属性 | 填写值 |
| --- | --- |
| 高度 | 237 mm |
| 上边位置 | 43 mm |
| 左边位置 | 19 mm |
| 宽度 | 172 mm |

填完后，蓝框上边应在分隔线下方，左右各留 **19 mm**，下方留 **17 mm**。左侧循环页组只需保留 **物理笔记 A4** 这一个版式。

[![保存后重新打开的模板，纸张为 210 × 297 mm，循环页组只有物理笔记 A4](/screenshots/physics-a4-template/04-a4-paper.jpg)](/screenshots/physics-a4-template/04-a4-paper.jpg)

[![选中正文框后的属性，上边位置 43 mm、左边位置 19 mm、宽 172 mm、高 237 mm](/screenshots/physics-a4-template/05-body-frame.jpg)](/screenshots/physics-a4-template/05-body-frame.jpg)

## 4. 保存 JSON 并在模板库核对

1. 点工作台右下角的 **另存为新模板…**。在保存窗口选一个能找到的文件夹，在 **文件名** 中输入 `physics-a4-template.json`，点 **保存**。
2. 回到 **模板库**，点 **墨构牌物理笔记专用纸**。右侧摘要应显示 **210 × 297 mm** 和 **0 起始 / 1 循环页**，预览中应有纸样标题及分隔线下的蓝框。打开刚选的文件夹，应能看到 `physics-a4-template.json`。

<p><a :href="withBase('/downloads/physics-a4-template.json')" download>下载实操保存的模板 JSON 作对照</a></p>

继续做 [笔记篇 · 排一份 A4 物理复习笔记](./student-notes) 时，可以在模板库直接选这份模板，并点 **用于当前文档…**。换到另一台电脑时，把 JSON 文件复制过去，在那台电脑的 **模板库 › 导入模板…** 中选它即可。

## 换用自己的 PDF

先量实物的纸宽和纸高。新建自定义模板后，在工作台右侧的 **纸张宽度** 和 **纸张高度** 填入实测值，再导入 PDF。从纸张左上角量出正文区的左边和上边位置，以及正文区的宽、高，单位都用毫米。有预印标题或横线时，把它们留在正文框外。套用模板后先试排一页，检查预览里的笔迹是否落在纸面可写的区域。

如果纸上有课题名称、教学目标等固定栏位，可以继续做[双页教案模板练习](./lesson-plan-template)，了解字段框如何与正文框配合。
