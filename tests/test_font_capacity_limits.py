"""The 4 GiB archive budget changes no member, trajectory or integrity rules."""
import copy
import stat
import struct
import zipfile
from types import SimpleNamespace

import pytest
from test_font_packages import recorded

from inkstruct.fonts import core
from inkstruct.fonts.importer import build_font


@pytest.fixture
def archive_parts(tmp_path):
    original = tmp_path / "original.inkfont"
    build_font(original, writer="fixture", name="capacity limits", symbols=recorded(tmp_path))
    with zipfile.ZipFile(original) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    manifest = core.decode(members.pop("manifest.json"))
    return original, members, manifest


def publication_spy(monkeypatch):
    calls = []
    original = core.os.link
    def publish(source, target):
        calls.append((source, target))
        return original(source, target)
    monkeypatch.setattr(core.os, "link", publish)
    return calls


def input_values(tmp_path, members, kind):
    if kind == "bytes":
        return members
    folder = tmp_path / "input-files"
    folder.mkdir()
    result = {}
    for index, (name, raw) in enumerate(members.items()):
        path = folder / str(index)
        path.write_bytes(raw)
        result[name] = path
    return result


def test_only_total_capacity_changes():
    assert core.MAX_TOTAL == 4 * 1024**3
    assert core.MAX_MEMBER == 32 * 1024**2
    assert core.MAX_POINTS == 100_000


@pytest.mark.parametrize("kind", ["bytes", "paths"])
@pytest.mark.parametrize("spare", [-1, 0])
def test_writer_total_includes_final_manifest_and_accepts_exact_boundary(
        archive_parts, tmp_path, monkeypatch, kind, spare):
    original, members, manifest = archive_parts
    with zipfile.ZipFile(original) as archive:
        total = sum(info.file_size for info in archive.infolist())
        manifest_size = len(archive.read("manifest.json"))
    assert total == sum(map(len, members.values())) + manifest_size
    assert sum(map(len, members.values())) < total - 1
    values = input_values(tmp_path, members, kind)
    monkeypatch.setattr(core, "MAX_TOTAL", total + spare)
    publications = publication_spy(monkeypatch)
    output = tmp_path / "publish" / "boundary.inkfont"
    if spare < 0:
        with pytest.raises(ValueError, match="展开大小超限"):
            core.write_archive(output, values, manifest)
        assert not output.exists() and not publications
    else:
        result = core.write_archive(output, values, manifest)
        assert len(publications) == 1 and output.is_file()
        assert result == manifest
        assert core.FontPackage(output).verify() == core.FontPackage(original).verify()
    assert not list(output.parent.glob("*.tmp"))


@pytest.mark.parametrize("kind", ["bytes", "paths"])
def test_writer_rejects_member_data_total_before_publication(
        archive_parts, tmp_path, monkeypatch, kind):
    _, members, manifest = archive_parts
    values = input_values(tmp_path, members, kind)
    monkeypatch.setattr(core, "MAX_TOTAL", sum(map(len, members.values())) - 1)
    publications = publication_spy(monkeypatch)
    output = tmp_path / "too-large.inkfont"
    with pytest.raises(ValueError, match="展开大小超限"):
        core.write_archive(output, values, manifest)
    assert not output.exists() and not publications
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize("kind", ["bytes", "paths"])
def test_writer_keeps_individual_member_limit(archive_parts, tmp_path, monkeypatch, kind):
    _, _, manifest = archive_parts
    members = {"payload.bin": b"x" * 33}
    values = input_values(tmp_path, members, kind)
    monkeypatch.setattr(core, "MAX_MEMBER", 32)
    publications = publication_spy(monkeypatch)
    output = tmp_path / "large-member.inkfont"
    with pytest.raises(ValueError, match="成员超限：payload.bin"):
        core.write_archive(output, values, manifest)
    assert not output.exists() and not publications
    assert not list(tmp_path.glob("*.tmp"))


