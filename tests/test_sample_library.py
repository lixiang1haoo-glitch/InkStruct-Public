import json
from dataclasses import replace
from zipfile import ZipFile

import pytest

from inkstruct.capture_management import CaptureCatalog
from inkstruct.fonts.publication import review_selection
from inkstruct.sample_library import SampleLibrary, export_bundle, inventory, open_bundle, open_source, read_row
from inkstruct.samples import scan_samples
from test_symbol_provider import specimen


def catalog(path, writer, name='书写者'):
    result = CaptureCatalog(path)
    (path / 'samples' / writer).mkdir(parents=True)
    result.rename_writer(writer, name)
    return result


def write(catalog, kind, writer, value):
    root = catalog.task_root(kind) / 'samples' / writer / f'U+{ord(value["character"]):04X}'
    root.mkdir(parents=True, exist_ok=True)
    path = root / (value['sample_id'] + '.json')
    path.write_bytes(json.dumps(value, ensure_ascii=False, indent=4).encode('utf-8'))
    return path


def test_mixed_handoff_keeps_bytes_task_and_writer(tmp_path):
    sender = catalog(tmp_path / 's', 'source')
    target = catalog(tmp_path / 't', 'target')
    raw_symbol = {**specimen('1'), 'writer_id': 'source', 'task': {'task_id': 'task-symbol'}}
    raw_han = {'schema_version': 'handwriting_single_v1', 'writer_id': 'source', 'sample_id': 'han-1',
               'character': '人', 'capture': {'canvas_width': 100, 'canvas_height': 100},
               'strokes': raw_symbol['strokes'], 'task': {'task_id': 'task-han'}}
    paths = [write(sender, 'han', 'source', raw_han), write(sender, 'symbol', 'source', raw_symbol)]
    before = {path.read_bytes() for path in paths}
    rows, errors = inventory(sender, 'source')
    assert not errors and {row.category for row in rows} == {'han', 'digits'}
    assert {row.task for row in rows} == {'task-han', 'task-symbol'}
    assert read_row(rows[0]) == raw_symbol
    archive = tmp_path / 'v1.inkcapture'
    assert export_bundle(archive, 'source', '来源', rows) == 2
    with pytest.raises(FileExistsError):
        export_bundle(archive, 'source', '来源', rows)
    bundle = open_source(archive)
    assert bundle.name == '来源' and {sample.raw for sample in bundle.samples} == before
    target_library = SampleLibrary(target)
    review = target_library.review(bundle, 'target')
    assert (len(review.new), len(review.duplicates), len(review.conflicts)) == (2, 0, 0)
    assert target_library.import_confirmed(bundle, 'target', review) == 2
    duplicate = target_library.review(bundle, 'target')
    assert (len(duplicate.new), len(duplicate.duplicates), len(duplicate.conflicts)) == (0, 2, 0)
    assert target_library.import_confirmed(bundle, 'target', duplicate) == 0
    with pytest.raises(ValueError, match='已变化'):
        target_library.import_confirmed(bundle, 'target', review)

    accepted, rejected, foreign = scan_samples(target.root / 'samples/target', 'target')
    assert len(accepted) == 1 and not rejected and not foreign
    assert review_selection('target', None, target.task_root('symbol'), '字体')['coverage']
    moved, errors = inventory(target, 'target')
    assert not errors and {row.task for row in moved} == {'task-han', 'task-symbol'}
    assert {row.origin[0] for row in moved} == {'source'}
    assert read_row(moved[0]) == raw_symbol
    assert {row.path.with_suffix('.raw').read_bytes() for row in moved} == before
    forwarded = tmp_path / 'forwarded.inkcapture'
    export_bundle(forwarded, 'target', '中转', moved)
    assert open_bundle(forwarded).writer == 'target'
    assert {sample.raw for sample in open_bundle(forwarded).samples} == before
    assert len(SampleLibrary(sender).review(open_bundle(forwarded), 'source').duplicates) == 2
    assert {path.read_bytes() for path in paths} == before


def test_conflicts_and_changed_bytes_are_rejected(tmp_path):
    target = catalog(tmp_path / 't', 'same')
    raw = {**specimen('1'), 'writer_id': 'same'}
    original = write(target, 'symbol', 'same', raw)
    fresh = {**specimen('2', 'new'), 'writer_id': 'same'}
    legacy = tmp_path / 'source.zip'
    with ZipFile(legacy, 'w') as archive:
        archive.writestr('1.json', json.dumps({**raw, 'note': 'new content with the same ID'}))
        archive.writestr('2.json', json.dumps(fresh))
    bundle = open_source(legacy)
    review = SampleLibrary(target).review(bundle, 'same')
    assert len(review.new) == len(review.conflicts) == 1 and not review.duplicates
    before = original.read_bytes()
    assert SampleLibrary(target).import_confirmed(bundle, 'same', review) == 1
    assert original.read_bytes() == before

    good = tmp_path / 'good.inkcapture'
    rows, _ = inventory(target, 'same')
    export_bundle(good, 'same', '本机', rows)
    bad = tmp_path / 'bad.inkcapture'
    with ZipFile(good) as source, ZipFile(bad, 'w') as dest:
        for name in source.namelist():
            dest.writestr(name, source.read(name) + (b' ' if name == 'samples/00000.json' else b''))
    with pytest.raises(ValueError, match='哈希'):
        open_bundle(bad)
    with pytest.raises(ValueError, match='已变化'):
        read_row(replace(rows[0], raw_hash='0' * 64))
