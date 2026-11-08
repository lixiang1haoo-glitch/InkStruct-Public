"""Visible, deterministic motion is measured before wrapping and preserves source assets."""
import json
import math
from dataclasses import replace
from itertools import pairwise

import pytest
from test_justification_han import normalized, render, resources

from inkstruct.document.editing import SourceSession
from inkstruct.document.han_variation import LEGACY, HanVariation, variation_record
from inkstruct.document.package import load_package, save_package
from inkstruct.document.schema import PageProfile, StyleProfile
from inkstruct.document.styles import FlowStyle
from inkstruct.layout.han_variation import varied_strokes
from inkstruct.plotter.adapters import plan_from_snapshot


def config(**kwargs):
    return HanVariation(enabled=True,strength=0,size_strength=0,spacing_strength=0,baseline_strength=0,**kwargs)


def test_high_shape_strength_has_visible_internal_stroke_changes():
    strokes=(((0,0),(2,0),(4,0)),((2,0),(2,2),(2,4)),((0,4),(2,4),(4,4)))
    low=replace(config(),strength=.1)
    high=replace(low,strength=.99)
    def displacement(result):
        return math.sqrt(sum(math.dist(a,b)**2 for old,new in zip(strokes,result) for a,b in zip(old,new))/9)
    assert displacement(varied_strokes(strokes,'same-character',high))>.08
    assert displacement(varied_strokes(strokes,'same-character',high))>5*displacement(varied_strokes(strokes,'same-character',low))
    assert varied_strokes(strokes,'same-character',high)==varied_strokes(strokes,'same-character',high)
    assert varied_strokes(strokes,'another-occurrence',high)!=varied_strokes(strokes,'same-character',high)


@pytest.mark.parametrize('seed',range(8))
def test_spacing_participates_in_line_breaking_and_justification(seed):
    initial=SourceSession('汉'*36,document_id='00000000000000000000000000000001')
    identity=initial.identity_record()
    identity['atom_ids']=[f"{i+1:032x}" for i in range(36)]
    session=SourceSession.restore(initial.source,identity)
    plain=render(session)
    natural=render(session,FlowStyle(paragraph_align='justify',han_variation=replace(config(),spacing_strength=1,seed=seed)))
    assert natural.plotter_exportable,natural.diagnostics
    first=[f for f in natural.fragments if f.line_index==0]
    gaps=[b.x_mm-a.x_mm for a,b in pairwise(first)]
    assert max(gaps)-min(gaps)>.1
    assert [f.occurrence_id for f in natural.fragments]==[f.occurrence_id for f in plain.fragments]
    assert natural.pages!=plain.pages
    for page in natural.pages:
        for f in page.fragments:
            assert f.ink_bounds[2]<=natural.page_profile.width_mm-natural.page_profile.margin_mm+1e-7
    plan_from_snapshot(natural)


def test_baselines_vary_without_breaking_stroke_shape_or_exportability():
    session=SourceSession('汉'*12)
    natural=render(session,FlowStyle(han_variation=replace(config(),baseline_strength=1)))
    assert natural.plotter_exportable,natural.diagnostics
    first=[f for f in natural.fragments if f.line_index==0]
    assert max(f.baseline_mm for f in first)-min(f.baseline_mm for f in first)>.1
    assert len({normalized(natural,f) for f in first})==1
    plan_from_snapshot(natural)


def test_all_zero_is_exact_and_code_math_latin_geometry_is_untouched():
    session=SourceSession('汉中文 `中文` $中$ abc')
    base=render(session)
    zero=render(session,FlowStyle(han_variation=config()))
    assert base.pages==zero.pages
    varied=render(session,FlowStyle(han_variation=HanVariation(enabled=True,strength=.99)))
    eligible={f.occurrence_id for f in base.fragments if f.span.start<3}
    by_id={f.occurrence_id:f for f in varied.fragments}
    for f in base.fragments:
        if f.occurrence_id not in eligible:
            assert normalized(base,f)==normalized(varied,by_id[f.occurrence_id])


def test_new_algorithm_roundtrips_exactly_and_never_changes_font_resources(tmp_path):
    session,resolver=SourceSession('汉'*30),resources()
    originals=tuple(g.original_json for pool in resolver.pools.values() for g in pool)
    flow=FlowStyle(han_variation=HanVariation(enabled=True,strength=.99,size_strength=.8,spacing_strength=.9,baseline_strength=.8,seed=998))
    before=render(session,flow,resolver=resolver)
    choices=resolver.selection_records()
    assert before.plotter_exportable,before.diagnostics
    target=tmp_path/'natural.inkdoc'
    save_package(target,session,resolver,PageProfile(46,160,5),StyleProfile(),flow=flow)
    loaded=load_package(target)
    after=render(loaded.session,loaded.flow,loaded.page,loaded.resolver)
    assert after==before
    assert resolver.selection_records()==choices
    assert tuple(g.original_json for pool in resolver.pools.values() for g in pool)==originals
    session.apply(0,0,'汉');session.undo()
    assert render(session,flow,resolver=resolver).pages==before.pages
    assert json.loads(json.dumps(variation_record(flow.han_variation)))['schema_version']=='inkstruct_han_variation_v2'


def test_legacy_record_has_no_new_fields_and_new_strengths_are_validated():
    old=HanVariation(enabled=True,strength=.35,schema_version=LEGACY)
    assert set(variation_record(old))=={'enabled','strength','seed','schema_version'}
    assert HanVariation(**variation_record(old))==old
    for name in ('size_strength','spacing_strength','baseline_strength'):
        for value in (-.1,1.1,float('nan'),True):
            with pytest.raises(ValueError):HanVariation(**{name:value})
