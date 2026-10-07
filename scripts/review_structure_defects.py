"""Traceable manual-review ledger and deterministic stratified review sheets."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.font_manager import FontProperties
from run_raw_trajectory_experiment import save
from validate_structure_corrections import repositories

from inkstruct.outline_median import flatten_outline
from inkstruct.samples import sha256_file

FONT = FontProperties(fname='/System/Library/Fonts/Supplemental/Arial Unicode.ttf')
NORMAL_CANDIDATES = set('灑瞈脍蕻螉轆辘髭鬍鲙')
CONFIRMED = {('黧','s1'), ('瀝','s6'), ('盼','s7')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scan', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    rows = json.loads((args.scan/'strokes.json').read_text())
    base, corrected = repositories()
    candidates = [r for r in rows if r['suspected']]
    normal = [r for r in rows if not r['suspected'] and not r['confirmed']]
    controls, chosen = [], set()
    strata = {'short_unflagged': lambda r: r['raw_length'] < 100, 'long_unflagged': lambda r: r['raw_length'] > 600,
        'bent_unflagged': lambda r: len(corrected.graphics[r['character']]['medians'][int(r['stroke_id'][1:])-1]) >= 5}
    for group, predicate in strata.items():
        pool = sorted((r for r in normal if predicate(r)), key=lambda r: hashlib.sha256(('structure-review-v1:'+r['character']+r['stroke_id']).encode()).hexdigest())
        selected = []
        for r in pool:
            identity = (r['character'], r['stroke_id'])
            if identity not in chosen:
                selected.append({**r, 'review_stratum': group})
                chosen.add(identity)
            if len(selected) == 8:
                break
        controls.extend(selected)
    clipped = sorted([r for r in rows if 'import_clipping' in r['confirmed']], key=lambda r: r['clipping_max_distance'])
    clipping = [dict(clipped[round(i*(len(clipped)-1)/11)], review_stratum='clipping_quantiles') for i in range(12)]
    review = []
    for r in candidates:
        if (r['character'], r['stroke_id']) in CONFIRMED:
            verdict, reason = 'confirmed_source_error', 'Near-empty path omits the long thin stroke' if r['character'] != '盼' else 'Two-point chord exits its own curved outline; both anchors are inside; missing curvature confirmed visually'
        elif r['character'] in NORMAL_CANDIDATES:
            verdict, reason = 'normal_font_difference', 'Wide regular-script corner/foot explains coverage gap; path still follows the bend; no missing-turn evidence'
        else:
            verdict, reason = 'manual_review_pending', 'Endpoint or hook-loop ambiguity; available outline does not uniquely establish intended path/order'
        review.append({**r, 'verdict': verdict, 'reason': reason, 'review_basis': 'model visual inspection of all 19 source overlays; not independent expert labels'})
    save(args.output/'candidate_ledger.json', review)
    save(args.output/'control_selection.json', controls)
    save(args.output/'clipping_selection.json', clipping)
    save(args.output/'review_protocol.json', {'scan_sha256': sha256_file(args.scan/'strokes.json'), 'script_sha256': sha256_file(Path(__file__)),
        'counts': dict(Counter(r['verdict'] for r in review)), 'controls': len(controls), 'clipping_examples': len(clipping),
        'limitation': 'Heuristic strata, small model visual review. No sensitivity/specificity estimate and no independently annotated blind validation.'})
    for group, selected in [('suspects', review), ('controls', controls), ('clipping', clipping)]:
        for page in range((len(selected)+5)//6):
            fig, axes = plt.subplots(2,3,figsize=(13,8))
            for ax, r in zip(axes.flat, selected[page*6:page*6+6], strict=False):
                c, sid = r['character'], r['stroke_id']; i = int(sid[1:])-1
                raw = corrected.graphics[c]
                poly = flatten_outline(raw['strokes'][i], subdivisions=48)
                original = np.asarray(base.get(c).strokes[i].median)*[1024,-1024]+[0,1024]
                proposed = np.asarray(corrected.get(c).strokes[i].median)*[1024,-1024]+[0,1024]
                upstream = np.asarray(raw['medians'][i])
                ax.fill(*poly.T, color='#eeeeee', edgecolor='#888888', lw=.5)
                ax.plot(*upstream.T, color='#888888', ls=':', lw=2, label='Upstream median')
                ax.plot(*original.T, color='#ce442f', lw=1.7, label='A imported')
                ax.plot(*proposed.T, color='#008d9c', lw=1.4, label='Corrected')
                ax.scatter(*proposed[[0,-1]].T, s=16, color='#008d9c')
                ax.set_aspect('equal'); ax.grid(alpha=.15)
                title = f"{c} {sid}\n{r.get('verdict',r.get('review_stratum',''))}"
                ax.set_title(title,fontproperties=FONT,fontsize=11)
                ax.legend(fontsize=7)
            for ax in list(axes.flat)[len(selected[page*6:page*6+6]):]:
                ax.set_visible(False)
            fig.suptitle('Same coordinate frame: outline / imported / corrected. Local zoom per panel.',fontsize=12)
            fig.tight_layout(); fig.savefig(args.output/f'{group}_{page+1}.png',dpi=150); plt.close(fig)
    print('review sheets saved', args.output, flush=True)


if __name__ == '__main__':
    main()
