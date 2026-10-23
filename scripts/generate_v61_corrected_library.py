"""Independent, resumable full-library review with current v6.1 author fallbacks.

Preserves reviewed placements; regenerates their full points from hashed archives.
New characters use current component expansion, no-split and positional guards.
"""
from __future__ import annotations

import argparse
import gzip
import json
import subprocess
import time
import traceback
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from pathlib import Path

from generate_v61_library import (
    CORRECTIONS,
    DB,
    REVIEW,
    SOURCES,
    WRITERS,
    atomic,
    digest,
    dump,
    encoded,
    generate,
    svg,
)
from run_v61_author_strokes import check_sources, decode, hybrid, plan_sources
from run_v61_candidate_expansion import ARMS
from run_v61_no_split import geometry, restore
from run_v61_positional_variants import load

from inkstruct.geometry import path_length
from inkstruct.glyph_frame_exp import reference_frame
from inkstruct.profile import load_profile
from inkstruct.reuse_rules import RULES, VERSION
from inkstruct.structure_corrections import CorrectedStructureRepository
from inkstruct.structures import StructureRepository
from inkstruct.trajectory_experiment import SharedTransform, assemble, invariants
from inkstruct.v6_exp import FullReferenceGenerator
from inkstruct.v6_integrated_exp import framed_graph
from inkstruct.v61_author_strokes import PARAMETERS
from inkstruct.v61_author_strokes_batch import BatchAuthorStrokeFallback
from inkstruct.v61_candidate_expansion import CandidateExpansionGenerator
from inkstruct.v61_exp import curves

NO_SPLIT = Path('artifacts/v61_no_split_20261014/run_verified')
SINGLES = Path('artifacts/v61_author_strokes_20261014/run_source_aware')
POSITIONAL = Path('artifacts/v61_positional_variants_20261014/run_final')
OLD_LIBRARY = Path('artifacts/v61_full_library_20261014/run_v1')
LABELS = {'author_complete_component':'完整部件', 'author_hybrid_retained':'关键笔替换·保留部件',
          'author_hybrid_key':'关键笔替换', 'author_single_stroke':'作者单笔'}


def replay(profile, reference, sources):
    pieces = {}
    for i, p in sources.items():
        sample = profile.source_trajectories[p['sample_id']]
        assert sample.character != reference.character and sample.source_sha256 == p['source_sha256']
        s = next(s for s in sample.strokes if s.standard_stroke_id == p['source_stroke_id'])
        pieces[i] = {'points': SharedTransform(**p['transform']).apply(s.points), 'pressure': s.pressure, 'time': s.t_ms}
    glyph = assemble(reference, pieces, 'v61_reviewed_author_source')
    for i, p in sources.items():
        s = next(s for s in profile.source_trajectories[p['sample_id']].strokes if s.standard_stroke_id == p['source_stroke_id'])
        glyph.strokes[i].confidence = s.confidence
        glyph.strokes[i].component_key = p.get('target_component')
    return glyph


def source_audit(engine, graph, sources):
    groups = {}
    for i, p in sources.items():
        if p['kind'] != 'author_complete_component':
            continue  # Individual strokes are intentionally not blocked by component split rules.
        key = (p['target_component'], p['sample_id'])
        groups.setdefault(key, []).append((i, p))
    for group in groups.values():
        for side, char, ids in [
            ('target', graph.character, [graph.strokes[i].stroke_id for i, _ in group]),
            ('source', group[0][1]['character'], [p['source_stroke_id'] for _, p in group])]:
            ev = engine.reuse_rules.check(engine.rule_graph(char, side=side), ids, side=side)
            if not ev['accepted']:
                raise ValueError(f'forbidden inherited source: {ev}')


