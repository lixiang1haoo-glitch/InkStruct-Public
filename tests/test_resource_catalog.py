import json
from dataclasses import replace

import pytest

from inkstruct.document.flow_template import FlowTemplate
from inkstruct.document.template_authoring import template_json
from inkstruct.resource_catalog import FontMetadata, TemplateStore


def test_managed_template_exact_copy_survives_source_move_and_reversible_archive(tmp_path):
    source = tmp_path/'original.json'
    raw = template_json(FlowTemplate(name='实验报告')).encode()
    source.write_bytes(raw)
    store = TemplateStore(tmp_path/'library')
    entry = store.add(source)
    assert store.path(entry['id']).read_bytes() == raw == source.read_bytes()
    assert store.add(source)['id'] == entry['id'] and len(store.entries()) == 1
    source.rename(tmp_path/'moved.json')
    assert store.read(entry).name == '实验报告'
    store.update(entry['id'], name='库内别名', archived=True)
    assert store.entries()[0]['name'] == '库内别名'
    assert store.read(entry).name == '实验报告'
    assert store.path(entry['id']).read_bytes() == raw
    store.update(entry['id'], archived=False)
    assert not store.entries()[0]['archived']


def test_source_update_creates_new_copy_does_not_change_old_template(tmp_path):
    source = tmp_path/'source.json'
    first = FlowTemplate(name='同名模板')
    source.write_text(template_json(first), 'utf-8')
    store = TemplateStore(tmp_path/'library')
    a = store.add(source)
    source.write_text(template_json(replace(first, width_mm=220)), 'utf-8')
    b = store.add(source)
    assert a['id'] != b['id']
    assert store.read(a) == first
    assert store.read(b).width_mm == 220
    store.path(a['id']).write_text('{}')
    with pytest.raises(ValueError, match='内容已改变'):
        store.read(a)


def test_unknown_catalog_and_invalid_template_preserved_not_overwritten(tmp_path):
    store = TemplateStore(tmp_path/'library')
    store.root.mkdir()
    store.index.write_text('{"schema":"future","entries":[],"unknown":true}')
    before = store.index.read_bytes()
    source = tmp_path/'valid.json'
    source.write_text(template_json(FlowTemplate()), 'utf-8')
    with pytest.raises(ValueError, match='未知'):
        store.add(source)
    assert store.index.read_bytes() == before
    other = TemplateStore(tmp_path/'other')
    source.write_text('{"unknown":true}')
    with pytest.raises((ValueError, TypeError)):
        other.add(source)
    assert not other.index.exists()
    for identity in ('../bad', '/absolute', '0'*63, 'z'*64):
        with pytest.raises(ValueError):
            other.path(identity)


def test_font_metadata_is_separate_and_unknown_fields_do_not_disappear(tmp_path):
    metadata = FontMetadata(tmp_path)
    metadata.update('a.inkfont', alias='显示名称', archived=True)
    assert metadata.read()['a.inkfont']['alias'] == '显示名称'
    metadata.update('a.inkfont', archived=False)
    assert not metadata.read()['a.inkfont']['archived']
    metadata.path.write_text(json.dumps({'schema': 'inkstruct_font_management_v1', 'items': {'a': {'unknown': 1}}}))
    before = metadata.path.read_bytes()
    with pytest.raises(ValueError):
        metadata.update('a', alias='new')
    assert metadata.path.read_bytes() == before


@pytest.mark.parametrize('value', [None, [], 1, {'schema': 'inkstruct_template_catalog_v1', 'entries': [None]}])
def test_malformed_catalogs_fail_without_rewriting(tmp_path, value):
    store = TemplateStore(tmp_path/'templates')
    store.root.mkdir()
    store.index.write_text(json.dumps(value), 'utf-8')
    before = store.index.read_bytes()
    with pytest.raises(ValueError):
        store.entries()
    assert store.index.read_bytes() == before
    metadata = FontMetadata(tmp_path)
    metadata.path.write_text(json.dumps(value), 'utf-8')
    before = metadata.path.read_bytes()
    with pytest.raises(ValueError):
        metadata.read()
    assert metadata.path.read_bytes() == before


def test_separate_catalog_instances_merge_choices_and_reject_writer_lock(tmp_path):
    from PySide6 import QtCore

    a, b = FontMetadata(tmp_path), FontMetadata(tmp_path)
    a.update('a.inkfont', alias='别名')
    b.update('a.inkfont', archived=True)
    assert a.read()['a.inkfont'] == {'alias': '别名', 'archived': True}
    lock = QtCore.QLockFile(str(a.lock_path))
    assert lock.tryLock(0)
    before = a.path.read_bytes()
    try:
        with pytest.raises(ValueError, match='另一窗口'):
            b.update('a.inkfont', archived=False)
    finally:
        lock.unlock()
    assert a.path.read_bytes() == before
