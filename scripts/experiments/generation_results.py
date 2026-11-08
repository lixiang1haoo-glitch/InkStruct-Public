"""Aggregate raw measurements without discarding slow/failing trials."""
from pathlib import Path
import json
import statistics
import sys
import gzip
from dataclasses import asdict
sys.path.insert(0,str(Path(__file__).resolve().parent))
from generation_parallel import ROOT,OUT,save,digest,canonical


def stats(values):
    if not values:return {'n':0}
    values=sorted(values)
    k=(len(values)-1)*.95;lo=int(k);hi=min(lo+1,len(values)-1)
    return {'n':len(values),'median':statistics.median(values),'min':values[0],'p95':values[lo]+(values[hi]-values[lo])*(k-lo),'max':values[-1]}


def main():
    records=[];groups={};tasks=[];artifacts=[]
    inputs=json.loads((OUT/'inputs.json').read_text('utf-8'))
    from inkstruct.v62_semantics import PARAMETERS as semantic_parameters,VERSION as semantic_version
    from inkstruct.v61_author_strokes import PARAMETERS as stroke_parameters
    from inkstruct.reuse_rules import RULES,VERSION as reuse_version
    from inkstruct.positional_variants import PARAMETERS as positional_parameters,FAMILIES
    from inkstruct.v61_candidate_expansion import ExpansionPolicy
    parameters={'semantic':semantic_parameters,'semantic_version':semantic_version,'stroke':stroke_parameters,
                'reuse_rules':RULES,'reuse_version':reuse_version,'positional':positional_parameters,'families':FAMILIES,
                'expansion':asdict(ExpansionPolicy(context=True,hierarchy=True,nested=True,whole_target=True,anisotropic=True))}
    import numpy,sqlite3
    environment={'python':sys.version,'numpy':numpy.__version__,'sqlite':sqlite3.sqlite_version,'precision':'NumPy float64',
                 'numeric_threads':inputs['numpy_threads']}
    for path in sorted(OUT.glob('*/measurement.json')):
        item=json.loads(path.read_text('utf-8'));label=path.parent.name
        first=item['rounds'][0]['wall_s']+(item['initialization']['initialization_s'] if item['initialization'] else 0.)
        warm=[r['wall_s'] for r in item['rounds'][1:]]
        cpu=[r['cpu_s'] for r in item['monitor']]
        reads=[r['read_bytes'] for r in item['monitor']];writes=[r['write_bytes'] for r in item['monitor']]
        row={'label':label,'mode':item['mode'],'workers':item['workers'],'targets':len(item['rounds'][0]['characters']),
             'cold_resource_ready_and_batch_s':first,'warm_s':warm,'total_including_all_rounds_shutdown_s':item['total_including_shutdown_s'],
             'peak_group_rss_MiB':item['peak_group_rss']/2**20,'sampled_group_cpu_s_approx':max(cpu)-cpu[0],
             'process_io_read_bytes_approx':max(reads)-reads[0],'process_io_write_bytes_approx':max(writes)-writes[0],
             'sampling_caveat':'10Hz process-tree sums; counters can fall when children exit; use sampled maximum; process I/O includes cached reads, not physical disk throughput'}
        records.append(row)
        cohort=('loaded-small' if label.startswith('small-') else 'loaded-representative' if label.startswith('representative-')
                else 'quiet-representative' if label.startswith('quiet-representative-') else label)
        key=f"{cohort}/{item['mode']}/{item['workers']}"
        group=groups.setdefault(key,{'cold':[],'warm':[],'total':[],'rss':[]})
        group['cold'].append(first);group['warm'].extend(warm);group['total'].append(row['total_including_all_rounds_shutdown_s']);group['rss'].append(row['peak_group_rss_MiB'])
        for repeat in item['rounds']:
            folder=path.parent/f"round-{repeat['round']}"
            for record in repeat['results']:
                character=record['character'];stem=folder/'user_001'/f'{ord(character):04X}'
                side=json.loads(stem.with_suffix('.json').read_text('utf-8'))
                for name,expected in side.get('files',{}).items():
                    assert digest(folder/name)==expected,(label,character,'binary hash')
                payload=None if record['status']=='failed' else json.loads(gzip.decompress(stem.with_suffix('.json.gz').read_bytes()))
                assert canonical(payload)==record['payload_hash'],(label,character,'payload modified')
                artifacts.append({'label':label,'round':repeat['round'],'character':character,'payload_hash':record['payload_hash'],'status':record['status'],'warnings':record['warnings']})
            task={'schema':'isolated-generation-task-v1','scope_label':label,'round':repeat['round'],'method':'v6.2 exp',
                  'method_version':__import__('inkstruct.generation_workflow',fromlist=['V62_VERSION']).V62_VERSION,
                  'actual_targets':repeat['characters'],'target_sha256':canonical(repeat['characters']),
                  'full_donor_resources':inputs['resources'],'source_code':inputs['code'],'complete_results':repeat['results'],
                  'parameters':parameters,'environment':environment,'compatibility_sha256':canonical({'method':'v6.2 exp','parameters':parameters,'resources':inputs['resources'],'code':inputs['code'],'environment':environment}),
                  'compatibility_rule':'method + all effective parameters/rules + profile and donor identity + structure/reference/correction identity + generation implementation and checks must match; presence of Unicode alone is insufficient'}
            save(folder/'task-identity.json',task);tasks.append({'label':label,'round':repeat['round'],'identity':canonical(task)})
    grouped={key:{part:stats(values) for part,values in value.items()} for key,value in groups.items()}
    native=[]
    reference={r['character']:r['payload_hash'] for r in json.loads((OUT/'small-serial-1/round-0/summary.json').read_text('utf-8'))['results']}
    for path in sorted(OUT.glob('native*/measurements.json')):
        value=json.loads(path.read_text('utf-8'))
        for row in value.get('trials',[]):
            for char,expected in reference.items():
                payload=json.loads(gzip.decompress((path.parent/row['label']/'user_001'/f'{ord(char):04X}.json.gz').read_bytes()))
                assert canonical(payload)==expected,(str(path),row['label'],char)
            native.append({'experiment':path.parent.name,'label':row['label'],'foreground_valid':row['foreground_valid'],
                           'foreground_fraction':row['foreground_fraction'],'wall_s':row['wall_s'],
                           'heartbeat_ms':stats(row['heartbeat_ms']),'input_to_paint_ms':stats(row['input_to_paint_ms']),
                           'all_character_payloads_exact':True})
    save(OUT/'performance-summary.json',{'groups':grouped,'trials':records,'native':native,
         'boundaries':'cold=initialized resources plus first batch; process first batch includes worker startup. Warm=rounds after first. Full trial includes initialization, summary writing and shutdown.',
         'cohort_caveat':'loaded cohort had active game/automation; quiet cohort follows user pause, with separately recorded telemetry. Never merge these conditions.',
         'verified_artifact_records':len(artifacts),'task_identities':tasks,'all_results':artifacts})
    print('Summarized',len(records),'trials,',len(artifacts),'verified records,',len(native),'native trials',flush=True)


if __name__=='__main__':main()
