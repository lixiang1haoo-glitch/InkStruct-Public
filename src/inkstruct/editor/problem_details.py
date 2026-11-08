"""Chinese problem summaries grouped without losing authoritative source targets."""
import re
from bisect import bisect_left
from dataclasses import dataclass

ISSUE_LABELS = {
    "template-slot-required": "必填字段尚未绑定内容，请选择对应源码块。",
    "template-slot-kind": "内容类型不符合字段要求，请检查正文、公式或表格的选择。",
    "template-slot-policy": "内容绑定与字段的页面、字号或锚点设置不一致。",
    "template-binding-source-missing": "绑定的源码块已不存在，请重新绑定或解除绑定。",
    "template-binding-region-missing": "找不到绑定的填写区，请恢复区域或重新绑定。",
    "template-binding-anchor-missing": "找不到绑定的基线锚点，请检查模板设置。",
    "template-field-configuration-invalid": "填写区配置无法排版，请检查尺寸与内容设置。",
    "template-field-height-overflow": "内容超出填写区高度，请增大区域或调整排版。",
    "template-field-ink-overflow": "实际笔迹超出填写区，请调整区域或排版。",
    "template-field-image-overflow": "图片超出填写区，请调整图片或区域尺寸。",
    "template-footnote-definition-binding": "脚注定义不能单独绑定到填写区。",
}



@dataclass(frozen=True)
class IssueGroup:
    key: tuple
    title: str
    category: str
    suggestion: str
    severity: str
    diagnostics: tuple = ()
    related: tuple = ()


def describe(diagnostic, source):
    code = diagnostic.code
    if code == "asset-missing":
        text = source[diagnostic.span.start:diagnostic.span.end]
        subject = text if len(text) <= 8 else ""
        marker = "Missing glyph resource: "
        if marker in diagnostic.message:
            subject = diagnostic.message.split(marker,1)[1].strip("'\"")
        return (f"缺少字形「{subject}」" if subject else "缺少字形", "字体与字形",
                "选择包含这些字符的字体，或补充符号样本后重新排版。缺字处仍可定位；强制导出会留空。", subject)
    if code == "template-body-no-progress":
        return ("正文流在此停止", "模板与布局",
                "此对象放不进正文框，后续内容尚未排版。请减小对象尺寸、增大正文框，或调整模板后重新排版。", "")
    if code.startswith("math-"):
        titles = {"math-command-unsupported":"公式命令暂不支持", "math-argument":"公式缺少参数",
                  "math-group":"公式花括号不成对", "math-script":"公式上下标需要检查",
                  "math-delimiter":"公式括号需要配对", "math-symbol":"公式符号暂不支持",
                  "math-environment":"公式环境需要检查", "math-budget":"公式过于复杂",
                  "math-depth":"公式嵌套过深"}
        title = titles.get(code,"公式语法或字形需要检查")
        command = re.search(r"\\[A-Za-z]+",diagnostic.message)
        if command:title += "「"+command.group()+"」"
        advice = ("将此命令替换为 Markdown/LaTeX 手册支持的写法，然后重新排版。"
                  if code=="math-command-unsupported" else "定位到公式，检查命令、配对括号及必需参数；可复制问题报告连同 Markdown 交给 AI 修正。")
        return title,"公式",advice,diagnostic.message
    if code.startswith("template-"):
        message = ISSUE_LABELS.get(code,"模板区域、字段绑定或正文框需要调整。")
        target = getattr(diagnostic,"target",None)
        field = getattr(target,"slot_id",None) or getattr(target,"region",None)
        title = f"填写区「{field}」需要调整" if field else "模板内容需要调整"
        return title,"模板与布局",message,""
    if "overflow" in code or code.endswith("too-wide"):
        category = "表格" if code.startswith("table-") else "图片" if code.startswith("image-") else "排版与边界"
        return ("内容超出可用区域", category,
                "定位到内容后调整字号、表格或图片尺寸；需要更大空间时修改纸张或模板，再重新排版。", "")
    if code.startswith("image-"):
        return ("图片资源或导出范围需要检查", "图片",
                "检查图片路径、资源与尺寸。参考位图不会转成写字机笔迹，导出时会说明跳过范围。", "")
    if code.startswith("point-"):
        return ("点状字形需要适配", "字体与字形", "在字体资源中完成点状笔迹适配，再尝试常规 SVG 导出。", "")
    if "break" in code:
        return ("换行、分页或换框命令需要检查", "Markdown",
                "检查命令所在位置；分页作用于物理页面，换框仅用于连续正文流。", "")
    if code == "preview-failed":
        return ("预览未能完成", "预览", "查看技术详情以确认原因；修正内容或设置后重新排版。原文档仍保留。", "")
    return ("内容需要检查", "其他提示", "定位到相关内容，按技术详情调整后重新排版；可复制报告交给 AI 辅助检查。", "")


def group_issues(diagnostics, source):
    groups = {}
    by_target = {}
    for diagnostic in diagnostics:
        if diagnostic.code.startswith("math-"):
            by_target.setdefault(getattr(diagnostic,"target",None),[]).append(diagnostic)
    math_locations = {}
    for target,items in by_target.items():
        ordered = sorted(items,key=lambda d:d.span.start)
        math_locations[target] = ordered,[d.span.start for d in ordered]
    attached = {}
    related = {}
    for diagnostic in diagnostics:
        if diagnostic.code != "unsupported-inline":
            continue
        math_errors,starts = math_locations.get(getattr(diagnostic,"target",None),((),()))
        index = bisect_left(starts,diagnostic.span.start)
        if index<len(math_errors):
            cause=math_errors[index]
            if cause.span.end<=diagnostic.span.end:
                attached[id(diagnostic)]=cause
                related.setdefault(id(cause),[]).append(diagnostic)
    for diagnostic in diagnostics:
        if id(diagnostic) in attached:
            continue
        title,category,suggestion,subject = describe(diagnostic,source)
        target = getattr(diagnostic,"target",None)
        key = (diagnostic.severity,diagnostic.code,subject,
               getattr(target,"region",None),getattr(target,"slot_id",None))
        groups.setdefault(key,[]).append(diagnostic)
    result = []
    for key,items in groups.items():
        title,category,suggestion,_ = describe(items[0],source)
        result.append(IssueGroup(key,title,category,suggestion,items[0].severity,tuple(items),
                                 tuple(d for item in items for d in related.get(id(item),()))))
    priorities = {"template-body-no-progress":0,"asset-missing":1}
    return tuple(sorted(result,key=lambda group:({"error":0,"warning":1}.get(group.severity,2),
                                                 priorities.get(group.key[1],2))))