def compact_sources(graph, sources, trials):
    by_id = {r['target_stroke_id']: r for r in trials}
    rows, donors, gaps = [], [], []
    for i, s in enumerate(graph.strokes):
        if i in sources:
            p = sources[i]
            rows.append({'order':i+1, 'standard_id':s.stroke_id, **p})
            donors.append({'character':p['character'], 'sample_id':p['sample_id'], 'orders':[i+1],
                           'source_stroke_id':p['source_stroke_id'], 'kind':p['kind'],
                           'label':LABELS.get(p['kind'],p['kind'])})
        else:
            evidence = by_id.get(s.stroke_id, {'reason':'no admitted author stroke; retained diagnostic reference'})
            gap = {'order':i+1, 'standard_id':s.stroke_id, **evidence}
            gaps.append(gap)
            rows.append({**gap, 'kind':'explicit_gap', 'display':'diagnostic reference only'})
    return rows, donors, gaps


def display_svg(glyph, sources):
    # Diagnostic reference is visible but never disguised as an author stroke.
    data = asdict(glyph)
    for i, s in enumerate(data['strokes']):
        s['style_source'] = 'author' if i in sources else 'reference'
    return svg(data).decode().replace('<g fill=', '<style>.reference{stroke:#c77b42;stroke-dasharray:.012 .008}</style><g fill=').encode()


def classify_inherited_contacts(geometry_checks, sources):
    """Do not present preserved source-component internals as boundary damage."""
    def inherited(pair):
        a, b = (sources.get(i-1) for i in pair)  # geometry external lists use 1-based orders.
        return (a is not None and b is not None and
                a['kind'] in ('author_complete_component','author_hybrid_retained') and
                a['kind'] == b['kind'] and a['sample_id'] == b['sample_id'] and
                a.get('target_component') == b.get('target_component') and a['transform'] == b['transform'])
    geometry_checks['inherited_source_crossings'] = [p for p in geometry_checks['new_external_crossings'] if inherited(p)]
    geometry_checks['new_external_crossings'] = [p for p in geometry_checks['new_external_crossings'] if not inherited(p)]
    for item in geometry_checks['contacts'].values():
        item['inherited_source_contacts'] = [p for p in item['new_external'] if inherited(p)]
        item['new_external'] = [p for p in item['new_external'] if not inherited(p)]
    return geometry_checks


