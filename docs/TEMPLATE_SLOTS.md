# 可复用模板内容字段

本文是 **旧模板 v2 的兼容协议**。0.1.21 新模板 v3 使用单份 Markdown 的 `:::field` 字段块与稳定字段标识，见 [当前模板协议](TEMPLATE_SINGLE_FLOW.md)。旧 slot 和源码块绑定保留读取，不自动转换或改写正文。

2026-10-14。模板声明字段含义和布局规则，每份文档单独提供内容块映射。用户与 Agent 使用同一个模型，不包含学校名称或预设报告栏目。入口为“页面模板…”→“新建 / 设计模板…”→“内容字段…”。

## 字段声明

字段保存于 `inkstruct_page_template_v2` 的 `slots` 数组。每个字段包含：

| 属性 | 含义 |
| --- | --- |
| `slot_id` | 稳定字段编号，1–128 个字符；模板内唯一，Agent 用它选择字段 |
| `label` | 显示名称，1–256 个字符；修改名称不改变文档绑定 |
| `region` | 首页固定填写区名称；每个填写区最多声明一个字段 |
| `kind` | `any` 任意完整块；`text` 段落/标题；`math` 独立公式；`table` 表格 |
| `required` | 是否必填；必须为布尔值，默认 false |
| `pages` | `first` 仅首页或 `all` 每页重复，默认首页 |
| `scale` | 字号倍率，0.25–4，默认 1；表格继续保留独立尺寸 |
| `anchor` | 可选首字基线锚点 |

声明最多 1000 项。每页重复的字段要求续页存在同名填写区和锚点。字段只引用区域，不保存实际文字、节点 ID 或字形轨迹。`text` 约束块类型，段落中的行内公式仍按已有语法处理；HTML 表格与 Markdown 表格均归入表格类型。`any` 不绕过排版器对未支持语法、缺字、图像和溢出的限制。

用户先在模板画布创建填写区，再在“内容字段…”中新建声明。修改后“写入字段”；未写入时暂时禁止切换字段，点击确认会先检查并写入当前修改。取消对话框不改变外层模板。确认后的整个修改形成一次模板撤销事务。删除字段声明不删除已有文档内容或区域绑定；原绑定转回普通固定区绑定，需用户另行解除。

使用模板时，绑定窗口显示字段名称、类型和必填状态。字段声明决定页面策略、倍率和锚点，这些控件只读；应回到模板设计器修改。没有声明字段的其他填写区继续支持原有自由绑定。用户显式选择完整源码块，程序不根据字段名称猜测或复制内容。

## Agent 工作流

```sh
.venv/bin/inkstruct document template inspect-slots configs/templates/generic-record-v2.json
.venv/bin/inkstruct document template inspect-content input.inkdoc --template configs/templates/generic-record-v2.json
.venv/bin/inkstruct document template bind input.inkdoc --template configs/templates/generic-record-v2.json --bindings request.json --output bound.inkdoc
.venv/bin/inkstruct document template validate-document bound.inkdoc
```

`inspect-slots` 检查模板几何和声明，返回 `slots`，不声称内容已放得下。`inspect-content` 读取原生项目，返回稳定的内容块编号及 `slot_request` 草稿。将该对象单独保存为请求 JSON，填入实际编号：

```json
{
  "schema_version": "inkstruct_template_slot_request_v1",
  "project_sha256": "使用检查输出的完整项目哈希",
  "slots": [
    {"slot_id": "record-number", "node_ids": ["使用检查输出的节点编号"]}
  ],
  "bindings": []
}
```

`slots` 使用稳定字段编号，排版参数由模板声明提供；不能在请求中偷偷覆盖倍率、锚点或页策略。`bindings` 只供未声明字段的普通填写区使用，格式沿用原 `TemplateBinding`。两部分合计最多 1000 项，合成后同一区域和源块均不可重复绑定。请求是全部替换操作：所有需要保留的字段与普通绑定都必须列出；省略的绑定被解除，其源块回到正文。必填字段缺失仍会阻止保存。

输入项目发生变化、字段编号未知/重复、额外属性、使用普通绑定绕过已声明字段等情况都会拒绝请求。项目哈希锁定原生项目快照；调用时显式提供的外部模板是本次选用版本，需自己保留该文件以便复现。两份不同文档可以使用同一模板，分别检查后填写各自的节点 ID，无需复制模板或修改原始 Markdown。

编译后的绑定沿用项目内的 `inkstruct_template_binding_v1`，模板 v2 同时嵌入项目。每次加载和排版都会重新检查声明，因此 GUI、旧式绑定请求或 Python 创建的绑定不能绕过必填、类型与字段布局策略。以下诊断阻止成品导出：

- `template-slot-required`：必填字段未绑定。
- `template-slot-kind`：绑定了不符合声明类型的完整块。
- `template-slot-policy`：现有绑定的页面、倍率或锚点与声明不符，需要重新绑定。

源节点失效、重复使用、缺字、固定区溢出继续走已有诊断。CLI 不保存有错误的绑定结果；图形编辑器仍可保留待修复的项目草稿，诊断通过前不能导出成品。普通预览可导出也不代表可输出写字机 SVG，位图与纸面校准边界保持不变。

## 版本与迁移

旧 v1 模板保持原有字段与序列化结构，没有自动添加空 `slots`。显式升级：

```sh
.venv/bin/inkstruct document template upgrade old-v1.json --output new-v2.json
```

输出必须是新文件，原模板不变。升级保留几何、底图、纸张、偏移和校准状态，初始字段列表为空。用户在 GUI 首次添加字段也会显式升级，界面提示旧程序不能读取。v2 的几何约束仍与 v1 相同；当前不支持多栏、多正文流区、任意页型，也没有静默降级入口。未知版本和在 v1 中添加 `slots` 都被拒绝。

字段编号与显示名称已分离；几何对象的 `name` 仍是原有区域/锚点标识，不等于新的字段编号。“页面模板…”中的“联动重命名填写区 / 锚点…”和 Agent 的 `template rename` 命令会同步更新两种页型的对象、字段声明和当前项目绑定，详见 [联动重命名](PAGE_TEMPLATES.md#联动重命名填写区和锚点2026-10-14)。直接编辑属性或 JSON 名称仍须自行维护引用，不会猜测改名关系。移除声明后已有文档绑定不自动删除，重新套用不同模板也不自动匹配字段。

公共样例是 `configs/templates/generic-record-v2.json`。验证包括两份真实手写数字文档共用一份带三个任意字段的模板、v1/v2 轨迹一致、完整源身份与已有选样保留、必填/类型/策略失败、保存重开，以及字段脚注和每页重复。设备实写与跨平台原生交互验收仍未完成。

字段诊断现在包含结构化目标，编辑器提供“修正模板…”以直接进入对应绑定和页型。操作和报告字段见 [模板诊断定位](PAGE_TEMPLATES.md#从诊断定位填写区2026-10-14)。
