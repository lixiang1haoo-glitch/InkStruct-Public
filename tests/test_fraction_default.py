"""New fractions use recorded minus; legacy records keep their geometry."""

import hashlib
import json
import zipfile
from dataclasses import asdict, replace

import pytest
from PySide6 import QtCore
from test_math_sample_constructions import measure, resolver

from inkstruct.assets.resolver import AssetResolver
from inkstruct.document.editing import SourceSession
from inkstruct.document.package import load_package, save_package
from inkstruct.document.schema import PageProfile, StyleProfile
from inkstruct.document.styles import FlowStyle
from inkstruct.global_defaults import GlobalDefaultsStore, LayoutDefaults
from inkstruct.math.style import MathStyle


def test_default_fraction_stretches_selected_minus_only_horizontally():
    r = resolver()
    style = MathStyle()
    assert style.fraction_source == "sample"
    assert style.radical_source == style.delimiter_source == "geometric"
    short = measure(SourceSession(r"$\frac{1}{2}$"), r, style)
    wide = measure(SourceSession(r"$\frac{12345}{2}$"), r, style)
    assert short.ready and wide.ready
    a, b = short.rules[0], wide.rules[0]
    assert a.asset_id == b.asset_id and a.sample_id == b.sample_id
    assert a.transform == b.transform == "sample-minus-length-v1"
    assert [y for _, y in a.points] == [y for _, y in b.points]
    assert b.points[-1][0] > a.points[-1][0]


def test_missing_minus_is_reported_without_silent_geometric_substitution():
    box = measure(SourceSession(r"$\frac{1}{2}$"), AssetResolver(builtin_numbers=True), MathStyle())
    assert not box.ready
    assert any(d.code == "math-construction-sample-invalid" for d in box.diagnostics)


def test_legacy_math_record_without_source_retains_geometric():
    assert FlowStyle().math.fraction_source == "sample"
    assert FlowStyle(math={"em_mm": 7}).math.fraction_source == "geometric"
    for source in ("geometric", "sample"):
        assert FlowStyle(math={"fraction_source": source}).math.fraction_source == source


@pytest.mark.parametrize("missing", ["math", "fraction_source"])
def test_old_package_missing_math_setting_keeps_geometry_and_source(tmp_path, missing):
    path = tmp_path / 'legacy.inkdoc'
    session = SourceSession(r'$\frac{1}{2}$')
    save_package(path, session, AssetResolver(builtin_numbers=True), PageProfile(), StyleProfile(),
                 flow=FlowStyle(math=MathStyle(fraction_source='geometric')))
    with zipfile.ZipFile(path) as archive:
        members = {n: archive.read(n) for n in archive.namelist()}
    styles = json.loads(members['styles.json'])
    if missing == 'math':
        styles['flow'].pop('math')
    else:
        styles['flow']['math'].pop('fraction_source')
    members['styles.json'] = json.dumps(styles).encode()
    manifest = json.loads(members['manifest.json'])
    manifest['sha256']['styles.json'] = hashlib.sha256(members['styles.json']).hexdigest()
    members['manifest.json'] = json.dumps(manifest).encode()
    with zipfile.ZipFile(path, 'w') as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    before = path.read_bytes()
    loaded = load_package(path)
    assert loaded.flow.math.fraction_source == 'geometric'
    assert loaded.session.source == session.source
    assert loaded.session.atom_ids == session.atom_ids
    assert path.read_bytes() == before


@pytest.mark.parametrize("choice", ["geometric", "sample"])
def test_global_default_upgrade_is_read_only_and_explicit_choice_survives(tmp_path, choice):
    QtCore.QSettings.setDefaultFormat(QtCore.QSettings.IniFormat)
    QtCore.QSettings.setPath(QtCore.QSettings.IniFormat, QtCore.QSettings.UserScope, str(tmp_path))
    store = GlobalDefaultsStore()
    old = LayoutDefaults(flow=replace(FlowStyle(), math=MathStyle(fraction_source="geometric")))
    record = {"version": 1, **asdict(old)}
    record["flow"].pop("latin_spacing")
    raw = json.dumps(record)
    store.settings.setValue(store.KEY, raw)
    store.settings.sync()
    store = GlobalDefaultsStore()
    upgraded, warning = store.load()
    assert warning is None and upgraded.flow.math.fraction_source == "sample"
    assert upgraded.flow.punctuation_spacing == 'handwriting'
    assert replace(upgraded, flow=replace(upgraded.flow, math=old.flow.math,
                   punctuation_spacing='capture', schema_version=old.flow.schema_version)) == old
    assert store.settings.value(store.KEY) == raw
    assert store.settings.value(store.FRACTION_DEFAULT_KEY) is None
    selected = replace(upgraded, flow=replace(upgraded.flow, math=MathStyle(fraction_source=choice)))
    store.save(selected)
    assert GlobalDefaultsStore().load() == (selected, None)
