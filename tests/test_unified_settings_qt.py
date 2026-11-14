"""Real Qt settings transactions, scoped drafts, inheritance and DPI navigation."""

import os
import subprocess
import sys

import pytest

PROGRAM = r"""
import sys, time
from pathlib import Path
from dataclasses import replace
from PySide6 import QtCore, QtGui, QtTest, QtWidgets
from inkstruct.editor.mixed import MixedWindow
from inkstruct.settings_dialog import SettingsDialog
from inkstruct.document.package import save_package, load_package
from inkstruct.document.table_style import TableStyle
from inkstruct.document.images import ImageStyle
from inkstruct.renderers.pages import page_svg
app = QtWidgets.QApplication([])
QtCore.QSettings.setDefaultFormat(QtCore.QSettings.Format.IniFormat)
QtCore.QSettings.setPath(QtCore.QSettings.Format.IniFormat, QtCore.QSettings.Scope.UserScope, sys.argv[1])
root = Path(sys.argv[1]); scenario = sys.argv[2]
if scenario=='navigation_largefont':
    font=app.font();font.setPointSize(13);app.setFont(font)
w = MixedWindow(source='12\n\n|1|2|\n|---|---|\n|3|4|\n\n|5|6|\n|---|---|\n|7|8|\n\n![1](a.png)\n\n![2](b.png)')
w.show()
def ready():
    deadline=time.monotonic()+15
    while time.monotonic()<deadline:
        app.processEvents()
        if w.snapshot and not w.timer.isActive() and not w.worker:
            w.recovery_timer.stop(); return
        time.sleep(.01)
    raise AssertionError(w.status.text())
ready()
document=w.parse_current_source()
tables=[n for r in document.nodes for n in r.walk() if n.kind=='table']
images=[n for r in document.nodes for n in r.walk() if n.kind=='image']
if scenario=='no_op':
    w.loaded_style=replace(w.style,em_mm=6.123456789)
    w.page=replace(w.page,margin_mm=20.123456789)
    w.flow=replace(w.flow,paragraph_gap_mm=2.123456789,
                   heading_scales=(1.6123456789,1.4,1.2,1.1,1,1),
                   math=replace(w.flow.math,fraction_scale=.8123456789),
                   code=replace(w.flow.code,em_mm=4.123456789),
                   footnote=replace(w.flow.footnote,text_scale=.7123456789),
                   table_overrides=((tables[1].node_id,TableStyle(width_mm=123.123456789)),),
                   image_overrides=((images[1].node_id,ImageStyle(width_mm=43.123456789)),))
    before=(w.style,w.page,w.flow,w.source_session.atom_ids,w.resolver.selection_records())
    w.dirty=False
    d=SettingsDialog(w)
    for key in d.items:d.select(key)
    for kind in ('table','image'):
        page=d.pages[kind]
        assert page.scope.count()==1 and not page.scope.isVisible()
    assert d.apply(),d.error.text()
    assert before==(w.style,w.page,w.flow,w.source_session.atom_ids,w.resolver.selection_records())
    assert not w.dirty
    d.reject()
elif scenario=='han_spacing':
    from inkstruct.global_defaults import GlobalDefaultsStore
    from inkstruct.document.han_variation import HanVariation
    from inkstruct.settings_dialog import BodyPage
    w.flow=replace(w.flow, han_variation=HanVariation(enabled=True, spacing_strength=.6))
    original=w.flow
    store=GlobalDefaultsStore()
    defaults,_=store.load()
    store.save(replace(defaults,flow=replace(defaults.flow,han_variation=original.han_variation)))
    d=SettingsDialog(w,category='body');p=d.pages['body']
    assert isinstance(p,BodyPage) and p.han_spacing.currentData()=='full'
    d.filter_categories('汉字间距')
    assert p.han_spacing.property('settingsSearchHit')
    p.han_spacing.setCurrentIndex(p.han_spacing.findData('handwriting'))
    assert d.apply(),d.error.text()
    assert w.flow==original and GlobalDefaultsStore().load()[0].flow.han_spacing=='handwriting'
    assert d.apply(to_document=True),d.error.text();d.reject();ready()
    assert w.flow.han_spacing=='handwriting' and w.flow.han_variation==original.han_variation
    path=root/'spacing.inkdoc'
    save_package(path,w.source_session,w.resolver,w.page,w.style,flow=w.flow)
    w.load_project_path(path);ready()
    d=SettingsDialog(w,category='body');p=d.pages['body']
    assert p.han_spacing.currentData()=='handwriting'
    p.han_spacing.setCurrentIndex(p.han_spacing.findData('full'))
    assert d.apply(to_document=True),d.error.text();d.reject();ready()
    assert w.flow.han_spacing=='full' and w.flow.han_variation==original.han_variation
elif scenario=='digit_spacing':
    from inkstruct.global_defaults import GlobalDefaultsStore
    assert w.flow.digits_follow_latin and w.flow.latin_spacing=='handwriting'
    old = root/'old.inkdoc'
    flow = replace(w.flow, digits_follow_latin=False, schema_version='inkstruct_flow_style_v5')
    save_package(old,w.source_session,w.resolver,w.page,w.style,flow=flow)
    w.load_project_path(old);ready()
    assert w.flow.latin_spacing=='handwriting' and not w.flow.digits_follow_latin
    d=SettingsDialog(w,category='table')
    assert d.apply(to_document=True),d.error.text()
    assert not w.flow.digits_follow_latin
    d.select('body'); p=d.pages['body']
    assert p.latin_spacing.accessibleName()=='字母与数字间距'
    assert d.apply(),d.error.text()
    assert not w.flow.digits_follow_latin and GlobalDefaultsStore().load()[0].flow.digits_follow_latin
    assert d.apply(to_document=True),d.error.text(); d.reject(); ready()
    assert w.flow.digits_follow_latin
    new=root/'new.inkdoc'
    save_package(new,w.source_session,w.resolver,w.page,w.style,flow=w.flow)
    w.load_project_path(new);ready()
    assert w.flow.digits_follow_latin and w.flow.latin_spacing=='handwriting'
elif scenario=='scopes':
    from inkstruct.global_defaults import GlobalDefaultsStore
    d=SettingsDialog(w,category='table');p=d.pages['table']
    d.resize(d.width(), 500); d.show(); app.processEvents()
    outer = d.stack.currentWidget()
    assert isinstance(outer, QtWidgets.QScrollArea) and outer.verticalScrollBar().maximum() > 0
    assert not p.findChildren(QtWidgets.QScrollArea)
    p.editors[None].controls['width_mm'].setValue(140)
    d.select('image');d.pages['image'].editors[None].controls['height_mm'].setValue(70)
    assert d.apply(),d.error.text()
    assert w.flow.table.width_mm==160 and w.flow.image.height_mm==60
    assert GlobalDefaultsStore().load()[0].flow.table.width_mm==140
    assert d.apply(to_document=True),d.error.text();d.reject();ready()
    inspector=w.element_inspector
    assert w.element_properties_dock.isVisible()
    def select(node):
        inspector.selector.setCurrentIndex(inspector.selector.findData(node.node_id))
        return inspector.pages[node.kind]
    p=select(tables[0]);assert p.inherit.isChecked()
    assert not p.editors[p.current_key].controls['width_mm'].isEnabled()
    p.custom.setChecked(True);p.editors[p.current_key].controls['width_mm'].setValue(120)
    p=select(tables[1]);p.custom.setChecked(True);p.editors[p.current_key].controls['width_mm'].setValue(110)
    p=select(tables[0]);assert p.editors[p.current_key].controls['width_mm'].value()==120
    p=select(images[0]);p.custom.setChecked(True)
    p.editors[p.current_key].dimension_mode.setCurrentIndex(p.editors[p.current_key].dimension_mode.findData('width'))
    p.editors[p.current_key].controls['width_mm'].setValue(45)
    p=select(images[1]);assert p.inherit.isChecked()
    p=select(images[0]);assert p.editors[p.current_key].controls['width_mm'].value()==45
    assert inspector.has_pending()
    calls=[];original=w.schedule_layout;w.schedule_layout=lambda:calls.append(1)
    assert inspector.apply(),inspector.error.text();assert len(calls)==1
    w.schedule_layout=original;inspector.refresh()
    assert w.flow.table_for(tables[0].node_id).width_mm==120
    assert w.flow.table_for(tables[1].node_id).width_mm==110
    assert w.flow.image_for(images[0].node_id).width_mm==45
    assert w.flow.image_for(images[1].node_id).height_mm==70
    p=select(images[0]);p.editors[p.current_key].controls['width_mm'].setValue(44)
    inspector.discard();assert w.flow.image_for(images[0].node_id).width_mm==45
    save_package(root/'scopes.inkdoc',w.source_session,w.resolver,w.page,w.style,flow=w.flow)
    assert load_package(root/'scopes.inkdoc').flow==w.flow
    p=select(tables[0]);p.inherit.setChecked(True)
    assert inspector.apply(),inspector.error.text();ready()
    assert tables[0].node_id not in dict(w.flow.table_overrides)
    assert w.flow.table_for(tables[1].node_id).width_mm==110
    global_flow=GlobalDefaultsStore().load()[0].flow
    assert not global_flow.table_overrides and not global_flow.image_overrides and not global_flow.images
    new=MixedWindow();assert new.flow.table.width_mm==140 and new.flow.image.height_mm==70
    new.load_project_path(root/'scopes.inkdoc')
    assert new.flow.table_for(tables[0].node_id).width_mm==120
    new.timer.stop()
    if new.cancelled:new.cancelled.set()
    new.pool.waitForDone();new.dirty=False;new.close()
elif scenario=='footer':
    from inkstruct.global_defaults import GlobalDefaultsStore
    w.flow=replace(w.flow,
        table_overrides=((tables[0].node_id,TableStyle(width_mm=123)),),
        image_overrides=((images[0].node_id,ImageStyle(width_mm=45)),))
    def show(editor):
        dialog=SettingsDialog(editor,category='body')
        dialog.show();app.processEvents()
        assert not hasattr(dialog,'apply_current')
        assert not hasattr(dialog.pages['body'],'preview')
        actions={b.text():b for b in dialog.buttons.findChildren(QtWidgets.QPushButton)}
        assert set(actions)=={'取消','存为默认','应用并保存'}
        return dialog,actions,dialog.pages['body'].style.controls['em_mm']
    def click(action):
        QtTest.QTest.mouseClick(action,QtCore.Qt.LeftButton)
        app.processEvents()
    d,a,c=show(w)
    c.setValue(7);click(a['存为默认'])
    assert not d.isVisible() and GlobalDefaultsStore().load()[0].style.em_mm==7
    assert w.style.em_mm==6
    d,a,c=show(w)
    hint='更新当前文档，并保存为新文档默认'
    assert a['应用并保存'].toolTip()==a['应用并保存'].accessibleDescription()==hint
    c.setValue(8);click(a['应用并保存']);ready()
    assert d.isVisible() and w.style.em_mm==GlobalDefaultsStore().load()[0].style.em_mm==8
    assert w.flow.table_for(tables[0].node_id).width_mm==123
    assert w.flow.image_for(images[0].node_id).width_mm==45
    c.setValue(9);click(a['取消'])
    assert not d.isVisible() and w.style.em_mm==GlobalDefaultsStore().load()[0].style.em_mm==8
    blank=MixedWindow()
    d,a,c=show(blank)
    assert a['应用并保存'].isHidden()
    click(a['取消'])
    blank.new_document()
    d,a,c=show(blank)
    assert a['应用并保存'].isVisible()
    click(a['取消']);blank.dirty=False;blank.close()
elif scenario=='validation':
    from inkstruct.global_defaults import GlobalDefaultsStore
    before=(w.flow,w.style,w.page)
    d=SettingsDialog(w,category='body');d.pages['body'].style.controls['em_mm'].setValue(7)
    d.select('table');p=d.pages['table'];panel=p.editors[None]
    panel.mode.setCurrentIndex(panel.mode.findData('fixed'));panel.sizes.setText('1,2')
    d.select('image');assert not d.apply()
    assert d.current=='table' and '固定列宽' in d.error.text()
    assert before==(w.flow,w.style,w.page)
    assert GlobalDefaultsStore().load()[0].style.em_mm==6
    panel.sizes.setText('80,80');assert d.apply(),d.error.text()
    assert GlobalDefaultsStore().load()[0].style.em_mm==7 and w.style.em_mm==6
    d.select('body');d.pages['body'].style.controls['em_mm'].setValue(8);d.reject()
    assert GlobalDefaultsStore().load()[0].style.em_mm==7
elif scenario in {'navigation','navigation_largefont'}:
    d=SettingsDialog(w,category='body'); d.resize(980,650);d.show(); app.processEvents()
    body = d.pages['body']
    short_fields = (body.han_seed, body.style.controls['em_mm'], body.mode)
    widths = [field.width() for field in short_fields]
    for field in short_fields:
        assert field.sizeHint().width() <= field.width() < 300
    search_width = d.search.width()
    d.resize(1260, 650);app.processEvents()
    assert [field.width() for field in short_fields] == widths
    assert d.search.width() > search_width
    core_fields = (body.mode, body.style.controls['em_mm'], body.flow.controls['paragraph_gap_mm'])
    assert len({field.mapTo(body, QtCore.QPoint()).x() for field in core_fields}) == 1
    assert body.style.controls['em_mm'].mapTo(body, QtCore.QPoint()).y() < body.han_seed.mapTo(body, QtCore.QPoint()).y()
    d.resize(980, 650);app.processEvents()
    for key in d.items:
        d.select(key); app.processEvents()
        assert d.buttons.isVisible()==(key!='templates')
        if key!='templates':assert d.rect().contains(d.buttons.geometry())
        assert d.width()>=d.minimumWidth() and d.height()==650
    d.search.setText('上下标'); assert d.current=='math'
    math=d.pages['math']; assert math.categories.isVisible()
    for i in range(math.categories.count()):
        math.categories.setCurrentRow(i);app.processEvents()
        assert math.categories.currentRow()==i
        assert math.panels.currentIndex()==i
        assert math.parameter_scroll.horizontalScrollBar().maximum()==0
    before=(w.flow,w.style,w.page,w.source_session.atom_ids)
    d.reject(); assert before==(w.flow,w.style,w.page,w.source_session.atom_ids)
else:raise AssertionError(scenario)
w.timer.stop()
if w.cancelled:w.cancelled.set()
w.pool.waitForDone();w.dirty=False;w.close()
QtCore.QCoreApplication.sendPostedEvents(None,QtCore.QEvent.DeferredDelete)
"""


