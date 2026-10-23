import common as b
import copy
from dataclasses import replace
import json
import multiprocessing as mp
import pickle
import time
from PySide6 import QtGui
from inkstruct.document.editing import SourceSession
from inkstruct.document.package import load_package,save_package
from inkstruct.editor import mixed
from inkstruct.editor.build_cache import MarkdownBuildCache
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.glyph_corrections import GlyphCorrection
from inkstruct.document.flow_template import FlowTemplate,PageLayout,TextFrame
from inkstruct.document.template import Region
from inkstruct.plotter.adapters import plan_from_snapshot
from inkstruct.plotter.export import export_plan
from inkstruct.renderers.pages import page_svg
from incremental import IncrementalParser
from packed import pack_snapshot
from process_layout import worker,restore_result

def run():
    app=QtGui.QGuiApplication([]);real=load_package(b.REAL);checks=[]
    sources=[
        '123 456\n\n789 012\n\n345 678',
        '1. 123\n2. 456\n\n789',
        '123\n===\n\n456',
        '123\n\n```\n:::field 12\n```\n\n456',
        '123[^a]\n\n456\n\n[^a]: $\\frac{12}{3}$',
        '123\n\n|1|2|\n|---|---|\n|3|4|',
        '$\\frac{12}{3}$\n\n456',
        ':::field name\n123\n:::\n\n456',
    ]
    for source in sources:
        s=SourceSession(source);parser=IncrementalParser();parser(s,field_blocks=':::field name' in source)
        pos=source.rfind('4') if '4' in source else source.find('1')
        s.apply(pos,pos+1,'9')
        actual=parser(s,field_blocks=':::field name' in source)
        assert actual==parse_markdown(s,field_blocks=':::field name' in source)
        checks.append({'case':source,'partial_hits':parser.hits,'full_fallbacks':parser.fallbacks,'exact_ast_spans_ids_diagnostics':True})
    # A confirmed partial-parse hit, measured separately without pre-updating the parser.
    loaded=load_package(b.OUT/'plain-real-font.inkdoc');args=b.build_inputs(loaded)
    cache=MarkdownBuildCache();parser=IncrementalParser();original=mixed.parse_markdown
    mixed.parse_markdown=parser
    try:mixed.build_markdown(**args,cache=cache)
    finally:mixed.parse_markdown=original
    timing=[]
    for repeat in range(5):
        pos=loaded.session.source.index('1',len(loaded.session.source)//2)
        loaded.session.apply(pos,pos+1,'9');args['revision']=loaded.session.revision
        prev=parser.previous
        start=time.perf_counter();full=mixed.build_markdown(**args);full_ms=(time.perf_counter()-start)*1000
        mixed.parse_markdown=parser
        try:
            start=time.perf_counter();actual=mixed.build_markdown(**args,cache=cache);partial_ms=(time.perf_counter()-start)*1000
        finally:mixed.parse_markdown=original
        assert parser.hits==repeat+1
        assert actual['snapshot']==full['snapshot'] and actual['document']==full['document']
        assert actual['resolver'].selection_records()==full['resolver'].selection_records()
        timing.append({'full_ms':full_ms,'partial_cached_ms':partial_ms,'hits':parser.hits})
    # Corrected real handwritten glyph, packed coordinate preservation, roundtrip and SVG.
    args=b.build_inputs(real);base=mixed.build_markdown(**args)
    f=next(f for f in base['snapshot'].fragments if f.asset_id and f.text=='2')
    correction=GlyphCorrection('occurrence',f.text,f.occurrence_id,f.asset_id,.02,-.01,1.03,.98)
    args['flow']=replace(args['flow'],glyph_corrections=(correction,))
    corrected=mixed.build_markdown(**args);packed=pack_snapshot(corrected['snapshot'])
    assert packed==corrected['snapshot']
    for i in range(len(packed.pages)):
        assert page_svg(packed,i)==page_svg(corrected['snapshot'],i)
    plan=plan_from_snapshot(corrected['snapshot']);other=plan_from_snapshot(packed)
    assert plan==other
    export_plan(plan,b.OUT/'correctness-original-svg')
    export_plan(other,b.OUT/'correctness-packed-svg')
    assert all(p.read_bytes()==(b.OUT/'correctness-packed-svg'/p.name).read_bytes() for p in (b.OUT/'correctness-original-svg').iterdir())
    save_package(b.OUT/'corrected-roundtrip.inkdoc',args['session'],corrected['resolver'],args['page'],args['style'],flow=args['flow'])
    reopened=load_package(b.OUT/'corrected-roundtrip.inkdoc');again=mixed.build_markdown(**b.build_inputs(reopened))
    assert again['snapshot']==corrected['snapshot'] and reopened.flow==args['flow']
    assert again['resolver'].selection_records()==corrected['resolver'].selection_records()
    # Two different-width frames in a four-layout loop: packed pages retain exact results.
    def frame(key,x,w,order):return TextFrame(key,key,Region(key,x,10,w,35),'body',order)
    layouts=tuple(PageLayout(str(i),str(i),(frame('a'+str(i),5,35,1),frame('b'+str(i),60,50,2))) for i in range(4))
    template=FlowTemplate(name='experiment',kind='custom',width_mm=120,height_mm=120,layouts=layouts,loop_pages=tuple(str(i) for i in range(4)))
    args=b.build_inputs(real);args['session']=SourceSession('\n\n'.join('12 34 56 78 90 '*4 for _ in range(30)))
    args['flow']=replace(args['flow'],template=template)
    value=mixed.build_markdown(**args);assert pack_snapshot(value['snapshot'])==value['snapshot']
    assert len(value['snapshot'].pages)>=4
    # Persistent process result parity; stale job kept separate and hard crash CPU fallback.
    ctx=mp.get_context('spawn');conn,child=ctx.Pipe();event=ctx.Event()
    process=ctx.Process(target=worker,args=(child,event,str(b.REAL),str(b.OUT/'tmp'),True));process.start();conn.recv()
    args=b.build_inputs(real);request={k:args[k] for k in ('session','revision','page','style','flow')}
    conn.send(dict(request,token=90001));response=conn.recv();assert 'error' not in response,response
    path=b.OUT/'tmp/layout-90001.pickle';payload=pickle.loads(path.read_bytes());path.unlink()
    remote=restore_result(payload,real.resolver);control=mixed.build_markdown(**args)
    assert remote['snapshot']==control['snapshot'] and remote['document']==control['document']
    assert remote['resolver'].selection_records()==control['resolver'].selection_records()
    process.terminate();process.join(timeout=5)
    start=time.perf_counter();fallback=mixed.build_markdown(**args)
    assert fallback['snapshot']==control['snapshot']
    b.save('correctness.json',{'parser_cases':checks,'guarded_partial_end_to_end':timing,
           'packed_binary64_and_correction_geometry_exact':True,'roundtrip_svg_selections_and_settings_exact':True,
           'four_layout_loop_different_width_frames_exact':True,'process_return_vs_full_exact':True,
           'process_crash_local_cpu_fallback_ms':(time.perf_counter()-start)*1000,
           'note':'Process cancellation uses shared Event; native output version guards discard stale results. Shared-image expiry/crash tests are in ipc-samples.json.'})
    print('Prototype correctness and real-font save/reopen/export checks passed')

if __name__=='__main__':mp.freeze_support();run()
