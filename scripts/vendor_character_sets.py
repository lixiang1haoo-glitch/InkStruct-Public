"""Reproduce bundled character facts from pinned official sources (no network).

Usage: python scripts/vendor_character_sets.py --sources DIR --output DIR
The output is a new directory; existing catalogues are never overwritten.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile

PINNED = {
    'Unihan-17.0.0.zip': 'f7a48b2b545acfaa77b2d607ae28747404ce02baefee16396c5d2d7a8ef34b5e',
    'tw-common-4808.ods': 'e97e29ed2aa222bbfc12c18a6d96f0270440b1d73f64366d9ad22d7fe9012408',
    'unicode-license.txt': 'e7a93b009565cfce55919a381437ac4db883e9da2126fa28b91d12732bc53d96',
}
UAX = 'https://www.unicode.org/reports/tr38/tr38-39.html'
TW = 'https://language.moe.gov.tw/material/info?m=9fe3ff5a-5a8c-4817-9e60-6337dd55a509'


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def build(sources, output):
    for name, expected in PINNED.items():
        if digest((sources / name).read_bytes()) != expected:
            raise ValueError('Source identity mismatch: ' + name)
    fields = {key: {} for key in ('kTGH', 'kGB1', 'kSimplifiedVariant', 'kTraditionalVariant', 'kZVariant')}
    with zipfile.ZipFile(sources / 'Unihan-17.0.0.zip') as archive:
        for name in archive.namelist():
            for line in archive.read(name).decode('utf-8').splitlines():
                if not line or line.startswith('#'):
                    continue
                code, field, value = line.split('\t')
                if field in fields:
                    assert code not in fields[field]
                    fields[field][code] = value
    han = lambda code: chr(int(code.removeprefix('U+'), 16))
    tgh = sorted((int(value.removeprefix('2013:')), han(code), value)
                 for code, value in fields['kTGH'].items())
    assert [r[0] for r in tgh] == list(range(1, 8106))
    gb = sorted((value, han(code)) for code, value in fields['kGB1'].items())
    assert len(gb) == len({v for v, c in gb}) == 6866
    ns = {'t': 'urn:oasis:names:tc:opendocument:xmlns:table:1.0'}
    with zipfile.ZipFile(sources / 'tw-common-4808.ods') as archive:
        sheet = ET.fromstring(archive.read('content.xml')).find('.//t:table', ns)
    tw, errata = [], []
    for row in sheet.findall('t:table-row', ns):
        cells = [''.join(cell.itertext()) for cell in row.findall('t:table-cell', ns)]
        if not cells or not cells[0].isdigit():
            continue
        ordinal, identifier, unicode, text = cells[:4]
        assert identifier == f'A{int(ordinal):05}' and len(text) == 1
        if chr(int(unicode, 16)) != text:
            # Preserve the official table's character column, corroborated by
            # the same Ministry's explicitly identified dictionary entry.
            assert cells[:4] == ['02149', 'A02149', '6c69', '汨']
            errata.append({'record': identifier, 'source_unicode_column': unicode,
                'source_character_column': text, 'used_codepoint': 'U+6C68',
                'policy': 'use explicit character column; retain conflicting Unicode column, no normalization',
                'corroboration': 'https://dict.variants.moe.edu.tw/dictView.jsp?ID=23423',
                'corroboration_version': '2024 正式七版 A02149 汨; B02035 汩 is 次常用'})
        tw.append((int(ordinal), text, identifier, unicode))
    assert [r[0] for r in tw] == list(range(1, 4809))
    relations = {}
    for field in ('kSimplifiedVariant', 'kTraditionalVariant', 'kZVariant'):
        for code, value in fields[field].items():
            targets = []
            for token in value.split():
                match = re.fullmatch(r'U\+([0-9A-F]+)(?:<(.+))?', token)
                assert match, token
                targets.append({'character': chr(int(match[1], 16)), 'raw': token})
            relations.setdefault(han(code), {})[field] = targets
    declarations = [
        ('cn-tgh-2013', '简体 · 通用规范汉字表（大陆）', '2013', 'CN',
         [(c, v) for _, c, v in tgh], 'Unicode 17.0.0 kTGH：2013 年全表，依原序号排列',
         'https://www.moe.gov.cn/jyb_xwfb/xw_fbh/moe_2069/s7135/s7562/s7569/201308/t20130827_156353.html'),
        ('traditional-gb12345-1990', '繁体 · GB/T 12345 汉字', '1990', 'CN',
         [(c, v) for v, c in gb], 'Unicode 17.0.0 kGB1：完整编码标准中的 6866 个汉字，依区位排列；不是全部繁体字',
         'https://openstd.samr.gov.cn/bzgk/std/newGbInfo?hcno=90394D2B4115D9291C825A7651AEFE4B'),
        ('tw-common-1982', '繁体 · 常用國字標準字體表（台湾）', '1982', 'TW',
         [(c, identifier) for _, c, identifier, _ in tw], '教育部 ODS 全表 4808 字，依 A 字号排列；不含次常用、罕用字', TW),
    ]
    # A separate, fully specified derived set, never presented as a regional
    # normative table. Keep every one-to-many/self relation, no word conversion.
    expanded = {}
    for _, c, v in tgh:
        for target in relations.get(c, {}).get('kTraditionalVariant', [{'character': c}]):
            expanded.setdefault(target['character'], []).append({'character': c, 'reference': v})
    declarations.append(('traditional-tgh-unihan17', '繁体扩展 · 8105 字的 Unihan 全对应（派生）',
        'TGH 2013 + Unihan 17.0.0', 'derived',
        list(expanded.items()), '逐字保留全部 kTraditionalVariant；无对应时保留原字，显式自身对应保留。非地区规范、非词义转换。', UAX))
    output.mkdir(parents=True, exist_ok=False)
    entries = []
    files = {}

    def write(name, value):
        raw = (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
        (output / name).write_bytes(raw)
        files[name] = digest(raw)

    for identifier, title, version, region, rows, scope, url in declarations:
        assert len(rows) == len({c for c, reference in rows})
        write(identifier + '.json', {'characters': [c for c, _ in rows], 'references': [r for _, r in rows]})
        entries.append({'id': identifier, 'title': title, 'version': version, 'region': region,
            'count': len(rows), 'file': identifier + '.json', 'scope': scope, 'url': url,
            'unicode_version': '17.0.0', 'errata': errata if region == 'TW' else []})
    write('relations.json', {'unicode_version': '17.0.0', 'source': UAX,
        'scope': 'All kSimplifiedVariant, kTraditionalVariant and kZVariant records, directed, no normalization',
        'counts': {k: len(fields[k]) for k in fields if 'Variant' in k}, 'characters': relations})
    license_bytes = (sources / 'unicode-license.txt').read_bytes()
    (output / 'UNICODE-LICENSE.txt').write_bytes(license_bytes)
    files['UNICODE-LICENSE.txt'] = digest(license_bytes)
    notice = ('Character facts: Unicode Unihan 17.0.0 (Unicode License V3), GB/T 12345-1990,\n'
        'PRC General Standard Chinese Characters 2013, Taiwan MOE common standard characters 1982.\n'
        'Taiwan data: Ministry of Education, R.O.C.; factual characters/identifiers only.\n'
        'No government font, dictionary definition, scanned page or glyph outline is distributed here.\n'
        'Complete original downloads and SHA-256 receipts are retained with the release validation.\n'
        'Scope and the A02149 source-column discrepancy are explicitly recorded in catalog.json.\n')
    (output / 'NOTICE.txt').write_text(notice, encoding='utf-8')
    files['NOTICE.txt'] = digest((output / 'NOTICE.txt').read_bytes())
    catalog = {'schema': 'inkstruct-character-set-catalog-v1', 'revision': '2026-10-22.1',
        'sources': [{'file': name, 'sha256': sha, 'url': url} for name, sha, url in (
            ('Unihan-17.0.0.zip', PINNED['Unihan-17.0.0.zip'], 'https://www.unicode.org/Public/17.0.0/ucd/Unihan.zip'),
            ('tw-common-4808.ods', PINNED['tw-common-4808.ods'], 'https://language.moe.gov.tw/uploads/files/17694982751710.ods'))],
        'sets': entries, 'files': files, 'relation_documentation': UAX,
        'policy': 'Literal character identities. Membership and relations are separate. Full donor pool remains independent.',
        'limitations': 'No universal complete traditional-character set; no HK normative list bundled. Unicode relations are informal, not context-aware conversion. Same-codepoint regional glyph differences require appropriate structures, not character replacement.'}
    (output / 'catalog.json').write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'catalog_sha256': digest((output / 'catalog.json').read_bytes()),
                      'sets': {e['id']: e['count'] for e in entries}, 'errata': errata}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    build(args.sources, args.output)
