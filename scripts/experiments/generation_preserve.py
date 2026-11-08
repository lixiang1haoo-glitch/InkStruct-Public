"""Read-only preservation audit, then remove only this experiment's caches."""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess
import sys
import time
from xml.etree import ElementTree
sys.path.insert(0,str(Path(__file__).resolve().parent))
from generation_parallel import ROOT,OUT,save,digest


def main():
    before=json.loads((OUT/'source-before.json').read_text('utf-8'))
    changes=[]
    for name,expected in before.items():
        path=ROOT/name
        if not path.is_file() or digest(path)!=expected:changes.append(name)
    assert not changes,changes
    assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT)==(OUT/'git-head-before.txt').read_bytes()
    from inkstruct.fonts import APP_VERSION
    assert APP_VERSION==json.loads((OUT/'inputs.json').read_text('utf-8'))['app_version']=='0.1.38'
    metadata=json.loads((OUT/'user-data-before-metadata.json').read_text('utf-8'))
    previous=json.loads((ROOT/'artifacts/export_parallel_0.1.38_20261022/user-data-before.json').read_text('utf-8'))
    changed=[];metadata_exact=0;historical_matches=0;historical_differences=[];unreadable=[]
    for index,(name,record) in enumerate(metadata.items()):
        path=Path(name)
        try:
            stat=path.stat()
            if stat.st_size==record['size'] and stat.st_mtime_ns==record['mtime_ns']:metadata_exact+=1
            else:changed.append({'path':name,'before':record,'after':{'size':stat.st_size,'mtime_ns':stat.st_mtime_ns}})
            if previous.get(name,{}).get('sha256'):
                if digest(path)==previous[name]['sha256']:historical_matches+=1
                else:historical_differences.append(name)
        except OSError as error:unreadable.append({'path':name,'error':str(error)})
        if index%4000==0:print('preservation',index,len(metadata),flush=True)
    preservation={'source_files_exact':len(before),'source_changes':changes,'head_exact':True,'app_version':APP_VERSION,
                  'user_file_count':len(metadata),'metadata_exact':metadata_exact,'metadata_changed':changed,
                  'matches_previous_delivery_sha256':historical_matches,'differs_from_previous_delivery_sha256':historical_differences,
                  'metadata_only_paths':[name for name in metadata if not previous.get(name,{}).get('sha256')],
                  'unreadable':unreadable,
                  'scope':'this-run pre-snapshot captured size/mtime; additionally compare readable contents with previous delivery SHA baseline. Do not infer when an older-baseline difference occurred; never restore automatically.'}
    save(OUT/'preservation.json',preservation)
    assert not changed,changed
    assert not historical_differences,historical_differences
    # Only this experiment's rebuildable directories. Resolve before every
    # recursive deletion; retain logs, all results, PDFs, fonts and frozen EXEs.
    removed=[]
    for name in ('tmp','mpl-cache','pytest-temp','frozen-probe-work','frozen-probe-v2-work'):
        path=(OUT/name).resolve()
        assert path.parent==OUT.resolve() and path.is_relative_to((ROOT/'artifacts').resolve())
        if path.is_dir():shutil.rmtree(path);removed.append(str(path))
    for source in (ROOT/'scripts/experiments').glob('generation_*.py'):
        for cache in (source.parent/'__pycache__').glob(source.stem+'.cpython-*.pyc'):
            assert cache.parent.resolve()==(ROOT/'scripts/experiments/__pycache__').resolve()
            cache.unlink();removed.append(str(cache))
    save(OUT/'cleanup.json',{'removed_rebuildable':removed,'preserved':'all raw logs, failed trials, generation outputs, font, inkdoc, SVG, frozen probe dist and spec'})
    (OUT/'git-status-after.txt').write_bytes(subprocess.check_output(['git','status','--short','--untracked-files=all'],cwd=ROOT))
    final_sources={p.relative_to(ROOT).as_posix():digest(p) for p in (ROOT/'scripts/experiments').glob('generation_*.py')}
    save(OUT/'experiment-source-final.json',final_sources)
    suite=ElementTree.parse(OUT/'regression.xml').getroot().find('testsuite')
    assert suite is not None and suite.attrib['failures']==suite.attrib['errors']=='0'
    frozen=json.loads((OUT/'frozen-probe-v2-run/verification.json').read_text('utf-8'));assert frozen['passed']
    font=json.loads((OUT/'font-validation/verification.json').read_text('utf-8'));assert font['passed']
    faults=json.loads((OUT/'faults/verification.json').read_text('utf-8'));assert faults['passed']
    comparison=json.loads((OUT/'comparison.json').read_text('utf-8'));assert not comparison['mismatches']
    native=json.loads((OUT/'native-eventloop/measurements.json').read_text('utf-8'));assert native['passed']
    save(OUT/'final-verification.json',{'passed':True,'official_application_release':False,'app_version':APP_VERSION,
         'production_sources_unchanged':True,'preservation':preservation,'regression':suite.attrib,'frozen_probe_passed':True,
         'frozen_initial_attempt_failed':'uncollected dynamic uuid dependency; first build/logs retained; second explicit dependency build passed',
         'production_frozen_application_integration':'not tested; minimal harness uses explicit external source/runtime',
         'font':font['font'],'font_sha256':font['sha256'],'comparison':comparison,
         'native_foreground_trials':len(native['trials']),'native_foreground_fraction':[r['foreground_fraction'] for r in native['trials']]})
    print('Preservation and final verification passed',metadata_exact,historical_matches,flush=True)


if __name__=='__main__':main()
