"""Independent exact geometry/provenance/export and preservation verification."""
import bootstrap as b
import gzip
import hashlib
import json
from pathlib import Path

def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for block in iter(lambda:f.read(8*1024*1024),b''):h.update(block)
    return h.hexdigest()

def main():
    report={};comparisons=[]
    base=b.ROOT/'artifacts/v62_0.1.32_20261020/release-run/user_001'
    for backend in ('cpu','gpu'):
        for rep in (1,2,3):
            directory=b.OUT/f'pipeline-{backend}-{rep}/user_001'
            for ch in '孔正址兄礼烧止怔歪羊群':
                name=f'{ord(ch):04X}.json.gz';original=gzip.decompress((base/name).read_bytes());actual=gzip.decompress((directory/name).read_bytes())
                a=json.loads(original);c=json.loads(actual)
                assert a==c,(backend,rep,ch)
                comparisons.append({'backend':backend,'repeat':rep,'character':ch,'full_payload_equal':True,
                    'compressed_sha_equal':sha(base/name)==sha(directory/name),'gaps':len(c['missing'])})
    report['candidate_comparisons']=comparisons
    report['numeric_max_abs_error']=max(json.loads((b.OUT/f'pipeline-gpu-{n}.json').read_text(encoding='utf-8'))['gpu']['max_error'] for n in (1,2,3))
    report['warnings_preserved']={'孔':'explicit reference gap retained','正':'no new gap','羊':'existing warning retained'}

    from inkstruct.document.package import load_package,save_package
    from inkstruct.editor.mixed import build_markdown
    from inkstruct.renderers.pages import page_svg
    from inkstruct.plotter.adapters import plan_from_snapshot
    from inkstruct.plotter.export import export_plan
    loaded=load_package(b.ROOT/'artifacts/v62_0.1.32_20261020/native-saved.inkdoc')
    def build(p):return build_markdown(p.session,0,p.resolver,'','',p.page,p.style,p.flow,None)
    first=build(loaded);loaded.resolver=first['resolver'];assert first['snapshot'].plotter_exportable
    target=b.OUT/'roundtrip-real-v62.inkdoc';assert not target.exists()
    save_package(target,loaded.session,loaded.resolver,loaded.page,loaded.style,optimize=loaded.optimize,flow=loaded.flow,reviews=loaded.reviews)
    reopened=load_package(target);second=build(reopened)
    assert loaded.session.identity_record()==reopened.session.identity_record()
    assert loaded.resolver.selection_records()==second['resolver'].selection_records()
    assert (loaded.flow,loaded.page,loaded.style,loaded.reviews)==(reopened.flow,reopened.page,reopened.style,reopened.reviews)
    for s,label in ((first['snapshot'],'before'),(second['snapshot'],'reopened')):
        export_plan(plan_from_snapshot(s),b.OUT/f'svg-{label}',optimize=loaded.optimize)
    svg_hashes={}
    for index in range(len(first['snapshot'].pages)):
        assert page_svg(first['snapshot'],index)==page_svg(second['snapshot'],index)
    for p in (b.OUT/'svg-before').glob('*.svg'):
        other=b.OUT/'svg-reopened'/p.name;assert p.read_bytes()==other.read_bytes();svg_hashes[p.name]=sha(p)
    report['real_v62_roundtrip']={'source_identity_exact':True,'frozen_selections_exact':True,
        'settings_reviews_exact':True,'export_svg_bytes_exact':True,'svg_sha256':svg_hashes,
        'font_usage_warnings':first['resolver'].usage_warnings()}

    before=json.loads((b.OUT/'preservation-before.json').read_text(encoding='utf-8'))
    changed=[];missing=[]
    for rel,metadata in before.items():
        p=b.ROOT/rel
        if not p.exists():missing.append(rel)
        elif sha(p)!=metadata['sha256']:changed.append(rel)
    report['task_baseline']={'files':len(before),'changed':changed,'missing':missing}
    historical=json.loads((b.ROOT/'artifacts/v62_0.1.32_20261020/user-data-before.json').read_text(encoding='utf-8'))
    historical_changed=[];historical_missing=[];errors=[]
    for name,expected in historical.items():
        p=Path(name)
        try:
            if not p.exists():historical_missing.append(name)
            elif sha(p)!=expected:historical_changed.append(name)
        except OSError as e:errors.append({'path':name,'error':str(e)})
    report['historical_preservation']={'files':len(historical),'changed':historical_changed,'missing':historical_missing,'unreadable':errors,
        'scope':'previous delivery manifest; pre-existing inaccessible fonts listed separately, never restored'}
    from inkstruct.fonts import APP_VERSION
    assert APP_VERSION=='0.1.32';report['app_version']=APP_VERSION
    b.save('verification.json',report)
    print(json.dumps({k:v for k,v in report.items() if k not in ('candidate_comparisons','real_v62_roundtrip')},ensure_ascii=False,indent=2))
    assert not changed and not missing and not historical_changed and not historical_missing

if __name__=='__main__':main()
