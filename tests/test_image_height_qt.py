import os
import subprocess
import sys

import pytest


@pytest.mark.parametrize('dpi',['1','1.5','2'])
def test_height_defaults_legacy_noop_explicit_conversion_and_independent_modes(tmp_path,dpi):
    program=r'''
import sys
from pathlib import Path
from dataclasses import replace
from PIL import Image
from PySide6 import QtCore,QtWidgets
from inkstruct.document.images import ImageStyle
from inkstruct.document.styles import FlowStyle
from inkstruct.document.markdown import parse_markdown
from inkstruct.editor.image_settings import ImageSettingsDialog
from inkstruct.global_defaults import GlobalDefaultsStore,LayoutDefaults
from inkstruct.settings_elements import ElementPage
app=QtWidgets.QApplication([])
root=Path(sys.argv[1])
QtCore.QSettings.setDefaultFormat(QtCore.QSettings.IniFormat)
QtCore.QSettings.setPath(QtCore.QSettings.IniFormat,QtCore.QSettings.UserScope,str(root/'settings'))
store=GlobalDefaultsStore()
legacy=ImageStyle(width_mm=43.123456789,max_height_mm=21)
store.save(LayoutDefaults(flow=FlowStyle(image=legacy)))
raw=store.settings.value(store.KEY)
defaults,warning=GlobalDefaultsStore().load()
assert warning is None and defaults.flow.image.height_mm==60
assert defaults.flow.image.max_height_mm is None
assert GlobalDefaultsStore().settings.value(store.KEY)==raw
doc=parse_markdown('![](a.png)')
d=ImageSettingsDialog(doc,FlowStyle(image=legacy));d.show();app.processEvents()
assert d.controls['width_mm'].isHidden() and d.controls['max_height_mm'].isHidden()
assert not d.controls['height_mm'].isHidden()
assert d.configuration().image==legacy
d.convert_height.click()
assert d.configuration().image.height_mm==60 and legacy.height_mm is None
d.reject()
fresh=FlowStyle()
d=ImageSettingsDialog(doc,fresh);d.show();app.processEvents()
assert d.configuration()==fresh and d.controls['height_mm'].value()==60
assert d.controls['width_mm'].isHidden() and d.dimension_mode.isHidden()
path=root/'a.png';Image.new('RGB',(120,60),'white').save(path)
d.picker.setCurrentIndex(1);d.import_file(path)
d.controls['height_mm'].setValue(35)
flow=d.configuration();node=next(n for r in doc.nodes for n in r.walk() if n.kind=='image').node_id
assert flow.image_for(node).dimensions(flow.images[0])==(70,35)
d.dimension_mode.setCurrentIndex(d.dimension_mode.findData('width'))
d.controls['width_mm'].setValue(50)
flow=d.configuration()
assert flow.image_for(node).height_mm is None
assert flow.image_for(node).dimensions(flow.images[0])==(50,25)
d.inherit.setChecked(True)
assert not d.configuration().image_overrides
d.reject();assert not fresh.images and not fresh.image_overrides
page=ElementPage('image',doc,FlowStyle(image=legacy))
page.reset_defaults()
assert page.configuration()['image'].height_mm==60
assert page.editors[None].controls['width_mm'].isHidden()
store=GlobalDefaultsStore()
store.save(replace(defaults,flow=replace(defaults.flow,image=ImageStyle(height_mm=55))))
assert GlobalDefaultsStore().load()[0].flow.image.height_mm==55
'''
    result=subprocess.run([sys.executable,'-X','utf8','-c',program,str(tmp_path)],
                          env={**os.environ,'QT_QPA_PLATFORM':'offscreen','QT_SCALE_FACTOR':dpi},
                          capture_output=True,text=True,encoding='utf-8',timeout=30,check=False)
    assert result.returncode==0,result.stdout+result.stderr
