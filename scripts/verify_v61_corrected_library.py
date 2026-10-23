"""Read-back verification of stored corrected-library outputs and provenance."""
import argparse
import gzip
import json
import math
from collections import Counter
from pathlib import Path

from generate_v61_library import digest, dump


def verify(root):
    manifest=json.loads((root/'protocol.json').read_text())
    assert manifest['split_rules'] and manifest['author_stroke_fallback']
    counts=Counter();failed=[]
    for group in ('inputs','code'):
        for path,h in manifest[group].items():
            if digest(path)!=h:raise ValueError(f'{group} hash mismatch: {path}')
    for w in manifest['writers']:
        for c in manifest['characters']:
            stem=root/w/f'{ord(c):04X}'
            row=json.loads(stem.with_suffix('.json').read_text())
            assert row['writer']==w and row['character']==c
            counts['records']+=1
            for file,h in row['files'].items():
                if digest(root/file)!=h:raise ValueError(f'output hash mismatch: {file}')
            if row['status']=='failed':
                failed.append({'writer':w,'character':c,'error':row['error']});continue
            data=json.loads(gzip.decompress(stem.with_suffix('.json.gz').read_bytes()))
            glyph=data['glyph'];sources=data['provenance'];strokes=glyph['strokes']
            if 'regression_exact' in data['checks']:
                path=data['logs']['reviewed_plan']['file']
                assert path in manifest['inputs']
                old=json.loads(gzip.decompress(Path(path).read_bytes()))
                old=old['B'] if 'B' in old else old['arms']['D']
                assert [s['points'] for s in old['glyph']['strokes']]==[s['points'] for s in strokes]
                assert old['provenance']==sources
                counts['reviewed_cases_final_payload_and_sources_exact']+=1
            assert len(strokes)==row['strokes']==len(row['stroke_sources'])
            missing={p['order']-1 for p in row['missing']}
            covered={int(k) for k in sources}
            assert not missing & covered and missing|covered==set(range(len(strokes)))
            assert len(covered)==row['source_strokes'] and len(missing)==row['reference_strokes']
            assert row['author_only_ready']==(not missing)==data['author_only_ready']
            assert not data['checks']['protocol'] and not data['checks']['source_integrity']
            previous=-1
            for i,s in enumerate(strokes):
                assert s['order']==i+1 and s['standard_stroke_id']==row['stroke_sources'][i]['standard_id']
                assert len(s['points'])>=2
                for p in s['points']:
                    assert all(math.isfinite(p[k]) for k in ('x','y','pressure','t_ms'))
                    assert all(0<=p[k]<=1 for k in ('x','y','pressure'))
                    assert p['t_ms']>=previous;previous=p['t_ms'];counts['points']+=1
                if i in covered:
                    source=sources[str(i)]
                    assert source['character']!=c and source['sample_id'] and source['source_sha256']
                    assert set(source['transform'])=={'sx','sy','tx','ty'}
                    counts[source['kind']]+=1
                else:assert row['stroke_sources'][i]['kind']=='explicit_gap'
            counts['strokes']+=len(strokes);counts['source_strokes']+=len(covered);counts['missing_strokes']+=len(missing)
    counts['failed']=len(failed)
    summary=json.loads((root/'summary.json').read_text())
    assert summary['expected_outputs']==counts['records']
    assert summary['source_strokes']==counts['source_strokes']
    assert summary['reference_strokes']==counts['missing_strokes']
    result={'counts':dict(counts),'failed':failed,'input_and_code_hashes_verified':True,
            'stored_file_hashes_verified':True,'protocol_and_gap_partition_read_back':True,
            'source_geometry_checked_during_generation':True,'style_quality_certified':False,'verifier_sha256':digest(__file__)}
    dump(root/'verification.json',result)
    print(json.dumps(result,ensure_ascii=False),flush=True)
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('output',type=Path)
    verify(p.parse_args().output)
