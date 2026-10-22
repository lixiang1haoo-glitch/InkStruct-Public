import bootstrap as b
import json

report={}
for name in ('old-cpu-1','old-gpu-raster-1','old-gpu-raster-2','old-external-gpu-raster-1'):
    path=b.OUT/f'preview-{name}.json'
    if not path.exists():continue
    r=json.loads(path.read_text(encoding='utf-8'));scenes={}
    for scene in ('cold_traverse','warm_local'):
        frames=r[scene]['frames'];actions=[x for x in r['scenarios'] if x['name']==scene]
        slow=[f for f in frames if f['ms']>20]
        def overlaps(a,z,start,end):return a<end and z>start
        scenes[scene]={'paint_ms':b.summary([f['ms'] for f in frames]),
            'input_lateness_ms':b.summary([x['input_lateness_ms'] for x in actions]),
            'visible_feedback_ms':b.summary([x['action_to_dwm_fence_ms'] for x in actions]),
            'slow_frames':len(slow),'slow_frames_overlapping_gc':sum(any(overlaps(f['start'],f['start']+f['ms']/1000,g['start'],g['end']) for g in r['gc_events']) for f in slow),
            'slow_frames_overlapping_sampler':sum(any(overlaps(f['start'],f['start']+f['ms']/1000,s.get('sample_start',0),s.get('sample_end',0)) for s in r['monitor']['rows']) for f in slow)}
    report[name]=scenes
b.save('trace-summary.json',report)
for name,data in report.items():
    print(name,{scene:{k:round(v['p95'],2) for k,v in row.items() if k in ('paint_ms','input_lateness_ms','visible_feedback_ms')} for scene,row in data.items()},flush=True)
