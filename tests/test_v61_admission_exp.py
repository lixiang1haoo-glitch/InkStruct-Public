import copy
from dataclasses import asdict

import pytest
from test_component_generation import make_graph
from test_source_generation_entry import fixture

from inkstruct.v61_admission_exp import (
    AdmissionProbeGenerator,
    classify_crossings,
    ordered_root_correspondence,
)


def test_root_bridge_requires_identity_count_and_ordered_reference_correspondence():
    target=make_graph('池','也')
    node=next(n for n in target.components if n.canonical=='也')
    source=copy.deepcopy(target)
    source.character='也'
    source.strokes=[s for s in source.strokes if s.stroke_id in node.stroke_ids]
    root=copy.deepcopy(node);root.path='root'
    source.components=[root]
    evidence=ordered_root_correspondence(source,target,node)
    assert evidence['source_ids']==evidence['target_ids']==node.stroke_ids
    assert evidence['reference_max_error']<1e-12
    bad=copy.deepcopy(source);bad.character='他'
    with pytest.raises(ValueError,match='identity'):
        ordered_root_correspondence(bad,target,node)
    bad=copy.deepcopy(source);bad.strokes.pop()
    with pytest.raises(ValueError,match='count'):
        ordered_root_correspondence(bad,target,node)
    bad=copy.deepcopy(source);bad.strokes.reverse()
    with pytest.raises(ValueError,match='correspondence|direction'):
        ordered_root_correspondence(bad,target,node)


def test_review_allows_only_inherited_pairs_never_external_collision():
    source=[[(.2,.2),(.8,.8)],[(.2,.8),(.8,.2)]]
    before=[[(.2,.2),(.8,.2)],[(.2,.8),(.8,.8)],[(.9,.1),(.9,.9)]]
    after=source+[before[-1]]
    unreviewed=classify_crossings(before,after,source,(0,1))
    assert unreviewed['unexplained_new_pairs']==[(0,1)]
    reviewed=classify_crossings(before,after,source,(0,1),[(0,1)])
    assert reviewed['internal_topology_preserved'] and not reviewed['unexplained_new_pairs']
    collided=source+[[(.5,.1),(.5,.9)]]
    bad=classify_crossings(before,collided,source,(0,1),[(0,1)])
    assert bad['unexplained_new_pairs']==[(0,2),(1,2)]
    changed=classify_crossings(before,before,source,(0,1),[(0,1)])
    assert not changed['internal_topology_preserved']


def test_off_switch_replays_baseline_and_stale_review_is_rejected(tmp_path):
    _,repo,_,profile,_=fixture(tmp_path)
    snapshot=asdict(profile)
    engine=AdmissionProbeGenerator(profile,repo,repo)
    ctx=engine.prepare('池')
    glyph,plan,log=engine.probe(ctx)
    assert [asdict(s)['points'] for s in glyph.strokes]==[asdict(s)['points'] for s in ctx.baseline.strokes]
    assert plan==ctx.baseline_plan and not log['placement']
    p=next(iter(ctx.baseline_plan.values()))
    review={'source':{k:p.candidate[k] for k in ('sample_id','source_sha256','component_id','stroke_ids')},
            'target_context':'wrong','source_internal_pairs':[]}
    review['source']['source_sha256']='stale'
    with pytest.raises(ValueError,match='review identity'):
        engine.attempt(ctx,ctx.baseline_plan,p,review)
    assert asdict(profile)==snapshot
