import copy
import json
import zipfile

import pytest
from test_document_layout import glyph
from test_font_packages import recorded

from inkstruct.fonts.core import FontPackage, decode
from inkstruct.fonts.importer import build_font
from inkstruct.fonts.revisions import replace_generated


def fixture(tmp_path, monkeypatch):
    run=tmp_path/'run'/'trajectories';run.mkdir(parents=True)
    g=glyph();g['writer_id']='fixture'
    (run/'U+4EBA.json').write_text(json.dumps(g))
    source=tmp_path/'source.inkfont'
    build_font(source,writer='fixture',name='original',run=run.parent,
               symbols=recorded(tmp_path),package_kind='user')
    font=FontPackage(source)
    r=next(r for r in font.records if r['character']=='人')
    with zipfile.ZipFile(source) as z:t=decode(z.read(r['file']))
    t['strokes'][0]['points'][0]['x']+=.01
    protocol={'method':'v6.2 exp','version':'test','semantic_admission':{'version':'test'}}
    import inkstruct.fonts.revisions as module
    monkeypatch.setattr(module,'generated_records',lambda *a:iter([(g,{}, {},protocol)]))
    monkeypatch.setattr(module,'make_generated',lambda *a:(t,copy.deepcopy(font.metrics[r['candidate_id']]),copy.deepcopy(font.provenance[r['candidate_id']])))
    return source,font


def test_revision_preserves_every_unselected_record_resource_and_source(tmp_path,monkeypatch):
    source,old=fixture(tmp_path,monkeypatch);before=source.read_bytes()
    output=tmp_path/'new.inkfont'
    report=replace_generated(source,'run',output,writer='fixture',characters='人',name='new',font_version='0.2')
    new=FontPackage(output)
    assert source.read_bytes()==before and len(new.records)==len(old.records)
    assert len(report['changed'])==1 and new.identity!=old.identity
    old_other=[r for r in old.records if r['character']!='人']
    assert old_other==[r for r in new.records if r['character']!='人']
    with zipfile.ZipFile(source) as a,zipfile.ZipFile(output) as b:
        for r in old_other:
            assert a.read(r['file'])==b.read(r['file'])
            assert old.metrics[r['candidate_id']]==new.metrics[r['candidate_id']]
            assert old.provenance[r['candidate_id']]==new.provenance[r['candidate_id']]
    with pytest.raises(FileExistsError):
        replace_generated(source,'run',output,writer='fixture',characters='人',name='new',font_version='0.2')


def test_revision_incomplete_or_wrong_writer_never_publishes(tmp_path,monkeypatch):
    source,_=fixture(tmp_path,monkeypatch)
    for writer,chars in [('other','人'),('fixture','孔')]:
        output=tmp_path/(writer+'.inkfont')
        with pytest.raises(ValueError):
            replace_generated(source,'run',output,writer=writer,characters=chars,name='new',font_version='0.2')
        assert not output.exists()
