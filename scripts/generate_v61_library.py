"""Offline four-writer full-library review of the frozen v6.1 source-topology path.

No production entry point or generator parameter is changed. Each result is
atomic, losslessly archived, provenance-bearing, and resumable under input hashes.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import subprocess
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from pathlib import Path

from run_v61_admission_exp import ROOT_CONTEXTS, stroke_payload
from run_v61_exp import check_integrity, dict_curves
from run_v61_source_topology_exp import ARCHIVES, PRIOR, REVIEW, WRITERS

from inkstruct.exemplar_index import component_key
from inkstruct.geometry import path_length
from inkstruct.profile import load_profile
from inkstruct.structure_corrections import CorrectedStructureRepository
from inkstruct.structures import StructureRepository
from inkstruct.trajectory_experiment import crossing_pairs, invariants
from inkstruct.v61_admission_exp import AdmissionProbeGenerator
from inkstruct.v61_contacts import BRUSH_WIDTH, contact_pairs

DB = Path('artifacts/full_library_20261010/inputs/characters.sqlite3')
CORRECTIONS = [Path('third_party/makemeahanzi/graphics.txt'),
               Path('third_party/makemeahanzi/dictionary.txt'),
               Path('configs/structure_overrides/unclipped_reference_v1.json')]
REGRESSION = Path('artifacts/v61_source_topology_20261013/run_v1')
SOURCES = {w: (PRIOR if w == 'user_001' else ARCHIVES / w) / 'source_archive.json' for w in WRITERS}


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()


def atomic(path, data):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_bytes(data)
    tmp.replace(path)


def dump(path, value):
    atomic(path, encoded(value))


def svg(glyph):
    paths = []
    for stroke in glyph['strokes']:
        # Display retains every vertex; exact floating point output is in JSON.gz.
        d = 'M' + ' L'.join(f'{p["x"]:.8f},{p["y"]:.8f}' for p in stroke['points'])
        kind = 'author' if 'author' in stroke.get('style_source', '') else 'reference'
        paths.append(f'<path class="{kind}" d="{d}"/>')
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="-.06 -.06 1.12 1.12">'
            '<rect x="0" y="0" width="1" height="1" fill="white" stroke="#eee" stroke-width=".002"/>'
            '<g fill="none" stroke="#17202a" stroke-width=".028" stroke-linecap="round" '
            'stroke-linejoin="round">' + ''.join(paths) + '</g></svg>').encode()


def generate(engine, char, writer, review):
    """Exact D order from run_v61_source_topology_exp, without A/B re-evaluation."""
    ctx = engine.prepare(char)
    logs = {}
    plan = ctx.baseline_plan
    if writer == 'user_001':
        _, plan, logs['accepted_probe'] = engine.probe(ctx, root_contexts=ROOT_CONTEXTS, reviews=[review])
    _, plan, logs['existing_pool'] = engine.expand(ctx, plan, existing_pool=True)
    roots = sorted({component_key(ctx.graph, n) for n in ctx.graph.components
                    if n.path != 'root' and len(n.stroke_ids) >= 2})
    glyph, plan, logs['whole_root'] = engine.expand(ctx, plan, root_contexts=roots)
    return ctx, glyph, plan, logs


def worker(writer, chars, root_string):
    root = Path(root_string)
    out = root / writer
    out.mkdir(exist_ok=True)
    base = StructureRepository(DB)
    target = CorrectedStructureRepository(base, *CORRECTIONS)
    profile = load_profile(SOURCES[writer])
    engine = AdmissionProbeGenerator(profile, base, target)
    review = json.loads(REVIEW.read_text())
    profile_hash = digest(SOURCES[writer])
    sample_chars = {s.character for s in profile.source_trajectories.values()}
    started = time.monotonic()
    counters = {'complete': 0, 'warning': 0, 'failed': 0, 'resumed': 0}
    for number, char in enumerate(chars, 1):
        stem = out / f'{ord(char):04X}'
        record_path = stem.with_suffix('.json')
        if record_path.exists():
            row = json.loads(record_path.read_text())
            if all((root / f).is_file() and digest(root / f) == h for f, h in row['files'].items()):
                counters[row['status']] += 1
                counters['resumed'] += 1
                continue
            raise RuntimeError(f'existing output corrupted: {record_path}')
        row = {'writer': writer, 'character': char, 'codepoint': f'U+{ord(char):04X}',
               'target_present_in_archive': char in sample_chars, 'same_character_reuse': False,
               'files': {}, 'warnings': []}
        try:
            ctx, glyph, plan, logs = generate(engine, char, writer, review)
            g = asdict(glyph)
            xy = dict_curves(g)
            own = {i: p.component_id for p in plan.values() for i in p.indices}
            external = lambda pairs, own=own: sorted((i + 1, j + 1) for i, j in pairs
                                            if own.get(i, f'ref:{i}') != own.get(j, f'ref:{j}'))
            checks = {'protocol': invariants(glyph, ctx.graph),
                      'degenerate_strokes': [i + 1 for i, c in enumerate(xy) if path_length(c) < .003],
                      'new_cross_component_crossings_vs_v6': external(crossing_pairs(xy) - ctx.baseline_crossings),
                      'new_cross_component_contacts_028_vs_v6': external(contact_pairs(xy) - ctx.baseline_contacts)}
            integrity = check_integrity(engine, ctx, glyph, plan)
            checks['source_integrity'] = integrity
            previous = REGRESSION / writer / 'glyphs' / f'{ord(char):04X}.json'
            if previous.exists():
                checks['regression_exact'] = stroke_payload(g) == stroke_payload(json.loads(previous.read_text())['D'])
                if not checks['regression_exact']:
                    row['warnings'].append('regression output drift')
            row['warnings'] += [k for k, v in checks.items() if k not in ('source_integrity', 'regression_exact') and v]
            row.update(status='warning' if row['warnings'] else 'complete',
                       strokes=len(glyph.strokes), source_strokes=integrity['source_strokes'],
                       reference_strokes=integrity['reference_strokes'],
                       source_components=len(plan),
                       donors=[{'component': p.component_id, 'character': p.candidate['character'],
                                'sample_id': p.candidate['sample_id'], 'orders': [i + 1 for i in p.indices]}
                               for p in plan.values()], checks=checks)
            payload = {'glyph': g, 'provenance': [asdict(p) for p in plan.values()],
                       'baseline_selection': ctx.baseline_meta, 'expansion': logs,
                       'checks': checks, 'same_character_reuse': False,
                       'source_profile_sha256': profile_hash}
            # All source coordinates, pressures, times and rejected attempts remain lossless.
            raw = stem.with_suffix('.json.gz')
            atomic(raw, gzip.compress(encoded(payload), mtime=0))
            picture = stem.with_suffix('.svg')
            atomic(picture, svg(g))
            for path in (raw, picture):
                row['files'][str(path.relative_to(root))] = digest(path)
        except Exception as exc:  # noqa: BLE001 -- isolate each glyph, preserve traceback
            row.update(status='failed', error=f'{type(exc).__name__}: {exc}', traceback=traceback.format_exc())
        dump(record_path, row)
        counters[row['status']] += 1
        if number % 100 == 0 or number == len(chars):
            progress = {'writer': writer, 'processed': number, 'total': len(chars), **counters,
                        'elapsed_seconds': round(time.monotonic() - started, 1)}
            dump(out / 'progress.json', progress)
            print(json.dumps(progress), flush=True)
        # Bound the correction cache for full-library runs; no geometric change.
        if number % 500 == 0:
            target._cache.clear()
    return {'writer': writer, 'samples': len(profile.source_trajectories), **counters}


def freeze(root, chars):
    inputs = [DB, *CORRECTIONS, REVIEW, *SOURCES.values(), *sorted(REGRESSION.glob('*/glyphs/*.json'))]
    code = {Path(__file__).resolve(), Path('scripts/report_v61_library.py').resolve()}
    code.update(Path(m.__file__).resolve() for name, m in sys.modules.items()
                if name.startswith(('inkstruct.', 'run_v6'))
                and getattr(m, '__file__', '').endswith('.py'))
    return {'name': 'v6.1 exp full-library visual review', 'characters': chars, 'writers': list(WRITERS),
            'baseline_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
            'inputs': {str(p): digest(p) for p in inputs},
            'code': {str(p): digest(p) for p in sorted(code)},
            'pipeline': '4b067a1 D: accepted probe -> existing pool -> ordered complete roots',
            'same_character_sources_excluded': True, 'archives_rebuilt': False,
            'parameters_retuned': False, 'production_changed': False,
            'brush_width': BRUSH_WIDTH, 'evaluation': 'visual review, not an unseen validation cohort'}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--resume', action='store_true')
    p.add_argument('--characters', help='optional smoke scope, omitted for the full database')
    p.add_argument('--workers', type=int, default=4)
    args = p.parse_args()
    chars = list(dict.fromkeys(args.characters)) if args.characters else StructureRepository(DB).characters()
    manifest = freeze(args.output, chars)
    if args.resume:
        old = json.loads((args.output / 'protocol.json').read_text())
        for key in ('inputs', 'code', 'characters', 'writers', 'pipeline'):
            if old[key] != manifest[key]:
                raise ValueError(f'resume refused: changed {key}')
    else:
        args.output.mkdir(parents=True, exist_ok=False)
        dump(args.output / 'protocol.json', manifest)
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(worker, WRITERS, [chars] * len(WRITERS), [str(args.output)] * len(WRITERS)))
    for group in ('inputs', 'code'):
        for path, expected in manifest[group].items():
            if digest(Path(path)) != expected:
                raise RuntimeError(f'frozen {group} drift: {path}')
    dump(args.output / 'workers.json', results)
    from report_v61_library import report
    report(args.output, chars)


if __name__ == '__main__':
    main()
