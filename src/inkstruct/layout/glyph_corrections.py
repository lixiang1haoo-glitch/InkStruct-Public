"""Apply optical transforms once, after nested pagination and field placement.

Character spacing and line breaks are deliberate invariants. Corrected ink,
hit bounds, SVG and plotter paths all share the resulting snapshot.
"""

from contextvars import ContextVar
from dataclasses import replace
from functools import wraps

from ..document.cancellation import check_cancel
from ..document.glyph_corrections import correction_for
from ..document.schema import Diagnostic

_depth = ContextVar("glyph_correction_depth", default=0)


def apply_corrections(snapshot, flow, *, cancelled=None):
    if flow is None or not flow.glyph_corrections:
        return snapshot
    pages, diagnostics = [], list(snapshot.diagnostics)
    profile = snapshot.page_profile
    margin = 0 if flow.template else profile.margin_mm
    for page in snapshot.pages:
        check_cancel(cancelled)
        changed, fragments = {}, []
        by_occurrence = {}
        for op in page.paint_ops:
            by_occurrence.setdefault(op.occurrence_id, []).append(op)
        for f in page.fragments:
            check_cancel(cancelled)
            rule = correction_for(flow.glyph_corrections, f) if f.asset_id and f.glyph_em_mm else None
            if rule is None:
                fragments.append(f)
                continue
            origin = f.x_mm + f.glyph_origin_offset_mm
            em = f.glyph_em_mm

            def point(p, r=rule, x0=origin, y0=f.baseline_mm, size=em):
                x, y = p
                return (x0 + (x - x0) * r.scale_x + r.dx_em * size,
                        y0 + (y - y0) * r.scale_y + r.dy_em * size)

            # Repeated table heads can share occurrence IDs within a page.
            # Select operations spatially by the original ink rectangle below.
            changed.setdefault(f.occurrence_id, []).append((f, point))
            ink = f.ink_bounds
            if ink:
                # Pen width stays physical; transform centreline extents below.
                ops = [o for o in by_occurrence.get(f.occurrence_id, ())
                       if all(ink[0]-1e-8 <= x <= ink[2]+1e-8 and
                               ink[1]-1e-8 <= y <= ink[3]+1e-8 for x, y in o.points)]
                points = [(point(p), o.width_mm / 2) for o in ops for p in o.points]
                if points:
                    ink = (min(p[0]-r for p, r in points), min(p[1]-r for p, r in points),
                           max(p[0]+r for p, r in points), max(p[1]+r for p, r in points))
                if (ink[0] < margin-1e-9 or ink[1] < margin-1e-9 or
                        ink[2] > profile.width_mm-margin+1e-9 or
                        ink[3] > profile.height_mm-margin+1e-9):
                    diagnostics.append(Diagnostic("glyph-correction-overflow",
                        "校正后笔迹超出页面可用区域，请减小位移或缩放", f.span))
                if flow.named_fields:
                    from ..document.template_diagnostics import TemplateDiagnostic, TemplateTarget
                    t=flow.template
                    layout=t.layout(page.index)
                    frame=next((frame for frame in layout.frames
                                if frame.region.x_mm+t.offset_x_mm-1e-8<=f.x_mm<=frame.region.bounds[2]+t.offset_x_mm+1e-8
                                and frame.region.y_mm+t.offset_y_mm-1e-8<=f.baseline_mm<=frame.region.bounds[3]+t.offset_y_mm+1e-8),None)
                    if frame:
                        a,b,c,d=frame.region.bounds
                        if (ink[0]<a+t.offset_x_mm-1e-8 or ink[1]<b+t.offset_y_mm-1e-8
                                or ink[2]>c+t.offset_x_mm+1e-8 or ink[3]>d+t.offset_y_mm+1e-8):
                            diagnostics.append(TemplateDiagnostic('template-correction-frame-overflow',
                                '校正后笔迹超出所属文本框；请调整框或校正参数。',f.span,
                                target=TemplateTarget(frame.frame_id,frame.field_id or None,layout.layout_id,page_index=page.index)))
            fragments.append(replace(f, ink_bounds=ink))
        operations = []
        for op in page.paint_ops:
            check_cancel(cancelled)
            target = next((transform for f, transform in changed.get(op.occurrence_id, ())
                           if f.ink_bounds and all(
                               f.ink_bounds[0]-1e-8 <= x <= f.ink_bounds[2]+1e-8 and
                               f.ink_bounds[1]-1e-8 <= y <= f.ink_bounds[3]+1e-8
                               for x, y in op.points)), None)
            operations.append(replace(op, points=tuple(map(target, op.points))) if target else op)
        pages.append(replace(page, fragments=tuple(fragments), paint_ops=tuple(operations)))
    return replace(snapshot, pages=tuple(pages), diagnostics=tuple(diagnostics))


def corrected_layout(function):
    @wraps(function)
    def layout(*args, **kwargs):
        depth = _depth.get()
        token = _depth.set(depth + 1)
        try:
            snapshot = function(*args, **kwargs)
        finally:
            _depth.reset(token)
        if depth:
            return snapshot
        flow = kwargs.get("flow")
        if flow is not None and flow.han_variation.enabled:
            from .han_variation import apply_variation

            snapshot = apply_variation(snapshot, args[0] if args else kwargs["document"], flow.han_variation, cancelled=kwargs.get("cancelled"))
        return apply_corrections(snapshot, flow, cancelled=kwargs.get("cancelled"))
    return layout
