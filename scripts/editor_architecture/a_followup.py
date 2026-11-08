import common as b
import copy
import cProfile
from dataclasses import replace
import pickle
import pstats
import io
import time
from inkstruct.document.editing import SourceSession
from inkstruct.document.package import load_package,save_package
from inkstruct.editor import mixed
from inkstruct.editor.build_cache import MarkdownBuildCache
from incremental import IncrementalParser
from admission import configure,install_weight_shortcut

def run():
    loaded=load_package(b.INPUT);args=b.build_inputs(loaded)
    edits=__import__('json').loads((b.OUT/'scenario-edits.json').read_text(encoding='utf-8'))
    rows=[]
    for mode in ('current','layout_admission','continuation_admission','admission'):
        for repeat in range(3):
            cache=MarkdownBuildCache();before=mixed.build_markdown(**args,cache=cache)
            old_weight=None
            if mode!='current':
                configure(cache,loaded.resolver,layout=mode!='continuation_admission',continuation=mode!='layout_admission')
                if mode!='continuation_admission':old_weight=install_weight_shortcut(loaded.resolver)
            session=copy.deepcopy(loaded.session);e=edits[0];session.apply(e['start'],e['end'],e['text'])
            inputs=dict(args,session=session,revision=session.revision)
            try:
                start=time.perf_counter();result=mixed.build_markdown(**inputs,cache=cache);ms=(time.perf_counter()-start)*1000
            finally:
                if old_weight:mixed.snapshot_weight=old_weight
            full=mixed.build_markdown(**inputs)
            assert result['snapshot']==full['snapshot']
            assert result['resolver'].selection_records()==full['resolver'].selection_records()
            rows.append({'mode':mode,'repeat':repeat,'ms':ms,'cache':cache.statistics()})
    profile=cProfile.Profile();profile.enable();mixed.build_markdown(**args,cache=MarkdownBuildCache());profile.disable()
    profile.dump_stats(str(b.OUT/'layout-cold.prof'))
    text=io.StringIO();pstats.Stats(profile,stream=text).sort_stats('cumtime').print_stats(35)
    (b.OUT/'layout-cold-profile.txt').write_text(text.getvalue(),encoding='utf-8')
    # Restricted fast-path positive case, using real recorded samples; no fake font.
    real=load_package(b.REAL);real.session=SourceSession('\n\n'.join('1234567890 1234567890' for _ in range(90)))
    save_package(b.OUT/'plain-real-font.inkdoc',real.session,real.resolver,real.page,real.style,flow=real.flow)
    inputs=b.build_inputs(real);parser=IncrementalParser();cache=MarkdownBuildCache()
    old_parse=mixed.parse_markdown;mixed.parse_markdown=parser
    try:base=mixed.build_markdown(**inputs,cache=cache)
    finally:mixed.parse_markdown=old_parse
    partial=[]
    for repeat in range(3):
        pos=len(real.session.source)//2
        while not real.session.source[pos].isdigit():pos+=1
        real.session.apply(pos,pos+1,'9' if real.session.source[pos]!='9' else '8')
        inputs['revision']=real.session.revision
        start=time.perf_counter();full=mixed.build_markdown(**inputs,cache=None);full_ms=(time.perf_counter()-start)*1000
        start=time.perf_counter();reference=old_parse(real.session);parse_full=(time.perf_counter()-start)*1000
        start=time.perf_counter();doc=parser(real.session);parse_partial=(time.perf_counter()-start)*1000
        assert doc==reference
        mixed.parse_markdown=parser
        try:
            # Seed parser's prior version explicitly; above direct timing updated it.
            start=time.perf_counter();actual=mixed.build_markdown(**inputs,cache=cache);partial_ms=(time.perf_counter()-start)*1000
        finally:mixed.parse_markdown=old_parse
        assert actual['snapshot']==full['snapshot'] and actual['document']==full['document']
        partial.append({'repeat':repeat,'full_ms':full_ms,'partial_cached_ms':partial_ms,
                        'full_parse_ms':parse_full,'partial_parse_ms':parse_partial,'hits':parser.hits,
                        'pages':len(actual['snapshot'].pages),'cache':cache.statistics()})
    b.save('a-followup.json',{'admission':rows,'plain_partial':partial,
           'catalog_input':str(b.INPUT),'partial_input':str(b.OUT/'plain-real-font.inkdoc'),
           'all_geometry_diagnostics_source_ids_and_selections_exact':True})
    print('Admission and guarded incremental parse measured; exact geometry parity',flush=True)

if __name__=='__main__':run()
