"""Explicit target manifests; no simplified conversion or donor filtering."""
from __future__ import annotations
import json
import hashlib
from pathlib import Path
import sys
import time
import zipfile
from dataclasses import asdict

sys.path.insert(0,str(Path(__file__).resolve().parent))
from generation_parallel import ROOT,OUT,DATABASE,save,canonical,digest
from inkstruct.structures import StructureRepository
from inkstruct.assets.glyph_provider import is_han
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.source import clusters
import unicodedata


def han_text(text):
    return any(is_han(c) or unicodedata.name(c,'').startswith('CJK COMPATIBILITY IDEOGRAPH')
               or c=='〇' for c in text)


def targets(text, supported, identity):
    requested=list(dict.fromkeys(c for _,c in clusters(text) if not c.isspace()))
    return {'schema':'experimental-target-manifest-v1','identity':identity,
            'requested':requested,'supported':[c for c in requested if c in supported],
            'unsupported':[c for c in requested if c not in supported],
            'empty':not requested,'target_sha256':canonical(requested),
            'donor_scope':'complete unchanged user_001 source archive; never filter by targets'}


def markdown_targets(source):
    document=parse_markdown(source,field_blocks=True)
    found=[]
    for occurrence in document.occurrences:
        if han_text(occurrence.text):
            found.append((occurrence.span.start,occurrence.text,asdict(occurrence.span),'text'))
    for root in document.nodes:
        for node in root.walk():
            if node.math:
                for math in node.math.walk():
                    if math.occurrence_id and han_text(math.value):
                        found.append((math.span.start,math.value,asdict(math.span),'math'))
    found.sort(key=lambda row:row[0])
    return ''.join(r[1] for r in found),found,[asdict(d) for d in document.diagnostics]


