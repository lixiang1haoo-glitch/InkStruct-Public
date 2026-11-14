"""Non-destructive writer and task management beside legacy capture records."""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import uuid
from pathlib import Path

from .resource_catalog import atomic_json, catalog_write


class CaptureCatalog:
    def __init__(self, root):
        self.root = Path(root)
        self.index = self.root / 'capture-management.json'
        self.lock_path = self.root / '.capture-management.lock'

    def read(self):
        if not self.index.exists():
            return {'schema_version': 'inkstruct_capture_management_v1', 'writers': {}, 'tasks': {}}
        value = json.loads(self.index.read_text('utf-8'))
        if (set(value) != {'schema_version', 'writers', 'tasks'}
                or value['schema_version'] != 'inkstruct_capture_management_v1'
                or not isinstance(value['writers'], dict) or not isinstance(value['tasks'], dict)):
            raise ValueError('采集管理记录格式未知，原文件保留，请查看数据目录')
        for key, writer in value['writers'].items():
            if not valid_writer(key) or set(writer) != {'name'} or not isinstance(writer['name'], str):
                raise ValueError('书写者登记损坏，未修改原记录')
        for state in value['tasks'].values():
            if state not in ('active', 'paused', 'cancelled', 'archived'):
                raise ValueError('未知任务管理状态，未修改原记录')
        return value

    def task_root(self, kind):
        if kind not in ('han', 'symbol'):
            raise ValueError('未知采集类别')
        return self.root if kind == 'han' else self.root / 'symbol_collection'

    def tasks(self):
        from handwriting_collector.tasks import TaskRepository
        states = self.read()['tasks']
        entries = []
        for kind in ('han', 'symbol'):
            root = self.task_root(kind)
            repository = TaskRepository(root)
            for path in repository.tasks_dir.glob('*/state.json'):
                try:
                    task = repository.load(path)
                    if (not valid_writer(task.writer_id) or path.parent.name != task.task_id
                            or str(uuid.UUID(task.task_id)) != task.task_id):
                        raise ValueError('任务身份或路径无效')
                    entries.append({'kind': kind, 'root': root, 'task': task, 'path': path,
                                    'state': states.get(kind + ':' + task.task_id, 'paused'), 'error': None})
                except (OSError, ValueError, KeyError, TypeError) as error:
                    entries.append({'kind': kind, 'root': root, 'path': path, 'task': None,
                                    'state': 'damaged', 'error': str(error)})
        return sorted(entries, key=lambda entry: str(entry['path']))

    def writers(self):
        result = dict(self.read()['writers'])
        for entry in self.tasks():
            if task := entry['task']:
                result.setdefault(task.writer_id, {'name': task.writer_id})
        for kind in ('han', 'symbol'):
            for folder in (self.task_root(kind) / 'samples').glob('*'):
                if folder.is_dir() and valid_writer(folder.name):
                    result.setdefault(folder.name, {'name': folder.name})
        return result

    @catalog_write
    def create_writer(self, name):
        name = name.strip()
        if not name or len(name) > 80:
            raise ValueError('请输入 1–80 字的书写者名称')
        value = self.read()
        key = 'w_' + uuid.uuid4().hex
        value['writers'][key] = {'name': name}
        atomic_json(self.index, value)
        return key

    @catalog_write
    def rename_writer(self, key, name):
        if key not in self.writers() or not name.strip() or len(name.strip()) > 80:
            raise ValueError('请选择已有书写者并填写有效名称')
        value = self.read()
        value['writers'][key] = {'name': name.strip()}
        atomic_json(self.index, value)

    def export_writer(self, key, path):
        writers = self.writers()
        if not portable_writer(key) or key not in writers:
            raise ValueError('请选择具有可迁移 ID 的书写者。旧 ID 可通过新建书写者并导入样本迁移。')
        profile = {'schema_version': 'inkstruct_writer_profile_v1', 'writer_id': key,
                   'display_name': writers[key]['name']}
        with Path(path).open('x', encoding='utf-8') as output:
            json.dump(profile, output, ensure_ascii=False, indent=2)

    @catalog_write
    def import_writer(self, path):
        with Path(path).open('rb') as source:
            raw = source.read(4097)
        if len(raw) > 4096:
            raise ValueError('书写者资料文件过大')
        profile = json.loads(raw)
        if (not isinstance(profile, dict) or set(profile) != {'schema_version', 'writer_id', 'display_name'}
                or profile['schema_version'] != 'inkstruct_writer_profile_v1'
                or not portable_writer(profile['writer_id']) or not isinstance(profile['display_name'], str)
                or not 1 <= len(profile['display_name'].strip()) <= 80):
            raise ValueError('书写者资料格式无效')
        key = profile['writer_id']
        value = self.read()
        if key not in value['writers']:
            value['writers'][key] = {'name': profile['display_name'].strip()}
            atomic_json(self.index, value)
        return key

    @catalog_write
    def set_state(self, kind, task_id, state):
        if state not in ('active', 'paused', 'cancelled', 'archived'):
            raise ValueError('无效任务状态')
        uuid.UUID(task_id)
        if not (self.task_root(kind) / 'tasks' / task_id / 'state.json').is_file():
            raise ValueError('任务不存在，未修改管理记录')
        value = self.read()
        value['tasks'][kind + ':' + task_id] = state
        atomic_json(self.index, value)


