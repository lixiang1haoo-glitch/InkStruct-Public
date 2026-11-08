"""Explicit recorded-stroke derivations; original candidates remain authoritative."""
import copy
import math
import os
import tempfile
import uuid
import zipfile
from itertools import pairwise
from pathlib import Path

from .core import (
    FontPackage,
    decode,
    encoded,
    semantic_hash,
    trajectory_hashes,
    validate_candidate,
    write_archive,
)
from .parallel_verify import verify_font

POLICY = 'recorded-symbol-constructions-v1'
TARGETS = ('℃', '–', '～', '*', '∗', '∶', '∘', 'ℏ')
RECORDED_MATH_POLICY = 'recorded-math-symbols-v1'


def _bounds(strokes):
    points = [p for s in strokes for p in s['points']]
    return (min(p['x'] for p in points), min(p['y'] for p in points),
            max(p['x'] for p in points), max(p['y'] for p in points))


def constructions(records, load, *, diagnostics=None, skip_invalid=False, disabled=frozenset()):
    """Yield (trajectory, metrics, source summary, deterministic construction key)."""
    pools = {}
    for r in records:
        if r['enabled']:
            pools.setdefault(r['character'], []).append(r)

    def sources(char):
        return [r for r in pools.get(char, ()) if load(r)[2]['review_status'] != 'rejected']

    def report(target, reason, *, invalid=False):
        if diagnostics is not None:
            diagnostics.append({'target': target, 'reason': reason, 'invalid': invalid})

    def source_ref(r, indices):
        return {'candidate_id': r['candidate_id'], 'character': r['character'],
                'trajectory_hash': r['trajectory_hash'], 'stroke_orders': indices}

    def subset(r, target, indices, rule):
        t, m, summary = map(copy.deepcopy, load(r))
        t['character'] = target
        t['strokes'] = [t['strokes'][i - 1] for i in indices]
        for i, s in enumerate(t['strokes'], 1):
            s.update(order=i, stroke_ref=f'stroke-{i}')
        for part in ('author_strokes', 'reference_strokes', 'unknown_strokes'):
            summary[part] = [j for j, i in enumerate(indices, 1) if i in summary[part]]
        summary['gaps'] = [{**g, 'order': indices.index(g['order']) + 1}
                           for g in summary['gaps'] if g['order'] in indices]
        summary['author_source_status'] = ('unknown' if summary['unknown_strokes'] else
            'reference_only' if len(summary['reference_strokes']) == len(indices) else
            'partial' if summary['reference_strokes'] else 'complete')
        summary['review_status'] = 'unreviewed'
        summary['symbol_construction'] = {'policy': POLICY, 'rule': rule, 'sources': [source_ref(r, indices)]}
        summary['evidence_scope'] = 'explicit reuse/extraction of recorded ink; not an independent target recording'
        return t, m, summary

    if '–' not in pools and '–' not in disabled:
        minus = sources('−')
        if not minus:
            report('–', '缺少可用的数学减号 −')
        for r in minus:
            original = load(r)[0]
            t, m, s = subset(r, '–', list(range(1, len(original['strokes']) + 1)), 'en-dash-from-minus')
            yield t, m, s, semantic_hash(s['symbol_construction'])
    if '～' not in pools and '～' not in disabled:
        approximate = sources('≈')
        if not approximate:
            report('～', '缺少可用的双笔约等号 ≈')
        for r in approximate:
            original = load(r)[0]
            if len(original['strokes']) != 2:
                if skip_invalid:
                    report('～', '约等号 ≈ 必须恰有两笔', invalid=True)
                    continue
                raise ValueError('约等号必须恰有两笔，不能猜测拆分波浪笔画：' + r['candidate_id'])
            for order in (1, 2):
                t, m, s = subset(r, '～', [order], 'fullwidth-tilde-from-approx-stroke')
                _, b, _, d = _bounds(t['strokes'])
                # Move the extracted wave to the source mathematical axis,
                # preserving its x coordinates, shape and every dynamic value.
                axis = s.get('capture_guides', {}).get('math_axis_em', 0.38)
                dy = m['baseline'] - axis - (b + d) / 2
                for p in t['strokes'][0]['points']:
                    p['y'] += dy
                s['symbol_construction']['translation_em'] = [0, dy]
                yield t, m, s, semantic_hash(s['symbol_construction'])
    if '℃' not in pools and '℃' not in disabled:
        circles = sources('。')
        capitals = [r for r in sources('C') if r['letter_style'] == 'upright']
        if not circles:
            report('℃', '缺少可用的中文句号 。')
        if not capitals:
            report('℃', '缺少可用的英文正体 C')
        for index in range(max(len(circles), len(capitals)) if circles and capitals else 0):
            circle, capital = circles[index % len(circles)], capitals[index % len(capitals)]
            ct, _, cs = load(circle); lt, lm, ls = load(capital)
            ca, cb, cc, cd = _bounds(ct['strokes']); la, lb, lc, ld = _bounds(lt['strokes'])
            diameter = max(0.1, min(0.22, (ld - lb) * 0.25))
            if max(cc - ca, cd - cb) <= 1e-9:
                if skip_invalid:
                    report('℃', '中文句号没有可合成的空间尺寸', invalid=True)
                    continue
                raise ValueError('中文句号没有可合成的空间尺寸')
            scale = diameter / max(cc - ca, cd - cb)
            transforms = [(scale, scale, 0.04 - ca * scale, lb - cb * scale),
                          (1, 1, 0.04 + (cc - ca) * scale + 0.04 - la, 0)]
            t = {'schema_version': 'inkfont_trajectory_v1', 'character': '℃',
                 'coordinate_space': 'em-y-down-baseline-0.88', 'strokes': []}
            summary = copy.deepcopy(ls)
            summary.pop('capture_guides', None)
            summary.update(source_kind='composed', review_status='unreviewed', author_strokes=[],
                           reference_strokes=[], unknown_strokes=[], gaps=[])
            clock = 0
            for original, source_summary, transform in ((ct, cs, transforms[0]), (lt, ls, transforms[1])):
                offset = len(t['strokes'])
                times = [p['t_ms'] for st in original['strokes'] for p in st['points'] if 't_ms' in p]
                shift = clock - min(times) if times else 0
                sx, sy, dx, dy = transform
                for st in original['strokes']:
                    stroke = copy.deepcopy(st)
                    ordinal = len(t['strokes']) + 1
                    stroke.update(order=ordinal, stroke_ref=f'stroke-{ordinal}')
                    for p in stroke['points']:
                        p['x'], p['y'] = p['x'] * sx + dx, p['y'] * sy + dy
                        if 't_ms' in p:
                            p['t_ms'] += shift
                            clock = max(clock, p['t_ms'] + 1)
                    if times:
                        stroke['dynamic_origin']['time'] = 'inherited_retimed'
                    t['strokes'].append(stroke)
                for part in ('author_strokes', 'reference_strokes', 'unknown_strokes'):
                    summary[part].extend(i + offset for i in source_summary[part])
                summary['gaps'].extend({**g, 'order': g['order'] + offset} for g in source_summary['gaps'])
            n = len(t['strokes'])
            summary['author_source_status'] = ('unknown' if summary['unknown_strokes'] else
                'reference_only' if len(summary['reference_strokes']) == n else
                'partial' if summary['reference_strokes'] else 'complete')
            summary['warnings'] = list(dict.fromkeys(cs.get('warnings', []) + ls.get('warnings', [])))
            summary['symbol_construction'] = {'policy': POLICY, 'rule': 'celsius-from-ideographic-stop-and-upright-C',
                'sources': [source_ref(circle, list(range(1, len(ct['strokes']) + 1))),
                            source_ref(capital, list(range(1, len(lt['strokes']) + 1)))],
                'component_affines_em': transforms}
            summary['evidence_scope'] = 'composed recorded circle and upright C; circle scaled/raised; times explicitly retimed'
            m = {**lm, 'advance': lc + transforms[1][2] + 0.08}
            yield t, m, summary, semantic_hash(summary['symbol_construction'])

    yield from _recorded_math_constructions(records, load, diagnostics, disabled=disabled)
    if 'ℏ' not in disabled:
        yield from _recorded_hbar_constructions(records, load, diagnostics)


