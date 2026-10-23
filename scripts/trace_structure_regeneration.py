"""Record selection/scale confounds in whole-reference regeneration, without edits."""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from run_raw_trajectory_experiment import save
from validate_structure_corrections import REGRESSION, read, repositories

from inkstruct.component_style import component_for_stroke
from inkstruct.generate import DeterministicGenerator
from inkstruct.geometry import resample, signature_key
from inkstruct.profile import load_profile
from inkstruct.samples import sha256_file


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--experiment',type=Path,required=True)
    args=parser.parse_args()
    base,corrected=repositories()
    profiles={w:load_profile(REGRESSION/'training'/(w+'.json')) for w in ('scx','mjb','wsq')}
    records=[]
    for path in sorted((args.experiment/'generated').glob('*.json')):
        row=read(path)
        if not row['events']['changes']:continue
        c,w=row['task']['character'],row['task']['writer'];profile=profiles[w]
        generator=DeterministicGenerator(profile,base.metadata()['source_version'],'adaptive',1.)
        trace={}
        for label,graph in [('A',base.get(c)),('B',corrected.get(c))]:
            whole=generator._whole_component_controls(graph);strokes=[]
            for standard in graph.strokes:
                signature=signature_key(standard.signature);comp=component_for_stroke(graph,standard)
                legacy,lexact=generator._prototype(signature,standard.component_path)
                prototype,weight,exact=generator._component_stroke_prototype(graph,comp,standard.stroke_id,signature) if comp else (None,0,False)
                raw_controls,layout,_,target_box,relation=generator._component_controls(graph,comp,resample(standard.median,8))
                raw_controls,geometry,_=generator._stroke_geometry_controls(graph,comp,standard,raw_controls,target_box)
                transformed=np.asarray(generator._global_transform(raw_controls))
                strokes.append({'stroke_id':standard.stroke_id,'signature':signature,'legacy_key':legacy.key if legacy else None,
                    'legacy_exact':lexact,'component_key':prototype.key if prototype else None,'component_weight':weight,'component_exact':exact,
                    'layout_key':layout.key if layout else None,'geometry_key':geometry.key if geometry else None,'relation_key':relation.key if relation else None,
                    'pre_residual_span':float(np.ptp(transformed,axis=0).max()),'whole_component_overrides_controls':standard.stroke_id in whole,
                    'actual_style_source':row['outputs'][label]['strokes'][standard.order-1]['style_source']})
            trace[label]=strokes
        differences=[]
        for a,b in zip(trace['A'],trace['B'],strict=True):
            changed={k:[a[k],b[k]] for k in a if a[k]!=b[k]}
            if changed:differences.append({'stroke_id':a['stroke_id'],'differences':changed})
        records.append({'task':row['task'],'changes':differences,'trace':trace})
    save(args.experiment/'regeneration_trace.json',{'script_sha256':sha256_file(Path(__file__)),'records':records,
        'caution':'pre_residual_span is not the final applied scale if whole-component trajectory controls override it; flag and actual style source are recorded'})
    print('traced',len(records),'cases',flush=True)


if __name__=='__main__':main()
