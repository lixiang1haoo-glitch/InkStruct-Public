"""Recoverable retirement of saved specimens; original bytes stay in .json.bak."""
import hashlib
import json
import os
import tempfile
import uuid
from pathlib import Path


def _write(path, value):
    from handwriting_collector.paths import native_path
    fd, name = tempfile.mkstemp(dir=path.parent, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(native_path(name), native_path(path))
    finally:
        Path(name).unlink(missing_ok=True)


def sample_path(root, task, item):
    if not item.sample_id:
        raise ValueError('该份次没有已保存样本')
    uuid.UUID(item.sample_id)
    if any(c in task.writer_id for c in '/\\:') or task.writer_id in ('.', '..'):
        raise ValueError('无效书写者路径')
    from handwriting_collector.storage import sanitize_writer_id
    return Path(root)/'samples'/sanitize_writer_id(task.writer_id)/f'U+{ord(item.character):04X}'/(item.sample_id+'.json')


def read_sample(root, task, item):
    path = sample_path(root, task, item)
    raw = path.read_bytes()
    value = json.loads(raw)
    if (value.get('schema_version') not in ('inkstruct_symbol_sample_v1', 'handwriting_single_v1')
            or value.get('sample_id') != item.sample_id or value.get('character') != item.character
            or value.get('writer_id') != task.writer_id
            or value.get('task', {}).get('task_id') != task.task_id
            or value['task'].get('item_id') != item.item_id):
        raise ValueError('样本身份与任务不一致，未修改记录')
    return path, raw, value


def _revision_files(root, directory, item, record):
    """Legacy symbol journals remain readable; Han journals include export copies."""
    if 'files' not in record:
        return [(sample_path(root, item[0], item[1]), directory/(record['sample_id']+'.json.bak'), record['sha256'])]
    result = []
    for entry in record['files']:
        active = (root / entry['path']).resolve()
        backup = (directory / entry['backup']).resolve()
        if not active.is_relative_to(root.resolve()) or not backup.is_relative_to(directory.resolve()):
            raise ValueError('重录记录路径越界')
        result.append((active, backup, entry['sha256']))
    return result


def recover_revisions(root, task):
    """A crash before task commit restores old active samples, never retires them."""
    root = Path(root)
    uuid.UUID(task.task_id)
    for path in (root/'revisions').glob('*/revision.json'):
        journal = json.loads(path.read_bytes())
        if journal.get('task_id') != task.task_id:
            continue
        if journal.get('status') != 'prepared':
            continue
        if journal.get('schema_version') not in ('inkstruct_symbol_revision_v1', 'inkstruct_capture_revision_v1'):
            raise ValueError('未知重录记录版本，原文件保留')
        if journal.get('task_id') != task.task_id or journal.get('writer_id') != task.writer_id:
            raise ValueError('重录恢复记录身份不一致')
        items = {i.item_id: i for i in task.items}
        old = [items.get(record['item_id']) for record in journal['samples']]
        before = all(i and i.status == 'completed' and i.sample_id == record['sample_id']
                     for i, record in zip(old, journal['samples'], strict=True))
        after = all(i and i.sample_id != record['sample_id']
                    for i, record in zip(old, journal['samples'], strict=True))
        if not (before or after):
            raise ValueError('任务状态与重录备份冲突，请先检查恢复记录')
        if before:
            for item, record in zip(old, journal['samples'], strict=True):
                for active, backup, expected in _revision_files(root, path.parent, (task, item), record):
                    raw = backup.read_bytes()
                    if hashlib.sha256(raw).hexdigest() != expected:
                        raise ValueError('重录备份校验失败')
                    if active.exists():
                        if active.read_bytes() != raw:
                            raise ValueError('活动样本与重录备份冲突')
                    else:
                        active.parent.mkdir(parents=True, exist_ok=True)
                        with active.open('xb') as stream:
                            stream.write(raw)
                            stream.flush()
                            os.fsync(stream.fileno())
        journal['status'] = 'rolled_back' if before else 'committed'
        _write(path, journal)


def requeue_completed(root, task, repository, item_ids):
    root = Path(root)
    disk = repository.load(repository.path_for(task.task_id))
    saved, shown = disk.to_dict(), task.to_dict()
    # current_item() can move the in-memory cursor over completed items while
    # displaying a task. Sample/status/identity changes remain strict conflicts;
    # the managed GUI additionally checks the exact disk hash under its lock.
    saved.pop('cursor')
    shown.pop('cursor')
    if saved != shown:
        raise ValueError('任务进度已变化，请继续任务重新载入后再重录')
    recover_revisions(root, task)
    selected = set(item_ids)
    items = [i for i in task.items if i.item_id in selected]
    if not items or len(items) != len(selected) or any(i.status != 'completed' for i in items):
        raise ValueError('请选择本任务中已保存的份次')
    samples = [read_sample(root, task, item) for item in items]
    # A flat revision directory avoids Windows MAX_PATH failures for sample IDs.
    revision = root/'revisions'/uuid.uuid4().hex
    revision.mkdir(parents=True, exist_ok=False)
    # .bak files are excluded from both font import and sample reconciliation.
    with (revision/'state-before.json.bak').open('xb') as stream:
        stream.write(repository.path_for(task.task_id).read_bytes())
    records = []
    han = any(value['schema_version'] == 'handwriting_single_v1' for _, _, value in samples)
    for item, (sample, raw, value) in zip(items, samples, strict=True):
        with (revision/(item.sample_id+'.json.bak')).open('xb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        record = {'item_id':item.item_id, 'sample_id':item.sample_id,
                        'character':item.character, 'repeat_index':item.repeat_index,
                        'sha256':hashlib.sha256(raw).hexdigest()}
        if value['schema_version'] == 'handwriting_single_v1':
            from handwriting_collector.storage import sanitize_writer_id
            legacy = root/'legacy'/sanitize_writer_id(task.writer_id)
            paths = [sample]
            npy = legacy/(item.sample_id+'.npy')
            if npy.exists():
                paths.append(npy)
            paths.extend(p for p in (legacy/item.sample_id).rglob('*') if p.is_file())
            record['files'] = []
            for ordinal, active in enumerate(paths):
                data = active.read_bytes()
                name = item.sample_id+f'-file-{ordinal}.bak'
                with (revision/name).open('xb') as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                record['files'].append({'path':active.relative_to(root).as_posix(), 'backup':name,
                                        'sha256':hashlib.sha256(data).hexdigest()})
        records.append(record)
    journal = {'schema_version':'inkstruct_capture_revision_v1' if han else 'inkstruct_symbol_revision_v1', 'task_id':task.task_id,
               'writer_id':task.writer_id, 'status':'prepared', 'samples':records}
    _write(revision/'revision.json', journal)
    updated = type(task).from_dict(task.to_dict())
    for item in updated.items:
        if item.item_id in selected:
            item.status, item.sample_id = 'pending', None
    updated.cursor = next(i for i, item in enumerate(updated.items) if item.item_id in selected)
    try:
        for item, record in zip(items, records, strict=True):
            for active, _, expected in _revision_files(root, revision, (task, item), record):
                if hashlib.sha256(active.read_bytes()).hexdigest() != expected:
                    raise ValueError('样本在操作中已变化，未继续修改')
                from handwriting_collector.paths import native_path
                Path(native_path(active)).unlink()
        repository.save(updated)
    except Exception:
        # If save failed before commit, restore the active originals immediately.
        recover_revisions(root, repository.load(repository.path_for(task.task_id)))
        raise
    task.items, task.cursor = updated.items, updated.cursor
    journal['status'] = 'committed'
    try:
        _write(revision/'revision.json', journal)
    except OSError:
        # The durable task already committed; resume will finish journal recovery.
        pass
    return revision
