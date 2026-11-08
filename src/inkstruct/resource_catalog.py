"""Local management metadata; never modifies font, template or document protocols."""

import hashlib
import json
import os
import tempfile
import time
from functools import wraps
from pathlib import Path


def catalog_write(function):
    @wraps(function)
    def locked(self, *args, **kwargs):
        from PySide6 import QtCore
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock = QtCore.QLockFile(str(self.lock_path))
        if not lock.tryLock(0):
            raise ValueError('另一窗口正在修改资源目录，请稍后重试；现有资源保持不变')
        try:
            return function(self, *args, **kwargs)
        finally:
            lock.unlock()
    return locked


def workspace_for(widget=None):
    from PySide6 import QtCore

    seen = set()
    while widget is not None and id(widget) not in seen:
        seen.add(id(widget))
        if hasattr(widget, 'workspace'):
            return Path(widget.workspace)
        host = getattr(widget, 'settings_host', None)
        if host is not None and host is not widget:
            widget = host
        elif getattr(widget, 'editor', None) is not None and not isinstance(widget.editor, str):
            candidate = widget.editor
            widget = candidate if hasattr(candidate, 'source_session') else widget.parentWidget()
        else:
            widget = widget.parentWidget() if hasattr(widget, 'parentWidget') else None
    if QtCore.QSettings.defaultFormat() == QtCore.QSettings.Format.IniFormat:
        settings = QtCore.QSettings(QtCore.QSettings.defaultFormat(), QtCore.QSettings.Scope.UserScope,
                                    'InkStruct', 'UnifiedSettings')
        return Path(settings.fileName()).parent / 'workspace'
    return Path(QtCore.QStandardPaths.writableLocation(QtCore.QStandardPaths.GenericDataLocation)) / 'InkStruct/workspace'


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(data, ensure_ascii=False, allow_nan=False, indent=2).encode('utf-8')
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix='.catalog-')
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


