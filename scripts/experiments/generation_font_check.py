"""New small experimental font; original recorded candidate identities retained."""
import copy
from dataclasses import asdict
import json
from pathlib import Path
import sys
import time
import uuid
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parent))
from generation_parallel import ROOT,OUT,SMALL,save,digest,canonical
from inkstruct.assets.glyph_provider import is_han
from inkstruct.assets.resolver import AssetResolver
from inkstruct.fonts.core import FontPackage,encoded,write_archive
from inkstruct.fonts.parallel_verify import verify_font
from inkstruct.fonts.importer import build_font
from inkstruct.document.editing import SourceSession
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.package import save_package,load_package
from inkstruct.document.schema import PageProfile,StyleProfile
from inkstruct.layout.blocks import layout_markdown
from inkstruct.plotter.adapters import plan_from_snapshot
from inkstruct.plotter.export import export_plan

SOURCE=ROOT/'artifacts/integration_0.1.34_20261020/user_001-v62-validation-recorded-math-symbols-20261020.inkfont'


def main():
    started=time.perf_counter();folder=OUT/'font-validation';folder.mkdir(exist_ok=False)
    before=digest(SOURCE)
    source=FontPackage(SOURCE,verify_all=False)
    statistics=verify_font(source,progress=lambda message:print(message,flush=True))
    generated=folder/'generated-only.inkfont'
    build_font(generated,writer='user_001',name='Generation parallel experiment ONLY',
               run=OUT/'small-process2-1/round-1',package_kind='developer')
    new=FontPackage(generated);verify_font(new)
    retained=[r for r in source.records if not is_han(r['character'])]
    records=copy.deepcopy(retained+new.records)
    metrics={};provenance={};members={}
    for font,selected in ((source,retained),(new,new.records)):
        with zipfile.ZipFile(font.path) as archive:
            for record in selected:
                cid=record['candidate_id']
                members[record['file']]=font._checked(archive,record['file'])
                metrics[cid]=copy.deepcopy(font.metrics[cid]);provenance[cid]=copy.deepcopy(font.provenance[cid])
    index=copy.deepcopy(source.index);index['candidates']=records
    members.update({'index.json':encoded(index),'metrics.json':encoded(metrics),'provenance.json':encoded(provenance)})
    manifest={k:v for k,v in source.manifest.items() if k not in ('members','core_members','core_hash','content_hash')}
    manifest.update(name='user_001 · v6.2 字集并行实验小包（非发布）',package_kind='user',font_version='experiment-20261022',
        release_id=str(uuid.uuid4()),package_id=str(uuid.uuid4()),derived_from_package={'package_id':source.manifest['package_id'],
        'content_hash':source.manifest['content_hash']})
    output=folder/'user_001-v62-parallel-experiment.inkfont'
    write_archive(output,members,manifest)
    combined=FontPackage(output);combined_statistics=verify_font(combined)
    assert all(r in combined.records for r in retained)
    for record in retained:
        cid=record['candidate_id']
        assert combined.metrics[cid]==source.metrics[cid] and combined.provenance[cid]==source.provenance[cid]
    for char in SMALL:assert char in combined.pools
    for group in ('ABCabc','0123456789','，。：；！？','+−='):
        assert all(c in combined.pools for c in group),(group,combined.pools.keys())
    session=SourceSession(('孔正址兄礼烧止怔歪羊群，ABC abc 0123456789。\n\n$1+2=3$\n\n')*8)
    resolver=AssetResolver(embedded=combined.glyphs(set(session.source)))
    page=PageProfile(100,120,10);style=StyleProfile()
    snapshot=layout_markdown(parse_markdown(session),resolver,page=page,style=style)
    save(folder/'layout-diagnostics.json',[asdict(d) for d in snapshot.diagnostics])
    assert snapshot.exportable,[asdict(d) for d in snapshot.diagnostics]
    from inkstruct.renderers.pages import page_svg
    from PySide6 import QtCore,QtGui,QtSvg,QtWidgets
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    for i in range(len(snapshot.pages)):
        text=page_svg(snapshot,i)
        (folder/f'preview-{i+1}.svg').write_text(text,'utf-8')
        image=QtGui.QImage(800,960,QtGui.QImage.Format.Format_ARGB32_Premultiplied);image.fill(QtCore.Qt.GlobalColor.white)
        painter=QtGui.QPainter(image);renderer=QtSvg.QSvgRenderer(text.encode());renderer.render(painter);painter.end()
        assert image.save(str(folder/f'preview-{i+1}.png'))
    plan=plan_from_snapshot(snapshot)
    export_plan(plan,folder/'svg-before',optimize=False)
    choices=resolver.selection_records()
    document=folder/'experiment.inkdoc'
    save_package(document,session,resolver,page,style,optimize=False)
    loaded=load_package(document)
    restored=layout_markdown(parse_markdown(loaded.session),loaded.resolver,page=loaded.page,style=loaded.style)
    assert asdict(snapshot)==asdict(restored)
    assert choices==loaded.resolver.selection_records()
    export_plan(plan_from_snapshot(restored),folder/'svg-reopened',optimize=False)
    a={p.name:digest(p) for p in (folder/'svg-before').glob('*.svg')}
    b={p.name:digest(p) for p in (folder/'svg-reopened').glob('*.svg')}
    assert a==b and a
    assert before==digest(SOURCE)
    save(folder/'verification.json',{'passed':True,'source':str(SOURCE),'source_sha256':before,'source_full_verification':statistics,
        'font':str(output),'sha256':digest(output),'retained_recorded_or_constructed_candidates':len(retained),
        'combined_full_verification':combined_statistics,
        'retained_candidate_identity_metrics_provenance_exact':True,'new_generated_characters':list(SMALL),
        'coverage':sorted(combined.pools),'pages':len(snapshot.pages),'selections':len(choices),
        'warnings':[asdict(d) for d in snapshot.diagnostics],'geometry_selection_save_reopen_exact':True,'svg_exact':a,
        'wall_s':time.perf_counter()-started,'not_independent_quality_evaluation':'profile contains historical validation examples; performance and deterministic correctness only'})
    print('Font/roundtrip/strict SVG passed',flush=True)


if __name__=='__main__':main()
