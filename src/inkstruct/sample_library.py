"""Read-only capture inventory and checked offline handoff of sample bytes."""

from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
from shutil import copyfileobj
import tempfile
from zipfile import ZIP_DEFLATED, ZipFile, is_zipfile

from .capture_management import check_capture_paths, portable_writer, valid_writer
from .document.schema import digest
from .resource_catalog import catalog_write
from .symbol_catalog import SYMBOL_GROUPS, symbol_group
from .writer_samples import (MAX_RECORD, MAX_TOTAL, SCHEMAS, attributed_sample, sample_bytes,
                             sample_identity, validate_sample)

FORMAT = 'inkstruct_capture_bundle_v1'
MAX_SAMPLES = 10000
MAX_MANIFEST = 8 * 1024**2
CATEGORIES = {'han': '汉字', **{k: v[0] for k, v in SYMBOL_GROUPS.items()},
              'latin_unspecified': '英文 · 写法未标注', 'other': '其他扩展'}
KINDS = {schema: kind for kind, schema in SCHEMAS.items()}


def metadata(value, key):
    record = value.get(key)
    return record if isinstance(record, dict) else {}


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False).encode('utf-8')


@dataclass(frozen=True)
class SampleRow:
    path: Path
    kind: str
    writer: str
    sample_id: str
    character: str
    category: str
    task: str
    captured: str
    raw_hash: str
    origin: tuple[str, str, str] | None


def read_file(path):
    with path.open('rb') as stream:
        raw = stream.read(MAX_RECORD + 1)
    if len(raw) > MAX_RECORD:
        raise ValueError('样本超过单文件容量限制')
    return raw


def row_for(path, value, raw_hash):
    kind = KINDS.get(value.get('schema_version')) if isinstance(value, dict) else None
    if kind is None:
        raise ValueError('未知样本格式')
    writer, sample_id, char = sample_identity(value)
    capture, task, variant = (metadata(value, key) for key in ('capture', 'task', 'variant'))
    origin = capture.get('imported_from')
    if isinstance(origin, dict) and all(isinstance(origin.get(key), str) for key in ('writer_id', 'sample_id', 'sha256')):
        origin = (origin['writer_id'], origin['sample_id'], origin['sha256'])
    else:
        origin = None
    return SampleRow(path, kind, writer, sample_id, char,
                     'han' if kind == 'han' else symbol_group(char, variant.get('letter_style')),
                     str(task.get('task_id', capture.get('imported_task', ''))),
                     str(capture.get('created_at', '')), raw_hash, origin)


def inventory(catalog, writer):
    if not valid_writer(writer):
        return (), ()
    rows, errors = [], []
    for kind in SCHEMAS:
        for path in (catalog.task_root(kind) / 'samples' / writer).glob('*/*.json'):
            try:
                raw = read_file(path)
                row = row_for(path, json.loads(raw), sha256(raw).hexdigest())
                if row.writer != writer or row.kind != kind:
                    raise ValueError('样本身份与目录不符')
                rows.append(row)
            except (OSError, ValueError, TypeError, AttributeError) as error:
                errors.append(f'{path.name} · {error}')
    return tuple(sorted(rows, key=lambda row: (row.character, row.captured, row.sample_id))), tuple(errors)


def read_row(row):
    raw = read_file(row.path)
    if sha256(raw).hexdigest() != row.raw_hash:
        raise ValueError('样本已变化，请刷新库后重试')
    value = json.loads(raw)
    validate_sample(row.kind, raw, value, row.path)
    original = row.path.with_suffix('.raw')
    if original.is_file():
        sample = bundle_sample(read_file(original), original)
        if (sample.row.writer, sample.row.sample_id, sample.row.raw_hash) != row.origin:
            raise ValueError('原始样本与来源记录不符')
        return sample.value
    return value


@dataclass(frozen=True)
class BundleSample:
    raw: bytes
    value: dict
    row: SampleRow


@dataclass(frozen=True)
class CaptureBundle:
    writer: str
    name: str
    samples: tuple[BundleSample, ...]


def bundle_sample(raw, path):
    value = json.loads(raw)
    row = row_for(path, value, sha256(raw).hexdigest())
    validate_sample(row.kind, raw, value, path)
    return BundleSample(raw, value, row)


def writer_record(writer, name):
    if not valid_writer(writer) or not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
        raise ValueError('采集包缺少有效书写者资料')
    return {'id': writer, 'display_name': name, 'scope': 'portable' if portable_writer(writer) else 'local'}


def sample_record(sample, index):
    row = sample.row
    return {'file': f'samples/{index:05}.json', 'kind': row.kind, 'writer_id': row.writer,
            'sample_id': row.sample_id, 'character': row.character, 'sha256': row.raw_hash,
            'size': len(sample.raw)}


