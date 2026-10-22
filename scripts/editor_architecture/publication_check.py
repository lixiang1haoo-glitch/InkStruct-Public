import common as b
import pickle
import time
from types import SimpleNamespace
from publication import warning_membership
from inkstruct.editor.mixed import MixedWindow

with (b.OUT/'baseline-result-v2.pickle').open('rb') as file:result=pickle.load(file)
owner=SimpleNamespace(markdown_document=result['document'],resolver=result['resolver'])
rows=[]
for repeat in range(5):
    for pending in (False,True):
        start=time.perf_counter();reference=MixedWindow.current_font_warnings(owner,pending_only=pending);baseline_ms=(time.perf_counter()-start)*1000
        start=time.perf_counter();actual=warning_membership(owner,pending_only=pending);indexed_ms=(time.perf_counter()-start)*1000
        assert actual==reference
        rows.append({'repeat':repeat,'pending_only':pending,'baseline_ms':baseline_ms,'indexed_ms':indexed_ms,'warnings':len(actual),
                     'result_sha256':b.sha_bytes(repr(actual).encode())})
b.save('publication-correctness.json',{'samples':rows,'all_warnings_and_acceptance_states_exact':True})
print('All warning records identical; no warning hidden or severity changed')
