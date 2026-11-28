"""Install the bundled reference handwriting into the current user's font library."""
import os
from pathlib import Path
import shutil
import tempfile
from zipfile import BadZipFile, ZipFile

from .core import exchange_manifest, package_manifest
from .exchange_codec import verify
from .library import file_digest


REFERENCE_ID = "3e5f7d55-94bc-5265-88b4-12c7c17a17b7"
REFERENCE_NAME = "参考字体"
REFERENCE_FILE = REFERENCE_NAME + ".inkfont"


def is_reference(path):
    try:
        with ZipFile(path) as archive:
            manifest = package_manifest(archive)
            return exchange_manifest(manifest) and manifest.get("font_id") == REFERENCE_ID
    except (BadZipFile, KeyError, ValueError, TypeError, RuntimeError, AttributeError):
        return False


def install_reference(source, library):
    """Recognize renamed/imported copies. Publish atomically without replacing any user's file."""
    source, library = Path(source), Path(library)
    library.mkdir(parents=True, exist_ok=True)
    for path in library.glob("*.inkfont"):
        if is_reference(path):
            try:
                verify(path)
                return path
            except (BadZipFile, ValueError, KeyError, TypeError):
                continue
    if not is_reference(source):
        raise ValueError("安装包中的参考字体无效")
    with tempfile.TemporaryDirectory(dir=library) as directory:
        staged = Path(directory) / REFERENCE_FILE
        shutil.copyfile(source, staged)
        verify(staged)
        checksum = file_digest(staged)
        number = 1
        while True:
            name = REFERENCE_FILE if number == 1 else f"{REFERENCE_NAME} ({number}).inkfont"
            target = library / name
            try:
                if os.name == "nt":
                    os.rename(staged, target)  # On Windows an existing destination is never replaced.
                else:
                    os.link(staged, target)
                return target
            except FileExistsError:
                if target.is_file() and file_digest(target) == checksum:
                    return target
                number += 1
