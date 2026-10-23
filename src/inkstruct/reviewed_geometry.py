"""Explicit, provenance-locked repairs; authored source strokes are never edited."""
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from .geometry import bbox, path_length
from .geometry_audit import audit_glyph
from .outline_median import apply_reviewed_override
from .samples import sha256_file
from .structures import graph_from_records
from .topology_repair import glyph_curves, repair_reviewed_crossings
from .trajectory_experiment import assemble, crossing_pairs, invariants

REVIEWED_POLICY = 'reviewed_local_geometry_v1'


def geometry_identity(glyph):
    return hashlib.sha256(json.dumps(glyph_curves(glyph), separators=(',', ':')).encode()).hexdigest()


class ReviewedGeometryProcessor:
    def __init__(self, baseline, repository, config_path, graphics_path, dictionary_path):
        self.baseline, self.repository = baseline, repository
        self.config = json.loads(Path(config_path).read_text(encoding='utf-8'))
        if self.config['policy'] != REVIEWED_POLICY:
            raise ValueError('unsupported reviewed geometry policy')
        self.identity = {'policy': REVIEWED_POLICY, 'config_sha256': sha256_file(Path(config_path)),
            'graphics_sha256': sha256_file(Path(graphics_path)), 'dictionary_sha256': sha256_file(Path(dictionary_path)),
            'implementation_sha256': {name: sha256_file(Path(__file__).with_name(name+'.py'))
                for name in ('reviewed_geometry', 'topology_repair', 'outline_median', 'trajectory_experiment', 'generate')}}
        targets = {r['character'] for r in self.config['outlines']}
        def records(path):
            found = {}
            with Path(path).open(encoding='utf-8') as stream:
                for line in stream:
                    record = json.loads(line)
                    if record['character'] in targets:
                        found[record['character']] = record
            return found
        graphics, dictionary = records(graphics_path), records(dictionary_path)
        self.overrides = {}
        # Validate every configured public record before any run is written.
        for config in self.config['outlines']:
            character = config['character']
            original = repository.get(character)
            expected = graph_from_records(graphics[character], dictionary[character],
                simplified_characters={character} if original.locale == 'zh-Hans' else set(),
                source_version=original.source_version)
            def medians(graph):
                return [(s.stroke_id, s.order, [[float(x), float(y)] for x, y in s.median]) for s in graph.strokes]
            if medians(original) != medians(expected):
                raise ValueError('structure database centerlines differ from locked source records')
            self.overrides[character] = (*apply_reviewed_override(original,
                graphics[character], dictionary[character], config), config)

    def apply(self, base, graph):
        events, current = [], base
        if graph.character not in self.overrides and not any(
                r['character'] == graph.character and r['writer_id'] == base.writer_id
                for r in self.config['crossings']):
            return base, {'policy': REVIEWED_POLICY, 'applied': False, 'changed_geometry_ids': [],
                'events': [], 'geometry_audit': None, 'scope': 'no configured repair; output unchanged'}
        if graph.character in self.overrides:
            corrected, source_report, config = self.overrides[graph.character]
            sid = config['stroke_id']
            index = next(i for i, stroke in enumerate(base.strokes) if stroke.standard_stroke_id == sid)
            event = {'kind': 'outline_source', 'stroke_id': sid, 'applied': False, 'source': source_report}
            events.append(event)
            if str(base.strokes[index].style_source).startswith(('source-', 'observed-')):
                event['reason'] = 'captured source stroke protected'
            else:
                # Generate with the corrected public graph, then take only the
                # reviewed stroke. All other generated geometry stays untouched.
                proposal = self.baseline.generate(corrected)
                candidate = proposal.strokes[index]
                old_length = path_length(glyph_curves(base)[index])
                new_length = path_length(glyph_curves(proposal)[index])
                event.update(old_length=old_length, proposed_length=new_length)
                if old_length >= .1 * new_length:
                    event['reason'] = 'output is not severely collapsed; keep existing shape'
                else:
                    replacement = {'points': [(p.x, p.y) for p in candidate.points],
                                   'pressure': [p.pressure for p in candidate.points],
                                   'time': [p.t_ms for p in candidate.points]}
                    tentative = assemble(base, {index: replacement}, 'reviewed_outline')
                    initial = crossing_pairs(glyph_curves(base))
                    introduced = crossing_pairs(glyph_curves(tentative))-initial
                    pairs = [(graph.strokes[i].stroke_id, graph.strokes[j].stroke_id) for i, j in sorted(introduced)]
                    try:
                        guarded, guard = repair_reviewed_crossings(tentative, corrected, pairs,
                            movable_stroke_ids={sid}, **self.config['translation_parameters'])
                    except ValueError as error:
                        guarded = tentative
                        guard = {'applied': False, 'reason': f'incompatible correction geometry: {error}'}
                    event['guard'] = guard
                    if invariants(guarded, graph) or crossing_pairs(glyph_curves(guarded))-initial:
                        event['reason'] = 'outline proposal introduces unresolved geometry conflicts'
                    else:
                        current = guarded
                        current.strokes[index].style_source = 'reviewed-outline-estimate'
                        event.update(applied=True, reason=None, output_length=path_length(glyph_curves(current)[index]))
        for reviewed in self.config['crossings']:
            if reviewed['character'] != graph.character or reviewed['writer_id'] != base.writer_id:
                continue
            event = {'kind': 'reviewed_crossing', 'reviewed_pairs': reviewed['pairs'], 'applied': False}
            events.append(event)
            protected = {s.standard_stroke_id for s in current.strokes
                         if str(s.style_source).startswith(('source-', 'observed-'))}
            if any(sid in protected for pair in reviewed['pairs'] for sid in pair):
                event['reason'] = 'captured source stroke protected'
                continue
            if graph.source_version != reviewed['source_version'] or geometry_identity(current) != reviewed['geometry_sha256']:
                event['reason'] = 'output differs from the explicitly reviewed case; no automatic correction'
                continue
            current, result = repair_reviewed_crossings(current, graph, reviewed['pairs'],
                **self.config['translation_parameters'])
            event.update(result)
        if current is not base:
            if invariants(current, graph) or crossing_pairs(glyph_curves(current))-crossing_pairs(glyph_curves(base)):
                raise RuntimeError('reviewed geometry failed final verification')
            current.generator = base.generator+'+'+REVIEWED_POLICY
            current.canvas_fit = copy.deepcopy(base.canvas_fit)
            current.canvas_fit['reviewed_geometry'] = {'policy': REVIEWED_POLICY,
                'verified_output_bbox': list(bbox([p for stroke in glyph_curves(current) for p in stroke]))}
        changed = [a.standard_stroke_id for a, b in zip(base.strokes, current.strokes, strict=True)
                   if [(p.x, p.y) for p in a.points] != [(p.x, p.y) for p in b.points]]
        return current, {'policy': REVIEWED_POLICY, 'applied': bool(changed), 'changed_geometry_ids': changed,
            'events': events, 'before_geometry_sha256': geometry_identity(base),
            'after_geometry_sha256': geometry_identity(current),
            'geometry_audit': audit_glyph(asdict(current), graph),
            'scope': 'reviewed source/geometry correction, not captured handwriting or style validation'}
