"""Separate GPU kernel/cache benefit, common scheduling benefit and display jitter."""
import bootstrap as b
import json
from collections import Counter

def read(name):return json.loads((b.OUT/name).read_text(encoding='utf-8'))
variants=[('old-external','cpu'),('old-external-steady','cpu'),('cpu-external-prewarm-steady','gpu-raster'),
          ('correct-external-prewarm-steady','gpu-raster'),('cached-external-prewarm-steady','gpu-raster')]
report={'native':{},'stages':{},'correctness':{}}
initial=[];edited=[]
for variant,backend in variants:
    data=[read(f'preview-{variant}-{backend}-{rep}.json') for rep in (3,4,5)]
    assert all('error' not in r and r['foreground_fraction']==1 for r in data)
    entry={'open_ms':b.summary([r['open_to_visible_ms'] for r in data]),'resources':[]}
    for scene in ('cold_traverse','warm_local'):
        actions=[x for r in data for x in r['scenarios'] if x['name']==scene]
        frames=[f for r in data for f in r[scene]['frames']]
        entry[scene]={'paint_ms':b.summary([f['ms'] for f in frames]),
            'visible_feedback_ms':b.summary([x['action_to_dwm_fence_ms'] for x in actions]),
            'input_lateness_ms':b.summary([x['input_lateness_ms'] for x in actions]),
            'content_not_ready_updates':sum(not x['cache_ready'] for x in actions),
            'over_50ms':sum(x['action_to_dwm_fence_ms']>50 for x in actions),
            'new_jobs':[r[scene]['cache_after']['render_jobs']-r[scene]['cache_before']['render_jobs'] for r in data],
            'new_cancellations':[r[scene]['cache_after']['cancelled_jobs']-r[scene]['cache_before']['cancelled_jobs'] for r in data],
            'svg_build_s':[r[scene]['cache_after']['svg_seconds']-r[scene]['cache_before']['svg_seconds'] for r in data]}
    for state in ('cold','warm'):
        values=[x['action_to_dwm_fence_ms'] for r in data for x in r['scenarios'] if x['name'].startswith('zoom_') and x['cache_ready_at_action']==(state=='warm')]
        entry['zoom_'+state+'_ms']=b.summary(values)
    entry['cold_content_settle_ms']=b.summary([x['action_to_dwm_fence_ms'] for r in data for x in r['scenarios'] if x['name']=='cold_traverse_content_settle'])
    for r in data:
        rows=r['monitor']['rows'];wall=rows[-1]['time']-rows[0]['time']
        entry['resources'].append({'rss_peak_mib':max(x['rss_bytes'] for x in rows)/1024**2,
            'cpu_seconds':rows[-1]['cpu_seconds']-rows[0]['cpu_seconds'],
            'global_vram_peak_mib':max(x.get('global_vram_bytes',0) for x in rows)/1024**2,
            'global_gpu_median':b.summary([x['global_gpu_percent'] for x in rows]),
            'sampler_cpu_s':r['monitor']['sampler_process_cpu_s'],'wall_s':wall})
        initial.append((r['page_svg_sha256'],r['selection_hash'],r['geometry_hash'],r['diagnostics']))
        edited.append(r['edit_geometry_hash'])
    report['native'][variant]=entry
assert all(x==initial[0] for x in initial);assert len(set(edited))==1
report['correctness'].update(native_initial_svg_geometry_selections_equal=True,native_whitespace_edit_geometry_equal=True,
                              native_reports=len(initial),diagnostics=initial[0][-1])
stage=read('stages.json')
for variant in stage['variants']:
    rows=[r for r in stage['records'] if r['variant']==variant]
    block={'pixel_mismatches':sum(not r['exact_stencil_control_pixels'] for r in rows)}
    for label,positions in [('first_dense',[0]),('repeat_dense',[1,3,5,7]),('zoom',[2]),('clip',[6])]:
        selected=[r for r in rows if r['position'] in positions]
        block[label+'_ms']=b.summary([r['end_to_end_s']*1000 for r in selected])
    repeated=[r for r in rows if r['position']==1]
    block['warm_parts_ms']={key:b.summary([r[key]*1000 for r in repeated]) for key in ('hash_s','svg_parse_s','pixel_write_s','receive_copy_s')}
    for key in ('allocate_bind_s','draw_submit_s','explicit_barrier_s','completed_readback_s','convert_s'):
        block['warm_parts_ms'][key]=b.summary([r['tiles'][0][key]*1000 for r in repeated])
    report['stages'][variant]=block
