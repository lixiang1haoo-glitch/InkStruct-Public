"""Selective capture, confirmed reuse, font publication and immutable documents."""
import json
import os
import zipfile

import pytest
from test_symbol_capture import CollectionTask, TaskRepository
from test_symbol_provider import specimen

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6 import QtCore, QtWidgets

from inkstruct.assets.resolver import AssetResolver
from inkstruct.document.editing import SourceSession
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.package import load_package, save_package
from inkstruct.document.schema import PageProfile, StyleProfile
from inkstruct.fonts.core import FontPackage, decode
from inkstruct.fonts.importer import build_font
from inkstruct.layout.blocks import layout_markdown
from inkstruct.symbol_reuse import inventory
from inkstruct.symbol_task_dialog import ReuseDialog, SymbolTaskDialog
from inkstruct.symbol_tasks import CUSTOM_PREFIX, item_letter_style


@pytest.fixture
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def captured(root, character='A', style='upright', sid='source-A'):
    root.mkdir(exist_ok=True, parents=True)
    value = specimen(character, sid)
    value['variant'] = {'letter_style': style}
    path = root/(sid+'.json')
    path.write_text(json.dumps(value), encoding='utf-8')
    return path


def declaration(group='latin_italic', target='A', source='A', ids=None):
    return {'group':group, 'target':target, 'source':source, 'source_style':'upright',
            'sample_ids':ids or ['source-A'], 'confirmed':True}


def save_config(root, records):
    source = CUSTOM_PREFIX + json.dumps({'groups':['latin_italic', 'greek'], 'reuse':records})
    task = CollectionTask.create('reuse', source, 'fixture', [])
    TaskRepository(root).save(task)
    return task


def test_individual_selection_no_presets_and_backward_task_styles(app):
    dialog = SymbolTaskDialog('fixture')
    assert not any(b.isChecked() for boxes in dialog.characters.values() for b in boxes.values())
    assert not dialog.findChildren(QtWidgets.QComboBox)
    for c in 'fg':
        dialog.characters['latin_italic'][c].setChecked(True)
    dialog.characters['greek']['θ'].setChecked(True)
    source, entries = dialog.plan()
    assert [(c,n) for c,n,_ in entries] == [('f',5),('g',5),('θ',5)]
    task = CollectionTask.create('partial', source, 'fixture', entries)
    assert item_letter_style(task, task.items[0]) == 'italic'
    assert item_letter_style(task, task.items[-1]) == 'unspecified'
    assert not json.loads(source[len(CUSTOM_PREFIX):])['reuse']
    dialog.reject()


def test_confirm_cancel_preview_and_only_missing_counts(app, tmp_path):
    captured(tmp_path)
    d = SymbolTaskDialog('fixture', collection_root=tmp_path)
    d.characters['latin_upright']['A'].setChecked(True)
    assert d.plan()[1] == [('A',4,0)]
    available = inventory(tmp_path, 'fixture')
    assert not inventory(tmp_path, 'other-writer')
    review = ReuseDialog(available, {})
    assert not review.confirmed() and review.preview.value['character']=='A'
    # Configure through the real nested modal: cancel does not change selections.
    QtCore.QTimer.singleShot(0, lambda: app.activeModalWidget().reject())
    d.reuse_button.click()
    assert not d.reuse
    def confirm():
        modal = app.activeModalWidget()
        assert isinstance(modal, ReuseDialog)
        for i,r in enumerate(modal.records):
            if r['target'] in ('A','Α'):
                modal.list.item(i).setCheckState(QtCore.Qt.Checked)
        modal.accept()
    d.characters['latin_italic']['A'].setChecked(True)
    QtCore.QTimer.singleShot(0, confirm)
    d.reuse_button.click()
    assert set(d.reuse) == {('latin_italic','A'), ('greek','Α')}
    assert not d.characters['latin_italic']['A'].isChecked()
    assert '复用 2' in d.summary.text()
    d.writer.setText('other-writer')
    assert not d.reuse
    review.reject(); d.reject()


