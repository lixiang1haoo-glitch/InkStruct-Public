"""Seeded smooth Han deformation, fitted inside each existing ink envelope."""
import math
from dataclasses import replace
from hashlib import sha256
from itertools import pairwise

from ..assets.glyph_provider import is_han
from ..document.cancellation import check_cancel
from ..document.han_variation import LEGACY


def eligible_occurrences(document):
    return {o.occurrence_id for root in document.nodes for node in root.walk()
            if node.kind in {"text", "text_special", "wiki_link", "wiki_embed"}
            for o in node.occurrences if o.text and is_han(o.text[0])}


def legacy_strokes(strokes, occurrence_id, config):
    if not config.enabled or config.strength == 0 or not strokes:
        return strokes
    raw = sha256((config.schema_version + "|" + str(config.seed) + "|" + occurrence_id).encode()).digest()
    r = [int.from_bytes(raw[i:i+4], "big") / 4294967295 * 2 - 1 for i in range(0, 32, 4)]
    points = [p for stroke in strokes for p in stroke]
    x0, y0 = min(x for x, y in points), min(y for x, y in points)
    width = max(x for x, y in points) - x0
    height = max(y for x, y in points) - y0
    s = config.strength
    angle = r[0] * 0.035 * s
    c, sn = math.cos(angle), math.sin(angle)
    warped = []
    for stroke in strokes:
        result = []
        for x, y in stroke:
            u = (x-x0) / width if width else 0.5
            v = (y-y0) / height if height else 0.5
            wave = math.sin(math.pi*u) * math.sin(math.pi*v) * 0.035 * s
            a = (u-0.5)*c - (v-0.5)*sn + r[1]*(v-0.5)*0.025*s + wave*(r[2]+r[3]*(v-0.5))
            b = (u-0.5)*sn + (v-0.5)*c + wave*(r[4]+r[5]*(u-0.5))
            result.append((a, b))
        warped.append(result)
    all_points = [p for stroke in warped for p in stroke]
    lo_x, hi_x = min(p[0] for p in all_points), max(p[0] for p in all_points)
    lo_y, hi_y = min(p[1] for p in all_points), max(p[1] for p in all_points)
    margins = [0.04*s*(1+r[i])/2 for i in (4, 5, 6, 7)]

    def point(p):
        u = (p[0]-lo_x)/(hi_x-lo_x) if hi_x > lo_x else 0.5
        v = (p[1]-lo_y)/(hi_y-lo_y) if hi_y > lo_y else 0.5
        return (x0+width*(margins[0]+min(1,max(0,u))*(1-margins[0]-margins[1])),
                y0+height*(margins[2]+min(1,max(0,v))*(1-margins[2]-margins[3])))
    return tuple(tuple(point(p) for p in stroke) for stroke in warped)


TEXT_KINDS = {"text", "text_special", "wiki_link", "wiki_embed"}


def random_values(identity, seed, channel):
    raw = sha256(f"natural-v2|{seed}|{identity}|{channel}".encode()).digest()
    return tuple(int.from_bytes(raw[i:i+4], "big") / 4294967295 * 2 - 1 for i in range(0, 32, 4))


def natural_metrics(boxes, config, radius):
    """Measure spacing and reserve motion room before wrapping/pagination."""
    if (not config or not config.enabled or config.schema_version == LEGACY
            or not any((config.strength,config.size_strength,config.spacing_strength,config.baseline_strength))):
        return boxes
    result = list(boxes)
    def eligible(box):
        return (box.run.kind in TEXT_KINDS and is_han(box.run.occurrence.text)
                and box.glyph is not None and box.status == "ready")
    for i, box in enumerate(boxes):
        if not eligible(box):
            continue
        bounds = box.glyph.layout_bounds
        baseline = box.glyph.layout_metrics.baseline
        reserve = box.em * (.065*config.strength + .05*config.size_strength)
        vertical = reserve + box.em*.12*config.baseline_strength
        left = max(0, reserve-(box.origin_offset+bounds[0]*box.em-radius))
        right = max(0, reserve-(box.advance-box.origin_offset-bounds[2]*box.em-radius))
        top = max(0, vertical-(box.ascent-(baseline-bounds[1])*box.em-radius))
        bottom = max(0, vertical-(box.descent-(bounds[3]-baseline)*box.em-radius))
        result[i] = replace(box, advance=box.advance+left+right, origin_offset=box.origin_offset+left,
                            ascent=box.ascent+top, descent=box.descent+bottom)
    for i in range(len(result)-1):
        a, b = result[i:i+2]
        if not (eligible(a) and eligible(b)):
            continue
        gap = (a.advance-a.origin_offset-a.glyph.layout_bounds[2]*a.em-radius
               +b.origin_offset+b.glyph.layout_bounds[0]*b.em-radius)
        delta = random_values(a.run.occurrence.occurrence_id,config.seed,"spacing")[0]*.18*a.em*config.spacing_strength
        # Every Han boundary may become a line end. Never borrow the next
        # glyph's left bearing: wrapping would otherwise leave ink past the line.
        right_space=max(0,a.advance-a.origin_offset-a.glyph.layout_bounds[2]*a.em-radius)
        negative_room=min(right_space,max(0,gap-.025*min(a.em,b.em)))
        delta = max(delta,-negative_room)
        result[i] = replace(a, advance=a.advance+delta)
    return result


