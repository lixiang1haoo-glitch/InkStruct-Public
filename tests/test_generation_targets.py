from dataclasses import replace

import pytest

from inkstruct.generation_targets import extract_document, read_target_file, target_manifest, validate_targets


def test_literal_targets_keep_variants_order_and_ivs():
    manifest = target_manifest('孔正孔 發髮发 臺台台 漢\ufe00 A', '孔正發髮发臺台漢')
    assert manifest['requested'] == ['孔', '正', '發', '髮', '发', '臺', '台', '漢\ufe00', 'A']
    assert manifest['unsupported'] == ['漢\ufe00', 'A']
    with pytest.raises(ValueError, match='截断'):
        validate_targets(manifest)
    with pytest.raises(ValueError, match='为空'):
        validate_targets(target_manifest(' \n\t', '孔'))
    changed = target_manifest('孔', '孔')
    changed['requested'] = ['正']
    with pytest.raises(ValueError, match='身份'):
        validate_targets(changed)


def test_utf8_csv_is_explicit_and_does_not_import_metadata(tmp_path):
    path = tmp_path/'中文字表.csv'
    path.write_text('\ufeffcharacter,count,备注\n孔,5,不要生成\n正,5,其他\n孔,5,重复', 'utf-8')
    text, origin = read_target_file(path)
    assert target_manifest(text, '孔正')['requested'] == ['孔', '正']
    assert origin['path'] == str(path.resolve()) and len(origin['sha256']) == 64
    path.write_text('name,count\n孔,5', 'utf-8')
    with pytest.raises(ValueError, match='唯一'):
        read_target_file(path)


def test_document_extracts_printable_text_math_code_and_caption_not_urls():
    source = '# 孔正\n\n[止](https://example.org/网址) ![羊](路径.png)\n\n$U_{正}=1$\n\n`群`\n\n```text\n兄\n```\n'
    result = extract_document(source, '孔正止羊群兄')
    assert result['requested'] == list('孔正止羊群兄')
    assert not result['unsupported']
    assert result['source_ranges'] and all(0 <= r['span']['start'] < r['span']['end'] <= len(source) for r in result['source_ranges'])
    assert not any(c in result['requested'] for c in '网址路径')


def test_current_template_only_references_reachable_named_fields_and_reports_errors():
    from inkstruct.document.flow_template import FlowTemplate, NamedField, PageLayout, TextFrame
    from inkstruct.document.styles import FlowStyle
    from inkstruct.document.template import Region
    frame = TextFrame('name', 'name', Region('name', 5, 5, 30, 10), 'field', 1, 'name')
    body = TextFrame('body', 'body', Region('body', 5, 25, 90, 60))
    layout = PageLayout('p', 'p', (frame, body))
    unused = PageLayout('unused', 'unused', (replace(frame, field_id='unused'), body))
    template = FlowTemplate(kind='custom', width_mm=120, height_mm=120, layouts=(layout, unused), loop_pages=('p',),
                            fields=(NamedField('name', '姓名'), NamedField('unused', '未使用')))
    source = ':::field name\n孔\n:::\n\n:::field unused\n羊\n:::\n\n:::field unknown\n群\n:::\n\n正'
    result = extract_document(source, '孔正羊群', flow=FlowStyle(template=template))
    assert result['requested'] == list('孔正')
    assert set(result['source']['excluded_unreferenced_fields']) == {'unused', 'unknown'}
    assert any(d['code'] == 'template-field-unknown' for d in result['diagnostics'])
    assert source.endswith('正')


def test_invalid_field_block_keeps_following_body_and_diagnoses():
    result = extract_document(':::field name\n孔\n\n正', '孔正')
    assert result['requested'] == list('孔正')
    assert any(d['code'] == 'template-field-syntax' for d in result['diagnostics'])
