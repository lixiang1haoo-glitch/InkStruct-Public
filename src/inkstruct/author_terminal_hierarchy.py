"""Back off sparse component direction evidence to similar public stroke geometry.

This only predicts ranking cues. No output stroke is independently transformed,
replaced or mixed: the caller still chooses one complete source component.
"""
from __future__ import annotations

from collections import defaultdict

import numpy as np

from .author_terminal_context import MODES, AuthorTerminalEvidence, circular_cue, complex_direction
from .geometry import path_length, resample


def stroke_geometry_key(stroke):
    # The current public database has no populated stroke_type labels. Use its
    # existing geometric signature; do not claim semantic calligraphic types.
    signature = stroke.signature
    return signature.hook, min(signature.turns, 3), signature.aspect


def normalized_stroke(points):
    sampled = np.asarray(resample(points, 16))
    span = float(np.ptp(sampled, axis=0).max())
    if span < 1e-8 or not np.isfinite(sampled).all():
        raise ValueError('invalid public stroke geometry')
    return (sampled-(sampled.min(0)+sampled.max(0))/2)/span


class HierarchicalAuthorTerminalEvidence(AuthorTerminalEvidence):
    def __init__(self, index):
        super().__init__(index)
        self.stroke_entries = defaultdict(list)
        allowed = {c['character'] for candidates in index.by_key.values() for c in candidates}
        for sample in index.sources.values():
            # Respect the index's explicitly allowed training-character set.
            if sample.character not in allowed:
                continue
            graph = index.graph(sample.character)
            mapping = {s.standard_stroke_id: s for s in sample.strokes}
            for stroke in graph.strokes:
                raw = mapping[stroke.stroke_id]
                if raw.confidence < .55 or path_length(raw.points) <= 1e-8:
                    continue
                try:
                    descriptor = normalized_stroke(stroke.median)
                except ValueError:
                    continue
                self.stroke_entries[stroke_geometry_key(stroke)].append({
                    'character': sample.character, 'sample_id': sample.sample_id,
                    'source_sha256': sample.source_sha256, 'stroke_id': stroke.stroke_id,
                    'descriptor': descriptor, 'raw': raw.points, 'public': stroke.median})

    def predict(self, graph, component, target_curves, excluded_character):
        cues, detail = super().predict(graph, component, target_curves, excluded_character)
        excluded = {graph.character, excluded_character}
        targets = [s for s in graph.strokes if s.stroke_id in component.stroke_ids]
        detail['stroke_backoff'] = []
        for i, (stroke, target_curve) in enumerate(zip(targets, target_curves, strict=True)):
            if all(cues[mode][i] is not None for mode in MODES):
                detail['stroke_backoff'].append({'used': False, 'reason': 'component evidence available'})
                continue
            descriptor = normalized_stroke(stroke.median)
            groups = defaultdict(list)
            for entry in self.stroke_entries[stroke_geometry_key(stroke)]:
                if entry['character'] in excluded:
                    continue
                distance = float(np.linalg.norm(entry['descriptor']-descriptor, axis=1).mean())
                if distance <= .20:
                    groups[entry['character']].append((distance, entry))
            ranked = sorted(groups, key=lambda c: (min(d for d, _ in groups[c]), c))[:8]
            fraction = min(.15, .02/max(path_length(target_curve), 1e-9))
            target_public = complex_direction(stroke.median, fraction*path_length(stroke.median))
            observations = {mode: defaultdict(list) for mode in MODES}
            sources = []
            for character in ranked:
                # Choose one homologous public stroke per reference character,
                # retain its repeated captures with equal within-character weight.
                sid = min(groups[character], key=lambda item: (item[0], item[1]['stroke_id']))[1]['stroke_id']
                for distance, entry in groups[character]:
                    if entry['stroke_id'] != sid:
                        continue
                    raw = complex_direction(entry['raw'], fraction*path_length(entry['raw']))
                    public = complex_direction(entry['public'], fraction*path_length(entry['public']))
                    sources.append({k: entry[k] for k in ('character', 'sample_id', 'source_sha256', 'stroke_id')} |
                                   {'public_shape_distance': distance})
                    if raw is not None:
                        observations['author'][character].append(raw)
                    if raw is not None and public is not None and target_public is not None:
                        observations['public_residual'][character].append(raw*public.conjugate()*target_public)
            applied = []
            for mode in MODES:
                if cues[mode][i] is None:
                    cues[mode][i] = circular_cue(observations[mode])
                    if cues[mode][i] is not None:
                        applied.append(mode)
            detail['stroke_backoff'].append({'used': bool(applied), 'applied_modes': applied,
                'key': stroke_geometry_key(stroke), 'reference_characters': ranked,
                'used_sources': sources, 'fractional_window': fraction})
        detail['hierarchy'] = 'component then geometric stroke signature; direction cues only'
        return cues, detail
