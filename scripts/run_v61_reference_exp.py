"""Frozen reference influence ablation; reuses v6.1 stages, sources and evaluation."""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path

import numpy as np
from run_v6_exp import sha, write
from run_v61_exp import WRITERS, check_integrity, dict_curves

from inkstruct.profile import load_profile
from inkstruct.structure_corrections import CorrectedStructureRepository
from inkstruct.structures import StructureRepository
from inkstruct.trajectory_experiment import stroke_metrics
from inkstruct.v61_contacts import contact_pairs, contact_report
from inkstruct.v61_exp import V61ExpGenerator
from inkstruct.v61_reference_exp import REFERENCE_PARAMETERS, ReferenceAblationGenerator

ARMS = ('A', 'R', 'B', 'C', 'D')
PRIOR = Path('artifacts/v61_exp_20261013/run_v2')
ARCHIVES = Path('artifacts/architecture_review_20261011/run_v1')


def run(root):
    root.mkdir(parents=True, exist_ok=False)
    pp = json.loads((PRIOR / 'protocol.json').read_text())
    # Historical source/data checks remain valid; code intentionally changes this turn.
    for p, h in pp['inputs'].items():
        assert sha(Path(p)) == h
    upstream = json.loads(Path('artifacts/v6_integrated_20261013/run_v2/protocol.json').read_text())
    for p, h in upstream['inputs'].items():
        assert sha(Path(p)) == h
    files = set(pp['inputs']) | set(upstream['inputs']) | {str(PRIOR / 'protocol.json')}
    files |= {str(p) for p in PRIOR.glob('*/glyphs/*.json')}
    files |= {str(p) for p in PRIOR.glob('*/records.json')}
    files |= {str(p) for p in PRIOR.glob('*/evaluation.json')}
    code = [*Path('src/inkstruct').glob('*.py'), Path(__file__), Path('scripts/run_v61_exp.py')]
    frozen = {'inputs': {p: sha(Path(p)) for p in sorted(files)},
              'code': {str(p): sha(p) for p in code}}
    write(root / 'protocol.json', {
        'name': 'v6.1 exp reference influence ablation', 'baseline_commit': 'd782a54',
        **frozen, 'parameters': REFERENCE_PARAMETERS,
        'arms': {'A': 'frozen integrated full-source v6, previous B',
                 'R': 'previous v6.1 candidate-only C; reference weight 1, peer/gap terms retained',
                 'B': 'same R pool and candidate transforms, reference geometry score weight .25 only',
                 'C': 'A donor identities fixed, envelope layout replaces centerline fit',
                 'D': 'B donor identities fixed, same envelope layout as C'},
        'isolation': 'B versus R isolates reference score weight; B versus A also includes existing peer/gap terms. '
                     'C versus A isolates placement. D is exploratory combination, not assumed additive. '
                     'No expansion/remapping, reference/author source representation unchanged.',
        'split': '92 previously observed regression combinations; no fresh blind holdout; '
                 'all duplicate target-character samples excluded as a group from archives',
        'development': 'one predeclared setting (.25 score weight; envelope scale ratio .8..1.25); '
                       'chosen as bounded sensitivity probe before opening this run target metrics, no sweep',
        'evaluation': 'all outputs frozen before opening target originals; uniform arc quadrature .003, '
                      'originals only evaluation; existing fixed guards unchanged, 3 brush widths audited',
        'coverage': 'unchanged frozen pools including existing validated nested views; no coverage expansion arm',
    })
    base = StructureRepository(Path('artifacts/full_library_20261010/inputs/characters.sqlite3'))
    target = CorrectedStructureRepository(base, Path('third_party/makemeahanzi/graphics.txt'),
        Path('third_party/makemeahanzi/dictionary.txt'),
        Path('configs/structure_overrides/unclipped_reference_v1.json'))
    corpus = {}
    for writer in WRITERS:
        out = root / writer
        (out / 'glyphs').mkdir(parents=True)
        old = json.loads((PRIOR / writer / 'records.json').read_text())
        profile = load_profile(ARCHIVES / writer / 'source_archive.json')
        assert not {r['character'] for r in old} & {s.character for s in profile.source_trajectories.values()}
        engine = ReferenceAblationGenerator(profile, base, target)
        rows = []
        for oldrow in old:
            c = oldrow['character']
            ctx = engine.prepare(c)
            saved = json.loads((PRIOR / writer / 'glyphs' / f'{ord(c):04X}.json').read_text())
            assert json.loads(json.dumps(asdict(ctx.baseline))) == saved['B']
            # The same pool serves the unmodified and reduced-weight scores.
            rplan, rlog = V61ExpGenerator.select(ReferenceControl(engine), ctx)
            bplan, blog = engine.select(ctx)
            cplan, clog = engine.envelope_layout(ctx, ctx.baseline_plan)
            dplan, dlog = engine.envelope_layout(ctx, bplan)
            specs = {'A': (ctx.baseline_plan, [], []), 'R': (rplan, rlog, []),
                     'B': (bplan, blog, []), 'C': (cplan, [], clog), 'D': (dplan, blog, dlog)}
            glyphs, metas, integrity, provenance = {}, {}, {}, {}
            for k, (plan, sl, ll) in specs.items():
                assert set(plan) == set(ctx.baseline_plan), 'coverage must remain isolated'
                g, m = engine.finish(ctx, plan, selection_log=sl, layout_log=ll)
                glyphs[k] = asdict(g)
                metas[k] = m
                integrity[k] = check_integrity(engine, ctx, g, plan)
                owners = {i: p for p in plan.values() for i in p.indices}
                provenance[k] = [{'order': i+1, 'standard_id': s.standard_stroke_id,
                    'origin': 'complete_author' if i in owners else 'reference_fallback_style_insufficient',
                    'component_id': owners[i].component_id if i in owners else None,
                    'candidate': owners[i].candidate if i in owners else None,
                    'transform': asdict(owners[i].transform) if i in owners else None}
                    for i, s in enumerate(g.strokes)]
            assert glyphs['R']['strokes'] == saved['C']['strokes'], 'old v6.1 scoring changed'
            assert [s['points'] for s in glyphs['A']['strokes']] == [s['points'] for s in saved['B']['strokes']]
            assert all(cplan[k].candidate == p.candidate for k,p in ctx.baseline_plan.items())
            assert all(dplan[k].candidate == p.candidate for k,p in bplan.items())
            contacts = {k: contact_report(dict_curves(g), [s.median for s in ctx.graph.strokes])
                        for k,g in glyphs.items()}
            sensitivity = {str(w): {k: sorted(contact_pairs(dict_curves(g), w)
                            - contact_pairs(dict_curves(glyphs['A']), w)) for k,g in glyphs.items()}
                           for w in (.014, .028, .05)}
            row = {'character': c, 'coverage': oldrow['coverage'], 'arms': metas,
                   'integrity': integrity, 'provenance': provenance,
                   'pool': {cid: [asdict(p) for p in pool] for cid,pool in ctx.pools.items()},
                   'reference': [s.median for s in ctx.graph.strokes], 'contacts': contacts,
                   'brush_sensitivity_new_pairs_vs_A': sensitivity,
                   'changed_vs_A': {k: dict_curves(g)!=dict_curves(glyphs['A']) for k,g in glyphs.items()},
                   'changed_vs_R': {k: dict_curves(g)!=dict_curves(glyphs['R']) for k,g in glyphs.items()}}
            rows.append(row)
            write(out / 'glyphs' / f'{ord(c):04X}.json', glyphs)
            print(writer, c, {k:row['changed_vs_A'][k] for k in 'BCD'}, flush=True)
        write(out / 'records.json', rows)
        corpus[writer] = rows
    summaries = evaluate(root, corpus)
    write(root / 'summary.json', summaries)
    for value in frozen.values():
        assert value == {p: sha(Path(p)) for p in value}
    write(root / 'verification.json', {'frozen_inputs_and_code': True, 'A_and_R_exact_regeneration':92,
        'full_source_geometry_pressure_time': True, 'fixed_C_and_D_donors':True,
        'coverage_unchanged':True, 'production_unchanged':True})