def read_zip_member(archive, info, limit):
    with archive.open(info) as stream:
        raw = stream.read(limit + 1)
    if len(raw) != info.file_size or len(raw) > limit:
        raise ValueError('采集包条目大小不符')
    return raw


def export_bundle(path, writer, name, rows):
    path = Path(path)
    if not rows or len(rows) > MAX_SAMPLES or any(row.writer != writer for row in rows):
        raise ValueError('请选择同一书写者的 1–10000 份样本')
    owner = writer_record(writer, name)
    total, records, seen = 0, [], set()
    with tempfile.TemporaryDirectory(prefix='.inkcapture-', dir=path.parent) as folder:
        staged = Path(folder) / 'capture.zip'
        with ZipFile(staged, 'w', compression=ZIP_DEFLATED) as archive:
            for row in rows:
                current = read_file(row.path)
                if sha256(current).hexdigest() != row.raw_hash:
                    raise ValueError('样本已变化，请刷新库后重试')
                original = row.path.with_suffix('.raw')
                has_original = original.is_file()
                raw = read_file(original) if has_original else current
                sample = bundle_sample(raw, row.path)
                source = sample.row.writer, sample.row.sample_id, sample.row.raw_hash
                if source != (row.origin if has_original else (row.writer, row.sample_id, row.raw_hash)):
                    raise ValueError('样本原始来源与库记录不符，请刷新后重试')
                identity = (sample.row.kind, *source[:2])
                if identity in seen:
                    raise ValueError('选中的样本含重复原始 ID，请分别核对后导出')
                seen.add(identity)
                total += len(raw)
                if total > MAX_TOTAL:
                    raise ValueError('采集包展开后超过容量限制，请减少样本')
                entry = sample_record(sample, len(records))
                archive.writestr(entry['file'], raw)
                records.append(entry)
            manifest = json_bytes({'schema_version': FORMAT, 'writer': owner, 'samples': records})
            if len(manifest) > MAX_MANIFEST:
                raise ValueError('采集包清单超过容量限制')
            archive.writestr('manifest.json', manifest)
        try:
            os.link(staged, path)
        except FileExistsError:
            raise
        except OSError:
            with staged.open('rb') as source, path.open('xb') as output:
                try:
                    copyfileobj(source, output)
                    output.flush()
                except OSError:
                    output.close()
                    path.unlink(missing_ok=True)
                    raise
    return len(records)


def open_bundle(path):
    path = Path(path)
    with ZipFile(path) as archive:
        entries = archive.infolist()
        files = {entry.filename: entry for entry in entries}
        manifest = files.get('manifest.json')
        if (manifest is None or len(entries) != len(files) or len(entries) > MAX_SAMPLES + 1
                or manifest.file_size > MAX_MANIFEST):
            raise ValueError('采集包缺少有效清单或含重复文件')
        record = json.loads(read_zip_member(archive, manifest, MAX_MANIFEST))
        if (not isinstance(record, dict) or set(record) != {'schema_version', 'writer', 'samples'}
                or record['schema_version'] != FORMAT):
            raise ValueError('不支持的采集包版本')
        owner, rows = record['writer'], record['samples']
        if (not isinstance(owner, dict) or owner != writer_record(owner.get('id'), owner.get('display_name'))
                or not isinstance(rows, list) or not 1 <= len(rows) <= MAX_SAMPLES
                or set(files) != {'manifest.json', *(f'samples/{i:05}.json' for i in range(len(rows)))}):
            raise ValueError('采集包书写者资料或文件清单不符')
        if sum(item.file_size for item in entries if item != manifest) > MAX_TOTAL:
            raise ValueError('采集包展开后超过容量限制')
        samples = []
        for index, entry in enumerate(rows):
            member = f'samples/{index:05}.json'
            info = files[member]
            if info.file_size > MAX_RECORD:
                raise ValueError('样本超过单文件容量限制')
            sample = bundle_sample(read_zip_member(archive, info, MAX_RECORD), Path(member))
            if entry != sample_record(sample, index):
                raise ValueError(f'采集包样本哈希或身份不符 · {member}')
            samples.append(sample)
    identities = {(s.row.kind, s.row.writer, s.row.sample_id) for s in samples}
    if len(identities) != len(samples):
        raise ValueError('采集包包含重复原始样本 ID')
    return CaptureBundle(owner['id'], owner['display_name'], tuple(samples))


