"""Frozen no-split rule repair; reuse existing full-source and stroke fallback."""
from __future__ import annotations

import argparse
import copy
import gzip
import subprocess
from dataclasses import asdict
from pathlib import Path

from generate_v61_library import CORRECTIONS, DB, SOURCES, WRITERS, digest, dump, encoded
from run_v61_author_strokes import check_sources, decode, plan_sources
from run_v61_candidate_expansion import ARMS
from run_v61_positional_variants import load

from inkstruct.glyph_frame_exp import reference_frame
from inkstruct.profile import load_profile
from inkstruct.reuse_rules import RULES, VERSION
from inkstruct.structure_corrections import CorrectedStructureRepository
from inkstruct.structures import StructureRepository
from inkstruct.trajectory_experiment import (
    SharedTransform,
    assemble,
    crossing_pairs,
    invariants,
    path_length,
)
from inkstruct.v6_exp import FullReferenceGenerator
from inkstruct.v6_integrated_exp import framed_graph
from inkstruct.v61_author_strokes import AuthorStrokeFallback
from inkstruct.v61_candidate_expansion import CandidateExpansionGenerator
from inkstruct.v61_contacts import contact_pairs
from inkstruct.v61_exp import Placement, curves

PRIOR=Path('artifacts/v61_author_strokes_20261014/run_source_aware')
PLANS=Path('artifacts/v61_positional_variants_20261014/run_final')
CHARS='群饿儒而相荡叵铜伯'


def restore(rows):
    return {p['component_id']:Placement(p['component_id'],tuple(p['ids']),tuple(p['indices']),
            p['candidate'],SharedTransform(**p['transform']),p['base_score']) for p in rows}


def geometry(before,after,graph):
    # Top-level structural ownership, not one owner per fallback stroke.
    root=next(n for n in graph.components if n.path=='root')
    owner={sid:n.component_id for n in graph.components if n.component_id in root.children_ids for sid in n.stroke_ids}
    external=lambda pairs:sorted((a+1,b+1) for a,b in pairs
        if owner.get(graph.strokes[a].stroke_id,'root') != owner.get(graph.strokes[b].stroke_id,'root'))
    bc,ac=curves(before),curves(after)
    result={'new_crossings':sorted(crossing_pairs(ac)-crossing_pairs(bc)),
            'new_external_crossings':external(crossing_pairs(ac)-crossing_pairs(bc)),
            'contacts':{}}
    for width in [.014,.028,.05]:
        old,new=contact_pairs(bc,width),contact_pairs(ac,width)
        result['contacts'][str(width)]={'new_pairs':sorted(new-old),'lost_pairs':sorted(old-new),
                                        'new_external':external(new-old)}
    return result


