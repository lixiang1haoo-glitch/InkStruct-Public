import json
import zipfile
from dataclasses import replace

import pytest
from PIL import Image

from inkstruct.assets.resolver import AssetResolver
from inkstruct.document.editing import SourceSession
from inkstruct.document.images import ImageStyle, RasterResource
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.package import load_package, save_package
from inkstruct.document.schema import PageProfile, StyleProfile
from inkstruct.document.styles import FlowStyle
from inkstruct.layout.blocks import layout_markdown
from inkstruct.renderers.pages import page_svg


@pytest.mark.parametrize('size,expected', [((120, 60), (120, 60)), ((60, 120), (30, 60))])
def test_default_height_uses_original_ratio_and_survives_frozen_reopen(tmp_path, size, expected):
    path=tmp_path/'image.png'
    Image.new('RGB',size,'white').save(path)
    resource=RasterResource.from_file(path,'image.png')
    flow=FlowStyle(images=(resource,))
    assert flow.image.height_mm==60 and flow.image.schema_version=='inkstruct_image_style_v2'
    assert flow.image.dimensions(resource)==expected
    session=SourceSession('![](image.png)')
    resolver=AssetResolver()
    before=layout_markdown(parse_markdown(session),resolver,flow=flow)
    assert before.exportable and not before.plotter_exportable
    image=before.pages[0].images[0]
    assert (image.bounds[2]-image.bounds[0],image.bounds[3]-image.bounds[1])==expected
    saved=tmp_path/'height.inkdoc'
    save_package(saved,session,resolver,PageProfile(),StyleProfile(),flow=flow)
    path.unlink()
    loaded=load_package(saved)
    after=layout_markdown(parse_markdown(loaded.session),loaded.resolver,flow=loaded.flow)
    assert page_svg(before,0)==page_svg(after,0)
    assert loaded.flow==flow


def test_old_image_style_keeps_geometry_and_serialized_v1_has_no_new_field(tmp_path):
    session=SourceSession('![](missing.png)')
    flow=FlowStyle(image=ImageStyle(width_mm=45,max_height_mm=12))
    assert flow.image.height_mm is None and flow.image.dimensions(None)==(24,12)
    saved=tmp_path/'legacy.inkdoc'
    save_package(saved,session,AssetResolver(),PageProfile(),StyleProfile(),flow=flow)
    with zipfile.ZipFile(saved) as z:
        style=json.loads(z.read('styles.json'))['flow']['image']
    assert style['schema_version']=='inkstruct_image_style_v1' and 'height_mm' not in style
    assert load_package(saved).flow==flow


def test_too_wide_height_based_image_is_diagnosed_without_automatic_shrinking(tmp_path):
    path=tmp_path/'wide.png';Image.new('RGB',(400,100),'white').save(path)
    resource=RasterResource.from_file(path,'wide.png')
    flow=FlowStyle(images=(resource,))
    snapshot=layout_markdown(parse_markdown('![](wide.png)'),AssetResolver(),flow=flow)
    assert not snapshot.exportable
    assert any(d.code=='image-width-overflow' for d in snapshot.diagnostics)
    assert flow.image.dimensions(resource)==(240,60)
    assert replace(flow.image,height_mm=30).dimensions(resource)==(120,30)


@pytest.mark.parametrize('height', [0,-1,float('nan'),float('inf'),2001])
def test_invalid_height_rejected(height):
    with pytest.raises(ValueError):ImageStyle(height_mm=height)
