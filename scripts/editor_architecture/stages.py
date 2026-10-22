import common as b
import copy
from dataclasses import replace
import json
import pickle
import time
from inkstruct.document.package import load_package,save_package
from inkstruct.editor import mixed
from inkstruct.editor.build_cache import MarkdownBuildCache
from incremental import IncrementalParser

trace=b.instrument()
loaded=load_package(b.INPUT)
args=b.build_inputs(loaded)
cache=MarkdownBuildCache()
start=time.perf_counter();first=mixed.build_markdown(**args,cache=cache)
cold={'ms':(time.perf_counter()-start)*1000,'stages':trace.aggregate(),'cache':cache.statistics()}
# Store private derived fixture and a pickled trusted experiment snapshot only.
with (b.OUT/'baseline-result-v2.pickle').open('xb') as file:pickle.dump(first,file,protocol=5)
b.save('input-record.json',{'path':str(b.INPUT),'sha256':b.sha(b.INPUT),
       'real_small_path':str(b.REAL),'real_small_sha256':b.sha(b.REAL),
       'pages':len(first['snapshot'].pages),'instances':len(first['snapshot'].fragments),
       'diagnostics':len(first['snapshot'].diagnostics),'cold':cold})
args['resolver']=first['resolver']
fragments=first['snapshot'].pages[len(first['snapshot'].pages)//2].fragments
digit=next(f.span.start for f in fragments if f.text.isascii() and f.text.isdigit()
           and loaded.session.source[f.span.start:f.span.end]==f.text)
formula=next(n.span for root in first['document'].nodes for n in root.walk() if n.math)
table=next((n.span for root in first['document'].nodes for n in root.walk() if n.kind=='table'),None)
scenarios=[('digit',digit,digit+1,'1' if loaded.session.source[digit]!='1' else '2'),
           ('insert',digit,digit,'\n\n'+'1234567890 '*35+'\n\n'),
           ('formula',formula.start,formula.end,'$\\frac{12}{3}+4$')]
if table:
    pos=next(i for i in range(table.start,table.end) if loaded.session.source[i].isdigit())
    scenarios.append(('table',pos,pos+1,'9'))
else:scenarios.append(('table',digit,digit,'\n\n|12|34|\n|---|---|\n|56|78|\n\n'))
scenarios.append(('footnote',digit,digit,'12[^experiment]\n\n[^experiment]: 34 56 78\n\n'))
rows=[]
for kind,a,z,text in scenarios:
    for repeat in range(3):
        session=copy.deepcopy(loaded.session)
        started=time.perf_counter();session.apply(a,z,text);input_ms=(time.perf_counter()-started)*1000
        inputs=dict(args,session=session,revision=session.revision)
        results={}
        for mode in ('full','current','incremental'):
            local_cache=None if mode=='full' else MarkdownBuildCache()
            parser=IncrementalParser() if mode=='incremental' else None
            original=mixed.parse_markdown
            if parser:mixed.parse_markdown=parser
            try:
                if local_cache:mixed.build_markdown(**args,cache=local_cache)
                index=len(trace.rows);started=time.perf_counter()
                value=mixed.build_markdown(**inputs,cache=local_cache)
                ms=(time.perf_counter()-started)*1000
            finally:mixed.parse_markdown=original
            results[mode]=value
            row={'kind':kind,'repeat':repeat,'mode':mode,'ms':ms,'input_identity_ms':input_ms,
                 'stages_inclusive_not_additive':trace.aggregate(index),
                 'cache':local_cache.statistics() if local_cache else None,
                 'partial_parse_hits':parser.hits if parser else None,
                 'snapshot_id':value['snapshot'].snapshot_id,'pages':len(value['snapshot'].pages)}
            rows.append(row);print(kind,repeat,mode,round(ms,2),flush=True)
        assert results['full']['snapshot']==results['current']['snapshot']==results['incremental']['snapshot'],kind
        assert results['full']['document']==results['incremental']['document'],kind
        assert results['full']['resolver'].selection_records()==results['incremental']['resolver'].selection_records()
b.save('stage-samples.json',rows)
b.save('scenario-edits.json',[dict(name=k,start=a,end=z,text=t) for k,a,z,t in scenarios])
print('All five scenarios: full/current/partial parse snapshot, source mapping, diagnostics and selections exact')
