"""Build an installer from the verified, version-matched Windows ZIP."""
from __future__ import annotations

import argparse
from hashlib import file_digest
import json
from pathlib import Path
import subprocess
import tempfile
from zipfile import ZipFile

from inkstruct.fonts import APP_VERSION

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def nsis_escape(path):
    return str(path).replace("$", "$$").replace('"', '$\\"')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verification", type=Path, required=True)
    parser.add_argument("--nsis-zip", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    record = json.loads(args.verification.read_bytes())
    archive_path = args.verification.with_name(f"InkStruct-{APP_VERSION}-Windows-x64.zip")
    if record.get("app_version") != APP_VERSION or digest(archive_path) != record.get("archive_sha256"):
        raise ValueError("The verified application ZIP does not match")
    compiler = json.loads((ROOT / "packaging/nsis-win.lock.json").read_bytes())
    if digest(args.nsis_zip) != compiler["sha256"]:
        raise ValueError("NSIS ZIP differs from the compiler lock")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    installer = output / f"InkStruct-{APP_VERSION}-Windows-x64-Installer.exe"
    with tempfile.TemporaryDirectory(dir=output) as directory:
        stage = Path(directory)
        with ZipFile(args.nsis_zip) as archive:
            archive.extractall(stage)
        with ZipFile(archive_path) as archive:
            archive.extractall(stage)
        payload = stage / "InkStruct"
        nsis = stage / f"nsis-{compiler['version']}"
        license_path = payload / "_internal/licenses/runtime/NSIS-COPYING.txt"
        license_path.write_bytes((nsis / "COPYING").read_bytes())
        files = sorted(path.relative_to(payload) for path in payload.rglob("*") if path.is_file())
        folders = sorted({parent for path in files for parent in path.parents if parent != Path(".")},
                         key=lambda path: (-len(path.parts), str(path)))
        remove = stage / "uninstall.nsh"
        directives = [f'Delete "$INSTDIR\\{nsis_escape(path)}"' for path in files]
        directives += [f'RMDir "$INSTDIR\\{nsis_escape(path)}"' for path in folders]
        remove.write_text("\n".join(directives) + "\n", encoding="utf-8-sig")
        defines = {"VERSION": APP_VERSION, "INSTALLER": installer, "PAYLOAD": payload,
                   "APP_ICON": ROOT / "src/inkstruct/editor/resources/inkstruct.ico",
                   "REMOVE_FILES": remove}
        with (output / "nsis-build.log").open("wb") as log:
            subprocess.run([str(nsis / "makensis.exe"), "/V3",
                            *(f"/D{key}={value}" for key, value in defines.items()),
                            str(ROOT / "packaging/InkStruct.nsi")],
                           cwd=nsis, stdout=log, stderr=subprocess.STDOUT, timeout=180, check=True)
    report = {"file": installer.name, "sha256": digest(installer),
              "input_zip_sha256": record["archive_sha256"], "nsis": compiler}
    (output / "installer-build.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
