"""Handwritten punctuation uses actual ink width, with no Chinese cell padding."""

import json
import zipfile
from dataclasses import asdict, replace

import pytest
from PySide6 import QtCore
from test_latin_spacing import captured

from inkstruct.assets.resolver import AssetResolver
from inkstruct.document.editing import SourceSession
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.package import load_package, save_package
from inkstruct.document.schema import Occurrence, PageProfile, SourceSpan, StyleProfile
from inkstruct.document.styles import FlowStyle
from inkstruct.global_defaults import GlobalDefaultsStore, LayoutDefaults
from inkstruct.layout.blocks import layout_markdown
from inkstruct.layout.inline import InlineRun, measure_runs
from inkstruct.layout.measurement_cache import MeasurementCache, measurement_scope
from inkstruct.renderers.pages import page_svg


@pytest.mark.parametrize('char', list('，。！？、（）；：“”,.?!()'))
def test_no_half_or_full_cell_and_capture_offset_is_removed(char):
    o = Occurrence('one','node',SourceSpan(0,1),char)
    values=[]
    for left in (.1,.7):
        r = AssetResolver(embedded=[captured(char,left)])
        boxes,issues=measure_runs([InlineRun(o)],r,StyleProfile(),punctuation_spacing='handwriting')
        assert not issues
        b=boxes[0]
        assert b.advance == pytest.approx(.18*6+.3)
        assert b.origin_offset+b.glyph.bounds[0]*6-.15 == pytest.approx(.04*6)
        assert b.advance < .5*6
        values.append(b.advance)
    assert values[0] == pytest.approx(values[1])


def test_code_math_spaces_han_and_digits_keep_original_geometry_and_cache_is_separate():
    r=AssetResolver(embedded=[captured(c,.6) for c in ',.中1A'],builtin_numbers=True)
    source=SourceSession('中1A ,1.\n\n`,.`\n\n$1,1$')
    doc=parse_markdown(source)
    cache=MeasurementCache()
    with measurement_scope(cache):
        old=layout_markdown(doc,r)
        choices=r.selection_records()
        new=layout_markdown(doc,r,flow=FlowStyle(punctuation_spacing='handwriting'))
        assert new==layout_markdown(doc,r,flow=FlowStyle(punctuation_spacing='handwriting'))
    assert r.selection_records()==choices and cache.reused>0
    assert all(a.advance_mm==b.advance_mm for a,b in zip(old.fragments[:4],new.fragments[:4]))
    assert [f.advance_mm for f in old.fragments[-5:]]==[f.advance_mm for f in new.fragments[-5:]]
    assert new.fragments[4].advance_mm < old.fragments[4].advance_mm


@pytest.mark.parametrize('named', [False,True])
def test_new_policy_roundtrips_as_v4_without_changing_samples_or_source(tmp_path,named):
    from inkstruct.document.flow_template import FlowTemplate
    session=SourceSession('1，2。（3）\n\n|1，2|\n|---|\n|3。|')
    r=AssetResolver(embedded=[captured(c,.6) for c in '，。（）'],builtin_numbers=True)
    raw={g.asset_id:g.original_json for pool in r.pools.values() for g in pool}
    flow=FlowStyle(punctuation_spacing='handwriting',template=FlowTemplate() if named else None)
    assert flow.schema_version=='inkstruct_flow_style_v4'
    before=layout_markdown(parse_markdown(session,field_blocks=named),r,flow=flow)
    path=tmp_path/'new.inkdoc'
    save_package(path,session,r,PageProfile(),StyleProfile(),flow=flow)
    loaded=load_package(path)
    after=layout_markdown(parse_markdown(loaded.session,field_blocks=named),loaded.resolver,flow=loaded.flow)
    assert loaded.flow==flow and loaded.session.atom_ids==session.atom_ids
    assert r.selection_records()==loaded.resolver.selection_records()
    assert {g.asset_id:g.original_json for pool in loaded.resolver.pools.values() for g in pool}==raw
    assert [page_svg(before,i,debug=not before.exportable) for i in range(len(before.pages))]==[page_svg(after,i,debug=not after.exportable) for i in range(len(after.pages))]


def test_old_saved_style_does_not_emit_new_fields_or_change_optimize(tmp_path):
    path=tmp_path/'old.inkdoc'
    save_package(path,SourceSession('1'),AssetResolver(builtin_numbers=True),PageProfile(),StyleProfile(),optimize=False)
    with zipfile.ZipFile(path) as z:
        assert 'punctuation_spacing' not in json.loads(z.read('styles.json'))['flow']
    loaded=load_package(path)
    assert loaded.flow.punctuation_spacing=='capture' and loaded.optimize is False


@pytest.mark.parametrize('choice',['capture','handwriting'])
def test_default_upgrade_is_read_only_and_explicit_choice_is_persistent(tmp_path,choice):
    QtCore.QSettings.setDefaultFormat(QtCore.QSettings.IniFormat)
    QtCore.QSettings.setPath(QtCore.QSettings.IniFormat,QtCore.QSettings.UserScope,str(tmp_path))
    old=LayoutDefaults(flow=FlowStyle())
    record={'version':1,**asdict(old)}
    record['flow'].pop('punctuation_spacing');record['flow'].pop('latin_spacing')
    store=GlobalDefaultsStore()
    raw=json.dumps(record)
    store.settings.setValue(store.KEY,raw);store.settings.sync()
    store=GlobalDefaultsStore()
    upgraded,warning=store.load()
    assert warning is None and upgraded.flow.punctuation_spacing=='handwriting'
    assert store.settings.value(store.KEY)==raw
    assert store.settings.value(store.PUNCTUATION_DEFAULT_KEY) is None
    selected=replace(upgraded,flow=replace(upgraded.flow,punctuation_spacing=choice))
    store.save(selected)
    assert GlobalDefaultsStore().load()==(selected,None)


@pytest.mark.parametrize('value',['unknown',None,1])
def test_invalid_policy_is_rejected(value):
    with pytest.raises(ValueError):FlowStyle(punctuation_spacing=value)
