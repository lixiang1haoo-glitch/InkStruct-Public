"""Expanded all-library screening, with explicit confirmed/suspect/unassessed separation."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from run_raw_trajectory_experiment import save

from inkstruct.samples import sha256_file
from inkstruct.structure_defects import audit_mapping, audit_stroke, record_hash
from inkstruct.structures import StructureRepository


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    graphics_path = Path('third_party/makemeahanzi/graphics.txt')
    dictionary_path = Path('third_party/makemeahanzi/dictionary.txt')
    repository = StructureRepository(Path('artifacts/structures/characters.sqlite3'))
    dictionary = {r['character']: r for r in map(json.loads, dictionary_path.open())}
    code = [Path(__file__), Path('src/inkstruct/structure_defects.py'), Path('src/inkstruct/outline_median.py')]
    files = [graphics_path, dictionary_path, repository.path, Path('third_party/makemeahanzi/README.md')]
    save(args.output/'protocol.json', {'input_sha256': {str(p):sha256_file(p) for p in files},
        'code_sha256': {str(p):sha256_file(p) for p in code},
        'screening': '12 subdivisions per SVG curve, 65 arc probes plus all median vertices; outside tolerance8 font units; endpoints12; max outside20; short10 or12% diagonal; turn140deg with segments>8; coverage gap>max(70,20%diagonal)',
        'scope': 'Fixed conservative triage rules; not calibrated defect probabilities; clipping proven from raw-coordinate identity. No generation-quality tuning.'})
    counts, chars, rows, mappings = Counter(), [], [], []
    for i, line in enumerate(graphics_path.open()):
        g = json.loads(line)
        graph = repository.get(g['character'])
        mapping = audit_mapping(g, dictionary[g['character']], graph)
        mappings.append({'character':g['character'], **mapping})
        affected = False
        for j, median in enumerate(g['medians']):
            row = {'character':g['character'], 'stroke_id':f's{j+1}', 'graphics_sha256':record_hash(g),
                'outline_sha256':sha256_text(g['strokes'][j]), 'median_sha256':record_hash(median),
                **audit_stroke(g['strokes'][j], median)}
            rows.append(row)
            counts['strokes'] += 1
            for group in ('confirmed','suspected','unassessed'):
                for flag in row[group]:
                    counts[group+':'+flag.split(':')[0]] += 1
            affected |= 'import_clipping' in row['confirmed']
        if affected:
            chars.append(g['character'])
        if (i+1)%500 == 0:
            print('audited',i+1,'characters',counts['strokes'],'strokes',flush=True)
    save(args.output/'strokes.json',rows)
    save(args.output/'mapping.json',mappings)
    save(args.output/'summary.json', {'characters':len(mappings),'counts':dict(counts),'clipped_characters':chars,
        'suspect_strokes':sum(bool(r['suspected']) for r in rows),'unassessed_strokes':sum(bool(r['unassessed']) for r in rows),
        'mapping_confirmed_characters':sum(bool(r['confirmed']) for r in mappings),
        'mapping_unresolved_characters':sum(bool(r['unresolved']) for r in mappings)})
    print(dict(counts),flush=True)


def sha256_text(value):
    import hashlib
    return hashlib.sha256(value.encode()).hexdigest()


if __name__ == '__main__':
    main()
