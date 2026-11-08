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
from inkstruct.symbol_tasks import CUSTOM_PREFIX, LEGACY_CUSTOM_PREFIX, item_letter_style


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


def test_legacy_task_indices_and_reuse_are_preserved_by_new_catalog(tmp_path):
    from inkstruct.fonts.publication import symbol_group
    from inkstruct.symbol_reuse import declarations

    source = LEGACY_CUSTOM_PREFIX + json.dumps({
        'groups': ['operators', 'chinese_punctuation', 'latin_italic', 'punctuation'],
        'reuse': [declaration()],
    })
    task = CollectionTask.create('old', source, 'fixture', [('-', 1, 0), ('【', 1, 1), ('B', 1, 2), ('%', 1, 3)])
    repo = TaskRepository(tmp_path)
    repo.save(task)
    restored = repo.load(repo.path_for(task.task_id))
    assert restored.to_dict() == task.to_dict()
    assert [item_letter_style(restored, item) for item in restored.items] == [
        'unspecified', 'unspecified', 'italic', 'unspecified']
    assert list(declarations(tmp_path, 'fixture')) == [declaration()]
    assert [symbol_group(c) for c in '-−【％℃ℏ§'] == [
        'punctuation', 'operators', 'brackets', 'units', 'units', 'operators', 'other']


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


def test_publication_scopes_capture_root_and_reuses_only_selected_styles(tmp_path):
    from inkstruct.fonts.publication import publication_inventory

    root = tmp_path / 'collection'
    own = root / 'samples' / 'fixture'
    captured(own)
    other = captured(root / 'samples' / 'other', sid='foreign')
    value = json.loads(other.read_text('utf-8'))
    value['writer_id'] = 'other'
    other.write_text(json.dumps(value), 'utf-8')
    save_config(root, [declaration(), declaration('greek', 'Α', ids=['retired'])])

    _, recorded, rejected, reused = publication_inventory('fixture', '', str(root))
    assert recorded['latin_upright'] == {'A'}
    assert reused['latin_italic'] == {'A'}
    assert rejected['greek'] == {'Α'}
    output = tmp_path / 'only-italic.inkfont'
    build_font(output, writer='fixture', name='filtered', symbols=root, symbol_groups={'latin_italic'})
    records = FontPackage(output, verify_all=True).records
    assert [(r['character'], r['letter_style'], r['style_evidence']) for r in records] == [
        ('A', 'italic', 'confirmed-reuse'),
    ]


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


def test_selected_coverage_is_the_published_coverage_and_rechecks_inputs(tmp_path, monkeypatch):
    import os

    from inkstruct.fonts.library import publish_font
    from inkstruct.fonts.publication import publication_stamp, review_selection, symbol_group

    source = tmp_path / "capture"
    samples = source / "samples" / "fixture"
    recorded = captured(samples)
    captured(samples, "。", "unspecified", "stop")
    captured(samples, "C", "upright", "upright-C")
    captured(samples, ",", "unspecified", "comma")
    save_config(source, [declaration(), declaration("greek", "Α", ids=["missing"])])
    args = ("fixture", "", str(source), "same-name")
    groups = {"latin_upright", "latin_italic", "punctuation", symbol_group("℃"), "greek"}
    all_coverage = review_selection(*args, groups)
    assert any(key[1:] == ("constructed", "℃") for key in all_coverage["coverage"])
    assert all_coverage["coverage"]["punctuation", "shared", "，"] == 1
    assert any(item["target"] == "Α" and item["invalid"] for item in all_coverage["issues"])
    groups.remove("latin_upright")
    review = review_selection(*args, groups)
    expected = review["coverage"]
    assert expected["latin_italic", "reuse", "A"] == 1
    assert not any(key[2] == "℃" for key in expected)
    assert any(item["target"] == "℃" and "C" in item["reason"] for item in review["issues"])
    assert ("规则合成", "℃", "句号 。与英文正体 C", "已启用", "缺少可用的英文正体 C") in review["rules"]
    assert any(row[:2] == ("确认复用", "A（英文斜体）") and row[3:] == ("已确认", "本次生效 · 1 份候选")
               for row in review["rules"])
    assert any(row[:2] == ("同形共用", "， ↔ ,") and row[4].startswith("本次生效") for row in review["rules"])

    root = tmp_path / "fonts"
    root.mkdir()
    old = root / "old.inkfont"
    build_font(old, writer=args[0], name=args[3], symbols=source, symbol_groups={"latin_upright"})
    old_bytes = old.read_bytes()
    stamp = publication_stamp(*args[:3])

    def publish():
        return publish_font(root, writer=args[0], run=args[1], symbols=args[2], name=args[3],
                            package_kind="user", groups=groups, stamp=stamp, expected=expected, progress=lambda _: None)

    def fail_verify(font, **kwargs):
        assert list(root.glob("*.inkfont")) == [old]
        assert font.path.parent.parent == root
        raise ValueError("mock final verification")

    with monkeypatch.context() as patch:
        patch.setattr(FontPackage, "verify", fail_verify)
        with pytest.raises(ValueError, match="完整验证失败"):
            publish()
    assert list(root.iterdir()) == [old]
    real_link = os.link

    def fail_link(source, dest):
        if dest.parent == root:
            assert list(root.glob("*.inkfont")) == [old]
            raise OSError("mock final link")
        return real_link(source, dest)

    with monkeypatch.context() as patch:
        patch.setattr(os, "link", fail_link)
        with pytest.raises(ValueError, match="入库失败"):
            publish()
    assert list(root.iterdir()) == [old]
    result = publish()
    assert result["coverage"] == expected and not result["difference"]
    assert list(result["timings"]) == ["准备字形", "封装", "完整验证", "入库"]
    assert old.read_bytes() == old_bytes
    assert len(list(root.glob("*.inkfont"))) == 2
    state = next(source.rglob("state.json"))
    state.write_text(state.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="重新核对"):
        publish()
    assert recorded.is_file() and len(list(root.glob("*.inkfont"))) == 2


