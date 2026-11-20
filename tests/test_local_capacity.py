from pathlib import Path
from zipfile import ZipFile

import pytest

from inkstruct.fonts import core, capacity, exchange_codec as codec
from inkstruct.fonts.importer import build_font
from inkstruct.fonts.library import LocalFontConsent, import_font, find_font_release
from inkstruct.fonts.identity import release_identity
from inkstruct.fonts.subset_ui import subset_choices
from test_font_packages import recorded


def test_local_publish_import_consent_and_subset(tmp_path, monkeypatch):
    old, local = (tmp_path / name for name in ("ordinary.inkfont", "local.inkfont"))
    options = dict(writer="fixture", name="local", symbols=recorded(tmp_path))
    monkeypatch.setattr(core, "MAX_TOTAL", 128)
    with pytest.raises(ValueError, match="展开大小超限"):
        build_font(old, **options)
    assert not old.exists()
    manifest = build_font(local, **options, local_capacity=True)
    assert capacity.local_package(manifest)
    lib = tmp_path / "fonts"
    for approval in (None, "different"):
        with pytest.raises(LocalFontConsent) as caught:
            import_font(local, lib, approved_hash=approval)
        assert caught.value.content_hash == manifest["content_hash"]
        assert not list(lib.glob("*.inkfont"))
    result = import_font(local, lib, approved_hash=manifest["content_hash"])
    target = Path(result["path"])
    assert target.read_bytes() == local.read_bytes() and "本机大容量" in result["entry"][1]
    assert find_font_release(lib, release_identity(manifest)) == target
    assert len(tuple(core.cached_font(target).glyphs("A"))) == 2
    choice = subset_choices(target)["subset_choices"]["A"][0][0]
    portable = tmp_path / "portable.inkfont"
    stats = codec.convert(target, portable, candidate_ids={choice}, extensions=("math", "provenance"),
                          legacy_context=True)
    assert stats["candidates"] == 1
    assert codec.verify(portable)["candidates"] == 1
    assert [g.sample_id for g in core.cached_font(portable).glyphs("A")] == [choice]
    with ZipFile(target) as z:
        assert any(n.startswith("development/") for n in z.namelist())
    with pytest.raises(ValueError):
        codec.convert(target, tmp_path / "missing.inkfont", candidate_ids={"missing"})
    assert not (tmp_path / "missing.inkfont").exists()
    with pytest.raises(ValueError):
        codec.convert(target, tmp_path / "unselected.inkfont")
    assert not (tmp_path / "unselected.inkfont").exists()


def test_local_limits_apply_only_to_index_metadata():
    assert capacity.member_limit("glyphs/a.json", True, 32) == 32
    assert capacity.member_limit("development/a.json", True, 32) == 32
    assert capacity.member_limit("index.json", False, 32) == 32
    assert capacity.member_limit("index.json", True, 32) == capacity.LOCAL_METADATA


def test_publication_cancel_before_preparation():
    from types import SimpleNamespace
    from unittest.mock import Mock
    from inkstruct.fonts.ui import FontLibrary
    inputs = ("writer", None, None, "font")
    groups = {"han"}
    view = SimpleNamespace(
        publication_inputs=lambda: inputs, review=inputs,
        selected_publication_groups=lambda: groups, review_groups=groups,
        review_stamp=(), rule_settings=None, kind=SimpleNamespace(currentData=lambda: "developer"),
        build_button=SimpleNamespace(isEnabled=lambda: True), local_capacity=SimpleNamespace(isChecked=lambda: False),
        review_result={"coverage": {("han", "generated", "字"): 52643}},
        confirm_local=Mock(return_value=False), submit=Mock())
    FontLibrary.build(view)
    view.confirm_local.assert_called_once_with(52643)
    view.submit.assert_not_called()
