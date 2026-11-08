"""Valid font catalogs have their own finite bound; integrity stays strict."""

import json
import zipfile
from hashlib import sha256

import pytest

from inkstruct.assets.resolver import AssetResolver
from inkstruct.document import package
from inkstruct.document.editing import SourceSession
from inkstruct.document.schema import PageProfile, StyleProfile


def record(tmp_path):
    p = tmp_path/'original.inkdoc'
    package.save_package(p, SourceSession('12'), AssetResolver(builtin_numbers=True), PageProfile(), StyleProfile())
    with zipfile.ZipFile(p) as z:
        return {n:z.read(n) for n in z.namelist()}


def write(tmp_path, members, *, rehash=True):
    if rehash:
        manifest = json.loads(members['manifest.json'])
        manifest['sha256'] = {n:sha256(b).hexdigest() for n,b in members.items() if n!='manifest.json'}
        members['manifest.json'] = json.dumps(manifest).encode()
    p = tmp_path/'catalog.inkdoc'
    with zipfile.ZipFile(p,'w',compression=zipfile.ZIP_DEFLATED) as z:
        for n,b in members.items():z.writestr(n,b)
    return p


def test_catalog_over_old_single_member_cap_still_checks_hashes(tmp_path):
    members = record(tmp_path)
    members['resources.json'] += b' ' * 16_000_001
    p = write(tmp_path,members)
    assert package.load_package(p).session.source == '12'
    members['resources.json'] += b' '
    write(tmp_path,members,rehash=False)
    with pytest.raises(ValueError):
        package.load_package(p)


@pytest.mark.parametrize('member', ['resources.json','source.md'])
def test_catalog_and_other_members_keep_separate_finite_limits(tmp_path,monkeypatch,member):
    members = record(tmp_path)
    monkeypatch.setattr(package,'MAX_MEMBER_BYTES',4000)
    monkeypatch.setattr(package,'MAX_RESOURCE_CATALOG_BYTES',8000)
    members[member] += b' '*9000
    p = write(tmp_path,members)
    with pytest.raises(ValueError,match='oversized'):
        package.load_package(p)
