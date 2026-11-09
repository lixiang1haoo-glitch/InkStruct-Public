"""Prepare and check the Windows bundle's dependency boundary."""

import subprocess
import sys

import pefile

NUMPY_RUNTIME = b"msvcp140-a4c2229bdc2a2a630acdc095b4d86008.dll"
SYSTEM_RUNTIME = b"msvcp140.dll"


def excluded_binary(name):
    name = name.replace("\\", "/").lower()
    filename = name.rsplit("/", 1)[-1]
    return (
        "virtualkeyboard" in name
        or filename in {
            "ucrtbase.dll", "qopensslbackend.dll", "qjpeg.dll", "opengl32sw.dll",
            "qtpdf.pyd", "qt6pdf.dll", "qt6pdfwidgets.dll", "qpdf.dll", "pdfium.dll",
        }
        or (filename.endswith(".dll") and filename.startswith(
            ("api-ms-win-", "vcruntime", "msvcp", "concrt", "vccorlib", "vcomp")
        ))
    )


def pe_imports(path):
    with pefile.PE(str(path), fast_load=True) as image:
        image.parse_data_directories(directories=[
            pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"],
            pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT"],
        ])
        return {
            entry.dll.lower()
            for directory in ("DIRECTORY_ENTRY_IMPORT", "DIRECTORY_ENTRY_DELAY_IMPORT")
            for entry in getattr(image, directory, ())
        }


def prepare_windows_bundle(bundle, log):
    targets = []
    for path in sorted(bundle.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(bundle).as_posix()
        if excluded_binary(relative):
            raise ValueError(f"Unexpected excluded file in the Windows payload: {relative}")
        if path.suffix.lower() not in {".pyd", ".dll", ".exe"}:
            continue
        if NUMPY_RUNTIME not in pe_imports(path):
            continue
        if not relative.startswith("_internal/numpy/"):
            raise ValueError(f"Unexpected caller of NumPy's private runtime: {relative}")
        subprocess.run(
            [sys.executable, "-m", "delvewheel", "replace-needed", str(path), "-change",
             NUMPY_RUNTIME.decode("ascii"), SYSTEM_RUNTIME.decode("ascii")],
            stdout=log, stderr=subprocess.STDOUT, check=True,
        )
        revised = pe_imports(path)
        if NUMPY_RUNTIME in revised or SYSTEM_RUNTIME not in revised:
            raise ValueError(f"Failed to redirect the Microsoft runtime: {relative}")
        targets.append(relative)
    expected = {"_multiarray_umath.cp313-win_amd64.pyd", "_pocketfft_umath.cp313-win_amd64.pyd"}
    if {path.rsplit("/", 1)[-1] for path in targets} != expected:
        raise ValueError(f"The locked NumPy wheel's runtime import footprint changed: {targets}")
    return {"numpy_system_runtime": SYSTEM_RUNTIME.decode("ascii"), "rewritten": targets}
