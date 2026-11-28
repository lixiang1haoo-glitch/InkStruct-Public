"""Install bundled reference handwriting with the same access as the user's library."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from zipfile import BadZipFile, ZipFile

from .core import exchange_manifest, package_manifest
from .exchange_codec import verify
from .library import file_digest


REFERENCE_ID = "3e5f7d55-94bc-5265-88b4-12c7c17a17b7"
REFERENCE_NAME = "参考字体"
REFERENCE_FILE = REFERENCE_NAME + ".inkfont"
# Exact official Han-only archive shipped in 0.1.152 and 0.1.153.
HAN_ONLY_SHA256 = bytes.fromhex("0133f9add44afb5cb5dd6c2822bae10de563b753c50fca215c3b175a3aeededd")


def is_reference(path):
    try:
        with ZipFile(path) as archive:
            manifest = package_manifest(archive)
            return exchange_manifest(manifest) and manifest.get("font_id") == REFERENCE_ID
    except (PermissionError, BadZipFile, KeyError, ValueError, TypeError, RuntimeError, AttributeError):
        return False


def _repair_152_acl(path):
    # Python 3.13 creates TemporaryDirectory on Windows with this protected DACL.
    # Renaming its child into fonts preserved the ACL, including its elevated owner.
    # Limit the repair to that descriptor on a verified, byte-identical bundled font.
    script = r"""
$ErrorActionPreference = 'Stop'
$p = $env:INKSTRUCT_REFERENCE_PATH
$acl = [IO.File]::GetAccessControl($p)
$dacl = $acl.GetSecurityDescriptorSddlForm([Security.AccessControl.AccessControlSections]::Access)
if ($dacl.Replace('D:PAI', 'D:P') -eq 'D:P(A;;FA;;;OW)(A;;FA;;;SY)(A;;FA;;;BA)') {
    & "$env:SystemRoot\System32\icacls.exe" $p /reset
    exit $LASTEXITCODE
}
"""
    powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    subprocess.run([str(powershell), "-NoProfile", "-NonInteractive", "-Command", script],
                   env={**os.environ, "INKSTRUCT_REFERENCE_PATH": str(path)}, check=True,
                   creationflags=subprocess.CREATE_NO_WINDOW, stdout=subprocess.DEVNULL)


def install_reference(source, library):
    """Recognize renamed copies and publish without replacing another user's font."""
    source, library = Path(source), Path(library)
    library.mkdir(parents=True, exist_ok=True)
    previous = None
    for path in library.glob("*.inkfont"):
        if is_reference(path):
            try:
                verify(path)
            except (PermissionError, BadZipFile, ValueError, KeyError, TypeError):
                continue
            installed_digest = file_digest(path)
            if installed_digest == file_digest(source):
                if os.name == "nt":
                    _repair_152_acl(path)
                return path
            if installed_digest == HAN_ONLY_SHA256:
                previous = path
                continue
            # A user-owned variant carrying the reference ID remains untouched.
            return path
    if not is_reference(source):
        raise ValueError("安装包中的参考字体无效")
    # Create the file directly in the library to inherit its Windows access rules.
    # The staging suffix keeps incomplete copies out of the font list.
    fd, name = tempfile.mkstemp(dir=library, prefix=".reference-", suffix=".tmp")
    staged = Path(name)
    try:
        with os.fdopen(fd, "wb") as target, source.open("rb") as original:
            shutil.copyfileobj(original, target)
        verify(staged)
        if previous is not None and file_digest(previous) == HAN_ONLY_SHA256:
            os.replace(staged, previous)
            return previous
        checksum = file_digest(staged)
        number = 1
        while True:
            name = REFERENCE_FILE if number == 1 else f"{REFERENCE_NAME} ({number}).inkfont"
            target = library / name
            try:
                if os.name == "nt":
                    os.rename(staged, target)  # Never replaces an existing Windows destination.
                else:
                    os.link(staged, target)
                return target
            except FileExistsError:
                try:
                    if target.is_file() and file_digest(target) == checksum:
                        return target
                except PermissionError:
                    pass  # Leave an unreadable collision intact and choose an available name.
                number += 1
    finally:
        staged.unlink(missing_ok=True)