class ReferenceControl:
    """Share engine state/pools, dispatch only original score policy (no second index)."""
    def __init__(self, engine):
        self.engine = engine

    def __getattr__(self, key):
        return getattr(self.engine, key)

    def ranking_score(self, p, peer, crowd):
        return V61ExpGenerator.ranking_score(self.engine, p, peer, crowd)


def evaluate(root, corpus):
    summaries = {}
    for writer, rows in corpus.items():
        originals = json.loads((PRIOR / writer / 'evaluation.json').read_text())
        grouped = defaultdict(lambda: defaultdict(list))
        items = []
        for item in originals:
            g = json.loads((root / writer / 'glyphs' / f"{ord(item['character']):04X}.json").read_text())
            metrics = {k: [stroke_metrics(x,y) for x,y in zip(dict_curves(v),item['original'],strict=True)]
                       for k,v in g.items()}
            items.append({**{k:item[k] for k in ('character','sample_id','original')}, 'metrics':metrics})
            for k, ss in metrics.items():
                grouped[item['character']][k].append({f:float(np.mean([s[f] for s in ss]))
                    for f in ('mean_distance','max_distance','terminal_angle_deg','absolute_length_error')})
        perchar = {c:{k:{f:float(np.mean([s[f] for s in ss])) for f in ss[0]} for k,ss in v.items()}
                   for c,v in grouped.items()}
        summaries[writer] = {'per_character':perchar, 'samples':len(items),
            'macro':{k:{f:float(np.mean([v[k][f] for v in perchar.values()]))
                        for f in next(iter(perchar.values()))[k]} for k in ARMS},
            'changed_vs_A':{k:sum(r['changed_vs_A'][k] for r in rows) for k in ARMS},
            'changed_vs_R':{k:sum(r['changed_vs_R'][k] for r in rows) for k in ARMS},
            'source_strokes':{k:sum(r['integrity'][k]['source_strokes'] for r in rows) for k in ARMS},
            'reference_strokes':{k:sum(r['integrity'][k]['reference_strokes'] for r in rows) for k in ARMS}}
        write(root / writer / 'evaluation.json', items)
    return summaries


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    run(parser.parse_args().output)
