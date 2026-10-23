"""Reproduce the seven documented issue groups without changing legacy outputs."""
from __future__ import annotations

import argparse
from dataclasses import asdict
from pathlib import Path

from run_raw_trajectory_experiment import save

from inkstruct.generate import DeterministicGenerator
from inkstruct.geometry_audit import audit_glyph
from inkstruct.profile import load_profile
from inkstruct.samples import sha256_file
from inkstruct.structures import StructureRepository


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    database = Path('artifacts/structures/characters.sqlite3')
    repository = StructureRepository(database)
    results = {}
    for writer in ('scx', 'mjb'):
        path = Path(f'profiles/{writer}/profile.json')
        generator = DeterministicGenerator(load_profile(path), repository.metadata()['source_version'], 'adaptive', 1.)
        records = []
        for character in '丢侈乌岛尴徹徼徽黧勾匈囊劓':
            graph = repository.get(character)
            glyph = generator.generate(graph)
            record = {'writer': writer, 'character': character, 'audit': audit_glyph(glyph, graph),
                      'mean_confidence': glyph.confidence, 'profile_sha256': sha256_file(path)}
            records.append(record)
            save(args.output / writer / f'U+{ord(character):04X}.json',
                 {**record, 'glyph': asdict(glyph), 'standard': asdict(graph)})
        results[writer] = records
    save(args.output / 'summary.json', results)
    for writer, records in results.items():
        for r in records:
            a = r['audit']
            print(writer, r['character'], 'mean/min', r['mean_confidence'], a['min_stroke_confidence'],
                  'warnings', [(x['kind'], x.get('stroke_ids', x.get('stroke_id'))) for x in a['geometry_warnings']],
                  'structure', a['structure_warnings'])


if __name__ == '__main__':
    main()
