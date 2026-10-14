"""Independent stored-output accounting and lossless archive verification."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from collections import Counter
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(root):
    protocol = json.loads((root / 'protocol.json').read_text())
    errors, records, failures, warnings = [], {}, [], []
    counts = Counter()
    for writer in protocol['writers']:
        for char in protocol['characters']:
            p = root / writer / f'{ord(char):04X}.json'
            if not p.exists():
                errors.append(f'missing record: {p}')
                continue
            record = json.loads(p.read_text())
            records[str(p.relative_to(root))] = sha(p)
            if record['writer'] != writer or record['character'] != char:
                errors.append(f'record identity mismatch: {p}')
            counts[record['status']] += 1
            for relative, expected in record['files'].items():
                file = root / relative
                if not file.exists() or sha(file) != expected:
                    errors.append(f'output hash mismatch: {relative}')
            if record['status'] == 'failed':
                failures.append({'writer': writer, 'character': char, 'error': record['error']})
                continue
            payload = json.loads(gzip.decompress(p.with_suffix('.json.gz').read_bytes()))
            glyph = payload['glyph']
            if len(glyph['strokes']) != record['strokes']:
                errors.append(f'stroke count mismatch: {p}')
            if record['source_strokes'] + record['reference_strokes'] != record['strokes']:
                errors.append(f'coverage accounting mismatch: {p}')
            if any(d['candidate']['character'] == char for d in payload['provenance']):
                errors.append(f'target source leaked: {p}')
            counts['points'] += sum(len(s['points']) for s in glyph['strokes'])
            if record['warnings']:
                warnings.append({'writer': writer, 'character': char, 'warnings': record['warnings'], 'checks': record['checks']})
    presentation_changes = {}
    for group in ('inputs', 'code'):
        for name, expected in protocol[group].items():
            actual = sha(Path(name))
            if actual != expected:
                # A reviewed gallery UI repair after generation can be recorded
                # separately; never waive drift of generator code or inputs.
                if group == 'code' and Path(name).name == 'report_v61_library.py':
                    presentation_changes[name] = {'generation_time_sha256': expected, 'current_sha256': actual}
                else:
                    errors.append(f'frozen {group} drift: {name}')
    summary = json.loads((root / 'summary.json').read_text())
    for status in ('complete', 'warning', 'failed'):
        if counts[status] != summary[status]:
            errors.append(f'summary mismatch: {status}')
    result = {'expected_outputs': len(protocol['writers']) * len(protocol['characters']),
              'record_count': len(records), 'counts': dict(counts), 'errors': errors,
              'failures': failures, 'warnings': warnings,
              'inputs_and_generator_unchanged': not any('drift' in e for e in errors),
              'post_generation_presentation_changes': presentation_changes,
              'record_sha256': records,
              'gallery_sha256': {name: sha(root / name) for name in ('index.html', 'catalog.js', 'summary.json', 'report.md')},
              'verifier_sha256': sha(Path(__file__))}
    (root / 'verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    if errors:
        raise RuntimeError(errors[:10])
    print(json.dumps({k: v for k, v in result.items() if k not in ('record_sha256', 'warnings')}, ensure_ascii=False))
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('output', type=Path)
    verify(p.parse_args().output)
