"""Versioned, literal target sets; never a conversion engine or donor filter."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

from .generation_targets import fingerprint, target_manifest

CATALOG_SHA256 = '262c98e1e1dbdf257ec447b0072be8da0582c830343a90923b73884e22ce4b02'


def data_root():
    root = Path(sys._MEIPASS) if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[2]
    return root / 'configs' / 'character_sets'


class CharacterSets:
    def __init__(self, root=None):
        root = Path(root) if root else data_root()
        raw = (root / 'catalog.json').read_bytes()
        if hashlib.sha256(raw).hexdigest() != CATALOG_SHA256:
            raise ValueError('内置字表目录身份不一致，请修复应用资源；未启动生成')
        self.catalog = json.loads(raw)
        self.data = {}
        for name, expected in self.catalog['files'].items():
            raw = (root / name).read_bytes()
            if hashlib.sha256(raw).hexdigest() != expected:
                raise ValueError('内置字表资源校验失败：' + name)
            if name.endswith('.json'):
                self.data[name] = json.loads(raw)
        self.entries = self.catalog['sets']
        self.by_id = {e['id']: e for e in self.entries}
        for entry in self.entries:
            chars = self.data[entry['file']]['characters']
            if len(chars) != entry['count'] or len(set(chars)) != len(chars) or any(len(c) != 1 for c in chars):
                raise ValueError('内置字表成员损坏：' + entry['id'])

    def characters(self, identifier):
        return list(self.data[self.by_id[identifier]['file']]['characters'])

    def union(self, identifiers):
        identifiers = list(identifiers)
        if len(set(identifiers)) != len(identifiers) or any(k not in self.by_id for k in identifiers):
            raise ValueError('未知或重复的内置字表身份')
        # Canonical catalogue order, independent of checkbox click order.
        chosen = [e for e in self.entries if e['id'] in identifiers]
        return chosen, list(dict.fromkeys(c for e in chosen for c in self.characters(e['id'])))

    def manifest(self, identifiers, supported, *, reviewed_unsupported=False):
        entries, requested = self.union(identifiers)
        available = set(supported)
        missing = [c for c in requested if c not in available]
        origin = {'kind': 'builtin-character-sets', 'catalog_sha256': CATALOG_SHA256,
            'catalog_revision': self.catalog['revision'], 'sets': entries,
            'complete_requested': requested, 'complete_target_sha256': fingerprint(requested),
            'unsupported_in_structure_library': missing,
            'structure_characters_sha256': fingerprint(sorted(available)),
            'unsupported_action': 'explicit-supported-intersection' if missing and reviewed_unsupported else 'block',
            'shared_deduplicated_count': sum(e['count'] for e in entries) - len(requested),
            'normalization': 'none', 'relations': 'informational only; no character conversion',
            'donor_scope': 'complete author profile'}
        actual = [c for c in requested if c in available] if missing and reviewed_unsupported else requested
        diagnostics = ([{'code': 'target-structure-unsupported', 'severity': 'warning',
                         'characters': missing, 'action': 'explicit-supported-intersection'}]
                       if missing and reviewed_unsupported else [])
        return target_manifest(''.join(actual), available, source=origin, diagnostics=diagnostics)

    def validate(self, manifest, supported):
        source = manifest.get('source', {})
        try:
            ids = [e['id'] for e in source['sets']]
            expected = self.manifest(ids, supported, reviewed_unsupported=
                source.get('unsupported_action') == 'explicit-supported-intersection')
        except (KeyError, TypeError) as error:
            raise ValueError('内置字表身份不完整，请重新选择字表') from error
        if manifest != expected:
            raise ValueError('内置字表、缺口确认或结构库身份已改变，请重新选择并确认字表')

    def describe_character(self, character):
        if len(character) != 1:
            return '请输入单个字符；不执行 Unicode 归一化或字符替换。'
        memberships = [e['title'] + ' ' + e['version'] for e in self.entries if character in self.characters(e['id'])]
        relations = self.data['relations.json']['characters'].get(character, {})
        lines = [f'{character} · U+{ord(character):04X}', '字表成员：' + ('；'.join(memberships) or '不属于以上字表')]
        labels = {'kSimplifiedVariant': '简体对应', 'kTraditionalVariant': '繁体对应', 'kZVariant': '编码异体关系'}
        for key, label in labels.items():
            if key in relations:
                lines.append(label + '：' + '、'.join(f"{r['character']}（{r['raw']}）" for r in relations[key]))
        lines += ['关系来源：Unihan 17.0.0；保留全部一对多、自身和定向关系，不自动替换。',
                  '地区字表成员与对应关系分开。同一编码的地区字形差异仍取决于结构库；选择字表不保证地区笔形。']
        return '\n'.join(lines)
