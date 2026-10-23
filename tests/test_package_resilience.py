"""Portable project corruption and interrupted writes fail without lost user data."""

import io
import json
import zipfile
from dataclasses import asdict
from hashlib import sha256

import pytest

from inkstruct.assets.resolver import AssetResolver
from inkstruct.document.editing import SourceSession
from inkstruct.document.markdown import parse_markdown
from inkstruct.document.package import load_package, package_bytes, save_package
from inkstruct.document.schema import PageProfile, StyleProfile
from inkstruct.editor import review
from inkstruct.editor.review import Review, atomic_write
from inkstruct.layout.blocks import layout_markdown


def fixture():
    session = SourceSession("12.50")
    resolver = AssetResolver(builtin_numbers=True)
    layout_markdown(parse_markdown(session), resolver)
    raw = package_bytes(session, resolver, PageProfile(), StyleProfile())
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        return {n: z.read(n) for n in z.namelist()}


def archive(path, members):
    manifest = json.loads(members["manifest.json"])
    if isinstance(manifest, dict):
        manifest["sha256"] = {
            n: sha256(data).hexdigest() for n, data in members.items() if n != "manifest.json"
        }
        members["manifest.json"] = json.dumps(manifest).encode()
    with zipfile.ZipFile(path, "w") as z:
        for n, data in members.items():
            z.writestr(n, data)


@pytest.mark.parametrize(
    "name",
    [
        "manifest.json",
        "identity.json",
        "styles.json",
        "resources.json",
        "selections.json",
        "reviews.json",
    ],
)
@pytest.mark.parametrize("value", [None, 5, "bad"])
def test_wrong_root_types_are_consistent_value_errors_and_never_rewritten(tmp_path, name, value):
    members = fixture()
    members[name] = json.dumps(value).encode()
    path = tmp_path / "broken.inkdoc"
    archive(path, members)
    before = path.read_bytes()
    with pytest.raises(ValueError):
        load_package(path)
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    "member,key,value",
    [
        ("manifest.json", "optimize", "false"),
        ("manifest.json", "optimize", 0),
        ("manifest.json", "allow_reverse", "false"),
        ("manifest.json", "allow_reverse", True),
        ("manifest.json", "seed", True),
        ("manifest.json", "seed", []),
        ("styles.json", "flow", []),
        ("styles.json", "page", []),
        ("identity.json", "atom_ids", [None] * 5),
    ],
)
def test_structured_metadata_is_not_coerced_or_silently_ignored(tmp_path, member, key, value):
    members = fixture()
    record = json.loads(members[member])
    record[key] = value
    members[member] = json.dumps(record).encode()
    path = tmp_path / "broken.inkdoc"
    archive(path, members)
    with pytest.raises(ValueError):
        load_package(path)


@pytest.mark.parametrize(
    "name,value",
    [
        ("resources.json", [None]),
        ("resources.json", [{}]),
        ("selections.json", [None]),
        ("reviews.json", [None]),
        ("reviews.json", [{}]),
    ],
)
def test_invalid_records_are_consistent_errors(tmp_path, name, value):
    members = fixture()
    members[name] = json.dumps(value).encode()
    path = tmp_path / "broken.inkdoc"
    archive(path, members)
    with pytest.raises(ValueError):
        load_package(path)


@pytest.mark.parametrize(
    "damage",
    [
        "duplicate-resource",
        "invalid-resource-id",
        "duplicate-review",
        "unknown-rating",
        "review-note-type",
        "review-index",
        "selection-version",
        "empty-selection",
        "missing-resource",
    ],
)
def test_resource_selection_and_review_integrity(tmp_path, damage):
    members = fixture()
    resources = json.loads(members["resources.json"])
    choices = json.loads(members["selections.json"])
    r = resources[0]
    records = [
        asdict(
            Review(
                r["asset_id"],
                r["character"],
                "bad",
                "note",
                "",
                "",
                "",
                "",
                "12.50",
                "hash",
                0,
                "now",
            )
        )
    ]
    if damage == "duplicate-resource":
        resources.append(resources[0])
    if damage == "invalid-resource-id":
        resources[0]["metrics_key"] = []
    if damage == "duplicate-review":
        records.append(records[0])
    if damage == "unknown-rating":
        records[0]["rating"] = "unknown"
    if damage == "review-note-type":
        records[0]["note"] = {}
    if damage == "review-index":
        records[0]["source_start"] = True
    if damage == "selection-version":
        choices[0]["selection_version"] = "future-v9"
    if damage == "empty-selection":
        choices[0]["occurrence_id"] = ""
    if damage == "missing-resource":
        members.pop(resources[0]["source_file"])
    members.update(
        {
            n: json.dumps(v).encode()
            for n, v in [
                ("resources.json", resources),
                ("selections.json", choices),
                ("reviews.json", records),
            ]
        }
    )
    path = tmp_path / "broken.inkdoc"
    archive(path, members)
    with pytest.raises(ValueError):
        load_package(path)