def open_source(path):
    """Read the versioned bundle, or a single-writer legacy JSON/ZIP/directory."""
    path = Path(path)
    if path.suffix.lower() == '.inkcapture':
        return open_bundle(path)
    if path.is_file() and is_zipfile(path):
        with ZipFile(path) as archive:
            if 'manifest.json' in archive.namelist():
                info = archive.getinfo('manifest.json')
                if info.file_size <= MAX_MANIFEST:
                    info_value = json.loads(read_zip_member(archive, info, MAX_MANIFEST))
                    if isinstance(info_value, dict) and str(info_value.get('schema_version', '')).startswith('inkstruct_capture_bundle_'):
                        return open_bundle(path)
    total, records, writers = 0, {}, set()
    for count, (member, raw) in enumerate(sample_bytes(path), 1):
        total += len(raw)
        if count > MAX_SAMPLES or len(raw) > MAX_RECORD or total > MAX_TOTAL:
            raise ValueError('样本来源超过导入容量限制')
        value = json.loads(raw)
        if not isinstance(value, dict) or value.get('schema_version') not in KINDS:
            continue
        sample = bundle_sample(raw, member)
        row = sample.row
        key = row.kind, row.sample_id
        if key in records and records[key].row.raw_hash != row.raw_hash:
            raise ValueError('来源含重复且内容不同的样本 ID')
        records[key] = sample
        writers.add(row.writer)
    if len(writers) != 1:
        raise ValueError('请选择只含一位书写者的旧采集来源')
    writer = writers.pop()
    return CaptureBundle(writer, writer, tuple(records.values()))


@dataclass(frozen=True)
class ImportReview:
    new: tuple[BundleSample, ...]
    duplicates: tuple[SampleRow, ...]
    conflicts: tuple[SampleRow, ...]


class SampleLibrary:
    def __init__(self, catalog):
        self.catalog = catalog
        self.lock_path = catalog.lock_path

    def review(self, bundle, writer):
        if writer not in self.catalog.writers():
            raise ValueError('请选择已有的目标书写者')
        rows, errors = inventory(self.catalog, writer)
        if errors:
            raise ValueError(f'目标书写者有 {len(errors)} 份样本无法核对，请先检查样本库。\n{errors[0]}')
        by_origin, by_id = {}, {}
        for row in rows:
            origin = row.origin or (row.writer, row.sample_id, row.raw_hash)
            by_origin.setdefault((row.kind, *origin[:2]), set()).add(origin[2])
            by_id.setdefault((row.kind, row.sample_id), set()).add(row.raw_hash)
        new, duplicate, conflict = [], [], []
        batch_origins = {}
        for sample in bundle.samples:
            row = sample.row
            origin = row.origin or (row.writer, row.sample_id, row.raw_hash)
            batch_origins.setdefault((row.kind, *origin[:2]), set()).add(origin[2])
        for sample in bundle.samples:
            row = sample.row
            identity = row.kind, row.writer, row.sample_id
            origin = row.origin or (row.writer, row.sample_id, row.raw_hash)
            known = by_origin.get(identity, set()) | by_origin.get((row.kind, *origin[:2]), set())
            if len(batch_origins[(row.kind, *origin[:2])]) > 1 or known - {row.raw_hash, origin[2]}:
                conflict.append(row)
            elif known or row.raw_hash in by_id.get((row.kind, row.sample_id), ()):
                duplicate.append(row)
            else:
                assigned = attributed_sample(row.kind, writer, row.raw_hash, sample.value)['sample_id']
                if (row.kind, assigned) in by_id:
                    conflict.append(row)
                else:
                    new.append(sample)
                    by_origin.setdefault((row.kind, *origin[:2]), set()).add(origin[2])
                    by_id.setdefault((row.kind, assigned), set()).add(row.raw_hash)
        return ImportReview(tuple(new), tuple(duplicate), tuple(conflict))

    @catalog_write
    def import_confirmed(self, bundle, writer, expected):
        current = self.review(bundle, writer)
        if current != expected:
            raise ValueError('目标样本库已变化，请重新预览和确认')
        if not current.new:
            return 0
        published = []
        staging = self.catalog.root / '.staging'
        staging.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='sample-library-', dir=staging) as folder:
            ready = []
            for kind in SCHEMAS:
                samples = [item for item in current.new if item.row.kind == kind]
                if not samples:
                    continue
                root = self.catalog.task_root(kind)
                check_capture_paths(root, writer)
                identifier = digest(sorted(item.row.raw_hash for item in samples))[:20]
                destination = root / 'samples' / writer / ('in-' + identifier)
                if os.name == 'nt' and len(str((destination / ('0' * 36 + '.json')).resolve())) > 258:
                    raise ValueError('采集目录过深，请改用较短的数据目录后再导入。')
                destination.parent.mkdir(parents=True, exist_ok=True)
                staged = Path(folder) / kind
                staged.mkdir()
                for sample in samples:
                    row = sample.row
                    value = attributed_sample(kind, writer, row.raw_hash, sample.value)
                    if row.task:
                        value['capture']['imported_task'] = row.task
                    path = staged / value['sample_id']
                    path.with_suffix('.raw').write_bytes(sample.raw)
                    path.with_suffix('.json').write_bytes(json_bytes(value))
                ready.append((staged, destination))
            try:
                for staged, destination in ready:
                    staged.rename(destination)
                    published.append((staged, destination))
            except OSError:
                for staged, destination in reversed(published):
                    destination.rename(staged)
                raise
        return len(current.new)
