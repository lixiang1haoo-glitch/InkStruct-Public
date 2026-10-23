import common as b
import json
import sys
from pathlib import Path

def read(name):return json.loads((b.OUT/name).read_text(encoding='utf-8'))
rows=[];native=[];excluded=[]
for mode in ('thread','process','compact','admission','visible4'):
    reports=[read(f'native-{mode}-{run}.json') for run in (10,11,12)]
    for r in reports:
        assert r.get('harness_version')==3 and 'error' not in r,r.get('error')
        assert r['foreground_all']
        assert all(s['foreground'] and s['foreground_fraction_frames']==1 for s in r['scenarios']), (mode,r['run'],'foreground')
    for kind in [s['name'] for s in reports[0]['scenarios']]:
        samples=[next(s for s in r['scenarios'] if s['name']==kind) for r in reports]
        actions=[a for s in samples for a in s.get('actions',[])]
        summary={'mode':mode,'scenario':kind,'complete_wall_ms':b.summary([s['wall_ms'] for s in samples]),
                 'input_return_ms':b.summary([s['input_return_ms'] for s in samples if 'input_return_ms' in s]),
                 'paint_frame_summary_each':[s['frame_ms'] for s in samples],
                 'heartbeat_p95_each':[s['heartbeat_gap_ms'].get('p95') for s in samples],
                 'heartbeat_max_each':[s['heartbeat_gap_ms'].get('max') for s in samples],
                 'visible_update_proxy_ms':b.summary([a['visible_update_proxy_ms'] for a in actions if 'visible_update_proxy_ms' in a]),
                 'scheduled_input_to_fence_proxy_ms':b.summary([a['input_lateness_ms']+a['visible_update_proxy_ms'] for a in actions if 'input_lateness_ms' in a]),
                 'input_lateness_ms':b.summary([a['input_lateness_ms'] for a in actions if 'input_lateness_ms' in a]),
                 'incomplete_frames':sum(not a['complete_at_frame'] for a in actions if 'complete_at_frame' in a),
                 'content_settle_ms':b.summary([s['after_scroll_content_settle_ms'] for s in samples if 'after_scroll_content_settle_ms' in s]),
                 'publish_ms':b.summary([p['ms'] for s in samples for p in s['publish_rows']]),
                 'completed_raster_ms':b.summary([p['raster_and_file_write_ms'] for s in samples for p in s['raster_rows']]),
                 'raster_receive_ms':b.summary([p['receive_ms'] for s in samples for p in s['raster_rows']]),
                 'cache_deltas':[{'jobs':s['cache_after']['render_jobs']-s['cache_before']['render_jobs'],
                                 'cancelled':s['cache_after']['cancelled_jobs']-s['cache_before']['cancelled_jobs'],
                                 'hits':s['cache_after']['raster_cache']['hits']-s['cache_before']['raster_cache']['hits'],
                                 'misses':s['cache_after']['raster_cache']['misses']-s['cache_before']['raster_cache']['misses']}
                                  for s in samples]}
        rows.append(summary)
    for r in reports:
        m=r['monitor']['rows'];trans=r['layout_transports']
        native.append({'mode':mode,'run':r['run'],'window':r['window'],'viewport':r['viewport'],
            'dpr':r['dpr'],'screen':r['screen'],'pages':r['pages'],'instances':r['instances'],'diagnostics':r['diagnostics'],
            'rss_peak_mib':max(x['rss_bytes'] for x in m)/1024**2,
            'cpu_seconds':m[-1]['cpu_seconds']-m[0]['cpu_seconds'],
            'global_vram_peak_mib':max(x.get('global_vram_bytes',0) for x in m)/1024**2,
            'global_gpu_percent_median':b.summary([x['global_gpu_percent'] for x in m if 'global_gpu_percent' in x]).get('median'),
            'foreground_complete':True,'transport_bytes':b.summary([x['bytes'] for x in trans if 'bytes' in x]),
            'transport_compute_ms':b.summary([x['compute_ms'] for x in trans if 'compute_ms' in x]),
            'transport_pack_ms':b.summary([x['pack_ms'] for x in trans if 'pack_ms' in x]),
            'transport_pickle_ms':b.summary([x['pickle_ms'] for x in trans if 'pickle_ms' in x]),
            'transport_decode_ms':b.summary([x['decode_ms'] for x in trans if 'decode_ms' in x]),
            'selection_probe':r.get('selection_probe'),'stale_click_disabled_at_submit':r.get('stale_click_disabled_at_submit')})

stage=read('stage-samples.json');geometry=read('geometry-v3-samples.json');ipc=read('ipc-v2-samples.json');a=read('a-followup.json')
warm_ipc=[dict(r,size_key='x'.join(map(str,r['size']))) for r in ipc['samples'] if r['repeat']>0]
groups=lambda data,keys,value:[dict(zip(keys,key),summary=b.summary([r[value] for r in data if tuple(r[k] for k in keys)==key]))
                              for key in sorted({tuple(r[k] for k in keys) for r in data})]
output={'native_scenarios':rows,'native_resources':native,
        'backend_stages':groups(stage,('kind','mode'),'ms'),
        'admission_stages':groups(a['admission'],('mode',),'ms'),
        'geometry_stages':groups(geometry['samples'],('mode',),'total_ms'),
        'geometry_quality':geometry['quality_vs_svg'],
        'ipc_stages':groups(warm_ipc,('backend','mode','size_key'),'end_to_ready_ms'),
        'ipc_release_inclusive':groups(warm_ipc,('backend','mode','size_key'),'release_inclusive_ms'),
        'trial_exclusion_reasons':read('trial-exclusion-reasons.json')}
tag='-'+sys.argv[1] if len(sys.argv)>1 else ''
b.save('summary'+tag+'.json',output)
lines=['| 场景：完整内容就绪 ms，中位数 / P95（3 次） | 当前线程 | 普通进程 | 紧凑进程 | 缓存准入 | 可见块预算 |',
       '|---|---:|---:|---:|---:|---:|']
for kind in [s['name'] for s in reports[0]['scenarios']]:
    values=[]
    for mode in ('thread','process','compact','admission','visible4'):
        v=next(r for r in rows if r['mode']==mode and r['scenario']==kind)['complete_wall_ms']
        values.append(f"{v['median']:.2f} / {v['p95']:.2f}")
    lines.append('| '+kind+' | '+' | '.join(values)+' |')
(b.OUT/('native-table'+tag+'.md')).write_text('\n'.join(lines)+'\n',encoding='utf-8')
print('\n'.join(lines))
