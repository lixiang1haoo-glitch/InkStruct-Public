"""Bounded per-character generation with immutable resources and serial recovery."""
from __future__ import annotations

import gzip
import json
import multiprocessing as mp
import os
import shutil
import threading
import time
from pathlib import Path

from .generation_resources import FrozenStructureRepository, freeze_database
from .samples import sha256_file

_spawn_lock = threading.Lock()
WORKER_PRESETS = (2, 4, 8, 12, 16, 24, 32)
MAX_WORKERS = WORKER_PRESETS[-1]


def _start(process):
    # NumPy can load while spawn imports the target module, before _worker runs.
    # Apply a child-start environment only; restore the application's environment.
    keys = ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS')
    with _spawn_lock:
        before = {key: os.environ.get(key) for key in keys}
        try:
            os.environ.update({key: '1' for key in keys})
            process.start()
        finally:
            for key, value in before.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


def worker_count(count, requested='auto'):
    from .plotter.parallel import available_memory
    if requested == 'auto':
        limit = 1 if count < 128 else 4
    elif requested == 'max':
        limit = MAX_WORKERS
    elif type(requested) is int and 1 <= requested <= MAX_WORKERS:
        limit = requested
    else:
        raise ValueError(f'生成并发请选择自动、高并行或 1–{MAX_WORKERS} 个进程')
    # After resource identity reuse, ordinary short jobs rarely amortize spawn.
    if limit == 1 or count <= 1:
        return 1
    cpus = getattr(os, 'process_cpu_count', os.cpu_count)() or 1
    budget = min(count, limit, max(1, cpus - 2))
    memory = available_memory()
    if memory is not None:
        budget = min(budget, max(1, (memory - 1024 * 1024**2) // (512 * 1024**2)))
    return max(1, budget)


def _session(config, cancelled=lambda: False):
    from .generation_workflow import prepare_generation
    for name, expected in config['hashes'].items():
        if cancelled():
            raise InterruptedError('生成已取消')
        if sha256_file(Path(name)) != expected:
            raise ValueError('任务资源快照已改变，停止生成')
    base = FrozenStructureRepository(config['database'], cancelled)
    return prepare_generation(config['writer'], base, config['profile'], semantic=config['semantic'],
                              reference_paths=config['references'], cancelled=cancelled,
                              candidate_limit=config.get('candidate_limit', 1),
                              same_character=config.get('same_character', False))


def _worker(connection, config, cancel_event):
    # Spawn imports this module before loading any numerical generator code.
    for key in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
        os.environ[key] = '1'
    try:
        protocol, compute = _session(config, cancel_event.is_set)
        connection.send(('ready', protocol))
        while not cancel_event.is_set():
            if not connection.poll(.05):
                continue
            request = connection.recv()
            if request is None:
                return
            character, staging = request
            row = compute(character, staging)
            connection.send(('result', character, row))
    except (EOFError, BrokenPipeError, InterruptedError):
        pass
    except Exception as error:  # parent records transport/setup failure and rechecks serially
        try:
            connection.send(('error', f'{type(error).__name__}: {error}'))
        except (EOFError, OSError):
            pass
    finally:
        connection.close()


def verify_row(staging, writer, character, row, profile_hash, *, candidate_limit=None, connected=False,
               same_character=False):
    """Only committed rows with matching complete payloads can leave staging."""
    from .generation_workflow import read
    # In-memory tuples in provenance are JSON arrays on disk. Compare the exact
    # serialization contract, not Python-only container types.
    row = json.loads(json.dumps(row, ensure_ascii=False, allow_nan=False))
    stem = Path(staging) / writer / f'{ord(character):04X}'
    if read(stem.with_suffix('.json')) != row or row.get('character') != character or row.get('writer') != writer:
        raise ValueError('生成工作进程返回了不一致的字符记录')
    if row.get('status') == 'failed':
        if row.get('files') or not row.get('error'):
            raise ValueError('无效的生成失败记录')
        return None
    relative = str(Path(writer) / f'{ord(character):04X}.json.gz')
    path = Path(staging) / relative
    if row.get('status') not in ('complete', 'warning') or row.get('files') != {relative: sha256_file(path)}:
        raise ValueError('生成产物身份校验失败')
    payload = json.loads(gzip.decompress(path.read_bytes()))
    if (payload.get('checks') != {'protocol': [], 'source_integrity': []}
            or row.get('checks') != payload['checks']
            or payload.get('source_profile_sha256') != profile_hash
            or payload.get('glyph', {}).get('character') != character
            or row.get('stroke_sources') != payload.get('stroke_sources')
            or row.get('missing') != payload.get('missing')
            or row.get('author_only_ready') != payload.get('author_only_ready')):
        raise ValueError('生成产物协议或来源记录不一致')
    from .generation_variants import candidate_payloads
    candidate_payloads(payload, row, writer=writer, character=character, profile_hash=profile_hash,
                       limit=candidate_limit)
    if connected or "connected_candidates" in payload:
        from .v63_package import verify_connected_candidates
        verify_connected_candidates(payload, row, writer, character,
                                    candidate_limit if connected else None, same_character)
    return path


def run_generation(output, writer, characters, base, profile_record, progress, cancelled, *,
                   semantic=False, workers='auto', target_manifest=None, candidate_limit=1, _context=None,
                   timeout=300, same_character=False):
    from .generation_workflow import corrections, write
    from .generation_variants import MAX_CANDIDATES
    if type(candidate_limit) is not int or not 1 <= candidate_limit <= (MAX_CANDIDATES if semantic else 1):
        raise ValueError("无效的生成候选数量")
    characters = list(characters)
    connected = profile_record.get('connected')
    if not characters or len(set(characters)) != len(characters) or any(len(c) != 1 for c in characters):
        raise ValueError('生成目标必须是非空、去重的受支持单字符列表')
    if target_manifest is None:
        from .generation_targets import target_manifest as make_manifest
        target_manifest = make_manifest(''.join(characters), base.characters())
    from .generation_targets import validate_targets
    if target_manifest.get('source', {}).get('kind') == 'builtin-character-sets':
        from .character_sets import CharacterSets
        CharacterSets().validate(target_manifest, base.characters())
    validate_targets(target_manifest)
    if target_manifest['requested'] != characters:
        raise ValueError('任务字表与已确认目标不一致，未启动生成')
    budget = worker_count(len(characters), workers)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    execution = {'requested_workers': workers, 'workers': budget,
                 'fallback': None, 'transport': 'one character per worker; disk payload, compact pipe result',
                 'resource_policy': 'task-local SQLite backup including WAL; immutable logical rows; full logical SHA once per resource view',
                 'events': []}
    protocol = {'requested_characters': characters, 'characters': [], 'status': 'preparing',
                'target_manifest': target_manifest, 'execution': execution}
    write(output / 'protocol.json', protocol)
    write(output / 'target-manifest.json', target_manifest)
    rows = {}
    config = None
    initialized = None

    def notify(character):
        if progress:
            progress({'completed_count': sum(r['status'] != 'failed' for r in rows.values()),
                      'failed_count': sum(r['status'] == 'failed' for r in rows.values()),
                      'requested_count': len(characters), 'character': character})

    def accept(character, row, staging):
        payload = verify_row(staging, writer, character, row, profile_record['sha256'],
                             candidate_limit=candidate_limit, connected=connected is not None,
                             same_character=same_character)
        if character in rows:
            raise ValueError('同一字符重复提交')
        dest = output / writer
        dest.mkdir(exist_ok=True)
        if payload is not None:
            shutil.copyfile(payload, dest / payload.name)
            if sha256_file(dest / payload.name) != next(iter(row['files'].values())):
                raise ValueError('生成产物复制校验失败')
        write(dest / f'{ord(character):04X}.json', row)  # commit marker LAST
        rows[character] = row
        notify(character)

    def set_protocol(value):
        nonlocal initialized, protocol
        if initialized is not None and value != initialized:
            raise ValueError('工作进程生成规则或资源身份不一致')
        initialized = value
        protocol = {**value, 'requested_characters': characters, 'target_manifest': target_manifest,
                    'execution': execution, 'status': 'running'}
        write(output / 'protocol.json', protocol)

    try:
        notify('准备只读资源')
        if cancelled():
            raise InterruptedError('生成已取消')
        folder = output / 'resources'
        folder.mkdir()
        database = folder / 'characters.sqlite3'
        freeze_database(base.path, database, cancelled)
        references = corrections()
        paths = [Path(profile_record['path']), *references]
        if connected is not None:
            paths.append(Path(connected['path']))
        copied = []
        origins = {}
        for index, path in enumerate(paths):
            if cancelled():
                raise InterruptedError('生成已取消')
            before = sha256_file(path)
            dest = folder / (str(index) + '-' + path.name)
            shutil.copyfile(path, dest)
            if sha256_file(dest) != before or sha256_file(path) != before:
                raise ValueError('任务准备期间资源已改变，请重新开始')
            origins[str(path)] = before
            copied.append(dest)
        if sha256_file(copied[0]) != profile_record['sha256']:
            raise ValueError('作者档案已改变，请重新建档')
        config = {'writer': writer, 'database': str(database), 'semantic': semantic, 'candidate_limit': candidate_limit,
                  'same_character': same_character,
                  'profile': {**profile_record, 'path': str(copied[0]), 'original_path': str(paths[0])},
                  'references': [str(p) for p in copied[1:1+len(references)]],
                  'hashes': {str(p): sha256_file(p) for p in [database, *copied]}}
        if connected is not None:
            if sha256_file(copied[-1]) != connected['sha256']:
                raise ValueError('作者连笔档案已改变，请重新建档')
            config['profile']['connected'] = {**connected, 'path': str(copied[-1])}
        write(folder / 'identity.json', {'schema': 'inkstruct-generation-resources-v1',
              'origins': origins, 'snapshot_hashes': config['hashes'], 'donor_scope': 'entire verified author profile'})
        execution['resource_preparation_s'] = time.perf_counter() - started
        if execution['workers'] > 1:
            context = _context or mp.get_context('spawn')
            items = []
            event = None
            pending = iter(characters)
            try:
                event = context.Event()
                for index in range(execution['workers']):
                    if cancelled():
                        raise InterruptedError('生成已取消')
                    parent, child = context.Pipe()
                    process = context.Process(target=_worker, args=(child, config, event), daemon=True)
                    item = {'process': process, 'pipe': parent, 'child': child, 'current': None,
                            'ready': False, 'last': time.monotonic(), 'staging': str(output/'staging'/f'worker-{index}')}
                    items.append(item)
                    _start(process)
                    child.close()
                while len(rows) < len(characters):
                    if cancelled():
                        raise InterruptedError('生成已取消')
                    for item in items:
                        pipe, process = item['pipe'], item['process']
                        if pipe.poll():
                            message = pipe.recv()
                            if message[0] == 'error':
                                raise RuntimeError(message[1])
                            if message[0] == 'ready' and not item['ready']:
                                set_protocol(message[1])
                                item['ready'] = True
                            elif message[0] == 'result' and message[1] == item['current']:
                                accept(message[1], message[2], item['staging'])
                                item['current'] = None
                            else:
                                raise ValueError('无效的生成工作进程消息')
                            item['last'] = time.monotonic()
                        if not process.is_alive():
                            raise RuntimeError(f'生成工作进程退出：{process.exitcode}')
                        if time.monotonic() - item['last'] > timeout and (not item['ready'] or item['current']):
                            raise TimeoutError('生成工作进程超时')
                        if item['ready'] and item['current'] is None and not cancelled():
                            character = next(pending, None)
                            if character is not None:
                                pipe.send((character, item['staging']))
                                item['current'] = character
                                item['last'] = time.monotonic()
                    time.sleep(.02)
            except InterruptedError:
                raise
            except Exception as error:
                execution['fallback'] = f'{type(error).__name__}: {error}'
                execution['events'].append({'event': 'serial_fallback', 'committed': [c for c in characters if c in rows],
                                            'pending': [c for c in characters if c not in rows]})
            finally:
                if event is not None:
                    event.set()
                grace_deadline = time.monotonic() + .3
                for item in items:
                    process = item['process']
                    if process.pid is not None:
                        process.join(max(0, grace_deadline - time.monotonic()))
                        if process.is_alive():
                            process.terminate()
                for item in items:
                    process = item['process']
                    if process.pid is not None:
                        process.join(2)
                        process.close()
                    item['pipe'].close()
                    item['child'].close()
        remaining = [c for c in characters if c not in rows]
        if remaining and not cancelled():
            notify('准备串行计算' if not execution['fallback'] else '工作进程不可用，串行恢复')
            value, compute = _session(config, cancelled)
            set_protocol(value)
            staging = output/'staging'/'serial'
            for character in remaining:
                if cancelled():
                    break
                accept(character, compute(character, staging), staging)
    except InterruptedError:
        pass
    except Exception as error:
        # Preserve diagnostics and any committed results on setup/resource failure.
        execution['fatal_error'] = f'{type(error).__name__}: {error}'
        protocol['status'] = 'failed'
        write(output/'protocol.json', protocol)
        raise
    complete = [c for c in characters if c in rows and rows[c]['status'] != 'failed']
    failed = [{'character': c, 'reason': rows[c]['error']} for c in characters if c in rows and rows[c]['status'] == 'failed']
    status = 'cancelled' if cancelled() else 'completed_with_errors' if failed else 'completed'
    execution['total_s'] = time.perf_counter() - started
    protocol.update(characters=complete, failed=failed, pending=[c for c in characters if c not in rows], status=status)
    write(output/'protocol.json', protocol)
    result = {'completed_count': len(complete), 'completed_preview': ''.join(complete[:24]),
              'failed_count': len(failed), 'failed': failed, 'status': status,
              'warning_characters': [c for c in complete if rows[c]['warnings']],
              'method': protocol.get('method', 'v6.2 exp' if semantic else 'v6.1 exp'),
              'version': protocol.get('version'), 'execution': execution, 'pending': protocol['pending']}
    if candidate_limit > 1 or connected is not None:
        counts = [rows[c].get('total_candidate_count', rows[c].get('candidate_count', 1)) for c in complete]
        result.update(candidate_count=sum(counts), variant_character_count=sum(n > 1 for n in counts))
    write(output/'summary.json', result)
    return result
