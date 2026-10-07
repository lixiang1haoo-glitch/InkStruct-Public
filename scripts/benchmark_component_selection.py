"""Check full-output equivalence and paired exploratory latency on a frozen plan."""
from __future__ import annotations

import argparse
import json
import statistics
import time
from dataclasses import asdict
from pathlib import Path

from inkstruct.contextual_trajectory import choose_component
from inkstruct.fast_placement import choose_component_fast
from inkstruct.generate import DeterministicGenerator
from inkstruct.profile import load_profile
from inkstruct.samples import sha256_file
from inkstruct.structures import StructureRepository


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    plan = json.loads(args.plan.read_text())
    assert plan['field_strength'] == 0., 'fast path only supports the frozen no-field policy'
    for filename, expected in plan['code_sha256'].items():
        assert sha256_file(Path(filename)) == expected, filename
    database = Path('artifacts/structures/characters.sqlite3')
    assert sha256_file(database) == plan['structure_sha256']
    repository = StructureRepository(database)
    results = {}
    for writer, dataset in plan['datasets'].items():
        for field in ('train_profile', 'sources'):
            assert sha256_file(Path(dataset[field])) == dataset[field + '_sha256']
        sources = load_profile(Path(dataset['sources'])).source_trajectories
        generator = DeterministicGenerator(load_profile(Path(dataset['train_profile'])),
            repository.metadata()['source_version'], 'adaptive', 1.)
        cache, rows = {}, []
        for number, task in enumerate(dataset['tasks']):
            graph = repository.get(task['character'])
            start = time.perf_counter()
            base = generator.generate(graph)
            base_seconds = time.perf_counter() - start
            output, times, metadata = {}, {}, {}
            # Alternate call order to reduce simple warm-cache/order bias.
            order = ['old', 'fast'] if number % 2 == 0 else ['fast', 'old']
            for label in order:
                start = time.perf_counter()
                common = (base, graph, task['target_stroke_ids'], task['ranked_candidates'], sources)
                if label == 'old':
                    output[label], metadata[label] = choose_component(*common,
                        max_candidates=plan['max_candidates'])
                else:
                    output[label], metadata[label] = choose_component_fast(*common,
                        max_candidates=plan['max_candidates'], anchor_cache=cache)
                times[label] = time.perf_counter() - start
            assert asdict(output['old']) == asdict(output['fast']), task['id']
            assert metadata['old']['selected'] == {k: v for k, v in (metadata['fast']['selected'] or {}).items()
                                                   if k != 'decision'} or metadata['old']['selected'] is None
            rows.append({'id': task['id'], 'all_output_fields_identical': True,
                         'base_seconds': base_seconds, 'seconds': times,
                         'fully_validated_candidates': metadata['fast']['fully_validated_candidates']})
        results[writer] = {'cases': len(rows), 'all_output_fields_identical': True,
            'median_seconds': {k: statistics.median(r['seconds'][k] for r in rows) for k in ('old', 'fast')},
            'median_base_seconds': statistics.median(r['base_seconds'] for r in rows),
            'rows': rows}
    record = {'plan_sha256': sha256_file(args.plan), 'code_sha256': sha256_file(Path('src/inkstruct/fast_placement.py')),
              'timing_protocol': 'one paired pass, alternating order, persistent source-anchor cache; exploratory',
              'results': results}
    args.output.parent.mkdir(exist_ok=True, parents=True)
    with args.output.open('x') as stream:
        json.dump(record, stream, ensure_ascii=False, indent=2)
    print(json.dumps({w: {k: v for k, v in r.items() if k != 'rows'} for w, r in results.items()}, indent=2))


if __name__ == '__main__':
    main()
