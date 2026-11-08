"""Real v6.2 font document, source identities, warnings and exact SVG roundtrip."""
import bootstrap as b
import hashlib
from inkstruct.document.package import load_package,save_package
from inkstruct.editor.mixed import build_markdown
from inkstruct.renderers.pages import page_svg
from inkstruct.plotter.adapters import plan_from_snapshot
from inkstruct.plotter.export import export_plan

loaded=load_package(b.ROOT/'artifacts/v62_0.1.32_20261020/native-saved.inkdoc')
def build(p):return build_markdown(p.session,0,p.resolver,'','',p.page,p.style,p.flow,None)
before=build(loaded);loaded.resolver=before['resolver'];assert before['snapshot'].plotter_exportable
target=b.OUT/'real-v62-roundtrip.inkdoc';assert not target.exists()
save_package(target,loaded.session,loaded.resolver,loaded.page,loaded.style,optimize=loaded.optimize,flow=loaded.flow,reviews=loaded.reviews)
reopened=load_package(target);after=build(reopened)
assert loaded.session.identity_record()==reopened.session.identity_record()
assert loaded.resolver.selection_records()==after['resolver'].selection_records()
assert (loaded.flow,loaded.page,loaded.style,loaded.reviews)==(reopened.flow,reopened.page,reopened.style,reopened.reviews)
for result,label in ((before,'before'),(after,'reopened')):
    export_plan(plan_from_snapshot(result['snapshot']),b.OUT/f'real-svg-{label}',optimize=loaded.optimize)
for index in range(len(before['snapshot'].pages)):
    assert page_svg(before['snapshot'],index)==page_svg(after['snapshot'],index)
hashes={}
for path in (b.OUT/'real-svg-before').glob('*.svg'):
    assert path.read_bytes()==(b.OUT/'real-svg-reopened'/path.name).read_bytes()
    hashes[path.name]=hashlib.sha256(path.read_bytes()).hexdigest()
b.save('real-verification.json',{'source_identity_exact':True,'frozen_choices_exact':True,'styles_reviews_exact':True,
    'svg_bytes_exact':True,'svg_sha256':hashes,'source_warnings':before['resolver'].usage_warnings(),
    'input':'artifacts/v62_0.1.32_20261020/native-saved.inkdoc'})
print('real v6.2 document roundtrip and SVG exact; source warnings retained',flush=True)
