"""Reuse verified content without relaxing font or geometry checks."""
import copy
import os
import zipfile
from dataclasses import replace

import pytest
from test_font_packages import recorded

from inkstruct.fonts import core
from inkstruct.fonts.importer import build_font
from inkstruct.layout.measurement_cache import _weight


def test_verified_font_reuse_rechecks_member_and_reuses_geometry(tmp_path, monkeypatch):
    path = tmp_path / 'font.inkfont'
    build_font(path, writer='fixture', name='test', symbols=recorded(tmp_path))
    font = core.FontPackage(path)
    first = tuple(font.glyphs())
    original = core.trajectory_hashes

    def forbidden(*args):
        raise AssertionError('unchanged verified candidate was recompiled')

    monkeypatch.setattr(core, 'trajectory_hashes', forbidden)
    assert all(a is b for a, b in zip(first, font.glyphs(reuse=first), strict=True))
    monkeypatch.setattr(core, 'trajectory_hashes', original)
    # Replacing a frozen descriptor cannot inherit its validation marker.
    replaced = [replace(g, strokes=(((9.0, 9.0),),)) for g in first]
    assert tuple(font.glyphs(reuse=replaced)) == first
    assert all(a is not b for a, b in zip(replaced, font.glyphs(reuse=replaced), strict=True))
    # Every reuse still reads and hashes the actual archive member, even if its
    # path, size and mtime are unchanged.
    stamp = path.stat()
    with zipfile.ZipFile(path) as z:
        members = {name: z.read(name) for name in z.namelist()}
    name = font.records[0]['file']
    raw = members[name]
    members[name] = raw.replace(b'"x":', b'"q":', 1)
    assert members[name] != raw and len(members[name]) == len(raw)
    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_STORED) as z:
        for name, value in members.items():
            z.writestr(name, value)
    # Keep only the outer fingerprint unchanged to exercise the member gate.
    font.fingerprint = (path.stat().st_size, stamp.st_mtime_ns)
    os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    with pytest.raises(ValueError, match='成员损坏'):
        tuple(font.glyphs(reuse=first))


def test_reuse_does_not_ignore_metadata_changes_or_numeric_type(tmp_path):
    path = tmp_path / 'font.inkfont'
    build_font(path, writer='fixture', name='test', symbols=recorded(tmp_path))
    font = core.FontPackage(path)
    glyph = next(font.glyphs())
    c = core.decode(glyph.original_json)
    changed = copy.deepcopy(c)
    changed['summary']['capture_guides'] = {'math_axis_em': 0.4}
    changed['record']['source_summary_hash'] = core.semantic_hash(changed['summary'])
    new = core.resolved_candidate(changed['record'], changed['trajectory'], changed['metrics'],
                                  changed['summary'], changed['identity'], _reuse=glyph)
    assert new is not glyph and new.math_axis_em == 0.4
    changed['summary']['capture_guides']['math_axis_em'] = True
    with pytest.raises(ValueError, match='数学轴'):
        core.resolved_candidate(changed['record'], changed['trajectory'], changed['metrics'],
                                changed['summary'], changed['identity'], _reuse=new)


def test_frozen_geometry_bounds_and_size_are_computed_once(tmp_path):
    path = tmp_path / 'font.inkfont'
    build_font(path, writer='fixture', name='test', symbols=recorded(tmp_path))
    glyph = next(core.FontPackage(path).glyphs())
    first = glyph.bounds
    assert glyph.bounds is first
    weight = _weight(glyph)
    assert weight == glyph.retained_bytes and weight > len(glyph.original_json)
    assert _weight((glyph, glyph)) < 2 * weight
    changed = replace(glyph, strokes=(((0.0, 0.0), (2.0, 3.0)),))
    assert changed.bounds == (0.0, 0.0, 2.0, 3.0)
    assert changed.bounds != glyph.bounds