def _compose_recorded(target, records, affines, rule, axis, *, load, **details):
    loaded = [load(record) for record in records]
    trajectory = {'schema_version': 'inkfont_trajectory_v1', 'character': target,
                  'coordinate_space': 'em-y-down-baseline-0.88', 'strokes': []}
    summary = copy.deepcopy(loaded[0][2])
    # Capture guides/optical correction frames describe the source, not the new ink.
    summary.pop('capture_guides', None)
    summary.pop('optical_layout_frame', None)
    summary.update(source_kind='composed', review_status='unreviewed', author_strokes=[],
                   reference_strokes=[], unknown_strokes=[], gaps=[], warnings=[])
    sources, shifts = [], []
    clock = 0
    for record, (original, _, source_summary), affine in zip(records, loaded, affines, strict=True):
        offset = len(trajectory['strokes'])
        times = [p['t_ms'] for st in original['strokes'] for p in st['points'] if 't_ms' in p]
        # Single-source reuse preserves time exactly. Multi-component copies get
        # one explicit translation per component, preserving within-stroke timing.
        shift = clock - min(times) if times and len(records) > 1 else 0
        shifts.append(shift)
        xx, xy, yx, yy, dx, dy = affine
        for old in original['strokes']:
            stroke = copy.deepcopy(old)
            ordinal = len(trajectory['strokes']) + 1
            stroke.update(order=ordinal, stroke_ref=f'stroke-{ordinal}')
            for point in stroke['points']:
                x, y = point['x'], point['y']
                point['x'], point['y'] = xx*x + xy*y + dx, yx*x + yy*y + dy
                if 't_ms' in point and len(records) > 1:
                    point['t_ms'] += shift
                    clock = max(clock, point['t_ms'] + 1)
            if times and len(records) > 1:
                stroke['dynamic_origin']['time'] = 'inherited_retimed'
            trajectory['strokes'].append(stroke)
        for part in ('author_strokes', 'reference_strokes', 'unknown_strokes'):
            summary[part].extend(i + offset for i in source_summary[part])
        summary['gaps'].extend({**gap, 'order': gap['order'] + offset}
                               for gap in source_summary['gaps'])
        summary['warnings'].extend(source_summary.get('warnings', []))
        sources.append({'candidate_id': record['candidate_id'], 'character': record['character'],
                        'trajectory_hash': record['trajectory_hash'],
                        'metrics_id': record['metrics_id'], 'source_summary_hash': record['source_summary_hash'],
                        'stroke_orders': [st['order'] for st in original['strokes']],
                        'stroke_refs': [st['stroke_ref'] for st in original['strokes']]})
    count = len(trajectory['strokes'])
    summary['author_source_status'] = ('unknown' if summary['unknown_strokes'] else
        'reference_only' if len(summary['reference_strokes']) == count else
        'partial' if summary['reference_strokes'] else 'complete')
    summary['warnings'] = list(dict.fromkeys(summary['warnings']))
    construction = {'policy': RECORDED_MATH_POLICY, 'rule': rule, 'sources': sources,
                    'component_affines_em': affines, 'component_time_shifts_ms': shifts,
                    'math_axis_em': axis, **details}
    construction['construction_id'] = semantic_hash(construction)
    summary['symbol_construction'] = construction
    summary['evidence_scope'] = ('composed/reused recorded ink; not an independent target recording; '
                                 'full pressure/pen-state retained; component time translations explicit')
    _, _, c, _ = _bounds(trajectory['strokes'])
    metrics = {**loaded[0][1], 'advance': c + .08}
    yield trajectory, metrics, summary, semantic_hash([target, construction])