def valid_writer(value):
    return isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,79}', value) is not None


def portable_writer(value):
    return isinstance(value, str) and re.fullmatch(r'w_[0-9a-f]{12}4[0-9a-f]{3}[89ab][0-9a-f]{15}', value) is not None


def check_capture_paths(root, writer):
    if os.name != 'nt':
        return
    base = Path(root).resolve()
    writer = writer or 'w_' + '0' * 32
    paths = [base/'samples'/writer/'U+10FFFF'/('0'*36+'.json'),
             base/'legacy'/writer/('0'*36)/'char_points_idx.txt',
             base/'.staging'/('0'*48)/'text'/'char_points_idx.txt']
    if max(len(str(p)) for p in paths) > 258:
        raise ValueError('采集目录过深，样本可能无法被 Windows 后续读取。请在“数据 → 选择采集数据目录”改选较短路径；当前笔迹和已有文件保留。')


def preview_han_file(path, default_repeats):
    """Preflight bounded counts and conflicting duplicates before allocating items."""
    from handwriting_collector.tasks import parse_character_file
    path = Path(path)
    if path.stat().st_size > 2_000_000:
        raise ValueError('字表超过 2 MB，请拆分后导入')
    duplicates = []
    if path.suffix.lower() == '.csv':
        seen = {}
        with path.open(encoding='utf-8-sig', newline='') as stream:
            for line, row in enumerate(csv.DictReader(stream), 2):
                char = (row.get('character') or '').strip()
                try:
                    count = int((row.get('repeats') or '').strip() or default_repeats)
                except ValueError as error:
                    raise ValueError(f'第 {line} 行份数不是整数') from error
                if not 1 <= count <= 100:
                    raise ValueError(f'第 {line} 行份数须为 1–100')
                if char in seen:
                    if seen[char] != count:
                        raise ValueError(f'第 {line} 行字符 {char} 的重复份数冲突，请先修改 CSV')
                    duplicates.append(line)
                seen[char] = count
    entries = parse_character_file(path, default_repeats)
    if sum(count for _, count, _ in entries) > 50_000:
        raise ValueError('任务超过 50,000 份，请拆分字表')
    return entries, duplicates


def task_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class ManagedRepository:
    """Compare-and-swap under the same task lock used during specimen saves."""
    def __init__(self, root, owner):
        from handwriting_collector.tasks import TaskRepository
        self.repository, self.owner = TaskRepository(root), owner

    def __getattr__(self, name):
        return getattr(self.repository, name)

    def save(self, task):
        path = self.repository.path_for(task.task_id)
        if (self.owner.task is not None and task.task_id == self.owner.task.task_id
                and self.owner._managed_stamp is not None and task_hash(path) != self.owner._managed_stamp):
            raise ValueError('任务已被其他窗口修改，请关闭后重新打开；当前笔迹保留')
        result = self.repository.save(task)
        self.owner._managed_stamp = task_hash(path)
        return result