def test_auto_review_discards_stale_failures_and_keeps_group_choices(app, tmp_path, monkeypatch):
    from threading import Event
    from time import monotonic, sleep

    from inkstruct.fonts import ui

    first = tmp_path / "first"
    second = tmp_path / "second"
    captured(first, "A")
    captured(second, "B", sid="second-B")
    captured(second, ",", "unspecified", "comma")
    library = ui.FontLibrary(tmp_path / "fonts")
    entered, release = Event(), Event()
    real_review = ui.review_selection

    def review(writer, run, symbols, name, groups):
        if name == "迟到的旧请求":
            entered.set()
            if not release.wait(5):
                raise ValueError("test did not release the worker")
            raise ValueError("过期错误")
        return real_review(writer, run, symbols, name, groups)

    def wait(predicate):
        end = monotonic() + 5
        while monotonic() < end:
            app.processEvents()
            if predicate():
                return
            sleep(.01)
        raise AssertionError(library.coverage_summary.text())

    monkeypatch.setattr(ui, "review_selection", review)
    library.writer.setText("fixture")
    library.symbols.setText(str(first))
    library.name.setText("迟到的旧请求")
    library.open_publication()
    try:
        wait(entered.is_set)
        assert not library.build_button.isEnabled()
        library.symbols.setText(str(second))
        library.name.setText("当前字体")
    finally:
        release.set()
    wait(library.build_button.isEnabled)
    assert {key[2] for key in library.review_result["coverage"]} == {"B", ",", "，"}
    assert "过期错误" not in library.coverage_summary.text()
    row = next(library.contents.topLevelItem(i) for i in range(library.contents.topLevelItemCount())
               if library.contents.topLevelItem(i).data(0, QtCore.Qt.UserRole) == "punctuation")
    row.setCheckState(0, QtCore.Qt.Unchecked)
    assert not library.build_button.isEnabled()
    wait(library.build_button.isEnabled)
    assert {key[2] for key in library.review_result["coverage"]} == {"B"}
    library.name.setText("当前字体改名")
    wait(library.build_button.isEnabled)
    assert {key[2] for key in library.review_result["coverage"]} == {"B"}
    captured(second, "C", sid="late-C")
    library.watch_publication()
    wait(lambda: library.build_button.isEnabled() and any(key[2] == "C" for key in library.review_result["coverage"]))
    assert "punctuation" not in library.review_groups
    library.publication.reject()
    QtCore.QThreadPool.globalInstance().waitForDone()
