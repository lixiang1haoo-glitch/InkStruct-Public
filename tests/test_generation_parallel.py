"""Scheduler failure tests use tiny payloads; real geometry is checked by release acceptance."""
import gzip
import json
import multiprocessing as mp
import os
import shutil
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from inkstruct.generation_parallel import run_generation, verify_row, worker_count
from inkstruct.generation_workflow import write
from inkstruct.samples import sha256_file


PROTOCOL = {'method': 'test', 'version': 'test', 'initialization_rule_log': ['setup evidence']}


def row_for(config, character, staging, *, commit=True):
    writer = config['writer']
    relative = str(Path(writer)/f'{ord(character):04X}.json.gz')
    payload = {'glyph': {'character': character}, 'checks': {'protocol': [], 'source_integrity': []},
               'source_profile_sha256': config['profile']['sha256'], 'stroke_sources': [],
               'missing': [], 'author_only_ready': True}
    path = Path(staging)/relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(json.dumps(payload).encode(), mtime=0))
    row = {'writer': writer, 'character': character, 'status': 'complete', 'warnings': [],
           'files': {relative: sha256_file(path)}, 'checks': payload['checks'], 'stroke_sources': [],
           'missing': [], 'author_only_ready': True}
    if commit:
        write(path.with_suffix('').with_suffix('.json'), row)
    return row


def child_ok(pipe, config, event):
    pipe.send(('ready', PROTOCOL))
    while not event.is_set():
        if not pipe.poll(.02):
            continue
        request = pipe.recv()
        if request is None:
            return
        character, staging = request
        pipe.send(('result', character, row_for(config, character, staging)))


def child_crash(pipe, config, event):
    pipe.send(('ready', PROTOCOL))
    while True:
        character, staging = pipe.recv()
        if character == '正':
            row_for(config, character, staging, commit=False)
            os._exit(23)
        pipe.send(('result', character, row_for(config, character, staging)))


@pytest.fixture
def tiny(tmp_path, monkeypatch):
    import inkstruct.generation_parallel as parallel
    import inkstruct.generation_workflow as workflow
    database = tmp_path/'db';database.write_bytes(b'database')
    profile = tmp_path/'profile';profile.write_bytes(b'profile')
    references = [tmp_path/f'ref-{i}' for i in range(3)]
    for p in references:
        p.write_bytes(b'reference')
    monkeypatch.setattr(workflow, 'corrections', lambda: references)
    monkeypatch.setattr(parallel, 'freeze_database', lambda src, dst, cancelled: shutil.copyfile(src, dst))
    monkeypatch.setattr(parallel, 'worker_count', lambda count, requested: requested if requested != 'auto' else 1)
    monkeypatch.setattr(parallel, '_session', lambda config, cancelled: (PROTOCOL, lambda c, s: row_for(config, c, s)))
    base = SimpleNamespace(path=database, characters=lambda: list('孔正止兄'))
    return base, {'path': str(profile), 'sha256': sha256_file(profile)}


def test_spawn_failure_serially_recovers_and_records_identity(tiny, tmp_path):
    class BrokenContext:
        def Event(self):
            raise OSError('event unavailable')
    base, profile = tiny
    result = run_generation(tmp_path/'out', 'writer', list('孔正'), base, profile, None, lambda: False,
                            workers=2, _context=BrokenContext())
    assert result['completed_count'] == 2 and 'event unavailable' in result['execution']['fallback']
    protocol = json.loads((tmp_path/'out/protocol.json').read_text('utf-8'))
    assert protocol['characters'] == list('孔正') and protocol['initialization_rule_log'] == ['setup evidence']
    assert protocol['target_manifest']['requested'] == list('孔正')


@pytest.mark.parametrize('worker', [child_ok, child_crash])
def test_spawn_results_are_ordered_and_crash_staging_never_committed(tiny, tmp_path, monkeypatch, worker):
    import inkstruct.generation_parallel as parallel
    monkeypatch.setattr(parallel, '_worker', worker)
    base, profile = tiny
    result = run_generation(tmp_path/'out', 'writer', list('孔正止兄'), base, profile, None, lambda: False, workers=2)
    protocol = json.loads((tmp_path/'out/protocol.json').read_text('utf-8'))
    assert protocol['characters'] == list('孔正止兄') and result['completed_count'] == 4
    assert bool(result['execution']['fallback']) == (worker is child_crash)
    if worker is child_crash:
        assert list((tmp_path/'out/staging').glob('worker-*/writer/6B63.json.gz'))
        assert not list((tmp_path/'out/staging').glob('worker-*/writer/6B63.json'))


def test_cancel_reaps_children_and_preserves_only_committed_rows(tiny, tmp_path, monkeypatch):
    import inkstruct.generation_parallel as parallel
    monkeypatch.setattr(parallel, '_worker', child_ok)
    base, profile = tiny
    event = threading.Event()
    before = {p.pid for p in mp.active_children()}
    result = run_generation(tmp_path/'out', 'writer', list('孔正止兄'), base, profile,
                            lambda message: event.set() if message['completed_count'] else None,
                            event.is_set, workers=2)
    assert result['status'] == 'cancelled' and result['completed_count'] + len(result['pending']) == 4
    assert {p.pid for p in mp.active_children()} == before


def test_incomplete_or_changed_payload_is_rejected(tiny, tmp_path):
    _, profile = tiny
    config = {'profile': profile, 'writer': 'writer'}
    row = row_for(config, '孔', tmp_path/'stage')
    path = verify_row(tmp_path/'stage', 'writer', '孔', row, profile['sha256'])
    path.write_bytes(b'broken')
    with pytest.raises(ValueError, match='身份'):
        verify_row(tmp_path/'stage', 'writer', '孔', row, profile['sha256'])


def test_auto_does_not_spawn_for_small_tasks_and_respects_memory(monkeypatch):
    import inkstruct.plotter.parallel as export
    assert worker_count(32, 'auto') == 1
    monkeypatch.setattr(export, 'available_memory', lambda: 1100*1024**2)
    assert worker_count(500, 4) == 1
    with pytest.raises(ValueError):
        worker_count(32, 8)


def test_child_thread_environment_is_restored_even_when_spawn_fails(monkeypatch):
    from inkstruct.generation_parallel import _start
    monkeypatch.setenv('OPENBLAS_NUM_THREADS', '7')
    monkeypatch.delenv('OMP_NUM_THREADS', raising=False)
    class BrokenStart:
        def start(self):
            assert os.environ['OPENBLAS_NUM_THREADS'] == os.environ['OMP_NUM_THREADS'] == '1'
            raise OSError('injected start failure')
    with pytest.raises(OSError):
        _start(BrokenStart())
    assert os.environ['OPENBLAS_NUM_THREADS'] == '7' and 'OMP_NUM_THREADS' not in os.environ