@pytest.mark.parametrize("dpi", ["1", "1.5", "2"])
@pytest.mark.parametrize("scenario", ["no_op", "han_spacing", "digit_spacing", "scopes", "footer", "validation", "navigation", "navigation_largefont"])
def test_settings_transactions_and_navigation(tmp_path, dpi, scenario):
    result = subprocess.run(
        [sys.executable, "-c", PROGRAM, str(tmp_path), scenario],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_SCALE_FACTOR": dpi},
        capture_output=True,
        text=True,
        encoding='utf-8',
        timeout=45,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("dpi", ["1", "1.5", "2"])
def test_integrated_gear_capture_and_write_failure(tmp_path, dpi):
    program = r"""
import sys,time
from pathlib import Path
from dataclasses import replace
from PySide6 import QtCore,QtGui,QtWidgets,QtTest
from inkstruct.application import InkStructWindow
from inkstruct.settings_dialog import SettingsDialog
app=QtWidgets.QApplication([])
QtCore.QSettings.setDefaultFormat(QtCore.QSettings.Format.IniFormat)
QtCore.QSettings.setPath(QtCore.QSettings.Format.IniFormat,QtCore.QSettings.Scope.UserScope,sys.argv[1])
w=InkStructWindow(workspace=Path(sys.argv[1])/'workspace');w.show();app.processEvents()
collector=w.collector
from handwriting_collector.config import UiSettingsStore
collector.ui_settings_store=UiSettingsStore(Path(sys.argv[1])/'capture-settings.json')
collector.ui_settings=replace(collector.ui_settings,stroke_width_scale=2.123456789)
assert not any(a.text()=='设置' for a in collector.menuBar().actions())
assert not w.editor.settings_button.isVisible() and not w.editor.settings_shortcut.isEnabled()
positions=[]
navigation_checks=[]
def inspect():
    d=app.activeModalWidget();assert isinstance(d,SettingsDialog)
    navigation_checks.append((
        ('capture' in d.pages)==(w.tabs.currentIndex()==0),
        set(d.items)=={'appearance','preview','capture','body','math','table','image','code','footnote'},
    ))
    d.reject()
for i in range(w.tabs.count()):
    w.tabs.setCurrentIndex(i);app.processEvents()
    assert w.settings_button.isVisible()
    positions.append(w.settings_button.mapTo(w,QtCore.QPoint()))
    QtCore.QTimer.singleShot(10,inspect)
    if i==0:QtTest.QTest.keySequence(w,QtGui.QKeySequence('Ctrl+,'))
    else:QtTest.QTest.mouseClick(w.settings_button,QtCore.Qt.LeftButton)
assert all(p==positions[0] for p in positions)
assert navigation_checks==[(True,True)]*w.tabs.count()
canvas=collector.symbol_widget.canvas
from handwriting_collector.models import TrajectoryPoint
canvas.trajectory.start_stroke(TrajectoryPoint(100,100,.4,0))
canvas.trajectory.append_point(TrajectoryPoint(150,140,.7,40))
points=repr(canvas.trajectory.strokes)
d=SettingsDialog(w.editor,collector,w,category='capture');p=d.pages['capture']
d.resize(980, 650);d.show();app.processEvents()
assert p.grid.width() <= 260
assert collector.single_widget.stroke_width_slider.width() <= 260
assert p.configuration()==collector.ui_settings
before=(w.editor.style,w.editor.flow,collector.ui_settings)
assert not hasattr(p, 'stroke')
collector.apply_ui_settings(collector.ui_settings)
collector.single_widget.stroke_width_slider.setValue(250)
assert collector.single_widget.canvas.stroke_width_scale == 2.5
assert canvas.stroke_width_scale == 2.123456789
collector.symbol_widget.stroke_width_slider.setValue(300)
assert collector.single_widget.canvas.stroke_width_scale == 2.5
assert canvas.stroke_width_scale == 3
assert collector.ui_settings_store.load()[0] == collector.ui_settings
before=(w.editor.style,w.editor.flow,collector.ui_settings)
p.grid.setValue(80)
d.select('body');d.pages['body'].style.controls['em_mm'].setValue(7)
save=collector.ui_settings_store.save
def fail(settings):raise OSError('write denied')
collector.ui_settings_store.save=fail
assert not d.apply() and 'write denied' in d.error.text()
assert before==(w.editor.style,w.editor.flow,collector.ui_settings)
collector.ui_settings_store.save=save
default_save=d.defaults_store.save
d.defaults_store.save=fail
assert not d.apply() and 'write denied' in d.error.text()
assert before==(w.editor.style,w.editor.flow,collector.ui_settings)
assert collector.ui_settings_store.load()[0]==collector.ui_settings
d.defaults_store.save=default_save
assert d.apply(),d.error.text()
assert collector.ui_settings.stroke_width_scale==2.5
assert collector.ui_settings_store.load()[0]==collector.ui_settings
assert collector.single_widget.canvas.stroke_width_scale==2.5 and canvas.stroke_width_scale==3
assert canvas.grid_scale==.8
assert repr(canvas.trajectory.strokes)==points
p.grid.setValue(85);d.reject()
assert collector.ui_settings.stroke_width_scale==2.5
canvas.clear()
w.editor.timer.stop()
if w.editor.cancelled:w.editor.cancelled.set()
w.editor.pool.waitForDone();w.editor.dirty=False;w.close()
QtCore.QCoreApplication.sendPostedEvents(None,QtCore.QEvent.DeferredDelete)
"""
    result = subprocess.run(
        [sys.executable, "-c", program, str(tmp_path)],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_SCALE_FACTOR": dpi},
        capture_output=True,
        text=True,
        encoding='utf-8',
        timeout=45,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
