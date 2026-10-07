from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

from test_source_generation_entry import fixture

from inkstruct.author_terminal_hierarchy import (
    HierarchicalAuthorTerminalEvidence,
    stroke_geometry_key,
)
from inkstruct.exemplar_index import component_key, ordered_ids


def test_stroke_backoff_uses_independent_characters_without_mixing_output(tmp_path):
    graphs, _, baseline, profile, _ = fixture(tmp_path)
    target, donor_graph = graphs['池'], graphs['沱']
    component = next(c for c in target.components if c.path == 'root.0')
    donor_component = next(c for c in donor_graph.components if c.path == 'root.0')
    chars = '池沱江河海湖洋流清'
    copies = {c: replace(donor_graph, character=c) for c in chars}
    sources = {c: replace(deepcopy(profile.source_trajectories['沱']), sample_id=c, character=c) for c in chars}
    entries = [{'character': c, 'sample_id': c, 'stroke_ids': ordered_ids(donor_graph, donor_component),
                'component_id': donor_component.component_id, 'source_sha256': sources[c].source_sha256} for c in chars]
    # Same component context has only the donor; others are deliberately under
    # another context, making component-only evidence unavailable.
    index = SimpleNamespace(by_key={component_key(target, component): entries[:2], 'other': entries[2:]},
                            sources=sources, graph=lambda c: copies[c])
    evidence = HierarchicalAuthorTerminalEvidence(index)
    base = baseline.generate(target)
    curves = [[(p.x, p.y) for p in s.points] for s in base.strokes[:3]]
    cues, detail = evidence.predict(target, component, curves, '沱')
    assert len(detail['ranked_reference_characters']) == 0
    assert any(c is not None for c in cues['author'])
    used = [s for d in detail['stroke_backoff'] for s in d.get('used_sources', [])]
    assert used and all(s['character'] not in {'池', '沱'} for s in used)
    for entries in evidence.stroke_entries.values():
        for entry in entries:
            if entry['character'] in {'池', '沱'}:
                entry['raw'] = [(float('nan'), float('nan'))]
    changed, _ = evidence.predict(target, component, curves, '沱')
    assert changed == cues
    assert stroke_geometry_key(target.strokes[0]) == stroke_geometry_key(donor_graph.strokes[0])
