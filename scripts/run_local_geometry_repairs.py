"""Reproducible, opt-in case study for reviewed topology and source-structure defects."""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from run_raw_trajectory_experiment import save

from inkstruct.component_views import expand_views
from inkstruct.exemplar_index import ExemplarIndex, ordered_ids
from inkstruct.fast_placement import choose_component_fast
from inkstruct.generate import DeterministicGenerator
from inkstruct.geometry import path_length
from inkstruct.outline_median import apply_reviewed_override, flatten_outline
from inkstruct.profile import load_profile
from inkstruct.samples import sha256_file
from inkstruct.structures import StructureRepository
from inkstruct.topology_repair import glyph_curves, repair_reviewed_crossings
from inkstruct.trajectory_experiment import crossing_pairs, invariants

REVIEWED = {'丢': [('s1', 's2')], '侈': [('s6', 's7')]}


def source_record(path, character):
    for line in path.open():
        value = json.loads(line)
        if value['character'] == character:
            return value
    raise ValueError(f'missing upstream record {character}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    repository = StructureRepository(Path('artifacts/structures/characters.sqlite3'))
    config = json.loads(Path('configs/structure_overrides/outline_repair_v1.json').read_text())
    graphics = source_record(Path('third_party/makemeahanzi/graphics.txt'), '黧')
    dictionary = source_record(Path('third_party/makemeahanzi/dictionary.txt'), '黧')
    corrected_graph, correction = apply_reviewed_override(repository.get('黧'), graphics, dictionary, config)
    save(args.output / 'protocol.json', {'type': 'reviewed diagnostic cases, not a fresh holdout',
        'reviewed_pairs': REVIEWED, 'translation_budget': .06, 'step': .002, 'clearance': .002,
        'allowed_nested_views': ['敫', '多'], 'source_override': config,
        'input_sha256': {str(p): sha256_file(p) for p in [
            Path('artifacts/structures/characters.sqlite3'),
            Path('third_party/makemeahanzi/graphics.txt'),
            Path('third_party/makemeahanzi/dictionary.txt'),
            Path('configs/structure_overrides/outline_repair_v1.json')]},
        'runner_sha256': sha256_file(Path(__file__)),
        'code_sha256': {p: sha256_file(Path(p)) for p in [
            'src/inkstruct/topology_repair.py', 'src/inkstruct/component_views.py',
            'src/inkstruct/outline_median.py', 'src/inkstruct/fast_placement.py',
            'src/inkstruct/exemplar_index.py']}})
    save(args.output / 'outline_source.json', {'outline': flatten_outline(graphics['strokes'][0]).tolist(),
        'original_median': graphics['medians'][0],
        'proposed_normalized_median': corrected_graph.strokes[0].median, 'diagnostics': correction})
    summaries = []
    for writer in ('scx', 'mjb'):
        path = Path(f'profiles/{writer}/profile.json')
        source_path = Path(f'profiles/source_v1_20261007/{writer}/profile.json')
        profile = load_profile(path)
        index = ExemplarIndex(load_profile(source_path), repository, nested_views=True)
        generator = DeterministicGenerator(profile, repository.metadata()['source_version'], 'adaptive', 1.)
        cache = {}
        for character in '丢侈徹徼徽黧':
            graph = repository.get(character)
            before = generator.generate(graph)
            variants, provenance = {}, {}
            view = expand_views(graph, repository)
            if character in REVIEWED:
                variants['translation'], provenance['translation'] = repair_reviewed_crossings(before, graph, REVIEWED[character])
            canonical = '夕' if character == '侈' else '攵' if character in '徹徼徽' else None
            if canonical:
                components = [n for n in view.graph.components if n.canonical == canonical and not n.children_ids]
                chosen_component = components[-1] if components else None
                trials, attempts = [], []
                if chosen_component:
                    for donor in index.candidates(view.graph, chosen_component)[:16]:
                        glyph, metadata = choose_component_fast(before, graph, ordered_ids(view.graph, chosen_component),
                            [donor], index.sources, anchor_cache=cache)
                        attempts.append(metadata)
                        if metadata['fallback_reason']:
                            continue
                        pairs = crossing_pairs(glyph_curves(glyph))
                        if character == '侈' and (5, 6) in pairs:
                            metadata['diagnostic_rejection'] = 'reviewed crossing s6/s7 remains'
                            continue
                        trials.append((metadata['selected']['score'], glyph, metadata))
                if trials:
                    _, variants['exemplar'], provenance['exemplar'] = min(trials, key=lambda p: p[0])
                    provenance['exemplar'] = dict(provenance['exemplar'])
                    provenance['exemplar']['target_component'] = asdict(chosen_component)
                else:
                    variants['exemplar'] = before
                    provenance['exemplar'] = {'fallback_reason': 'no compatible full-source component passes geometry constraints'}
                provenance['exemplar']['attempts'] = attempts
                provenance['exemplar']['candidate_count_checked'] = len(attempts)
            if character == '黧':
                raw_proposal = DeterministicGenerator(profile, corrected_graph.source_version, 'adaptive', 1.).generate(corrected_graph)
                variants['outline_override_raw'] = raw_proposal
                provenance['outline_override_raw'] = correction
                introduced = crossing_pairs(glyph_curves(raw_proposal)) - crossing_pairs(glyph_curves(before))
                reviewed = [(graph.strokes[i].stroke_id, graph.strokes[j].stroke_id)
                            for i, j in sorted(introduced)]
                guarded, guard_report = repair_reviewed_crossings(raw_proposal, corrected_graph,
                    reviewed, movable_stroke_ids={'s1'})
                if crossing_pairs(glyph_curves(guarded)) - crossing_pairs(glyph_curves(before)):
                    variants['outline_override'] = before
                    provenance['outline_override'] = {**correction, 'guard': guard_report,
                        'fallback_reason': 'source correction introduced unresolved crossings'}
                else:
                    variants['outline_override'] = guarded
                    provenance['outline_override'] = {**correction, 'guard': guard_report,
                        'fallback_reason': None}
            for label, after in variants.items():
                expected = corrected_graph if label.startswith('outline_override') else graph
                assert not invariants(after, expected)
                initial_crossings = crossing_pairs(glyph_curves(before))
                final_crossings = crossing_pairs(glyph_curves(after))
                if label != 'outline_override_raw':
                    assert not final_crossings - initial_crossings
                changed = [a.standard_stroke_id for a, b in zip(before.strokes, after.strokes, strict=True)
                           if [(p.x, p.y) for p in a.points] != [(p.x, p.y) for p in b.points]]
                record = {'id': f'{writer}-{ord(character):04X}-{label}', 'writer': writer,
                    'character': character, 'method': label, 'before': asdict(before), 'after': asdict(after),
                    'standard': asdict(graph), 'view_diagnostics': view.diagnostics,
                    'provenance': provenance[label], 'changed_geometry_ids': changed,
                    'profile_sha256': sha256_file(path), 'source_profile_sha256': sha256_file(source_path),
                    'new_crossings': sorted(final_crossings - initial_crossings),
                    'removed_crossings': sorted(initial_crossings - final_crossings),
                    's1_lengths': [path_length(c[0]) for c in [glyph_curves(before), glyph_curves(after)]]}
                save(args.output / 'cases' / f"{record['id']}.json", record)
                summaries.append({k: record[k] for k in ('id', 'writer', 'character', 'method',
                    'changed_geometry_ids', 'new_crossings', 'removed_crossings', 's1_lengths', 'provenance')})
                print(writer, character, label, 'changed', changed, 'removed', record['removed_crossings'],
                      'new', record['new_crossings'], flush=True)
    save(args.output / 'summary.json', summaries)


if __name__ == '__main__':
    main()
