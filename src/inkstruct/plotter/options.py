"""Explicit export-only filters and physical coordinate correction."""
import math
import re
from dataclasses import dataclass, replace

from .adapters import plan_from_snapshot, reference_image_export_scope
from .schema import PlotStroke


def parse_pages(text, count):
    if not text.strip():
        return tuple(range(count))
    result = set()
    for item in re.split(r'[,，]', text.strip()):
        match = re.fullmatch(r'\s*([0-9]+)\s*(?:[-–]\s*([0-9]+)\s*)?', item)
        if not match:
            raise ValueError('页码格式无效，例如：1-3,5；留空表示全部页面')
        a, b = int(match[1]), int(match[2] or match[1])
        if not 1 <= a <= b <= count:
            raise ValueError(f'页码必须在 1–{count} 内且范围递增')
        result.update(range(a - 1, b))
    return tuple(sorted(result))


@dataclass(frozen=True)
class ExportOptions:
    pages: tuple[int, ...]
    table_contents: bool = True
    scale_x: float = 1
    scale_y: float = 1
    registration: bool = False
    force: bool = False

    def __post_init__(self):
        if (not self.pages or any(type(i) is not int or i < 0 for i in self.pages)
                or tuple(sorted(set(self.pages))) != self.pages):
            raise ValueError('导出页码必须唯一且递增')
        if any(type(v) not in (int, float) or not math.isfinite(v) or not 0.1 <= v <= 10
               for v in (self.scale_x, self.scale_y)):
            raise ValueError('比例校正须为 10%–1000%')
        if any(type(v) is not bool for v in (self.table_contents, self.registration, self.force)):
            raise ValueError('导出选项无效')


def content_frames(snapshot, flow, index):
    template = getattr(flow, 'template', None)
    if template:
        dx, dy = template.offset_x_mm, template.offset_y_mm
        if hasattr(template, 'layout'):
            return [(f.frame_id, tuple(v + (dx if i % 2 == 0 else dy) for i, v in enumerate(f.region.bounds)))
                    for f in template.layout(index).frames]
        face = template.face(index)
        return [(r.name, tuple(v + (dx if i % 2 == 0 else dy) for i, v in enumerate(r.bounds)))
                for r in (face.body, *face.reserved)]
    p = snapshot.page_profile
    return [('body', (p.margin_mm, p.margin_mm, p.width_mm - p.margin_mm, p.height_mm - p.margin_mm))]


def prepare_export(snapshot, document, flow, options):
    if options.pages[-1] >= len(snapshot.pages):
        raise ValueError('导出页码超出冻结快照范围')
    image_scope = reference_image_export_scope(snapshot)
    forced_scope = {}
    if options.force:
        from .forced import force_plan
        plan, forced_scope = force_plan(snapshot)
        image_scope = None
    else:
        plan = plan_from_snapshot(snapshot, omit_reference_images=bool(image_scope))
    table_owners = set()
    table_occurrences = set()
    if not options.table_contents:
        if document is None:
            raise ValueError('当前文档缺少可验证的表格语义，无法筛选表格内容')
        for root in document.nodes:
            for table in root.walk():
                if table.kind == 'table':
                    for child in table.children:
                        for n in child.walk():
                            table_owners.add(n.node_id)
                            table_occurrences.update(o.occurrence_id for o in n.occurrences)
    pages = [];omitted = [];markers = [];canvases = []
    for page in plan.pages:
        if page.index not in options.pages:
            pages.append(page)
            continue
        strokes = []
        for stroke in page.strokes:
            owner = (stroke.occurrence_id or '').split(':math-rule:')[0]
            decoration_owner = (stroke.occurrence_id or '').split(':underline:')[0].split(':strike:')[0]
            if stroke.occurrence_id in table_occurrences or owner in table_owners or decoration_owner in table_owners:
                omitted.append({'page_index': page.index, 'stroke_id': stroke.stroke_id,
                                'occurrence_id': stroke.occurrence_id, 'reason': 'table-cell-content-disabled'})
                continue
            strokes.append(stroke)
        if options.registration:
            for name, bounds in content_frames(snapshot, flow, page.index):
                a, b, c, d = bounds
                length = min(0.1, (c - a) / 2)
                for corner, points in (('top-left', ((a, b), (a + length, b))),
                                       ('bottom-right', ((c - length, d), (c, d)))):
                    identity = f'registration:{page.index}:{name}:{corner}'
                    strokes.append(PlotStroke(identity, points, 0.01, identity, execution_domain='registration'))
                    markers.append({'page_index': page.index, 'frame_id': name, 'corner': corner,
                                    'points_before_scale_mm': points,
                                    'points_mm': [(x * options.scale_x, y * options.scale_y) for x, y in points],
                                    'stroke_id': identity})
        strokes = tuple(replace(s, points=tuple((x * options.scale_x, y * options.scale_y) for x, y in s.points)) for s in strokes)
        # The original plan was strictly validated before filtering or scaling.
        # Scale the output canvas with its coordinates, retaining physical pen
        # width. PlotPage still validates the final ink against that new canvas.
        width, height = page.width_mm * options.scale_x, page.height_mm * options.scale_y
        if options.force:
            from .forced import fits_page
            kept = []
            for stroke in strokes:
                if fits_page(stroke, width, height):
                    kept.append(stroke)
                else:
                    forced_scope["omitted_strokes"].append({"page_index": page.index,
                        "occurrence_id": stroke.occurrence_id, "stroke_id": stroke.stroke_id,
                        "reason": "scaled-stroke-outside-physical-page"})
            strokes = tuple(kept)
        pages.append(replace(page, width_mm=width, height_mm=height, strokes=strokes))
        canvases.append({'page_index': page.index, 'page_number': page.index + 1,
                         'source_size_mm': [page.width_mm, page.height_mm],
                         'output_size_mm': [width, height]})
    scope = {**(image_scope or {}), 'kind': 'explicit-svg-export-selection',
             'source_snapshot_id': snapshot.snapshot_id, 'page_numbers': [i + 1 for i in options.pages],
             'table_contents': options.table_contents, 'omitted_table_strokes': omitted,
             'coordinate_scale': {'x': options.scale_x, 'y': options.scale_y, 'origin_mm': [0, 0],
                                  'canvas_policy': 'scale-with-coordinates-v1',
                                  'pen_width_unchanged': True, 'canvases': canvases},
             'registration_marks': markers}
    if image_scope:
        scope['omitted_images'] = [{**i, 'output_bounds_mm': [v * (options.scale_x if n % 2 == 0 else options.scale_y)
                                                            for n, v in enumerate(i['bounds'])]}
                                   for i in image_scope['omitted_images'] if i['page_index'] in options.pages]
    if options.force:
        scope.update(forced_scope)
        scope["omitted_strokes"] = [v for v in scope["omitted_strokes"] if v["page_index"] in options.pages]
        scope["omitted_images"] = [v for v in scope["omitted_images"] if v["page_index"] in options.pages]
        emitted = {s.stroke_id for p in pages if p.index in options.pages for s in p.strokes}
        for marker in scope["registration_marks"]:
            marker["exported"] = marker["stroke_id"] in emitted
    return replace(plan, pages=tuple(pages)), scope
