from hashlib import sha256
import json
from pathlib import Path
from zipfile import ZipFile

import pytest
from test_document_layout import glyph
from test_symbol_provider import specimen

from inkstruct.assets.resolver import AssetResolver
from inkstruct.capture_management import CaptureCatalog
from inkstruct.document.editing import SourceSession
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.package import load_package, save_package
from inkstruct.document.schema import PageProfile, StyleProfile
from inkstruct.fonts.core import FontPackage
from inkstruct.fonts.library import publish_font
from inkstruct.fonts.publication import publication_stamp, review_selection
from inkstruct.layout.blocks import layout_markdown
from inkstruct.samples import scan_samples
from inkstruct.writer_links import WriterLinkRequired, WriterLinks
from inkstruct.writer_samples import SampleImports, inspect_samples


def write_zip(path, *values):
    with ZipFile(path, 'w') as archive:
        for index, value in enumerate(values):
            archive.writestr(f'samples/{index}.json', json.dumps(value))


def test_legacy_publication_uses_an_explicit_content_bound_link(tmp_path):
    run = tmp_path / 'historical-batch'
    (run / 'trajectories').mkdir(parents=True)
    trajectory = run / 'trajectories/U+4EBA.json'
    trajectory.write_text(json.dumps({**glyph(), 'writer_id': 'legacy_local'}), encoding='utf-8')
    symbols = tmp_path / 'extension.zip'
    value = {**specimen('1'), 'writer_id': 'another_device'}
    write_zip(symbols, value)
    sources = {path: path.read_bytes() for path in (trajectory, symbols)}
    links = WriterLinks(tmp_path)
    args = ('legacy_local', run, symbols, '跨设备回归')
    with pytest.raises(ValueError, match='其他书写者'):
        review_selection(*args)
    with pytest.raises(WriterLinkRequired) as unconfirmed:
        review_selection(*args, writer_links=links)
    link = unconfirmed.value.link
    assert link.target_writer == 'legacy_local'
    assert (link.symbols.writer, link.symbols.characters, link.symbols.count) == ('another_device', '1', 1)
    links.confirm(link)
    links.confirm(link)
    assert len(links.read()) == 1
    reviewed = review_selection(*args, writer_links=WriterLinks(tmp_path))
    groups = {key[0] for key in reviewed['coverage']}
    result = publish_font(tmp_path / 'fonts', writer=args[0], run=run, symbols=symbols, name=args[3],
                          package_kind='user', groups=groups, stamp=publication_stamp(*args[:3]),
                          expected=reviewed['coverage'], progress=lambda _: None, writer_links=links)
    font = FontPackage(result['path'])
    assert font.verify()['characters'] == 2
    by_character = {record['character']: font.provenance[record['candidate_id']] for record in font.records}
    assert by_character['1']['writer_link']['source_writer'] == 'another_device'
    assert 'writer_link' not in by_character['人']
    assert not result['difference']
    resolver = AssetResolver(embedded=font.glyphs())
    source = SourceSession('人1')
    before = layout_markdown(parse_markdown(source), resolver)
    doc = tmp_path / 'frozen.inkdoc'
    save_package(doc, source, resolver, PageProfile(), StyleProfile())
    Path(result['path']).unlink()
    saved = load_package(doc)
    assert layout_markdown(parse_markdown(saved.session), saved.resolver) == before
    assert all(path.read_bytes() == raw for path, raw in sources.items())

    trajectory.write_bytes(sources[trajectory] + b'\n')
    with pytest.raises(WriterLinkRequired):
        review_selection(*args, writer_links=links)
    trajectory.write_bytes(sources[trajectory])
    write_zip(symbols, {**value, 'sample_id': 'changed'})
    with pytest.raises(WriterLinkRequired):
        review_selection(*args, writer_links=links)
    write_zip(symbols, value, {**value, 'sample_id': 'mixed', 'writer_id': 'legacy_local'})
    with pytest.raises(ValueError, match='其他书写者'):
        review_selection(*args, writer_links=links)


def test_portable_writer(tmp_path):
    local = CaptureCatalog(tmp_path / 'l')
    borrowed = CaptureCatalog(tmp_path / 'b')
    stable = local.create_writer('同名')
    other = borrowed.create_writer('同名')
    profile = tmp_path / 'borrowed.inkwriter'
    local.export_writer(stable, profile)
    assert borrowed.import_writer(profile) == stable != other
    borrowed.rename_writer(stable, '本机名称')
    assert borrowed.import_writer(profile) == stable
    assert borrowed.writers()[stable]['name'] == '本机名称'
    with pytest.raises(ValueError, match='旧 ID'):
        local.export_writer('legacy_local', tmp_path / 'legacy.inkwriter')

    han = tmp_path / 'han.json'
    value = {'schema_version': 'handwriting_single_v1', 'writer_id': 'legacy_local', 'sample_id': 'han-1',
             'character': '人', 'capture': {'canvas_width': 100, 'canvas_height': 100},
             'strokes': specimen()['strokes']}
    han.write_text(json.dumps(value), encoding='utf-8')
    original = han.read_bytes()
    imports = SampleImports(local)
    selection = inspect_samples(han, 'han')
    assert imports.add('han', stable, selection) == 1
    assert imports.add('han', stable, selection) == 0
    directory = local.root / 'samples' / stable
    accepted, rejected, foreign = scan_samples(directory, stable)
    assert len(accepted) == 1 and not rejected and not foreign
    assert accepted[0].capture['imported_from'] == {'writer_id': 'legacy_local', 'sample_id': 'han-1',
                                                   'sha256': sha256(original).hexdigest()}
    assert han.read_bytes() == original

    symbols = tmp_path / 'capture.zip'
    write_zip(symbols, {**specimen(), 'writer_id': stable})
    before = symbols.read_bytes()
    assert imports.add('symbol', stable, inspect_samples(symbols, 'symbol')) == 1
    assert imports.add('symbol', stable, inspect_samples(symbols, 'symbol')) == 0
    source = local.task_root('symbol') / 'samples' / stable
    assert review_selection(stable, None, source, '稳定 ID')['coverage']
    assert symbols.read_bytes() == before