def test_writer_manifest_itself_keeps_individual_member_limit(
        archive_parts, tmp_path, monkeypatch):
    _, _, manifest = archive_parts
    members = {"payload.bin": b"x"}
    probe = tmp_path / "manifest-probe.inkfont"
    core.write_archive(probe, members, manifest)
    with zipfile.ZipFile(probe) as archive:
        size = len(archive.read("manifest.json"))
    monkeypatch.setattr(core, "MAX_MEMBER", size - 1)
    publications = publication_spy(monkeypatch)
    output = tmp_path / "large-manifest.inkfont"
    with pytest.raises(ValueError, match="成员超限：manifest.json"):
        core.write_archive(output, members, manifest)
    assert not output.exists() and not publications
    assert not list(tmp_path.glob("*.tmp"))


def test_writer_member_count_includes_manifest(archive_parts, tmp_path, monkeypatch):
    _, _, manifest = archive_parts
    members = {f"development/{index}.json": b"" for index in range(100_000)}
    publications = publication_spy(monkeypatch)
    output = tmp_path / "too-many.inkfont"
    with pytest.raises(ValueError, match="成员过多"):
        core.write_archive(output, members, manifest)
    assert not output.exists() and not publications
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize("spare", [-1, 0])
def test_reader_total_includes_manifest_and_keeps_boundary(archive_parts, monkeypatch, spare):
    original, _, _ = archive_parts
    with zipfile.ZipFile(original) as archive:
        total = sum(info.file_size for info in archive.infolist())
    expected = core.FontPackage(original).verify()
    monkeypatch.setattr(core, "MAX_TOTAL", total + spare)
    if spare < 0:
        with pytest.raises(ValueError, match="展开大小超限"):
            core.FontPackage(original)
    else:
        assert core.FontPackage(original).verify() == expected


def test_reader_keeps_member_count_guard(archive_parts, monkeypatch):
    original, _, _ = archive_parts
    infos = [SimpleNamespace(filename=f"member-{index}") for index in range(100_001)]
    monkeypatch.setattr(zipfile.ZipFile, "infolist", lambda self: infos)
    with pytest.raises(ValueError, match="成员过多"):
        core.FontPackage(original)


@pytest.mark.parametrize("name", ["../escape.json", "/absolute.json", "x/../escape.json",
                                   "x\\..\\escape.json", "C:/escape.json"])
def test_reader_still_rejects_unsafe_paths(archive_parts, tmp_path, name):
    original, _, _ = archive_parts
    output = tmp_path / "unsafe.inkfont"
    with zipfile.ZipFile(original) as source, zipfile.ZipFile(output, "w") as target:
        for info in source.infolist():
            target.writestr(info, source.read(info.filename))
        target.writestr(name, b"unsafe")
    before = output.read_bytes()
    with pytest.raises(ValueError, match="不安全的字体成员"):
        core.FontPackage(output)
    assert output.read_bytes() == before
    assert not (tmp_path / "escape.json").exists()


def test_reader_keeps_backslash_metadata_guard(archive_parts, monkeypatch):
    original, _, _ = archive_parts
    infolist = zipfile.ZipFile.infolist
    def raw_metadata(archive):
        infos = list(infolist(archive))
        infos[0] = copy.copy(infos[0])
        # Windows zipfile normalizes written names. Explicit raw metadata
        # isolates the application guard from that platform behavior.
        infos[0].filename = "x\\escape.json"
        return infos
    monkeypatch.setattr(zipfile.ZipFile, "infolist", raw_metadata)
    with pytest.raises(ValueError, match="不安全的字体成员"):
        core.FontPackage(original)


def test_reader_still_rejects_symlink_member(archive_parts, tmp_path):
    original, _, _ = archive_parts
    output = tmp_path / "symlink.inkfont"
    link = zipfile.ZipInfo("development/link")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(original) as source, zipfile.ZipFile(output, "w") as target:
        for info in source.infolist():
            target.writestr(info, source.read(info.filename))
        target.writestr(link, "outside")
    with pytest.raises(ValueError, match="不安全的字体成员"):
        core.FontPackage(output)