class TemplateStore:
    """Explicitly imported, immutable template copies with reversible hiding."""

    def __init__(self, root):
        self.root = Path(root)
        self.index = self.root / 'catalog.json'
        self.lock_path = self.root / '.catalog.lock'

    def entries(self):
        if not self.index.exists():
            return []
        raw = self.index.read_bytes()
        if len(raw) > 8*1024*1024:
            raise ValueError('模板目录索引过大，原文件保留')
        data = json.loads(raw)
        if (not isinstance(data, dict) or set(data) != {'schema', 'entries'}
                or data['schema'] not in {'inkstruct_template_catalog_v1', 'inkstruct_template_catalog_v2'}):
            raise ValueError('未知模板管理索引，原文件保留')
        entries = data['entries']
        if not isinstance(entries, list) or len(entries) > 10000:
            raise ValueError('模板目录索引无效')
        ids = set()
        for item in entries:
            keys = {'id', 'name', 'source', 'created_ns', 'archived'}
            if isinstance(item, dict) and 'revision' in item and data['schema'].endswith('_v2'):
                from .document.template_revision import TemplateRevision
                if not isinstance(item['revision'], dict):
                    raise ValueError('模板目录修订条目无效')
                TemplateRevision(**item['revision'])
                keys.add('revision')
            if (not isinstance(item, dict) or set(item) != keys
                    or not isinstance(item['id'], str) or len(item['id']) != 64
                    or any(c not in '0123456789abcdef' for c in item['id'])
                    or item['id'] in ids or not isinstance(item['name'], str)
                    or not isinstance(item['source'], str) or type(item['created_ns']) is not int
                    or type(item['archived']) is not bool):
                raise ValueError('模板目录条目无效')
            ids.add(item['id'])
        return entries

    def path(self, identity):
        if not isinstance(identity, str) or len(identity) != 64 or any(c not in '0123456789abcdef' for c in identity):
            raise ValueError('无效模板管理身份')
        path = self.root / 'items' / (identity + '.json')
        # Managed copies use a full content hash. Deep Windows workspaces can
        # exceed MAX_PATH even when the source filename itself remains short.
        absolute = str(path.absolute())
        if os.name == 'nt' and len(absolute) >= 248 and not absolute.startswith('\\\\?\\'):
            return Path('\\\\?\\UNC\\' + absolute[2:] if absolute.startswith('\\\\') else '\\\\?\\' + absolute)
        return path

    def read(self, item):
        from .document.template_authoring import MAX_FLOW_TEMPLATE_BYTES, parse_template

        path = self.path(item['id'])
        if path.is_symlink():
            raise ValueError('库内模板不能是符号链接')
        with path.open('rb') as stream:
            raw = stream.read(MAX_FLOW_TEMPLATE_BYTES+1)
        if len(raw) > MAX_FLOW_TEMPLATE_BYTES:
            raise ValueError('库内模板超过容量限制')
        if hashlib.sha256(raw).hexdigest() != item['id']:
            raise ValueError('库内模板内容已改变；请重新显式导入，不能自动替换')
        template = parse_template(raw.decode('utf-8'))
        if 'revision' in item:
            from dataclasses import asdict
            if template.revision is None or asdict(template.revision) != item['revision']:
                raise ValueError('模板库修订与文件身份不一致')
        return template

    def newer(self, template):
        """Only a confirmed descendant of this exact snapshot is an update."""
        from .document.template_revision import template_revision

        prior = template_revision(template)
        entries = [e for e in self.entries()
                   if e.get('revision', {}).get('template_id') == prior.template_id]
        reachable = {prior.revision_id: prior.number}
        matches = []
        for entry in sorted(entries, key=lambda e: e['revision']['number']):
            revision = entry['revision']
            if reachable.get(revision['parent_id']) != revision['number'] - 1:
                continue
            reachable[revision['revision_id']] = revision['number']
            if not entry['archived']:
                matches.append(entry)
        return tuple(sorted(matches, key=lambda e: (e['revision']['number'], e['created_ns']), reverse=True))

    def superseded_ids(self, entries):
        """Ancestors of active revisions belong in history, not the current list."""
        by_revision = {entry['revision']['revision_id']: entry for entry in entries if 'revision' in entry}
        legacy_sources = {str(self.path(entry['id'])): entry for entry in entries if 'revision' not in entry}
        superseded = set()
        for entry in entries:
            if entry['archived']:
                continue
            revision = entry.get('revision')
            while revision and revision['parent_id']:
                parent = by_revision.get(revision['parent_id'])
                if parent is None:
                    # Local saves of a legacy template retain its managed path.
                    parent = legacy_sources.get(entry['source'])
                if parent is None or parent['id'] in superseded:
                    break
                prior = parent.get('revision')
                if prior and (prior['template_id'] != revision['template_id']
                              or prior['number'] + 1 != revision['number']):
                    break
                superseded.add(parent['id'])
                entry, revision = parent, prior
        return superseded

    @catalog_write
    def add(self, source, *, revision_parent=None):
        from .document.template_authoring import (
            MAX_FLOW_TEMPLATE_BYTES,
            parse_template,
        )

        source = Path(source).resolve()
        with source.open('rb') as stream:
            raw = stream.read(MAX_FLOW_TEMPLATE_BYTES + 1)
        if len(raw) > MAX_FLOW_TEMPLATE_BYTES:
            raise ValueError('模板文件超过容量限制')
        template = parse_template(raw.decode('utf-8'))
        if revision_parent is not None:
            if template.revision is not None:
                raise ValueError('文件已有修订身份，请直接导入以保留原修订关系')
            return self._save_revision(template, revision_parent, source, self.entries())
        return self._add(raw, template, source, self.entries())

    @catalog_write
    def save_revision(self, parent_id, candidate):
        entries = self.entries()
        parent = next((entry for entry in entries if entry['id'] == parent_id), None)
        if parent is None or parent['archived']:
            raise ValueError('原修订已移出模板库，请恢复后重试。')
        return self._save_revision(candidate, self.read(parent), self.path(parent_id), entries)

    def _save_revision(self, candidate, parent, source, entries):
        from .document.template_authoring import parse_template, template_json
        from .document.template_revision import version_template

        raw = template_json(version_template(candidate, parent=parent))
        return self._add(raw.encode('utf-8'), parse_template(raw), source, entries)

    def _add(self, raw, template, source, entries):
        from dataclasses import asdict

        identity = hashlib.sha256(raw).hexdigest()
        if template.revision:
            revision = asdict(template.revision)
            related = next((item for item in entries if item.get('revision', {}).get('revision_id')
                            == template.revision.revision_id), None)
            if related:
                if related['revision'] != revision:
                    raise ValueError('同一修订标识对应不同内容或关系')
                self.read(related)
                related['archived'] = False
                self._write(entries)
                return related
        target = self.path(identity)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_symlink():
            raise ValueError('库内目标不能是符号链接')
        created = False
        try:
            try:
                with target.open('xb') as stream:
                    created = True
                    stream.write(raw)
                    stream.flush()
                    os.fsync(stream.fileno())
            except FileExistsError:
                if target.read_bytes() != raw:
                    raise ValueError('已有模板副本损坏，原文件保留') from None
            existing = next((item for item in entries if item['id'] == identity), None)
            if existing:
                existing['archived'] = False
                item = existing
            else:
                item = {'id': identity, 'name': template.name, 'source': str(source),
                        'created_ns': time.time_ns(), 'archived': False}
                if template.revision:
                    item['revision'] = revision
                entries.append(item)
            self._write(entries)
        except (OSError, ValueError, TypeError):
            if created:
                target.unlink(missing_ok=True)
            raise
        return item

    def _write(self, entries):
        atomic_json(self.index, {'schema': 'inkstruct_template_catalog_v2', 'entries': entries})

    @catalog_write
    def update(self, identity, **changes):
        if not set(changes) <= {'name', 'archived'}:
            raise ValueError('不可改变模板内容或来源身份')
        entries = self.entries()
        item = next(item for item in entries if item['id'] == identity)
        if 'name' in changes and (not isinstance(changes['name'], str) or not changes['name'].strip()):
            raise ValueError('请输入显示名称')
        if 'archived' in changes and type(changes['archived']) is not bool:
            raise ValueError('无效移出状态')
        item.update(changes)
        self._write(entries)


