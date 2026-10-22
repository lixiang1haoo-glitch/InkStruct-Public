"""Produce summaries from retained raw measurements, never edit those records."""
import bootstrap as b
import json
from pathlib import Path
import numpy as np

def read(name):return json.loads((b.OUT/name).read_text(encoding='utf-8'))
def telemetry(data):
    rows=data['monitor']['rows'];start,end=rows[0],rows[-1];wall=end['time']-start['time']
    # A terminated raster child disappears from psutil tree totals; use the
    # maximum cumulative observed total, rather than a negative final delta.
    cpu=max(r['cpu_seconds'] for r in rows)-start['cpu_seconds']
    return {'wall_s':wall,'observed_cpu_s':cpu,'cpu_one_core_percent':cpu/wall*100,
            'rss_peak_mib':max(r['rss_bytes'] for r in rows)/1024**2,
            'gpu_percent_median':float(np.median([r.get('global_gpu_percent',0) for r in rows])),
            'global_vram_peak_mib':max(r.get('global_vram_bytes',0) for r in rows)/1024**2,
            'global_vram_start_mib':start.get('global_vram_bytes',0)/1024**2}

def main():
    report={'preview':{},'raster':{},'candidate':{},'pipeline':{}}
    if (b.OUT/'baseline-parts.json').exists():
        parts=read('baseline-parts.json')
        report['cpu_baseline_parts_ms']={k:b.summary([t['inclusive_parts_not_additive'][k]['seconds']*1000 for t in parts]) for k in parts[0]['inclusive_parts_not_additive']}
    hashes={};geometries={};selection={};edited={}
    for backend in ('cpu','gpu','gpu-raster'):
        trials=[read(f'preview-{backend}-{rep}.json') for rep in (8,9,10)]
        assert all('error' not in t and t['foreground_fraction']==1 for t in trials)
        block={'open_ms':b.summary([t['open_to_visible_ms'] for t in trials]),
               'package_ms':b.summary([t['package_load_ms'] for t in trials]),
               'parse_layout_ms':b.summary([t['parse_layout_ms'] for t in trials]),
               'edit_build_ms':b.summary([t['edit_parse_layout_ms'] for t in trials]),
               'telemetry':[telemetry(t) for t in trials]}
        for name in ('first_visible_cold','cold_traverse','cold_traverse_content_settle','warm_local','zoom_1.5','zoom_1.0','edit_visible'):
            rows=[r for t in trials for r in t['scenarios'] if r['name']==name]
            block[name]={'paint_latency_ms':b.summary([r['action_to_paint_ms'] for r in rows]),
                         'visible_fence_ms':b.summary([r['action_to_dwm_fence_ms'] for r in rows]),
                         'updates_over_50ms':sum(r['action_to_dwm_fence_ms']>50 for r in rows),
                         'cache_not_ready_updates':sum(not r['cache_ready'] for r in rows)}
        for state in ('cold','warm'):
            rows=[r for t in trials for r in t['scenarios'] if r['name'].startswith('zoom_') and r['cache_ready_at_action']==(state=='warm')]
            block['zoom_'+state+'_cache_ms']=b.summary([r['action_to_dwm_fence_ms'] for r in rows])
        for mode in ('cold_traverse','warm_local'):
            values=[f['ms'] for t in trials for f in t[mode]['frames']]
            block[mode]['paint_work_ms']=b.summary(values)
            rows=[r for t in trials for r in t['scenarios'] if r['name']==mode]
            block[mode]['input_lateness_ms']=b.summary([r['input_lateness_ms'] for r in rows])
            block[mode]['input_gap_max_ms']=max((c['time']-a['time'])*1000 for t in trials for a,c in zip([r for r in t['scenarios'] if r['name']==mode],[r for r in t['scenarios'] if r['name']==mode][1:]))
        block['all_dpr']=[t['dpr'] for t in trials];block['viewport']=[t['viewport'] for t in trials]
        block['cache_stats']=[t['cache'] for t in trials]
        report['preview'][backend]=block
        for rep,t in zip((8,9,10),trials):
            key=f'{backend}-{rep}';hashes[key]=t['page_svg_sha256'];geometries[key]=t['geometry_hash'];selection[key]=t['selection_hash'];edited[key]=t['edit_geometry_hash']
    assert all(v==next(iter(hashes.values())) for v in hashes.values())
    assert len(set(geometries.values()))==1 and len(set(selection.values()))==1 and len(set(edited.values()))==1
    report['correctness']={'all_9_preview_svg_page_hashes_equal':True,'all_preview_geometry_equal':True,
        'all_frozen_selections_equal':True,'all_edited_geometry_equal':True,
        'actual_selection_handler_exercised':True,'diagnostics':read('preview-cpu-8.json')['diagnostics']}
    raster=read('raster.json')
    for zoom in (1.,1.5,2.):
        block={}
        for backend in ('cpu','gpu'):
            rows=[r for r in raster['records'] if r['zoom']==zoom and r['backend']==backend]
            block[backend]={key:b.summary([r[key]*1000 for r in rows]) for key in ('svg_parse_s','allocate_s','raster_sync_s','readback_s','pixel_write_s','pixel_read_copy_s','total_s')}
            block[backend]['first']=rows[0]
        report['raster'][str(zoom)]=block
    report['raster']['quality']=raster['pixel_comparison'];report['raster']['telemetry']=telemetry(raster)
    for backend in ('cpu','gpu-raster'):
        data=[read(f'preview-{backend}-open-{rep}.json') for rep in (4,5,6)]
        report['preview'][backend]['contiguous_open_ms']=b.summary([r['open_to_visible_ms'] for r in data])
        report['preview'][backend]['open_telemetry']=[telemetry(t) for t in data]
        edits=[read(f'preview-{backend}-edit-{rep}.json') for rep in (1,2,3)]
        assert all('error' not in r for r in edits)
        assert len({r['edit_geometry_hash'] for r in edits})==1
        report['preview'][backend]['visible_digit_edit_ms']=b.summary([r['edit_to_visible_ms'] for r in edits])
        report['preview'][backend]['visible_digit_build_ms']=b.summary([r['edit_parse_layout_ms'] for r in edits])
        report['preview'][backend]['visible_digit_raster_feedback_ms']=b.summary([next(x['action_to_dwm_fence_ms'] for x in r['scenarios'] if x['name']=='edit_visible') for r in edits])
    assert read('preview-cpu-edit-1.json')['edit_geometry_hash']==read('preview-gpu-raster-edit-1.json')['edit_geometry_hash']
    engine=read('preview-gpu-11.json')['gl']['measured_paint_engines']
    assert set(engine)=={'Type.OpenGL2'}
    report['correctness']['actual_gpu_composition_engine_counts']=engine
    candidate=read('candidate-stage.json');rows=candidate['repetitions']
    report['candidate']={'queries':candidate['query_count'],'candidate_pairs':candidate['candidate_pairs'],
        'characters':len(candidate['characters']),'repository_characters':candidate['repository_characters'],
        'groups':len(candidate['groups']),'profile_load_s':candidate['profile_load_s'],
        'descriptors_s':candidate['source_pool_and_descriptors_s'],'semantic_queries_s':candidate['semantic_query_prepare_s'],
        'telemetry':telemetry(candidate),'small_max_abs_error':candidate['small_check_max_error']}
    for key in ('cpu_s','gpu_including_verify_s','cpu_verify_s','device_s','upload_s','download_s'):
        report['candidate'][key]=b.summary([r[key] for r in rows])
    report['candidate']['gpu_before_verify_s']=b.summary([r['gpu_including_verify_s']-r['cpu_verify_s'] for r in rows])
    report['candidate']['scale']={}
    for count in sorted(set(r['queries'] for r in candidate['scale'])):
        items=[r for r in candidate['scale'] if r['queries']==count]
        report['candidate']['scale'][count]={key:b.summary([r[key]*1000 for r in items]) for key in ('cpu_s','gpu_total_s','device_event_s','query_upload_alloc_s','download_s')}
    cold=[read(f'cold-fit-{rep}.json') for rep in (1,2,3)]
    report['candidate']['cold']={'context_import_ms':b.summary([r['gpu_context_import_s']*1000 for r in cold]),
        'first_total_ms':b.summary([r['batches'][0]['gpu_total_s']*1000 for r in cold]),
        'first_jit_device_wall_ms':b.summary([r['batches'][0]['device_wall_s']*1000 for r in cold]),
        'first_candidate_pack_ms':b.summary([r['batches'][0]['candidate_pack_s']*1000 for r in cold]),
        'first_candidate_h2d_ms':b.summary([r['batches'][0]['candidate_h2d_s']*1000 for r in cold]),
        'first_query_h2d_allocate_ms':b.summary([r['batches'][0]['query_upload_alloc_s']*1000 for r in cold]),
        'first_d2h_ms':b.summary([r['batches'][0]['download_s']*1000 for r in cold]),
        'warm_total_ms':b.summary([r['gpu_total_s']*1000 for t in cold for r in t['batches'][1:]])}
    components=read('component-stage.json')
    report['component']={'fit_pairs':components['fit_pairs'],'groups':components['groups'],'max_abs_error':components['max_abs_error'],
        **{key:b.summary([r[key]*1000 for r in components['records']]) for key in ('numpy_batch_s','device_s','download_s','resident_gpu_fit_download_s','cpu_authoritative_recompute_s','safe_fit_total_s')},
        'initial_upload_ms':components['initial_descriptor_upload_s']*1000,
        'scope':components['scope']}
    if (b.OUT/'decisions.json').exists():
        decisions=read('decisions.json');report['decisions']={k:decisions[k] for k in ('characters','accepted','verified_candidate_pairs','max_abs_error','all_payloads_exact','total_s')}
        report['decisions']['cases']=len(decisions['rows'])
    for backend in ('cpu','gpu'):
        files=[b.OUT/f'pipeline-{backend}-{rep}.json' for rep in (1,2,3)]
        if not all(p.exists() for p in files):continue
        data=[json.loads(p.read_text(encoding='utf-8')) for p in files]
        report['pipeline'][backend]={'total_s':b.summary([r['seconds'] for r in data]),
            'with_backend_init_s':b.summary([r['seconds']+(r['gpu']['init_s'] if r['gpu'] else 0) for r in data]),
            'numeric_s':b.summary([sum(r['numeric_seconds']) for r in data]),
            'telemetry':[telemetry(r) for r in data],'phases':[r['phases_inclusive_not_additive'] for r in data]}
    b.save('summary.json',report)
    print(json.dumps({k:v for k,v in report.items() if k not in ('preview','raster','pipeline')},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