@pytest.mark.parametrize(
    "data",
    [
        b'{"x":1,"x":2}',
        b'{"x":NaN}',
        b'{"x":Infinity}',
        b'{"x":-Infinity}',
        b"[" * 1100 + b"]" * 1100,
    ],
)
def test_ambiguous_nonfinite_or_excessively_nested_json_rejected(tmp_path, data):
    members = fixture()
    members["styles.json"] = data
    path = tmp_path / "broken.inkdoc"
    archive(path, members)
    with pytest.raises(ValueError):
        load_package(path)


def test_invalid_review_is_rejected_before_existing_project_write(tmp_path):
    path = tmp_path / "safe.inkdoc"
    session = SourceSession("1")
    r = AssetResolver(builtin_numbers=True)
    stamp = save_package(path, session, r, PageProfile(), StyleProfile())
    before = path.read_bytes()
    with pytest.raises(ValueError):
        save_package(
            path, session, r, PageProfile(), StyleProfile(), expected_hash=stamp, reviews=({},)
        )
    assert path.read_bytes() == before


@pytest.mark.parametrize("stage", ["write-sync", "rename", "external-change"])
def test_failed_atomic_save_preserves_destination_and_removes_temp(tmp_path, monkeypatch, stage):
    path = tmp_path / "saved.inkdoc"
    path.write_bytes(b"original")
    stamp = sha256(b"original").hexdigest()

    def sync(_):
        if stage == "external-change":
            path.write_bytes(b"external")
        else:
            raise OSError("simulated disk failure")

    def rename(*_):
        raise OSError("simulated rename failure")

    monkeypatch.setattr(review.os, "replace", rename) if stage == "rename" else monkeypatch.setattr(
        review.os, "fsync", sync
    )
    with pytest.raises((ValueError, OSError)):
        atomic_write(path, b"new", stamp)
    assert path.read_bytes() == (b"external" if stage == "external-change" else b"original")
    assert not list(tmp_path.glob(".inkstruct-review-*"))


def test_moved_unicode_project_and_archive_need_no_old_resource_paths(tmp_path):
    members = fixture()
    original = tmp_path / "old.inkdoc"
    archive(original, members)
    before = load_package(original)
    folder = tmp_path / "迁移 空格 Ω"
    folder.mkdir()
    moved = folder / "项目.inkdoc"
    original.rename(moved)
    after = load_package(moved)
    assert after.session.identity_record() == before.session.identity_record()
    assert after.resolver.selection_records() == before.resolver.selection_records()
    assert layout_markdown(parse_markdown(after.session), after.resolver) == layout_markdown(
        parse_markdown(before.session), before.resolver
    )


@pytest.mark.parametrize("optimize", ["false", 0, 1, None])
def test_invalid_export_option_cannot_replace_saved_project(tmp_path, optimize):
    path = tmp_path / "safe.inkdoc"
    session = SourceSession("1")
    resolver = AssetResolver(builtin_numbers=True)
    stamp = save_package(path, session, resolver, PageProfile(), StyleProfile())
    before = path.read_bytes()
    with pytest.raises(ValueError, match="boolean"):
        save_package(
            path,
            session,
            resolver,
            PageProfile(),
            StyleProfile(),
            expected_hash=stamp,
            optimize=optimize,
        )
    assert path.read_bytes() == before
