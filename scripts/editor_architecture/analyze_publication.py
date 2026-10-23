import common as b
import json
from inkstruct.global_defaults import GlobalDefaultsStore

report={'current_machine_backend':GlobalDefaultsStore.make_settings().value('preview_backend_v1','cpu',str),
        'backend_note':'Native runs inherit the same existing machine preference. Earlier harness did not log per-request backend; actual current setting and GPU failure diagnosis recorded separately. No settings writes in the performance harness.',
        'scenarios':[],'resources':[]}
for mode in ('thread','warnings','idle'):
    runs=[json.loads((b.OUT/f'native-{mode}-{i}.json').read_text(encoding='utf-8')) for i in (20,21,22)]
    for r in runs:
        assert r['harness_version']==3 and 'error' not in r
        assert all(s['foreground_fraction_frames']==1 and s['foreground'] for s in r['scenarios'])
        samples=r['monitor']['rows']
        report['resources'].append({'mode':mode,'run':r['run'],
            'rss_peak_mib':max(x['rss_bytes'] for x in samples)/1024**2,
            'cpu_seconds':samples[-1]['cpu_seconds']-samples[0]['cpu_seconds'],
            'vram_global_peak_mib':max(x.get('global_vram_bytes',0) for x in samples)/1024**2})
    for kind in (s['name'] for s in runs[0]['scenarios']):
        samples=[next(s for s in r['scenarios'] if s['name']==kind) for r in runs]
        actions=[a for s in samples for a in s.get('actions',[])]
        report['scenarios'].append({'mode':mode,'name':kind,
            'full_content_wall_ms':b.summary([s['wall_ms'] for s in samples]),
            'input_return_ms':b.summary([s['input_return_ms'] for s in samples if 'input_return_ms' in s]),
            'publish_ms':b.summary([p['ms'] for s in samples for p in s['publish_rows']]),
            'visual_ms':b.summary([a['visible_update_proxy_ms'] for a in actions if 'visible_update_proxy_ms' in a]),
            'scheduled_to_visual_ms':b.summary([a['input_lateness_ms']+a['visible_update_proxy_ms'] for a in actions if 'input_lateness_ms' in a]),
            'frame_summary_each':[s['frame_ms'] for s in samples],
            'max_heartbeat_gap_ms':max(s['heartbeat_gap_ms'].get('max',0) for s in samples),
            'cancelled_jobs':[s['cache_after']['cancelled_jobs']-s['cache_before']['cancelled_jobs'] for s in samples],
            'jobs':[s['cache_after']['render_jobs']-s['cache_before']['render_jobs'] for s in samples],
            'incomplete_frames':sum(not a['complete_at_frame'] for a in actions if 'complete_at_frame' in a)})
b.save('publication-idle-summary.json',report)
for row in report['scenarios']:
    if row['name'] in ('edit_digit','edit_insert','edit_formula','edit_table','edit_footnote','warm_scroll','warm_idle_scroll'):
        print(row['mode'],row['name'],round(row['full_content_wall_ms']['median'],2),
              'visible_p95',round(row['visual_ms'].get('p95',0),2),
              'scheduled_p95',round(row['scheduled_to_visual_ms'].get('p95',0),2),'jobs',row['jobs'])
