"""Bulk orchestration checks; generation geometry is covered by v6.1 tests."""
import gzip
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location('generate_v61_library', SCRIPTS / 'generate_v61_library.py')
bulk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bulk)
from report_v61_library import report


def test_pipeline_keeps_frozen_order_and_plans():
    calls = []
    ctx = SimpleNamespace(baseline_plan={'original': 1}, graph=SimpleNamespace(components=[]))

    class Engine:
        def prepare(self, char):
            assert char == '测'
            return ctx

        def probe(self, context, **kwargs):
            calls.append(('probe', kwargs))
            return None, {'probe': 2}, {}

        def expand(self, context, plan, **kwargs):
            calls.append(('expand', dict(plan), kwargs))
            return 'glyph', {**plan, str(len(calls)): True}, {}

    _, glyph, plan, _ = bulk.generate(Engine(), '测', 'user_001', {'review': 1})
    assert glyph == 'glyph'
    assert calls[1] == ('expand', {'probe': 2}, {'existing_pool': True})
    assert calls[2][1] == {'probe': 2, '2': True}
    assert calls[2][2] == {'root_contexts': []}
    assert plan['probe'] == 2


def test_svg_and_archive_keep_every_vertex(tmp_path):
    points = [{'x': .1, 'y': .2}, {'x': .10123456789, 'y': .8}, {'x': .3, 'y': .4}]
    glyph = {'strokes': [{'points': points, 'style_source': 'v61_complete_author_source'}]}
    svg = bulk.svg(glyph).decode()
    assert svg.count(' L') == 2
    assert '0.10123457,0.80000000' in svg
    raw = tmp_path / 'x.json.gz'
    bulk.atomic(raw, gzip.compress(bulk.encoded(glyph), mtime=0))
    assert json.loads(gzip.decompress(raw.read_bytes())) == glyph
    assert not list(tmp_path.glob('*.tmp'))


def test_failure_is_visible_and_resume_does_not_overwrite(monkeypatch, tmp_path):
    source = tmp_path / 'source.json'
    source.write_text('{}')
    monkeypatch.setattr(bulk, 'SOURCES', {'test': source})
    monkeypatch.setattr(bulk, 'REVIEW', source)
    monkeypatch.setattr(bulk, 'StructureRepository', lambda *_: None)
    monkeypatch.setattr(bulk, 'CorrectedStructureRepository', lambda *_: None)
    monkeypatch.setattr(bulk, 'load_profile', lambda *_: SimpleNamespace(source_trajectories={}))
    monkeypatch.setattr(bulk, 'AdmissionProbeGenerator', lambda *_: None)

    def fail(*args):
        raise ValueError('explicit unsupported structure')

    monkeypatch.setattr(bulk, 'generate', fail)
    assert bulk.worker('test', ['测'], str(tmp_path))['failed'] == 1
    path = tmp_path / 'test' / f'{ord("测"):04X}.json'
    before = path.read_bytes()
    row = json.loads(before)
    assert row['status'] == 'failed' and row['files'] == {}
    assert 'explicit unsupported structure' in row['error']
    assert bulk.worker('test', ['测'], str(tmp_path))['resumed'] == 1
    assert path.read_bytes() == before
    row['files'] = {'missing.svg': 'invalid'}
    path.write_text(json.dumps(row))
    with pytest.raises(RuntimeError, match='corrupted'):
        bulk.worker('test', ['测'], str(tmp_path))


def test_report_requires_every_record_and_displays_failures(tmp_path):
    (tmp_path / 'protocol.json').write_text('{"baseline_commit":"test"}')
    with pytest.raises(RuntimeError, match='missing completed record'):
        report(tmp_path, ['测'])
    for w in ('user_001', 'scx', 'mjb', 'wsq'):
        (tmp_path / w).mkdir(exist_ok=True)
        (tmp_path / w / f'{ord("测"):04X}.json').write_text(json.dumps({
            'writer': w, 'character': '测', 'status': 'failed', 'error': '<script>bad</script>', 'warnings': []}))
    report(tmp_path, ['测'])
    assert json.loads((tmp_path / 'summary.json').read_text())['failed'] == 4
    assert '<script>bad' not in (tmp_path / 'catalog.js').read_text()
    assert 'fetch(' not in (tmp_path / 'index.html').read_text()


def test_stored_output_verifier_detects_tampering(tmp_path):
    from verify_v61_library import verify

    writers = ['user_001', 'scx', 'mjb', 'wsq']
    (tmp_path / 'protocol.json').write_text(json.dumps({
        'baseline_commit': 'test', 'writers': writers, 'characters': ['测'], 'inputs': {}, 'code': {}}))
    for w in writers:
        folder = tmp_path / w
        folder.mkdir()
        stem = folder / f'{ord("测"):04X}'
        payload = {'glyph': {'strokes': [{'points': [{'x': .1, 'y': .2}, {'x': .2, 'y': .3}]}]}, 'provenance': []}
        raw = stem.with_suffix('.json.gz')
        raw.write_bytes(gzip.compress(bulk.encoded(payload)))
        stem.with_suffix('.json').write_text(json.dumps({
            'writer': w, 'character': '测', 'status': 'complete', 'strokes': 1,
            'source_strokes': 0, 'reference_strokes': 1, 'warnings': [],
            'files': {str(raw.relative_to(tmp_path)): bulk.digest(raw)}}))
    report(tmp_path, ['测'])
    assert verify(tmp_path)['record_count'] == 4
    raw.write_bytes(gzip.compress(bulk.encoded({**payload, 'tampered': True})))
    with pytest.raises(RuntimeError, match='output hash mismatch'):
        verify(tmp_path)


def test_gallery_uses_inline_review_form_for_embedded_browser():
    from report_v61_library import PAGE

    assert 'prompt(' not in PAGE
    assert 'id="noteForm"' in PAGE
    assert 'aria-label="问题描述"' in PAGE
    assert 'aria-label="导出的问题清单"' in PAGE