def _recorded_math_constructions(records, load, diagnostics, *, disabled=frozenset()):
    """Bounded, deterministic transforms of complete recorded ink, never ideal shapes.

    New rules have their own policy identity; existing v1 constructions and old
    candidate IDs are unchanged. Diagnostics describe unavailable sources without
    adding placeholder glyphs to a font.
    """
    pools = {}
    for record in records:
        if record['enabled']:
            pools.setdefault(record['character'], []).append(record)

    def report(target, reason, record=None):
        if diagnostics is not None:
            diagnostics.append({'target': target, 'reason': reason,
                                'source_candidate': record['candidate_id'] if record else None})

    def eligible(char, target, *, single=False):
        result = []
        for record in sorted(pools.get(char, ()), key=lambda r: r['candidate_id']):
            trajectory, _, summary = load(record)
            # Explicit shared punctuation retains the original recording evidence.
            if (summary.get('source_kind') != 'recorded'
                    or summary.get('review_status') == 'rejected'
                    or summary.get('protocol_status') != 'valid'):
                report(target, 'source-not-qualified-recorded-ink', record)
                continue
            a, b, c, d = _bounds(trajectory['strokes'])
            if max(c - a, d - b) <= 1e-9 or (single and len(trajectory['strokes']) != 1):
                report(target, 'degenerate-source-or-minus-not-single-stroke', record)
                continue
            if single and c - a <= 1e-9:
                report(target, 'minus-has-no-horizontal-extent', record)
                continue
            result.append(record)
        return result

    def compose(target, records, affines, rule, axis, **details):
        return _compose_recorded(target, records, affines, rule, axis, load=load, **details)

    star_targets = [target for target in ('*', '∗') if target not in pools and target not in disabled]
    if star_targets:
        target_label = '/'.join(star_targets)
        minus = eligible('−', target_label, single=True)
        if not minus:
            report(target_label, 'no-qualified-minus-source')
        for i in range(len(minus)):
            chosen = [minus[(i + j) % len(minus)] for j in range(3)]
            axis = load(chosen[0])[2].get('capture_guides', {}).get('math_axis_em', .25)
            baseline = load(chosen[0])[1]['baseline']
            # Use one common shortened extent, preserving each stroke's irregularities.
            widths = [_bounds(load(record)[0]['strokes'])[2] - _bounds(load(record)[0]['strokes'])[0]
                      for record in chosen]
            extent = min(.42, min(widths) * .65)
            affines = []
            for record, width, degrees in zip(chosen, widths, (0, 60, 120), strict=True):
                a, b, c, d = _bounds(load(record)[0]['strokes'])
                scale = extent / width
                cosine, sine = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
                xx, xy, yx, yy = scale*cosine, -scale*sine, scale*sine, scale*cosine
                cx, cy = (a + c)/2, (b + d)/2
                affines.append([xx, xy, yx, yy, .04 + extent/2 - xx*cx - xy*cy,
                                baseline - axis - yx*cx - yy*cy])
            for target in star_targets:
                yield from compose(target, chosen, affines, 'six-ray-star-from-minus', axis,
                                   angles_degrees=[0, 60, 120], shortened_extent_em=extent,
                                   axis_basis=('source-capture-guide' if 'capture_guides' in load(chosen[0])[2]
                                               else 'default-math-style'),
                                   repeated_source_count=3-len({r['candidate_id'] for r in chosen}),
                                   shared_geometry_targets=['*', '∗'])

    for target, alternatives, height in (('∶', ('：', ':'), .36), ('∘', ('。',), .18)):
        if target in pools or target in disabled:
            continue
        chosen = []
        for char in alternatives:
            chosen = eligible(char, target)
            if chosen:
                break
        if not chosen:
            report(target, 'no-qualified-recorded-source')
        for record in chosen:
            trajectory, metrics, _ = load(record)
            a, b, c, d = _bounds(trajectory['strokes'])
            axis = .25  # Existing default math axis; explicitly constructed, never a capture guide.
            scale = height / max(c-a, d-b)
            affine = [scale, 0, 0, scale, .04-a*scale,
                      metrics['baseline']-axis-(b+d)/2*scale]
            yield from compose(target, [record], [affine],
                               'ratio-from-recorded-colon' if target == '∶' else 'circ-from-ideographic-stop',
                               axis, axis_basis='default-math-style', uniform_scale=scale)



