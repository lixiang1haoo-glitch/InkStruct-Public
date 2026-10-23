"""Check tracked-file boundaries without reading ignored user data."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_ROOTS = {"handoff", "检查项目", "artifacts", "data", "profiles", "outputs", "workspaces", ".venv", "build", "dist", "release"}
EXCLUDED_SUFFIXES = {".inkreview", ".inkfont", ".inkdoc", ".sqlite3", ".pt", ".pth", ".ckpt", ".apk", ".aab", ".jks", ".keystore"}
SECRET_PATTERNS = (
    re.compile(rb"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})\b"),
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(rb"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{40,}\b"),
)


def main() -> int:
    names = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).split(b"\0")
    errors = []
    checked = 0
    for raw in names:
        if not raw:
            continue
        name = raw.decode("utf-8")
        path = ROOT / name
        environment_file = path.name == ".env" or (path.name.startswith(".env.") and path.name != ".env.example")
        if name.split("/")[0] in EXCLUDED_ROOTS or path.suffix in EXCLUDED_SUFFIXES or environment_file:
            errors.append(f"Excluded tracked path: {name}")
            continue
        if not path.is_file():
            continue
        data = path.read_bytes()
        if len(data) >= 100_000_000:
            errors.append(f"Oversize tracked file: {name}")
        if any(pattern.search(data) for pattern in SECRET_PATTERNS):
            errors.append(f"Potential credential in: {name}")
        checked += 1
    for error in errors:
        print(error)
    print(f"Checked {checked} tracked files; {len(errors)} findings. Pattern checks do not replace content review.")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