def main():
    supported=set(StructureRepository(DATABASE).characters())
    # Four entries from Unicode's primary proposal appendix; this is ONLY a
    # verified representative subset, not a complete simplification classifier.
    mainland=targets('一乙二十',supported,{
        'label':'通用规范汉字表（2013）代表子集，序号0001—0004','complete':False,
        'source':'https://www.unicode.org/L2/L2019/19160-adding-ktghz-2013.pdf',
        'authority':'2019 UTC proposal appendix B quoting 2013 normative list; first four entries verified in indexed primary source text',
        'official_publication':'https://www.moe.gov.cn/jyb_sjzl/ziliao/A19/201306/t20130601_186002.html',
        'limitation':'official full attachment could not be fetched; no full simplified-list claim'})
    traditional=targets('的一是了不我有在人來大上這到們個小你子他以好為就生要說中',supported,{
        'label':'臺灣常用國字標準字體表（1982）官方比對表前28項','complete':False,
        'source':'https://language.moe.gov.tw/001/Upload/files/SITE_CONTENT/M0001/PRIMARY/shrest2-18.htm',
        'table_identifiers':[2724,1,1791,46,10,1473,1842,743,68,138,848,7,4136,348,183,190,1068,124,982,82,78,883,2395,1074,2623,3763,3839,20],
        'limitation':'regional standard subset, not every traditional/regional variant'})
    custom=targets('孔正孔 發髮发 臺台台 A😀𰻞',supported,{'label':'literal custom regression list','complete':True})
    markdown=':::field name\n孔正\n:::\n\n# 孔正\n\n[止](https://example.org/網址) ![羊](不存在.png)\n\n$U_{正}=1$\n\n`群`\n\n```text\n兄\n```\n'
    save(OUT/'target-source-specimens.json',{'mainland':mainland,'traditional':traditional,
         'retrieved':'2026-10-22','not_classification':'No GB2312 complement, Unicode range classifier, or one-to-many conversion used'})
    (OUT/'targets-input.md').write_text(markdown,'utf-8')
    han,mappings,diagnostics=markdown_targets(markdown)
    md=targets(han,supported,{'label':'one authoritative Markdown parsed by current parser',
               'path':str(OUT/'targets-input.md'),'sha256':digest(OUT/'targets-input.md'),
               'policy':'all printable occurrence Han, including fields, code, math and captions; exclude URL/resource paths'})
    empty=targets(' \n\t',supported,{'label':'empty'})
    merged=targets(''.join(mainland['requested']+traditional['requested']+custom['requested']),supported,{'label':'stable union','parents':[mainland['target_sha256'],traditional['target_sha256'],custom['target_sha256']]})
    all_targets=targets(''.join(StructureRepository(DATABASE).characters()),supported,{'label':'all actual repository targets','database_sha256':digest(DATABASE),'complete':True})
    assert '一' in mainland['requested'] and '一' in traditional['requested']
    assert custom['requested'].count('孔')==1 and custom['requested'].count('台')==1
    assert all(c in custom['requested'] for c in '發髮发臺台')
    assert empty['empty'] and not empty['supported']
    from generation_parallel import trial
    try:trial('process',4,[],'empty-must-not-start',rounds=1)
    except ValueError:pass
    else:raise AssertionError('empty target task started')
    assert not (OUT/'empty-must-not-start').exists()
    ivs=targets('漢\ufe00',supported,{'label':'literal variation sequence control'})
    assert ivs['unsupported']==['漢\ufe00'] and not ivs['supported']
    assert not any(c in md['requested'] for c in '網址不存在')
    assert all(c in md['requested'] for c in '孔正止羊群兄'),md
    report={'mainland_representative':mainland,'traditional_representative':traditional,'custom':custom,
            'markdown':md,'empty':empty,'merged':merged,'all_supported':all_targets,
            'markdown_source_ranges':mappings,'markdown_diagnostics':diagnostics,'variation_sequence_control':ivs,
            'full_supported_generation':'manifest complete; generation bounded to explicitly recorded representative targets',
            'mapping_policy':'literal independent Unicode targets; one-simplified-to-many-traditional membership/locale data still requires full authoritative vendoring'}
    save(OUT/'target-sets.json',report)
    empty_control=ROOT/'artifacts/integration_0.1.33_20261020/native-input.inkdoc'
    with zipfile.ZipFile(empty_control) as archive:empty_source=archive.read('source.md').decode('utf-8')
    empty_han,_,empty_errors=markdown_targets(empty_source)
    assert not empty_han
    save(OUT/'real-markdown-empty-control.json',{'source':str(empty_control),'targets':[],
         'diagnostics':empty_errors,'expected':'real symbol-only saved document creates no Han generation task'})
    real=ROOT/'artifacts/preview_performance_0.1.12_20261018/input.inkdoc'
    with zipfile.ZipFile(real) as archive:source=archive.read('source.md').decode('utf-8')
    han,ranges,errors=markdown_targets(source)
    real_manifest=targets(han,supported,{'label':'existing real user multi-page document source.md',
        'inkdoc':str(real),'inkdoc_sha256':digest(real),'source_sha256':hashlib.sha256(source.encode('utf-8')).hexdigest(),
        'parser':'current Markdown parser, no source replacement'})
    save(OUT/'real-markdown-targets.json',{'manifest':real_manifest,'ranges':ranges,'diagnostics':errors})
    # Each full representative scope is measured independently. The real
    # document manifest is complete; only its first 8 unique supported targets
    # are generated, explicitly bounded rather than claiming a full run.
    save(OUT/'scope-inputs.json',{'mainland':mainland['supported'],'traditional':traditional['supported'],
        'markdown':real_manifest['supported'][:8],'custom':[c for c in custom['supported'] if c in '孔正發髮发臺台'],
        'identities':{k:v['identity'] for k,v in [('mainland',mainland),('traditional',traditional),('markdown',real_manifest),('custom',custom)]}})
    print('Target models passed; supported',len(supported),'Markdown',md['requested'],flush=True)


if __name__=='__main__':main()
