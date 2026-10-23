"""One capture feeds explicit width variants without changing recorded points."""
import csv
import io
import json
from hashlib import sha256

import pytest
from test_symbol_provider import specimen

from inkstruct.assets.resolver import AssetResolver, gap_capture_csv
from inkstruct.document.editing import SourceSession
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.package import load_package, save_package
from inkstruct.document.resources import inspect_resources
from inkstruct.document.schema import PageProfile, StyleProfile
from inkstruct.fonts.core import FontPackage, decode, to_user
from inkstruct.fonts.importer import build_font
from inkstruct.layout.blocks import layout_markdown
from inkstruct.plotter.adapters import plan_from_snapshot
from inkstruct.plotter.svg import page_svg
from inkstruct.punctuation import CHINESE_PUNCTUATION, SHARED_PUNCTUATION, capture_character
from inkstruct.symbol_capture import CAPTURE_CHARACTERS, CHARACTERS, parse_symbol_file, symbol_info
from inkstruct.symbol_tasks import TASK_GROUPS, imported_entries, task_plan


def test_collection_canonicalization_and_distinct_shapes(tmp_path):
    p = tmp_path/'punctuation.txt'
    p.write_text('，,？?（）()。.【】《》“”‘’、—−-…', encoding='utf-8')
    chars = [c for c, _, _ in parse_symbol_file(p)]
    assert chars == list(',?()。.【】《》“”‘’、—−-…')
    assert len(CHARACTERS)==len(set(CHARACTERS))
    assert set(CAPTURE_CHARACTERS)=={capture_character(c) for c in CHARACTERS}
    _, entries = task_plan(TASK_GROUPS)
    assert len(entries)==260 and sum(n for _, n, _ in entries)==1300
    assert not any(c in SHARED_PUNCTUATION for c, _, _ in entries)
    assert set(CHINESE_PUNCTUATION)<={c for c, _, _ in entries}
    assert symbol_info('（')['math_class_hint']=='open'
    assert symbol_info('）')['math_class_hint']=='close'
    p = tmp_path/'conflict.csv'
    with p.open('w',encoding='utf-8',newline='') as f:
        writer=csv.writer(f); writer.writerow(['character','repeats'])
        writer.writerows([(',',5),('，',3)])
    with pytest.raises(ValueError,match='份数不一致'):
        parse_symbol_file(p)
    assert imported_entries(('punctuation','brackets'), [('，',5,0),(',',5,1),('（',3,2)])==[(',',5,0),('(',3,1)]


def test_capture_gap_csv_deduplicates_width_variants():
    doc=parse_markdown(',，?？。.【】')
    report=inspect_resources(doc,AssetResolver())
    rows=list(csv.DictReader(io.StringIO(gap_capture_csv(report['gaps']))))
    assert [r['character'] for r in rows]==list(',?。.【】')
    assert all(r['repeats']=='5' for r in rows)


def test_shared_font_points_provenance_and_portable_reopen(tmp_path):
    folder=tmp_path/'symbols'; folder.mkdir()
    originals={}
    for c in '123,?()。':
        p=folder/f'{ord(c)}.json'
        raw=json.dumps(specimen(c,f'sample-{ord(c)}'),ensure_ascii=False).encode('utf-8')
        p.write_bytes(raw); originals[p]=sha256(raw).hexdigest()
    dev=tmp_path/'shared.inkfont'
    build_font(dev,writer='fixture',name='shared',symbols=folder)
    font=FontPackage(dev); font.verify()
    pools={c:next(font.glyphs(c)) for c in font.pools}
    for original, target in [(',', '，'),('?', '？'),('(', '（'),(')', '）')]:
        a,b=pools[original],pools[target]
        ac,bc=decode(a.original_json),decode(b.original_json)
        assert ac['trajectory']['strokes']==bc['trajectory']['strokes']
        assert a.strokes==b.strokes
        assert ac['record']['geometry_hash']==bc['record']['geometry_hash']
        assert ac['record']['pressure_hash']==bc['record']['pressure_hash']
        assert ac['record']['time_hash']==bc['record']['time_hash']
        assert b.metrics.advance==1 and a.metrics.advance<1
        assert bc['summary']['shared_punctuation']['source_character']==original
        assert bc['summary']['review_status']=='unreviewed'
    assert '、' not in pools and '.' not in pools  # No unrelated shape substitutions.
    user=tmp_path/'user.inkfont'; to_user(dev,user)
    assert FontPackage(user).manifest['core_hash']==font.manifest['core_hash']
    session=SourceSession('1，2（3）？。')
    resolver=AssetResolver(embedded=font.glyphs())
    before=layout_markdown(parse_markdown(session),resolver)
    assert before.plotter_exportable, before.diagnostics
    svg=[page_svg(p) for p in plan_from_snapshot(before).pages]
    path=tmp_path/'shared.inkdoc'
    save_package(path,session,resolver,PageProfile(),StyleProfile())
    restored=load_package(path)
    after=layout_markdown(parse_markdown(restored.session),restored.resolver)
    assert before==after and restored.session.source==session.source
    assert [page_svg(p) for p in plan_from_snapshot(after).pages]==svg
    assert all(sha256(p.read_bytes()).hexdigest()==h for p,h in originals.items())


def test_explicit_fullwidth_recording_takes_precedence(tmp_path):
    folder=tmp_path/'samples'; folder.mkdir()
    for c,h in [(',',10),('，',20)]:
        (folder/f'{ord(c)}.json').write_text(json.dumps(specimen(c,str(ord(c)),height=h)),encoding='utf-8')
    path=tmp_path/'explicit.inkfont'
    build_font(path,writer='fixture',name='explicit',symbols=folder)
    font=FontPackage(path)
    assert len(font.records)==2
    a,b=next(font.glyphs(',')),next(font.glyphs('，'))
    assert a.strokes!=b.strokes
    assert 'shared_punctuation' not in decode(b.original_json)['summary']