def _ink_sections_at_y(strokes, y):
    """Horizontal intersections of recorded segments, including level intervals."""
    sections = []
    for stroke in strokes:
        points = stroke['points']
        for first, last in pairwise(points):
            if not min(first['y'], last['y']) <= y <= max(first['y'], last['y']):
                continue
            dy = last['y'] - first['y']
            if abs(dy) <= 1e-12:
                sections.append((min(first['x'], last['x']), max(first['x'], last['x'])))
            else:
                x = first['x'] + (y - first['y']) / dy * (last['x'] - first['x'])
                sections.append((x, x))
    return sections


def _recorded_hbar_constructions(records, load, diagnostics=None):
    """Cross the recorded h ascender with a shortened, recorded minus stroke."""
    if any(r['enabled'] and r['character'] == 'ℏ' for r in records):
        return
    pools = {'h': [], '−': [], '-': []}
    for record in sorted(records, key=lambda r: r['candidate_id']):
        char = record['character']
        if not record['enabled'] or char not in pools:
            continue
        trajectory, _, summary = load(record)
        if (summary.get('source_kind') != 'recorded'
                or summary.get('review_status') in {'rejected', 'needs_review'}
                or summary.get('protocol_status') != 'valid'):
            continue
        a, b, c, d = _bounds(trajectory['strokes'])
        if c - a <= 1e-9 or (char == 'h' and d - b <= 1e-9):
            continue
        if char != 'h' and len(trajectory['strokes']) != 1:
            continue
        pools[char].append(record)
    minus = pools['−'] + pools['-']
    if not pools['h'] and diagnostics is not None:
        diagnostics.append({'target': 'ℏ', 'reason': '缺少可用的录制小写 h'})
    if not minus and not pools['h'] and diagnostics is not None:
        diagnostics.append({'target': 'ℏ', 'reason': 'no-qualified-minus-source'})
    for base in pools['h']:
        if not minus:
            if diagnostics is not None:
                diagnostics.append({'target': 'ℏ', 'reason': 'no-qualified-minus-source',
                                    'source_candidate': base['candidate_id']})
            continue
        # Every source pair has a stable identity: adding a specimen must never
        # invalidate a document's previously frozen construction choice.
        for bar in minus:
            ht, hm, hs = load(base)
            mt, _, _ = load(bar)
            a, b, c, d = _bounds(ht['strokes'])
            left, top, right, bottom = _bounds(mt['strokes'])
            extent = max(.24, min(.5, (c - a) * .75))
            scale_x = extent / (right - left)
            # Anchor to real h ink at the upper ascender, rather than the full
            # bounding box: a slanted stem may be well to the right of that box.
            y = b + (d - b) * .25
            sections = _ink_sections_at_y(ht['strokes'], y)
            if sections:
                crossing = min(first for first, _ in sections)
            else:
                # A disconnected recording can leave this level empty. Use its
                # nearest actual point instead of placing an unattached bar.
                point = min((p for st in ht['strokes'] for p in st['points']),
                            key=lambda p: (abs(p['y'] - y), p['x'], p['y']))
                crossing, y = point['x'], point['y']
            middle = (top + bottom) / 2
            bar_sections = _ink_sections_at_y(mt['strokes'], middle)
            preferred = left + (crossing - (a - .05)) / scale_x
            bar_crossing = min((max(first, min(last, preferred))
                                for first, last in bar_sections),
                               key=lambda x: (abs(x - preferred), x))
            # The two interpolated source points coincide after this affine map,
            # even when the recorded minus is slightly wavy. Neither source is
            # smoothed, redrawn, or assigned extra trajectory points.
            affines = [[1, 0, 0, 1, 0, 0],
                       [scale_x, 0, 0, 1, crossing - bar_crossing * scale_x, y - middle]]
            axis = hm['baseline'] - y
            # The construction axis is provenance only: hbar is an ordinary atom.
            axis = max(0, min(2, axis))
            made = _compose_recorded('ℏ', [base, bar], affines, 'hbar-from-h-and-minus',
                                     axis, load=load,
                                     base_letter_style=base.get('letter_style', 'unspecified'),
                                     bar_extent_em=extent, bar_height_fraction=.25,
                                     hbar_crossing_em=[crossing, y],
                                     minus_crossing_em=[bar_crossing, middle])
            for trajectory, metrics, summary, key in made:
                if 'optical_layout_frame' in hs:
                    # A correction's frame is a frozen layout reference. Keep h's
                    # effective baseline and bounds, adding only the new bar ink.
                    frame = copy.deepcopy(hs['optical_layout_frame'])
                    bar_bounds = _bounds(trajectory['strokes'][len(ht['strokes']):])
                    old = frame['bounds']
                    frame['bounds'] = [min(old[0], bar_bounds[0]), min(old[1], bar_bounds[1]),
                                       max(old[2], bar_bounds[2]), max(old[3], bar_bounds[3])]
                    frame['metrics']['advance'] = max(frame['metrics']['advance'], bar_bounds[2] + .08)
                    summary['optical_layout_frame'] = frame
                yield trajectory, metrics, summary, key


