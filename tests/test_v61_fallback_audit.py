"""Census distinguishes missing evidence from excluded candidates; bridge keeps mapping guards."""
import copy
import sys
from pathlib import Path

import pytest
from test_component_generation import make_graph
from test_source_generation_entry import fixture

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from audit_v61_library_fallbacks import classify, identity, source_inventory
from probe_v61_fallback_cases import correspondence

from inkstruct.v6_exp import V6ExemplarIndex


def test_missing_source_self_exclusion_and_mapping_are_distinct():
    args = {'scheduled': True, 'target_reliable': True, 'raw': [], 'cross': [], 'reliable': [], 'trials': [], 'same_context': [], 'roots': []}
    assert classify(**args) == 'no_declared_identity_count_source'
    assert classify(**{**args, 'raw': [1]}) == 'only_same_character_source_excluded'
    assert classify(**{**args, 'raw': [1], 'cross': [1]}) == 'source_mapping_unreliable'
    good = {**args, 'raw': [1], 'cross': [1], 'reliable': [1]}
    assert classify(**good) == 'context_or_index_scope_restriction'
    assert classify(**{**good, 'trials': [1]}) == 'actual_placement_rejected'
    assert classify(**{**good, 'scheduled': False}) == 'target_not_scheduled_with_source'


def test_inventory_keeps_roots_but_does_not_waive_low_mapping(tmp_path):
    _, repo, _, profile, _ = fixture(tmp_path)
    index = V6ExemplarIndex(profile, repo)
    inv = source_inventory(profile, index)
    assert any(e['root'] for values in inv.values() for e in values)
    sample = next(iter(profile.source_trajectories.values()))
    graph = index.graph(sample.character)
    node = next(n for n in graph.components if n.path != 'root')
    sid = node.stroke_ids[0]
    next(s for s in sample.strokes if s.standard_stroke_id == sid).confidence = .29
    inv = source_inventory(profile, index)
    entry = next(e for e in inv[identity(node)] if e['sample_id'] == sample.sample_id and e['component_id'] == node.component_id)
    assert 'stroke_mapping_confidence' in entry['mapping_errors']
    sample.strokes.reverse()
    inv = source_inventory(profile, index)
    entry = next(e for e in inv[identity(node)] if e['sample_id'] == sample.sample_id and e['component_id'] == node.component_id)
    assert 'archive_order_or_ids' in entry['mapping_errors']


def test_diagnostic_role_bridge_keeps_identity_order_and_confidence():
    target = make_graph('池', '也')
    node = next(n for n in target.components if n.canonical == '也')
    source = copy.deepcopy(target)
    sn = next(n for n in source.components if n.canonical == '也')
    sn.role = 'top'
    assert correspondence(source, sn, target, node)['max_error'] < 1e-12
    sn.confidence = .79
    with pytest.raises(ValueError, match='confidence'):
        correspondence(source, sn, target, node)
    sn.confidence = 1
    sn.glyph_variant = '他'
    with pytest.raises(ValueError, match='identity'):
        correspondence(source, sn, target, node)
    sn.glyph_variant = '也'
    source.strokes[-1], source.strokes[-2] = source.strokes[-2], source.strokes[-1]
    with pytest.raises(ValueError, match='correspondence|direction'):
        correspondence(source, sn, target, node)
