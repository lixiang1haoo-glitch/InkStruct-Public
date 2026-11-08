"""Pinned complete tables, explicit omissions, literal variant identities."""
import copy
from pathlib import Path

import pytest

from inkstruct.character_sets import CharacterSets
from inkstruct.generation_targets import validate_targets


@pytest.fixture(scope='module')
def catalog():
    return CharacterSets()


def test_complete_named_standards_counts_order_and_erratum(catalog):
    expected = [8105, 6866, 4808, 8593]
    assert [e['count'] for e in catalog.entries] == expected
    for entry in catalog.entries:
        chars = catalog.characters(entry['id'])
        assert len(chars) == len(set(chars)) == entry['count']
        assert entry['version'] and entry['url'].startswith('https://')
    cn = catalog.data['cn-tgh-2013.json']
    assert cn['references'] == [f'2013:{i}' for i in range(1, 8106)]
    tw = catalog.data['tw-common-1982.json']
    assert tw['references'] == [f'A{i:05}' for i in range(1, 4809)]
    assert tw['characters'][2148] == '汨' and '汩' not in tw['characters']
    erratum = catalog.by_id['tw-common-1982']['errata'][0]
    assert erratum['source_unicode_column'] == '6c69' and erratum['used_codepoint'] == 'U+6C68'
    assert len(catalog.data['relations.json']['characters']) > 13000


def test_membership_is_not_exclusive_and_no_first_mapping_or_normalization(catalog):
    sets = [set(catalog.characters(e['id'])) for e in catalog.entries]
    assert set('一井后台').issubset(set.intersection(*sets))
    relations = catalog.data['relations.json']['characters']
    targets = lambda c: [r['character'] for r in relations[c]['kTraditionalVariant']]
    assert targets('发') == list('發髮')
    assert targets('说') == list('說説')
    assert targets('为') == list('為爲')
    assert targets('后') == list('后後')
    assert targets('台') == list('台檯臺颱')
    assert targets('苧') == ['薴'] and relations['苧']['kSimplifiedVariant'][0]['character'] == '苎'
    expanded = sets[-1]
    assert set('發髮說説為爲后後台檯臺颱').issubset(expanded)
    assert '說' in sets[2] and '説' not in sets[2]  # explicit TW table, no locale guessing
    assert 'U+8AAC' in catalog.describe_character('说')
    assert 'U+7232' in catalog.describe_character('为')
    assert '归一化' in catalog.describe_character('漢\ufe00')


def test_merge_keeps_shared_chars_and_has_canonical_order(catalog):
    ids = [e['id'] for e in catalog.entries]
    entries, union = catalog.union(ids)
    assert catalog.union(ids[::-1])[1] == union
    assert union[:8105] == catalog.characters(ids[0])
    assert len(union) == len(set(union))
    for entry in entries:
        assert set(catalog.characters(entry['id'])).issubset(union)
    with pytest.raises(ValueError):
        catalog.union(['simplified'])
    with pytest.raises(ValueError):
        catalog.union([ids[0], ids[0]])


def test_unsupported_requires_explicit_review_and_retains_all_facts(catalog):
    identifier = 'cn-tgh-2013'
    manifest = catalog.manifest([identifier], '孔正一井')
    assert len(manifest['requested']) == 8105 and len(manifest['unsupported']) == 8101
    catalog.validate(manifest, '孔正一井')
    with pytest.raises(ValueError, match='不支持'):
        validate_targets(manifest)
    accepted = catalog.manifest([identifier], '孔正一井', reviewed_unsupported=True)
    assert set(accepted['requested']) == set('孔正一井') and not accepted['unsupported']
    assert accepted['source']['complete_requested'] == manifest['requested']
    assert accepted['source']['unsupported_in_structure_library'] == manifest['unsupported']
    assert len(accepted['diagnostics'][0]['characters']) == 8101
    assert accepted['source']['donor_scope'] == 'complete author profile'
    catalog.validate(accepted, '孔正一井')
    validate_targets(accepted)
    for field, value in [('unsupported_action', 'block'), ('complete_requested', ['孔']),
                         ('unsupported_in_structure_library', []), ('catalog_sha256', 'bad')]:
        changed = copy.deepcopy(accepted)
        changed['source'][field] = value
        with pytest.raises(ValueError, match='身份已改变'):
            catalog.validate(changed, '孔正一井')
    with pytest.raises(ValueError, match='身份已改变'):
        catalog.validate(accepted, '孔正一井乙')
    with pytest.raises(ValueError, match='为空'):
        validate_targets(catalog.manifest([], '孔正'))
    with pytest.raises(ValueError, match='为空'):
        validate_targets(catalog.manifest([identifier], [], reviewed_unsupported=True))


def test_tampered_catalog_or_any_member_is_rejected(tmp_path, catalog):
    import shutil
    from inkstruct.character_sets import data_root
    shutil.copytree(data_root(), tmp_path/'data')
    member = tmp_path/'data/relations.json'
    member.write_bytes(member.read_bytes() + b' ')
    with pytest.raises(ValueError, match='校验失败'):
        CharacterSets(tmp_path/'data')
    (tmp_path/'data/catalog.json').write_text('{}', encoding='utf-8')
    with pytest.raises(ValueError, match='目录身份'):
        CharacterSets(tmp_path/'data')


def test_runner_rejects_changed_scope_before_creating_output(tmp_path, catalog):
    from types import SimpleNamespace
    from inkstruct.generation_parallel import run_generation
    base = SimpleNamespace(characters=lambda: list('孔正一井'))
    manifest = catalog.manifest(['cn-tgh-2013'], base.characters(), reviewed_unsupported=True)
    with pytest.raises(ValueError, match='任务字表'):
        run_generation(tmp_path/'output', 'user_001', ['孔'], base, {}, None, lambda: False,
                       target_manifest=manifest)
    assert not (tmp_path/'output').exists()