def extend_font(source, output, *, name, font_version='0.3', progress=lambda _: None):
    """Publish a new fully verified package without changing any old candidate."""
    output = Path(output)
    if output.exists():
        raise FileExistsError(output)
    font = FontPackage(source, verify_all=False)
    verify_font(font, progress=progress)
    index, metrics, provenance = map(copy.deepcopy, (font.index, font.metrics, font.provenance))
    manifest = {k: v for k, v in font.manifest.items() if k not in ('members', 'core_members', 'core_hash', 'content_hash')}
    manifest.update(package_id=str(uuid.uuid4()), release_id=str(uuid.uuid4()), name=name, font_version=font_version,
        derived_from_package={'package_id': font.manifest['package_id'], 'content_hash': font.manifest['content_hash']})
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as directory, zipfile.ZipFile(font.path) as z:
        members = {}
        for i, member in enumerate(font.manifest['members']):
            p = Path(directory) / str(i);p.write_bytes(font._checked(z, member));members[member] = p
        def load(r):
            cid = r['candidate_id']
            return decode(members[r['file']].read_bytes()), metrics[cid], provenance[cid]
        added, diagnostics = [], []
        for t, m, s, key in constructions(font.records, load, diagnostics=diagnostics):
            cid = str(uuid.uuid5(uuid.UUID(font.manifest['font_id']), POLICY + key))
            hashes = trajectory_hashes(t)
            record = {'candidate_id': cid, 'character': t['character'], 'file': 'glyphs/' + hashes['trajectory_hash'] + '.json',
                **hashes, 'metrics_id': semantic_hash(m), 'source_summary_hash': semantic_hash(s),
                'letter_style': s['symbol_construction'].get('base_letter_style', 'not_applicable'),
                'style_evidence': 'explicit-construction', 'enabled': True,
                'priority': int(s['symbol_construction']['rule'] == 'hbar-from-h-and-minus'
                                and s['symbol_construction']['sources'][1]['character'] == '-')}
            validate_candidate(record, t, m, s)
            index['candidates'].append(record);metrics[cid] = m;provenance[cid] = s
            members[record['file']] = encoded(t);added.append(record)
        if not added:
            raise ValueError('没有可添加的符号；缺少合格录制来源或目标字形已存在')
        index['candidates'].sort(key=lambda r: (ord(r['character']), r['letter_style'], r['priority'], r['candidate_id']))
        members.update({'index.json': encoded(index), 'metrics.json': encoded(metrics), 'provenance.json': encoded(provenance)})
        staged = Path(directory) / 'new.inkfont'
        write_archive(staged, members, manifest)
        revised = FontPackage(staged, verify_all=False);stats = verify_font(revised, progress=progress)
        if font.fingerprint != (font.path.stat().st_size, font.path.stat().st_mtime_ns):
            raise ValueError('源字体在扩展期间发生变化')
        os.link(staged, output)
    return {'font': str(output), 'statistics': stats, 'added': added, 'construction_diagnostics': diagnostics,
            'source_identity': font.identity, 'identity': revised.identity}
