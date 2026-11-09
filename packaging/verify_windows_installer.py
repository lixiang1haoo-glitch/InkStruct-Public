"""Exercise a per-user installer without registering it on the verification host."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import time
from zipfile import ZipFile

from build_windows_installer import digest
from verify_public_windows import synthetic_font, verify


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installer-build", type=Path, required=True)
    parser.add_argument("--zip", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    record = json.loads(args.installer_build.read_bytes())
    installer = args.installer_build.resolve().with_name(record["file"])
    if digest(installer) != record["sha256"] or digest(args.zip) != record["input_zip_sha256"]:
        raise ValueError("Installer or source ZIP hash does not match the build receipt")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    installed = output / "installed"
    system = Path(os.environ["SystemRoot"])
    env = {**os.environ, "PATH": os.pathsep.join((str(system / "System32"), str(system)))}
    subprocess.run(f'"{installer}" /S /ISOLATED /D={installed}', env=env, cwd=output,
                   timeout=120, check=True, creationflags=subprocess.CREATE_NO_WINDOW)
    with ZipFile(args.zip) as source:
        members = source.namelist()
        for member in members:
            filename = member.removeprefix("InkStruct/")
            if digest(installed / filename) != sha256(source.read(member)).hexdigest():
                raise ValueError(f"Installed file differs from the verified ZIP: {filename}")
    assert (installed / "_internal/licenses/runtime/NSIS-COPYING.txt").is_file()
    font = synthetic_font(output)
    native = verify(installed / "InkStruct.exe", "installed-native", "--windows-style-check", font, output)
    sentinel = installed / "user-files" / "keep.txt"
    sentinel.parent.mkdir()
    sentinel.write_bytes(b"Synthetic data preservation check\n")
    previous = digest(sentinel)
    subprocess.run([str(installed / "Uninstall.exe"), "/S", "/ISOLATED"], env=env, cwd=output,
                   timeout=120, check=True, creationflags=subprocess.CREATE_NO_WINDOW)
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline and (installed / "Uninstall.exe").exists():
        time.sleep(.25)
    remaining = [path for path in installed.rglob("*") if path.is_file()]
    if remaining != [sentinel] or digest(sentinel) != previous:
        raise ValueError(f"Uninstall did not remove only the installed payload: {remaining[:10]}")
    result = {"installer_sha256": record["sha256"], "installed_zip_members_exact": len(members),
              "native": native, "uninstall_preserved_synthetic_user_data": True,
              "shell_integration_skipped_for_isolation": True}
    (output / "installer-verification.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