def run(out):
    out.mkdir(parents=True,exist_ok=False)
    inputs=[DB,*CORRECTIONS,*SOURCES.values(),*[PRIOR/w/f'{ord(c):04X}.json.gz' for w in WRITERS for c in CHARS],
            *[PLANS/w/f'{ord(c):04X}.json.gz' for w in WRITERS for c in CHARS]]
    hashes={str(p):digest(p) for p in inputs}
    dump(out/'protocol.json',{'version':VERSION,'rules':RULES,'inputs':hashes,
        'code':{str(p):digest(p) for p in [Path(__file__),*Path('src/inkstruct').glob('*.py')]},
        'git_head':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
        'production_priority':['whole author glyph','complete component','key stroke replacement','author stroke','explicit gap'],
        'validation':'all same-character donors excluded; development/regression only',
        'arms':{'A':'saved D from c84fef5 experiment, rules off','B':'rules on; repair only forbidden source units'},
        'fixed':'archives, corrected reference, old transforms and all unblocked strokes',
        'parameters':'unchanged candidate expansion and author stroke fallback parameters',
        'target_originals_used':False,'production_default_changed':False})
    base=StructureRepository(DB);target=CorrectedStructureRepository(base,*CORRECTIONS)
    summary=[]
    for w in WRITERS:
        profile=load_profile(SOURCES[w])
        engine=CandidateExpansionGenerator(profile,base,target,split_rules=True)
        legacy=CandidateExpansionGenerator(profile,base,target,split_rules=False)
        single=AuthorStrokeFallback(profile,base)
        (out/w).mkdir()
        for char in CHARS:
            saved=load(PRIOR/w/f'{ord(char):04X}.json.gz')['arms']['D']
            a=decode(saved['glyph']);provenance={int(k):v for k,v in saved['provenance'].items()}
            plans=restore(load(PLANS/w/f'{ord(char):04X}.json.gz')['arms']['new_G']['provenance'])
            raw=target.get(char);graph=framed_graph(raw,reference_frame(raw))
            ctx=copy.copy(legacy.prepare(char))
            kept,removed=engine.filter_plan(ctx,plans)
            # Audit every already accepted full component, on both source and target.
            audits=[{'candidate':p.candidate,'target_ids':p.ids,'evidence':engine.reuse_evidence(ctx,p)} for p in plans.values()]
            b=a;bp=dict(provenance);search=[];fallback={};whole_inventory=[]
            if removed:
                bad_ids={sid for p in plans.values() if not engine.reuse_evidence(ctx,p)['accepted'] for sid in p.ids}
                bad_indices={i for i,s in enumerate(graph.strokes) if s.stroke_id in bad_ids}
                reference=FullReferenceGenerator(profile,graph.source_version).generate(graph)
                reset={i:{'points':curves(reference)[i],'pressure':[p.pressure for p in reference.strokes[i].points],
                          'time':[p.t_ms for p in reference.strokes[i].points]} for i in bad_indices}
                ctx.reference=assemble(a,reset,'no_split_diagnostic_reference')
                ctx.baseline=a
                ctx.baseline_crossings=crossing_pairs(curves(a));ctx.baseline_contacts=contact_pairs(curves(a))
                bp={i:p for i,p in provenance.items() if i not in bad_indices}
                # Try complete 尹/君 before fallback; permitted whole ancestors,
                # not their forbidden subunits. Other top-level parts stay locked.
                scope=set(bad_ids)
                rule_graph=engine.rule_graph(char,side='target')
                for n in rule_graph.components:
                    if n.canonical in ('尹','君') and bad_ids <= set(n.stroke_ids):
                        scope.update(n.stroke_ids)
                inventory=engine.inventory(True)
                for key,entries in inventory.items():
                    if key[0] in ('尹','君'):
                        whole_inventory.extend({'identity':key,'candidate':q,'mapping_errors':errors}
                                               for _,_,q,errors in entries if q['character']!=char)
                ctx,b,new_plan,search=engine.extend(ctx,kept,ARMS['G_axes'],target_scope=scope)
                for p in new_plan.values():
                    bp.update(plan_sources([asdict(p)]))
                # Only newly missing slots are eligible; existing single-stroke
                # outputs outside the forbidden unit cannot be reselected.
                b,bp,fallback=single.fill(b,graph,[s.median for s in graph.strokes],bp)
            assert not invariants(b,graph)
            assert not check_sources(profile,b,bp)
            changed=[i+1 for i,(x,y) in enumerate(zip(curves(a),curves(b),strict=True)) if x!=y]
            record={'writer':w,'character':char,'rule_audits':audits,'removed':removed,
                'whole_candidates':whole_inventory,'search':search,'fallback':fallback,
                'rule_log':engine.rule_log,'A':saved,
                'B':{'glyph':asdict(b),'provenance':bp},
                'checks':{'protocol':invariants(b,graph),'source_exact':check_sources(profile,b,bp),
                    'changed_strokes':changed,'author_strokes':len(bp),'strokes':len(b.strokes),
                    'degenerate':[i+1 for i,s in enumerate(curves(b)) if path_length(s)<.003],
                    'geometry':geometry(a,b,graph)}}
            engine.rule_log=[]
            (out/w/f'{ord(char):04X}.json.gz').write_bytes(gzip.compress(encoded(record),mtime=0))
            summary.append({'writer':w,'character':char,'removed':len(removed),**record['checks']})
            print(w,char,'removed',len(removed),'changed',changed,flush=True)
        # Exhaustively verify no forbidden source extraction survives inventory.
        source_audit=[]
        for nested in (False,True):
            for entries in engine.inventory(nested).values():
                for _,_,q,_ in entries:
                    ev=engine.reuse_rules.check(engine.rule_graph(q['character'],side='source'),q['stroke_ids'],side='source')
                    assert ev['accepted'],ev
            source_audit.append({'nested':nested,'accepted_inventory_checked':sum(len(v) for v in engine.inventory(nested).values())})
        dump(out/w/'source_audit.json',{'checked':source_audit,
            'rejected_views':[r for logs in engine.view_log.values() for r in logs if r.get('version')==VERSION],
            'other_rule_log':engine.rule_log})
    assert hashes=={str(p):digest(p) for p in inputs}
    dump(out/'summary.json',summary)
    dump(out/'freeze.json',{'outputs':{str(p):digest(p) for p in out.glob('*/*.json.gz')},'originals_opened':False})


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    run(p.parse_args().output)
