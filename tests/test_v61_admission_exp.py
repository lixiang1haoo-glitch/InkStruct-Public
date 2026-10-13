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


def source_fixture(tmp_path, paths):
    from inkstruct.source_trajectory import arc_parameters

    _,repo,_,profile,_=fixture(tmp_path)
    sample=profile.source_trajectories['沱']
    for stroke,xy in zip(sample.strokes[3:],paths,strict=True):
        stroke.points=xy
        stroke.pressure=[.5]*len(xy)
        stroke.t_ms=[12000+10*i for i in range(len(xy))]
        stroke.arc_parameters=arc_parameters(xy)
    engine=AdmissionProbeGenerator(profile,repo,repo)
    ctx=engine.prepare('池')
    proposal=ctx.pools['c_1'][0]
    plan={k:p for k,p in ctx.baseline_plan.items() if k!='c_1'}
    return engine,ctx,proposal,plan


def test_source_topology_is_not_defect_but_new_external_contact_still_blocks(tmp_path):
    from dataclasses import replace

    from inkstruct.trajectory_experiment import SharedTransform

    engine,ctx,p,plan=source_fixture(tmp_path,[[(.5,.3),(.85,.7)],[(.9,.3),(.9,.5)],[(.5,.7),(.85,.3)]])
    old,old_d=engine.attempt(ctx,plan,p)
    assert old==plan and not old_d['accepted']
    new,d=engine.attempt(ctx,plan,p,source_aware=True)
    assert d['accepted'] and new['c_1']==p
    assert d['source_mapping_evidence']['complete_ordered_mapping']
    assert d['topology']['source_inherited_pairs']==[(3,5)]
    assert not d['topology']['unexplained_new_pairs']
    # Place a source endpoint exactly on the other component's endpoint;
    # touching endpoints need not be strict transverse crossings.
    anchor=engine.emit(ctx,plan).strokes[0].points[0]
    x,y=engine.source(p)[0].points[0];t=p.transform
    moved=replace(p,transform=SharedTransform(t.sx,t.sy,anchor.x-t.sx*x,anchor.y-t.sy*y))
    rejected,rd=engine.attempt(ctx,plan,moved,source_aware=True)
    assert rd['new_cross_boundary_contacts']
    assert not rd['accepted'] and rejected==plan


def test_reference_length_difference_is_diagnostic_and_source_mapping_is_still_required(tmp_path):
    engine,ctx,p,plan=source_fixture(tmp_path,[[(.60,.3),(.62,.3)],[(.8,.3),(.8,.8)],[(.55,.8),(.7,.8)]])
    _,blocked=engine.attempt(ctx,plan,p,source_aware=True,reference_differences_diagnostic=False)
    new,d=engine.attempt(ctx,plan,p,source_aware=True)
    assert not blocked['accepted'] and 'length differs' in blocked['fallback_reason']
    assert d['accepted'] and new['c_1']==p
    assert 'length differs from reference' in d['reference_differences_diagnostic_only']
    engine.source(p)[0].confidence=.29
    with pytest.raises(ValueError,match='mapping below'):
        engine.attempt(ctx,plan,p,source_aware=True)


def test_expansion_switches_off_preserve_given_plan_and_identity(tmp_path):
    from dataclasses import replace

    _,repo,_,profile,_=fixture(tmp_path)
    engine=AdmissionProbeGenerator(profile,repo,repo);ctx=engine.prepare('池')
    g,plan,log=engine.expand(ctx,ctx.baseline_plan)
    assert plan==ctx.baseline_plan and not log['placement']
    assert [asdict(s)['points'] for s in g.strokes]==[asdict(s)['points'] for s in ctx.baseline.strokes]
    p=next(iter(plan.values()))
    partial=replace(p,ids=p.ids[:-1],indices=p.indices[:-1])
    with pytest.raises(ValueError,match='one-to-one'):
        engine.attempt(ctx,plan,partial,source_aware=True)
    anisotropic=replace(p,transform=replace(p.transform,sy=p.transform.sy*1.01))
    with pytest.raises(ValueError,match='isotropic'):
        engine.attempt(ctx,plan,anisotropic,source_aware=True)
