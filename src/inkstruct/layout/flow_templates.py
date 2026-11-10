"""Compose template v3 from the shared body engine and independent fixed fields."""

from collections import Counter
from dataclasses import asdict, replace

from ..document.limits import PointAccumulator, allocating_page, validate_snapshot
from ..document.named_fields import split_fields
from ..document.schema import Diagnostic, PageProfile, SourceSpan, digest
from ..document.template_diagnostics import TemplateDiagnostic, TemplateTarget, with_template_target
from ..scene.schema import LayoutSnapshot, Page, PaintOp
from .flow_regions import NoRegionProgress, RegionCursor
from .inline import check_cancel

VERSION = "template-single-flow-v3/named-fields-v1/partial-preview-v1/paper-grid-v1"


def layout_flow_template(document, resolver, *, page, style, flow, cancelled=None):
    from .blocks import layout_markdown

    template = flow.template
    body, definitions, issues = split_fields(document, template)
    diagnostics = list(issues)
    if "/named-fields-v1" not in document.dialect and ":::field" in document.source:
        # Protocol must be chosen before parsing, so a legacy document containing
        # literal :::field remains unchanged until explicitly converted.
        diagnostics.append(
            Diagnostic(
                "template-field-parser-required",
                "请使用命名字段协议解析此模板的单份 Markdown。",
                SourceSpan(0, 0),
            )
        )
    inner = replace(flow, template=None, template_bindings=(), glyph_corrections=())
    cursor = RegionCursor(template)
    try:
        if body.nodes:
            cursor.bounds()
            result = layout_markdown(
                body,
                resolver,
                page=template.page,
                style=style,
                flow=inner,
                cancelled=cancelled,
                _regions=cursor,
            )
            pages = list(result.pages)
            diagnostics.extend(result.diagnostics)
        else:
            pages = [Page(0, (), ())]
            diagnostics.extend(document.diagnostics)
    except NoRegionProgress as error:
        # A blocked source object is explicit and prevents finished export.
        # The authoritative source is retained for correction, never consumed.
        pages = list(error.pages) or [Page(0, (), ())]
        diagnostics.extend(error.diagnostics or document.diagnostics)
        diagnostics.append(Diagnostic("template-body-no-progress", str(error), error.span))
    # A nonempty body ends on its last used page, including inside the start
    # group. An empty/fields-only document emits the configured start group
    # once, or the first loop layout when there is no start group.
    count = max(len(pages), len(template.start_pages) if not body.nodes else 1)
    if template.finish_cycle and count > len(template.start_pages):
        cycles = (count - len(template.start_pages) + len(template.effective_loop) - 1) // len(
            template.effective_loop
        )
        count = len(template.start_pages) + cycles * len(template.effective_loop)
    allocating_page(count)
    while len(pages) < count:
        pages.append(Page(len(pages), (), ()))
    # Fields do not change count. Each is measured in its own fixed dimensions.
    composed = []
    seen = Counter()
    meter = PointAccumulator(pages)
    for index, original in enumerate(pages):
        check_cancel(cancelled)
        layout = template.layout(index)
        fragments = list(original.fragments)
        ops = []
        previews = []
        images = list(original.images)
        for rule in layout.rules:
            rx = template.offset_x_mm if template.mode == "blank" else 0
            ry = template.offset_y_mm if template.mode == "blank" else 0
            op = PaintOp(
                f"template:{layout.layout_id}:{rule.name}",
                tuple((x + rx, y + ry) for x, y in rule.points),
                rule.width_mm,
                execution_domain="template-frame",
            )
            meter.add(len(op.points))
            if template.mode == "blank":
                ops.append(op)
            elif layout.background is None:
                previews.append(replace(op, color="#8a8a8a"))
        for frame in layout.frames:
            if frame.role == "body":
                continue
            if frame.role == "field":
                node = definitions.get(frame.field_id)
                if node is None:
                    continue
                field_doc = replace(
                    document,
                    nodes=tuple(
                        n
                        for n in node.children
                        if not n.kind.startswith("footnote_") and n.kind != "named_field_error"
                    ),
                    diagnostics=(),
                )
                span = node.span
            else:
                # Automatic page values have deterministic identities distinct
                # from user source, independent of cyclic layout indices.
                from ..document.editing import SourceSession
                from ..document.markdown import parse_markdown

                text = str(index + 1)
                session = SourceSession(
                    "", document_id=document.document_id + ":page-number:" + str(index)
                )
                session.source = text
                session.atom_ids = tuple(digest([session.document_id, i]) for i in range(len(text)))
                field_doc = parse_markdown(session)
                span = SourceSpan(0, 0)
            region = frame.region
            target = TemplateTarget(
                frame.frame_id, frame.field_id or None, layout.layout_id, page_index=index
            )
            fixed = layout_markdown(
                field_doc,
                resolver,
                page=PageProfile(region.width_mm, region.height_mm, 0),
                style=style,
                flow=inner,
                cancelled=cancelled,
                _references_only=True,
            )
            diagnostics.extend(with_template_target(d, target) for d in fixed.diagnostics)
            if len(fixed.pages) > 1:
                diagnostics.append(
                    TemplateDiagnostic(
                        "template-field-overflow",
                        f"布局 {layout.label} 的字段框 {frame.label} 溢出；不会续页、缩字或截断。",
                        span,
                        target=target,
                    )
                )
            dx = region.x_mm + template.offset_x_mm
            dy = region.y_mm + template.offset_y_mm
            for local in fixed.pages:
                off = dy + local.index * region.height_mm

                def shifted(b, dx=dx, off=off):
                    return (b[0] + dx, b[1] + off, b[2] + dx, b[3] + off) if b else None

                for f in local.fragments:
                    repeated = f.repeated or seen[f.occurrence_id] > 0
                    fragments.append(
                        replace(
                            f,
                            fragment_id=digest([f.fragment_id, index, frame.frame_id]),
                            page_index=index,
                            x_mm=f.x_mm + dx,
                            baseline_mm=f.baseline_mm + off,
                            logical_bounds=shifted(f.logical_bounds),
                            ink_bounds=shifted(f.ink_bounds),
                            repeated=repeated,
                            container_id=f"template-field:{frame.field_id or frame.frame_id}",
                        )
                    )
                    seen[f.occurrence_id] += 1
                for op in local.paint_ops:
                    moved = replace(
                        op,
                        points=tuple((x + dx, y + off) for x, y in op.points),
                        execution_domain=f"template-field:{frame.frame_id}",
                    )
                    meter.add(len(moved.points))
                    ops.append(moved)
                images.extend(
                    replace(image, bounds=shifted(image.bounds)) for image in local.images
                )
        ops.extend(
            replace(
                op,
                execution_domain="template-body"
                if op.execution_domain == "page"
                else op.execution_domain,
            )
            for op in original.paint_ops
        )
        composed.append(
            Page(
                index,
                tuple(fragments),
                tuple(ops),
                tuple(previews),
                layout.background if template.mode == "preprinted" else None,
                tuple(images),
                layout.label,
            )
        )
    used = {
        f.field_id
        for index in range(len(pages))
        for f in template.layout(index).frames
        if f.role == "field"
    }
    for key, node in definitions.items():
        if key not in used and node.children:
            diagnostics.append(
                TemplateDiagnostic(
                    "template-field-not-placed",
                    f"字段 {key} 在实际页面中没有字段框；请配置起始页、补齐循环组或添加字段框。",
                    node.span,
                    target=TemplateTarget(key, key, "named"),
                )
            )
    key = digest(
        {
            "source": document.content_key,
            "flow": asdict(flow),
            "style": asdict(style),
            "resources": resolver.resource_key,
            "selections": resolver.selection_records(),
            "layout": VERSION,
        }
    )
    result = LayoutSnapshot(
        key,
        key,
        document.document_id,
        document.revision,
        template.page,
        tuple(composed),
        tuple(dict.fromkeys(diagnostics)),
        resolver.resource_key,
        VERSION,
    )
    validate_snapshot(result, cancelled=cancelled)
    return result