@pytest.mark.parametrize("duplicate", ["index.json", "INDEX.JSON"])
def test_reader_still_rejects_duplicate_or_casefold_paths(archive_parts, tmp_path, duplicate):
    original, _, _ = archive_parts
    output = tmp_path / "duplicate.inkfont"
    with zipfile.ZipFile(original) as source, zipfile.ZipFile(output, "w") as target:
        for info in source.infolist():
            target.writestr(info, source.read(info.filename))
        if duplicate == "index.json":
            with pytest.warns(UserWarning, match="Duplicate name"):
                target.writestr(duplicate, b"{}")
        else:
            target.writestr(duplicate, b"{}")
    with pytest.raises(ValueError, match="路径重复"):
        core.FontPackage(output)


def test_reader_still_rejects_encrypted_member_flag(archive_parts, tmp_path):
    original, _, _ = archive_parts
    # Set the encryption bit in the first local/central header. No decryption or
    # successful read is intended: flagged entries must fail before payload IO.
    raw = bytearray(original.read_bytes())
    with zipfile.ZipFile(original) as archive:
        offsets = (archive.infolist()[0].header_offset + 6, archive.start_dir + 8)
    for offset in offsets:
        flags = struct.unpack_from("<H", raw, offset)[0]
        struct.pack_into("<H", raw, offset, flags | 1)
    output = tmp_path / "encrypted-flag.inkfont"
    output.write_bytes(raw)
    with pytest.raises(ValueError, match="不安全的字体成员"):
        core.FontPackage(output)


def test_reader_still_rejects_member_size_limit(archive_parts, monkeypatch):
    original, _, _ = archive_parts
    with zipfile.ZipFile(original) as archive:
        maximum = max(info.file_size for info in archive.infolist())
    monkeypatch.setattr(core, "MAX_MEMBER", maximum - 1)
    with pytest.raises(ValueError, match="不安全的字体成员"):
        core.FontPackage(original)


def test_reader_still_rejects_damaged_hash(archive_parts, tmp_path):
    original, _, _ = archive_parts
    output = tmp_path / "damaged.inkfont"
    with zipfile.ZipFile(original) as source, zipfile.ZipFile(output, "w") as target:
        for info in source.infolist():
            data = source.read(info.filename)
            if info.filename == "index.json":
                data += b" "
            target.writestr(info, data)
    before = output.read_bytes()
    with pytest.raises(ValueError, match="成员损坏"):
        core.FontPackage(output)
    assert output.read_bytes() == before


def test_reader_still_rejects_point_budget(archive_parts, monkeypatch):
    original, members, _ = archive_parts
    index = core.decode(members["index.json"])
    first = core.decode(members[index["candidates"][0]["file"]])
    count = sum(len(stroke["points"]) for stroke in first["strokes"])
    monkeypatch.setattr(core, "MAX_POINTS", count - 1)
    with pytest.raises(ValueError, match="点数超过资源预算"):
        core.FontPackage(original).verify()


@pytest.mark.parametrize("channel", ["pressure", "geometry"])
def test_resigned_candidate_is_still_semantically_checked(archive_parts, tmp_path, channel):
    _, members, manifest = archive_parts
    changed = copy.deepcopy(members)
    index = core.decode(changed["index.json"])
    name = index["candidates"][0]["file"]
    trajectory = core.decode(changed[name])
    point = trajectory["strokes"][0]["points"][0]
    point["pressure" if channel == "pressure" else "x"] = 2 if channel == "pressure" else 99
    changed[name] = core.encoded(trajectory)
    output = tmp_path / "resigned.inkfont"
    core.write_archive(output, changed, manifest)
    with pytest.raises(ValueError):
        core.FontPackage(output).verify()


def test_existing_publication_is_never_overwritten(archive_parts, tmp_path):
    _, members, manifest = archive_parts
    output = tmp_path / "existing.inkfont"
    output.write_bytes(b"existing publication")
    with pytest.raises(FileExistsError):
        core.write_archive(output, members, manifest)
    assert output.read_bytes() == b"existing publication"