report['correctness']['cpu_vs_msaa8_quality']=stage['quality']
if (b.OUT/'validation.json').exists():report['validation']=read('validation.json')
for kind,reps,choices in [
    ('open',(6,7,8),[('old-external','cpu'),('old-external-prewarm','cpu'),*variants[2:]]),
    ('edit',(21,22,23),[('old-external-steady','cpu'),('cpu4-external-prewarm-steady','gpu-raster'),('cached4-external-prewarm-steady','gpu-raster')])]:
    entries={};edit_hashes=[]
    for variant,backend in choices:
        paths=[b.OUT/f'preview-{variant}-{backend}-{kind}-{rep}.json' for rep in reps]
        if not all(p.exists() for p in paths):continue
        data=[json.loads(p.read_text(encoding='utf-8')) for p in paths]
        assert all('error' not in r and r['foreground_fraction']==1 for r in data)
        entries[variant]=b.summary([r['open_to_visible_ms'] if kind=='open' else r['edit_to_visible_ms'] for r in data])
        if kind=='edit':edit_hashes.extend(r['edit_geometry_hash'] for r in data)
    if edit_hashes:assert len(set(edit_hashes))==1
    report[kind+'_only_ms']=entries
report['capacity']={}
for variant in ('cpu4-external-prewarm-steady','cached-external-prewarm-steady','cached4-external-prewarm-steady'):
    paths=[b.OUT/f'preview-{variant}-gpu-raster-{rep}.json' for rep in (18,19,20)]
    if not all(p.exists() for p in paths):continue
    data=[json.loads(p.read_text(encoding='utf-8')) for p in paths]
    assert all('error' not in r and r['foreground_fraction']==1 for r in data)
    assert all((r['page_svg_sha256'],r['selection_hash'],r['geometry_hash'],r['diagnostics'])==initial[0] for r in data)
    row={}
    for state in ('cold','warm'):
        row['zoom_'+state+'_ms']=b.summary([x['action_to_dwm_fence_ms'] for r in data for x in r['scenarios'] if x['name'].startswith('zoom_') and x['cache_ready_at_action']==(state=='warm')])
    row['warm_scroll_ms']=b.summary([x['action_to_dwm_fence_ms'] for r in data for x in r['scenarios'] if x['name']=='warm_local'])
    row['rss_peak_mib']=[max(x['rss_bytes'] for x in r['monitor']['rows'])/1024**2 for r in data]
    row['cpu_seconds']=[r['monitor']['rows'][-1]['cpu_seconds']-r['monitor']['rows'][0]['cpu_seconds'] for r in data]
    row['global_vram_peak_mib']=[max(x.get('global_vram_bytes',0) for x in r['monitor']['rows'])/1024**2 for r in data]
    row['warm_jobs']=[r['warm_local']['cache_after']['render_jobs']-r['warm_local']['cache_before']['render_jobs'] for r in data]
    report['capacity'][variant]=row
excluded=[]
for path in b.OUT.glob('preview-*.json'):
    r=json.loads(path.read_text(encoding='utf-8'))
    if 'error' in r or r.get('foreground_fraction')!=1:
        excluded.append({'file':path.name,'foreground_fraction':r.get('foreground_fraction'),'error':r.get('error')})
report['excluded_native_runs']=excluded
b.save('summary.json',report)
for variant,row in report['native'].items():print(variant,'warm p95',round(row['warm_local']['visible_feedback_ms']['p95'],2),'jobs',row['warm_local']['new_jobs'],'cancel',row['warm_local']['new_cancellations'],'zoom',round(row['zoom_cold_ms']['median'],2),flush=True)
print('open',report['open_only_ms']);print('edit',report['edit_only_ms'])