class FontMetadata:
    """Disposable summaries and local display choices, keyed by exact file stamp."""

    def __init__(self, root):
        self.path = Path(root) / 'management.json'
        self.lock_path = Path(root) / '.management.lock'

    def read(self):
        if not self.path.exists():
            return {}
        with self.path.open('rb') as stream:
            raw = stream.read(16*1024*1024+1)
        if len(raw) > 16*1024*1024:
            raise ValueError('字体管理索引过大；原文件保留')
        data = json.loads(raw)
        if not isinstance(data, dict) or set(data) != {'schema', 'items'} or data['schema'] != 'inkstruct_font_management_v1' or not isinstance(data['items'], dict):
            raise ValueError('未知字体管理索引；原文件保留')
        for name, item in data['items'].items():
            if (Path(name).name != name or not name.endswith('.inkfont')
                    or not isinstance(item, dict) or not set(item) <= {'alias', 'archived', 'summary', 'error', 'error_stamp', 'verified_stamp'}
                    or ('alias' in item and not isinstance(item['alias'], str))
                    or ('archived' in item and type(item['archived']) is not bool)
                    or ('error' in item and not isinstance(item['error'], str))):
                raise ValueError('字体管理条目无效；原文件保留')
            summary = item.get('summary')
            if summary and (not isinstance(summary, dict) or set(summary) != {'stamp', 'manifest', 'title', 'detail', 'groups', 'origins'}
                            or not isinstance(summary['manifest'], dict) or not isinstance(summary['stamp'], list)
                            or any(not isinstance(summary['manifest'].get(key), str) for key in ('name', 'font_id', 'writer_alias', 'font_version', 'release_id', 'package_id', 'package_kind'))):
                raise ValueError('字体摘要索引无效；原文件保留')
        return data['items']

    @catalog_write
    def update(self, name, **changes):
        items = self.read()
        items.setdefault(name, {}).update(changes)
        atomic_json(self.path, {'schema': 'inkstruct_font_management_v1', 'items': items})
