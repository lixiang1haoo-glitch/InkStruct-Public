"""Full verification stays strict while import avoids duplicate layout decoding."""

import zipfile
from pathlib import Path

import pytest
from test_font_packages import recorded

from inkstruct.fonts import core, library
from inkstruct.fonts.importer import build_font


@pytest.fixture
def font_path(tmp_path):
    path = tmp_path / "original.inkfont"
    build_font(path, writer="fixture", name="import check", symbols=recorded(tmp_path))
    return path


def rewrite(source, output, change):
    with zipfile.ZipFile(source) as archive:
        manifest = core.decode(archive.read("manifest.json"))
        members = {name: archive.read(name) for name in manifest["members"]}
    change(members)
    core.write_archive(output, members, manifest)


def test_single_validation_without_layout_allocation(font_path, tmp_path, monkeypatch):
    font = core.FontPackage(font_path)
    glyphs = tuple(font.glyphs())
    expected_points = sum(len(s) for g in glyphs for s in g.strokes)
    original = core.validate_candidate
    calls = []

    def validate(*args):
        calls.append(args[0]["candidate_id"])
        return original(*args)

    monkeypatch.setattr(core, "validate_candidate", validate)
    monkeypatch.setattr(
        core, "resolved_candidate", lambda *a, **k: pytest.fail("Layout asset allocated on import")
    )
    progress = []
    result = library.import_font(font_path, tmp_path / "library", progress.append)
    assert len(calls) == len(font.records) == len(set(calls))
    assert Path(result["path"]).read_bytes() == font_path.read_bytes()
    assert result["entry"][0] == library.fingerprint(result["path"])
    assert progress[0].startswith("正在复制")
    assert any(f"{len(font.records)}/{len(font.records)}" in text for text in progress)
    verified = core.FontPackage(result["path"], verify_all=False).verify()
    assert verified["points"] == expected_points
    assert verified["candidates"] == len(glyphs)


@pytest.mark.parametrize(
    "kind",
    [
        "geometry",
        "pressure",
        "time",
        "pen_state",
        "dynamic_origin",
        "summary",
        "axis",
        "metrics",
        "letter_style",
    ],
)
@pytest.mark.parametrize('workers', [1, 2])
def test_resigned_invalid_candidate_still_rejected(font_path, tmp_path, kind, workers):
    def change(members):
        index = core.decode(members["index.json"])
        record = index["candidates"][0]
        cid = record["candidate_id"]
        trajectory = core.decode(members[record["file"]])
        summary = core.decode(members["provenance.json"])
        metrics = core.decode(members["metrics.json"])
        point = trajectory["strokes"][0]["points"][0]
        if kind == "geometry":
            point["x"] += 0.1
        elif kind == "pressure":
            point["pressure"] = 2
        elif kind == "time":
            point["t_ms"] = -1
        elif kind == "pen_state":
            point["pen_state"] = "bad"
        elif kind == "dynamic_origin":
            trajectory["strokes"][0]["dynamic_origin"]["time"] = "bad"
        elif kind == "summary":
            summary[cid]["author_strokes"] = []
            record["source_summary_hash"] = core.semantic_hash(summary[cid])
        elif kind == "axis":
            summary[cid]["capture_guides"] = {"math_axis_em": True}
            record["source_summary_hash"] = core.semantic_hash(summary[cid])
        elif kind == "metrics":
            metrics[cid]["advance"] = -1
            record["metrics_id"] = core.semantic_hash(metrics[cid])
        elif kind == "letter_style":
            record["letter_style"] = "bad"
        members[record["file"]] = core.encoded(trajectory)
        members["index.json"] = core.encoded(index)
        members["metrics.json"] = core.encoded(metrics)
        members["provenance.json"] = core.encoded(summary)

    damaged = tmp_path / "invalid.inkfont"
    rewrite(font_path, damaged, change)
    # Re-signed members pass byte hashes; semantic checks must still reject them.
    core.FontPackage(damaged, verify_all=False)
    original = font_path.read_bytes()
    with pytest.raises(ValueError):
        library.import_font(damaged, tmp_path / "library", workers=workers)
    assert not list((tmp_path / "library").iterdir())
    assert font_path.read_bytes() == original


def test_complete_verification_checks_unreferenced_member(font_path, tmp_path):
    extra = tmp_path / "extra.inkfont"
    rewrite(font_path, extra, lambda members: members.update({"development/check.json": b"{}"}))
    with zipfile.ZipFile(extra) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    members["development/check.json"] = b"{ }"
    damaged = tmp_path / "damaged.inkfont"
    with zipfile.ZipFile(damaged, "w") as archive:
        for name, raw in members.items():
            archive.writestr(name, raw)
    font = core.FontPackage(damaged, verify_all=False)
    with pytest.raises(ValueError, match="成员损坏"):
        font.verify()
    from inkstruct.fonts.parallel_verify import verify_font
    with pytest.raises(ValueError, match="成员损坏"):
        verify_font(font, workers=2)


def test_duplicate_identity_does_not_replace_existing_font(font_path, tmp_path):
    root = tmp_path / "library"
    first = library.import_font(font_path, root)
    assert library.import_font(font_path, root)["path"] == first["path"]
    collision = tmp_path / "collision.inkfont"
    rewrite(font_path, collision, lambda members: members.update({"development/new.json": b"{}"}))
    original = Path(first["path"]).read_bytes()
    with pytest.raises(ValueError, match="同一包 ID"):
        library.import_font(collision, root)
    assert Path(first["path"]).read_bytes() == original
    assert len(list(root.iterdir())) == 1


def test_staged_copy_is_verified_instead_of_trusting_source(font_path, tmp_path, monkeypatch):
    copyfile = library.shutil.copyfile

    def corrupt(source, target):
        copyfile(source, target)
        with zipfile.ZipFile(target) as archive:
            members = {name: archive.read(name) for name in archive.namelist()}
        name = next(n for n in members if n.startswith("glyphs/"))
        members[name] += b" "
        with zipfile.ZipFile(target, "w") as archive:
            for name, raw in members.items():
                archive.writestr(name, raw)

    monkeypatch.setattr(library.shutil, "copyfile", corrupt)
    with pytest.raises(ValueError, match="成员损坏"):
        library.import_font(font_path, tmp_path / "library")
    assert not list((tmp_path / "library").iterdir())
    assert core.FontPackage(font_path).verify()["candidates"] == 2


def test_failed_publication_leaves_no_partial_font(font_path, tmp_path, monkeypatch):
    def fail(*args):
        raise OSError("write denied")

    monkeypatch.setattr(library.os, "link", fail)
    with pytest.raises(OSError, match="write denied"):
        library.import_font(font_path, tmp_path / "library")
    assert not list((tmp_path / "library").iterdir())
