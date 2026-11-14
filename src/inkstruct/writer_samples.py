"""Copy explicitly attributed samples without modifying the captured originals."""

from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import tempfile
import uuid
from zipfile import ZipFile, is_zipfile

from .capture_management import check_capture_paths, valid_writer
from .document.schema import digest
from .resource_catalog import catalog_write
from .samples import SUPPORTED_SCHEMA, parse_raw_sample

MAX_RECORD = 16 * 1024**2
MAX_TOTAL = 256 * 1024**2
SCHEMAS = {'han': SUPPORTED_SCHEMA, 'symbol': 'inkstruct_symbol_sample_v1'}
UUID_FILENAME = re.compile(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}')


@dataclass(frozen=True)
class SampleImport:
    writer: str
    characters: str
    fingerprint: str
    records: tuple


def sample_bytes(source):
    if source.is_dir():
        for path in sorted(source.rglob('*.json')):
            with path.open('rb') as stream:
                yield path, stream.read(MAX_RECORD + 1)
    elif is_zipfile(source):
        with ZipFile(source) as archive:
            for info in archive.infolist():
                if info.filename.endswith('.json') and not info.filename.startswith('__MACOSX/'):
                    with archive.open(info) as stream:
                        yield Path(info.filename), stream.read(MAX_RECORD + 1)
    else:
        with source.open('rb') as stream:
            yield source, stream.read(MAX_RECORD + 1)


def inspect_samples(path, kind):
    from .fonts.importer import make_symbol
    from .fonts.core import validate_summary, validate_trajectory

    records, writers = {}, set()
    total = 0
    for count, (member, raw) in enumerate(sample_bytes(Path(path)), 1):
        total += len(raw)
        if count > 10000 or len(raw) > MAX_RECORD or total > MAX_TOTAL:
            raise ValueError('样本来源超过导入大小限制')
        value = json.loads(raw)
        if not isinstance(value, dict) or value.get('schema_version') != SCHEMAS[kind]:
            continue
        writer, sample_id, char = (value.get(key) for key in ('writer_id', 'sample_id', 'character'))
        if (not valid_writer(writer) or not isinstance(sample_id, str) or not sample_id
                or not isinstance(char, str) or len(char) != 1):
            raise ValueError('样本缺少有效的书写者、样本 ID 或字符')
        char.encode('utf-8')
        if kind == 'han':
            parse_raw_sample(raw, member, expected_writer=writer)
        else:
            trajectory, _, summary = make_symbol(raw, value)
            validate_trajectory(trajectory)
            validate_summary(summary, len(trajectory['strokes']))
        key = sha256(raw).hexdigest()
        if sample_id in records and key != records[sample_id][0]:
            raise ValueError('来源含重复且内容不同的样本 ID')
        records[sample_id] = (key, value)
        writers.add(writer)
    if len(writers) != 1:
        raise ValueError('请选择包含此采集类别且只含一位书写者的来源')
    ordered = tuple(records[key] for key in sorted(records))
    return SampleImport(writers.pop(), ''.join(sorted({v['character'] for _, v in ordered})),
                        digest([key for key, _ in ordered]), ordered)


class SampleImports:
    def __init__(self, catalog):
        self.catalog = catalog
        self.lock_path = catalog.lock_path

    @catalog_write
    def add(self, kind, writer, selection):
        if writer not in self.catalog.writers():
            raise ValueError('请选择已有书写者')
        root = self.catalog.task_root(kind)
        check_capture_paths(root, writer)
        target = root / 'samples' / writer / ('import-' + selection.fingerprint[:24])
        if os.name == 'nt' and len(str((target / ('0' * 36 + '.json')).resolve())) > 258:
            raise ValueError('采集目录过深，请改用较短的采集数据目录后再导入。')
        if target.exists():
            return 0
        target.parent.mkdir(parents=True, exist_ok=True)
        existing = {path.stem for path in target.parent.glob('*/*.json')}
        staging = root / '.staging'
        staging.mkdir(exist_ok=True)
        added = 0
        with tempfile.TemporaryDirectory(prefix='writer-import-', dir=staging) as folder:
            stage = Path(folder) / 'samples'
            stage.mkdir()
            for key, original in selection.records:
                char = original['character']
                original_id = original['sample_id']
                same_writer = selection.writer == writer
                sample_id = (original_id if same_writer and UUID_FILENAME.fullmatch(original_id) else
                             str(uuid.uuid5(uuid.NAMESPACE_URL, f'inkstruct:import:{writer}:{key}')))
                if sample_id in existing or (same_writer and original_id in existing):
                    continue
                value = {**original, 'writer_id': writer, 'sample_id': sample_id,
                         'codepoint': f'U+{ord(char):04X}',
                         'capture': {**(original.get('capture') or {}), 'imported_from': {
                             'writer_id': selection.writer, 'sample_id': original_id, 'sha256': key}}}
                value.pop('task', None)
                value.pop('legacy_export', None)
                if kind == 'symbol' and 'variant' in value:
                    value['variant'] = {**value['variant'], 'selection_group': [writer, char]}
                path = stage / (sample_id + '.json')
                path.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False), encoding='utf-8')
                existing.add(sample_id)
                added += 1
            if added:
                stage.rename(target)
        return added
