import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from zipfile import ZipFile

import pytest

from inkstruct.fonts.exchange_codec import digest, encode
from inkstruct.fonts.reference import REFERENCE_FILE, REFERENCE_ID, install_reference


@pytest.fixture
def bundled(tmp_path):
    source = tmp_path / "bundled.inkfont"
    data = {"index.json": encode({"一": ["u4e00"]}),
            "glyphs/u4e00.json": encode({"strokes": [[[0, 0], [1, 0]]]})}
    manifest = {"format": "inkfont", "format_version": 1, "name": "参考字体", "font_id": REFERENCE_ID,
                "members": {key: {"bytes": len(value), "sha256": digest(value)} for key, value in data.items()}}
    with ZipFile(source, "w") as archive:
        for key, value in data.items():
            archive.writestr(key, value)
        archive.writestr("manifest.json", encode(manifest))
    return source


def test_unreadable_filename_collision_does_not_block_seeding(bundled, tmp_path, monkeypatch):
    library = tmp_path / "fonts"
    library.mkdir()
    other = library / REFERENCE_FILE
    other.write_bytes(b"unrelated")
    original = Path.open

    def restricted(self, *args, **kwargs):
        if self == other:
            raise PermissionError(13, "Permission denied", str(other))
        return original(self, *args, **kwargs)

    import inkstruct.fonts.reference as installer
    identify = installer.is_reference
    # ZipFile opens via io.open, independently of Path.open.
    with monkeypatch.context() as m:
        m.setattr(Path, "open", restricted)
        m.setattr(installer, "is_reference", lambda p: False if p == other else identify(p))
        new = install_reference(bundled, library)
    assert new != other and new.read_bytes() == bundled.read_bytes()
    assert install_reference(bundled, library) == new
    assert other.read_bytes() == b"unrelated"


@pytest.mark.skipif(os.name != "nt", reason="Windows installation ACLs")
def test_fresh_and_152_upgrade_inherit_library_dacl(bundled, tmp_path):
    library = tmp_path / "fonts"
    library.mkdir()
    control = library / "ordinary-file"
    control.write_bytes(b"control")

    def acl(path):
        return subprocess.check_output(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
            "([IO.File]::GetAccessControl($env:INKSTRUCT_ACL_TEST)).GetSecurityDescriptorSddlForm("
            "[Security.AccessControl.AccessControlSections]::Access)"],
            env={**os.environ, "INKSTRUCT_ACL_TEST": str(path)}, text=True).strip().replace("D:PAI", "D:P").replace("D:AI", "D:")

    expected = acl(control)
    fresh = install_reference(bundled, library)
    assert acl(fresh) == expected
    fresh.unlink()
    # Reproduce the exact 0.1.152 move, including a user-renamed package.
    old = library / "renamed.inkfont"
    with tempfile.TemporaryDirectory(dir=library) as folder:
        staged = Path(folder) / REFERENCE_FILE
        shutil.copyfile(bundled, staged)
        staged.rename(old)
    # Pytest's own private temp tree can already inherit owner-only ACEs.
    # Use the exact protected DACL captured from the 0.1.152 Windows installer.
    legacy = "D:P(A;;FA;;;OW)(A;;FA;;;SY)(A;;FA;;;BA)"
    if acl(old) != legacy:
        subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
            "$p=$env:INKSTRUCT_ACL_TEST; $a=[IO.File]::GetAccessControl($p); "
            "$a.SetSecurityDescriptorSddlForm($env:INKSTRUCT_TEST_DACL,"
            "[Security.AccessControl.AccessControlSections]::Access); [IO.File]::SetAccessControl($p,$a)"],
            env={**os.environ, "INKSTRUCT_ACL_TEST": str(old), "INKSTRUCT_TEST_DACL": legacy}, check=True)
    assert acl(old) == legacy and acl(old) != expected
    stamp = old.stat().st_mtime_ns
    assert install_reference(bundled, library) == old
    assert acl(old) == expected and old.stat().st_mtime_ns == stamp
    assert old.read_bytes() == bundled.read_bytes()
    assert list(library.glob("*.inkfont")) == [old]



def test_library_retries_permission_errors_without_a_file_change(bundled, tmp_path, monkeypatch):
    from time import monotonic
    from PySide6 import QtCore, QtTest, QtWidgets
    from inkstruct.fonts import management_ui
    from inkstruct.fonts.library import fingerprint
    from inkstruct.fonts.ui import FontLibrary
    from inkstruct.resource_catalog import FontMetadata

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    library = tmp_path / "fonts"
    path = install_reference(bundled, library)
    stamp = fingerprint(path)
    FontMetadata(library).update(path.name, error="old read error", error_stamp=list(stamp))
    real_summary = management_ui.summarize
    attempts = []
    unavailable = True

    def summarize(entry):
        attempts.append(entry)
        if unavailable:
            raise PermissionError("access denied")
        return real_summary(entry)

    def wait(predicate):
        end = monotonic() + 8
        while not predicate() and monotonic() < end:
            QtTest.QTest.qWait(10)
        assert predicate()

    monkeypatch.setattr(management_ui, "summarize", summarize)
    window = FontLibrary(library)
    try:
        window.refresh(str(path))
        wait(lambda: attempts and window.metadata_job is None)
        assert len(attempts) == 1 and not window.use_button.isEnabled()
        window.refresh(str(path))
        QtTest.QTest.qWait(50)
        assert len(attempts) == 1
        unavailable = False
        action = next(a for a in window.more_button.menu().actions() if a.text() == "刷新资源列表")
        action.trigger()
        wait(lambda: window.metadata_job is None and window.metadata_for(path))
        assert len(attempts) == 2 and window.use_button.isEnabled()
        assert fingerprint(path) == stamp
        selected = []
        window.use_requested.connect(selected.append)
        QtTest.QTest.mouseClick(window.use_button, QtCore.Qt.LeftButton)
        assert selected == [str(path)] and not FontMetadata(library).read()[path.name].get("error")
    finally:
        wait(lambda: window.inspection_job is None)
        window.close()
        app.processEvents()

def test_upgrade_known_reference_in_place_even_when_renamed(bundled, tmp_path, monkeypatch):
    from inkstruct.fonts import reference
    from inkstruct.fonts.library import file_digest

    library = tmp_path / "fonts"
    previous = install_reference(bundled, library).rename(library / "custom-name.inkfont")
    monkeypatch.setattr(reference, "HAN_ONLY_SHA256", file_digest(previous))
    # Change the reference's bytes while retaining its validated identity.
    with ZipFile(bundled, "a") as archive:
        archive.comment = b"next release"
    upgraded = install_reference(bundled, library)
    assert upgraded == previous and file_digest(upgraded) == file_digest(bundled)
    assert list(library.glob("*.inkfont")) == [previous]
    stamp = upgraded.stat().st_mtime_ns
    assert install_reference(bundled, library) == upgraded and upgraded.stat().st_mtime_ns == stamp


def test_customized_reference_is_not_overwritten(bundled, tmp_path):
    library = tmp_path / "fonts"
    customized = install_reference(bundled, library)
    with ZipFile(customized, "a") as archive:
        archive.comment = b"user variant"
    content = customized.read_bytes()
    assert install_reference(bundled, library) == customized
    assert customized.read_bytes() == content