@pytest.mark.parametrize('archive', [False,True])
def test_confirmed_reuse_font_unicode_style_provenance_and_freeze(tmp_path, archive):
    root = tmp_path/'collection'
    path = captured(root)
    before = path.read_bytes()
    save_config(root, [declaration(), declaration('greek','Α')])
    symbols = root
    if archive:
        symbols = tmp_path/'collection.zip'
        with zipfile.ZipFile(symbols,'w') as z:
            for p in root.rglob('*.json'):
                z.write(p, str(p.relative_to(root)))
    output = tmp_path/'reuse.inkfont'
    build_font(output, writer='fixture', name='reuse', symbols=symbols)
    font = FontPackage(output)
    font.verify()
    assert set(font.pools)=={'A','Α'}
    a = list(font.glyphs('A'))
    assert {decode(g.original_json)['record']['letter_style'] for g in a}=={'upright','italic'}
    upright = next(g for g in a if decode(g.original_json)['record']['letter_style']=='upright')
    targets = [g for g in a if g != upright] + list(font.glyphs('Α'))
    for g in targets:
        core = decode(g.original_json)
        assert g.strokes==upright.strokes
        assert core['summary']['confirmed_reuse']['source_sample_id']=='source-A'
        assert core['summary']['review_status']=='unreviewed'
    assert decode(targets[0].original_json)['record']['style_evidence']=='confirmed-reuse'
    session = SourceSession('AΑ')
    resolver = AssetResolver(embedded=font.glyphs())
    snap = layout_markdown(parse_markdown(session),resolver)
    assert snap.plotter_exportable
    doc = tmp_path/'reuse.inkdoc'
    save_package(doc,session,resolver,PageProfile(),StyleProfile())
    reopened=load_package(doc)
    assert layout_markdown(parse_markdown(reopened.session),reopened.resolver)==snap
    assert path.read_bytes()==before


def test_missing_retired_source_rejected_and_direct_italic_wins(tmp_path):
    root = tmp_path/'collection'
    captured(root)
    save_config(root, [declaration(ids=['retired-sample'])])
    with pytest.raises(ValueError,match='缺失或已重录'):
        build_font(tmp_path/'missing.inkfont',writer='fixture',name='missing',symbols=root)
    assert not (tmp_path/'missing.inkfont').exists()
    captured(root,style='italic',sid='own-italic-A')
    build_font(tmp_path/'direct.inkfont',writer='fixture',name='direct',symbols=root)
    assert len(FontPackage(tmp_path/'direct.inkfont').records)==2


def test_reuse_configuration_only_persists_and_stale_confirmation_blocks(app,tmp_path):
    path = captured(tmp_path)
    dialog = SymbolTaskDialog('fixture', collection_root=tmp_path)
    dialog.reuse[('latin_italic','A')] = declaration()
    source, entries = dialog.plan()
    assert not entries
    task=CollectionTask.create('reuse only',source,'fixture',entries)
    repo=TaskRepository(tmp_path); repo.save(task)
    assert repo.load(repo.path_for(task.task_id)).source==source
    path.unlink()
    dialog.accept()
    assert dialog.result()!=QtWidgets.QDialog.Accepted
    assert '来源已变化' in dialog.error.text()
    dialog.reject()


def test_unconfirmed_or_foreign_reuse_does_not_supply_a_glyph(tmp_path):
    root = tmp_path/'collection'
    captured(root)
    record=declaration()
    record['confirmed']=False
    save_config(root,[record])
    with pytest.raises(ValueError,match='复用必须确认'):
        build_font(tmp_path/'unconfirmed.inkfont',writer='fixture',name='bad',symbols=root)
    # A config belonging to another author has no effect on this font.
    for p in root.rglob('state.json'):
        value=json.loads(p.read_bytes())
        value['writer_id']='other-writer'
        p.write_text(json.dumps(value),encoding='utf-8')
    build_font(tmp_path/'foreign.inkfont',writer='fixture',name='foreign',symbols=root)
    assert len(FontPackage(tmp_path/'foreign.inkfont').records)==1
