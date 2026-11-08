import common as b
import json
import pickle
with (b.OUT/'baseline-result-v2.pickle').open('rb') as file:result=pickle.load(file)
edits=json.loads((b.OUT/'scenario-edits.json').read_text(encoding='utf-8'))
digit=edits[0]['start']
paragraphs=[n for n in result['document'].nodes if n.kind=='paragraph']
boundary=min(paragraphs,key=lambda n:abs(n.span.start-digit)).span.start
for edit in edits:
    if edit['name'] in ('insert','footnote'):
        edit['start']=edit['end']=boundary
        if edit['name']=='footnote':edit['text']='12[^experiment]\n\n[^experiment]: 34 56 78\n\n'
b.save('scenario-edits-v3.json',edits)
b.save('trial-exclusion-reasons.json',{
    'runs_0_to_3':'Development trials excluded as a group, regardless of speed. Earlier cursor entry used scalar offsets before UTF16 correction, and paragraph/note insertions could start inside a formula. Trials remain intact.',
    'formal_runs':'10-12, harness_version 3, exact source transaction assertions and block-boundary insertions',
    'first_partial_timing':'a-followup plain_partial_cached includes a pre-updated parser and is excluded from partial end-to-end conclusion. correctness.json repeats with actual partial hits instead.',
    'initializer_failure':'First inventory met one of the pre-existing unreadable font files; rerun records unreadable metadata without restoring or overwriting it.',
    'first_stage_failure':'MappingProxyType was not picklable. Added private read-only mapping reducer; failed pickle/log retained.'})
print('Formal v3 edits prepared at semantic block boundary',boundary)
