"""The old combined case files must not expose target captures to inference."""
import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
runner = importlib.import_module('regress_calibrated_layout_writers')


def test_case_allowlist_is_independent_of_gold_and_target_capture_ids():
    row = {'task': {'id': 'synthetic', 'character': '池', 'target_stroke_ids': ['s1'],
                    'target_sample_id': 'gold-id', 'ranked_candidates': ['unused']},
           'variants': {'A': {'synthetic': 1}, 'D': {'synthetic': 2}},
           'provenance': {'selected': None, 'fallback_reason': 'no donor', 'candidates': []},
           'reference': ['first gold'], 'metrics': {'gold': 1}}
    clean = runner.sanitize_case(row)
    row['reference'] = ['arbitrarily different gold']
    row['metrics'] = {'gold': -100}
    row['task']['target_sample_id'] = 'different capture'
    assert runner.sanitize_case(row) == clean
    assert set(clean) == {'task', 'outputs', 'metadata'}
    assert set(clean['task']) == {'id', 'character', 'target_stroke_ids'}
    row['provenance_D'] = row.pop('provenance')
    assert runner.sanitize_case(row) == clean


def test_archive_filter_keeps_all_repeats_in_same_character_group():
    chars = [chr(i) for i in range(0x4e00, 0x4e80)]
    archive = {f'{c}-{repeat}': SimpleNamespace(character=c) for c in chars for repeat in range(3)}
    kept = runner.training_sources(archive)
    assert 0 < len(kept) < len(archive)
    for c in chars:
        retained = sum(s.character == c for s in kept.values())
        assert retained == (3 if runner.split(c) == 'train' else 0)
    assert len(archive) == 3*len(chars)
