"""Markdown body flow in physical millimetres, independent of editor and export."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace

from ..assets.resolver import AssetResolver
from ..document.break_commands import FLOW_BREAK_KINDS
from ..document.limits import (
    BudgetedOps,
    PointAccumulator,
    allocating_page,
    bounded_layout,
    validate_snapshot,
)
from ..document.line_svg import LineSvgResource
from ..document.markdown import MarkdownDocument, SemanticNode
from ..document.schema import Diagnostic, Occurrence, PageProfile, SourceSpan, StyleProfile, digest
from ..document.styles import FlowStyle
from ..document.tables import table_model
from ..scene.schema import Fragment, LayoutSnapshot, Page, PaintOp, RasterOp
from .code import measure_code
from .continuation import (
    Checkpoint,
    prepare,
    publish,
    suffix_boundary,
    suffix_checkpoints,
)
from .glyph_corrections import corrected_layout
from .images import measure_image
from .inline import (
    InlineBox,
    InlineRun,
    box_occurrences,
    break_lines,
    check_cancel,
    inline_runs,
    measure_runs,
)
from .justification import justify_line
from .note_units import AtomicBand
from .plain import CLOSING, OPENING
from .table_pages import (
    first_group_height,
    paginate_table,
    paginate_table_with_notes,
    paint_table,
    table_boxes,
)
from .tables import measure_table

LAYOUT_VERSION = "markdown-mixed-mm-v4/code-grid-v1/marker-identity-v2/page-frame-breaks-v2/justify-natural-v2"


@dataclass(frozen=True)
class BodyBlock:
    node: SemanticNode
    runs: tuple[InlineRun, ...]
    indent: float = 0
    quote_depth: int = 0
    marker: str = ""
    scale: float = 1
    keep_next: bool = False
    rule: bool = False
    unsupported: bool = False
    first_indent: float = 0
    task: SemanticNode | None = None
    note_label: SemanticNode | None = None


def marker_occurrence(block, index, character, resolver):
    """Preserve legacy marker choices while giving changed digits a new instance.

    List numbers are synthesized, so changing a list start/inserting an item can
    change their text without changing the paragraph's source identity. Existing
    selections for unchanged marker digits remain authoritative, including errors.
    """
    identity = f"{block.node.node_id}:marker:{index}"
    previous = resolver.selections.get(identity)
    if previous is not None and previous.character != character:
        identity += f":value:{ord(character):x}"
    return Occurrence(identity, block.node.node_id, block.node.span, character)


def body_blocks(document: MarkdownDocument, flow=None, *, frame_breaks=False):
    flow = flow or FlowStyle()
    result = []

    def append_text(block):
        runs = tuple(r for r in block.runs if frame_breaks or r.kind != "framebreak")
        block = replace(block, runs=runs)
        controls = any(run.kind in FLOW_BREAK_KINDS for run in block.runs)
        if not controls:
            result.append(block)
            return
        part, first = [], True

        def flush():
            nonlocal first
            if not part:
                return
            span = SourceSpan(part[0].occurrence.span.start, part[-1].occurrence.span.end)
            identity = digest([block.node.node_id, "frame-segment", part[0].occurrence.occurrence_id])
            result.append(replace(
                block, node=replace(block.node, node_id=identity, span=span), runs=tuple(part),
                marker=block.marker if first else "", task=block.task if first else None,
                note_label=block.note_label if first else None,
                first_indent=block.first_indent if first else 0,
            ))
            part.clear()
            first = False

        for run in block.runs:
            if run.kind not in FLOW_BREAK_KINDS:
                part.append(run)
                continue
            flush()
            o = run.occurrence
            result.append(BodyBlock(SemanticNode(o.node_id, run.kind, o.span), ()))
        flush()

    def visit(node, indent=0, quote=0, marker=""):
        if node.kind == "footnote_entry":
            first = len(result)
            for child in node.children:
                visit(child, indent + flow.list_indent_mm, quote)
            if (
                len(result) > first
                and node.children[0].kind == "paragraph"
                and result[first].node.kind == "paragraph"
            ):
                result[first] = replace(
                    result[first], marker=dict(node.attributes)["number"], note_label=node
                )
        elif node.kind in {"paragraph", "heading", "callout_title"}:
            children = node.children[0].children if len(node.children) == 1 else ()
            if (
                node.kind == "paragraph"
                and not marker
                and len(children) == 1
                and children[0].kind == "image"
            ):
                image = children[0]
                result.append(
                    BodyBlock(
                        image,
                        tuple(r for child in image.children for r in inline_runs(child)),
                        indent,
                        quote,
                    )
                )
                return
            task = (
                children[0] if marker and children and children[0].kind == "task_checkbox" else None
            )
            if task:
                runs = tuple(r for child in children[1:] for r in inline_runs(child))
                if marker == "bullet":
                    marker = "task"
            else:
                runs = tuple(r for child in node.children for r in inline_runs(child))
            attrs = dict(node.attributes)
            level = int(attrs.get("tag", "h1")[1:]) if node.kind == "heading" else 1
            scale = flow.heading_scales[level - 1]
            append_text(
                BodyBlock(
                    node,
                    runs,
                    indent,
                    quote,
                    marker,
                    scale if node.kind == "heading" else 1,
                    node.kind in {"heading", "callout_title"},
                    task=task,
                    first_indent=(
                        flow.first_line_indent_mm
                        if node.kind == "paragraph" and indent == 0 and not marker
                        else 0
                    ),
                )
            )
        elif node.kind in {"blockquote", "callout"}:
            for child in node.children:
                visit(child, indent + flow.quote_indent_mm, quote + 1)
        elif node.kind in {"bullet_list", "ordered_list"}:
            start = int(dict(node.attributes).get("start", "1"))
            for index, item in enumerate(node.children):
                label = "bullet" if node.kind == "bullet_list" else f"{start + index}."
                first = 0
                while first < len(item.children) and item.children[first].kind in {
                    "pagebreak", "framebreak", "break_command_error",
                }:
                    visit(item.children[first], indent + flow.list_indent_mm, quote)
                    first += 1
                children = item.children[first:]
                if (not item.children or (children and children[0].kind not in {
                    "paragraph", "heading", "math_block",
                })):
                    result.append(BodyBlock(item, (), indent + flow.list_indent_mm, quote, label))
                for n, child in enumerate(children):
                    visit(child, indent + flow.list_indent_mm, quote, label if n == 0 else "")
        elif node.kind == "break_command_error":
            return
        elif node.kind in FLOW_BREAK_KINDS:
            attrs = dict(node.attributes)
            if (node.kind == "pagebreak" or frame_breaks) and attrs.get("blocked") != "true" and attrs.get("strength", "4") == "4":
                result.append(BodyBlock(node, ()))
        elif node.kind == "math_block":
            result.append(BodyBlock(node, tuple(inline_runs(node)), indent, quote, marker))
        elif node.kind in {"fence", "code_block"}:
            result.append(
                BodyBlock(
                    node,
                    tuple(
                        InlineRun(o, "hardbreak" if o.text == "\n" else "code_block")
                        for o in node.occurrences
                    ),
                    indent,
                    quote,
                    marker,
                )
            )
        elif node.kind == "hr":
            result.append(BodyBlock(node, (), indent, quote, marker, rule=True))
        elif node.kind == "table":
            result.append(BodyBlock(node, (), indent, quote, marker))
        else:
            o = Occurrence(
                node.node_id + ":unsupported",
                node.node_id,
                node.span,
                node.raw_content[:24] or node.kind,
            )
            result.append(
                BodyBlock(
                    node, (InlineRun(o, "unsupported"),), indent, quote, marker, unsupported=True
                )
            )

    for node in document.nodes:
        visit(node)
    return result


@bounded_layout
@corrected_layout
def layout_markdown(
    document: MarkdownDocument,
    resolver: AssetResolver,
    *,
    page: PageProfile | None = None,
    style: StyleProfile | None = None,
    flow: FlowStyle | None = None,
    cancelled=None,
    _footnotes=None,
    _atomic_bands=None,
    _fixed_references=(),
    _references_only=False,
    _regions=None,
) -> LayoutSnapshot:
    check_cancel(cancelled)
    page, style = page or PageProfile(), style or StyleProfile()
    flow = flow or FlowStyle()
    if flow.named_fields and _regions is None:
        from .flow_templates import layout_flow_template
        return layout_flow_template(document,resolver,page=page,style=style,flow=flow,cancelled=cancelled)
    if flow.template_bindings or getattr(flow.template, "slots", ()):
        from .template_fields import layout_template_fields

        return layout_template_fields(
            document, resolver, page=page, style=style, flow=flow, cancelled=cancelled
        )
    if (
        _footnotes is None
        and not _references_only
        and (
            _fixed_references
            or any(
                n.kind in {"footnote_reference", "footnote_definition"}
                for root in document.nodes
                for n in root.walk()
            )
        )
    ):
        from .footnotes import layout_footnotes

        return layout_footnotes(
            document,
            resolver,
            page=page,
            style=style,
            flow=flow,
            cancelled=cancelled,
            fixed_references=_fixed_references,
            regions=_regions,
        )
    diagnostics = [d for d in document.diagnostics if d.code != "layout-pending"]
    if _footnotes is False:
        for root in document.nodes:
            for node in root.walk():
                if node.kind in {"footnote_reference", "footnote_definition"}:
                    diagnostics.append(
                        Diagnostic(
                            "footnote-layout-pending",
                            "This footnote combination has not passed coordinated pagination",
                            node.span,
                        )
                    )
    if _regions is None:
        for root in document.nodes:
            for node in root.walk():
                if node.kind == "framebreak" and dict(node.attributes).get("blocked") != "true":
                    diagnostics.append(Diagnostic(
                        "frame-break-inactive",
                        "Frame breaks only advance the template body text-frame flow",
                        node.span, "warning",
                    ))
    blocks = body_blocks(document, flow, frame_breaks=_regions is not None)
    template = flow.template
    if template:
        page = template.page
    margin, radius = page.margin_mm, style.stroke_width_mm / 2

    def page_bounds(index):
        return (
            _regions.bounds(index) if _regions else template.bounds(index)
            if template or _regions
            else (margin, margin, page.width_mm - margin, page.height_mm - margin)
        )

    region_left, region_top, region_right, region_bottom = page_bounds(0)
    grid = _regions.grid if _regions else None
    content_width = region_right - region_left
    continuation_bounds = page_bounds(1)
    content_height = continuation_bounds[3] - continuation_bounds[1]
    if not grid and min(content_width, content_height, region_bottom - region_top) <= style.stroke_width_mm:
        raise ValueError("The brush leaves no usable page area")
    measured = []
    measured_tables = {}
    measured_images = {}
    code_continuations = {}
    for block in blocks:
        check_cancel(cancelled)
        if block.node.kind in FLOW_BREAK_KINDS:
            measured.append((block, [], [(0, 0, 0)], 0, []))
            continue
        if block.node.kind == "image":
            figure = measure_image(
                block, resolver, style, flow,
                (max(f.region.width_mm for p in _regions.template.effective_layouts for f in p.body_frames)
                 if _regions else content_width) - block.indent, cancelled
            )
            measured_images[block.node.node_id] = figure
            diagnostics.extend(figure.diagnostics)
            measured.append((block, figure.lines, [(0, 0, figure.total_height)], block.indent, []))
            continue
        if block.node.kind == "table":
            table = measure_table(
                table_model(block.node),
                resolver,
                flow.table_for(block.node.node_id),
                cancelled=cancelled,
                math_style=flow.math,
                footnote_style=flow.footnote,
                latin_spacing=flow.latin_spacing,
                punctuation_spacing=flow.punctuation_spacing,
                han_variation=flow.han_variation,
            )
            measured_tables[block.node.node_id] = table
            diagnostics.extend(table.diagnostics)
            if not _regions and table.width + table.style.stroke_width_mm > content_width - block.indent + 1e-7:
                diagnostics.append(
                    Diagnostic(
                        "table-page-width-overflow",
                        "Table exceeds page content width; change table or page settings",
                        block.node.span,
                    )
                )
            measured.append(
                (
                    block,
                    [[]],
                    [(0, 0, first_group_height(table) + table.style.stroke_width_mm)],
                    block.indent,
                    [],
                )
            )
            continue
        is_code = block.node.kind in {"fence", "code_block"}
        if not is_code:
            boxes, issues = measure_runs(
                block.runs,
                resolver,
                style,
                scale=block.scale,
                cancelled=cancelled,
                math_style=flow.math,
                footnote_style=flow.footnote,
                latin_spacing=flow.latin_spacing,
                punctuation_spacing=flow.punctuation_spacing,
                han_variation=flow.han_variation,
            )
            diagnostics.extend(issues)
        prefix = []
        indent = block.indent
        if block.marker == "bullet":
            indent += max(0, 3 + radius - flow.list_indent_mm)
        if block.marker and block.marker not in {"bullet", "task"}:
            runs = [
                InlineRun(
                    marker_occurrence(block, i, c, resolver),
                    role="list-marker",
                )
                for i, c in enumerate(block.marker)
            ]
            if block.note_label:
                runs = [InlineRun(o, role="footnote-label") for o in block.note_label.occurrences]
            prefix, issues = measure_runs(runs, resolver, style, cancelled=cancelled,
                                          latin_spacing=flow.latin_spacing, punctuation_spacing=flow.punctuation_spacing)
            diagnostics.extend(issues)
            indent += max(0, sum(b.advance for b in prefix) + 1.5 - flow.list_indent_mm)
        if block.task:
            size = style.em_mm * 0.55
            prefix_width = sum(b.advance for b in prefix) + 1.5 if prefix else 0
            indent = max(
                indent, block.indent - flow.list_indent_mm + prefix_width + size + 1.5 + radius
            )
            if size <= 2 * style.stroke_width_mm:
                diagnostics.append(
                    Diagnostic(
                        "task-checkbox-too-small",
                        "Task checkbox is too small for the current pen width",
                        block.task.span,
                    )
                )
        if is_code and flow.code.wrap_lines:
            indent += 4  # Reserve a separate gutter for the visible continuation mark.
        width = content_width - indent
        if (
            not _regions and block.node.kind == "math_block"
            and block.node.math
            and any(n.kind == "EquationTag" for n in block.node.math.walk())
        ):
            boxes, _ = measure_runs(
                block.runs,
                resolver,
                style,
                scale=block.scale,
                cancelled=cancelled,
                math_style=flow.math,
                math_width=max(0.01, width),
                footnote_style=flow.footnote,
                latin_spacing=flow.latin_spacing,
                punctuation_spacing=flow.punctuation_spacing,
                han_variation=flow.han_variation,
            )
        if width <= 0:
            diagnostics.append(
                Diagnostic("indent-overflow", "Nested blocks leave no line width", block.node.span)
            )
        if is_code:
            lines, issues, continued = measure_code(
                block.runs, resolver, style, flow.code, width=width, cancelled=cancelled
            )
            code_continuations[block.node.node_id] = continued
            diagnostics.extend(issues)
        else:
            lines = break_lines(
                boxes,
                max(0.01, width),
                first_width=max(0.01, width - block.first_indent),
                cancelled=cancelled,
            )
        metrics = []
        block_em = flow.code.em_mm if is_code else style.em_mm * block.scale
        block_height = flow.code.line_height_mm if is_code else style.line_height_mm * block.scale
        for line in lines:
            ascent = max([0.88 * block_em + radius] + [b.ascent for b in line])
            descent = max([0.12 * block_em + radius] + [b.descent for b in line])
            height = max(block_height, ascent + descent)
            metrics.append((ascent, descent, height))
        if block.rule:
            metrics = [(0, 0, 4)]
        measured.append((block, lines, metrics, indent, prefix))

    prepared = None
    if (
        not _regions and _footnotes is not False
        and _atomic_bands is None
        and not _fixed_references
        and not _references_only
    ):
        prepared = prepare(
            document,
            resolver,
            page,
            style,
            flow,
            measured,
            measured_tables,
            measured_images,
            code_continuations,
            cancelled,
            pager=_footnotes,
        )
    resume = prepared.common if prepared else 0
    previous = prepared.previous if prepared else None
    suffix_reused = 0
    suffix_page = None
    checkpoints = list(previous.checkpoints[:resume]) if resume else []
    placement_diagnostics_start = len(diagnostics)
    point_meter = PointAccumulator()
    fragments, ops, images = [[]], [BudgetedOps(point_meter)], [[]]
    if _regions:
        for i in range(_regions.page_index):
            allocating_page(i+2)
            fragments.append([])
            ops.append(BudgetedOps(point_meter))
            images.append([])
            if _footnotes:
                _footnotes.finish()
                _footnotes.start(i+1)
    y, line_index = region_top, 0
    previous_heading_page = None
    if resume:
        state = previous.checkpoints[resume]
        fragments, ops, images = [], [], []
        allocating_page(state.page + 1)
        for index, old_page in enumerate(previous.pages[: state.page + 1]):
            check_cancel(cancelled)
            complete = index < state.page
            fragments.append(
                list(old_page.fragments if complete else old_page.fragments[: state.fragments])
            )
            current_ops = BudgetedOps(point_meter)
            current_ops.extend(old_page.paint_ops if complete else old_page.paint_ops[: state.ops])
            ops.append(current_ops)
            images.append(list(old_page.images if complete else old_page.images[: state.images]))
        y, line_index = state.y, state.line_index
        previous_heading_page = state.previous_heading_page
        region_left, region_top, region_right, region_bottom = page_bounds(state.page)
        diagnostics.extend(previous.diagnostics[: state.diagnostics])
        if _footnotes:
            _footnotes.restore(state.footnotes, previous.note_pages, previous.note_diagnostics)

    def checkpoint():
        return Checkpoint(
            len(fragments) - 1,
            len(fragments[-1]),
            len(ops[-1]),
            len(images[-1]),
            y,
            line_index,
            previous_heading_page,
            len(diagnostics) - placement_diagnostics_start,
            _footnotes.checkpoint() if _footnotes else None,
        )

    def new_page(*, physical=False):
        nonlocal y, region_left, region_top, region_right, region_bottom, content_width, content_height, grid
        if _regions:
            _regions.next_page() if physical else _regions.next()
        count=_regions.page_index+1 if _regions else len(fragments)+1
        allocating_page(count)
        while len(fragments)<count:
            if _footnotes:
                _footnotes.finish()
            fragments.append([])
            ops.append(BudgetedOps(point_meter))
            images.append([])
            if _footnotes:
                _footnotes.start(len(fragments)-1)
        region_left, region_top, region_right, region_bottom = page_bounds(len(fragments) - 1)
        y = region_top
        if _regions:
            grid = _regions.grid
            content_width=region_right-region_left
            content_height=region_bottom-region_top

    def seek_fit(width, height, *, line=None, padding=0):
        target = _regions.fits_later(width, height, line=line, padding=padding)
        while (_regions.page_index,_regions.frame_index)!=target:
            new_page()

    def block_end(required):
        return grid.block_end(required) if grid else required

    def line_geometry(start, metric, *, align_baseline, padding):
        ascent, descent, height = metric
        if grid and align_baseline:
            return grid.line(start, *metric)
        inset = padding if grid else 0
        return start + inset + (height - ascent - descent) / 2 + ascent, block_end(start + height + 2 * inset)

    if _regions:
        def capture_partial():
            check_cancel(cancelled)
            return tuple(
                Page(i, tuple(fs), tuple(ps), images=tuple(ims))
                for i, (fs, ps, ims) in enumerate(zip(fragments, ops, images))
            ), tuple(diagnostics)

        _regions.capture_partial = capture_partial

    def rewrap(block,lines,metrics,pos,indent):
        """Reflow unconsumed measured boxes, never truncate or reparse Markdown."""
        remaining=[b for line in lines[pos:] for b in line]
        width=max(.01,content_width-indent)
        if (pos==0 and block.node.kind=='math_block' and block.node.math
                and any(n.kind=='EquationTag' for n in block.node.math.walk())):
            remaining,issues=measure_runs(block.runs,resolver,style,scale=block.scale,
                                         cancelled=cancelled,math_style=flow.math,math_width=width,
                                         footnote_style=flow.footnote,latin_spacing=flow.latin_spacing,
                                         punctuation_spacing=flow.punctuation_spacing)
            if sum(b.advance for b in remaining)<=width+1e-8:
                diagnostics.extend(issues)
        if block.node.kind in {'fence','code_block'}:
            if flow.code.wrap_lines:
                tail=[]
                line=[]
                used=0
                for box in remaining:
                    if used+box.advance>width+1e-9 and line and box.status!='line-break':
                        tail.append(line)
                        line=[]
                        used=0
                    line.append(box)
                    used+=box.advance
                    if box.status=='line-break':
                        tail.append(line)
                        line=[]
                        used=0
                if line or not tail:
                    tail.append(line)
                continuations={i for i in code_continuations.get(block.node.node_id,()) if i<pos}
                continued=pos>0 and bool(lines[pos-1]) and lines[pos-1][-1].status!='line-break'
                for i,line in enumerate(tail,pos):
                    if continued:
                        continuations.add(i)
                    continued=bool(line) and line[-1].status!='line-break'
                code_continuations[block.node.node_id]=continuations
            else:
                return lines,metrics
        else:
            tail=break_lines(remaining,width,first_width=max(.01,width-block.first_indent) if pos==0 else width,cancelled=cancelled)
        em=flow.code.em_mm if block.node.kind in {'fence','code_block'} else style.em_mm*block.scale
        line_height=flow.code.line_height_mm if block.node.kind in {'fence','code_block'} else style.line_height_mm*block.scale
        sizes=[]
        for line in tail:
            a=max([.88*em+radius]+[b.ascent for b in line])
            d=max([.12*em+radius]+[b.descent for b in line])
            sizes.append((a,d,max(line_height,a+d)))
        return lines[:pos]+tail,metrics[:pos]+sizes

    def current_page_position():
        return y, region_top, region_bottom

    def table_capacity(indent):
        return content_width-indent,region_bottom-y

    def current_y():
        return y

    def capture_start():
        return y, len(fragments[-1]), len(ops[-1]), len(images[-1])

    def capture_end(start, span, *, table=None, x=0):
        if _atomic_bands is not None:
            top, fs, ps, rs = start
            _atomic_bands.append(
                AtomicBand(
                    top,
                    y,
                    tuple(fragments[-1][fs:]),
                    tuple(ops[-1][ps:]),
                    tuple(images[-1][rs:]),
                    span,
                    table,
                    x,
                )
            )

    def place_box(box, x, baseline, index, *, stroke_width=None, repeated=False, container_id=None):
        stroke_width = style.stroke_width_mm if stroke_width is None else stroke_width
        if box.math:
            for item in box.math.glyphs:
                child = InlineBox(
                    InlineRun(item.occurrence),
                    item.advance_mm,
                    item.ascent_mm,
                    item.descent_mm,
                    item.em_mm,
                    item.origin_offset_mm,
                    item.glyph,
                    item.status,
                )
                place_box(
                    child,
                    x + item.x_mm,
                    baseline + item.baseline_mm,
                    index,
                    stroke_width=stroke_width,
                    repeated=repeated,
                    container_id=container_id,
                )
            for rule in box.math.rules:
                ops[-1].append(
                    PaintOp(
                        rule.occurrence_id,
                        tuple((x + px, baseline + py) for px, py in rule.points),
                        stroke_width,
                    )
                )
            return x + box.advance
        radius = stroke_width / 2
        o, glyph = box.run.occurrence, box.glyph
        ink = None
        if glyph:
            gx = x + box.origin_offset
            top = baseline - glyph.metrics.baseline * box.em
            bounds = glyph.bounds
            ink = (
                gx + bounds[0] * box.em - radius,
                top + bounds[1] * box.em - radius,
                gx + bounds[2] * box.em + radius,
                top + bounds[3] * box.em + radius,
            )
            if (
                ink[0] < region_left - 1e-9
                or ink[1] < region_top - 1e-9
                or ink[2] > region_right + 1e-9
                or ink[3] > region_bottom + 1e-9
            ):
                diagnostics.append(
                    Diagnostic("ink-overflow", "Ink exceeds the content area", o.span)
                )
            for stroke in glyph.strokes:
                ops[-1].append(
                    PaintOp(
                        o.occurrence_id,
                        tuple((gx + px * box.em, top + py * box.em) for px, py in stroke),
                        stroke_width,
                    )
                )
        elif box.status in {"missing", "unsupported"}:
            top = baseline - 0.88 * box.em
            points = (
                (x, top),
                (x + box.advance, top),
                (x + box.advance, top + box.em),
                (x, top + box.em),
                (x, top),
            )
            ops[-1].append(PaintOp(o.occurrence_id, points, 0.2, "#dc2626"))
        fragments[-1].append(
            Fragment(
                digest([o.occurrence_id, len(fragments), index]),
                o.occurrence_id,
                o.node_id,
                o.span,
                o.text,
                len(fragments) - 1,
                index,
                x,
                baseline,
                box.advance,
                (x, baseline - box.ascent, x + box.advance, baseline + box.descent),
                ink,
                glyph.asset_id if glyph else None,
                box.status,
                repeated,
                container_id,
                glyph_origin_offset_mm=box.origin_offset if glyph else 0,
                glyph_em_mm=box.em if glyph else 0,
            )
        )
        return x + box.advance

    last_content_block = next(
        (i for i in range(len(measured) - 1, -1, -1) if measured[i][0].node.kind not in FLOW_BREAK_KINDS),
        -1,
    )
    for block_index in range(resume, len(measured)):
        check_cancel(cancelled)
        state = checkpoint() if prepared else None
        old_index = suffix_boundary(prepared, block_index, state)
        if old_index is not None:
            old = previous.checkpoints[old_index]
            allocating_page(len(previous.pages))
            for index in range(old.page, len(previous.pages)):
                check_cancel(cancelled)
                old_page = previous.pages[index]
                if index == old.page:
                    fragments[-1].extend(old_page.fragments[old.fragments :])
                    ops[-1].extend(old_page.paint_ops[old.ops :])
                    images[-1].extend(old_page.images[old.images :])
                else:
                    fragments.append(list(old_page.fragments))
                    current_ops = BudgetedOps(point_meter)
                    current_ops.extend(old_page.paint_ops)
                    ops.append(current_ops)
                    images.append(list(old_page.images))
            diagnostics.extend(previous.diagnostics[old.diagnostics :])
            if _footnotes:
                _footnotes.restore(
                    previous.checkpoints[-1].footnotes,
                    previous.note_pages,
                    previous.note_diagnostics,
                    boundary=old.footnotes,
                )
            checkpoints.extend(suffix_checkpoints(previous, old_index, state))
            suffix_reused = len(measured) - block_index
            suffix_page = old.page
            break
        if prepared:
            checkpoints.append(state)
        block, lines, metrics, indent, prefix = measured[block_index]
        if block.node.kind in FLOW_BREAK_KINDS:
            # Page controls skip remaining frames on this physical page. Empty
            # pages and trailing controls do not create spurious blank output.
            active = block.node.kind == "framebreak" or bool(
                fragments[-1] or ops[-1] or images[-1] or y > region_top
            )
            if active and block_index < last_content_block:
                if _regions:
                    _regions.span = block.node.span
                new_page(physical=block.node.kind == "pagebreak")
            previous_heading_page = None
            continue
        if _regions:
            _regions.span=block.node.span
            if block.node.node_id not in measured_images and block.node.node_id not in measured_tables and not block.rule:
                lines,metrics=rewrap(block,lines,metrics,0,indent)
        gap = flow.heading_gap_mm if block.node.kind == "heading" else flow.paragraph_gap_mm
        if y > region_top and not grid:
            required = metrics[0][2]
            if block.keep_next and block_index + 1 < len(measured):
                required = sum(m[2] for m in metrics)
                for next_block, _, next_metrics, _, _ in measured[block_index + 1 :]:
                    if next_block.node.kind in FLOW_BREAK_KINDS:
                        break
                    required += (
                        flow.heading_gap_mm if next_block.keep_next else flow.paragraph_gap_mm
                    )
                    required += (
                        sum(m[2] for m in next_metrics)
                        if next_block.keep_next
                        else next_metrics[0][2]
                    )
                    if not next_block.keep_next:
                        break
            foot_heading_fits = True
            if _footnotes and block.keep_next:
                probe = _footnotes.probe()
                future_y = y + gap
                for offset, (future_block, future_lines, future_metrics, _, _) in enumerate(
                    measured[block_index:]
                ):
                    if future_block.node.kind in FLOW_BREAK_KINDS:
                        break
                    if offset:
                        future_y += (
                            flow.heading_gap_mm if future_block.keep_next else flow.paragraph_gap_mm
                        )
                    if future_block.node.node_id in measured_images:
                        future_lines = [
                            [
                                b
                                for line in measured_images[future_block.node.node_id].lines
                                for b in line
                            ]
                        ]
                    if future_block.node.node_id in measured_tables:
                        future_table = measured_tables[future_block.node.node_id]
                        header_rows = future_table.model.header_rows
                        first_group = next(
                            (g for g in future_table.model.row_groups if g[0] >= header_rows), None
                        )
                        rows = range(first_group[1] if first_group else future_table.model.rows)
                        future_lines = [table_boxes(future_table, rows)]
                    keep = (
                        len(future_lines) if future_block.keep_next else min(2, len(future_lines))
                    )
                    for future_line, (_, _, future_height) in zip(
                        future_lines[:keep], future_metrics[:keep]
                    ):
                        future_y += future_height
                        if not probe.can_fit([future_line], future_y):
                            foot_heading_fits = False
                            break
                        probe.accept(future_line, future_y)
                    if not foot_heading_fits or not future_block.keep_next:
                        break
            if (
                y + gap + required > region_bottom or not foot_heading_fits
            ) and required <= content_height:
                new_page()
            else:
                y += gap
        if block.node.node_id in measured_images:
            figure = measured_images[block.node.node_id]
            if _regions and (figure.width+indent>content_width+1e-8 or block_end(y + figure.total_height)>region_bottom+1e-8):
                seek_fit(figure.width+indent,figure.total_height)
            caption_boxes = [box for line in figure.lines for box in line]
            while True:
                check_cancel(cancelled)
                end = block_end(y + figure.total_height)
                fits_geometry = end <= region_bottom + 1e-9
                fits_notes = not _footnotes or _footnotes.can_fit(
                    [caption_boxes], end
                )
                if fits_geometry and fits_notes:
                    break
                if (
                    y > region_top
                    or (_footnotes and _footnotes.can_advance())
                    or (
                        len(fragments) == 1
                        and figure.total_height <= content_height
                        and figure.total_height > region_bottom - region_top
                    )
                ):
                    new_page()
                    continue
                break  # Impossible empty-page combination: emit debug geometry once.
            if _footnotes:
                _footnotes.accept(caption_boxes, end)
            capture = capture_start()
            if figure.total_height > region_bottom - region_top + 1e-9:
                diagnostics.append(
                    Diagnostic(
                        "image-height-overflow",
                        "Image and caption exceed the empty page region",
                        block.node.span,
                    )
                )
            spare = max(0, content_width - indent - figure.width)
            x = (
                region_left
                + indent
                + (
                    spare / 2
                    if figure.alignment == "center"
                    else spare
                    if figure.alignment == "right"
                    else 0
                )
            )
            o = block.node.occurrences[0]
            bounds = (x, y, x + figure.width, y + figure.height)
            resource = figure.resource
            vector = isinstance(resource, LineSvgResource)
            if vector:
                for path in figure.paths:
                    ops[-1].append(
                        PaintOp(
                            o.occurrence_id,
                            tuple((x + px, y + py) for px, py in path),
                            style.stroke_width_mm,
                        )
                    )
            else:
                images[-1].append(
                    RasterOp(
                        o.occurrence_id,
                        o.node_id,
                        o.span,
                        dict(block.node.attributes).get("src", ""),
                        resource.original_sha256 if resource else None,
                        resource.png_base64 if resource else None,
                        bounds,
                    )
                )
            fragments[-1].append(
                Fragment(
                    digest([o.occurrence_id, len(fragments), "image"]),
                    o.occurrence_id,
                    o.node_id,
                    o.span,
                    "\ufffc",
                    len(fragments) - 1,
                    line_index,
                    x,
                    y + figure.height,
                    figure.width,
                    bounds,
                    bounds if vector else None,
                    None,
                    "image-vector"
                    if vector
                    else "image-reference"
                    if resource
                    else "image-missing",
                    container_id=block.node.node_id,
                    source_resource_id=(
                        f"svg:{resource.original_sha256}:tolerance-mm={flow.image_for(block.node.node_id).svg_tolerance_mm:g}"
                        if vector
                        else None
                    ),
                )
            )
            caption_y = y + figure.height + figure.gap
            for caption, (ascent, descent, height) in zip(figure.lines, figure.metrics):
                cx = x + max(0, (figure.width - sum(b.advance for b in caption)) / 2)
                baseline = caption_y + (height - ascent - descent) / 2 + ascent
                decorations = []
                for box in caption:
                    start = cx
                    cx = place_box(box, cx, baseline, line_index, container_id=block.node.node_id)
                    decorations.append((start, cx, box))
                for name in ("underline", "strike"):
                    intervals = []
                    for start, end, box in decorations:
                        if getattr(box.run, name):
                            if intervals and abs(intervals[-1][1] - start) < 1e-9:
                                intervals[-1] = (intervals[-1][0], end)
                            else:
                                intervals.append((start, end))
                    offset = descent - radius - 0.15 if name == "underline" else -0.35 * style.em_mm
                    for start, end in intervals:
                        if end > start:
                            ops[-1].append(
                                PaintOp(
                                    f"{block.node.node_id}:caption-{name}:{line_index}",
                                    (
                                        (start + radius, baseline + offset),
                                        (end - radius, baseline + offset),
                                    ),
                                    style.stroke_width_mm,
                                )
                            )
                caption_y += height
                line_index += 1
            for depth in range(block.quote_depth):
                qx = region_left + depth * flow.quote_indent_mm + radius
                ops[-1].append(
                    PaintOp(
                        f"{block.node.node_id}:quote:{depth}",
                        ((qx, y + radius), (qx, y + figure.total_height - radius)),
                        style.stroke_width_mm,
                    )
                )
            y = end
            capture_end(capture, block.node.span)
            line_index += 1
            previous_heading_page = None
            continue
        if block.node.node_id in measured_tables:
            table = measured_tables[block.node.node_id]
            if _regions:
                from .flow_tables import paginate_regions
                chunks = paginate_regions(
                    table, lambda indent=indent: table_capacity(indent),
                    lambda width, height, indent=indent: seek_fit(width + indent, height),
                    new_page, _regions, cancelled=cancelled, pager=_footnotes,
                    position=current_y, occupied_end=block_end,
                )
            elif _footnotes:
                chunks = paginate_table_with_notes(
                    table,
                    _footnotes,
                    current_page_position,
                    new_page,
                    content_height,
                    diagnostics,
                    cancelled=cancelled,
                )
            else:
                chunks, issues = paginate_table(
                    table,
                    region_bottom - y - table.style.stroke_width_mm,
                    content_height - table.style.stroke_width_mm,
                    cancelled=cancelled,
                )
                diagnostics.extend(issues)
            for chunk in chunks:
                if chunk.new_page:
                    new_page()
                capture = capture_start()
                # Width is the distance between outside border centrelines.
                x = (
                    region_left
                    + indent
                    + max(
                        table.style.stroke_width_mm / 2, (content_width - indent - table.width) / 2
                    )
                )
                line_index = paint_table(
                    table,
                    chunk,
                    x,
                    y + table.style.stroke_width_mm / 2,
                    place_box,
                    ops[-1],
                    line_index,
                    cancelled=cancelled,
                )
                for depth in range(block.quote_depth):
                    qx = region_left + depth * flow.quote_indent_mm + radius
                    ops[-1].append(
                        PaintOp(
                            f"{block.node.node_id}:quote:{depth}:{len(fragments)}",
                            ((qx, y + radius), (qx, y + chunk.height - radius)),
                            style.stroke_width_mm,
                        )
                    )
                y = block_end(y + chunk.height + table.style.stroke_width_mm)
                capture_end(capture, block.node.span, table=table, x=x)
            previous_heading_page = None
            continue
        pos = 0
        align_baseline = not block.rule and block.node.kind != "math_block"
        padding = flow.paragraph_gap_mm / 2 if block.node.kind == "math_block" else 0
        while pos < len(lines):
            check_cancel(cancelled)
            if _regions and block.rule and block_end(y + metrics[pos][2]) > region_bottom + 1e-8:
                seek_fit(0, metrics[pos][2])
                continue
            if _regions and not block.rule:
                lines,metrics=rewrap(block,lines,metrics,pos,indent)
                required_width=sum(b.advance for b in lines[pos])+indent+(block.first_indent if pos==0 else 0)
                end = line_geometry(y, metrics[pos], align_baseline=align_baseline, padding=padding)[1]
                if required_width > content_width + 1e-8 or end > region_bottom + 1e-8:
                    empty_end = line_geometry(
                        region_top, metrics[pos], align_baseline=align_baseline, padding=padding
                    )[1]
                    if y > region_top and required_width <= content_width + 1e-8 and empty_end <= region_bottom + 1e-8:
                        new_page()
                    else:
                        seek_fit(required_width, metrics[pos][2],
                                 line=metrics[pos] if align_baseline else None, padding=padding)
                    continue
            count, candidate_start = 0, y
            probe = _footnotes.probe() if _footnotes else None
            while pos + count < len(lines):
                candidate_bottom = line_geometry(
                    candidate_start, metrics[pos + count], align_baseline=align_baseline, padding=padding
                )[1]
                if candidate_bottom > region_bottom + 1e-9:
                    break
                if probe:
                    candidate = lines[pos + count]
                    if not probe.can_fit([candidate], candidate_bottom):
                        break
                    probe.accept(candidate, candidate_bottom)
                candidate_start = candidate_bottom
                count += 1
            remaining = len(lines) - pos
            protected_heading = (
                _footnotes and pos == 0 and previous_heading_page == len(fragments) - 1
            )
            if (
                not _regions and not protected_heading
                and remaining - count == 1
                and count >= 2
                and y > region_top
                and sum(m[2] for m in metrics[pos:]) <= content_height
            ):
                new_page()
                continue
            if count == 0 and (
                y > region_top
                or (
                    len(fragments) == 1
                    and metrics[pos][2] <= content_height
                    and metrics[pos][2] > region_bottom - region_top
                )
            ):
                new_page()
                continue
            # At least two body lines on either side of a page boundary when feasible.
            if (
                not _regions and not protected_heading
                and count == 1
                and remaining > 1
                and y > region_top
                and sum(m[2] for m in metrics[pos : pos + 2]) <= content_height
            ):
                new_page()
                continue
            if remaining - count == 1 and count > 2:
                count -= 1
            if count == 0 and _footnotes and _footnotes.can_advance():
                new_page()
                continue
            if count == 0 and grid:
                _regions.stop("正文行及其脚注无法同时放入纸张行格，排版已停止。")
            if count == 0:
                count = 1  # Over-tall line: emit once with an error, never loop forever.
            for local in range(pos, pos + count):
                line = lines[local]
                capture = (
                    capture_start()
                    if block.rule or (_atomic_bands is not None and not line)
                    else None
                )
                ascent, descent, height = metrics[local]
                baseline, end = line_geometry(
                    y, metrics[local], align_baseline=align_baseline, padding=padding
                )
                if _footnotes:
                    _footnotes.accept(line, end)
                if height > region_bottom - region_top + 1e-9:
                    diagnostics.append(
                        Diagnostic(
                            "line-height-overflow", "Line exceeds empty page", block.node.span
                        )
                    )
                first_indent = block.first_indent if local == 0 else 0
                if sum(b.advance for b in line) > content_width - indent - first_indent + 1e-9:
                    code_line = block.node.kind in {"fence", "code_block"}
                    span = (
                        SourceSpan(
                            line[0].run.occurrence.span.start, line[-1].run.occurrence.span.end
                        )
                        if code_line and line
                        else block.node.span
                    )
                    diagnostics.append(
                        Diagnostic(
                            "code-line-width-overflow" if code_line else "line-width-overflow",
                            "Unbreakable run exceeds line",
                            span,
                        )
                    )
                visible = [b for b in line if b.status not in {"space", "line-break", "break-hint"}]
                if (
                    block.node.kind not in {"fence", "code_block"}
                    and visible
                    and (
                        visible[0].run.occurrence.text in CLOSING
                        or visible[-1].run.occurrence.text in OPENING
                    )
                ):
                    diagnostics.append(
                        Diagnostic(
                            "forbidden-line-boundary",
                            "Punctuation at forbidden boundary",
                            block.node.span,
                        )
                    )
                x = region_left + indent + first_indent
                if local in code_continuations.get(block.node.node_id, ()):
                    cy = baseline - flow.code.em_mm * 0.35
                    ops[-1].append(
                        PaintOp(
                            f"{block.node.node_id}:code-continuation:{local}",
                            ((x - 3, cy - 1), (x - 3, cy), (x - 1, cy), (x - 1.6, cy - 0.6)),
                            style.stroke_width_mm,
                        )
                    )
                if block.node.kind == "math_block" and flow.math.display_align == "center":
                    x += max(0, content_width - indent - sum(b.advance for b in line)) / 2
                if local == 0 and block.marker:
                    marker_x = x - (sum(b.advance for b in prefix) + 1.5 if prefix else 3)
                    if block.task:
                        marker_x = x - (
                            sum(b.advance for b in prefix)
                            + (1.5 if prefix else 0)
                            + style.em_mm * 0.55
                            + 1.5
                        )
                    for box in prefix:
                        marker_x = place_box(box, marker_x, baseline, line_index)
                    if block.marker == "bullet":
                        cy = baseline - style.em_mm * 0.35
                        ops[-1].append(
                            PaintOp(
                                block.node.node_id + ":bullet",
                                (
                                    (marker_x, cy),
                                    (marker_x + 0.5, cy - 0.5),
                                    (marker_x + 1, cy),
                                    (marker_x + 0.5, cy + 0.5),
                                    (marker_x, cy),
                                ),
                                style.stroke_width_mm,
                            )
                        )
                if local == 0 and block.task:
                    task = block.task
                    o = task.occurrences[0]
                    size = style.em_mm * 0.55
                    left, top = x - size - 1.5, baseline - style.em_mm * 0.35 - size / 2
                    right, bottom = left + size, top + size
                    checked = dict(task.attributes)["checked"] == "true"
                    bounds = (left - radius, top - radius, right + radius, bottom + radius)
                    fragments[-1].append(
                        Fragment(
                            digest([o.occurrence_id, "checkbox"]),
                            o.occurrence_id,
                            task.node_id,
                            task.span,
                            "\ufffc",
                            len(fragments) - 1,
                            line_index,
                            left,
                            baseline,
                            size,
                            bounds,
                            bounds,
                            None,
                            "task-checked" if checked else "task-unchecked",
                        )
                    )
                    ops[-1].append(
                        PaintOp(
                            o.occurrence_id,
                            (
                                (left, top),
                                (right, top),
                                (right, bottom),
                                (left, bottom),
                                (left, top),
                            ),
                            style.stroke_width_mm,
                        )
                    )
                    if checked:
                        ops[-1].append(
                            PaintOp(
                                o.occurrence_id,
                                (
                                    (left + 0.2 * size, top + 0.5 * size),
                                    (left + 0.43 * size, top + 0.73 * size),
                                    (left + 0.82 * size, top + 0.23 * size),
                                ),
                                style.stroke_width_mm,
                            )
                        )
                decoration = []
                extra = [0.0] * len(line)
                if (flow.paragraph_align == "justify" and block.node.kind == "paragraph"
                        and local+1 < len(lines) and line and line[-1].status != "line-break"):
                    line, extra = justify_line(line, content_width-indent-first_indent)
                for box, gap_after in zip(line, extra):
                    left = x
                    x = place_box(box, x, baseline, line_index) + gap_after
                    if box.run.underline or box.run.strike:
                        decoration.append((left, x, box))
                for name in ("underline", "strike"):
                    intervals = []
                    for left, right, box in decoration:
                        if getattr(box.run, name):
                            if intervals and abs(intervals[-1][1] - left) < 1e-9:
                                intervals[-1] = (intervals[-1][0], right)
                            else:
                                intervals.append((left, right))
                    dy = (
                        descent - radius - 0.15
                        if name == "underline"
                        else -0.35 * style.em_mm * block.scale
                    )
                    for left, right in intervals:
                        if right > left:
                            ops[-1].append(
                                PaintOp(
                                    f"{block.node.node_id}:{name}:{line_index}",
                                    (
                                        (left + radius, baseline + dy),
                                        (right - radius, baseline + dy),
                                    ),
                                    style.stroke_width_mm,
                                )
                            )
                if block.rule:
                    ops[-1].append(
                        PaintOp(
                            block.node.node_id + ":rule",
                            ((x + radius, y + 2), (region_right - radius, y + 2)),
                            style.stroke_width_mm,
                        )
                    )
                for depth in range(block.quote_depth):
                    qx = region_left + depth * flow.quote_indent_mm + radius
                    ops[-1].append(
                        PaintOp(
                            f"{block.node.node_id}:quote:{depth}:{line_index}",
                            ((qx, y + radius), (qx, end - radius)),
                            style.stroke_width_mm,
                        )
                    )
                y = end
                if capture is not None:
                    capture_end(capture, block.node.span)
                line_index += 1
            pos += count
            if pos < len(lines):
                new_page()
        previous_heading_page = len(fragments) - 1 if block.keep_next else None
    if prepared and not suffix_reused:
        checkpoints.append(checkpoint())
    if _footnotes:
        _footnotes.expand_final()
        _footnotes.finish()
    pages, body_pages = [], []
    for i, (fs, ps) in enumerate(zip(fragments, ops)):
        if (resume and i < previous.checkpoints[resume].page) or (
            suffix_page is not None and i > suffix_page
        ):
            pages.append(previous.finished_pages[i])
            if template:
                body_pages.append(previous.pages[i])
            continue
        preview = ()
        background = None
        if template:
            body_pages.append(Page(i, tuple(fs), tuple(ps), images=tuple(images[i])))
            background = template.face(i).background if template.mode == "preprinted" else None
            dx = template.offset_x_mm if template.mode == "blank" else 0
            dy = template.offset_y_mm if template.mode == "blank" else 0
            rules = tuple(
                PaintOp(
                    f"template:{rule.name}",
                    tuple((x + dx, y + dy) for x, y in rule.points),
                    rule.width_mm,
                    execution_domain="template-frame",
                )
                for rule in template.face(i).rules
            )
            ps = [replace(op, execution_domain="template-body") for op in ps]
            if template.mode == "blank":
                ps = [*rules, *ps]
            elif background is None:
                preview = tuple(replace(op, color="#8a8a8a") for op in rules)
        pages.append(Page(i, tuple(fs), tuple(ps), preview, background, tuple(images[i])))
    pages = tuple(pages)
    expected = []
    for block, lines, _, _, prefix in measured:
        if block.node.node_id in measured_images:
            expected.extend(o.occurrence_id for o in block.node.occurrences)
        if block.node.node_id in measured_tables:
            boxes = [
                b
                for cell in measured_tables[block.node.node_id].cells
                for line in cell.lines
                for b in line
            ]
        else:
            boxes = [*prefix, *(b for line in lines for b in line)]
        if block.task:
            expected.extend(o.occurrence_id for b in prefix for o in box_occurrences(b))
            expected.extend(o.occurrence_id for o in block.task.occurrences)
            boxes = [b for line in lines for b in line]
        expected.extend(o.occurrence_id for b in boxes for o in box_occurrences(b))
    if tuple(f.occurrence_id for p in pages for f in p.fragments if not f.repeated) != tuple(
        expected
    ):
        raise RuntimeError("Markdown layout lost, duplicated or reordered inline instances")
    key = digest(
        {
            "source": document.content_key,
            "page": asdict(page),
            "style": asdict(style),
            "flow": asdict(flow),
            "resources": resolver.resource_key,
            "selections": resolver.selection_records(),
            "layout": LAYOUT_VERSION,
        }
    )
    snapshot = LayoutSnapshot(
        key,
        key,
        document.document_id,
        document.revision,
        page,
        pages,
        tuple(diagnostics),
        resolver.resource_key,
        LAYOUT_VERSION,
    )
    validate_snapshot(snapshot, cancelled=cancelled)
    publish(
        prepared,
        checkpoints,
        pages,
        diagnostics[placement_diagnostics_start:],
        cancelled,
        suffix_reused=suffix_reused,
        body_pages=tuple(body_pages) if template else None,
        pager=_footnotes,
    )
    return snapshot