def varied_strokes(strokes, occurrence_id, config):
    if config.schema_version == LEGACY:
        return legacy_strokes(strokes, occurrence_id, config)
    if not config.enabled or not strokes or not (config.strength or config.size_strength):
        return strokes
    r = random_values(occurrence_id,config.seed,"shape")
    points = [p for stroke in strokes for p in stroke]
    x0,y0 = min(x for x,y in points),min(y for x,y in points)
    width,height = max(x for x,y in points)-x0,max(y for x,y in points)-y0
    cx,cy = x0+width/2,y0+height/2
    s = config.strength
    angle = r[0]*math.radians(6)*s
    c,sn = math.cos(angle),math.sin(angle)
    sx,sy = 1+r[1]*.16*config.size_strength,1+r[2]*.16*config.size_strength
    result=[]
    for index,stroke in enumerate(strokes):
        q = random_values(occurrence_id,config.seed,f"stroke:{index}")
        lengths=[0.0]
        for a,b in pairwise(stroke):
            lengths.append(lengths[-1]+math.hypot(b[0]-a[0],b[1]-a[1]))
        changed=[]
        for (x,y),distance in zip(stroke,lengths):
            u=(x-x0)/width if width else .5
            v=(y-y0)/height if height else .5
            # Shared smooth field moves junctions together. Per-stroke bending
            # vanishes at endpoints and uses arc length, independent of sampling density.
            t=distance/lengths[-1] if lengths[-1] else 0
            bend=math.sin(math.pi*t)
            dx=width*s*(.075*r[3]*math.sin(math.pi*v)+.04*r[4]*math.sin(2*math.pi*u)+.035*q[0]*bend)
            dy=height*s*(.075*r[5]*math.sin(math.pi*u)+.04*r[6]*math.sin(2*math.pi*v)+.035*q[1]*bend)
            a=(x-cx)*sx+dx+.08*r[7]*s*(y-cy)
            b=(y-cy)*sy+dy
            changed.append((cx+a*c-b*sn,cy+a*sn+b*c))
        result.append(tuple(changed))
    return tuple(result)


def fit_motion(original, changed, bounds, radius):
    """Limit an exceptional motion without renormalizing every glyph's shape."""
    lo_x,lo_y,hi_x,hi_y=bounds
    limits=((lo_x+radius,hi_x-radius),(lo_y+radius,hi_y-radius))
    fraction=1.0
    for before,after in zip(original,changed):
        for a,b in zip(before,after):
            for axis,(lo,hi) in enumerate(limits):
                delta=b[axis]-a[axis]
                if delta>0:fraction=min(fraction,max(0,(hi-a[axis])/delta))
                elif delta<0:fraction=min(fraction,max(0,(lo-a[axis])/delta))
    return tuple(tuple((a[0]+fraction*(b[0]-a[0]),a[1]+fraction*(b[1]-a[1]))
                       for a,b in zip(before,after)) for before,after in zip(original,changed)),fraction


def apply_variation(snapshot, document, config, *, cancelled=None):
    if (not config.enabled or (config.schema_version == LEGACY and not config.strength)
            or (config.schema_version != LEGACY and not any((config.strength,config.size_strength,config.spacing_strength,config.baseline_strength)))):
        return snapshot
    eligible = eligible_occurrences(document)
    pages = []
    for page in snapshot.pages:
        check_cancel(cancelled)
        indexed = {}
        for i, op in enumerate(page.paint_ops):
            indexed.setdefault(op.occurrence_id, []).append((i, op))
        changed, fragments = {}, []
        for fragment in page.fragments:
            check_cancel(cancelled)
            ink = fragment.ink_bounds
            if fragment.occurrence_id not in eligible or not fragment.asset_id or not ink:
                fragments.append(fragment)
                continue
            matches = [(i, op) for i, op in indexed.get(fragment.occurrence_id, ())
                       if all(ink[0]-1e-8 <= x <= ink[2]+1e-8 and ink[1]-1e-8 <= y <= ink[3]+1e-8
                              for x, y in op.points)]
            original = tuple(op.points for _, op in matches)
            strokes = varied_strokes(original, fragment.occurrence_id, config)
            shift = 0
            if config.schema_version != LEGACY and matches:
                shift = random_values(fragment.occurrence_id,config.seed,"baseline")[0]*.12*fragment.glyph_em_mm*config.baseline_strength
                strokes = tuple(tuple((x,y+shift) for x,y in stroke) for stroke in strokes)
                strokes,fraction = fit_motion(original,strokes,fragment.logical_bounds,max(op.width_mm/2 for _,op in matches))
                shift *= fraction
            points = []
            for (i, op), stroke in zip(matches, strokes):
                changed[i] = replace(op, points=stroke)
                points.extend((x, y, op.width_mm/2) for x, y in stroke)
            if points:
                ink = (min(x-r for x,y,r in points), min(y-r for x,y,r in points),
                       max(x+r for x,y,r in points), max(y+r for x,y,r in points))
            fragments.append(replace(fragment, ink_bounds=ink, baseline_mm=fragment.baseline_mm+shift))
        pages.append(replace(page, fragments=tuple(fragments),
                             paint_ops=tuple(changed.get(i, op) for i, op in enumerate(page.paint_ops))))
    return replace(snapshot, pages=tuple(pages))
