"""Development ablation of coherent source-trajectory placement; no production mutations."""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

import numpy as np
from run_raw_trajectory_experiment import Experiment, curves, save

from inkstruct.contextual_trajectory import anchor_error, place_component
from inkstruct.geometry import path_length
from inkstruct.trajectory_experiment import assemble, crossing_pairs, invariants, stroke_metrics


def trial(experiment, task, candidate, field_strength):
    graph = experiment.repository.get(task['character'])
    base = experiment.training.generate(graph)
    base_curves = curves(base)
    indices = [i for i, s in enumerate(base.strokes) if s.standard_stroke_id in task['target_stroke_ids']]
    target = [base_curves[i] for i in indices]
    donor = experiment.sources[candidate['sample_id']]
    mapping = {s.standard_stroke_id: s for s in donor.strokes}
    source = [mapping[s] for s in candidate['stroke_ids']]
    placed, transform, field = place_component([s.points for s in source], target,
                                               field_strength=field_strength)
    decoded = [{'points': p, 'pressure': s.pressure, 'time': s.t_ms}
               for p, s in zip(placed, source, strict=True)]
    glyph = assemble(base, dict(zip(indices, decoded, strict=True)), 'contextual')
    errors = invariants(glyph, graph)
    crossings = crossing_pairs(curves(glyph)) - crossing_pairs(base_curves)
    lengths = [path_length(p) / max(path_length(t), 1e-9) for p, t in zip(placed, target, strict=True)]
    external = [p for p in crossings if not set(p) <= set(indices)]
    score = anchor_error(placed, target) + .01 * candidate['score']
    return {'glyph': glyph, 'indices': indices, 'source': candidate,
            'score': score, 'transform': asdict(transform),
            'field': field.metadata() if field else None, 'errors': errors,
            'new_crossings': sorted(crossings), 'external_crossings': external,
            'length_ratios_vs_A': lengths}


def evaluate(experiment, task, result):
    graph = experiment.repository.get(task['character'])
    source = experiment.sources[task['target_sample_id']]
    target_map = {s.standard_stroke_id: s for s in source.strokes}
    predicted = curves(result['glyph'])
    rows = [stroke_metrics(predicted[i], target_map[graph.strokes[i].stroke_id].points)
            for i in result['indices']]
    return {k: float(np.mean([r[k] for r in rows if r[k] is not None]))
            for k in ('mean_distance', 'max_distance', 'terminal_angle_deg', 'absolute_length_error')}


def fallback(experiment, task, proposal, reason):
    graph = experiment.repository.get(task['character'])
    return {**proposal, 'glyph': experiment.training.generate(graph),
            'proposal_errors': proposal['errors'], 'errors': [], 'fallback': reason}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, default=Path('artifacts/raw_trajectory_20261007'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(exist_ok=False, parents=True)
    experiment = Experiment(args.baseline)
    protocol = {'phase': 'development only', 'selection': 'training donors only, 16 original top candidates',
                'field_strengths': [0., .5, 1.], 'derivative_cap': .25, 'field_ridge': .005,
                'goal': 'reduce target error without compressing source vertices or independent stroke transforms',
                'old_test_status': 'previously inspected; regression only, not a fresh holdout'}
    save(args.output / 'protocol.json', protocol)
    records = []
    for task in experiment.plan['tasks']:
        if task['task'] != 'cross' or task['split'] != 'dev':
            continue
        candidates = task['ranked_candidates'][:16]
        variants, diagnostics = {}, {}
        for strength in protocol['field_strengths']:
            proposals = [trial(experiment, task, c, strength) for c in candidates]
            valid = [r for r in proposals if not r['errors']]
            if strength == 0:
                variants['fixed_similarity'] = (proposals[0] if not proposals[0]['errors'] else
                    fallback(experiment, task, proposals[0], 'fixed donor violates output invariants'))
            variants[f'rerank_field_{strength}'] = (min(valid, key=lambda r: r['score']) if valid else
                fallback(experiment, task, proposals[0], 'no in-bounds candidate'))
            safe = [r for r in valid if not r['new_crossings']
                    and min(r['length_ratios_vs_A']) >= .4 and max(r['length_ratios_vs_A']) <= 2.5]
            if safe:
                variants[f'guarded_field_{strength}'] = min(safe, key=lambda r: r['score'])
            else:
                variants[f'guarded_field_{strength}'] = fallback(
                    experiment, task, proposals[0], 'no topology-compatible complete exemplar')
            diagnostics[strength] = [{k: v for k, v in r.items() if k != 'glyph'} for r in proposals]
        baseline = json.loads((args.baseline / 'cases' / f"{task['id']}.json").read_text())
        metrics = {label: evaluate(experiment, task, result) for label, result in variants.items()}
        for label in ('A', 'B'):
            metrics[label] = {k: baseline['scores'][label]['aggregate'][k] for k in metrics['fixed_similarity']}
        record = {'task': task, 'metrics': metrics,
                  'variants': {k: {**{key: value for key, value in v.items() if key != 'glyph'},
                                   'glyph': asdict(v['glyph'])} for k, v in variants.items()},
                  'diagnostics': diagnostics}
        save(args.output / 'cases' / f"{task['id']}.json", record)
        records.append(record)
        print(f"development {len(records)}/32", flush=True)
    summary = {}
    for label in records[0]['metrics']:
        summary[label] = {k: float(np.mean([r['metrics'][label][k] for r in records]))
                          for k in records[0]['metrics'][label]}
        summary[label]['better_than_A'] = sum(r['metrics'][label]['mean_distance'] < r['metrics']['A']['mean_distance'] - 1e-9 for r in records)
        summary[label]['fallback_count'] = sum(bool(r['variants'].get(label, {}).get('fallback')) for r in records)
    save(args.output / 'summary.json', summary)
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == '__main__':
    main()
