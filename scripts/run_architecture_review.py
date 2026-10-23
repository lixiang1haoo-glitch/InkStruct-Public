"""Frozen, grouped multi-writer ablations and source-preserving frame experiments."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import time
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

import numpy as np
from run_v6_exp import integrity, matched_compressed

from inkstruct.alignment import align_sample
from inkstruct.control_repair import ControlRepairGenerator
from inkstruct.generate import DeterministicGenerator
from inkstruct.geometry import path_length, resample
from inkstruct.glyph_frame_exp import GlyphFrameEvidence, apply_glyph_frame
from inkstruct.profile import build_profile
from inkstruct.samples import iter_index
from inkstruct.schemas import StyleProfile
from inkstruct.source_trajectory import TRAJECTORY_SCHEMA, source_trajectory
from inkstruct.structures import StructureRepository
from inkstruct.trajectory_experiment import crossing_pairs, invariants, stroke_metrics
from inkstruct.v6_exp import FullReferenceGenerator, V6ExpGenerator

PROTECTION = '而相儒荡传砖桂生叵黧瀝'
ARMS = ('A', 'no_global', 'no_layout', 'no_relation', 'no_geometry', 'no_legacy',
        'no_component_residual', 'no_whole', 'no_spline', 'repair',
        'R', 'V6', 'V6_frame', 'V6_learned', 'M_frame')


def write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def curves(g):
    return [[(p.x, p.y) for p in s.points] for s in g.strokes]


def engines(profile, version):
    result = {k: DeterministicGenerator(profile, version) for k in ARMS[:9]}
    result['no_global']._global_transform = lambda points: points
    result['no_layout']._layout_prototype = lambda g, c: (None, 0., False)
    result['no_relation']._relation_prototype = lambda g, c: (None, 0.)
    result['no_geometry']._stroke_geometry_controls = lambda g,c,s,controls,box: (controls,None,False)
    result['no_component_residual']._component_stroke_prototype = lambda *args: (None,0.,False)
    result['no_whole']._whole_component_controls = lambda g: {}
    residual_free = copy.deepcopy(profile)
    for p in residual_free.prototypes.values():
        p.residual = [(0.,0.)]*len(p.residual)
    result['no_legacy'] = DeterministicGenerator(residual_free, version)
    result['repair'] = ControlRepairGenerator(profile, version)
    return result


def run(root):
    root.mkdir(parents=True, exist_ok=False)
    db = Path('artifacts/full_library_20261010/inputs/characters.sqlite3')
    repo = StructureRepository(db)
    paths = {w:Path(f'artifacts/samples/{w}/index.jsonl') for w in ('scx','mjb','wsq')}
    paths['user_001'] = Path('artifacts/component_aspect_20261007/user001_snapshot/index.jsonl')
    splits = {}
    for writer, path in paths.items():
        characters = {s.character for s in iter_index(path)} - set(PROTECTION)
        eligible = []
        for c in characters:
            try:
                if 3 <= len(repo.get(c).strokes) <= 20:
                    eligible.append(c)
            except KeyError:
                pass
        splits[writer] = sorted(eligible, key=lambda c:hashlib.sha256(
            ('architecture-review-v1:'+c).encode()).hexdigest())[:12]
    implementation = [Path(__file__), Path('src/inkstruct/glyph_frame_exp.py'),
                      *[Path('src/inkstruct')/f for f in ('generate.py','profile.py','alignment.py',
                       'v6_exp.py','fast_placement.py','trajectory_experiment.py','control_repair.py')]]
    protocol = {'date':'2026-10-11', 'split_policy':'12 smallest SHA256 architecture-review-v1:character; '
        'metadata/structure count 3..20 only; repeated characters grouped; excludes old protection characters',
        'holdout_characters':splits, 'regression_protection':list(PROTECTION), 'arms':ARMS,
        'classification':'fixed grouped validation; many samples previously examined, NOT new blind data',
        'hyperparameters':'no outcome tuning; existing selector gates; shared public extent=.85; '
        'learned frame median per character, >=8 groups, scale .75..1.25, centre shift norm<=.15; '
        'all variants deterministic, no random augmentation; no anisotropic scaling in frame arms',
        'source_freeze':'V6 donor and placement frozen before V6_frame/V6_learned/M_frame; no target capture used',
        'metrics':'same arc-length quadrature step .003; equal strokes then repeats then characters then writers; '
        'no output resampling for evaluation; hook is heuristic diagnostic, not annotated truth',
        'inputs':{str(p):sha(p) for p in [db,*paths.values()]},
        'code':{str(p):sha(p) for p in implementation}}
    write(root/'protocol.json',protocol)
    writer_summaries = {}
    for writer, path in paths.items():
        out = root/writer
        out.mkdir()
        (out/'glyphs').mkdir()
        held = set(splits[writer]) | set(PROTECTION)
        samples = list(iter_index(path))
        sources, rejected = {}, []
        for sample in samples:
            if sample.character in held:
                continue
            try:
                graph = repo.get(sample.character)
                source, reason = source_trajectory(sample, align_sample(sample,graph),graph)
            except (KeyError,ValueError) as error:
                source, reason = None,str(error)
            if source is None:
                rejected.append({'sample_id':sample.sample_id,'reason':reason})
            else:
                sources[sample.sample_id] = source
        write(out/'source_exclusions.json',rejected)
        training = out/'training.jsonl'
        training.write_text(''.join(line+'\n' for line in path.read_text().splitlines()
                                   if json.loads(line)['sample_id'] in sources))
        profile, profile_path = build_profile(writer, training, repo, out/'profiles')
        archive = StyleProfile('style_profile_v4',sha(training)[:16],writer,'2026-10-11',sha(path),
            len(sources),len({s.character for s in sources.values()}),{},{},{},
            trajectory_schema=TRAJECTORY_SCHEMA,source_trajectories=sources,
            build_identity={'structure_sha256':repo.content_sha256(),
                            'excluded_characters':sorted(held)})
        write(out/'source_archive.json',asdict(archive))
        v6 = V6ExpGenerator(archive,repo)
        reference = FullReferenceGenerator(archive,repo.metadata()['source_version'])
        evidence = GlyphFrameEvidence(sources,repo,excluded_characters=held)
        engine = engines(profile,repo.metadata()['source_version'])
        write(out/'training_manifest.json',{'profile_sha256':sha(profile_path),
            'source_samples':len(sources),'source_characters':archive.character_count,
            'legacy_profile_samples':profile.sample_count,'legacy_profile_characters':profile.character_count,
            'frame_prediction':evidence.predict('而'),'frame_exclusions':evidence.rejected})
        outputs, records = {}, []
        timings = defaultdict(list)
        generation_failures = []
        for c in list(PROTECTION)+splits[writer]:
            graph = repo.get(c)
            glyphs = {}
            try:
                for label,e in engine.items():
                    start = time.perf_counter()
                    if label == 'no_spline':
                        with patch('inkstruct.generate.cubic_bspline',lambda xy,n,**kw:resample(xy,n)):
                            glyphs[label] = e.generate(graph)
                    else:
                        glyphs[label] = e.generate(graph)
                    timings[label].append(time.perf_counter()-start)
                start = time.perf_counter()
                glyphs['R'] = reference.generate(graph)
                timings['R'].append(time.perf_counter()-start)
                start = time.perf_counter()
                glyphs['V6'], diagnostics = v6.generate(graph)
                timings['V6'].append(time.perf_counter()-start)
                check = integrity(glyphs['V6'],graph,diagnostics,sources)
                start = time.perf_counter()
                glyphs['V6_frame'], fixed = apply_glyph_frame(glyphs['V6'],graph)
                timings['V6_frame_postprocess'].append(time.perf_counter()-start)
                start = time.perf_counter()
                glyphs['V6_learned'], learned = apply_glyph_frame(glyphs['V6'],graph,evidence=evidence)
                timings['V6_learned_postprocess'].append(time.perf_counter()-start)
                compressed = matched_compressed(glyphs['R'],glyphs['V6'],diagnostics,sources)
                glyphs['M_frame'], compressed_frame = apply_glyph_frame(compressed,graph)
            except ValueError as error:
                generation_failures.append({'character':c,'reason':str(error)})
                continue
            outputs[c] = glyphs
            reference_cross = crossing_pairs(curves(glyphs['R']))
            raw_cross = crossing_pairs(curves(glyphs['V6']))
            for k in ('V6_frame','V6_learned'):
                assert [len(s.points) for s in glyphs[k].strokes] == [len(s.points) for s in glyphs['V6'].strokes]
                assert crossing_pairs(curves(glyphs[k])) == raw_cross
            checks = {k:{'invariant_errors':invariants(g,graph),
                         'zero_lengths':sum(path_length(s)<=1e-9 for s in curves(g)),
                         'extra_crossings_vs_reference':sorted(crossing_pairs(curves(g))-reference_cross),
                         'points':sum(len(s.points) for s in g.strokes)} for k,g in glyphs.items()}
            record = {'character':c,'group':'regression_protection' if c in PROTECTION else 'grouped_validation',
                      'checks':checks,'integrity':check,'diagnostics':diagnostics,
                      'frame':fixed,'learned_frame':learned,'compressed_frame':compressed_frame}
            records.append(record)
            write(out/'glyphs'/f'{ord(c):04X}.json',{k:asdict(g) for k,g in glyphs.items()})
        # Freeze all generated outputs before opening any target geometry for evaluation.
        write(out/'records.json',records)
        write(out/'generation_failures.json',generation_failures)
        evaluation, exclusions = [], []
        for sample in samples:
            if sample.character not in splits[writer] or sample.character not in outputs:
                continue
            graph = repo.get(sample.character)
            raw, reason = source_trajectory(sample,align_sample(sample,graph),graph)
            if raw is None:
                exclusions.append({'sample_id':sample.sample_id,'character':sample.character,'reason':reason})
                continue
            true = [s.points for s in raw.strokes]
            evaluation.append({'sample_id':sample.sample_id,'character':sample.character,
                'original':true, 'metrics':{label:[stroke_metrics(a,b) for a,b in zip(curves(g),true,strict=True)]
                    for label,g in outputs[sample.character].items()}})
        write(out/'evaluation.json',evaluation)
        write(out/'evaluation_exclusions.json',exclusions)
        summary = summarize(evaluation,records,timings)
        writer_summaries[writer] = summary
        write(out/'summary.json',summary)
        print(writer,json.dumps(summary['macro_distance']),flush=True)
    write(root/'summary.json',writer_summaries)
    assert protocol['inputs'] == {str(p):sha(p) for p in [db,*paths.values()]}


def summarize(evaluation,records,timings):
    bychar = defaultdict(lambda:defaultdict(list))
    fields = ('mean_distance','max_distance','terminal_angle_deg','absolute_length_error','endpoint_error')
    for row in evaluation:
        for label, metrics in row['metrics'].items():
            bychar[row['character']][label].append({f:float(np.mean([m[f] for m in metrics])) for f in fields})
    perchar = {c:{k:{f:float(np.mean([s[f] for s in samples])) for f in fields}
                for k,samples in arms.items()} for c,arms in bychar.items()}
    return {'n_samples':len(evaluation),'n_characters':len(perchar),'per_character':perchar,
        'macro_distance':{k:float(np.mean([v[k]['mean_distance'] for v in perchar.values()])) for k in ARMS},
        'macro_terminal_angle':{k:float(np.mean([v[k]['terminal_angle_deg'] for v in perchar.values()])) for k in ARMS},
        'improved_vs_A':{k:sum(v[k]['mean_distance']<v['A']['mean_distance']-1e-12 for v in perchar.values()) for k in ARMS},
        'checks':{k:{'invariant_failed_glyphs':sum(bool(r['checks'][k]['invariant_errors']) for r in records),
                     'zero_length_strokes':sum(r['checks'][k]['zero_lengths'] for r in records),
                     'glyphs_with_extra_crossings_vs_reference':sum(bool(r['checks'][k]['extra_crossings_vs_reference']) for r in records)} for k in ARMS},
        'frame_fallbacks':{k:sum(not r[k]['applied'] for r in records) for k in ('frame','learned_frame','compressed_frame')},
        'total_glyphs':len(records),'source_strokes':sum(r['integrity']['source_strokes'] for r in records),
        'source_components':sum(r['diagnostics']['accepted_component_count'] for r in records),
        'median_generation_seconds':{k:float(np.median(v)) for k,v in timings.items()}}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    run(parser.parse_args().output)