def worker(writer, chars, root_string, shard):
    root = Path(root_string); out = root/writer; out.mkdir(exist_ok=True)
    base = StructureRepository(DB); target = CorrectedStructureRepository(base,*CORRECTIONS)
    profile = load_profile(SOURCES[writer]); engine = CandidateExpansionGenerator(profile,base,target,split_rules=True)
    single = BatchAuthorStrokeFallback(profile,base)
    engine.inventory(True)
    review = load(REVIEW)
    profile_hash = digest(SOURCES[writer])
    counters = Counter(); start = time.monotonic()
    for number, char in enumerate(chars,1):
        stem = out/f'{ord(char):04X}'; rp = stem.with_suffix('.json')
        if rp.exists():
            row = load(rp)
            if any(not (root/f).is_file() or digest(root/f)!=h for f,h in row['files'].items()):
                raise RuntimeError(f'corrupted completed output: {rp}')
            counters[row['status']]+=1; counters['resumed']+=1
            continue
        row = {'writer': writer,'character': char,'files': {},'warnings': [],'same_character_reuse': False}
        try:
            raw = target.get(char); graph = framed_graph(raw,reference_frame(raw))
            reference = FullReferenceGenerator(profile,graph.source_version).generate(graph)
            frozen = NO_SPLIT/writer/f'{ord(char):04X}.json.gz'
            prior = SINGLES/writer/f'{ord(char):04X}.json.gz'
            positional = POSITIONAL/writer/f'{ord(char):04X}.json.gz'
            logs = {}; regression = None
            if frozen.exists() or prior.exists():
                path = frozen if frozen.exists() else prior
                saved = load(path)
                saved = saved['B'] if frozen.exists() else saved['arms']['D']
                sources = {int(k):v for k,v in saved['provenance'].items()}
                glyph = replay(profile,reference,sources)
                source_audit(engine,graph,sources)
                regression = curves(glyph) == curves(decode(saved['glyph']))
                if not regression:
                    raise ValueError('reviewed geometry replay drift')
                logs['reviewed_plan'] = {'file':str(path),'sha256':digest(path)}
                # Fill only existing gaps, using exactly the same frozen stroke policy.
                glyph,sources,fill = single.fill(glyph,graph,[s.median for s in graph.strokes],sources)
            else:
                if positional.exists():
                    saved = load(positional)
                    ctx = engine.prepare(char)
                    plan = restore(saved['arms']['new_G']['provenance'])
                    ctx,glyph,plan,logs['repair'] = engine.repair(ctx,plan,ARMS['G_axes'])
                    logs['reviewed_plan'] = {'file':str(positional),'sha256':digest(positional)}
                else:
                    ctx,glyph,plan,logs['base'] = generate(engine,char,writer,review)
                    ctx,glyph,plan,logs['expansion'] = engine.extend(ctx,plan,ARMS['G_axes'])
                sources = plan_sources([asdict(p) for p in plan.values()])
                source_audit(engine,graph,sources)
                if positional.exists():
                    glyph,sources,logs['hybrid'] = hybrid(single,saved,glyph,graph,[s.median for s in graph.strokes],sources)
                glyph,sources,fill = single.fill(glyph,graph,[s.median for s in graph.strokes],sources)
            errors = invariants(glyph,graph)
            source_errors = check_sources(profile,glyph,sources)
            if errors or source_errors:
                raise ValueError(f'protocol/source integrity: {errors}, {source_errors}')
            old_path = OLD_LIBRARY/writer/f'{ord(char):04X}.json.gz'
            old = decode(load(old_path)['glyph'])
            geom = classify_inherited_contacts(geometry(old,glyph,raw),sources)
            degenerate = [i+1 for i,c in enumerate(curves(glyph)) if path_length(c)<.003]
            stroke_rows,donors,gaps = compact_sources(graph,sources,fill['trials'])
            if gaps: row['warnings'].append(f'作者来源缺口 {len(gaps)} 笔（橙色虚线）')
            if degenerate: row['warnings'].append('短/退化笔画待审查')
            if geom['new_external_crossings']: row['warnings'].append('相对旧全库新增跨部件交叉，待人工审查')
            if geom['contacts']['0.028']['new_external']: row['warnings'].append('相对旧全库新增跨部件笔宽接触，待人工审查')
            checks = {'protocol':errors,'source_integrity':source_errors,'degenerate':degenerate,'geometry':geom}
            if regression is not None: checks['regression_exact']=regression
            row.update(status='warning' if row['warnings'] else 'complete', strokes=len(glyph.strokes),
                source_strokes=len(sources), reference_strokes=len(gaps), missing=gaps,
                source_kinds=dict(Counter(p['kind'] for p in sources.values())),donors=donors,
                checks=checks,author_only_ready=not gaps,
                axis_strokes=sum(abs(p['transform']['sx']-p['transform']['sy'])>1e-12 for p in sources.values()),
                stroke_sources=stroke_rows)
            payload = {'glyph':asdict(glyph),'provenance':sources,'stroke_sources':stroke_rows,
                       'logs':logs,'fallback':fill,'rule_log':engine.rule_log,'checks':checks,
                       'missing':gaps,'author_only_ready':not gaps,'source_profile_sha256':profile_hash}
            for path,data in [(stem.with_suffix('.json.gz'),gzip.compress(encoded(payload),mtime=0)),
                              (stem.with_suffix('.svg'),display_svg(glyph,sources))]:
                atomic(path,data); row['files'][str(path.relative_to(root))]=digest(path)
        except Exception as exc:  # noqa: BLE001 -- every failed glyph remains visible
            row.update(status='failed',error=f'{type(exc).__name__}: {exc}',traceback=traceback.format_exc())
        dump(rp,row); counters[row['status']]+=1
        engine.rule_log=[]
        if number%25==0 or number==len(chars):
            progress={'writer':writer,'shard':shard,'processed':number,'total':len(chars),**counters,
                      'elapsed_seconds':round(time.monotonic()-start,1)}
            dump(out/f'progress_{shard}.json',progress);print(json.dumps(progress),flush=True)
        if number%100==0:
            target._cache.clear()
            engine._rule_graphs={k:v for k,v in engine._rule_graphs.items() if k[0]=='source'}
    return {'writer':writer,'shard':shard,**counters}


