"""Place source-bound fixed fields separately from paginated Markdown body."""

from collections import Counter
from dataclasses import asdict, replace

from ..document.break_commands import constrain_flow_breaks
from ..document.limits import BudgetedOps, PointAccumulator
from ..document.schema import PageProfile, SourceSpan, digest
from ..document.template_diagnostics import TemplateDiagnostic, binding_target, with_template_target
from ..document.template_slots import geometry_only, slot_diagnostics
from ..scene.schema import Page
from .inline import check_cancel

VERSION = "template-source-fields-v2"


def layout_template_fields(document, resolver, *, page, style, flow, cancelled=None):
    from .blocks import layout_markdown

    template = flow.template
    no_bindings = replace(flow, template=geometry_only(template), template_bindings=())
    diagnostics = list(slot_diagnostics(document, template, flow.template_bindings))
    selected = []
    by_id = {n.node_id: n for n in document.nodes}
    for binding in flow.template_bindings:
        check_cancel(cancelled)
        target = binding_target(template, binding)
        nodes = tuple(n for n in document.nodes if n.node_id in binding.node_ids)
        span = SourceSpan(nodes[0].span.start, nodes[-1].span.end) if nodes else SourceSpan(0, 0)
        if not template:
            diagnostics.append(
                TemplateDiagnostic(
                    "template-binding-no-template",
                    "A fixed field requires a page template",
                    span,
                    target=target,
                )
            )
            continue
        if any(node_id not in by_id for node_id in binding.node_ids):
            diagnostics.append(
                TemplateDiagnostic(
                    "template-binding-source-missing",
                    f"Field {binding.region}: a bound top-level block was removed or replaced; rebind or unbind it",
                    span,
                    target=target,
                )
            )
            continue
        if any(n.kind == "footnote_definition" for n in nodes):
            diagnostics.append(
                TemplateDiagnostic(
                    "template-footnote-definition-binding",
                    "Bind reference-containing source blocks to fields; footnote definitions belong to the page-bottom note area",
                    span,
                    target=target,
                )
            )
            continue
        faces = (
            (template.first, template.continuation) if binding.pages == "all" else (template.first,)
        )
        missing_region = next(
            (
                i
                for i, face in enumerate(faces)
                if not any(r.name == binding.region for r in face.reserved)
            ),
            None,
        )
        if missing_region is not None:
            target = binding_target(
                template, binding, face="first" if missing_region == 0 else "continuation"
            )
            diagnostics.append(
                TemplateDiagnostic(
                    "template-binding-region-missing",
                    f"Field {binding.region}: reserved region is missing on a target page",
                    span,
                    target=target,
                )
            )
            continue
        missing_anchor = next(
            (
                i
                for i, face in enumerate(faces)
                if binding.anchor and not any(a.name == binding.anchor for a in face.anchors)
            ),
            None,
        )
        if missing_anchor is not None:
            target = binding_target(
                template, binding, face="first" if missing_anchor == 0 else "continuation"
            )
            diagnostics.append(
                TemplateDiagnostic(
                    "template-binding-anchor-missing",
                    f"Field {binding.region}: baseline anchor is missing on a target page",
                    span,
                    target=target,
                )
            )
            continue
        regions = [next(r for r in face.reserved if r.name == binding.region) for face in faces]
        small_region = next(
            (
                i
                for i, r in enumerate(regions)
                if min(r.width_mm, r.height_mm) <= style.stroke_width_mm
            ),
            None,
        )
        if (
            small_region is not None
            or max(flow.math.em_mm, flow.code.em_mm, flow.code.advance_mm, flow.code.line_height_mm)
            * binding.scale
            > 2000
        ):
            target = binding_target(
                template, binding, face="continuation" if small_region == 1 else "first"
            )
            diagnostics.append(
                TemplateDiagnostic(
                    "template-field-configuration-invalid",
                    f"Field {binding.region}: region is too small for the pen or scaled dimensions exceed the layout limit",
                    span,
                    target=target,
                )
            )
            continue
        selected.append((binding, nodes, span))

    bound_ids = {n.node_id for _, nodes, _ in selected for n in nodes}
    body = replace(document, nodes=tuple(n for n in document.nodes if n.node_id not in bound_ids))
    fixed_references = tuple(
        sorted(
            (
                n
                for _, nodes, _ in selected
                for root in nodes
                for n in root.walk()
                if n.kind == "footnote_reference"
            ),
            key=lambda n: n.span.start,
        )
    )
    result = layout_markdown(
        body,
        resolver,
        page=page,
        style=style,
        flow=no_bindings,
        cancelled=cancelled,
        _fixed_references=fixed_references,
    )
    diagnostics.extend(result.diagnostics)
    point_meter = PointAccumulator(result.pages)
    pages = [
        {
            "fragments": list(p.fragments),
            "fields": BudgetedOps(point_meter),
            "body": list(p.paint_ops),
            "preview": p.preview_ops,
            "background": p.background,
            "images": list(p.images),
        }
        for p in result.pages
    ]
    expected = Counter(f.occurrence_id for f in result.fragments if not f.repeated)
    for binding, nodes, span in selected:
        scale = binding.scale
        field_style = replace(
            style, em_mm=style.em_mm * scale, line_height_mm=style.line_height_mm * scale
        )
        field_flow = replace(
            no_bindings,
            template=None,
            math=replace(flow.math, em_mm=flow.math.em_mm * scale),
            code=replace(
                flow.code,
                em_mm=flow.code.em_mm * scale,
                advance_mm=flow.code.advance_mm * scale,
                line_height_mm=flow.code.line_height_mm * scale,
            ),
        )
        field_diagnostics = []
        field_nodes = constrain_flow_breaks(
            nodes, field_diagnostics, context="fixed field", cancelled=cancelled
        )
        field_doc = replace(document, nodes=field_nodes, diagnostics=tuple(field_diagnostics))
        targets = range(len(pages)) if binding.pages == "all" else (0,)
        for index in targets:
            check_cancel(cancelled)
            target = binding_target(template, binding, page_index=index)
            face = template.face(index)
            region = next(r for r in face.reserved if r.name == binding.region)
            snapshot = layout_markdown(
                field_doc,
                resolver,
                page=PageProfile(region.width_mm, region.height_mm, 0),
                style=field_style,
                flow=field_flow,
                cancelled=cancelled,
                _references_only=True,
            )
            diagnostics.extend(with_template_target(d, target) for d in snapshot.diagnostics)
            if len(snapshot.pages) > 1:
                diagnostics.append(
                    TemplateDiagnostic(
                        "template-field-height-overflow",
                        f"Field {binding.region} needs more than its fixed region; change field size or content",
                        span,
                        target=target,
                    )
                )
            dx, dy = region.x_mm + template.offset_x_mm, region.y_mm + template.offset_y_mm
            if binding.anchor and snapshot.fragments:
                anchor = next(a for a in face.anchors if a.name == binding.anchor)
                # An anchor sets the first logical character's x and baseline.
                # Glyph side bearings remain intact; no ink-bbox fitting.
                first = snapshot.fragments[0]
                dx = anchor.x_mm + template.offset_x_mm - first.x_mm
                dy = anchor.y_mm + template.offset_y_mm - first.baseline_mm
            if index == 0:
                expected.update(f.occurrence_id for f in snapshot.fragments if not f.repeated)
            for local in snapshot.pages:
                # Overflow stays present in debug geometry and source coverage;
                # the error above blocks finished/plotter export. Never drop it.
                y_offset = dy + local.index * region.height_mm

                def moved(bounds, dx=dx, y_offset=y_offset):
                    return (
                        (bounds[0] + dx, bounds[1] + y_offset, bounds[2] + dx, bounds[3] + y_offset)
                        if bounds
                        else None
                    )

                for fragment in local.fragments:
                    placed = replace(
                        fragment,
                        fragment_id=digest([VERSION, fragment.fragment_id, index, binding.region]),
                        page_index=index,
                        x_mm=fragment.x_mm + dx,
                        baseline_mm=fragment.baseline_mm + y_offset,
                        logical_bounds=moved(fragment.logical_bounds),
                        ink_bounds=moved(fragment.ink_bounds),
                        repeated=fragment.repeated or index > 0,
                        container_id=f"template-field:{binding.region}",
                    )
                    pages[index]["fragments"].append(placed)
                for image in local.images:
                    placed_image = replace(image, bounds=moved(image.bounds))
                    pages[index]["images"].append(placed_image)
                    a, b, c, d = region.bounds
                    x, y, right, bottom = placed_image.bounds
                    if (
                        x < a + template.offset_x_mm - 1e-9
                        or y < b + template.offset_y_mm - 1e-9
                        or right > c + template.offset_x_mm + 1e-9
                        or bottom > d + template.offset_y_mm + 1e-9
                    ):
                        diagnostics.append(
                            TemplateDiagnostic(
                                "template-field-image-overflow",
                                f"Field {binding.region}: image exceeds reserved region",
                                span,
                                target=target,
                            )
                        )
                for op in local.paint_ops:
                    points = tuple((x + dx, y + y_offset) for x, y in op.points)
                    a, b, c, d = region.bounds
                    a, b, c, d = (
                        a + template.offset_x_mm,
                        b + template.offset_y_mm,
                        c + template.offset_x_mm,
                        d + template.offset_y_mm,
                    )
                    radius = op.width_mm / 2
                    if any(
                        x - radius < a - 1e-8
                        or y - radius < b - 1e-8
                        or x + radius > c + 1e-8
                        or y + radius > d + 1e-8
                        for x, y in points
                    ):
                        diagnostics.append(
                            TemplateDiagnostic(
                                "template-field-ink-overflow",
                                f"Field {binding.region}: ink exceeds the reserved region",
                                span,
                                target=target,
                            )
                        )
                    pages[index]["fields"].append(
                        replace(
                            op, points=points, execution_domain=f"template-field:{binding.region}"
                        )
                    )
    composed = []
    for index, p in enumerate(pages):
        # The existing body list begins with explicit blank-paper frame strokes.
        frame = [op for op in p["body"] if op.execution_domain == "template-frame"]
        body_ops = [op for op in p["body"] if op.execution_domain != "template-frame"]
        composed.append(
            Page(
                index,
                tuple(p["fragments"]),
                tuple(frame + p["fields"] + body_ops),
                p["preview"],
                p["background"],
                tuple(p["images"]),
            )
        )
    if (
        Counter(f.occurrence_id for p in composed for f in p.fragments if not f.repeated)
        != expected
    ):
        raise RuntimeError("Template composition lost or duplicated primary source instances")
    key = digest(
        {
            "source": document.content_key,
            # All fields have now selected their resources. A partial body's
            # snapshot key would depend on whether field choices were cached
            # before this call, breaking first-save/reopen identity.
            "body_layout": result.layout_version,
            "page": asdict(result.page_profile),
            "style": asdict(style),
            "flow": flow.layout_record(),
            "fields": VERSION,
            "diagnostic_targets": "v1",
            "resources": resolver.resource_key,
            "selections": resolver.selection_records(),
        }
    )
    return replace(
        result,
        snapshot_id=key,
        job_key=key,
        pages=tuple(composed),
        diagnostics=tuple(dict.fromkeys(diagnostics)),
        layout_version=f"{result.layout_version}/{VERSION}",
    )
