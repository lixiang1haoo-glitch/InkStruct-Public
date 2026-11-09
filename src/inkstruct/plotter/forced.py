"""Explicit partial SVG export: keep valid frozen ink, omit placeholders, report gaps."""
from collections import Counter
from dataclasses import asdict

from ..document.limits import validate_snapshot
from ..scene.schema import PaintOp
from .schema import PlotPage, PlotPlan, PlotStroke


def fits_page(stroke, width, height):
    radius = 0 if stroke.execution_domain == "registration" else stroke.width_mm / 2
    return all(-1e-6 <= x-radius and -1e-6 <= y-radius
               and x+radius <= width+1e-6 and y+radius <= height+1e-6 for x, y in stroke.points)


def blocked_identity(identity, blocked):
    while True:
        if identity in blocked:
            return True
        identity, separator, _ = identity.rpartition(":")
        if not separator:
            return False


def force_plan(snapshot):
    validate_snapshot(snapshot)
    pages, omitted, images = [], [], []
    for page in snapshot.pages:
        assets = {f.occurrence_id: f.asset_id or f.source_resource_id for f in page.fragments}
        blocked = {f.occurrence_id for f in page.fragments
                   if f.status in {"missing", "failed", "unsupported", "image-reference", "image-missing"}}
        for image in page.images:
            blocked.add(image.occurrence_id)
            images.append({"page_index": page.index, "source": image.source,
                           "occurrence_id": image.occurrence_id, "span": asdict(image.span)})
        strokes, counts = [], Counter()
        for op in page.paint_ops:
            identity = getattr(op, "occurrence_id", "unknown")
            ordinal = counts[identity]
            counts[identity] += 1
            reason = ""
            stroke = None
            if type(op) is not PaintOp:
                reason = "unsupported-operation"
            elif blocked_identity(identity, blocked):
                reason = "missing-or-error-placeholder"
            elif op.color.lower() not in {"#111827", "#000000", "#000", "black"}:
                reason = "non-ink-or-unsupported-colour"
            else:
                try:
                    asset = assets.get(identity)
                    stroke = PlotStroke(f"page:{page.index}:{identity}:stroke:{ordinal}", op.points,
                                        op.width_mm, identity, f"{asset}:stroke:{ordinal}" if asset else None,
                                        op.execution_domain)
                    if not fits_page(stroke, snapshot.page_profile.width_mm, snapshot.page_profile.height_mm):
                        reason = "stroke-outside-physical-page"
                except (ValueError, TypeError) as error:
                    reason = str(error)
            if reason:
                omitted.append({"page_index": page.index, "occurrence_id": identity,
                                "stroke_ordinal": ordinal, "reason": reason})
            else:
                strokes.append(stroke)
        pages.append(PlotPage(page.index, snapshot.page_profile.width_mm, snapshot.page_profile.height_mm, tuple(strokes)))
    scope = {"forced": True, "complete_document": False, "kind": "forced-svg-export",
             "policy": "valid-frozen-ink-only; leave-missing-blank; no-reflow-no-clipping",
             "diagnostics": [asdict(d) for d in snapshot.diagnostics],
             "omitted_strokes": omitted, "omitted_images": images,
             "notice": "仅导出当前快照中可用的笔迹。缺字、错误占位和无效或越出纸张的笔画留空；未排出的内容未补排。"}
    return PlotPlan(snapshot.document_id, snapshot.snapshot_id, tuple(pages)), scope
