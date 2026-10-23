"""Build a public, author-independent starter CSV from frozen v6.1 opportunities."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
from pathlib import Path

from inkstruct.positional_variants import VERSION as VARIANT_VERSION
from inkstruct.recommend import DEFAULT_COMMON_CHARACTERS, _load_common_characters
from inkstruct.reuse_rules import VERSION as RULE_VERSION
from inkstruct.structure_corrections import CorrectedStructureRepository
from inkstruct.structures import StructureRepository
from inkstruct.v61_starter_collection import (
    PARAMETERS,
    VERSION,
    coverage,
    freeze_split,
    project,
    public_view,
    select,
)

DB = Path('artifacts/full_library_20261010/inputs/characters.sqlite3')
CORRECTIONS = [Path('third_party/makemeahanzi/graphics.txt'),
               Path('third_party/makemeahanzi/dictionary.txt'),
               Path('configs/structure_overrides/unclipped_reference_v1.json')]
FIELDS = ['character', 'repeats', 'purpose', 'components', 'reason']


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def write_csv(path, rows):
    with path.open('x', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def run(output, audit):
    if output.exists() or audit.exists():
        raise ValueError('Use new output and audit directories; existing runs are immutable')
    base = StructureRepository(DB)
    corrected = CorrectedStructureRepository(base, *CORRECTIONS)
    supported = set(base.characters())
    common = [c for c in _load_common_characters() if c in supported]
    development, validation = freeze_split(common, PARAMETERS['validation_count'])
    graphs = {c: base.get(c) for c in development}
    eligible = [c for c in development if 1 <= len(graphs[c].strokes) <= PARAMETERS['max_capture_strokes']
                and not graphs[c].component_warnings]
    inputs = [DB, *CORRECTIONS, DEFAULT_COMMON_CHARACTERS]
    code = [Path(__file__).resolve().relative_to(Path.cwd()),
            *sorted(Path('src/inkstruct').glob('*.py'))]
    frozen = {'inputs': {str(p.resolve().relative_to(Path.cwd())): digest(p) for p in inputs},
              'code': {str(p): digest(p) for p in code}}
    output.mkdir(parents=True)
    audit.mkdir(parents=True)
    save(audit / 'split.json', {'development': development, 'validation': validation,
                               'all_repeats_grouped': True, 'frozen_before_ranking': True})
    sources = {c: public_view(base, c) for c in eligible}
    targets = {c: public_view(corrected, c, target=True) for c in development}
    print(f'Public planning: {len(sources)} candidates, {len(targets)} targets, {len(validation)} held out', flush=True)
    candidates, weights, _, rejected = project(sources, targets,
        progress=lambda i, n: print(f'Projected {i}/{n}', flush=True))
    selected = select(candidates, weights, max(PARAMETERS['budgets']))
    save(audit / 'selection_frozen.json', selected)  # Before any holdout geometry is evaluated.
    save(audit / 'candidate_evidence.json', candidates)
    rows = []
    explanations = []
    for item in selected:
        char = item['character']
        new = [k for k in item['new_opportunities'] if k.startswith('component/')]
        second = [k for k in item['second_donor_opportunities'] if k.startswith('component/')]
        relevant = new or second
        wanted = set(relevant)
        parts = sorted({e['canonical'] for e in candidates[char]['evidence']
                        if any(f"component/{e['target_character']}/{sid}" in wanted
                               for sid in e['target_stroke_ids'])})
        serves = sorted({k.split('/')[1] for k in relevant})
        example = '、'.join(serves[:10]) or '复杂单笔补充'
        bucket = sum(k.startswith('bucket/') for k in item['new_opportunities'])
        reason = (f"第{item['sequence']}字，{item['stroke_count']}笔；预计新增整部件来源机会{len(new)}目标笔，"
                  f"第二供体机会{len(second)}目标笔；新增单笔类别机会{bucket}目标笔；服务示例：{example}。"
                  '仅公开结构预测，实际采后须验证映射、形态与放置；不保证这些目标都能生成良好。')
        rows.append({'character': char, 'repeats': 1, 'purpose': 'v61_starter_training',
                     'components': ' '.join(parts), 'reason': reason})
        explanations.append({**item, 'components': parts, 'target_examples': serves[:10]})
    write_csv(output / 'recommended_96.csv', rows)
    for lo, hi in [(0, 32), (32, 64), (64, 96)]:
        write_csv(output / f'stage_{lo // 32 + 1}_{hi-lo}.csv', rows[lo:hi])
    write_csv(output / 'validation_16_do_not_train.csv', [
        {'character': c, 'repeats': 1, 'purpose': 'v61_validation_do_not_train', 'components': '',
         'reason': '可选的采后跨字检查；本轮规划前冻结，禁止进入本轮建档和调参；同字所有重复样本整组排除'}
        for c in validation])
    chars = [r['character'] for r in rows]
    save(output / 'split.json', {'training': chars, 'validation_do_not_train': validation,
         'note': 'CSV purpose is advisory only; archive builders must explicitly exclude all validation characters.'})
    summaries = []
    for budget in PARAMETERS['budgets']:
        stroke_budget = sum(candidates[c]['stroke_count'] for c in chars[:budget])
        equal_cost, running = [], 0
        for c in eligible:
            if running + candidates[c]['stroke_count'] > stroke_budget:
                break
            equal_cost.append(c)
            running += candidates[c]['stroke_count']
        summaries.append({'budget': budget,
            'recommended': coverage(candidates, chars[:budget], targets),
            'curated_order_baseline': coverage(candidates, eligible[:budget], targets),
            'curated_prefix_same_stroke_budget': {
                'characters': len(equal_cost), **coverage(candidates, equal_cost, targets)}})
    # Held-out public structures are inspected only after the list is frozen.
    held_targets = {c: public_view(corrected, c, target=True) for c in validation}
    held_candidates, _, _, _ = project({c: sources[c] for c in chars}, held_targets)
    held = [{'budget': b, **coverage(held_candidates, chars[:b], held_targets)} for b in PARAMETERS['budgets']]
    protocol = {'version': VERSION, 'parameters': PARAMETERS, 'split_rule': 'sha256 version + validation + character',
        'base_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
        'reuse_rules': RULE_VERSION, 'positional_variants': VARIANT_VERSION,
        'common_list_size': len(common), 'candidate_count': len(sources),
        'development_count': len(targets), 'validation_count': len(validation),
        'candidate_exclusions': {c: ('structural_warnings' if graphs[c].component_warnings else 'over_16_strokes')
                                 for c in development if c not in sources},
        'scope': 'project curated common characters, not frequency-ranked or full-library coverage',
        'assumptions': 'one natural complete recording per character; actual mapping, author variant, top-k '
            'selection, geometry, contact and placement unmeasured; no simulated author data',
        'objective': 'distinct cross-character target strokes; component weight 1, stroke bucket .2; '
            'second distinct donor gain .15; divide by sqrt(capture strokes)',
        'anisotropic_or_key_replacement_projected': False,
        'whole_character_self_reuse_in_cross_metrics': False,
        'global_minimum_guaranteed': False, 'style_quality_improvement_measured': False,
        'actual_usable_coverage': None, 'production_default_changed': False,
        'development': summaries, 'validation_public_projection_only': held,
        'rejected_pairs': rejected, **frozen}
    save(output / 'plan_summary.json', protocol)
    save(audit / 'recommendations_explained.json', explanations)
    assert len(chars) == 96 and len(set(chars)) == 96 and not set(chars) & set(validation)
    assert all(digest(Path(p)) == h for group in frozen.values() for p, h in group.items())
    for path in output.glob('*.csv'):
        with path.open(encoding='utf-8-sig', newline='') as stream:
            back = list(csv.DictReader(stream))
        assert all(len(r['character']) == 1 and r['repeats'] == '1' for r in back)
    save(audit / 'verification.json', {'csv_roundtrip': True, 'inputs_code_unchanged': True,
         'split_disjoint': True, 'output_hashes': {p.name: digest(p) for p in sorted(output.iterdir())},
         'actual_author_samples_read': 0, 'new_user_quality_validated': False})
    print(json.dumps({'characters': ''.join(chars), 'summaries': summaries, 'held': held}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--audit', type=Path, required=True)
    args = parser.parse_args()
    run(args.output, args.audit)