def freeze(chars):
    inputs=[DB,*CORRECTIONS,REVIEW,*SOURCES.values()]
    for folder in (NO_SPLIT,SINGLES,POSITIONAL):
        inputs += [p for p in folder.glob('*/*.json.gz') if chr(int(p.name.split('.')[0],16)) in chars]
    # Freeze the exact previous glyphs used only for geometry comparison.
    inputs += [OLD_LIBRARY/w/f'{ord(c):04X}.json.gz' for w in WRITERS for c in chars]
    code=[Path(__file__),*Path('src/inkstruct').glob('*.py')]
    code += [Path('scripts')/n for n in ('generate_v61_library.py','report_v61_library.py',
              'report_v61_corrected_library.py','run_v61_author_strokes.py','run_v61_no_split.py',
              'run_v61_candidate_expansion.py','run_v61_positional_variants.py')]
    return {'name':'current corrected v6.1 exp four-author library','characters':chars,'writers':list(WRITERS),
            'baseline_commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
            'inputs':{str(p):digest(p) for p in inputs},'code':{str(p):digest(p) for p in code},
            'pipeline':'reviewed plans replayed from source; current guarded expansion; existing key replacement; author stroke fallback; explicit gaps',
            'split_rules':True,'rule_version':VERSION,'rules':RULES,'author_stroke_fallback':True,
            'parameters':PARAMETERS,'component_policy':asdict(ARMS['G_axes']),
            'same_character_sources_excluded':True,'archives_rebuilt':False,'production_changed':False,
            'whole_character_priority':'excluded in this cross-character review; not production replay mode',
            'key_replacement_scope':'existing audited positional plans only; no new generalized key substitution',
            'batch_acceleration':'cached affine-equivalent retrieval descriptors; unchanged full output and admission rules',
            'display':'same 0.028 width; missing author strokes are orange dashed diagnostic reference',
            'evaluation':'full-library visual review, not held-out validation; warnings are not automatic defects'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--characters')
    p.add_argument('--workers',type=int,default=8);p.add_argument('--shards',type=int,default=2)
    p.add_argument('--resume',action='store_true')
    args=p.parse_args();chars=list(dict.fromkeys(args.characters)) if args.characters else StructureRepository(DB).characters()
    manifest=freeze(chars)
    if args.resume:
        old=load(args.output/'protocol.json')
        for key in ('characters','inputs','code','pipeline','split_rules','author_stroke_fallback'):
            if old[key]!=manifest[key]:raise ValueError(f'resume refused: changed {key}')
    else:
        args.output.mkdir(parents=True,exist_ok=False);dump(args.output/'protocol.json',manifest)
    jobs=[(w,chars[s::args.shards],str(args.output),s) for w in WRITERS for s in range(args.shards)]
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures=[pool.submit(worker,*job) for job in jobs]
        results=[f.result() for f in futures]
    for group in ('inputs','code'):
        for path,h in manifest[group].items():
            if digest(path)!=h:raise ValueError(f'frozen {group} drift: {path}')
    dump(args.output/'workers.json',results)
    from report_v61_corrected_library import report
    report(args.output,chars)


if __name__=='__main__':main()
