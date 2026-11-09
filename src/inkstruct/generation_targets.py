"""Literal, versioned generation targets; output scope never filters donors."""
from __future__ import annotations

import csv
import hashlib
import io
import unicodedata
from dataclasses import asdict
from pathlib import Path


def fingerprint(value):
    import json
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def target_manifest(text, supported, *, source=None, ranges=(), diagnostics=()):
    from .document.source import clusters
    requested = list(dict.fromkeys(c for _, c in clusters(text) if not c.isspace()))
    available = set(supported)
    return {'schema': 'inkstruct-generation-targets-v1', 'requested': requested,
            'supported': [c for c in requested if c in available],
            'unsupported': [c for c in requested if c not in available],
            'target_sha256': fingerprint(requested), 'source': source or {'kind': 'custom-text'},
            'source_ranges': list(ranges), 'diagnostics': list(diagnostics),
            'donor_scope': 'complete author profile; independent of target list'}


def structure_targets(supported):
    supported = tuple(supported)
    return target_manifest("".join(supported), supported, source={"kind": "all-supported"})


def read_target_file(path):
    path = Path(path)
    if path.stat().st_size > 4_000_000:
        raise ValueError('字表超过 4 MB，请拆分后导入')
    raw = path.read_bytes()
    text = raw.decode('utf-8-sig')
    if path.suffix.lower() == '.csv':
        rows = list(csv.reader(io.StringIO(text)))
        rows = [r for r in rows if r and any(v.strip() for v in r)]
        if rows:
            headers = [v.strip() for v in rows[0]]
            columns = [i for i, v in enumerate(headers) if v in ('character', '汉字', '字符')]
            if len(columns) == 1:
                col, rows = columns[0], rows[1:]
            elif all(len(r) == 1 for r in rows):
                col = 0
            else:
                raise ValueError('多列 CSV 需包含唯一的 character、汉字或字符列；不会猜测其他列的用途')
            if any(len(r) <= col for r in rows):
                raise ValueError('CSV 字符列存在缺失单元格')
            text = '\n'.join(r[col] for r in rows)
        else:
            text = ''
    elif path.suffix.lower() != '.txt':
        raise ValueError('自定义字表支持 UTF-8 TXT 或 CSV')
    return text, {'kind': 'custom-file', 'path': str(path.resolve()), 'sha256': hashlib.sha256(raw).hexdigest(),
                  'encoding': 'utf-8-sig', 'normalization': 'none'}


def _han(text):
    from .assets.glyph_provider import is_han
    return any(is_han(c) or unicodedata.name(c, '').startswith('CJK COMPATIBILITY IDEOGRAPH') or c == '〇' for c in text)


def extract_document(source, supported, *, flow=None, identity=None):
    from .document.markdown import parse_markdown
    from .document.source import clusters
    document = parse_markdown(source, dialect=flow.markdown_dialect if flow else 'markdown',
                              field_blocks=flow.named_fields if flow else True)
    roots = document.nodes
    diagnostics = [asdict(d) for d in document.diagnostics]
    excluded = []
    if flow is not None and flow.named_fields:
        from .document.named_fields import split_fields
        body, fields, issues = split_fields(document, flow.template)
        used_layouts = set(flow.template.start_pages + flow.template.loop_pages)
        referenced = {f.field_id for layout in flow.template.layouts if layout.layout_id in used_layouts
                      for f in layout.frames if f.role == 'field'}
        roots = (*body.nodes, *(n for key, n in fields.items() if key in referenced))
        excluded = [key for key in fields if key not in referenced]
        diagnostics.extend(asdict(d) for d in issues)
    found = []
    for root in roots:
        for node in root.walk():
            for occurrence in node.occurrences:
                if _han(occurrence.text):
                    found.append((occurrence.span.start, occurrence.text, asdict(occurrence.span), 'text'))
            if node.math:
                for math in node.math.walk():
                    if math.occurrence_id and _han(math.value):
                        for _, cluster in clusters(math.value):
                            if _han(cluster):
                                found.append((math.span.start, cluster, asdict(math.span), 'math'))
    found.sort(key=lambda row: row[0])
    origin = {'kind': 'document', 'sha256': hashlib.sha256(source.encode()).hexdigest(),
              'parser': document.dialect, 'identity': identity,
              'policy': 'parsed printable text/math/code/captions; no URLs or resource paths',
              'excluded_unreferenced_fields': excluded,
              'scope': 'current flow reachable fields' if flow else 'conservative Markdown printable nodes; no template context'}
    return target_manifest(''.join(r[1] for r in found), supported, source=origin,
                           ranges=[{'text': r[1], 'span': r[2], 'kind': r[3]} for r in found], diagnostics=diagnostics)


def extract_file(path, supported):
    path = Path(path)
    if path.suffix.lower() == '.inkdoc':
        # Reuse the complete existing package validator, including resource hashes.
        from .document.package import load_package
        loaded = load_package(path)
        return extract_document(loaded.session.source, supported, flow=loaded.flow,
                                identity={'path': str(path.resolve()), 'package_sha256': loaded.file_hash})
    if path.suffix.lower() not in ('.md', '.markdown') or path.stat().st_size > 4_000_000:
        raise ValueError('请选择不超过 4 MB 的 UTF-8 Markdown，或已有 .inkdoc 文档')
    return extract_document(path.read_text('utf-8-sig'), supported,
                            identity={'path': str(path.resolve()), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})


def validate_targets(manifest):
    if manifest.get('schema') != 'inkstruct-generation-targets-v1' or fingerprint(manifest['requested']) != manifest['target_sha256']:
        raise ValueError('目标字表身份不一致')
    if not manifest['requested']:
        raise ValueError('字表为空，或文档中没有可提取的汉字；未启动生成')
    if manifest['unsupported']:
        raise ValueError('结构库不支持以下目标（未做替换或截断）：' + ' '.join(manifest['unsupported']) + '。字母、数字与符号请使用录制样本。')
