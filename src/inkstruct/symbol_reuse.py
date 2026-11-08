"""Explicit, sample-bound reuse declarations; never fabricate capture records."""
import json
import string
import zipfile
from pathlib import Path

from .punctuation import capture_character
from .symbol_tasks import CUSTOM_PREFIXES, source_configuration

GREEK_SIMILAR = dict(zip('ΑΒΕΖΗΙΚΜΝΟΡΤΥΧ', 'ABEZHIKMNOPTYX', strict=True))
REUSE_POLICY = 'confirmed-symbol-reuse-v1'


def reuse_options():
    return [('latin_italic', c, c) for c in string.ascii_letters] + [
        ('greek', target, source) for target, source in GREEK_SIMILAR.items()]


def inventory(root, writer):
    if root is None or not Path(root).exists():
        return {}
    from .assets.symbol_provider import adapt_symbol
    from .fonts.importer import symbol_records
    result = {}
    for raw, value in symbol_records(root):
        if value['writer_id'] != writer:
            continue
        adapt_symbol(raw)
        key = (capture_character(value['character']), value.get('variant', {}).get('letter_style', 'unspecified'))
        result.setdefault(key, {})[value['sample_id']] = value
    return result


def validate_reuse(record):
    if not isinstance(record, dict) or set(record) != {
        'group', 'target', 'source', 'source_style', 'sample_ids', 'confirmed'}:
        raise ValueError('复用配置字段无效')
    if (record['confirmed'] is not True or record['source_style'] != 'upright'
            or (record['group'], record['target'], record['source']) not in reuse_options()
            or not isinstance(record['sample_ids'], list) or not record['sample_ids']
            or any(not isinstance(s, str) or not s for s in record['sample_ids'])
            or len(set(record['sample_ids'])) != len(record['sample_ids'])):
        raise ValueError('复用必须确认且指向已有英文正体样本')
    return record


def declarations(path, writer):
    """Read embedded task configuration from a selected directory or archive."""
    path = Path(path)
    if path.is_dir():
        payloads = (p.read_bytes() for p in sorted(path.rglob('state.json')))
        yield from _declarations(payloads, writer)
    else:
        with zipfile.ZipFile(path) as archive:
            items = [i for i in archive.infolist() if i.filename.endswith('/state.json')]
            if len(items) > 10000 or any(i.file_size > 16 * 1024**2 for i in items):
                raise ValueError('采集任务配置超过资源预算')
            yield from _declarations((archive.read(i) for i in items), writer)


def _declarations(payloads, writer):
    for raw in payloads:
        if len(raw) > 16 * 1024**2:
            raise ValueError('采集任务配置超过资源预算')
        value = json.loads(raw)
        if (value.get('schema_version') != 'handwriting_task_v1'
                or value.get('writer_id') != writer):
            continue
        source = value.get('source', '')
        if source.startswith(CUSTOM_PREFIXES):
            for record in source_configuration(source)['reuse']:
                yield validate_reuse(record)
